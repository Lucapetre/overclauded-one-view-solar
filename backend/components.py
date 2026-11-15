"""Imported component evidence: immutable snapshots of meters, batteries and irradiance.

`python -m backend import-components --database build/components/component.sqlite` copies the
phase (a) component snapshot (SQLite `backup()`, so committed WAL pages are included) next
to the API database, identifies it by its content identity (input manifest, asset registry,
profile config and engine hashes), and switches every covered provider site to it in one
transaction. A repeat import is a duplicate no-op. Old imports stay on disk (immutable).
Importing never registers new sites and never grants access.

What decisions need is copied into API tables (authoritative grid energy, assets,
capability declarations); bounded per-asset history (battery state, irradiance, evidence)
is read read-only from the snapshot. Rows after the analytical clock are never read.
"""

import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from backend.bridge import (
    SLOT,
    BatteryCapability,
    History,
    MeterSeries,
    pv_history,
)
from backend.clock import clock_state, scenario_now
from backend.component_models import (
    CapabilityDecision,
    EquipmentAsset,
    EquipmentEvidence,
    EquipmentFamily,
    EquipmentSummary,
    EquipmentValue,
    EvidenceItem,
    Freshness,
)
from backend.db import Database, stamp
from backend.errors import ApiError
from backend.models import Metric, User
from backend.offers_math import MeterInterval
from backend.providers import backend_site_id, digest_file, readonly
from backend.security import authorized_site
from backend.solar_forecast import DEFAULT_LOCATION, Sample, solar_position

GRID = {
    "interval_grid_import_kwh": "grid_import",
    "interval_grid_export_kwh": "grid_export",
}
METRIC_NAMES = {Metric.grid_import: "grid_import", Metric.grid_export: "grid_export"}
STALE_AFTER = 2700  # seconds, the provider-site staleness bound
SOC_FRESH = 1800
MAX_EVIDENCE_SPAN = timedelta(days=7)
LABEL = (
    "SYNTHETIC replay evidence. Internal/PCC meters are operational evidence, not certified "
    "billing meters."
)


def _ms(moment: datetime) -> int:
    return int(moment.astimezone(UTC).timestamp() * 1000)


def _iso(text: str | None) -> datetime | None:
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


# ---------------------------------------------------------------- import


def _meta(connection) -> dict:
    try:
        return dict(
            connection.execute("SELECT key, value FROM component_meta").fetchall()
        )
    except sqlite3.OperationalError as exc:
        raise ValueError("The source is not a component snapshot") from exc


