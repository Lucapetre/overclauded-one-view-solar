"""Power Block Offers: scope, targeting, acceptance, metering, settlement and counters.

Most tests call the service layer with explicit UTC times; two tests drive the HTTP API.
"""

import json
import shutil
import threading
import time
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.__main__ import main
from backend.config import Settings
from backend.db import Database
from backend.errors import ApiError
from backend.ingestion import ingest
from backend.main import create_app
from backend.models import User
from backend.offers import (
    accept_offer,
    cancel_offer,
    client_offers,
    create_offer,
    list_manager_offers,
    list_notifications,
    manager_offer_detail,
    my_offers,
    offer_audit,
    preview_draft,
    publish_offer,
    update_offer,
)
from backend.offers_models import OfferDraft
from backend.offers_worker import reconcile, settle_due, simulate_offer_meter
from backend.seed import seed_demo

PASSWORD = "test-password-only"
SUPERVISOR = User(user_id="supervisor", username="supervisor", role="supervisor")
AREA_MANAGER = User(user_id="area-manager", username="area-manager", role="supervisor")
CUSTOMER = User(user_id="customer", username="customer", role="customer")
# Acceptance times are explicit; the seeded demo offers stay open for 7 wall-clock days.
T = (datetime.now(UTC) + timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
BASE = json.loads(
    (
        Path(__file__).resolve().parents[1] / "backend" / "fixtures" / "telemetry.json"
    ).read_text()
)
DEMO = {"demo-offer-s6-consume", "demo-offer-s6-export", "demo-offer-s6-draft"}
MANAGER = "/api/v1/manager/offers"


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    path = tmp_path_factory.mktemp("offers") / "seed.sqlite3"
    database = Database(path)
    seed_demo(database, PASSWORD)
    with database.connect() as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return path


@pytest.fixture
def database(template, tmp_path):
    """A private copy of one seeded database (seeding hashes several passwords)."""
    path = tmp_path / "test.sqlite3"
    shutil.copyfile(template, path)
    return Database(path)


class Clock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock():
    return Clock(T)


@pytest.fixture
def app(database, clock):
    settings = Settings(
        database_path=database.path,
        media_dir=database.path.parent / "media",
        offer_worker=False,
        clock=clock,
    )
    application = create_app(settings)
    with TestClient(application):
        yield application


def login(app, username: str) -> TestClient:
    """A separate cookie jar per account; CSRF is sent by default."""
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client


def worker(database: Database, now: datetime) -> dict:
    return settle_due(
        database, now, Settings(database_path=database.path, offer_worker=False)
    )


def draft(**changes) -> OfferDraft:
    terms = {
        "type": "consume",
        "title": "Test block",
        "energy_kwh": "10",
        "offer_price_ron_per_kwh": "0.55",
        "window_minutes": 120,
        "penalty_type": "per_unfulfilled_kwh",
        "penalty_value": "0.3",
        "offer_expires_at": T + timedelta(days=1),
        "area_id": "sector-6",
    }
    return OfferDraft(**(terms | changes))


def body(**changes) -> dict:
    return draft(**changes).model_dump(mode="json")


def make_offer(database, publish=True, user=SUPERVISOR, now=T, **changes) -> str:
    with database.connect() as connection:
        offer_id = create_offer(
            database, connection, user, draft(**changes), "test", now
        ).offer_id
    if publish:
        with database.connect() as connection:
            publish_offer(database, connection, user, offer_id, "test", now)
    return offer_id


def accept(database, offer_id, user=CUSTOMER, now=T, site_id=None, key=None, cap=3):
    with database.connect() as connection:
        view, _ = accept_offer(
            database, connection, user, offer_id, site_id, key, "test", now, cap
        )
    return view


def refused(function, *arguments) -> tuple[int, str]:
    with pytest.raises(ApiError) as error:
        function(*arguments)
    return error.value.status, error.value.code


def call(database, function, *arguments):
    with database.connect() as connection:
        return function(connection, *arguments)


def write(database, function, *arguments):
    with database.connect() as connection:
        return function(database, connection, *arguments)


def add_client(database, username: str, *site_ids: str) -> User:
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO users(user_id,username,password_hash,role,account_type) "
            "VALUES (?,?,?,?,?)",
            (username, username, "scrypt$00$00", "customer", "home"),
        )
        for site_id in site_ids:
            connection.execute(
                "INSERT INTO user_sites(user_id,site_id) VALUES (?,?)",
                (username, site_id),
            )
    return User(user_id=username, username=username, role="customer")


