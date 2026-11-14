"""Read-only bridge from phase 1's canonical SQLite and exported frames to scoped APIs.

Canonical values, timestamps, channels and requirements remain in their original vocabulary.
They are never flattened into the earlier, smaller demo energy contract.
"""

import csv
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.db import Database, stamp
from backend.errors import ApiError
from backend.models import Metric, Site, SiteRegistration, User
from backend.provider_models import (
    ProviderFrame,
    ProviderFrames,
    ProviderLatest,
    ProviderObservation,
    ProviderObservations,
    ProviderSite,
    ProviderSourceHealth,
)
from backend.provisioning import register_site
from backend.security import accessible_sites, authorized_site

# Only exact, interpretable correspondences describe the compact demo capabilities.
# Detailed frontend values always come from the canonical endpoints below.
CAPABILITIES = {
    "pv_ac_kw": Metric.pv,
    "pv_dc_kw": Metric.pv,
    "pv_production_kw": Metric.pv,
    "grid_import_kw": Metric.grid_import,
    "grid_export_kw": Metric.grid_export,
    "household_load_kw": Metric.load,
    "battery_charge_kw": Metric.battery_charge,
    "battery_discharge_kw": Metric.battery_discharge,
    "soc_pct": Metric.soc,
    "inverter_temperature_c": Metric.temperature,
    "ac_voltage_v": Metric.voltage,
}


def backend_site_id(site_key: str) -> str:
    return "provider-" + hashlib.sha256(site_key.encode()).hexdigest()[:24]