def import_component_snapshot(database: Database, source: Path) -> dict:
    """Explicit local import. Atomic per-site switch; never registers sites or grants."""
    database.migrate()
    if source.resolve() == database.path.resolve():
        raise ValueError("The component snapshot must differ from the API database")
    if source.suffix == ".gz":
        raise ValueError("Pass the component SQLite snapshot itself, not a .gz copy")
    with readonly(source) as incoming:
        meta = _meta(incoming)
    if meta.get("snapshot_kind") != "component_snapshot":
        raise ValueError("The source is not a component snapshot")
    identity = "|".join(
        meta.get(key, "")
        for key in (
            "input_manifest_sha256",
            "asset_registry_sha256",
            "config_hash",
            "engine_hash",
            "scenario_version",
            "as_of_utc",
            "families",
        )
    )
    import_id = hashlib.sha256(identity.encode()).hexdigest()
    with database.connect() as connection:
        if connection.execute(
            "SELECT 1 FROM component_imports WHERE import_id=?", (import_id,)
        ).fetchone():
            sites = [
                row[0]
                for row in connection.execute(
                    "SELECT site_id FROM component_sites WHERE import_id=? ORDER BY site_id",
                    (import_id,),
                )
            ]
            return {"status": "duplicate", "import_id": import_id, "sites": sites}
    snapshot_dir = database.path.resolve().parent / "component-snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=snapshot_dir, suffix=".partial")
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with readonly(source) as incoming:
            outgoing = sqlite3.connect(temporary)
            try:
                incoming.backup(outgoing)
            finally:
                outgoing.close()
        with readonly(temporary) as snapshot:
            if _meta(snapshot) != meta:
                raise ValueError("The snapshot changed while it was being copied")
            run = snapshot.execute(
                "SELECT as_of_utc FROM runs WHERE status='completed' "
                "ORDER BY finished_at_utc DESC LIMIT 1"
            ).fetchone()
            if not run:
                raise ValueError("The component snapshot has no completed scraper run")
            registry = snapshot.execute(
                "SELECT site_key, kind, demo_site_key, backend_site_id, json FROM site_registry"
            ).fetchall()
            assets = snapshot.execute(
                "SELECT asset_id, site_key, family, profile_id, source_role, boundary, json "
                "FROM asset_registry"
            ).fetchall()
            capabilities = snapshot.execute(
                "SELECT site_key, capability, declared, state, reason, assets "
                "FROM capability_registry"
            ).fetchall()
            grid = snapshot.execute(
                "SELECT site_key, metric_name, frame_start_utc, frame_end_utc, value_kwh, "
                "value_origin, authority_status, selected_asset_id, selected_endpoint_key, "
                "selected_basis, selected_coverage, reason, mirrors_excluded "
                "FROM authority_frames WHERE boundary='grid_pcc' AND metric_name IN (?,?) "
                "ORDER BY site_key, metric_name, frame_start_ms",
                tuple(GRID),
            ).fetchall()
        sites = {}
        linked: dict[str, list[str]] = {}
        with database.connect() as connection:
            for site_key, kind, demo, site_id, document in registry:
                details = json.loads(document or "{}")
                if kind == "area_resource":
                    if not details.get("test_only"):
                        linked[site_key] = details.get("linked_site_keys", [])
                    continue
                if site_id != backend_site_id(site_key):
                    raise ValueError(f"Site identity mismatch for {site_key}")
                if not connection.execute(
                    "SELECT 1 FROM sites WHERE site_id=?", (site_id,)
                ).fetchone():
                    raise ApiError(
                        409,
                        "provider_sites_missing",
                        "Import the provider snapshot first (import-provider); "
                        f"site {demo or site_key} is not registered",
                    )
                sites[site_key] = (site_id, demo)
        rows_assets = []
        for asset_id, site_key, family, profile_id, role, boundary, document in assets:
            if role != "production" or not family:
                continue  # test-only equivalence encodings are never imported
            details = json.loads(document or "{}")
            mounting = details.get("mounting")
            targets = (
                [(site_key, 0, None)]
                if site_key in sites
                else [
                    (key, 1, "explicitly linked area resource; not electrical topology")
                    for key in linked.get(site_key, [])
                    if key in sites
                ]
            )
            for target, shared, basis in targets:
                rows_assets.append(
                    (
                        import_id,
                        asset_id,
                        sites[target][0],
                        site_key,
                        family,
                        profile_id,
                        boundary,
                        json.dumps(mounting) if mounting else None,
                        shared,
                        basis,
                        json.dumps(_public_details(details), sort_keys=True),
                    )
                )
        rows_capabilities = [
            (
                import_id,
                sites[site_key][0],
                capability,
                int(declared or 0),
                state,
                reason,
                assets_json,
            )
            for site_key, capability, declared, state, reason, assets_json in capabilities
            if site_key in sites
        ]
        rows_grid = []
        for row in grid:
            site_key = row["site_key"] if isinstance(row, sqlite3.Row) else row[0]
            if site_key not in sites:
                continue
            value = row[4]
            if value is not None and value < 0:
                raise ValueError("Directional grid energy must be non-negative")
            rows_grid.append(
                (
                    import_id,
                    sites[site_key][0],
                    GRID[row[1]],
                    stamp(_iso(row[2])),
                    stamp(_iso(row[3])),
                    value,
                    row[5],
                    row[6],
                    row[7],
                    row[8],
                    row[9],
                    row[10],
                    row[11],
                    row[12],
                )
            )
        destination = snapshot_dir / f"{import_id}.sqlite"
        os.replace(temporary, destination)
        with database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute(
                "SELECT 1 FROM component_imports WHERE import_id=?", (import_id,)
            ).fetchone():
                return {"status": "duplicate", "import_id": import_id, "sites": []}
            connection.execute(
                "INSERT INTO component_imports VALUES (?,?,?,?,?,?,?)",
                (
                    import_id,
                    str(destination),
                    stamp(),
                    stamp(_iso(run[0])),
                    meta.get("scenario_version", "unknown"),
                    int(meta.get("synthetic") == "true"),
                    json.dumps(meta, sort_keys=True),
                ),
            )
            connection.executemany(
                "INSERT INTO component_assets VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                rows_assets,
            )
            connection.executemany(
                "INSERT INTO component_capabilities VALUES (?,?,?,?,?,?,?)",
                rows_capabilities,
            )
            connection.executemany(
                "INSERT INTO component_grid_frames VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                rows_grid,
            )
            for site_key, (site_id, demo) in sites.items():
                connection.execute(
                    "INSERT INTO component_sites VALUES (?,?,?,?,?) ON CONFLICT(site_id) DO "
                    "UPDATE SET import_id=excluded.import_id, updated_at=excluded.updated_at",
                    (site_id, site_key, demo, import_id, stamp()),
                )
            database.audit(
                connection,
                "local-admin",
                "component.snapshot.imported",
                import_id,
                "local-import",
                {
                    "sites": len(sites),
                    "assets": len(rows_assets),
                    "grid_frames": len(rows_grid),
                    "scenario_version": meta.get("scenario_version"),
                },
            )
        return {
            "status": "imported",
            "import_id": import_id,
            "scenario_version": meta.get("scenario_version"),
            "sites": sorted(site_id for site_id, _ in sites.values()),
            "assets": len(rows_assets),
            "grid_frames": len(rows_grid),
            "snapshot_sha256": digest_file(destination),
        }
    finally:
        temporary.unlink(missing_ok=True)