def add_consumer_site(database, site_id="s6-99"):
    """An import-only meter without PV and without a site profile."""
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO sites(site_id,alias,area_id,topology_mode,"
            "reporting_interval_seconds,stale_after_seconds,capabilities,"
            "measurement_requirements) VALUES (?,?,?,?,?,?,?,?)",
            (
                site_id,
                f"Demo flat {site_id}",
                "sector-6",
                "simulated",
                900,
                1800,
                json.dumps(["home_load", "grid_import"]),
                json.dumps({"home_load": "optional", "grid_import": "optional"}),
            ),
        )
        connection.execute(
            "INSERT INTO devices(device_id,site_id,source_id) VALUES (?,?,?)",
            (f"meter-{site_id}", site_id, "synthetic-demo"),
        )
        connection.execute(
            "INSERT INTO energy_streams(site_id,device_id,source_id) VALUES (?,?,?)",
            (site_id, f"meter-{site_id}", "synthetic-demo"),
        )


def meter(database, site_id, start, count, kw, metric="grid_import", received=None):
    """Ingest `count` 15-minute records through the normal ingestion path."""
    other = "grid_export" if metric == "grid_import" else "grid_import"
    for index in range(count):
        begin = start + timedelta(minutes=15 * index)
        end = begin + timedelta(minutes=15)
        record = deepcopy(BASE)
        reading = record["measurements"][metric]
        if kw is None:
            reading.update(value=None, availability="missing")
        else:
            reading["value"] = kw
        record["measurements"][other]["value"] = 0
        record.update(
            record_id=f"{site_id}-{begin:%Y%m%dT%H%M}",
            site_id=site_id,
            device_id=f"meter-{site_id}",
            interval_start=begin.isoformat(),
            interval_end=end.isoformat(),
            received_at=(received or end).isoformat(),
            raw_record_ref=f"test://{site_id}/{begin:%Y%m%dT%H%M}",
        )
        assert ingest(database, record, "test").status == "accepted"


def one(database, sql, *parameters):
    with database.connect() as connection:
        return connection.execute(sql, parameters).fetchone()


def kinds(database, user=CUSTOMER) -> list[str]:
    return [
        item.kind
        for item in call(database, list_notifications, user, False).notifications
    ]


# ---------------------------------------------------------------- HTTP: roles and scope


def test_roles_and_area_scope_over_http(app, database):
    other_area = make_offer(database, area_id="sector-3")
    dispatcher = login(app, "dispatcher")
    for path in (MANAGER, "/api/v1/manager/clients", f"{MANAGER}/{other_area}"):
        response = dispatcher.get(path)
        assert (response.status_code, response.json()["code"]) == (
            403,
            "manager_required",
        )
    assert dispatcher.post(MANAGER, json=body()).json()["code"] == "manager_required"
    for path in ("/api/v1/offers", "/api/v1/offers/mine", "/api/v1/offers/savings"):
        assert dispatcher.get(path).json()["code"] == "customer_required"
    technician = login(app, "technician")
    assert technician.get(MANAGER).json()["code"] == "manager_required"
    customer = login(app, "customer")
    assert customer.get(MANAGER).status_code == 403
    assert customer.post(f"{MANAGER}/preview", json=body()).status_code == 403
    visible = {item["offer_id"] for item in customer.get("/api/v1/offers").json()}
    assert visible == {"demo-offer-s6-consume", "demo-offer-s6-export"}
    assert customer.post(f"/api/v1/offers/{other_area}/accept").status_code == 404

    area = login(app, "area-manager")
    assert {item["offer_id"] for item in area.get(MANAGER).json()} == DEMO
    assert area.get(f"{MANAGER}?status=draft").json()[0]["offer_id"] == (
        "demo-offer-s6-draft"
    )
    for path in ("", "/preview", "/audit"):
        assert area.get(f"{MANAGER}/{other_area}{path}").status_code == 404
    for path in ("", "/publish", "/cancel"):
        assert (
            area.post(f"{MANAGER}/{other_area}{path}", json=body()).status_code == 404
        )
    response = area.post(MANAGER, json=body(area_id="sector-3"))
    assert (response.status_code, response.json()["code"]) == (422, "area_out_of_scope")
    response = area.post(
        MANAGER,
        json=body(target_mode="clients", target_user_ids=["business-customer"]),
    )
    assert response.json()["code"] == "client_out_of_scope"
    clients = area.get("/api/v1/manager/clients").json()
    assert [client["username"] for client in clients] == ["customer"]
    assert clients[0]["sites"][0] | {"zone": None} == {
        "site_id": "s6-01",
        "alias": "Home · Militari 1",
        "area_id": "sector-6",
        "zone": None,
        "segment": "prosumers",
        "installed_kwp": "6",
        "has_pv": True,
        "export_capable": True,
        "has_meter": True,
    }
    assert area.get("/api/v1/manager/clients?area_id=sector-3").status_code == 404
    wrong = area.post(MANAGER, json=body(), headers={"X-CSRF-Token": "wrong"})
    assert wrong.json()["code"] == "csrf_required"

    supervisor = login(app, "supervisor")
    assert other_area in {item["offer_id"] for item in supervisor.get(MANAGER).json()}
    assert {
        client["username"]
        for client in supervisor.get("/api/v1/manager/clients").json()
    } == {"customer", "other-customer", "business-customer"}
    assert supervisor.get(f"{MANAGER}/{other_area}").json()["area_id"] == "sector-3"


