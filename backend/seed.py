import json
import secrets
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.db import Database, stamp
from backend.ingestion import ingest
from backend.models import Metric
from backend.ops import open_incident, profile_source
from backend.security import hash_password

REPLAY_AT = datetime(2026, 7, 15, 12, 15, tzinfo=UTC)
SHIFT = "08:00-18:00"
CREWS = (
    (
        "solar-care",
        "Solar Care",
        "north",
        ["Production", "Temperature", "Telemetry", "Local issue", "Other"],
        ["technician"],
    ),
    (
        "grid-response",
        "Grid Response",
        "central",
        [
            "Voltage",
            "Area event",
            "Telemetry",
            "Other",
            "Production",
            "Temperature",
            "Local issue",
        ],
        ["technician-central"],
    ),
    (
        "field-service",
        "Field Service",
        "south",
        ["Local issue", "Production", "Temperature", "Telemetry", "Voltage", "Other"],
        ["technician-south"],
    ),
)
POLICY = "Synthetic demo policy rule on replayed demo data; not an equipment diagnosis."
# (incident_id, site, tier, family, title, evidence, minutes before the replay clock)
INCIDENTS = (
    (
        "demo-inc-central-05-area",
        "central-05",
        "P0",
        "Area event",
        "Synthetic area event: several demo feeds dropped together",
        "Replay policy marks a simultaneous drop across demo feeds near this site.",
        50,
    ),
    (
        "demo-inc-north-05-production",
        "north-05",
        "P1",
        "Production",
        "Synthetic rule: mandatory PV value missing in the latest interval",
        "The latest replayed record reports PV power as missing.",
        95,
    ),
    (
        "demo-inc-central-07-voltage",
        "central-07",
        "P1",
        "Voltage",
        "Synthetic voltage-band policy flag",
        "Replay policy flags a demo voltage value outside its configured band.",
        80,
    ),
    (
        "demo-inc-south-05-temperature",
        "south-05",
        "P1",
        "Temperature",
        "Synthetic temperature-threshold policy flag",
        "Replay policy flags a demo temperature value above its configured threshold.",
        70,
    ),
    (
        "demo-inc-north-02-telemetry",
        "north-02",
        "P2",
        "Telemetry",
        "Synthetic rule: demo feed is stale",
        "The latest replayed interval ended more than 30 minutes before the replay clock.",
        60,
    ),
    (
        "demo-inc-south-08-production",
        "south-08",
        "P2",
        "Production",
        "Synthetic rule: production below the demo expectation band",
        "Replay policy compares PV power with a fixed demo band for this profile.",
        45,
    ),
    (
        "demo-inc-north-03-telemetry",
        "north-03",
        "P3",
        "Telemetry",
        "Synthetic rule: no telemetry received for this demo site",
        "The registered demo site has no replayed record.",
        120,
    ),
    (
        "demo-inc-south-03-local",
        "south-03",
        "P3",
        "Local issue",
        "Synthetic follow-up: scheduled demo inspection reminder",
        "Replay policy schedules a periodic demo inspection reminder.",
        30,
    ),
)


