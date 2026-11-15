"""Business task planner: incremental site cost, constraints, battery fairness, API flow."""

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.clock import start_scenario
from backend.config import Settings
from backend.db import Database
from backend.ingestion import ingest
from backend.main import create_app
from backend.planner import (
    SLOT,
    BatteryParams,
    SlotInput,
    TaskSpec,
    optimize,
)
from backend.seed import seed_demo

PASSWORD = "test-password-only"
DAY = datetime(2026, 7, 20, tzinfo=UTC)  # a Monday (UTC midnight = 03:00 local)


def slots(pv, base, rate=1.0, value=0.4, hours=24, start=DAY):
    """Hourly lists (or callables of the UTC hour) expanded to 15-minute slots."""
    result = []
    for index in range(hours * 4):
        moment = start + SLOT * index
        hour = moment.hour

        def pick(item, hour=hour):
            return item(hour) if callable(item) else item

        result.append(
            SlotInput(
                moment,
                moment + SLOT,
                pick(pv),
                pick(base),
                pick(rate),
                pick(value),
                "band",
                "v1",
            )
        )
    return result


def spec(**changes):
    values = {
        "power_kw": 4.0,
        "energy_kwh": 8.0,
        "earliest_start": DAY,
        "deadline": DAY + timedelta(hours=24),
    }
    values.update(changes)
    return TaskSpec(**values)


def solar(hour):
    return 6.0 if 8 <= hour < 14 else 0.0


def test_export_opportunity_cost_self_consuming_solar_is_not_free():
    plan = optimize(slots(solar, 0.5, rate=1.0, value=0.45), spec(), None)
    assert plan.status == "recommended"
    assert 8 <= plan.selected.start.hour and plan.selected.end.hour <= 14
    # Running on surplus solar loses its export value: 8 kWh x 0.45, not zero.
    assert plan.selected.cost == pytest.approx(8 * 0.45)
    # Night: everything is imported at the import rate.
    night = next(e for e in plan.feasible if e.start == DAY)
    assert night.cost == pytest.approx(8 * 1.0)


def test_deadline_and_non_interruptible_run_with_deterministic_tie_break():
    task = spec(
        earliest_start=DAY + timedelta(hours=2), deadline=DAY + timedelta(hours=6)
    )
    plan = optimize(slots(0.0, 1.0, rate=1.0), task, None)
    duration = timedelta(hours=2)
    assert plan.feasible
    for item in plan.feasible:
        assert item.end - item.start == duration  # one contiguous run
        assert item.start >= task.earliest_start and item.end <= task.deadline
    # Every start costs the same: the earliest start wins, every time.
    assert plan.selected.start == DAY + timedelta(hours=2)
    again = optimize(slots(0.0, 1.0, rate=1.0), task, None)
    assert again.selected.start == plan.selected.start
    assert [e.start for e in again.feasible] == [e.start for e in plan.feasible]
    # Solar after the deadline would be cheaper: the deadline is the binding constraint.
    late = optimize(slots(lambda h: 8.0 if h >= 10 else 0.0, 0.5), task, None)
    assert "deadline" in late.binding


def test_site_import_limit_excludes_starts_and_is_reported_binding():
    cheap_night = optimize(
        slots(solar, 3.0, rate=lambda h: 0.5 if h < 6 else 2.0, value=0.4),
        spec(import_limit_kw=6.0),
        None,
    )
    # 3 kW base + 4 kW task = 7 kW import at night exceeds the 6 kW limit.
    assert all(e.start.hour >= 6 for e in cheap_night.feasible)
    assert "site_import_limit" in cheap_night.binding
    assert cheap_night.selected.start.hour >= 8
    unlimited = optimize(
        slots(solar, 3.0, rate=lambda h: 0.5 if h < 6 else 2.0, value=0.4), spec(), None
    )
    assert unlimited.selected.start.hour < 6


BATTERY = BatteryParams(
    usable_kwh=10.0,
    soc_pct=100.0,
    reserve_pct=20.0,
    charge_limit_kw=3.0,
    discharge_limit_kw=3.0,
    charge_efficiency=0.95,
    discharge_efficiency=0.9,
)


