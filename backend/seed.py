"""Idempotent SYNTHETIC demo: Bucharest Sectors 1-6 and Ilfov, ~60 fictional sites.

Sites, profiles and clusters come from `backend/fixtures/site_profiles.json`.
Telemetry special cases (all in Sector 6 unless noted, on the replay clock):

- s6-01 (customer's home): full record, the compact telemetry example
- s6-02: stale feed (last interval ended 75 minutes before the replay clock)
- s6-03: registered but no telemetry at all
- s6-04: only the mandatory PV value is reported
- s6-09: mandatory PV value missing
- s3-01 (Sector 3): battery state of charge only; s3-02: SoC plus battery power
"""

import json
import secrets
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.db import Database, stamp
from backend.errors import ApiError
from backend.ingestion import ingest
from backend.models import Metric
from backend.offers import publish
from backend.ops import open_incident, profile_source
from backend.security import hash_password

REPLAY_AT = datetime(2026, 7, 15, 12, 15, tzinfo=UTC)
SHIFT = "08:00-18:00"
# Areas of the retired three-area demo; such a database must be recreated, not mixed.
LEGACY_AREAS = ("north", "central", "south")
NO_TELEMETRY = "s6-03"
STALE = "s6-02"
PV_ONLY = "s6-04"
PV_MISSING = "s6-09"
SOC_ONLY = "s3-01"
BATTERY = "s3-02"
SKILLS = [
    "Production",
    "Temperature",
    "Telemetry",
    "Voltage",
    "Area event",
    "Local issue",
    "Other",
]
# (crew_id, name, area, members): one crew per area with every technical skill.
CREWS = (
    ("sector-1-solar-care", "Sector 1 Solar Care", "sector-1", ["technician-s1"]),
    ("sector-2-solar-care", "Sector 2 Solar Care", "sector-2", ["technician-s2"]),
    ("sector-3-solar-care", "Sector 3 Solar Care", "sector-3", ["technician-s3"]),
    ("sector-4-solar-care", "Sector 4 Solar Care", "sector-4", ["technician-s4"]),
    ("sector-5-solar-care", "Sector 5 Solar Care", "sector-5", ["technician-s5"]),
    ("sector-6-solar-care", "Sector 6 Solar Care", "sector-6", ["technician"]),
    ("ilfov-field-service", "Ilfov Field Service", "ilfov", ["technician-ilfov"]),
)
# (username, role, account_type, site grants, area grants)
ACCOUNTS = (
    ("customer", "customer", "home", ["s6-01"], []),
    ("other-customer", "customer", "home", ["s4-01"], []),
    ("business-customer", "customer", "business", ["s3-06"], []),
    ("dispatcher", "dispatcher", "home", [], ["sector-6"]),
    ("technician", "technician", "home", ["s6-01", "s6-02"], []),
    *(
        (f"technician-{suffix}", "technician", "home", [], [])
        for suffix in ("s1", "s2", "s3", "s4", "s5", "ilfov")
    ),
    ("area-manager", "supervisor", "home", [], ["sector-6"]),
    (
        "supervisor",
        "supervisor",
        "home",
        [],
        [f"sector-{n}" for n in range(1, 7)] + ["ilfov"],
    ),
)
POLICY = "Synthetic demo policy rule on replayed demo data; not an equipment diagnosis."
# (incident_id, site, tier, family, title, evidence, minutes before the replay clock)
INCIDENTS = (
    (
        "demo-inc-s3-04-area",
        "s3-04",
        "P0",
        "Area event",
        "Synthetic area event: several demo feeds dropped together",
        "Replay policy marks a simultaneous drop across demo feeds near this site.",
        50,
    ),
    (
        "demo-inc-s6-09-production",
        PV_MISSING,
        "P1",
        "Production",
        "Synthetic rule: mandatory PV value missing in the latest interval",
        "The latest replayed record reports PV power as missing.",
        95,
    ),
    (
        "demo-inc-s3-09-voltage",
        "s3-09",
        "P1",
        "Voltage",
        "Synthetic voltage-band policy flag",
        "Replay policy flags a demo voltage value outside its configured band.",
        80,
    ),
    (
        "demo-inc-s4-07-temperature",
        "s4-07",
        "P1",
        "Temperature",
        "Synthetic temperature-threshold policy flag",
        "Replay policy flags a demo temperature value above its configured threshold.",
        70,
    ),
    (
        "demo-inc-ilfov-01-voltage",
        "ilfov-01",
        "P1",
        "Voltage",
        "Synthetic voltage-band policy flag",
        "Replay policy flags a demo voltage value outside its configured band.",
        40,
    ),
    (
        "demo-inc-s6-02-telemetry",
        STALE,
        "P2",
        "Telemetry",
        "Synthetic rule: demo feed is stale",
        "The latest replayed interval ended more than 30 minutes before the replay clock.",
        60,
    ),
    (
        "demo-inc-s4-06-production",
        "s4-06",
        "P2",
        "Production",
        "Synthetic rule: production below the demo expectation band",
        "Replay policy compares PV power with a fixed demo band for this profile.",
        45,
    ),
    (
        "demo-inc-s1-10-temperature",
        "s1-10",
        "P2",
        "Temperature",
        "Synthetic temperature-threshold policy flag",
        "Replay policy flags a demo temperature value above its configured threshold.",
        35,
    ),
    (
        "demo-inc-s6-03-telemetry",
        NO_TELEMETRY,
        "P3",
        "Telemetry",
        "Synthetic rule: no telemetry received for this demo site",
        "The registered demo site has no replayed record.",
        120,
    ),
    (
        "demo-inc-s5-01-local",
        "s5-01",
        "P3",
        "Local issue",
        "Synthetic follow-up: scheduled demo inspection reminder",
        "Replay policy schedules a periodic demo inspection reminder.",
        30,
    ),
    (
        "demo-inc-s2-04-local",
        "s2-04",
        "P3",
        "Local issue",
        "Synthetic follow-up: scheduled demo inspection reminder",
        "Replay policy schedules a periodic demo inspection reminder.",
        25,
    ),
)
PROFILE_FIELDS = (
    "latitude",
    "longitude",
    "zone",
    "character",
    "segment",
    "business_type",
    "installed_kwp",
    "monthly_import_kwh",
    "monthly_export_kwh",
    "service_fee_ron",
    "cluster",
)