# ---------------------------------------------------------------- HTTP: full lifecycle


def test_offer_lifecycle_over_http(app, database, clock):
    manager, customer = login(app, "supervisor"), login(app, "customer")
    clock.now = T - timedelta(minutes=5)  # publish before the acceptance at T
    contract = {
        "supplier": "Demo Energy",
        "import_price_ron_kwh": 1.1,
        "export_price_ron_kwh": 0.5,
    }
    assert (
        customer.post("/api/v1/sites/s6-01/contract", json=contract).status_code == 200
    )
    terms = body(title="Lunch surplus")
    preview = manager.post(f"{MANAGER}/preview", json=terms).json()
    assert (preview["audience_size"], preview["sites"], preview["errors"]) == (1, 1, [])
    assert preview["sample_clients"] == ["customer"]
    assert preview["summary"]["max_penalty_bani"] == 300
    assert preview["summary"]["block_value_bani"] == 550
    assert preview["summary"]["max_client_value_bani"] == 750
    created = manager.post(MANAGER, json=terms)
    assert created.status_code == 201, created.text
    offer_id = created.json()["offer_id"]
    assert (created.json()["status"], created.json()["locked"]) == ("draft", False)
    assert offer_id not in {
        o["offer_id"] for o in customer.get("/api/v1/offers").json()
    }
    assert customer.post(f"/api/v1/offers/{offer_id}/accept").status_code == 404

    edited = manager.post(
        f"{MANAGER}/{offer_id}", json={**terms, "energy_kwh": "4", "window_minutes": 60}
    )
    assert edited.json()["energy_kwh"] == "4", edited.text
    published = manager.post(f"{MANAGER}/{offer_id}/publish").json()
    assert (published["status"], published["audience_size"]) == ("available", 1)
    again = manager.post(f"{MANAGER}/{offer_id}/publish")
    assert again.json()["code"] == "offer_not_draft"
    assert manager.get(f"{MANAGER}/{offer_id}/preview").json()["errors"] == []

    visible = next(
        item
        for item in customer.get("/api/v1/offers").json()
        if item["offer_id"] == offer_id
    )
    assert visible["penalty_rule_text"] == (
        "If you use less than 4 kWh within 1 hour, you pay 0.30 RON for each kWh not used."
    )
    assert "0.55 RON/kWh" in visible["terms_text"]
    assert visible["max_penalty_bani"] == 120
    assert visible["eligible_sites"] == [
        {
            "site_id": "s6-01",
            "alias": "Home · Militari 1",
            "reference_price_ron_per_kwh": "1.1",
            "reference_price_source": "contract",
            "export_capable": True,
            "has_meter": True,
            "savings_if_completed_bani": 220,
        }
    ]
    path = f"/api/v1/offers/{offer_id}/accept"
    clock.now = T
    first = customer.post(
        path, json={"site_id": "s6-01"}, headers={"Idempotency-Key": "k-1"}
    )
    assert first.status_code == 201, first.text
    repeat = customer.post(
        path, json={"site_id": "s6-01"}, headers={"Idempotency-Key": "k-1"}
    )
    assert repeat.status_code == 200
    assert repeat.json()["user_offer_id"] == first.json()["user_offer_id"]
    other = customer.post(path, json={}, headers={"Idempotency-Key": "k-2"})
    assert (other.status_code, other.json()["code"]) == (409, "already_accepted")
    reused = customer.post(
        "/api/v1/offers/demo-offer-s6-consume/accept",
        headers={"Idempotency-Key": "k-1"},
    )
    assert reused.json()["code"] == "idempotency_key_reused"
    accepted = first.json()
    assert accepted["status"] == "accepted"
    assert (
        accepted["reference_price_ron_per_kwh"],
        accepted["reference_price_source"],
    ) == (
        "1.1",
        "contract",
    )
    assert accepted["window_end"] == (T + timedelta(hours=1)).isoformat().replace(
        "+00:00", "Z"
    )
    locked = manager.post(f"{MANAGER}/{offer_id}", json=terms)
    assert (locked.status_code, locked.json()["code"]) == (409, "offer_locked")

    meter(database, "s6-01", T, 2, 6)  # 3 kWh in the first 30 minutes
    clock.now = T + timedelta(minutes=35)
    live = customer.get("/api/v1/offers/mine?status=active").json()
    assert [item["user_offer_id"] for item in live] == [accepted["user_offer_id"]]
    assert (live[0]["status"], live[0]["metered_kwh"], live[0]["remaining_kwh"]) == (
        "active",
        "3",
        "1",
    )
    assert (live[0]["coverage_ratio"], live[0]["projected_penalty_bani"]) == (0.5, 30)
    assert live[0]["settlement"] is None
    assert worker(database, clock.now)["settled"] == 0
    meter(database, "s6-01", T + timedelta(minutes=30), 1, 6)  # block now delivered
    assert (
        worker(database, T + timedelta(minutes=46))["settled"] == 1
    )  # early settlement
    clock.now = T + timedelta(minutes=61)
    history = customer.get("/api/v1/offers/mine?status=history").json()[0]
    assert history["status"] == "completed"
    settlement = history["settlement"]
    assert (settlement["fulfilled_kwh"], settlement["excess_kwh"]) == ("4", "0.5")
    assert (settlement["amount_bani"], settlement["direction"]) == (220, "charge")
    assert (settlement["savings_bani"], settlement["penalty_bani"]) == (220, 0)
    savings = customer.get("/api/v1/offers/savings").json()
    assert savings["lifetime_bani"] == savings["this_month_bani"] == 220
    assert (savings["consume_bani"], savings["export_bani"]) == (220, 0)
    assert (savings["settled_count"], savings["penalties_paid_bani"]) == (1, 0)
    assert savings["recent"][0]["user_offer_id"] == accepted["user_offer_id"]

    notes = customer.get("/api/v1/notifications").json()
    assert [item["kind"] for item in notes["notifications"]][:3] == [
        "offer_settled",
        "offer_reminder_30",  # sent by the pass at T+35, 25 minutes before the end
        "offer_accepted",
    ]
    assert (
        notes["notifications"][0]["link"] == f"offers/mine/{accepted['user_offer_id']}"
    )
    assert "2.20 RON" in notes["notifications"][0]["body"]
    unread = notes["unread_count"]
    first_note = notes["notifications"][0]["notification_id"]
    marked = customer.post(f"/api/v1/notifications/{first_note}/read").json()
    assert marked["unread_count"] == unread - 1
    assert manager.post(f"/api/v1/notifications/{first_note}/read").status_code == 404
    assert customer.post("/api/v1/notifications/read-all").json()["unread_count"] == 0
    assert (
        customer.get("/api/v1/notifications?unread=true").json()["notifications"] == []
    )

    detail = manager.get(f"{MANAGER}/{offer_id}").json()
    stats = detail["stats"]
    assert (stats["accepted"], stats["fulfilled"], stats["active"]) == (1, 1, 0)
    assert (stats["charges_bani"], stats["payouts_bani"]) == (220, 0)
    assert (stats["total_kwh_committed"], stats["total_kwh_delivered"]) == ("4", "4")
    assert detail["takers"][0]["username"] == "customer"
    assert detail["takers"][0]["amount_bani"] == 220
    cancelled = manager.post(f"{MANAGER}/{offer_id}/cancel").json()
    assert cancelled["status"] == "cancelled"
    assert manager.post(f"{MANAGER}/{offer_id}/cancel").json()["code"] == (
        "offer_not_cancellable"
    )
    audit = manager.get(f"{MANAGER}/{offer_id}/audit").json()
    assert [entry["action"] for entry in audit] == [
        "offer.created",
        "offer.updated",
        "offer.published",
        "offer.accepted",
        "offer.settled",
        "offer.cancelled",
    ]
    assert audit[0]["actor"] == "supervisor"
    assert audit[1]["detail"]["changed"] == {
        "energy_kwh": ["10", "4"],
        "window_minutes": [120, 60],
    }
    assert audit[3]["actor"] == "customer"