def test_battery_energy_is_valued_at_terminal_state_not_claimed_as_savings():
    # No solar, flat tariff: a full battery covers the run, but the energy it gives away
    # is valued at what it would have displaced, so the task still costs 8 kWh x rate.
    plan = optimize(slots(0.0, 0.0, rate=1.2), spec(), BATTERY)
    assert plan.battery_used
    assert plan.selected.cost == pytest.approx(8 * 1.2)
    # 3 kW discharge limit x 2 h = 6 kWh delivered = 6 / 0.9 kWh taken from storage.
    assert plan.selected.terminal_change_kwh == pytest.approx(-6 / 0.9)
    no_battery = optimize(slots(0.0, 0.0, rate=1.2), spec(), None)
    assert no_battery.selected.cost == pytest.approx(plan.selected.cost)


def test_battery_reserve_and_power_limits_are_respected():
    at_reserve = BatteryParams(**{**BATTERY.__dict__, "soc_pct": 20.0})
    plan = optimize(slots(0.0, 0.0, rate=1.0), spec(), at_reserve)
    battery_power = [
        kw for kw in plan.selected.simulation.battery_kw if kw is not None and kw > 0
    ]
    assert battery_power == []  # nothing below the reserve
    full = optimize(slots(0.0, 0.0, rate=1.0), spec(), BATTERY)
    discharges = [kw for kw in full.selected.simulation.battery_kw if kw and kw > 0]
    assert discharges and max(discharges) <= BATTERY.discharge_limit_kw + 1e-9
    # 4 kW task, 3 kW discharge limit: at least 1 kW comes from the grid.
    run = [
        imported
        for imported, kw in zip(
            full.selected.simulation.import_kwh, full.selected.profile, strict=True
        )
        if kw > 0
    ]
    assert min(run) >= 0.25 - 1e-9  # 1 kW x 15 minutes
    # Stored energy never ends below the reserve.
    assert full.selected.simulation.stored_kwh >= 10.0 * 0.2 - 1e-9


def test_unknown_price_gives_null_cost_with_reason_never_zero():
    def rate(hour):
        return 1.0 if 4 <= hour < 19 else None

    night_only = spec(
        earliest_start=DAY + timedelta(hours=20), deadline=DAY + timedelta(hours=23)
    )
    plan = optimize(slots(0.0, 1.0, rate=rate, value=rate), night_only, None)
    assert plan.status == "cost_unknown"
    assert plan.selected is None
    assert all(e.cost is None and e.low is None for e in plan.feasible)
    assert "price_coverage_missing" in plan.reasons


def test_unknown_load_keeps_tariff_bounds_and_ranks_by_them():
    plan = optimize(slots(solar, None, rate=1.0, value=0.4), spec(), None)
    assert plan.status == "cost_unknown"
    assert plan.selected.cost is None
    assert plan.selected.low == pytest.approx(8 * 0.4)
    assert plan.selected.high == pytest.approx(8 * 1.0)
    assert 8 <= plan.selected.start.hour < 14
    assert "cost_bounded_by_tariff_unknown_solar_or_load" in plan.selected.reasons


def test_allowed_local_window_and_latest_start():
    # Local window 09:00-12:00 Europe/Bucharest (UTC+3 in July) = 06:00-09:00 UTC.
    task = spec(
        allowed_window=(9 * 60, 12 * 60),
        latest_start=DAY + timedelta(hours=6, minutes=30),
    )
    plan = optimize(slots(0.0, 1.0), task, None)
    assert [e.start for e in plan.feasible] == [
        DAY + timedelta(hours=6),
        DAY + timedelta(hours=6, minutes=15),
        DAY + timedelta(hours=6, minutes=30),
    ]


# ---------------------------------------------------------------- API flow


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    path = tmp_path_factory.mktemp("planner") / "seed.sqlite3"
    database = Database(path)
    seed_demo(database, PASSWORD)
    with database.connect() as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return path


