"""Power Block Offers worker: progress, reminders, expiry and idempotent settlement.

All state lives in the database, so a restart (or a second worker) resumes safely: each
settlement is guarded by the user offer's status and a UNIQUE ledger row.
"""

import json
import logging
import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from backend.clock import analytical_now
from backend.config import Settings
from backend.db import Database, stamp
from backend.errors import ApiError
from backend.ingestion import ingest
from backend.models import Metric
from backend.offers import (
    RUNNING_SQL,
    allocate,
    effective_end,
    live_allocations,
    notify,
    settle_user_offer,
)
from backend.offers_math import decimal_text, window_text

logger = logging.getLogger(__name__)


def _remind(connection, row, metered: Decimal, now: datetime) -> int:
    left = effective_end(row) - now
    energy = Decimal(row["energy_kwh"])
    kind = None
    if left <= timedelta(minutes=10) and not row["reminded_10_at"]:
        kind = "offer_reminder_10"
    elif (
        timedelta(minutes=10) < left <= timedelta(minutes=30)
        and not row["reminded_30_at"]
        and row["window_minutes"] > 30
    ):
        kind = "offer_reminder_30"
    if not kind:
        return 0
    minutes = max(1, round(left.total_seconds() / 60))
    verb = "used" if row["type"] == "consume" else "fed into the grid"
    done = min(metered, energy)
    notify(
        connection,
        row["user_id"],
        kind,
        f"About {window_text(minutes)} left",
        f"You have {verb} {decimal_text(done)} of {decimal_text(energy)} kWh so far; "
        f"{decimal_text(energy - done)} kWh to go before your window ends.",
        f"offers/mine/{row['user_offer_id']}",
        now,
    )
    # A 10-minute reminder also retires the 30-minute one, so each is sent at most once.
    connection.execute(
        "UPDATE user_offers SET reminded_10_at=CASE WHEN ? THEN ? ELSE reminded_10_at END, "
        "reminded_30_at=COALESCE(reminded_30_at, ?) WHERE user_offer_id=?",
        (kind == "offer_reminder_10", stamp(now), stamp(now), row["user_offer_id"]),
    )
    return 1


def settle_due(
    database: Database, now: datetime | None = None, settings: Settings | None = None
) -> dict[str, int]:
    """One idempotent worker pass at `now` (UTC), by default the analytical clock.

    Repeating a pass at the same (or a later) analytical time never adds notifications,
    reminders or ledger rows: every write is guarded by status or a reminder timestamp.
    """
    settings = settings or Settings(database_path=database.path)
    now = (now or settings.clock()).astimezone(UTC)
    grace = timedelta(minutes=settings.offer_settlement_grace_minutes)
    summary = {"expired_offers": 0, "progressed": 0, "settled": 0, "reminders": 0}
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        summary["expired_offers"] = connection.execute(
            "UPDATE offers SET status='expired', updated_at=? "
            "WHERE status='available' AND offer_expires_at<=?",
            (stamp(now), stamp(now)),
        ).rowcount
        groups = connection.execute(
            f"SELECT DISTINCT site_id, type FROM user_offers WHERE status IN {RUNNING_SQL} "
            "ORDER BY site_id, type"
        ).fetchall()
    for group in groups:
        with database.connect() as connection:
            # One site and metric per transaction; a concurrent pass waits, then re-reads.
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                f"SELECT * FROM user_offers WHERE site_id=? AND type=? AND status IN {RUNNING_SQL} "
                "ORDER BY accepted_at, user_offer_id",
                (group["site_id"], group["type"]),
            ).fetchall()
            if not rows:
                continue
            allocations = allocate(connection, group["site_id"], group["type"], rows)
            for row in rows:
                allocation = allocations[row["user_offer_id"]]
                energy = Decimal(row["energy_kwh"])
                if (
                    allocation.metered_kwh >= energy
                    or now >= effective_end(row) + grace
                ):
                    summary["settled"] += settle_user_offer(
                        database, connection, row, allocation, now
                    )
                    continue
                connection.execute(
                    "UPDATE user_offers SET metered_kwh=?, coverage_ratio=?, progress_at=?, "
                    "status=CASE WHEN ? THEN 'active' ELSE status END "
                    f"WHERE user_offer_id=? AND status IN {RUNNING_SQL}",
                    (
                        decimal_text(allocation.metered_kwh),
                        float(round(allocation.coverage_ratio, 4)),
                        stamp(now),
                        allocation.metered_kwh > 0,
                        row["user_offer_id"],
                    ),
                )
                summary["progressed"] += 1
                if now < effective_end(row):
                    summary["reminders"] += _remind(
                        connection, row, allocation.metered_kwh, now
                    )
    return summary


