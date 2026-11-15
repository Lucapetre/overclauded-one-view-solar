"""Contract time bands: midnight-crossing bands, DST days, explicit gaps and versions."""

import shutil
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import tariff
from backend.config import Settings
from backend.db import Database
from backend.main import create_app
from backend.seed import seed_demo

PASSWORD = "test-password-only"
WEEKDAYS = (1, 2, 3, 4, 5)
EVERY_DAY = (1, 2, 3, 4, 5, 6, 7)


def version(bands, version_id="v1", effective=tariff.EPOCH, number=1, valid_to=None):
    return tariff.ContractVersion(
        version_id, number, effective, tuple(bands), "time_of_use", "payment", valid_to
    )


def band(band_id, start, end, rate, value=0.4, days=EVERY_DAY, **extra):
    return tariff.Band(band_id, tuple(days), start, end, rate, value, **extra)


def local(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=tariff.LOCAL)


def test_midnight_crossing_band_splits_interval_and_belongs_to_its_start_day():
    bands = [
        band("night", 22 * 60, 7 * 60, 0.9, days=WEEKDAYS),
        band("day", 7 * 60, 22 * 60, 1.3, days=WEEKDAYS),
    ]
    # Thursday 2026-07-16 21:00 -> Friday 08:00 local.
    parts = tariff.segments(
        [version(bands)], local(2026, 7, 16, 21), local(2026, 7, 17, 8)
    )
    assert [(p.band_id, p.hours) for p in parts] == [
        ("day", 1.0),
        ("night", 9.0),
        ("day", 1.0),
    ]
    # Friday night's occurrence starts on Friday, so it still covers Saturday 00:00-07:00;
    # Saturday itself has no band, so Saturday 07:00 onwards is an explicit gap.
    parts = tariff.segments(
        [version(bands)], local(2026, 7, 17, 23), local(2026, 7, 18, 9)
    )
    assert [(p.band_id, p.gap_reason, p.hours) for p in parts] == [
        ("night", None, 8.0),
        (None, "no_band_coverage", 2.0),
    ]


def test_interval_price_is_time_weighted_and_names_bands_and_version():
    bands = [band("night", 22 * 60, 7 * 60, 1.0), band("day", 7 * 60, 22 * 60, 2.0)]
    priced = tariff.price(
        [version(bands)], local(2026, 7, 16, 21, 45), local(2026, 7, 16, 22, 15)
    )
    assert priced.covered
    assert priced.import_rate == pytest.approx(1.5)
    assert priced.band_ids == ["day", "night"]
    assert priced.version_ids == ["v1"]


def test_spring_forward_day_has_23_hours_and_gap_boundary_maps_to_gap_end():
    # 2026-03-29: 03:00 EET jumps to 04:00 EEST in Europe/Bucharest.
    day = date(2026, 3, 29)
    start = tariff.local_to_utc(day, 0)
    end = tariff.local_to_utc(day + timedelta(days=1), 0)
    assert (end - start) == timedelta(hours=23)
    parts = tariff.segments([version([band("all", 0, 1440, 1.0)])], start, end)
    assert sum(p.hours for p in parts) == pytest.approx(23)
    assert all(p.gap_reason is None for p in parts)
    # 03:30 local does not exist on that day: the band starts at 04:00 EEST (01:00 UTC).
    assert tariff.local_to_utc(day, 3 * 60 + 30) == datetime(2026, 3, 29, 1, tzinfo=UTC)
    early = band("early", 2 * 60, 5 * 60, 0.5)
    rest = band("rest", 5 * 60, 2 * 60, 1.5)
    parts = tariff.segments([version([early, rest])], start, end)
    assert {p.band_id: round(p.hours, 6) for p in parts if p.band_id == "early"} == {
        "early": 2.0
    }