@pytest.fixture
def database(template, tmp_path):
    path = tmp_path / "test.sqlite3"
    shutil.copyfile(template, path)
    return Database(path)


def client_for(database, username):
    settings = Settings(
        database_path=database.path,
        media_dir=database.path.parent / "media",
        offer_worker=False,
    )
    client = TestClient(create_app(settings))
    client.__enter__()
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client


TASK = {
    "label": "Laundry batch",
    "kind": "laundry_batch",
    "power_kw": 4,
    "energy_kwh": 8,
    "earliest_start": "2026-07-15T13:00:00Z",
    "deadline": "2026-07-15T19:00:00Z",
    "usual_start": "2026-07-15T13:00:00Z",
}


def meter_record(index, start, kw):
    base = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "backend"
            / "fixtures"
            / "telemetry.json"
        ).read_text()
    )
    base.update(
        record_id=f"planner-meter-{index}",
        interval_start=start.isoformat(),
        interval_end=(start + SLOT).isoformat(),
        received_at=(start + SLOT).isoformat(),
    )
    for name, value in (("grid_import", kw), ("grid_export", 0.0)):
        base["measurements"][name] = {
            "value": value,
            "unit": "kW",
            "requirement": "optional",
            "availability": "available",
            "boundary": "ac",
        }
    return base


def test_task_plan_accept_review_and_progress_flow(database):
    start_scenario(database, "planner-test", datetime(2026, 7, 15, 12, 30, tzinfo=UTC))
    customer = client_for(database, "customer")
    other = client_for(database, "other-customer")
    created = customer.post("/api/v1/sites/s6-01/tasks", json=TASK)
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["status"] == "suggested" and task["non_interruptible"] is True
    assert task["duration_minutes"] == 120
    task_id = task["task_id"]
    # Another customer's site and task are indistinguishable from missing ones.
    assert other.get(f"/api/v1/sites/s6-01/plan?task={task_id}").status_code == 404
    assert other.post("/api/v1/sites/s6-01/tasks", json=TASK).status_code == 404
    decision = customer.get(f"/api/v1/sites/s6-01/plan?task={task_id}").json()
    assert decision["clock_mode"] == "scenario"
    assert decision["decided_at"].startswith("2026-07-15T12:30")
    assert decision["forecast"]["issue_time"].startswith("2026-07-15T12:30")
    assert decision["contract_version_id"] == "default-tariff"
    assert "default_tariff_assumed_no_contract" in decision["reason_codes"]
    assert decision["cost_label"] == "estimated"
    assert decision["battery"]["available"] is False
    assert decision["recommended_start"] is not None
    assert decision["status"] in ("recommended", "cost_unknown")
    if decision["estimated_cost_ron"] is None:
        assert decision["cost_range"] is not None
    # A stale recommendation revision is refused.
    stale = customer.post(
        f"/api/v1/sites/s6-01/tasks/{task_id}/accept",
        json={"recommendation_revision": "0000000000000000"},
    )
    assert stale.status_code == 409 and stale.json()["code"] == "recommendation_changed"
    accept = customer.post(
        f"/api/v1/sites/s6-01/tasks/{task_id}/accept",
        json={"recommendation_revision": decision["recommendation_revision"]},
        headers={"Idempotency-Key": "accept-1"},
    )
    assert accept.status_code == 201, accept.text
    accepted = accept.json()
    assert accepted["status"] == "accepted"
    commitment = accepted["commitment"]
    assert commitment["start"] == decision["recommended_start"]
    # The commitment records the baseline it was compared with.
    assert commitment["baseline_kind"] == decision["baseline_kind"]
    assert commitment["baseline_start"] == decision["baseline_start"]
    assert commitment["accepted_at"].startswith("2026-07-15T12:30")
    assert not commitment["accepted_received_at"].startswith("2026-07-15")
    repeat = customer.post(
        f"/api/v1/sites/s6-01/tasks/{task_id}/accept",
        json={"recommendation_revision": decision["recommendation_revision"]},
        headers={"Idempotency-Key": "accept-1"},
    )
    assert repeat.status_code == 200
    assert repeat.json()["commitment"]["commitment_id"] == commitment["commitment_id"]
    # An accepted plan is immutable unless explicitly reviewed.
    edit = customer.post(
        f"/api/v1/sites/s6-01/tasks/{task_id}", json={**TASK, "expected_revision": 1}
    )
    assert edit.status_code == 409 and edit.json()["code"] == "task_committed"
    plan_again = customer.get(f"/api/v1/sites/s6-01/plan?task={task_id}").json()
    assert plan_again["commitment"]["commitment_id"] == commitment["commitment_id"]
    # Measured progress comes from the site's grid meter, with an attribution note.
    run_start = datetime.fromisoformat(commitment["start"])
    for index in range(8):
        ingest(database, meter_record(index, run_start + SLOT * index, 2.0), "test")
    progress = customer.get(f"/api/v1/sites/s6-01/tasks/{task_id}/progress").json()
    assert progress["measured"]["import_coverage"] == 0  # the run has not started yet
    assert "run_not_started" in progress["reason_codes"]
    from backend.clock import advance_scenario

    advance_scenario(database, to=run_start + timedelta(hours=1))
    progress = customer.get(f"/api/v1/sites/s6-01/tasks/{task_id}/progress").json()
    assert progress["status"] == "running"
    assert progress["measured"]["grid_import_kwh"] == pytest.approx(2.0)  # 1 h x 2 kW
    assert progress["measured"]["import_coverage"] == pytest.approx(1.0)
    assert progress["measured"]["source"] == "compact_telemetry"
    assert "PCC" in progress["attribution_note"]
    assert progress["comparison_label"] == "estimated"
    # Release is refused once the run started.
    review = customer.post(
        f"/api/v1/sites/s6-01/tasks/{task_id}/review",
        json={"action": "release", "reason": "changed my mind"},
    )
    assert review.status_code == 409
    advance_scenario(database, to=run_start + timedelta(hours=3))
    done = customer.get("/api/v1/sites/s6-01/tasks").json()
    assert done[0]["status"] == "completed"


