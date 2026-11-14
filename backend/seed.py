import json
import secrets
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from backend.db import Database, stamp
from backend.ingestion import ingest
from backend.models import Metric
from backend.security import hash_password

REPLAY_AT = datetime(2026, 7, 15, 12, 15, tzinfo=UTC)


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
                        f"Demo home {site_id}",
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
        for username, role in (
            ("customer", "customer"),
            ("other-customer", "customer"),
            ("dispatcher", "dispatcher"),
            ("technician", "technician"),
            ("supervisor", "supervisor"),
        ):
            if not connection.execute(
                "SELECT 1 FROM users WHERE username=?", (username,)
            ).fetchone():
                secret = password or secrets.token_urlsafe(18)
                connection.execute(
                    "INSERT INTO users VALUES (?,?,?,?)",
                    (username, username, hash_password(secret), role),
                )
                credentials[username] = secret
        for user_id, site_id in (
            ("customer", "north-01"),
            ("other-customer", "south-01"),
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
        ):
            connection.execute(
                "INSERT OR IGNORE INTO user_areas VALUES (?,?)", (user_id, area)
            )
        connection.execute(
            "INSERT OR IGNORE INTO settings VALUES ('replay_at',?)", (stamp(REPLAY_AT),)
        )
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