PUBLIC_DETAIL_KEYS = (
    "model",
    "phases",
    "pcc_capacity_kw",
    "rated_power_kw",
    "conversion_boundary",
    "declared",
    "declared_nominal_limits",
    "capabilities",
    "mounting",
    "responsible_service",
    "sensors",
    "location",
)


def _public_details(details: dict) -> dict:
    """Asset facts decisions need; no collector paths, unit ids or raw references."""
    return {key: details[key] for key in PUBLIC_DETAIL_KEYS if key in details}


# ---------------------------------------------------------------- lookups


def _active(connection, site_id: str):
    return connection.execute(
        "SELECT cs.site_key, cs.import_id, ci.database_path, ci.scenario_version, "
        "ci.synthetic FROM component_sites cs JOIN component_imports ci USING(import_id) "
        "WHERE cs.site_id=?",
        (site_id,),
    ).fetchone()


def _assets(connection, site_id: str, family: str | None = None) -> list[dict]:
    active = _active(connection, site_id)
    if not active:
        return []
    rows = connection.execute(
        "SELECT * FROM component_assets WHERE import_id=? AND site_id=?"
        + (" AND family=?" if family else "")
        + " ORDER BY shared_resource, asset_id",
        (active["import_id"], site_id, *((family,) if family else ())),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["details"] = json.loads(row["details"])
        item["mounting"] = json.loads(row["mounting"]) if row["mounting"] else None
        result.append(item)
    return result


def _capabilities(connection, site_id: str) -> dict[str, str]:
    active = _active(connection, site_id)
    if not active:
        return {}
    return dict(
        connection.execute(
            "SELECT capability, state FROM component_capabilities WHERE import_id=? AND site_id=?",
            (active["import_id"], site_id),
        ).fetchall()
    )


def _frames(
    connection,
    site_id: str,
    source_site_key: str,
    metric: str,
    start: datetime,
    end: datetime,
    *,
    asset_id: str | None = None,
    aggregation: str | None = None,
    channel: str | None = "any",
    limit: int = 2000,
):
    """Snapshot frames of one series that are complete at `end` (bounded, read-only)."""
    active = _active(connection, site_id)
    if not active or end <= start:
        return []
    clauses = ["site_key=?", "metric_name=?", "frame_start_ms>=?", "frame_start_ms<?"]
    values: list = [source_site_key, metric, _ms(start - SLOT), _ms(end)]
    if asset_id:
        clauses.append("physical_asset_id=?")
        values.append(asset_id)
    if aggregation:
        clauses.append("frame_aggregation=?")
        values.append(aggregation)
    if channel is None:
        clauses.append("channel IS NULL")
    elif channel != "any":
        clauses.append("channel=?")
        values.append(channel)
    with readonly(Path(active["database_path"])) as snapshot:
        rows = snapshot.execute(
            "SELECT * FROM component_frames WHERE "
            + " AND ".join(clauses)
            + " ORDER BY frame_start_ms LIMIT ?",
            (*values, limit),
        ).fetchall()
    return [
        dict(row)
        for row in rows
        if _iso(row["frame_end_utc"]) <= end and _iso(row["frame_start_utc"]) >= start
    ]


def _frame_id(row: dict) -> str:
    return (
        f"frame:{row.get('physical_asset_id') or row['endpoint_key']}:{row['metric_name']}"
        f"{':' + row['channel'] if row.get('channel') else ''}:{row['frame_start_utc']}"
    )


# ---------------------------------------------------------------- bridge hooks


def grid_meter_series(
    connection, site_id: str, metric: Metric, start: datetime, end: datetime
) -> MeterSeries | None:
    """Authoritative PCC meter energy. Only *measured* counter energy is settlement
    evidence; estimated (bounded-hold) frames and unknown frames count as missing."""
    active = _active(connection, site_id)
    if not active or metric not in METRIC_NAMES:
        return None
    if not connection.execute(
        "SELECT 1 FROM component_grid_frames WHERE import_id=? AND site_id=? LIMIT 1",
        (active["import_id"], site_id),
    ).fetchone():
        return None
    series = MeterSeries(metric.value, "component_meter", boundary="grid_pcc")
    if end <= start:
        return series
    rows = connection.execute(
        "SELECT * FROM component_grid_frames WHERE import_id=? AND site_id=? AND metric=? "
        "AND frame_start<? AND frame_end>? AND frame_end<=? ORDER BY frame_start LIMIT 5000",
        (
            active["import_id"],
            site_id,
            METRIC_NAMES[metric],
            stamp(end),
            stamp(start),
            stamp(end),
        ),
    ).fetchall()
    estimated = 0
    for row in rows:
        lower, upper = _iso(row["frame_start"]), _iso(row["frame_end"])
        usable = row["value_kwh"] is not None and row["value_origin"] == "measured"
        if row["value_kwh"] is not None and not usable:
            estimated += 1
        hours = Decimal((upper - lower).total_seconds()) / 3600
        series.intervals.append(
            MeterInterval(
                start=lower,
                end=upper,
                kw=Decimal(str(row["value_kwh"])) / hours if usable else None,
            )
        )
        series.evidence_ids.append(
            f"authority:{row['selected_asset_id'] or 'none'}:{row['metric']}:{row['frame_start']}"
        )
    if estimated:
        series.note = f"{estimated} estimated frame(s) excluded from measured energy"
    return series


def _battery_asset(connection, site_id: str):
    assets = [
        a for a in _assets(connection, site_id, "battery") if not a["shared_resource"]
    ]
    return assets[0] if assets else None


def _ac_battery_samples(connection, site_id, asset, start, end) -> dict:
    """Battery power converted to the AC boundary with declared efficiencies (derived)."""
    declared = asset["details"].get("declared", {})
    eta_c = declared.get("eta_charge_ac_to_storage")
    eta_d = declared.get("eta_discharge_storage_to_ac")
    if not eta_c or not eta_d:
        return {}
    samples = {}
    for row in _frames(
        connection,
        site_id,
        asset["source_site_key"],
        "battery_net_kw",
        start,
        end,
        asset_id=asset["asset_id"],
        aggregation="mean",
    ):
        if row["value"] is None or row["coverage_ratio"] < 0.5:
            continue
        dc = row["value"]  # + discharge / - charge at the DC battery boundary
        samples[_iso(row["frame_start_utc"])] = (
            dc * eta_d if dc >= 0 else dc / eta_c,
            _frame_id(row),
        )
    return samples


def _sun_down(location, moment: datetime) -> bool:
    return all(
        solar_position(*location, moment + SLOT * fraction)[0] <= 0
        for fraction in (0, 0.5, 1)
    )


def derived_load_samples(connection, site_id, start, end) -> list[Sample]:
    """Whole-site load = PCC import - export + AC PV (+ AC-side battery), per 15 minutes."""
    active = _active(connection, site_id)
    if not active:
        return []
    grid = {}
    for row in connection.execute(
        "SELECT metric, frame_start, value_kwh FROM component_grid_frames WHERE import_id=? "
        "AND site_id=? AND frame_start>=? AND frame_end<=? AND value_kwh IS NOT NULL",
        (active["import_id"], site_id, stamp(start), stamp(end)),
    ):
        grid.setdefault(_iso(row["frame_start"]), {})[row["metric"]] = row["value_kwh"]
    if not grid:
        return []
    pv = {
        sample.start: sample
        for sample in pv_history(connection, site_id, start, end).samples
    }
    battery = _battery_asset(connection, site_id)
    battery_ac = (
        _ac_battery_samples(connection, site_id, battery, start, end) if battery else {}
    )
    placement = connection.execute(
        "SELECT latitude, longitude FROM site_placements WHERE site_id=?", (site_id,)
    ).fetchone()
    location = (
        (placement["latitude"], placement["longitude"])
        if placement
        else DEFAULT_LOCATION
    )
    samples = []
    for moment in sorted(grid):
        flows = grid[moment]
        if len(flows) != 2:
            continue
        if moment in pv:
            solar = pv[moment].value
        elif _sun_down(location, moment):
            solar = 0.0  # inverter silent with the sun below the horizon: no AC PV
        else:
            continue
        load = (flows["grid_import"] - flows["grid_export"]) / 0.25 + solar
        evidence = f"derived:load:{stamp(moment)}"
        if battery:
            if moment not in battery_ac:
                continue
            load += battery_ac[moment][0]
        if load < 0:
            continue
        samples.append(Sample(moment, round(load, 4), evidence))
    return samples


def poa_history(connection, site_id, start, end) -> History | None:
    """Recent POA irradiance from the site's own sensor, else an explicitly linked station."""
    for asset in _assets(connection, site_id, "weather"):
        mounting = asset["mounting"] or {}
        if mounting.get("plane") != "poa" or mounting.get("tilt_deg") is None:
            continue  # GHI is never substituted for POA
        rows = _frames(
            connection,
            site_id,
            asset["source_site_key"],
            "irradiance_wm2",
            start,
            end,
            aggregation="mean",
            channel="avg" if asset["shared_resource"] else None,
        )
        samples = [
            Sample(_iso(row["frame_start_utc"]), row["value"], _frame_id(row))
            for row in rows
            if row["value"] is not None
            and row["coverage_ratio"] >= 0.5
            and row.get("mounting") == "poa"
        ]
        history = History(
            samples=samples,
            source=("area_station:" if asset["shared_resource"] else "site_sensor:")
            + asset["asset_id"],
            plane=(
                float(mounting["tilt_deg"]),
                float(mounting.get("azimuth_deg", 180)),
            ),
        )
        if not samples:
            history.reasons.append("no_recent_valid_poa_irradiance")
        return history
    return None


def _latest(connection, site_id, asset, metric, now, channel="any", lookback=6):
    rows = _frames(
        connection,
        site_id,
        asset["source_site_key"],
        metric,
        now - timedelta(hours=lookback),
        now,
        asset_id=asset["asset_id"],
        channel=channel,
    )
    for row in reversed(rows):
        if row["value"] is not None:
            return row
    return None


def battery_capability(connection, site_id, now) -> BatteryCapability | None:
    """Battery-assisted planning decision from imported battery evidence at `now`."""
    from backend.planner import BatteryParams

    asset = _battery_asset(connection, site_id)
    if asset is None:
        return None
    declared_caps = _capabilities(connection, site_id)
    details = asset["details"]
    declared = details.get("declared", {})
    reasons: list[str] = []
    evidence: list[str] = []
    info: dict = {}
    soc_row = _latest(connection, site_id, asset, "soc_pct", now)
    soc = None
    if soc_row and 0 <= soc_row["value"] <= 100:
        observed = _iso(soc_row["value_time_utc"]) or _iso(soc_row["frame_end_utc"])
        info["soc_pct"], info["soc_as_of"] = soc_row["value"], observed
        evidence.append(_frame_id(soc_row))
        if (now - observed).total_seconds() <= SOC_FRESH:
            soc = soc_row["value"]
        else:
            reasons.append("battery_soc_stale")
    else:
        reasons.append("battery_soc_unavailable")
    if declared_caps.get("battery_limits_available") != "available":
        # Energy-only / SoC-only interfaces never imply power capability (B2 case).
        reasons.append("battery_limits_unavailable")
        return BatteryCapability(
            None, reasons + ["grid_solar_only_plan"], evidence, info
        )
    voltage = declared.get("nominal_voltage_v")
    eta_c = declared.get("eta_charge_ac_to_storage")
    eta_d = declared.get("eta_discharge_storage_to_ac")
    reserve = declared.get("reserve_soc_pct")
    rating = declared.get("battery_inverter_rating_kw") or details.get("rated_power_kw")
    capacity_row = _latest(connection, site_id, asset, "battery_capacity_ah", now)
    capacity = None
    if capacity_row and voltage:
        capacity = capacity_row["value"] * voltage / 1000  # reported Ah x nominal V
        evidence.append(_frame_id(capacity_row))
    elif declared.get("capacity_basis_kwh"):
        capacity = declared["capacity_basis_kwh"]
        reasons.append("capacity_from_declared_basis")
    limits = {}
    for metric in ("battery_max_charge_current_a", "battery_max_discharge_current_a"):
        row = _latest(connection, site_id, asset, metric, now)
        if row and (now - _iso(row["frame_end_utc"])).total_seconds() <= SOC_FRESH:
            limits[metric] = row["value"]
            evidence.append(_frame_id(row))
    nominal = details.get("declared_nominal_limits", {})
    if any(
        metric in limits and nominal.get(metric) and limits[metric] < nominal[metric]
        for metric in limits
    ):
        reasons.append("battery_limit_derated_by_bms")
    alarms = []
    for channel in (
        "internal_failure",
        "high_temperature",
        "low_temperature",
        "high_voltage",
        "low_voltage",
        "high_charge_current",
        "high_discharge_current",
        "low_soc",
    ):
        row = _latest(connection, site_id, asset, "battery_alarm_raw", now, channel, 1)
        if row and row["value"] not in (0, 0.0):
            alarms.append(channel)
            evidence.append(_frame_id(row))
    missing = [
        name
        for name, value in (
            ("fresh_soc", soc),
            ("usable_capacity", capacity),
            ("reserve", reserve),
            ("charge_limit", limits.get("battery_max_charge_current_a")),
            ("discharge_limit", limits.get("battery_max_discharge_current_a")),
            ("efficiencies", eta_c and eta_d),
            ("nominal_voltage", voltage),
            ("conversion_boundary", details.get("conversion_boundary")),
        )
        if not value
    ]
    info.update(
        usable_capacity_kwh=round(capacity, 3) if capacity else None,
        reserve_pct=reserve,
        charge_efficiency=eta_c,
        discharge_efficiency=eta_d,
    )
    if alarms:
        reasons += ["battery_alarm_active_restricted"] + [f"alarm_{a}" for a in alarms]
        return BatteryCapability(
            None, reasons + ["grid_solar_only_plan"], evidence, info
        )
    if missing:
        reasons += [f"battery_{name}_missing" for name in missing]
        return BatteryCapability(
            None, reasons + ["grid_solar_only_plan"], evidence, info
        )
    # The minimum of applicable limits on the AC side: BMS DC limits and the inverter rating.
    charge = min(
        limits["battery_max_charge_current_a"] * voltage / 1000 / eta_c, rating or 1e9
    )
    discharge = min(
        limits["battery_max_discharge_current_a"] * voltage / 1000 * eta_d,
        rating or 1e9,
    )
    info.update(
        charge_limit_kw=round(charge, 3), discharge_limit_kw=round(discharge, 3)
    )
    reasons.append("battery_assisted_planning_available")
    params = BatteryParams(
        usable_kwh=capacity,
        soc_pct=soc,
        reserve_pct=reserve,
        charge_limit_kw=charge,
        discharge_limit_kw=discharge,
        charge_efficiency=eta_c,
        discharge_efficiency=eta_d,
        as_of=info.get("soc_as_of"),
        evidence_ids=tuple(evidence),
    )
    return BatteryCapability(params, reasons, evidence, info)


def planning_equipment(connection, site_id) -> dict:
    return {}


def _grid_freshness(connection, site_id, now) -> dict | None:
    active = _active(connection, site_id)
    if not active:
        return None
    latest = connection.execute(
        "SELECT MAX(frame_end) FROM component_grid_frames WHERE import_id=? AND site_id=? "
        "AND frame_end<=? AND value_kwh IS NOT NULL AND value_origin='measured'",
        (active["import_id"], site_id, stamp(now)),
    ).fetchone()[0]
    any_frames = connection.execute(
        "SELECT 1 FROM component_grid_frames WHERE import_id=? AND site_id=? LIMIT 1",
        (active["import_id"], site_id),
    ).fetchone()
    if not any_frames:
        return None
    last = _iso(latest)
    age = (now - last).total_seconds() if last else None
    return {
        "source": "component_pcc_meter",
        "status": "missing"
        if last is None
        else ("fresh" if age <= STALE_AFTER else "stale"),
        "last_observed_at": last,
        "age_seconds": age,
    }


def source_freshness(connection, site_id, now) -> list[dict]:
    result = []
    grid = _grid_freshness(connection, site_id, now)
    if grid:
        result.append(grid)
    battery = _battery_asset(connection, site_id)
    if battery:
        row = _latest(connection, site_id, battery, "soc_pct", now)
        observed = (
            (_iso(row["value_time_utc"]) or _iso(row["frame_end_utc"])) if row else None
        )
        age = (now - observed).total_seconds() if observed else None
        result.append(
            {
                "source": "component_battery",
                "status": "missing"
                if observed is None
                else ("fresh" if age <= SOC_FRESH else "stale"),
                "last_observed_at": observed,
                "age_seconds": age,
            }
        )
    poa = poa_history(connection, site_id, now - timedelta(hours=2), now)
    if poa is not None:
        last = poa.samples[-1].start + SLOT if poa.samples else None
        age = (now - last).total_seconds() if last else None
        result.append(
            {
                "source": "component_irradiance",
                "status": "missing"
                if last is None
                else ("fresh" if age <= STALE_AFTER else "stale"),
                "last_observed_at": last,
                "age_seconds": age,
            }
        )
    return result


def grid_energy_capable(connection, site_id: str) -> bool:
    """Declared authoritative PCC energy for offer gating (consume and export)."""
    return _capabilities(connection, site_id).get("grid_energy_measured") == "available"


# ---------------------------------------------------------------- capability decisions


def capability_decisions(
    connection, site_id: str, now: datetime
) -> list[CapabilityDecision]:
    decisions = []
    grid = _grid_freshness(connection, site_id, now)
    if grid is None:
        decisions.append(
            CapabilityDecision(
                capability="grid_energy_verified",
                available=False,
                reason_codes=["no_authoritative_grid_meter"],
                evidence_ids=[],
            )
        )
    else:
        reasons = ["authoritative_pcc_meter_counter_energy"]
        active = _active(connection, site_id)
        mirrors = connection.execute(
            "SELECT 1 FROM component_grid_frames WHERE import_id=? AND site_id=? "
            "AND mirrors_excluded NOT IN ('[]','') LIMIT 1",
            (active["import_id"], site_id),
        ).fetchone()
        if mirrors:
            reasons.append("gateway_mirror_excluded_not_summed")
        if grid["status"] != "fresh":
            reasons.append(f"grid_meter_{grid['status']}")
        decisions.append(
            CapabilityDecision(
                capability="grid_energy_verified",
                available=grid["status"] == "fresh",
                reason_codes=reasons,
                evidence_ids=[],
            )
        )
    from backend import bridge

    battery = bridge.battery_capability(connection, site_id, now)
    decisions.append(
        CapabilityDecision(
            capability="battery_assisted_planning",
            available=battery.params is not None,
            reason_codes=battery.reason_codes,
            evidence_ids=battery.evidence_ids[:20],
        )
    )
    poa = poa_history(connection, site_id, now - timedelta(hours=1), now)
    if poa is None:
        decisions.append(
            CapabilityDecision(
                capability="irradiance_explanation",
                available=False,
                reason_codes=["no_compatible_irradiance_sensor", "forecast_unchanged"],
                evidence_ids=[],
            )
        )
    else:
        match = module_plane_match(connection, site_id, poa.plane)
        plane_reason = {
            "module_plane": "poa_irradiance_on_registered_plane",
            "differs_from_module_plane": "sensor_plane_differs_from_module_plane",
            "unknown": "poa_sensor_plane_vs_module_plane_unknown",
        }[match]
        decisions.append(
            CapabilityDecision(
                capability="irradiance_explanation",
                available=bool(poa.samples),
                reason_codes=([plane_reason] if poa.samples else [])
                + poa.reasons
                + [poa.source.split(":")[0]],
                evidence_ids=[s.evidence_id for s in poa.samples[-4:] if s.evidence_id],
            )
        )
    decisions.append(_performance_review(connection, site_id, now, poa))
    return decisions


def module_plane_match(connection, site_id: str, plane) -> str:
    """One shared statement: does a POA sensor plane match every module array plane?"""
    placement = connection.execute(
        "SELECT module_arrays FROM site_placements WHERE site_id=?", (site_id,)
    ).fetchone()
    arrays = (
        json.loads(placement["module_arrays"])
        if placement and placement["module_arrays"]
        else []
    )
    if not plane or not arrays:
        return "unknown"
    if any(
        abs(a["tilt"] - plane[0]) > 5 or abs(a["az"] - plane[1]) > 10 for a in arrays
    ):
        return "differs_from_module_plane"
    return "module_plane"


def _performance_review(connection, site_id, now, poa) -> CapabilityDecision:
    reasons = []
    placement = connection.execute(
        "SELECT installed_kwp, module_arrays FROM site_placements WHERE site_id=?",
        (site_id,),
    ).fetchone()
    if not placement or not placement["installed_kwp"]:
        reasons.append("installed_capacity_unknown")
    if poa is None or not poa.plane:
        reasons.append("no_poa_irradiance")
    elif module_plane_match(connection, site_id, poa.plane) != "module_plane":
        reasons.append("sensor_plane_differs_from_module_plane")
    day = now - timedelta(days=1)
    production = pv_history(connection, site_id, day, now)
    if not production.samples:
        reasons.append("no_ac_production_boundary_data")
    elif poa is not None:
        daylight = [
            s
            for s in (poa_history(connection, site_id, day, now) or poa).samples
            if s.value > 50
        ]
        if len(daylight) < 24:
            reasons.append("insufficient_valid_daylight_coverage")
    return CapabilityDecision(
        capability="pv_performance_review",
        available=not reasons,
        reason_codes=reasons or ["inputs_complete_numeric_review_possible"],
        evidence_ids=[],
    )


# ---------------------------------------------------------------- equipment API

ROLES = {
    "meter": "authoritative_pcc_meter",
    "battery": "battery_monitoring",
    "weather": "irradiance_sensor",
}
SUMMARY_METRICS = {
    "meter": [("grid_net_kw", "mean", None)],
    "battery": [
        ("soc_pct", "last_valid", None),
        ("battery_net_kw", "mean", None),
        ("battery_max_discharge_current_a", "last_valid", None),
        ("battery_max_charge_current_a", "last_valid", None),
    ],
    "weather": [
        ("irradiance_wm2", "mean", "any"),
        ("module_temperature_c", "mean", None),
        ("ambient_temperature_c", "mean", None),
    ],
}


def _value(row: dict) -> EquipmentValue:
    return EquipmentValue(
        metric=row["metric_name"],
        channel=row.get("channel"),
        value=row["value"],
        unit=row["unit"],
        observed_at=_iso(row.get("value_time_utc")),
        frame_start=_iso(row["frame_start_utc"]),
        frame_end=_iso(row["frame_end_utc"]),
        aggregation=row["frame_aggregation"],
        origin=row.get("value_origin") or "unknown",
        coverage_ratio=row["coverage_ratio"] or 0.0,
        evidence_id=_frame_id(row),
    )


def equipment_summary(connection, user: User, site_id: str) -> EquipmentSummary:
    authorized_site(connection, user, site_id)
    state = clock_state(connection)
    now = state.now
    active = _active(connection, site_id)
    declared = _capabilities(connection, site_id)
    families = []
    for family in ("meter", "battery", "weather"):
        assets = _assets(connection, site_id, family)
        latest = []
        for asset in assets:
            for metric, aggregation, channel in SUMMARY_METRICS[family]:
                rows = _frames(
                    connection,
                    site_id,
                    asset["source_site_key"],
                    metric,
                    now - timedelta(hours=3),
                    now,
                    asset_id=asset["asset_id"],
                    aggregation=aggregation,
                    channel="avg"
                    if channel == "any" and asset["shared_resource"]
                    else channel,
                )
                valid = [r for r in rows if r["value"] is not None]
                if valid:
                    latest.append(_value(valid[-1]))
        last = max((value.frame_end for value in latest), default=None)
        age = (now - last).total_seconds() if last else None
        notes = []
        selected = None
        if family == "meter" and assets:
            grid = _grid_freshness(connection, site_id, now)
            if grid and grid["last_observed_at"]:
                last, age = grid["last_observed_at"], grid["age_seconds"]
            selected = next(
                (
                    row[0]
                    for row in connection.execute(
                        "SELECT selected_asset_id FROM component_grid_frames WHERE import_id=? "
                        "AND site_id=? AND frame_end<=? AND selected_asset_id IS NOT NULL "
                        "ORDER BY frame_start DESC LIMIT 1",
                        (active["import_id"], site_id, stamp(now)),
                    )
                ),
                assets[0]["asset_id"],
            )
            notes.append(
                "Authoritative grid energy comes from one selected meter per interval; "
                "gateway mirrors stay evidence and are never added."
            )
        elif assets:
            selected = assets[0]["asset_id"]
        if family == "weather" and any(a["shared_resource"] for a in assets):
            notes.append(
                "Shared area station explicitly linked to this site; not a topology claim."
            )
        relevant = {
            key: value
            for key, value in declared.items()
            if key.startswith(
                {"meter": "grid", "battery": "battery", "weather": "irradiance"}[family]
            )
            or (family == "meter" and key == "pcc_phase_voltage")
            or (family == "weather" and key.endswith("temperature_available"))
        }
        families.append(
            EquipmentFamily(
                family=family,
                availability="not_installed"
                if not assets
                else ("available" if latest else "declared_not_observed"),
                selected_source=selected,
                assets=[
                    EquipmentAsset(
                        asset_id=a["asset_id"],
                        profile_id=a["profile_id"],
                        role=ROLES[family],
                        boundary=a["boundary"],
                        mounting=(a["mounting"] or {}).get("plane"),
                        shared_resource=bool(a["shared_resource"]),
                        link_basis=a["link_basis"],
                        plane_match=module_plane_match(
                            connection,
                            site_id,
                            (
                                a["mounting"].get("tilt_deg"),
                                a["mounting"].get("azimuth_deg", 180),
                            )
                            if a["mounting"]
                            and a["mounting"].get("plane") == "poa"
                            and a["mounting"].get("tilt_deg") is not None
                            else None,
                        )
                        if family == "weather"
                        else None,
                    )
                    for a in assets
                ],
                latest=latest,
                freshness=Freshness(
                    status="missing"
                    if last is None
                    else ("fresh" if age <= STALE_AFTER else "stale"),
                    last_observed_at=last,
                    age_seconds=age,
                    stale_after_seconds=STALE_AFTER,
                ),
                declared_capabilities=relevant,
                notes=notes,
            )
        )
    return EquipmentSummary(
        site_id=site_id,
        as_of=now,
        clock_mode=state.mode,
        source_mode=("synthetic" if active["synthetic"] else "replay")
        if active
        else "none",
        scenario_version=active["scenario_version"] if active else None,
        import_id=active["import_id"] if active else None,
        families=families,
        capabilities=capability_decisions(connection, site_id, now),
        label=LABEL,
    )


def equipment_evidence(
    connection,
    user: User,
    site_id: str,
    family: str | None,
    start: datetime,
    end: datetime,
    metric: str | None,
    limit: int,
    offset: int,
) -> EquipmentEvidence:
    if end <= start or end - start > MAX_EVIDENCE_SPAN:
        raise ApiError(
            422, "invalid_time_range", "Use a positive time range of at most 7 days"
        )
    authorized_site(connection, user, site_id)
    now = clock_state(connection).now
    known = scenario_now(connection)
    upper = min(end, known) if known else end
    active = _active(connection, site_id)
    items: list[EvidenceItem] = []
    total = 0
    if active and upper > start:
        assets = [
            a for a in _assets(connection, site_id) if family in (None, a["family"])
        ]
        clauses = []
        values: list = []
        for asset in assets:
            clauses.append("(site_key=? AND physical_asset_id=?)")
            values += [asset["source_site_key"], asset["asset_id"]]
        if clauses:
            where = (
                "("
                + " OR ".join(clauses)
                + ") AND frame_start_ms>=? AND frame_start_ms<? "
                "AND frame_start_ms+900000<=?"
            )
            values += [_ms(start), _ms(upper), _ms(upper)]
            if metric:
                where += " AND metric_name=?"
                values.append(metric)
            with readonly(Path(active["database_path"])) as snapshot:
                total = snapshot.execute(
                    "SELECT COUNT(*) FROM component_frames WHERE " + where, values
                ).fetchone()[0]
                rows = snapshot.execute(
                    "SELECT * FROM component_frames WHERE "
                    + where
                    + " ORDER BY frame_start_ms, physical_asset_id, metric_name, channel, "
                    "frame_aggregation LIMIT ? OFFSET ?",
                    (*values, limit, offset),
                ).fetchall()
            items = [
                EvidenceItem(
                    evidence_id=_frame_id(dict(row)),
                    asset_id=row["physical_asset_id"],
                    family=row["family"],
                    endpoint_key=row["endpoint_key"],
                    metric=row["metric_name"],
                    channel=row["channel"],
                    boundary=row["boundary"],
                    mounting=row["mounting"],
                    aggregation=row["frame_aggregation"],
                    basis=row["basis"],
                    frame_start=_iso(row["frame_start_utc"]),
                    frame_end=_iso(row["frame_end_utc"]),
                    value=row["value"],
                    unit=row["unit"],
                    coverage_ratio=row["coverage_ratio"] or 0.0,
                    value_origin=row["value_origin"],
                    frame_status=row["frame_status"],
                )
                for row in rows
            ]
    return EquipmentEvidence(
        site_id=site_id,
        family=family,
        as_of=now,
        total=total,
        limit=limit,
        offset=offset,
        items=items,
    )


__all__ = [
    "battery_capability",
    "capability_decisions",
    "derived_load_samples",
    "equipment_evidence",
    "equipment_summary",
    "grid_energy_capable",
    "grid_meter_series",
    "import_component_snapshot",
    "planning_equipment",
    "poa_history",
    "source_freshness",
]