@contextmanager
def readonly(path: Path):
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.OperationalError as exc:
        raise ApiError(
            503,
            "provider_snapshot_unavailable",
            "The imported provider snapshot is unavailable",
        ) from exc
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
        yield connection
    finally:
        connection.close()


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def import_provider_snapshot(
    database: Database, source: Path, sites_path: Path, frames_path: Path
) -> dict:
    """Explicit local import. Snapshot replacement is atomic and never creates access grants."""
    database.migrate()
    if source.resolve() == database.path.resolve():
        raise ValueError(
            "The source scraper database must differ from the API database"
        )
    document = json.loads(sites_path.read_text(encoding="utf-8"))
    snapshot_dir = database.path.resolve().parent / "provider-snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=snapshot_dir, suffix=".partial")
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        if source.suffix == ".gz":
            with gzip.open(source, "rb") as incoming, temporary.open("wb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)
        else:
            with readonly(source) as incoming:
                outgoing = sqlite3.connect(temporary)
                try:
                    incoming.backup(outgoing)
                finally:
                    outgoing.close()
        # Hash the complete, consistent SQLite backup, including committed WAL pages.
        import_id = hashlib.sha256(
            "|".join(
                digest_file(path) for path in (temporary, sites_path, frames_path)
            ).encode()
        ).hexdigest()
        destination = snapshot_dir / f"{import_id}.sqlite"
        with database.connect() as connection:
            if connection.execute(
                "SELECT 1 FROM provider_imports WHERE import_id=?", (import_id,)
            ).fetchone():
                identities = [
                    json.loads(row[0])
                    for row in connection.execute(
                        "SELECT identity FROM provider_sites WHERE import_id=? ORDER BY site_id",
                        (import_id,),
                    )
                ]
                return {
                    "status": "duplicate",
                    "import_id": import_id,
                    "sites": identities,
                }
        with readonly(temporary) as incoming:
            run = incoming.execute(
                "SELECT as_of_utc FROM runs WHERE status='completed' ORDER BY finished_at_utc DESC LIMIT 1"
            ).fetchone()
            if not run:
                raise ValueError("Source database has no completed scraper run")
            as_of = datetime.fromisoformat(run[0].replace("Z", "+00:00"))
            if as_of.tzinfo is None:
                raise ValueError("The scraper replay clock must include a timezone")
            known = {
                row[0]
                for row in incoming.execute(
                    "SELECT site_key FROM canonical_observations UNION SELECT site_key FROM source_health"
                )
            }
            sites = {}
            for site in document["sites"]:
                key = "|".join(
                    str(site[name]) for name in ("provider", "account_id", "site_id")
                )
                if key not in known:
                    continue
                if key in sites:
                    raise ValueError("Duplicate site binding in sites.json")
                site_id = backend_site_id(key)
                identity = ProviderSite(
                    site_id=site_id,
                    site_key=key,
                    provider=site["provider"],
                    account_id=str(site["account_id"]),
                    native_site_id=str(site["site_id"]),
                    display_name=site.get("display_name", site_id),
                    provider_profile_id=site["provider_profile_id"],
                    capabilities=site.get("capabilities", {}),
                    source_mode="synthetic"
                    if document.get("synthetic") is True
                    else "replay",
                    as_of_utc=as_of,
                )
                metrics = incoming.execute(
                    "SELECT DISTINCT metric_name,requirement_class FROM observations WHERE site_key=?",
                    (key,),
                ).fetchall()
                requirements = {}
                for metric, classification in metrics:
                    mapped = CAPABILITIES.get(metric)
                    if mapped:
                        requirement = (
                            "optional" if classification == "optional" else "mandatory"
                        )
                        if requirements.get(mapped) != "mandatory":
                            requirements[mapped] = requirement
                # A site may expose only metrics outside the compact energy vocabulary.
                # Do not fabricate a PV capability to make that contract fit.
                registration = SiteRegistration(
                    site=Site(
                        site_id=site_id,
                        alias=identity.display_name[:128],
                        area_id=None,
                        topology_mode="unknown",
                        reporting_interval_seconds=900,
                        stale_after_seconds=2700,
                        capabilities=list(requirements),
                        measurement_requirements=requirements,
                    ),
                    device_id="stream-" + site_id,
                    source_id="phase1-scraper",
                )
                sites[key] = (identity, registration)
            if set(sites) != known:
                raise ValueError(
                    "sites.json does not cover every identity in the scraper snapshot"
                )
            frames = []
            with frames_path.open(encoding="utf-8-sig", newline="") as stream:
                for row in csv.DictReader(stream):
                    for name in ("value", "device_id", "channel", "original_cadence_s"):
                        if row[name] == "":
                            row[name] = None
                    frame = ProviderFrame.model_validate(row)
                    if frame.site_key not in sites:
                        raise ValueError(
                            "Frame references a site outside the source snapshot"
                        )
                    identity = sites[frame.site_key][0]
                    if (frame.provider, frame.account_id, frame.site_id) != (
                        identity.provider,
                        identity.account_id,
                        identity.native_site_id,
                    ):
                        raise ValueError(
                            "Frame identity differs from the registered source binding"
                        )
                    if (
                        frame.frame_start_utc.tzinfo is None
                        or frame.frame_end_utc.tzinfo is None
                        or frame.frame_end_utc <= frame.frame_start_utc
                    ):
                        raise ValueError(
                            "Frames need positive, timezone-aware intervals"
                        )
                    frames.append(
                        (
                            import_id,
                            identity.site_id,
                            frame.endpoint_key,
                            frame.device_id or "",
                            frame.channel or "",
                            frame.metric_name,
                            stamp(frame.frame_start_utc),
                            stamp(frame.frame_end_utc),
                            frame.model_dump_json(),
                        )
                    )
        # Registering a site grants nobody access. Repeated registration verifies its contract.
        for _, registration in sites.values():
            register_site(database, registration)
        os.replace(temporary, destination)
        with database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO provider_imports VALUES (?,?,?,?,?)",
                (
                    import_id,
                    str(destination),
                    stamp(),
                    stamp(as_of),
                    int(document.get("synthetic") is True),
                ),
            )
            connection.executemany(
                "INSERT INTO provider_frames VALUES (?,?,?,?,?,?,?,?,?)", frames
            )
            for identity, _ in sites.values():
                connection.execute(
                    "INSERT INTO provider_sites VALUES (?,?,?,?) ON CONFLICT(site_id) DO UPDATE SET import_id=excluded.import_id,identity=excluded.identity",
                    (
                        identity.site_id,
                        identity.site_key,
                        import_id,
                        identity.model_dump_json(),
                    ),
                )
            database.audit(
                connection,
                "local-admin",
                "provider.snapshot.imported",
                import_id,
                "local-import",
            )
        return {
            "status": "imported",
            "import_id": import_id,
            "frames": len(frames),
            "sites": [
                identity.model_dump(mode="json") for identity, _ in sites.values()
            ],
        }
    finally:
        temporary.unlink(missing_ok=True)


