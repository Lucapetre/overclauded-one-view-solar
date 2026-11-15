"""Targeted tests for the demo-richness features (SYNTHETIC data)."""

from datetime import date

import pytest

from backend.customer import create_request, list_requests
from backend.customer_models import SupportRequestCreate
from backend.db import Database
from backend.energy_views import profile_day
from backend.enrich import ALL_AREAS, grant_areas_and_accounts
from backend.models import User
from backend.ops import _create_assignment
from backend.seed import seed_demo


def test_profile_is_seasonal_and_deterministic():
    january = [
        profile_day(6.0, "home", None, "s1-01", date(2026, 1, d)) for d in range(1, 29)
    ]
    july = [
        profile_day(6.0, "home", None, "s1-01", date(2026, 7, d)) for d in range(1, 29)
    ]
    consumption = lambda days: sum(sum(c) for _, c in days)  # noqa: E731
    production = lambda days: sum(sum(p) for p, _ in days)  # noqa: E731
    assert consumption(january) > consumption(july)
    assert production(july) > 3 * production(january)
    assert profile_day(6.0, "home", None, "s1-01", date(2026, 7, 1)) == july[0]
    # A home peaks in the evening, a weekday business in the daytime.
    _, home = profile_day(6.0, "home", None, "s1-01", date(2026, 7, 6))
    _, business = profile_day(15.0, "business", "Office", "s1-05", date(2026, 7, 6))
    assert max(range(24), key=home.__getitem__) >= 17
    assert 8 <= max(range(24), key=business.__getitem__) <= 16
    # Weekend business load is lower for an office.
    _, weekend = profile_day(15.0, "business", "Office", "s1-05", date(2026, 7, 11))
    assert sum(weekend) < sum(business)


@pytest.fixture
def city(tmp_path):
    database = Database(tmp_path / "city.sqlite3")
    seed_demo(database, "correct horse battery staple")
    return database


def test_technician_sees_only_requests_linked_by_assignment(city):
    customer = User(user_id="customer", username="customer", role="customer")
    technician = User(user_id="technician", username="technician", role="technician")
    other = User(user_id="technician-s1", username="technician-s1", role="technician")
    with city.connect() as connection:
        request = create_request(
            city,
            connection,
            customer,
            SupportRequestCreate(
                site_id="s6-01",
                request_type="solar",
                description="Production looks low",
            ),
            "test",
        )
        assert list_requests(connection, technician) == []
        incident = connection.execute(
            "SELECT incident_id FROM incidents WHERE support_request_id=?",
            (request.request_id,),
        ).fetchone()[0]
        dispatcher = User(
            user_id="dispatcher", username="dispatcher", role="dispatcher"
        )
        _create_assignment(
            connection,
            incident,
            "sector-6-solar-care",
            "dispatch",
            "assigned",
            dispatcher,
            "2026-07-17T05:00:00.000000+00:00",
        )
        assert [r.request_id for r in list_requests(connection, technician)] == [
            request.request_id
        ]
        assert list_requests(connection, other) == []


def test_enrich_grants_cover_all_areas_and_victor_only_ilfov(city):
    with city.connect() as connection:
        for user_id, role in (
            ("scenario-supervisor", "supervisor"),
            ("scenario-dispatcher", "dispatcher"),
        ):
            connection.execute(
                "INSERT INTO users(user_id,username,password_hash,role,account_type) "
                "VALUES (?,?,?,?,'home')",
                (user_id, user_id, "x", role),
            )
        created = grant_areas_and_accounts(city, connection)
        assert "victor" in created
        areas = lambda user: sorted(  # noqa: E731
            r[0]
            for r in connection.execute(
                "SELECT area_id FROM user_areas WHERE user_id=?", (user,)
            )
        )
        assert areas("victor") == ["ilfov"]
        assert areas("scenario-supervisor") == sorted(ALL_AREAS)
        # Idempotent: a second pass creates nothing new.
        assert grant_areas_and_accounts(city, connection) == {}