def test_fall_back_day_has_25_hours():
    day = date(2026, 10, 25)  # 04:00 EEST falls back to 03:00 EET
    start = tariff.local_to_utc(day, 0)
    end = tariff.local_to_utc(day + timedelta(days=1), 0)
    assert end - start == timedelta(hours=25)
    bands = [band("night", 22 * 60, 7 * 60, 0.9), band("day", 7 * 60, 22 * 60, 1.3)]
    parts = tariff.segments([version(bands)], start, end)
    hours = {}
    for part in parts:
        hours[part.band_id] = hours.get(part.band_id, 0) + part.hours
    # 00:00-07:00 spans 8 elapsed hours on this day; 22:00-24:00 two more.
    assert hours == {"night": pytest.approx(10), "day": pytest.approx(15)}


def test_missing_coverage_is_an_explicit_gap_never_zero():
    day_only = version([band("day", 7 * 60, 22 * 60, 1.3)])
    priced = tariff.price([day_only], local(2026, 7, 16, 21), local(2026, 7, 16, 23))
    assert not priced.covered
    assert priced.import_rate is None and priced.export_value is None
    assert priced.gap_reasons == ["no_band_coverage"]
    later = version([band("all", 0, 1440, 1.0)], effective=local(2026, 7, 17))
    priced = tariff.price([later], local(2026, 7, 16, 23), local(2026, 7, 17, 1))
    assert [s.gap_reason for s in priced.segments] == ["no_contract_version", None]
    assert priced.import_rate is None
    ended = version([band("all", 0, 1440, 1.0)], valid_to=local(2026, 7, 17))
    assert tariff.price(
        [ended], local(2026, 7, 17), local(2026, 7, 17, 1)
    ).gap_reasons == ["no_contract_version"]


def test_new_version_supersedes_from_its_effective_instant():
    old = version([band("all", 0, 1440, 1.0)], "v1")
    new = version(
        [band("all", 0, 1440, 2.0)],
        "v2",
        effective=datetime(2026, 7, 17, 12, tzinfo=UTC),
        number=2,
    )
    parts = tariff.segments(
        [old, new],
        datetime(2026, 7, 17, 11, tzinfo=UTC),
        datetime(2026, 7, 17, 13, tzinfo=UTC),
    )
    assert [(p.version_id, p.import_rate, p.hours) for p in parts] == [
        ("v1", 1.0, 1.0),
        ("v2", 2.0, 1.0),
    ]
    assert (
        tariff.current_version([old, new], datetime(2026, 7, 17, 11, tzinfo=UTC)) is old
    )


def test_band_validity_dates_and_overlap_validation():
    summer = band(
        "summer", 0, 1440, 1.0, valid_from=date(2026, 6, 1), valid_to=date(2026, 9, 1)
    )
    parts = tariff.segments(
        [version([summer])], local(2026, 8, 31, 23), local(2026, 9, 1, 1)
    )
    assert [p.gap_reason for p in parts] == [None, "no_band_coverage"]
    assert tariff.validate_bands(
        [band("a", 22 * 60, 7 * 60, 1.0), band("b", 6 * 60, 8 * 60, 1.0)]
    ) == ["Bands a and b overlap"]
    # A Friday-night band spills into Saturday morning and collides with a Saturday band.
    assert tariff.validate_bands(
        [
            band("fri", 22 * 60, 7 * 60, 1.0, days=(5,)),
            band("sat", 0, 60, 1.0, days=(6,)),
        ]
    )
    assert not tariff.validate_bands(
        [band("night", 22 * 60, 7 * 60, 1.0), band("day", 7 * 60, 22 * 60, 1.0)]
    )


# ---------------------------------------------------------------- API and migration


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    path = tmp_path_factory.mktemp("tariff") / "seed.sqlite3"
    database = Database(path)
    seed_demo(database, PASSWORD)
    with database.connect() as connection:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return path


@pytest.fixture
def api(template, tmp_path):
    path = tmp_path / "test.sqlite3"
    shutil.copyfile(template, path)
    settings = Settings(
        database_path=path, media_dir=tmp_path / "media", offer_worker=False
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/auth/login", json={"username": "customer", "password": PASSWORD}
        )
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        yield client


