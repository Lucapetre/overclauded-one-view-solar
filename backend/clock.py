"""One analytical clock for decisions; real wall time for security and audit receipt.

Live mode (the default) is wall time. A local *scenario* run stores its analytical time in the
database (`settings.replay_at`, plus `settings.scenario` naming the run) and only moves forward
through the local CLI (`python -m backend scenario ...`). Restarting a scenario means a new
local database; there is no rewind and no HTTP control.

Analytical time drives telemetry freshness, planning, forecast-as-of, offer acceptance,
expiry, reminders, progress and settlement, and incident ages. Sessions, authentication,
request receipt and `audit.received_at` always use `datetime.now(UTC)`.
"""

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.db import stamp
from backend.errors import ApiError

SCENARIO_KEY = "scenario"
REPLAY_KEY = "replay_at"
SCENARIO_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
DURATION_PATTERN = re.compile(r"^(\d{1,6})([smhd])$")
UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def wall_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ClockState:
    mode: str  # "live" or "scenario"
    now: datetime
    scenario_id: str | None = None
    run_id: str | None = None
    started_at: datetime | None = None

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "analytical_now": stamp(self.now),
            "scenario_id": self.scenario_id,
            "run_id": self.run_id,
            "scenario_started_at": stamp(self.started_at) if self.started_at else None,
            "wall_now": stamp(wall_now()),
        }


def _parse(text: str) -> datetime:
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("Scenario times must be timezone-aware")
    return value.astimezone(UTC)


def _read(connection) -> ClockState:
    try:
        rows = dict(
            connection.execute(
                "SELECT key,value FROM settings WHERE key IN (?,?)",
                (SCENARIO_KEY, REPLAY_KEY),
            ).fetchall()
        )
    except sqlite3.OperationalError:
        return ClockState("live", wall_now())
    scenario = rows.get(SCENARIO_KEY)
    if not scenario or REPLAY_KEY not in rows:
        return ClockState("live", wall_now())
    details = json.loads(scenario)
    return ClockState(
        "scenario",
        _parse(rows[REPLAY_KEY]),
        details.get("scenario_id"),
        details.get("run_id"),
        _parse(details["start_at"]) if details.get("start_at") else None,
    )


def clock_state(connection) -> ClockState:
    """Clock state seen through an open connection (same transaction as the caller)."""
    return _read(connection)


def analytical_now(connection) -> datetime:
    """Analytical time: the scenario clock when one runs in this database, else wall time."""
    return _read(connection).now


def scenario_now(connection) -> datetime | None:
    """The scenario clock, or None in live mode (data newer than it is not yet known)."""
    state = _read(connection)
    return state.now if state.mode == "scenario" else None


def age_seconds(connection, moment: datetime | str) -> float:
    """Elapsed analytical seconds since `moment` (incident ages, freshness). Negative = future."""
    if isinstance(moment, str):
        moment = _parse(moment)
    return (analytical_now(connection) - moment.astimezone(UTC)).total_seconds()


class AnalyticalClock:
    """Callable used as `Settings.clock`: reads the scenario clock of one database file.

    Opening read-only means a missing database or table simply yields wall time.
    """

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)

    def __call__(self) -> datetime:
        if not self.database_path.exists():
            return wall_now()
        try:
            connection = sqlite3.connect(
                self.database_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10
            )
        except sqlite3.OperationalError:
            return wall_now()
        try:
            return _read(connection).now
        finally:
            connection.close()


def parse_duration(text: str) -> timedelta:
    match = DURATION_PATTERN.match(text.strip())
    if not match:
        raise ApiError(
            422, "invalid_duration", "Use a duration such as 15m, 2h, 1d or 90s"
        )
    return timedelta(seconds=int(match.group(1)) * UNITS[match.group(2)])