# ---------------------------------------------------------------- validation and audit


def test_validation_publish_rules_edit_and_audit(database):
    def create(**changes):
        return write(database, create_offer, SUPERVISOR, draft(**changes), "t", T)

    for changes in (
        {"energy_kwh": "0"},
        {"energy_kwh": "10000.5"},
        {"energy_kwh": "1.2345"},
        {"offer_price_ron_per_kwh": "10.01"},
        {"offer_price_ron_per_kwh": "0.12345"},
        {"window_minutes": 14},
        {"window_minutes": 1441},
        {"penalty_type": "percent_of_unfulfilled_value", "penalty_value": "101"},
        {"penalty_type": "flat", "penalty_value": "1000.01"},
        {"penalty_value": "10.5"},
        {"max_total_kwh": "5"},
        {"target_mode": "segment"},
        {"target_segment": "prosumers"},
        {"target_mode": "clients"},
        {"target_zone": "Băneasa"},
    ):
        with pytest.raises(ApiError) as error:
            create(**changes)
        assert (error.value.status, error.value.code) == (422, "invalid_offer_terms"), (
            changes
        )
    with pytest.raises(ApiError) as error:
        create(offer_expires_at=datetime(2030, 1, 1))
    assert "timezone" in error.value.message

    past = make_offer(database, publish=False, offer_expires_at=T - timedelta(hours=1))
    assert refused(write, database, publish_offer, SUPERVISOR, past, "t", T) == (
        422,
        "expiry_in_past",
    )
    nobody = make_offer(
        database, publish=False, target_mode="segment", target_segment="consumers"
    )
    assert refused(write, database, publish_offer, SUPERVISOR, nobody, "t", T) == (
        422,
        "empty_audience",
    )
    preview = call(
        database,
        preview_draft,
        SUPERVISOR,
        draft(target_mode="segment", target_segment="consumers"),
        T,
    )
    assert (
        preview.errors == ["No client matches this targeting"] and not preview.summary
    )

    warned = call(
        database,
        preview_draft,
        SUPERVISOR,
        draft(offer_price_ron_per_kwh="1.5", penalty_type="flat", penalty_value="20"),
        T,
    ).warnings
    assert any("lose money" in item for item in warned)
    assert any("higher than the value of the block" in item for item in warned)
    export = call(
        database,
        preview_draft,
        SUPERVISOR,
        draft(type="export", offer_price_ron_per_kwh="0.4"),
        T,
    )
    assert any("below the default export tariff" in w for w in export.warnings)
    assert export.summary.max_client_value_bani == -150

    offer_id = make_offer(database)
    edited = write(
        database,
        update_offer,
        SUPERVISOR,
        offer_id,
        draft(offer_price_ron_per_kwh="0.5"),
        "t",
        T,
    )
    assert edited.offer_price_ron_per_kwh == "0.5" and edited.status == "available"
    assert refused(
        write,
        database,
        update_offer,
        SUPERVISOR,
        offer_id,
        draft(offer_expires_at=T - timedelta(minutes=1)),
        "t",
        T,
    ) == (422, "expiry_in_past")
    accepted = accept(database, offer_id)
    # Accepted terms are a copy; the offer can no longer change.
    assert refused(
        write, database, update_offer, SUPERVISOR, offer_id, draft(), "t", T
    ) == (409, "offer_locked")
    assert accepted.offer_price_ron_per_kwh == "0.5"
    write(database, cancel_offer, SUPERVISOR, past, "t", T)
    assert refused(
        write, database, update_offer, SUPERVISOR, past, draft(), "t", T
    ) == (409, "offer_closed")
    actions = [
        entry.action for entry in call(database, offer_audit, SUPERVISOR, offer_id)
    ]
    assert actions == [
        "offer.created",
        "offer.published",
        "offer.updated",
        "offer.accepted",
    ]
    trail = call(database, offer_audit, SUPERVISOR, past)
    assert [entry.action for entry in trail] == ["offer.created", "offer.cancelled"]
    assert trail[1].detail == {"previous_status": "draft", "running_windows_closed": 0}
    assert refused(
        call,
        database,
        offer_audit,
        AREA_MANAGER,
        make_offer(database, area_id="sector-4"),
    ) == (404, "not_found")


