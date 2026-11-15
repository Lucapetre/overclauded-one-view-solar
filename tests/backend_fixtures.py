import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.db import Database
from backend.main import create_app
from backend.seed import seed_demo


@pytest.fixture
def database(tmp_path):
    database = Database(tmp_path / "test.sqlite3")
    seed_demo(database, "test-password-only")
    return database


@pytest.fixture
def client(database):
    settings = Settings(
        database_path=database.path,
        ingest_key="test-pipeline-key",
        media_dir=database.path.parent / "media",
        # Deterministic tests call settle_due(database, now) themselves.
        offer_worker=False,
    )
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture
def signed_in(client):
    def sign_in(username="customer"):
        response = client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": "test-password-only"},
        )
        assert response.status_code == 200, response.text
        return response.json()

    return sign_in


@pytest.fixture
def record():
    payload = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "backend"
            / "fixtures"
            / "telemetry.json"
        ).read_text()
    )
    payload.update(
        record_id="new-record",
        interval_start="2026-07-15T12:15:00Z",
        interval_end="2026-07-15T12:30:00Z",
        received_at="2026-07-15T12:30:01Z",
    )
    return payload
