import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.db import Database
from backend.errors import ApiError
from backend.ingestion import ingest
from backend.models import SiteRegistration, User
from backend.provisioning import create_user, grant_access, register_site
from backend.security import accessible_sites


@pytest.fixture
def registration():
    path = (
        Path(__file__).resolve().parents[1] / "backend/fixtures/site-registration.json"
    )
    return SiteRegistration.model_validate_json(path.read_text())


def test_register_real_pipeline_site_and_grant_access(tmp_path, registration, record):
    database = Database(tmp_path / "new.sqlite3")
    database.migrate()
    register_site(database, registration)
    register_site(database, registration)
    create_user(database, "new-customer", "a-long-test-password", "customer")
    with database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE username='new-customer'"
        ).fetchone()
        user = User(**{key: row[key] for key in ("user_id", "username", "role")})
        assert accessible_sites(connection, user) == []
    grant_access(database, "new-customer", registration.site.site_id, "site")
    with database.connect() as connection:
        assert [row["site_id"] for row in accessible_sites(connection, user)] == [
            registration.site.site_id
        ]
    record.update(
        site_id=registration.site.site_id,
        device_id=registration.device_id,
        source_id=registration.source_id,
    )
    assert ingest(database, record).status == "accepted"


def test_registry_changes_cannot_reinterpret_existing_telemetry(database, registration):
    register_site(database, registration)
    registration.site.measurement_requirements["pv_power"] = "optional"
    with pytest.raises(ApiError) as error:
        register_site(database, registration)
    assert error.value.code == "site_conflict"


def test_customers_cannot_be_granted_area_access(database):
    with pytest.raises(ApiError) as error:
        grant_access(database, "customer", "sector-6", "area")
    assert error.value.status == 403


def test_invalid_site_capability_contract_is_rejected(registration):
    payload = registration.model_dump(mode="json")
    del payload["site"]["measurement_requirements"]["pv_power"]
    with pytest.raises(ValidationError):
        SiteRegistration.model_validate(json.loads(json.dumps(payload)))