# ---------------------------------------------------------------- targeting and limits


def test_targeting_modes_and_eligibility(database):
    add_consumer_site(database)
    second = add_client(database, "c2", "s6-02", "s6-03")
    business = add_client(database, "c4", "s6-13")
    zoned = add_client(database, "c5", "s6-09")
    flat = add_client(database, "c9", "s6-99")

    def audience(**changes):
        preview = call(database, preview_draft, SUPERVISOR, draft(**changes), T)
        return sorted(preview.sample_clients), preview.sites, preview.errors

    assert audience()[:2] == (["c2", "c4", "c5", "c9", "customer"], 6)
    assert audience(target_mode="segment", target_segment="prosumers")[0] == [
        "c2",
        "c4",
        "c5",
        "customer",
    ]
    assert audience(target_mode="segment", target_segment="consumers")[0] == ["c9"]
    assert audience(target_min_kwp="7.5")[:2] == (["c2", "c4"], 2)  # 8 and 120 kWp
    assert audience(target_mode="clients", target_user_ids=["c2", "customer"])[0] == [
        "c2",
        "customer",
    ]
    zone = one(database, "SELECT zone FROM site_profiles WHERE site_id='s6-09'")[0]
    incident = "demo-inc-s6-09-production"
    assert audience(linked_incident_id=incident, target_zone=zone)[0] == ["c5"]
    assert audience(linked_incident_id=incident, target_zone="Elsewhere")[2][0] == (
        "target_zone must be the linked incident site's zone"
    )
    assert refused(
        call,
        database,
        preview_draft,
        SUPERVISOR,
        draft(linked_incident_id="demo-inc-s3-04-area"),
        T,
    ) == (422, "incident_out_of_scope")
    assert refused(
        call,
        database,
        preview_draft,
        SUPERVISOR,
        draft(target_mode="clients", target_user_ids=["other-customer"]),
        T,
    ) == (422, "client_out_of_scope")
    warnings = call(
        database, preview_draft, SUPERVISOR, draft(type="export"), T
    ).warnings
    assert "1 targeted sites cannot measure grid export and cannot accept." in warnings

    picked = make_offer(database, target_mode="clients", target_user_ids=["c2"])
    assert picked not in {
        o.offer_id for o in call(database, client_offers, CUSTOMER, T)
    }
    assert refused(accept, database, picked) == (404, "not_found")
    assert "offer_new" in kinds(database, second)
    assert "offer_new" not in kinds(database, business)  # not targeted
    assert refused(accept, database, picked, second) == (422, "site_required")
    assert refused(accept, database, picked, second, T, "s6-01") == (
        422,
        "site_not_eligible",
    )
    assert accept(database, picked, second, T, "s6-03").site_id == "s6-03"

    export = make_offer(database, type="export")
    assert refused(accept, database, export, flat) == (422, "export_meter_required")
    consume = make_offer(database, target_mode="segment", target_segment="consumers")
    view = accept(database, consume, flat)
    assert (view.reference_price_ron_per_kwh, view.reference_price_source) == (
        "1.3",
        "default_tariff",
    )
    assert accept(database, export, zoned).reference_price_ron_per_kwh == "0.55"