def seed_operations(connection):
    """Synthetic site profiles, crews and incidents. Idempotent."""
    for profile in profile_source()["profiles"]:
        connection.execute(
            f"INSERT OR IGNORE INTO site_profiles(site_id,{','.join(PROFILE_FIELDS)}) "
            f"SELECT ?,{','.join('?' * len(PROFILE_FIELDS))} "
            "WHERE EXISTS (SELECT 1 FROM sites WHERE site_id=?)",
            (
                profile["site_id"],
                *(profile.get(field) for field in PROFILE_FIELDS),
                profile["site_id"],
            ),
        )
    for crew_id, name, area, members in CREWS:
        connection.execute(
            "INSERT OR IGNORE INTO crews(crew_id,name,area_id,skills,shift) VALUES (?,?,?,?,?)",
            (crew_id, name, area, json.dumps(SKILLS), SHIFT),
        )
        for member in members:
            connection.execute(
                "INSERT OR IGNORE INTO crew_members(crew_id,user_id) "
                "SELECT ?, user_id FROM users WHERE username=?",
                (crew_id, member),
            )
    for incident_id, site_id, tier, family, title, evidence, minutes in INCIDENTS:
        opened = stamp(REPLAY_AT - timedelta(minutes=minutes))
        open_incident(
            connection,
            incident_id=incident_id,
            site_id=site_id,
            title=title,
            family=family,
            tier=tier,
            source="synthetic_replay",
            evidence=f"{evidence} {POLICY}",
            actor="system",
            detail="Opened by the synthetic replay policy",
            now=opened,
        )


# Power Block Offers by the supervisor in area sector-6: two published, one draft.
OFFER_AREA = "sector-6"
DEMO_OFFERS = (
    (
        "demo-offer-s6-consume",
        True,
        (
            "consume",
            "Midday solar surplus",
            "10",
            "0.55",
            120,
            "per_unfulfilled_kwh",
            "0.3",
        ),
    ),
    (
        "demo-offer-s6-export",
        True,
        (
            "export",
            "Evening peak support",
            "10",
            "0.7",
            120,
            "percent_of_unfulfilled_value",
            "20",
        ),
    ),
    (
        "demo-offer-s6-draft",
        False,
        ("consume", "Weekend load shift", "5", "0.45", 60, "flat", "5"),
    ),
)
OFFER_FIELDS = (
    "type",
    "title",
    "energy_kwh",
    "offer_price_ron_per_kwh",
    "window_minutes",
    "penalty_type",
    "penalty_value",
)


def seed_offers(database: Database, connection):
    """Demo offers expiring 7 days after seeding (wall clock). Idempotent; no acceptances."""
    now = datetime.now(UTC)
    for offer_id, published, terms in DEMO_OFFERS:
        offer = dict(zip(OFFER_FIELDS, terms, strict=True)) | {
            "offer_id": offer_id,
            "offer_expires_at": stamp(now + timedelta(days=7)),
            "area_id": OFFER_AREA,
            "status": "draft",
            "target_mode": "all",
            "created_by": "supervisor",
            "created_at": stamp(now),
            "updated_at": stamp(now),
        }
        columns = list(offer)
        if not connection.execute(
            f"INSERT OR IGNORE INTO offers({','.join(columns)}) "
            f"SELECT {','.join('?' * len(columns))} "
            "WHERE EXISTS (SELECT 1 FROM users WHERE user_id='supervisor')",
            [offer[column] for column in columns],
        ).rowcount:
            continue
        database.audit(
            connection,
            "supervisor",
            "offer.created",
            offer_id,
            "seed-demo",
            {"seed": True},
        )
        if published:
            offer |= {
                "target_segment": None,
                "target_min_kwp": None,
                "target_zone": None,
            }
            publish(database, connection, offer, "supervisor", "seed-demo", now)


