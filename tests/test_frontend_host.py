from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app


def test_frontend_routes_serve_built_application_and_keep_api_404s(database, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<!doctype html><div id="root">SolarLens</div>')
    (dist / "assets" / "app.js").write_text("console.log('frontend')")
    with TestClient(
        create_app(Settings(database_path=database.path, frontend_dist=dist))
    ) as client:
        for path in (
            "/",
            "/consumer",
            "/consumer/",
            "/ops",
            "/ops/",
            "/demo/",
            "/consumer/history",
        ):
            response = client.get(path)
            assert response.status_code == 200
            assert "SolarLens" in response.text
            assert "text/html" in response.headers["content-type"]
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/api/v1/not-a-route").status_code == 404
        assert client.get("/api/v1/not-a-route").json()["code"] == "not_found"
        assert client.get("/api/v1/sites").status_code == 401
        assert client.get("/.local/alice-credentials.json").status_code == 404
        assert client.get("/database/solarlenes-demo.sqlite").status_code == 404
        assert "/consumer" not in client.get("/openapi.json").json()["paths"]


def test_api_still_runs_when_frontend_has_not_been_built(database, tmp_path):
    with TestClient(
        create_app(
            Settings(database_path=database.path, frontend_dist=tmp_path / "missing")
        )
    ) as client:
        assert client.get("/health").status_code == 200
        response = client.get("/consumer")
        assert response.status_code == 503
        assert response.json()["code"] == "frontend_not_built"