def reconcile(
    database: Database, user_id: str | None = None, fix: bool = True
) -> list[dict]:
    """Recompute savings_totals from the ledger; return (and optionally fix) mismatches."""
    fields = (
        "lifetime_bani",
        "consume_bani",
        "export_bani",
        "penalties_bani",
        "settled_count",
    )
    where = " WHERE user_id=?" if user_id else ""
    parameters = (user_id,) if user_id else ()
    mismatches = []
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        expected = {
            row["user_id"]: dict(row)
            for row in connection.execute(
                "SELECT user_id, SUM(savings_bani) AS lifetime_bani, "
                "SUM(CASE WHEN type='consume' THEN savings_bani ELSE 0 END) AS consume_bani, "
                "SUM(CASE WHEN type='export' THEN savings_bani ELSE 0 END) AS export_bani, "
                "SUM(penalty_bani) AS penalties_bani, COUNT(*) AS settled_count "
                "FROM offer_settlements" + where + " GROUP BY user_id",
                parameters,
            )
        }
        stored = {
            row["user_id"]: dict(row)
            for row in connection.execute(
                "SELECT * FROM savings_totals" + where, parameters
            )
        }
        zero = dict.fromkeys(fields, 0)
        for user in sorted(set(expected) | set(stored)):
            want = expected.get(user, zero)
            have = stored.get(user, zero)
            for field in fields:
                if want[field] != have[field]:
                    mismatches.append(
                        {
                            "user_id": user,
                            "field": field,
                            "stored": have[field],
                            "expected": want[field],
                        }
                    )
            if fix and any(want[field] != have[field] for field in fields):
                connection.execute(
                    "INSERT INTO savings_totals(user_id,lifetime_bani,consume_bani,"
                    "export_bani,penalties_bani,settled_count,updated_at) "
                    "VALUES (?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                    "lifetime_bani=excluded.lifetime_bani, consume_bani=excluded.consume_bani, "
                    "export_bani=excluded.export_bani, penalties_bani=excluded.penalties_bani, "
                    "settled_count=excluded.settled_count, updated_at=excluded.updated_at",
                    (user, *(want[field] for field in fields), stamp()),
                )
        if fix and mismatches:
            database.audit(
                connection,
                "local-admin",
                "offer.savings_reconciled",
                user_id or "all",
                "reconcile-savings",
                {"mismatches": len(mismatches)},
            )
    return mismatches


SLOT = timedelta(minutes=15)