def seed_operations(connection):
    """Synthetic site profiles, crews and incidents. Idempotent."""
    for profile in profile_source()["profiles"]:
        site_id = f"{profile['area']}-{profile['number']:02d}"
        connection.execute(
            "INSERT OR IGNORE INTO site_profiles(site_id,latitude,longitude,zone,character,"
            "segment,business_type,installed_kwp,monthly_import_kwh,monthly_export_kwh,"
            "service_fee_ron) SELECT ?,?,?,?,?,?,?,?,?,?,? "
            "WHERE EXISTS (SELECT 1 FROM sites WHERE site_id=?)",
            (
                site_id,
                profile["latitude"],
                profile["longitude"],
                profile["zone"],
                profile["character"],
                profile["segment"],
                profile.get("business_type"),
                profile["installed_kwp"],
                profile["monthly_import_kwh"],
                profile["monthly_export_kwh"],
                profile["service_fee_ron"],
                site_id,
            ),
        )
    for crew_id, name, area, skills, members in CREWS:
        connection.execute(
            "INSERT OR IGNORE INTO crews(crew_id,name,area_id,skills,shift) VALUES (?,?,?,?,?)",
            (crew_id, name, area, json.dumps(skills), SHIFT),
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


def seed_demo(database: Database, password: str | None = None) -> dict[str, str]:
    """Idempotent, explicitly synthetic demo. Existing passwords are never reset."""
    database.migrate()
    base = json.loads(
        (Path(__file__).parent / "fixtures" / "telemetry.json").read_text()
    )
    credentials = {}
    with database.connect() as connection:
        for area in ("north", "central", "south"):
            connection.execute(
                "INSERT OR IGNORE INTO areas VALUES (?,?,?)",
                (area, f"Demo {area.title()}", "simulated"),
            )
            for number in range(1, 9):
                site_id = f"{area}-{number:02d}"
                capabilities = [
                    Metric.pv.value,
                    Metric.load.value,
                    Metric.grid_import.value,
                    Metric.grid_export.value,
                ]
                if area == "central" and number in (1, 2):
                    capabilities.append(Metric.soc.value)
                    if number == 2:
                        capabilities += [
                            Metric.battery_charge.value,
                            Metric.battery_discharge.value,
                        ]
                requirements = {
                    metric: "mandatory" if metric == Metric.pv else "optional"
                    for metric in capabilities
                }
                connection.execute(
                    "INSERT OR IGNORE INTO sites VALUES (?,?,?,?,?,?,?,?)",
                    (
                        site_id,
                        "Demo bistro central-03"
                        if site_id == "central-03"
                        else f"Demo home {site_id}",
                        area,
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
        for username, role, account_type in (
            ("customer", "customer", "home"),
            ("other-customer", "customer", "home"),
            ("business-customer", "customer", "business"),
            ("dispatcher", "dispatcher", "home"),
            ("technician", "technician", "home"),
            ("supervisor", "supervisor", "home"),
            ("technician-central", "technician", "home"),
            ("technician-south", "technician", "home"),
            ("area-manager", "supervisor", "home"),
        ):
            if not connection.execute(
                "SELECT 1 FROM users WHERE username=?", (username,)
            ).fetchone():
                secret = password or secrets.token_urlsafe(18)
                connection.execute(
                    "INSERT INTO users(user_id,username,password_hash,role,account_type) VALUES (?,?,?,?,?)",
                    (username, username, hash_password(secret), role, account_type),
                )
                credentials[username] = secret
        for user_id, site_id in (
            ("customer", "north-01"),
            ("other-customer", "south-01"),
            ("business-customer", "central-03"),
            ("technician", "north-01"),
            ("technician", "north-02"),
        ):
            connection.execute(
                "INSERT OR IGNORE INTO user_sites VALUES (?,?)", (user_id, site_id)
            )
        for user_id, area in (
            ("dispatcher", "north"),
            ("supervisor", "north"),
            ("supervisor", "central"),
            ("supervisor", "south"),
            ("area-manager", "north"),
        ):
            connection.execute(
                "INSERT OR IGNORE INTO user_areas VALUES (?,?)", (user_id, area)
            )
        connection.execute(
            "INSERT OR IGNORE INTO settings VALUES ('replay_at',?)", (stamp(REPLAY_AT),)
        )
        seed_operations(connection)
    for area in ("north", "central", "south"):
        for number in range(1, 9):
            site_id = f"{area}-{number:02d}"
            if site_id == "north-03":
                continue  # A registered but unavailable feed.
            record = deepcopy(base)
            record.update(
                site_id=site_id,
                device_id=f"meter-{site_id}",
                record_id=f"{site_id}-20260715T1215",
                raw_record_ref=f"fixture://summer-2026/{site_id}/1215",
            )
            if site_id == "north-02":
                record.update(
                    interval_start="2026-07-15T10:45:00Z",
                    interval_end="2026-07-15T11:00:00Z",
                    received_at="2026-07-15T11:00:00Z",
                )
            if site_id == "north-04":
                record["measurements"] = {
                    "pv_power": record["measurements"]["pv_power"]
                }
            if site_id == "north-05":
                record["measurements"]["pv_power"].update(
                    value=None, availability="missing"
                )
            if site_id in ("central-01", "central-02"):
                record["measurements"]["battery_soc"] = {
                    "value": 65,
                    "unit": "%",
                    "requirement": "optional",
                    "boundary": "not_applicable",
                }
            if site_id == "central-02":
                record["measurements"]["battery_charge"] = {
                    "value": 1.5,
                    "unit": "kW",
                    "requirement": "optional",
                    "boundary": "ac",
                }
                record["measurements"]["battery_discharge"] = {
                    "value": 0,
                    "unit": "kW",
                    "requirement": "optional",
                    "boundary": "ac",
                }
                record["measurements"]["grid_export"]["value"] = 2.5
            ingest(database, record, "seed-demo")
    return credentials