def _set(connection, key: str, value: str):
    connection.execute(
        "INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def start_scenario(database, scenario_id: str, at: datetime) -> dict:
    """Begin a forward-only scenario run in this database. Idempotent for the same start."""
    if not SCENARIO_PATTERN.match(scenario_id):
        raise ApiError(422, "invalid_scenario", "Use a short scenario identifier")
    at = at.astimezone(UTC)
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        state = _read(connection)
        if state.mode == "scenario":
            if state.scenario_id == scenario_id and state.started_at == at:
                return {"status": "already_running", **state.as_dict()}
            raise ApiError(
                409,
                "scenario_running",
                "A scenario already runs in this database. Restart it with a new local "
                "database (SOLAR_DATABASE) instead of rewinding",
            )
        latest = connection.execute(
            "SELECT MAX(value) FROM (SELECT MAX(settled_at) AS value FROM offer_settlements "
            "UNION ALL SELECT MAX(accepted_at) FROM user_offers "
            "UNION ALL SELECT MAX(accepted_at) FROM planner_commitments)"
        ).fetchone()[0]
        if latest and _parse(latest) > at:
            raise ApiError(
                409,
                "would_rewind",
                "This database already holds offers or plans after the requested start; "
                "use a new local database for this scenario",
            )
        run_id = uuid.uuid4().hex
        connection.execute(
            "INSERT INTO scenario_runs(run_id,scenario_id,start_at,started_received_at) "
            "VALUES (?,?,?,?)",
            (run_id, scenario_id, stamp(at), stamp(wall_now())),
        )
        connection.execute(
            "INSERT INTO scenario_clock_events(run_id,from_at,to_at,received_at) VALUES (?,?,?,?)",
            (run_id, None, stamp(at), stamp(wall_now())),
        )
        _set(
            connection,
            SCENARIO_KEY,
            json.dumps(
                {"scenario_id": scenario_id, "run_id": run_id, "start_at": stamp(at)},
                sort_keys=True,
            ),
        )
        _set(connection, REPLAY_KEY, stamp(at))
        database.audit(
            connection,
            "local-admin",
            "scenario.started",
            run_id,
            "local-scenario",
            {"scenario_id": scenario_id, "analytical_at": stamp(at)},
        )
        return {"status": "started", **_read(connection).as_dict()}


def advance_scenario(
    database, *, to: datetime | None = None, by: timedelta | None = None
) -> dict:
    """Move the scenario clock forward. Rewinds are refused; equal time is a no-op."""
    if (to is None) == (by is None):
        raise ApiError(422, "invalid_advance", "Give exactly one of --to or --by")
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        state = _read(connection)
        if state.mode != "scenario":
            raise ApiError(
                409, "no_scenario", "Start a scenario first: scenario start <name> --at"
            )
        target = (to.astimezone(UTC) if to else state.now + by).astimezone(UTC)
        if target < state.now:
            raise ApiError(
                409,
                "rewind_refused",
                f"The scenario clock only moves forward (now {stamp(state.now)})",
            )
        if target == state.now:
            return {"status": "unchanged", **state.as_dict()}
        connection.execute(
            "INSERT INTO scenario_clock_events(run_id,from_at,to_at,received_at) VALUES (?,?,?,?)",
            (state.run_id, stamp(state.now), stamp(target), stamp(wall_now())),
        )
        _set(connection, REPLAY_KEY, stamp(target))
        database.audit(
            connection,
            "local-admin",
            "scenario.advanced",
            state.run_id or "scenario",
            "local-scenario",
            {"from": stamp(state.now), "to": stamp(target)},
        )
        return {"status": "advanced", **_read(connection).as_dict()}


def scenario_status(database) -> dict:
    with database.connect() as connection:
        state = _read(connection)
        result = state.as_dict()
        if state.run_id:
            result["advances"] = connection.execute(
                "SELECT COUNT(*) FROM scenario_clock_events WHERE run_id=?",
                (state.run_id,),
            ).fetchone()[0]
        return result
