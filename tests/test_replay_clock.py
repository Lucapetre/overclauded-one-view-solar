"""Unified analytical clock: live default, forward-only scenario, offers on scenario time."""

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.__main__ import main
from backend.clock import (
    advance_scenario,
    age_seconds,
    analytical_now,
    clock_state,
    parse_duration,
    start_scenario,
)
from backend.config import Settings
from backend.db import Database
from backend.errors import ApiError
from backend.ingestion import ingest
from backend.main import create_app
from backend.offers_worker import settle_due
from backend.seed import seed_demo

PASSWORD = "test-password-only"
START = datetime(2026, 7, 15, 12, 15, tzinfo=UTC)
BASE = json.loads(
    (
        Path(__file__).resolve().parents[1] / "backend" / "fixtures" / "telemetry.json"
    ).read_text()
)


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    path = tmp_path_factory.mktemp("clock") / "seed.sqlite3"
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


def login(app, username):
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client


@pytest.fixture
def app(database):
    settings = Settings(
        database_path=database.path,
        media_dir=database.path.parent / "m",
        offer_worker=False,
    )
    application = create_app(settings)
    with TestClient(application):
        yield application


def test_live_mode_is_wall_time_and_settings_default_reads_the_database(database):
    settings = Settings(database_path=database.path, offer_worker=False)
    before = datetime.now(UTC)
    assert before - timedelta(seconds=1) <= settings.clock() <= datetime.now(UTC)
    with database.connect() as connection:
        assert clock_state(connection).mode == "live"
    start_scenario(database, "clock-test", START)
    assert settings.clock() == START
    # Explicitly injected clocks (tests) still win.
    assert Settings(
        database_path=database.path, clock=lambda: START - timedelta(1)
    ).clock() == START - timedelta(1)
    # A database that does not exist yet means live wall time.
    missing = Settings(database_path=database.path.parent / "absent.sqlite3")
    assert abs((missing.clock() - datetime.now(UTC)).total_seconds()) < 5
    assert not (database.path.parent / "absent.sqlite3").exists()


def test_scenario_is_forward_only_and_restart_needs_a_new_database(database):
    started = start_scenario(database, "clock-test", START)
    assert started["status"] == "started" and started["mode"] == "scenario"
    assert start_scenario(database, "clock-test", START)["status"] == "already_running"
    with pytest.raises(ApiError) as error:
        start_scenario(database, "clock-test", START - timedelta(hours=1))
    assert error.value.code == "scenario_running"
    moved = advance_scenario(database, by=parse_duration("30m"))
    assert moved["analytical_now"].startswith("2026-07-15T12:45")
    assert (
        advance_scenario(database, to=START + timedelta(minutes=30))["status"]
        == "unchanged"
    )
    with pytest.raises(ApiError) as error:
        advance_scenario(database, to=START)
    assert error.value.code == "rewind_refused"
    with pytest.raises(ApiError):
        parse_duration("-5m")
    with database.connect() as connection:
        assert analytical_now(connection) == START + timedelta(minutes=30)
        assert age_seconds(connection, START) == 1800
        steps = connection.execute(
            "SELECT COUNT(*) FROM scenario_clock_events"
        ).fetchone()[0]
        audit = connection.execute(
            "SELECT received_at, detail FROM audit WHERE action='scenario.advanced'"
        ).fetchone()
    assert steps == 2
    # The audit row keeps real receipt time; the event time is in its detail.
    assert not audit["received_at"].startswith("2026-07-15")
    assert json.loads(audit["detail"])["to"].startswith("2026-07-15T12:45")


def test_cli_scenario_commands_and_replay_clock_guard(database, monkeypatch, capsys):
    monkeypatch.setenv("SOLAR_DATABASE", str(database.path))
    main(["scenario", "start", "cli-test", "--at", "2026-07-15T15:15:00+03:00"])
    status = json.loads(capsys.readouterr().out)
    assert status["analytical_now"].startswith("2026-07-15T12:15")
    main(["scenario", "advance", "--by", "2h", "--settle"])
    result = json.loads(capsys.readouterr().out)
    assert result["analytical_now"].startswith("2026-07-15T14:15")
    assert set(result["offers_worker"]) == {
        "expired_offers",
        "progressed",
        "settled",
        "reminders",
    }
    with pytest.raises(SystemExit) as exit_info:
        main(["scenario", "advance", "--to", "2026-07-15T10:00:00Z"])
    assert exit_info.value.code == 2
    assert "rewind_refused" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["replay-clock", "2026-07-15T10:00:00Z"])
    main(["replay-clock", "2026-07-15T15:00:00Z"])
    assert "advanced" in capsys.readouterr().out
    main(["scenario", "status"])
    assert json.loads(capsys.readouterr().out)["advances"] == 3