def test_review_releases_a_commitment_before_it_starts(database):
    start_scenario(database, "planner-test", datetime(2026, 7, 15, 12, 30, tzinfo=UTC))
    customer = client_for(database, "customer")
    task = customer.post("/api/v1/sites/s6-01/tasks", json=TASK).json()
    decision = customer.get(f"/api/v1/sites/s6-01/plan?task={task['task_id']}").json()
    customer.post(
        f"/api/v1/sites/s6-01/tasks/{task['task_id']}/accept",
        json={"recommendation_revision": decision["recommendation_revision"]},
    )
    released = customer.post(
        f"/api/v1/sites/s6-01/tasks/{task['task_id']}/review",
        json={"action": "release", "reason": "plan review"},
    ).json()
    assert released["status"] == "suggested" and released["commitment"] is None
    assert released["revision"] == 2
    # Staff may read the plan of a site in their area but cannot write customer tasks.
    staff = client_for(database, "dispatcher")
    assert (
        staff.get(f"/api/v1/sites/s6-01/plan?task={task['task_id']}").status_code == 200
    )
    assert staff.post("/api/v1/sites/s6-01/tasks", json=TASK).status_code == 403
    # CSRF is required on writes.
    customer.headers.pop("X-CSRF-Token")
    assert customer.post("/api/v1/sites/s6-01/tasks", json=TASK).status_code == 403


def test_task_validation_rejects_unaware_and_impossible_windows(database):
    customer = client_for(database, "customer")
    bad = {**TASK, "earliest_start": "2026-07-15T13:00:00"}
    assert customer.post("/api/v1/sites/s6-01/tasks", json=bad).status_code == 422
    short = {**TASK, "deadline": "2026-07-15T14:00:00Z"}
    assert customer.post("/api/v1/sites/s6-01/tasks", json=short).status_code == 422