def test_capacity_limits_active_cap_and_expiry(database):
    other = add_client(database, "c2", "s6-02")
    single = make_offer(database, max_takers=1)
    accept(database, single)
    assert refused(accept, database, single, other) == (409, "offer_full")
    shared = make_offer(database, max_total_kwh="15")
    accept(database, shared)
    capacity = next(
        o for o in call(database, client_offers, other, T) if o.offer_id == shared
    ).remaining_capacity
    assert (capacity.takers_left, capacity.kwh_left, capacity.full) == (None, "5", True)
    assert refused(accept, database, shared, other) == (409, "offer_full")
    third = make_offer(database)
    assert refused(accept, database, third, CUSTOMER, T, None, None, 2) == (
        409,
        "too_many_active_offers",
    )

    soon = make_offer(database, offer_expires_at=T + timedelta(hours=1))
    later = T + timedelta(hours=2)
    assert soon not in {o.offer_id for o in call(database, client_offers, other, later)}
    assert refused(accept, database, soon, other, later) == (409, "offer_unavailable")
    listed = call(database, list_manager_offers, SUPERVISOR, "expired", later)
    assert [o.offer_id for o in listed] == [soon]
    assert worker(database, later)["expired_offers"] >= 1
    assert (
        one(database, "SELECT status FROM offers WHERE offer_id=?", soon)[0]
        == "expired"
    )
    gone = make_offer(database)
    write(database, cancel_offer, SUPERVISOR, gone, "t", T)
    assert refused(accept, database, gone, other) == (409, "offer_unavailable")


def test_concurrent_accepts_respect_max_takers(database):
    users = [add_client(database, f"c{n}", f"s6-0{n}") for n in range(2, 8)]
    offer_id = make_offer(database, max_takers=1)
    barrier = threading.Barrier(len(users))
    outcomes = []

    def attempt(user):
        barrier.wait()
        try:
            accept(database, offer_id, user)
            outcomes.append("accepted")
        except ApiError as error:
            outcomes.append(error.code)

    threads = [threading.Thread(target=attempt, args=(user,)) for user in users]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["accepted"] + ["offer_full"] * (len(users) - 1)
    assert (
        one(database, "SELECT COUNT(*) FROM user_offers WHERE offer_id=?", offer_id)[0]
        == 1
    )


# ---------------------------------------------------------------- metering and settlement


def test_fifo_attribution_across_two_overlapping_offers(database):
    first = make_offer(database, energy_kwh="5")
    second = make_offer(database, energy_kwh="5")
    a = accept(database, first, now=T)
    b = accept(database, second, now=T + timedelta(minutes=30))
    meter(database, "s6-01", T, 10, 8)  # 20 kWh from T to T+150 minutes
    live = {
        item.user_offer_id: item
        for item in call(database, my_offers, CUSTOMER, "active")
    }
    assert (live[a.user_offer_id].metered_kwh, live[b.user_offer_id].metered_kwh) == (
        "11",
        "9",
    )
    assert worker(database, T + timedelta(minutes=151))["settled"] == 2
    rows = {
        row["user_offer_id"]: row
        for row in call(
            database, lambda c: c.execute("SELECT * FROM offer_settlements").fetchall()
        )
    }
    assert (
        rows[a.user_offer_id]["fulfilled_kwh"],
        rows[a.user_offer_id]["excess_kwh"],
    ) == ("5", "6")
    assert (
        rows[b.user_offer_id]["fulfilled_kwh"],
        rows[b.user_offer_id]["excess_kwh"],
    ) == ("5", "4")
    # Excess is informational: both blocks are charged exactly 5 x 0.55 RON.
    assert {row["amount_bani"] for row in rows.values()} == {275}