def test_scenario_start_refuses_to_rewind_over_existing_financial_state(database):
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO user_offers(user_offer_id,offer_id,user_id,site_id,type,energy_kwh,"
            "offer_price_ron_per_kwh,window_minutes,penalty_type,penalty_value,"
            "reference_price_ron_per_kwh,reference_price_source,status,accepted_at,"
            "window_start,window_end) VALUES ('uo','demo-offer-s6-consume','customer','s6-01',"
            "'consume','5','0.5',120,'flat','0','1.3','default_tariff','accepted',?,?,?)",
            ("2026-07-16T10:00:00+00:00",) * 3,
        )
    with pytest.raises(ApiError) as error:
        start_scenario(database, "late", START)
    assert error.value.code == "would_rewind"


def record(index, start, kw, minutes=15):
    payload = json.loads(json.dumps(BASE))
    payload.update(
        record_id=f"clock-meter-{index}",
        interval_start=start.isoformat(),
        interval_end=(start + timedelta(minutes=minutes)).isoformat(),
        received_at=(start + timedelta(minutes=minutes)).isoformat(),
    )
    payload["measurements"]["grid_import"] = {
        "value": kw,
        "unit": "kW",
        "requirement": "optional",
        "availability": "available",
        "boundary": "ac",
    }
    return payload


def counts(database):
    with database.connect() as connection:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("notifications", "offer_settlements", "user_offers")
        }


def test_offers_accept_progress_and_settle_on_the_scenario_clock(database, app):
    start_scenario(database, "offers-clock", START)
    customer = login(app, "customer")
    offers = customer.get("/api/v1/offers").json()
    consume = next(o for o in offers if o["type"] == "consume")
    accepted = customer.post(
        f"/api/v1/offers/{consume['offer_id']}/accept", json={"site_id": "s6-01"}
    )
    assert accepted.status_code == 201, accepted.text
    view = accepted.json()
    assert view["accepted_at"].startswith("2026-07-15T12:15")
    with database.connect() as connection:
        audit = connection.execute(
            "SELECT received_at, detail FROM audit WHERE action='offer.accepted'"
        ).fetchone()
    detail = json.loads(audit["detail"])
    assert detail["accepted_at"].startswith("2026-07-15T12:15")
    assert detail["clock"] == "scenario"
    assert not audit["received_at"].startswith("2026-07-15")  # real receipt time
    window_end = datetime.fromisoformat(view["window_end"])
    energy = float(view["energy_kwh"])
    hours = (window_end - START).total_seconds() / 3600
    # July meter data for the whole window exists, but only the elapsed part is known.
    power = energy / hours * 1.2
    cursor, index = START, 0
    while cursor < window_end:
        ingest(database, record(index, cursor, power), "clock-test")
        cursor += timedelta(minutes=15)
        index += 1
    first = settle_due(database, settings=Settings(database_path=database.path))
    assert first["settled"] == 0
    mine = customer.get("/api/v1/offers/mine").json()[0]
    assert float(mine["metered_kwh"]) == 0  # nothing after the scenario clock is read
    advance_scenario(database, to=START + timedelta(minutes=30))
    settle_due(database, settings=Settings(database_path=database.path))
    mine = customer.get("/api/v1/offers/mine").json()[0]
    assert 0 < float(mine["metered_kwh"]) < energy
    advance_scenario(database, to=window_end)
    summary = settle_due(database, settings=Settings(database_path=database.path))
    assert summary["settled"] == 1
    before = counts(database)
    # Repeated passes at the same analytical time add no notification or ledger row.
    for _ in range(3):
        assert (
            settle_due(database, settings=Settings(database_path=database.path))[
                "settled"
            ]
            == 0
        )
    assert counts(database) == before
    with database.connect() as connection:
        settled = connection.execute(
            "SELECT outcome, settled_at FROM offer_settlements"
        ).fetchone()
    assert settled["outcome"] == "completed"
    assert settled["settled_at"].startswith(window_end.strftime("%Y-%m-%dT%H"))


def test_freshness_uses_the_scenario_clock(database, app):
    customer = login(app, "customer")
    live = customer.get("/api/v1/sites/s6-01/energy/latest").json()["freshness"]
    assert live["clock"] == "replay"  # seeded synthetic records use the replay setting
    start_scenario(database, "fresh", START + timedelta(hours=2))
    view = customer.get("/api/v1/sites/s6-01/energy/latest").json()["freshness"]
    assert view["clock"] == "replay" and view["status"] == "stale"
    assert view["evaluated_at"].startswith("2026-07-15T14:15")
    clock = customer.get("/api/v1/clock").json()
    assert clock["mode"] == "scenario" and clock["scenario_id"] == "fresh"
    assert clock["analytical_now"].startswith("2026-07-15T14:15")
    assert not clock["wall_now"].startswith("2026-07-15")