def provider_sites(connection, user: User) -> list[ProviderSite]:
    permitted = {row["site_id"] for row in accessible_sites(connection, user)}
    return [
        ProviderSite.model_validate_json(row["identity"])
        for row in connection.execute(
            "SELECT site_id,identity FROM provider_sites ORDER BY site_id"
        )
        if row["site_id"] in permitted
    ]


def binding(connection, user: User, site_id: str):
    authorized_site(connection, user, site_id)
    row = connection.execute(
        "SELECT ps.*,pi.database_path FROM provider_sites ps JOIN provider_imports pi USING(import_id) WHERE site_id=?",
        (site_id,),
    ).fetchone()
    if not row:
        raise ApiError(404, "not_found", "Resource not found")
    return row, ProviderSite.model_validate_json(row["identity"])


def provider_latest(connection, user: User, site_id: str) -> ProviderLatest:
    row, identity = binding(connection, user, site_id)
    frames = connection.execute(
        "SELECT payload FROM (SELECT payload,ROW_NUMBER() OVER (PARTITION BY endpoint_key,device_id,channel,metric_name ORDER BY frame_start DESC) AS rank "
        "FROM provider_frames WHERE site_id=? AND import_id=?) WHERE rank=1",
        (site_id, row["import_id"]),
    ).fetchall()
    with readonly(Path(row["database_path"])) as source:
        fields = ",".join(ProviderSourceHealth.model_fields)
        health = [
            ProviderSourceHealth.model_validate(dict(item))
            for item in source.execute(
                f"SELECT {fields} FROM source_health WHERE site_key=? ORDER BY endpoint_key,device_key",
                (row["site_key"],),
            )
        ]
    return ProviderLatest(
        site=identity,
        frames=[ProviderFrame.model_validate_json(item["payload"]) for item in frames],
        source_health=health,
    )


def provider_history(
    connection,
    user: User,
    site_id: str,
    start: datetime,
    end: datetime,
    metric: str | None,
    endpoint: str | None,
    device: str | None,
    channel: str | None,
    limit: int,
    offset: int,
    *,
    observations: bool,
):
    if end <= start or end - start > timedelta(days=31):
        raise ApiError(
            422,
            "invalid_time_range",
            "Use a positive time range of at most 31 elapsed days",
        )
    row, identity = binding(connection, user, site_id)
    filters = []
    values = []
    for column, value in (
        ("metric_name", metric),
        ("endpoint_key", endpoint),
        ("device_id", device),
        ("channel", channel),
    ):
        if value is not None:
            filters.append(f"{column}=?")
            values.append(value)
    suffix = "".join(" AND " + clause for clause in filters)
    if observations:
        # ISO strings in the upstream view always use UTC milliseconds and a Z suffix.
        def source_stamp(value):
            return (
                value.astimezone(UTC)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z")
            )

        base = (
            " FROM canonical_observations WHERE site_key=? AND effective_time_utc>=? AND effective_time_utc<?"
            + suffix
        )
        arguments = [row["site_key"], source_stamp(start), source_stamp(end), *values]
        with readonly(Path(row["database_path"])) as source:
            total = source.execute("SELECT COUNT(*)" + base, arguments).fetchone()[0]
            fields = ",".join(ProviderObservation.model_fields)
            items = [
                ProviderObservation.model_validate(dict(item))
                for item in source.execute(
                    "SELECT "
                    + fields
                    + base
                    + " ORDER BY effective_time_utc,obs_id LIMIT ? OFFSET ?",
                    [*arguments, limit, offset],
                )
            ]
        return ProviderObservations(
            site=identity, total=total, limit=limit, offset=offset, items=items
        )
    base = (
        " FROM provider_frames WHERE site_id=? AND import_id=? AND frame_start<? AND frame_end>?"
        + suffix
    )
    arguments = [site_id, row["import_id"], stamp(end), stamp(start), *values]
    total = connection.execute("SELECT COUNT(*)" + base, arguments).fetchone()[0]
    items = [
        ProviderFrame.model_validate_json(item[0])
        for item in connection.execute(
            "SELECT payload"
            + base
            + " ORDER BY frame_start,endpoint_key,device_id,channel,metric_name LIMIT ? OFFSET ?",
            [*arguments, limit, offset],
        )
    ]
    return ProviderFrames(
        site=identity, total=total, limit=limit, offset=offset, items=items
    )