def test_grace_period_and_incomplete_meter_data_waive_penalty(database):
    view = accept(database, make_offer(database))
    meter(database, "s6-01", T, 4, 4)  # 4 kWh in the first hour only
    assert worker(database, T + timedelta(minutes=130))["settled"] == 0
    row = one(
        database, "SELECT * FROM user_offers WHERE user_offer_id=?", view.user_offer_id
    )
    assert (row["status"], row["metered_kwh"], row["coverage_ratio"]) == (
        "active",
        "4",
        0.5,
    )
    assert worker(database, T + timedelta(minutes=180))["settled"] == 1
    settled = call(database, my_offers, CUSTOMER, "history")[0]
    assert settled.status == "partial"
    assert settled.settlement.penalty_waived_reason == "meter_data_incomplete"
    assert (
        settled.settlement.penalty_bani,
        settled.settlement.penalty_before_waiver_bani,
    ) == (0, 180)
    assert settled.settlement.amount_bani == 220
    note = call(database, list_notifications, CUSTOMER, False).notifications[0]
    assert (
        note.kind == "offer_settled"
        and "meter data for the window was incomplete" in note.body
    )


def test_late_meter_data_before_grace_counts(database):
    view = accept(database, make_offer(database))
    meter(database, "s6-01", T, 4, 8)  # 8 kWh in the first hour
    assert worker(database, T + timedelta(minutes=125))["settled"] == 0
    meter(
        database,
        "s6-01",
        T + timedelta(hours=1),
        4,
        4,
        received=T + timedelta(minutes=150),
    )
    assert worker(database, T + timedelta(minutes=181))["settled"] == 1
    settlement = call(database, my_offers, CUSTOMER, "all")[0].settlement
    assert (settlement.fulfilled_kwh, settlement.excess_kwh) == ("10", "2")
    assert settlement.coverage_ratio == 1.0
    assert (
        view.user_offer_id
        == call(database, my_offers, CUSTOMER, "all")[0].user_offer_id
    )


def test_export_offer_and_negative_savings(database):
    view = accept(
        database,
        make_offer(
            database,
            type="export",
            offer_price_ron_per_kwh="0.4",
            penalty_type="percent_of_unfulfilled_value",
            penalty_value="25",
        ),
    )
    assert view.reference_price_ron_per_kwh == "0.55"
    meter(database, "s6-01", T, 8, 3, metric="grid_export")  # 6 kWh exported
    assert worker(database, T + timedelta(minutes=180))["settled"] == 1
    settlement = call(database, my_offers, CUSTOMER, "all")[0].settlement
    assert (settlement.direction, settlement.fulfilled_kwh) == ("credit", "6")
    assert settlement.penalty_bani == 40  # 4 kWh x 0.40 x 25%
    assert settlement.amount_bani == 200  # 2.40 - 0.40
    assert settlement.savings_bani == -130  # 6 x (0.40 - 0.55) - 0.40, never clamped
    totals = one(database, "SELECT * FROM savings_totals WHERE user_id='customer'")
    assert (
        totals["export_bani"],
        totals["lifetime_bani"],
        totals["penalties_bani"],
    ) == (-130, -130, 40)


def test_cancellation_mid_window_settles_delivered_energy_without_penalty(database):
    offer_id = make_offer(database)
    view = accept(database, offer_id)
    meter(database, "s6-01", T, 2, 6)  # 3 kWh
    detail = write(
        database, cancel_offer, SUPERVISOR, offer_id, "t", T + timedelta(minutes=40)
    )
    assert detail.status == "cancelled" and detail.stats.cancelled == 1
    settled = call(database, my_offers, CUSTOMER, "all")[0]
    assert (settled.status, settled.cancelled_at is not None) == ("cancelled", True)
    assert settled.settlement.penalty_waived_reason == "cancelled_by_distributor"
    assert (settled.settlement.amount_bani, settled.settlement.savings_bani) == (
        165,
        225,
    )
    assert worker(database, T + timedelta(hours=5))["settled"] == 0
    assert view.user_offer_id == settled.user_offer_id
    assert kinds(database)[0] == "offer_settled"