def _capabilities(site_id: str) -> list[str]:
    capabilities = [
        Metric.pv.value,
        Metric.load.value,
        Metric.grid_import.value,
        Metric.grid_export.value,
    ]
    if site_id in (SOC_ONLY, BATTERY):
        capabilities.append(Metric.soc.value)
    if site_id == BATTERY:
        capabilities += [Metric.battery_charge.value, Metric.battery_discharge.value]
    return capabilities


def _refuse_legacy_geography(connection, database: Database):
    legacy = connection.execute(
        f"SELECT area_id FROM areas WHERE area_id IN ({','.join('?' * len(LEGACY_AREAS))})",
        LEGACY_AREAS,
    ).fetchall()
    if legacy:
        raise ApiError(
            409,
            "legacy_demo_geography",
            "This database was seeded with the retired three-area demo geography "
            f"({', '.join(row['area_id'] for row in legacy)}). The demo now uses "
            "Bucharest Sectors 1-6 and Ilfov. It only holds synthetic demo data: delete "
            f"{database.path} (with its -wal and -shm files) and run seed-demo again.",
        )


def _telemetry(base: dict, site_id: str) -> dict:
    record = deepcopy(base)
    record.update(
        site_id=site_id,
        device_id=f"meter-{site_id}",
        record_id=f"{site_id}-20260715T1215",
        raw_record_ref=f"fixture://summer-2026/{site_id}/1215",
    )
    measurements = record["measurements"]
    if site_id == STALE:
        record.update(
            interval_start="2026-07-15T10:45:00Z",
            interval_end="2026-07-15T11:00:00Z",
            received_at="2026-07-15T11:00:00Z",
        )
    if site_id == PV_ONLY:
        record["measurements"] = {"pv_power": measurements["pv_power"]}
    if site_id == PV_MISSING:
        measurements["pv_power"].update(value=None, availability="missing")
    if site_id in (SOC_ONLY, BATTERY):
        measurements["battery_soc"] = {
            "value": 65,
            "unit": "%",
            "requirement": "optional",
            "boundary": "not_applicable",
        }
    if site_id == BATTERY:
        for metric, value in (("battery_charge", 1.5), ("battery_discharge", 0)):
            measurements[metric] = {
                "value": value,
                "unit": "kW",
                "requirement": "optional",
                "boundary": "ac",
            }
        measurements["grid_export"]["value"] = 2.5
    return record


def seed_demo(database: Database, password: str | None = None) -> dict[str, str]:
    """Idempotent, explicitly synthetic demo. Existing passwords are never reset."""
    database.migrate()
    base = json.loads(
        (Path(__file__).parent / "fixtures" / "telemetry.json").read_text()
    )
    source = profile_source()
    credentials = {}
    with database.connect() as connection:
        _refuse_legacy_geography(connection, database)
        for area_id, area in source["areas"].items():
            connection.execute(
                "INSERT OR IGNORE INTO areas VALUES (?,?,?)",
                (area_id, area["label"], "simulated"),
            )
        for profile in source["profiles"]:
            site_id = profile["site_id"]
            capabilities = _capabilities(site_id)
            requirements = {
                metric: "mandatory" if metric == Metric.pv else "optional"
                for metric in capabilities
            }
            connection.execute(
                "INSERT OR IGNORE INTO sites VALUES (?,?,?,?,?,?,?,?)",
                (
                    site_id,
                    profile["name"],
                    profile["area_id"],
                    "simulated",
                    900,
                    1800,
                    json.dumps(capabilities),
                    json.dumps(requirements),
                ),
            )
            connection.execute(
                "INSERT OR IGNORE INTO devices VALUES (?,?,?)",
                (f"meter-{site_id}", site_id, "synthetic-demo"),
            )
            connection.execute(
                "INSERT OR IGNORE INTO energy_streams VALUES (?,?,?)",
                (site_id, f"meter-{site_id}", "synthetic-demo"),
            )
        for username, role, account_type, sites, areas in ACCOUNTS:
            if not connection.execute(
                "SELECT 1 FROM users WHERE username=?", (username,)
            ).fetchone():
                secret = password or secrets.token_urlsafe(18)
                connection.execute(
                    "INSERT INTO users(user_id,username,password_hash,role,account_type) VALUES (?,?,?,?,?)",
                    (username, username, hash_password(secret), role, account_type),
                )
                credentials[username] = secret
            for site_id in sites:
                connection.execute(
                    "INSERT OR IGNORE INTO user_sites VALUES (?,?)", (username, site_id)
                )
            for area_id in areas:
                connection.execute(
                    "INSERT OR IGNORE INTO user_areas VALUES (?,?)", (username, area_id)
                )
        connection.execute(
            "INSERT OR IGNORE INTO settings VALUES ('replay_at',?)", (stamp(REPLAY_AT),)
        )
        seed_operations(connection)
        seed_offers(database, connection)
        # One transaction for every feed: a commit per record is slow on Windows.
        for profile in source["profiles"]:
            if profile["site_id"] != NO_TELEMETRY:  # A registered but unavailable feed.
                ingest(
                    database,
                    _telemetry(base, profile["site_id"]),
                    "seed-demo",
                    within=connection,
                )
    return credentials
