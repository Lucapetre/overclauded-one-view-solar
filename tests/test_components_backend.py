"""Component scenario backend: provisioning, import, bridge capabilities, offers metering."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import bridge
from backend.clock import start_scenario
from backend.components import import_component_snapshot
from backend.config import Settings
from backend.db import Database
from backend.errors import ApiError
from backend.main import create_app
from backend.models import Metric, Site, SiteRegistration, User
from backend.offers import accept_offer, create_offer, my_offers, publish_offer
from backend.offers_models import OfferDraft
from backend.offers_worker import settle_due
from backend.planner import plan
from backend.providers import backend_site_id
from backend.provisioning import register_site
from backend.security import accessible_sites
from backend.seed import PLACEMENTS, seed_component_scenario
from engine.storage import Store

ROOT = Path(__file__).resolve().parents[1]
SITES = ROOT / "demo_data" / "sites.json"
PASSWORD = "test-password-only"
REGISTRY = json.loads(SITES.read_text(encoding="utf-8"))
KEYS = {
    site["demo_site_key"]: backend_site_id(
        "|".join(str(site[k]) for k in ("provider", "account_id", "site_id"))
    )
    for site in REGISTRY["sites"]
}


def registration(site_id: str) -> SiteRegistration:
    """The same registration shape import-provider uses (no area, unknown topology)."""
    return SiteRegistration(
        site=Site(
            site_id=site_id,
            alias=site_id,
            area_id=None,
            topology_mode="unknown",
            reporting_interval_seconds=900,
            stale_after_seconds=2700,
            capabilities=["pv_power"],
            measurement_requirements={"pv_power": "mandatory"},
        ),
        device_id="stream-" + site_id,
        source_id="phase1-scraper",
    )


@pytest.fixture
def provider_db(tmp_path):
    database = Database(tmp_path / "scenario.sqlite3")
    database.migrate()
    for site_id in KEYS.values():
        register_site(database, registration(site_id))
    return database


def test_provisioning_places_sites_and_grants_explicitly_and_is_idempotent(provider_db):
    with provider_db.connect() as connection:
        before = connection.execute("SELECT COUNT(*) FROM user_sites").fetchone()[0]
    assert before == 0  # registering (importing) sites grants nobody access
    credentials = seed_component_scenario(provider_db, PASSWORD, SITES)
    assert set(credentials) == {
        "laundry-owner",
        "h2-resident",
        "scenario-supervisor",
        "scenario-dispatcher",
    }
    assert seed_component_scenario(provider_db, PASSWORD, SITES) == {}
    with provider_db.connect() as connection:
        placements = {
            row["site_id"]: dict(row)
            for row in connection.execute("SELECT * FROM site_placements")
        }
        areas = dict(
            connection.execute("SELECT site_id, area_id FROM sites").fetchall()
        )
        owner = User(user_id="laundry-owner", username="laundry-owner", role="customer")
        resident = User(user_id="h2-resident", username="h2-resident", role="customer")
        staff = User(
            user_id="scenario-dispatcher",
            username="scenario-dispatcher",
            role="dispatcher",
        )
        owner_sites = [row["site_id"] for row in accessible_sites(connection, owner)]
        resident_sites = [
            row["site_id"] for row in accessible_sites(connection, resident)
        ]
        staff_sites = {row["site_id"] for row in accessible_sites(connection, staff)}
        task = connection.execute("SELECT * FROM planner_tasks").fetchone()
        contract = connection.execute("SELECT * FROM contracts").fetchone()
    assert len(placements) == 9
    for key, area, *_ in PLACEMENTS:
        placement = placements[KEYS[key]]
        assert placement["area_id"] == area == areas[KEYS[key]]
        assert placement["coordinates_fictional"] == 1
        assert "Fictional" in placement["location_label"]
    assert placements[KEYS["F1"]]["segment"] == "business"
    assert owner_sites == [KEYS["F1"]]
    assert resident_sites == [KEYS["H2"]]
    assert staff_sites == set(KEYS.values())
    assert task["site_id"] == KEYS["F1"] and task["power_kw"] == 4.0
    assert contract["pricing"] == "time_of_use"
    # A repeated import of the same provider site still matches its registered contract.
    register_site(provider_db, registration(KEYS["F1"]))


def test_provisioning_requires_imported_provider_sites(tmp_path):
    database = Database(tmp_path / "empty.sqlite3")
    database.migrate()
    from backend.errors import ApiError

    with pytest.raises(ApiError) as error:
        seed_component_scenario(database, PASSWORD, SITES)
    assert error.value.code == "provider_sites_missing"


# ---------------------------------------------------------------- a small component snapshot

DAY = datetime(2026, 7, 17, tzinfo=UTC)
ALARM = datetime(2026, 7, 18, 6, 40, tzinfo=UTC)
F1, F2, H2, S3 = (KEYS[k] for k in ("F1", "F2", "H2", "S3"))
SITE_KEYS = {
    site["demo_site_key"]: "|".join(
        str(site[k]) for k in ("provider", "account_id", "site_id")
    )
    for site in REGISTRY["sites"]
}
META = {
    "snapshot_kind": "component_snapshot",
    "scenario_version": "components-test-1",
    "as_of_utc": "2026-07-21T21:00:00+00:00",
    "config_hash": "c",
    "engine_hash": "e",
    "input_manifest_sha256": "m",
    "asset_registry_sha256": "a",
    "families": "all",
    "synthetic": "true",
}
B1 = {
    "conversion_boundary": "AC-coupled via a separate battery inverter (test)",
    "rated_power_kw": 3.0,
    "declared": {
        "nominal_voltage_v": 51.2,
        "capacity_basis_kwh": 10.24,
        "reserve_soc_pct": 20.0,
        "eta_charge_ac_to_storage": 0.95,
        "eta_discharge_storage_to_ac": 0.95,
        "battery_inverter_rating_kw": 3.0,
    },
    "declared_nominal_limits": {
        "battery_max_charge_current_a": 70.0,
        "battery_max_discharge_current_a": 100.0,
    },
    "collector": {"path": "secret internal path"},
}
ASSETS = [
    ("F1-M1", "F1", "meter", "m1", "production", "grid_pcc", {}),
    ("F1-B1", "F1", "battery", "b1", "production", "dc_battery", B1),
    (
        "F1-W1",
        "F1",
        "weather",
        "w1",
        "production",
        "sensor_plane",
        {"mounting": {"plane": "poa", "tilt_deg": 35, "azimuth_deg": 180}},
    ),
    ("F2-M2", "F2", "meter", "m2", "production", "grid_pcc", {}),
    ("H2-M3", "H2", "meter", "m3", "production", "grid_pcc", {}),
    ("S3-B2", "S3", "battery", "b2", "production", "dc_battery", {"rated_power_kw": 5}),
    ("EQ-M1", "F1", "meter", "m1", "test_only", "grid_pcc", {}),
]
CAPABILITIES = [
    ("F1", "grid_energy_measured", "available"),
    ("F1", "battery_limits_available", "available"),
    ("F1", "battery_soc_available", "available"),
    ("F2", "grid_energy_measured", "available"),
    ("H2", "grid_energy_measured", "available"),
    ("S3", "battery_soc_available", "available"),
    ("S3", "battery_limits_available", "not_declared"),
]
GRID = {"F1": (1.5, 0.5), "F2": (1.0, 0.0), "H2": (1.5, 0.0)}
METERS = {"F1": "F1-M1", "F2": "F2-M2", "H2": "H2-M3"}


def iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def ms(moment):
    return int(moment.timestamp() * 1000)


def _grid_row(key, metric, start, value):
    status, origin, mirrors, value_kwh = "selected_primary", "measured", "[]", value
    if key == "F2":
        mirrors = json.dumps(["GetPowerFlowRealtimeData"])
        if start.hour == 10 and start.minute >= 30:
            status, origin = "selected_mirror_fallback", "estimated"
    if key == "H2" and start.hour == 11 and start.minute < 45:
        status, origin, value_kwh = "no_complete_source", None, None
    return (
        SITE_KEYS[key],
        key,
        "grid_pcc",
        metric,
        iso(start),
        iso(start + timedelta(minutes=15)),
        ms(start),
        value_kwh,
        METERS[key],
        origin,
        status,
        mirrors,
    )


def _frame(key, asset, family, metric, start, value, aggregation, **extra):
    return (
        SITE_KEYS[key],
        key,
        "ep",
        family,
        asset,
        metric,
        extra.get("channel"),
        "b",
        extra.get("mounting"),
        aggregation,
        iso(start),
        iso(start + timedelta(minutes=15)),
        ms(start),
        value,
        iso(start + timedelta(minutes=10)),
        extra.get("unit", "pct"),
        3,
        1.0,
        "simulated_observation",
        "ok",
    )


def build_snapshot(path: Path, **meta) -> Path:
    store = Store(path, extended=True)
    con = store.con
    con.executemany(
        "INSERT INTO component_meta VALUES (?,?)", list((META | meta).items())
    )
    con.execute(
        "INSERT INTO runs(run_id,finished_at_utc,as_of_utc,status) "
        "VALUES ('r','2026-11-15',?,'completed')",
        (META["as_of_utc"],),
    )
    for key, site_key in SITE_KEYS.items():
        con.execute(
            "INSERT INTO site_registry(site_key,kind,demo_site_key,backend_site_id,json) "
            "VALUES (?,?,?,?,?)",
            (site_key, "site", key, backend_site_id(site_key), "{}"),
        )
    for asset_id, key, family, profile, role, boundary, details in ASSETS:
        con.execute(
            "INSERT INTO asset_registry VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                asset_id,
                SITE_KEYS[key],
                key,
                family,
                profile,
                asset_id,
                role,
                boundary,
                None,
                json.dumps(details),
            ),
        )
    con.executemany(
        "INSERT INTO capability_registry(site_key,demo_site_key,capability,declared,state) "
        "VALUES (?,?,?,?,?)",
        [(SITE_KEYS[k], k, c, int(s != "not_declared"), s) for k, c, s in CAPABILITIES],
    )
    grid_rows, frames = [], []
    for index in range(2 * 96):
        start = DAY + timedelta(minutes=15 * index)
        for key, (imported, exported) in GRID.items():
            grid_rows.append(
                _grid_row(key, "interval_grid_import_kwh", start, imported)
            )
            grid_rows.append(
                _grid_row(key, "interval_grid_export_kwh", start, exported)
            )
        derated = start >= ALARM
        frames += [
            _frame("F1", "F1-B1", "battery", "soc_pct", start, 60.0, "last_valid"),
            _frame(
                "F1",
                "F1-B1",
                "battery",
                "battery_capacity_ah",
                start,
                200.0,
                "last_valid",
            ),
            _frame(
                "F1",
                "F1-B1",
                "battery",
                "battery_max_charge_current_a",
                start,
                70.0,
                "last_valid",
            ),
            _frame(
                "F1",
                "F1-B1",
                "battery",
                "battery_max_discharge_current_a",
                start,
                25.0 if derated else 100.0,
                "last_valid",
            ),
            _frame(
                "F1",
                "F1-B1",
                "battery",
                "battery_alarm_raw",
                start,
                2.0 if derated else 0.0,
                "last",
                channel="internal_failure",
                unit="none",
            ),
            _frame(
                "F1",
                "F1-B1",
                "battery",
                "battery_net_kw",
                start,
                0.0,
                "mean",
                unit="kW",
            ),
            _frame(
                "F1",
                "F1-W1",
                "weather",
                "irradiance_wm2",
                start,
                500.0,
                "mean",
                unit="W/m2",
                mounting="poa",
            ),
            _frame("S3", "S3-B2", "battery", "soc_pct", start, 55.0, "last_valid"),
        ]
    con.executemany(
        "INSERT INTO authority_frames(site_key,demo_site_key,boundary,metric_name,"
        "frame_start_utc,frame_end_utc,frame_start_ms,value_kwh,selected_asset_id,"
        "value_origin,authority_status,mirrors_excluded) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        grid_rows,
    )
    con.executemany(
        "INSERT INTO component_frames(site_key,demo_site_key,endpoint_key,family,"
        "physical_asset_id,metric_name,channel,boundary,mounting,frame_aggregation,"
        "frame_start_utc,frame_end_utc,frame_start_ms,value,value_time_utc,unit,n_obs,"
        "coverage_ratio,value_origin,frame_status) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        frames,
    )
    store.close()  # WAL mode: committed pages may still sit in the -wal file
    return path


@pytest.fixture
def scenario_db(provider_db, tmp_path):
    seed_component_scenario(provider_db, PASSWORD, SITES)
    snapshot = build_snapshot(tmp_path / "build" / "component.sqlite")
    result = import_component_snapshot(provider_db, snapshot)
    assert result["status"] == "imported"
    return provider_db, snapshot, result


def counts(database):
    with database.connect() as connection:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("notifications", "offer_settlements", "user_offers")
        }


def test_import_is_idempotent_atomic_wal_safe_and_grants_nothing(provider_db, tmp_path):
    snapshot = build_snapshot(tmp_path / "build" / "component.sqlite")
    # An open writer keeps its last commit only in the WAL; backup() must include it.
    writer = sqlite3.connect(snapshot)
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute(
        "UPDATE authority_frames SET value_kwh=2.5 WHERE demo_site_key='F1' "
        "AND metric_name='interval_grid_import_kwh' AND frame_start_utc=?",
        ("2026-07-17T10:00:00.000Z",),
    )
    writer.commit()
    first = import_component_snapshot(provider_db, snapshot)
    writer.close()
    assert first["status"] == "imported" and len(first["sites"]) == 9
    assert first["grid_frames"] == 3 * 2 * 192
    again = import_component_snapshot(provider_db, snapshot)
    assert again["status"] == "duplicate" and again["import_id"] == first["import_id"]
    with provider_db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM user_sites").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM user_areas").fetchone()[0] == 0
        assets = [
            r[0] for r in connection.execute("SELECT asset_id FROM component_assets")
        ]
        details = connection.execute(
            "SELECT details FROM component_assets WHERE asset_id='F1-B1'"
        ).fetchone()[0]
        wal_value = connection.execute(
            "SELECT value_kwh FROM component_grid_frames WHERE site_id=? AND "
            "metric='grid_import' AND frame_start LIKE '2026-07-17T10:00:00%'",
            (F1,),
        ).fetchone()[0]
    assert wal_value == 2.5
    assert "EQ-M1" not in assets  # test-only encodings are never imported
    assert "secret internal path" not in details
    folder = provider_db.path.parent / "component-snapshots"
    stored = folder / f"{first['import_id']}.sqlite"
    assert stored.is_file() and not list(folder.glob("*.partial"))
    # A new snapshot switches every site in one transaction; the old file is kept.
    newer = build_snapshot(tmp_path / "build2" / "component.sqlite", engine_hash="e2")
    second = import_component_snapshot(provider_db, newer)
    assert second["status"] == "imported" and second["import_id"] != first["import_id"]
    with provider_db.connect() as connection:
        active = {
            r[0]
            for r in connection.execute(
                "SELECT DISTINCT import_id FROM component_sites"
            )
        }
    assert active == {second["import_id"]} and stored.is_file()
    # "Restart": a fresh Database object over the same file sees the same active import.
    with Database(provider_db.path).connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM component_sites WHERE import_id=?",
                (second["import_id"],),
            ).fetchone()[0]
            == 9
        )


def test_import_requires_registered_provider_sites(tmp_path):
    database = Database(tmp_path / "fresh.sqlite3")
    snapshot = build_snapshot(tmp_path / "build" / "component.sqlite")
    with pytest.raises(ApiError) as error:
        import_component_snapshot(database, snapshot)
    assert error.value.code == "provider_sites_missing"


def test_capability_degradation_limits_alarm_and_missing_weather(scenario_db):
    database, _, _ = scenario_db
    before = datetime(2026, 7, 18, 6, 0, tzinfo=UTC)
    after = datetime(2026, 7, 18, 7, 30, tzinfo=UTC)
    with database.connect() as connection:
        healthy = bridge.battery_capability(connection, F1, before)
        assert healthy.params is not None
        # Minimum of BMS DC limits (converted) and the 3 kW battery inverter rating.
        assert healthy.params.discharge_limit_kw == pytest.approx(3.0)
        assert healthy.params.charge_limit_kw == pytest.approx(3.0)
        assert healthy.params.reserve_pct == 20.0 and healthy.params.soc_pct == 60.0
        alarmed = bridge.battery_capability(connection, F1, after)
        assert alarmed.params is None
        assert "battery_alarm_active_restricted" in alarmed.reason_codes
        assert "battery_limit_derated_by_bms" in alarmed.reason_codes
        limited = bridge.battery_capability(connection, S3, before)
        assert limited.params is None
        assert "battery_limits_unavailable" in limited.reason_codes
        # H2 has no irradiance sensor; F1's POA sensor keeps its registered plane.
        assert (
            bridge.irradiance_recent(
                connection, H2, before - timedelta(hours=1), before
            )
            is None
        )
        poa = bridge.irradiance_recent(
            connection, F1, before - timedelta(hours=1), before
        )
        assert poa.plane == (35.0, 180.0) and len(poa.samples) == 4


def client_for(database, username):
    settings = Settings(
        database_path=database.path,
        media_dir=database.path.parent / "m",
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


def test_equipment_api_is_scoped_bounded_and_hides_internals(scenario_db):
    database, _, result = scenario_db
    start_scenario(database, "equipment", datetime(2026, 7, 18, 6, 0, tzinfo=UTC))
    owner = client_for(database, "laundry-owner")
    resident = client_for(database, "h2-resident")
    staff = client_for(database, "scenario-supervisor")
    response = owner.get(f"/api/v1/sites/{F1}/equipment/summary")
    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["clock_mode"] == "scenario" and summary["source_mode"] == "synthetic"
    assert summary["import_id"] == result["import_id"]
    families = {f["family"]: f for f in summary["families"]}
    assert families["meter"]["selected_source"] == "F1-M1"
    assert families["battery"]["availability"] == "available"
    decisions = {c["capability"]: c for c in summary["capabilities"]}
    assert decisions["grid_energy_verified"]["available"] is True
    assert decisions["battery_assisted_planning"]["available"] is True
    assert decisions["irradiance_explanation"]["available"] is True
    assert "component-snapshots" not in response.text
    assert "secret internal path" not in response.text
    # Out-of-scope sites are indistinguishable from missing ones.
    assert resident.get(f"/api/v1/sites/{F1}/equipment/summary").status_code == 404
    query = {"from": "2026-07-17T00:00:00Z", "to": "2026-07-19T00:00:00Z"}
    path = f"/api/v1/sites/{F1}/equipment/evidence"
    assert resident.get(path, params=query).status_code == 404
    evidence = staff.get(path, params={**query, "family": "battery", "limit": 5}).json()
    assert evidence["limit"] == 5 and len(evidence["items"]) == 5
    # Six battery series up to the scenario clock (day 1 plus six hours of day 2).
    assert evidence["total"] == 6 * (96 + 24)
    late = staff.get(path, params={**query, "family": "battery", "offset": 715}).json()
    assert all(item["frame_end"] <= "2026-07-18T06:00:00Z" for item in late["items"])
    too_long = {"from": "2026-07-01T00:00:00Z", "to": "2026-07-19T00:00:00Z"}
    assert staff.get(path, params=too_long).status_code == 422
    other = resident.get(f"/api/v1/sites/{H2}/equipment/summary").json()
    decisions = {c["capability"]: c for c in other["capabilities"]}
    assert decisions["battery_assisted_planning"]["available"] is False
    assert (
        "no_compatible_irradiance_sensor"
        in decisions["irradiance_explanation"]["reason_codes"]
    )


SUPERVISOR = User(
    user_id="scenario-supervisor", username="scenario-supervisor", role="supervisor"
)
OWNER = User(user_id="laundry-owner", username="laundry-owner", role="customer")
RESIDENT = User(user_id="h2-resident", username="h2-resident", role="customer")
F2_OWNER = User(user_id="f2-owner", username="f2-owner", role="customer")
WINDOW = datetime(2026, 7, 17, 10, 0, tzinfo=UTC)


def offer(database, kind="consume", energy="10"):
    draft = OfferDraft(
        type=kind,
        title="Component test block",
        energy_kwh=energy,
        offer_price_ron_per_kwh="0.55",
        window_minutes=120,
        penalty_type="per_unfulfilled_kwh",
        penalty_value="0.3",
        offer_expires_at=WINDOW + timedelta(days=1),
        area_id="sector-1",
    )
    with database.connect() as connection:
        offer_id = create_offer(
            database, connection, SUPERVISOR, draft, "t", WINDOW
        ).offer_id
    with database.connect() as connection:
        publish_offer(database, connection, SUPERVISOR, offer_id, "t", WINDOW)
    return offer_id


def take(database, offer_id, user, site_id):
    with database.connect() as connection:
        accept_offer(
            database, connection, user, offer_id, site_id, None, "t", WINDOW, 3
        )


def mine(database, user):
    with database.connect() as connection:
        return {row.offer_id: row for row in my_offers(connection, user, "all")}


def test_offers_settle_from_component_meter_direction_and_waive_gaps(scenario_db):
    database, _, _ = scenario_db
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO users(user_id,username,password_hash,role) "
            "VALUES ('f2-owner','f2-owner','x','customer')"
        )
        connection.execute("INSERT INTO user_sites VALUES ('f2-owner',?)", (F2,))
    consume = offer(database)
    export = offer(database, "export", "2")
    # F1's inverter data has no grid meter; its imported PCC meter makes it eligible.
    take(database, consume, OWNER, F1)
    take(database, export, OWNER, F1)
    take(database, consume, RESIDENT, H2)
    take(database, consume, F2_OWNER, F2)
    settings = Settings(database_path=database.path, offer_worker=False)
    end = WINDOW + timedelta(hours=3, minutes=30)
    assert settle_due(database, end, settings)["settled"] == 4
    before = counts(database)
    # Consume from grid_import (8 x 1.5 kWh), export from grid_export (8 x 0.5 kWh).
    f1 = mine(database, OWNER)
    assert f1[consume].status == "completed" and Decimal(f1[consume].metered_kwh) == 12
    assert f1[export].status == "completed" and Decimal(f1[export].metered_kwh) == 4
    # H2: three unknown intervals -> coverage 5/8 < 0.8 -> the penalty is waived.
    h2 = mine(database, RESIDENT)[consume]
    assert h2.status == "partial" and Decimal(h2.metered_kwh) == Decimal("7.5")
    assert h2.settlement.penalty_waived_reason == "meter_data_incomplete"
    # F2: the gateway mirror is never added; estimated mirror-fallback frames are not
    # settlement energy, so only the six measured primary intervals count.
    f2 = mine(database, F2_OWNER)[consume]
    assert Decimal(f2.metered_kwh) == 6
    for _ in range(2):  # repeated worker passes: no new ledger rows or notifications
        assert settle_due(database, end, settings)["settled"] == 0
    assert counts(database) == before


def test_scenario_clock_hides_future_component_energy(scenario_db):
    database, _, _ = scenario_db
    start_scenario(database, "meter-cap", WINDOW + timedelta(minutes=30))
    with database.connect() as connection:
        series = bridge.meter_series(
            connection, F1, Metric.grid_import, WINDOW, WINDOW + timedelta(hours=2)
        )
    assert series.source == "component_meter" and series.boundary == "grid_pcc"
    assert len(series.intervals) == 2 and series.energy_kwh() == pytest.approx(3.0)


def test_planner_uses_battery_only_when_the_bridge_allows_it(scenario_db):
    database, _, _ = scenario_db
    start_scenario(database, "plan", datetime(2026, 7, 17, 4, 30, tzinfo=UTC))
    with database.connect() as connection:
        decision = plan(connection, OWNER, F1, "f1-laundry-batch-2026-07-17")
        later = bridge.battery_capability(
            connection, F1, datetime(2026, 7, 18, 7, 0, tzinfo=UTC)
        )
    assert decision.battery.available is True
    assert decision.battery.discharge_limit_kw == pytest.approx(3.0)
    assert decision.contract_version_id.startswith("cv-")
    assert decision.forecast.recent_source == "poa_irradiance"
    assert any(item.source == "component_pcc_meter" for item in decision.freshness)
    assert later.params is None and "grid_solar_only_plan" in later.reason_codes


def test_one_plane_statement_for_irradiance_and_performance(scenario_db):
    from backend.components import capability_decisions, module_plane_match

    database, _, _ = scenario_db
    h2, f1 = KEYS["H2"], KEYS["F1"]
    with database.connect() as connection:
        # The shared area station plane (30/180) is not H2's east/west 15-degree plane.
        assert (
            module_plane_match(connection, h2, (30.0, 180.0))
            == "differs_from_module_plane"
        )
        assert module_plane_match(connection, f1, (35.0, 180.0)) == "module_plane"
        assert module_plane_match(connection, f1, None) == "unknown"
        decisions = {
            d.capability: d
            for d in capability_decisions(connection, f1, WINDOW + timedelta(hours=2))
        }
    irradiance = decisions["irradiance_explanation"].reason_codes
    review = decisions["pv_performance_review"].reason_codes
    assert "poa_irradiance_on_registered_plane" in irradiance
    assert "sensor_plane_differs_from_module_plane" not in review