def test_settlement_is_idempotent_concurrent_and_restart_safe(database):
    view = accept(database, make_offer(database))
    meter(database, "s6-01", T, 2, 6)
    assert worker(database, T + timedelta(minutes=30))["progressed"] == 1
    # A new worker instance (restart mid-window) resumes from the database alone.
    restarted = settle_due(
        database,
        T + timedelta(minutes=31),
        Settings(database_path=database.path, offer_worker=False),
    )
    assert restarted["settled"] == 0
    results = []
    barrier = threading.Barrier(3)

    def run():
        barrier.wait()
        results.append(worker(database, T + timedelta(minutes=181))["settled"])

    threads = [threading.Thread(target=run) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == [0, 0, 1]
    assert worker(database, T + timedelta(minutes=500))["settled"] == 0
    assert one(database, "SELECT COUNT(*) FROM offer_settlements")[0] == 1
    totals = one(database, "SELECT * FROM savings_totals WHERE user_id='customer'")
    # 3 of 10 kWh with 25% meter coverage: the penalty is waived.
    assert (
        totals["settled_count"],
        totals["lifetime_bani"],
        totals["penalties_bani"],
    ) == (1, 225, 0)
    assert kinds(database).count("offer_settled") == 1
    assert view.status == "accepted"


def test_reconcile_detects_and_fixes_tampered_counters(database, monkeypatch, capsys):
    accept(database, make_offer(database))
    meter(database, "s6-01", T, 8, 5)  # 10 kWh: completed, savings 7.50 RON
    worker(database, T + timedelta(minutes=121))
    assert reconcile(database) == []
    with database.connect() as connection:
        connection.execute(
            "UPDATE savings_totals SET lifetime_bani=lifetime_bani+999 WHERE user_id='customer'"
        )
    found = reconcile(database, "customer", fix=False)
    assert found == [
        {
            "user_id": "customer",
            "field": "lifetime_bani",
            "stored": 1749,
            "expected": 750,
        }
    ]
    monkeypatch.setenv("SOLAR_DATABASE", str(database.path))
    with pytest.raises(SystemExit) as error:
        main(["reconcile-savings", "--check"])
    assert error.value.code == 1
    main(["reconcile-savings", "--username", "customer"])
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["fixed"] is True
    assert reconcile(database) == []
    assert one(database, "SELECT lifetime_bani FROM savings_totals")[0] == 750


def test_reminders_are_sent_once_each(database):
    view = accept(database, make_offer(database))
    assert worker(database, T + timedelta(minutes=95))["reminders"] == 1
    assert worker(database, T + timedelta(minutes=96))["reminders"] == 0
    assert worker(database, T + timedelta(minutes=112))["reminders"] == 1
    assert worker(database, T + timedelta(minutes=113))["reminders"] == 0
    found = kinds(database)
    assert (found.count("offer_reminder_30"), found.count("offer_reminder_10")) == (
        1,
        1,
    )
    short = accept(database, make_offer(database, window_minutes=15))
    assert worker(database, T + timedelta(minutes=1))["reminders"] == 0
    assert worker(database, T + timedelta(minutes=6))["reminders"] == 1
    assert kinds(database).count("offer_reminder_30") == 1  # none for the short window
    assert view.window_minutes == 120 and short.window_minutes == 15


def test_meter_simulator_and_cli(database, monkeypatch, capsys):
    view = accept(database, make_offer(database))
    summary = simulate_offer_meter(
        database, view.user_offer_id, 0.8, now=T + timedelta(minutes=50)
    )
    assert (summary["records"], summary["metric"], summary["power_kw"]) == (
        4,
        "grid_import",
        9.6,
    )
    assert call(database, my_offers, CUSTOMER, "active")[0].metered_kwh == "8"
    # Re-running tops up; already covered intervals are never rewritten.
    assert (
        simulate_offer_meter(
            database, view.user_offer_id, 0.8, now=T + timedelta(minutes=50)
        )["records"]
        == 0
    )
    other = add_client(database, "c2", "s6-02")
    export = accept(database, make_offer(database, type="export"), other)
    partial = simulate_offer_meter(
        database, export.user_offer_id, 1.0, coverage=0.5, now=T + timedelta(hours=2)
    )
    assert (partial["records"], partial["reported_records"], partial["metric"]) == (
        8,
        4,
        "grid_export",
    )
    item = call(database, my_offers, other, "active")[0]
    assert (item.metered_kwh, item.coverage_ratio) == ("10", 0.5)
    monkeypatch.setenv("SOLAR_DATABASE", str(database.path))
    main(["settle-offers", "--now", (T + timedelta(hours=4)).isoformat()])
    assert json.loads(capsys.readouterr().out)["settled"] == 2
    main(["offers-worker", "--once"])
    assert "expired_offers" in capsys.readouterr().out
    live = accept(
        database,
        "demo-offer-s6-export",
        now=datetime.now(UTC) - timedelta(minutes=20),
    )
    main(["simulate-offer-meter", live.user_offer_id, "--fraction", "0.5"])
    assert json.loads(capsys.readouterr().out)["records"] == 2
    with pytest.raises(SystemExit):
        main(["simulate-offer-meter", "missing"])


def test_in_app_worker_settles_in_the_background(database):
    view = accept(database, make_offer(database))
    meter(database, "s6-01", T, 8, 5)
    settings = Settings(
        database_path=database.path,
        media_dir=database.path.parent / "media",
        offer_worker=True,
        clock=lambda: T + timedelta(hours=4),
    )
    with TestClient(create_app(settings)):
        for _ in range(100):
            if one(database, "SELECT 1 FROM offer_settlements"):
                break
            time.sleep(0.05)
    row = one(
        database,
        "SELECT status FROM user_offers WHERE user_offer_id=?",
        view.user_offer_id,
    )
    assert row["status"] == "completed"


def test_manager_detail_reports_live_progress(database):
    offer_id = make_offer(database)
    accept(database, offer_id)
    meter(database, "s6-01", T, 2, 6)
    detail = call(
        database, manager_offer_detail, SUPERVISOR, offer_id, T + timedelta(minutes=31)
    )
    assert (detail.stats.active, detail.stats.total_kwh_delivered) == (1, "3")
    assert (detail.takers[0].status, detail.takers[0].metered_kwh) == ("active", "3")
    assert detail.locked is True