def simulate_offer_meter(
    database: Database,
    user_offer_id: str,
    fraction: float,
    coverage: float = 1.0,
    now: datetime | None = None,
) -> dict:
    """SYNTHETIC demo meter data for the elapsed part of an accepted offer's window.

    Writes 15-minute records (the last one may be shorter) through `ingest()` so the energy
    attributed to the offer reaches about `fraction` x energy_kwh. Only already-ended intervals
    are written, with received_at = now. Re-running tops up to the requested fraction.

    Live-mode helper only: in a component scenario, offers at provider sites settle from the
    imported authoritative meter energy, so no synthetic readings are needed.
    """
    if not 0 <= fraction <= 2 or not 0 <= coverage <= 1:
        raise ApiError(
            422, "invalid_simulation", "Use 0 <= fraction <= 2 and 0 <= coverage <= 1"
        )
    with database.connect() as connection:
        # Live mode: wall time. In a scenario run: the analytical scenario clock.
        now = (now or analytical_now(connection)).astimezone(UTC)
        row = connection.execute(
            "SELECT uo.*, s.capabilities, s.measurement_requirements, e.device_id, "
            "e.source_id FROM user_offers uo JOIN sites s ON s.site_id=uo.site_id "
            "LEFT JOIN energy_streams e ON e.site_id=uo.site_id WHERE uo.user_offer_id=?",
            (user_offer_id,),
        ).fetchone()
        if not row:
            raise ApiError(404, "not_found", "User offer not found")
        if row["status"] not in ("accepted", "active"):
            raise ApiError(409, "offer_settled", "This user offer is already settled")
        if not row["device_id"]:
            raise ApiError(422, "meter_required", "This site has no linked meter")
        start, end = datetime.fromisoformat(row["window_start"]), effective_end(row)
        limit = min(now, end)
        slots = []
        cursor = start
        while cursor < limit:
            slot_end = min(cursor + SLOT, limit)
            clash = connection.execute(
                "SELECT MAX(interval_end) FROM telemetry WHERE site_id=? "
                "AND interval_start<? AND interval_end>?",
                (row["site_id"], stamp(slot_end), stamp(cursor)),
            ).fetchone()[0]
            if clash:
                cursor = max(
                    cursor + timedelta(seconds=1), datetime.fromisoformat(clash)
                )
                continue
            if slot_end - cursor >= timedelta(minutes=1):
                slots.append((cursor, slot_end))
            cursor = slot_end
        metered = live_allocations(connection, [row])[user_offer_id].metered_kwh
    capabilities = json.loads(row["capabilities"])
    requirements = json.loads(row["measurement_requirements"])
    metric = Metric.grid_import if row["type"] == "consume" else Metric.grid_export
    reported = round(len(slots) * coverage)
    available = slots[:reported]
    target = max(
        Decimal(0), Decimal(row["energy_kwh"]) * Decimal(str(fraction)) - metered
    )
    hours = sum(((end - begin).total_seconds() / 3600 for begin, end in available), 0.0)
    power = round(float(target) / hours, 3) if hours else 0.0
    written = []
    for index, (begin, finish) in enumerate(slots):
        flow = power if index < reported else None
        values = {
            Metric.grid_import: flow if row["type"] == "consume" else 0.0,
            Metric.grid_export: flow if row["type"] == "export" else 0.0,
            Metric.pv: 0.4 if row["type"] == "consume" else (flow or 0.0) + 0.8,
        }
        measurements = {
            name.value: {
                "value": value,
                "unit": "kW",
                "requirement": requirements.get(name.value, "optional"),
                "availability": "missing" if value is None else "available",
                "boundary": "ac",
            }
            for name, value in values.items()
            if name.value in capabilities
        }
        record_id = f"offer-sim-{user_offer_id[:12]}-{begin:%Y%m%dT%H%M%S}"
        result = ingest(
            database,
            {
                "schema_version": "1.0",
                "record_id": record_id,
                "site_id": row["site_id"],
                "device_id": row["device_id"],
                "source_id": row["source_id"],
                "interval_start": begin.isoformat(),
                "interval_end": finish.isoformat(),
                "received_at": now.isoformat(),
                "source_mode": "synthetic",
                "raw_record_ref": f"simulate-offer-meter://{user_offer_id}/{begin:%H%M%S}",
                "measurements": measurements,
                "quality_flags": ["synthetic_offer_demo"],
                "vendor_codes": [],
            },
            "simulate-offer-meter",
        )
        written.append(result.record_id)
    return {
        "user_offer_id": user_offer_id,
        "site_id": row["site_id"],
        "metric": metric.value,
        "records": len(written),
        "reported_records": min(reported, len(slots)),
        "power_kw": power,
        "target_added_kwh": decimal_text(target) if available else "0",
    }


def run_worker(
    database: Database,
    settings: Settings,
    once: bool = False,
    interval: float | None = None,
    stop: threading.Event | None = None,
):
    interval = interval or settings.offer_worker_interval_seconds
    stop = stop or threading.Event()
    while not stop.is_set():
        try:
            summary = settle_due(database, settings.clock(), settings)
            if once or any(summary.values()):
                logger.info("Offer worker pass: %s", summary)
            if once:
                return summary
        except Exception:
            logger.exception("Offer worker pass failed")
            if once:
                raise
        stop.wait(interval)
    return None


def start_background_worker(database: Database, settings: Settings):
    """Start the in-app worker thread; returns a function that stops it."""
    stop = threading.Event()
    thread = threading.Thread(
        target=run_worker,
        args=(database, settings),
        kwargs={"stop": stop},
        name="offers-worker",
        daemon=True,
    )
    thread.start()

    def shutdown():
        stop.set()
        thread.join(timeout=10)

    return shutdown