TOU = {
    "supplier": "Demo Supply",
    "pricing": "time_of_use",
    "import_price_ron_kwh": 1.3,
    "export_price_ron_kwh": 0.5,
    "export_compensation": "credit",
    "bands": [
        {
            "band_id": "night",
            "days": [1, 2, 3, 4, 5, 6, 7],
            "start_minute": 1320,
            "end_minute": 420,
            "import_rate_ron_kwh": 0.9,
            "export_value_ron_kwh": 0.4,
        },
        {
            "band_id": "day",
            "label": "Day",
            "days": [1, 2, 3, 4, 5, 6, 7],
            "start_minute": 420,
            "end_minute": 1320,
            "import_rate_ron_kwh": 1.4,
            "export_value_ron_kwh": 0.5,
        },
    ],
}


def test_contract_api_keeps_fixed_contracts_and_versions_time_bands(api):
    fixed = {
        "supplier": "Demo Supply",
        "pricing": "fixed",
        "import_price_ron_kwh": 1.2,
        "export_price_ron_kwh": 0.5,
    }
    view = api.post("/api/v1/sites/s6-01/contract", json=fixed).json()
    # A fixed contract keeps its original response shape (no band fields).
    assert "bands" not in view["contract"]
    assert view["version"]["bands"][0]["band_id"] == "all-day"
    assert view["version"]["uncovered_week_minutes"] == 0
    response = api.post("/api/v1/sites/s6-01/contract", json=TOU)
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["version_count"] == 2
    assert view["version"]["version_no"] == 2
    assert view["version"]["export_compensation"] == "credit"
    assert [b["band_id"] for b in view["contract"]["bands"]] == ["day", "night"]
    again = api.get("/api/v1/sites/s6-01/contract").json()
    assert again["version"]["version_id"] == view["version"]["version_id"]
    overlapping = {
        **TOU,
        "bands": [TOU["bands"][0], {**TOU["bands"][1], "start_minute": 300}],
    }
    assert api.post("/api/v1/sites/s6-01/contract", json=overlapping).status_code == 422
    assert (
        api.post(
            "/api/v1/sites/s6-01/contract", json={**TOU, "pricing": "fixed"}
        ).status_code
        == 422
    )
    past = {**fixed, "effective_from": "2020-01-01T00:00:00Z"}
    response = api.post("/api/v1/sites/s6-01/contract", json=past)
    assert response.json()["code"] == "retroactive_tariff"
    assert api.get("/api/v1/sites/s4-01/contract").status_code == 404


def test_migration_turns_existing_fixed_contract_into_version_one(tmp_path):
    path = tmp_path / "old.sqlite3"
    migrations = sorted(
        (Path(__file__).resolve().parents[1] / "backend" / "migrations").glob("*.sql")
    )
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY)")
    for migration in migrations:
        if migration.name >= "007":
            break
        connection.executescript(migration.read_text())
        connection.execute(
            "INSERT INTO schema_migrations VALUES (?)", (migration.name,)
        )
    connection.execute(
        "INSERT INTO sites VALUES ('x','X',NULL,'unknown',900,1800,'[]','{}')"
    )
    connection.execute(
        "INSERT INTO users(user_id,username,password_hash,role) VALUES ('u','u','h','customer')"
    )
    connection.execute(
        "INSERT INTO contracts VALUES ('x','Old supplier','fixed',1.1,0.4,5.0,'u','2026-07-01T00:00:00+00:00')"
    )
    connection.commit()
    connection.close()
    database = Database(path)
    database.migrate()
    with database.connect() as connection:
        versions = tariff.load_versions(connection, "x")
        row = connection.execute("SELECT * FROM contracts WHERE site_id='x'").fetchone()
    assert row["current_version_id"] == "cv-x-1"
    assert len(versions) == 1 and versions[0].pricing == "fixed"
    (only,) = versions[0].bands
    assert (only.start_minute, only.end_minute, only.import_rate) == (0, 1440, 1.1)
    priced = tariff.price(versions, local(2026, 7, 16, 23), local(2026, 7, 17, 1))
    assert priced.import_rate == pytest.approx(1.1) and priced.covered
