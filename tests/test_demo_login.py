from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app


def test_demo_login_is_off_by_default(client):
    assert client.get("/api/v1/auth/demo-accounts").status_code == 404
    response = client.post("/api/v1/auth/demo-login", json={"username": "customer"})
    assert response.status_code == 404
    assert "/api/v1/auth/demo-login" not in client.get("/openapi.json").json()["paths"]


def test_demo_login_signs_in_existing_accounts_when_enabled(database):
    settings = Settings(
        database_path=database.path, demo_login=True, offer_worker=False
    )
    with TestClient(create_app(settings)) as client:
        accounts = client.get("/api/v1/auth/demo-accounts").json()
        names = {account["username"]: account for account in accounts}
        assert names["customer"]["role"] == "customer"
        assert names["customer"]["sites"]
        assert "password" not in str(accounts)
        session = client.post(
            "/api/v1/auth/demo-login", json={"username": "dispatcher"}
        ).json()
        assert session["user"]["role"] == "dispatcher"
        assert client.get("/api/v1/me").json()["user"]["username"] == "dispatcher"
        missing = client.post("/api/v1/auth/demo-login", json={"username": "nobody"})
        assert missing.status_code == 404
        bad = client.post("/api/v1/auth/demo-login", json={"username": ""})
        assert bad.status_code == 422


def test_lan_hosts_only_allowed_in_demo_lan_mode():
    from backend.security import is_private_host

    assert is_private_host("10.200.21.180")
    assert is_private_host("192.168.1.20")
    assert not is_private_host("8.8.8.8")
    assert not is_private_host("example.com")
    assert not is_private_host(None)
    assert Settings().demo_lan is False
