from datetime import UTC, datetime

import pytest

from backend.db import stamp
from backend.ingestion import ingest

LATEST = "/api/v1/sites/north-01/energy/latest"
HISTORY = "/api/v1/sites/north-01/energy"


def test_authentication_and_session_cookie(client, signed_in):
    assert client.get(LATEST).status_code == 401
    session = signed_in()
    assert session["user"]["role"] == "customer"
    assert client.get("/api/v1/me").json()["csrf_token"] == session["csrf_token"]
    assert client.cookies.get("solar_session")
    assert "password" not in str(client.get("/api/v1/me").json())


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/sites/south-01",
        "/api/v1/sites/south-01/energy/latest",
        "/api/v1/sites/south-01/energy?from=2026-07-15T00:00:00Z&to=2026-07-16T00:00:00Z",
        "/api/v1/sites/no-such-site",
    ],
)
def test_customer_cannot_change_site_ids(client, signed_in, path):
    signed_in()
    response = client.get(path)
    assert response.status_code == 404
    assert set(response.json()) == {"code", "message", "request_id"}
    assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_customer_site_list_and_no_area_access(client, signed_in):
    signed_in()
    assert [site["site_id"] for site in client.get("/api/v1/sites").json()] == [
        "north-01"
    ]
    assert client.get("/api/v1/areas").status_code == 403
    assert client.get("/api/v1/areas/north/summary").status_code == 403


def test_dispatcher_scope_and_coverage_denominator(client, signed_in):
    signed_in("dispatcher")
    assert len(client.get("/api/v1/sites").json()) == 8
    assert [area["area_id"] for area in client.get("/api/v1/areas").json()] == ["north"]
    summary = client.get("/api/v1/areas/north/summary").json()
    assert (
        summary["monitored_sites"],
        summary["recent_sites"],
        summary["stale_sites"],
        summary["unavailable_sites"],
    ) == (8, 6, 1, 1)
    assert summary["incident_status"] == "not_evaluated"
    assert summary["area"]["topology_mode"] == "simulated"
    assert client.get("/api/v1/areas/south/summary").status_code == 404
    assert client.get("/api/v1/sites/south-01/energy/latest").status_code == 404


def test_assigned_technician_has_only_explicit_sites(client, signed_in):
    signed_in("technician")
    assert [site["site_id"] for site in client.get("/api/v1/sites").json()] == [
        "north-01",
        "north-02",
    ]
    assert client.get("/api/v1/sites/north-04/energy/latest").status_code == 404
    assert client.get("/api/v1/areas/north/summary").status_code == 404


def test_latest_preserves_zero_and_derives_only_supported_load(client, signed_in):
    signed_in()
    response = client.get(LATEST)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["measurements"]["grid_import"]["value"] == 0
    assert body["measurements"]["home_load"]["value"] == 2
    assert body["measurements"]["home_load"]["origin"] == "derived"
    assert body["measurements"]["voltage"]["availability"] == "unsupported"
    assert body["provenance"]["source_mode"] == "synthetic"
    assert body["freshness"]["status"] == "fresh"
    assert body["freshness"]["clock"] == "replay"
    assert "raw_record_ref" not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_stale_and_missing_feeds_never_become_zero_production(client, signed_in):
    signed_in("dispatcher")
    stale = client.get("/api/v1/sites/north-02/energy/latest").json()
    assert stale["freshness"]["status"] == "stale"
    assert stale["measurements"]["pv_power"]["value"] == 6
    missing = client.get("/api/v1/sites/north-03/energy/latest").json()
    assert missing["freshness"]["status"] == "unavailable"
    assert missing["measurements"]["pv_power"]["value"] is None
    assert missing["measurements"]["pv_power"]["requirement"] == "mandatory"
    mandatory_only = client.get("/api/v1/sites/north-04/energy/latest").json()
    assert mandatory_only["measurements"]["grid_import"]["availability"] == "missing"
    assert mandatory_only["measurements"]["home_load"]["value"] is None


def test_soc_alone_does_not_establish_battery_power_or_load(client, signed_in):
    signed_in("supervisor")
    soc_only = client.get("/api/v1/sites/central-01/energy/latest").json()
    assert soc_only["measurements"]["battery_soc"]["value"] == 65
    assert soc_only["measurements"]["home_load"]["value"] is None
    battery = client.get("/api/v1/sites/central-02/energy/latest").json()
    assert battery["measurements"]["home_load"]["value"] == 2


def test_dc_pv_is_displayed_but_not_combined_with_ac_grid(
    client, signed_in, database, record
):
    record["measurements"]["pv_power"]["boundary"] = "dc"
    ingest(database, record)
    signed_in()
    body = client.get(LATEST).json()
    assert body["measurements"]["pv_power"]["value"] == 6
    assert body["measurements"]["home_load"]["value"] is None


def test_history_time_weighted_power_energy_and_coverage(
    client, signed_in, database, record
):
    record["measurements"]["pv_power"]["value"] = 2
    ingest(database, record)
    signed_in()
    response = client.get(
        HISTORY,
        params={
            "from": "2026-07-15T12:00:00Z",
            "to": "2026-07-15T13:00:00Z",
            "resolution": "1h",
        },
    )
    assert response.status_code == 200, response.text
    point = response.json()["points"][0]
    assert point["measurements"]["pv_power"]["value"] == 4
    assert point["energy_kwh"]["pv_power"] == 2
    assert point["coverage"]["pv_power"] == 0.5
    assert "partial_coverage" in point["measurements"]["pv_power"]["quality_flags"]


def test_coarse_samples_do_not_gain_finer_resolution_information(
    client, signed_in, database, record
):
    record.update(
        interval_end="2026-07-15T13:15:00Z", received_at="2026-07-15T13:15:01Z"
    )
    ingest(database, record)
    signed_in()
    response = client.get(
        HISTORY,
        params={
            "from": "2026-07-15T12:15:00Z",
            "to": "2026-07-15T13:15:00Z",
            "resolution": "15m",
        },
    )
    assert response.status_code == 200
    assert all(
        point["source_interval_seconds"] == [3600]
        for point in response.json()["points"]
    )
    assert all(
        "interval_average_distributed" in point["quality_flags"]
        for point in response.json()["points"]
    )
    assert (
        sum(point["energy_kwh"]["pv_power"] for point in response.json()["points"]) == 6
    )


@pytest.mark.parametrize(
    "start,end,hours",
    [
        ("2026-03-29T00:00:00+02:00", "2026-03-30T00:00:00+03:00", 23),
        ("2026-10-25T00:00:00+03:00", "2026-10-26T00:00:00+02:00", 25),
    ],
)
def test_local_dst_days_use_real_elapsed_hours(
    client, signed_in, database, record, start, end, hours
):
    record.update(interval_start=start, interval_end=end, received_at=end)
    ingest(database, record)
    signed_in()
    response = client.get(
        HISTORY, params={"from": start, "to": end, "resolution": "1h"}
    )
    assert response.status_code == 200
    assert len(response.json()["points"]) == hours
    assert (
        sum(point["energy_kwh"]["pv_power"] for point in response.json()["points"])
        == 6 * hours
    )


def test_invalid_readings_keep_their_state_and_evidence_in_history(
    client, signed_in, database, record
):
    record["measurements"]["pv_power"].update(
        value=None, availability="invalid", quality_flags=["sensor_rejected"]
    )
    record["quality_flags"] = [f"upstream-{number}" for number in range(32)]
    ingest(database, record)
    signed_in()
    latest = client.get(LATEST)
    assert latest.status_code == 200
    assert "mandatory_unavailable:pv_power" in latest.json()["quality_flags"]
    response = client.get(
        HISTORY, params={"from": record["interval_start"], "to": record["interval_end"]}
    )
    assert response.status_code == 200, response.text
    reading = response.json()["points"][0]["measurements"]["pv_power"]
    assert reading["availability"] == "invalid"
    assert reading["value"] is None
    assert reading["quality_flags"] == ["sensor_rejected"]


@pytest.mark.parametrize(
    "params",
    [
        {"from": "2026-07-15T12:00:00", "to": "2026-07-16T12:00:00Z"},
        {"from": "2026-07-16T12:00:00Z", "to": "2026-07-15T12:00:00Z"},
        {"from": "2026-01-01T00:00:00Z", "to": "2026-07-15T12:00:00Z"},
        {
            "from": "2026-07-15T12:00:00Z",
            "to": "2026-07-16T12:00:00Z",
            "resolution": "1s",
        },
    ],
)
def test_invalid_history_queries_have_consistent_errors(client, signed_in, params):
    signed_in()
    response = client.get(HISTORY, params=params)
    assert response.status_code == 422
    assert set(response.json()) == {"code", "message", "request_id"}


def test_replay_and_wall_clocks_remain_separate(client, signed_in, database):
    signed_in()
    with database.connect() as connection:
        connection.execute(
            "UPDATE settings SET value=? WHERE key='replay_at'",
            (stamp(datetime(2026, 7, 15, 15, tzinfo=UTC)),),
        )
    assert client.get(LATEST).json()["freshness"]["status"] == "stale"
    assert client.get("/api/v1/me").status_code == 200


def test_unknown_replay_clock_does_not_fall_back_to_wall_time(
    client, signed_in, database
):
    signed_in()
    with database.connect() as connection:
        connection.execute("DELETE FROM settings WHERE key='replay_at'")
    assert client.get(LATEST).json()["freshness"]["status"] == "unknown_clock"


def test_logout_requires_csrf_and_revokes_session(client, signed_in):
    session = signed_in()
    assert client.post("/api/v1/auth/logout").status_code == 403
    assert (
        client.post(
            "/api/v1/auth/logout", headers={"X-CSRF-Token": session["csrf_token"]}
        ).status_code
        == 204
    )
    assert client.get("/api/v1/me").status_code == 401


def test_expired_session_is_rejected(client, signed_in, database):
    signed_in()
    with database.connect() as connection:
        connection.execute("UPDATE sessions SET expires_at='2000-01-01T00:00:00+00:00'")
    assert client.get(LATEST).status_code == 401


def test_bad_password_unknown_user_and_rate_limit(client):
    for username in ["customer", "unknown"] * 10:
        assert (
            client.post(
                "/api/v1/auth/login",
                json={"username": username, "password": "incorrect"},
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "customer", "password": "test-password-only"},
        ).status_code
        == 429
    )


def test_origins_and_cookie_flags(client, signed_in):
    bad = client.post(
        "/api/v1/auth/login",
        json={"username": "customer", "password": "test-password-only"},
        headers={"Origin": "https://untrusted.example"},
    )
    assert bad.status_code == 403
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "customer", "password": "test-password-only"},
        headers={"Origin": "http://localhost:5173"},
    )
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_pipeline_key_is_separate_from_customer_session(
    client, signed_in, record, database
):
    signed_in()
    assert client.post("/internal/v1/telemetry", json=record).status_code == 401
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0] == 0
    headers = {"X-Ingest-Key": "test-pipeline-key"}
    assert (
        client.post("/internal/v1/telemetry", json=record, headers=headers).json()[
            "status"
        ]
        == "accepted"
    )
    assert (
        client.post("/internal/v1/telemetry", json=record, headers=headers).json()[
            "status"
        ]
        == "duplicate"
    )
    invalid = client.post(
        "/internal/v1/telemetry", json={"wrong": "shape"}, headers=headers
    )
    assert invalid.status_code == 422


def test_payload_size_and_malformed_json(client):
    assert (
        client.post("/internal/v1/telemetry", content="x" * 262145).status_code == 413
    )
    response = client.post(
        "/api/v1/auth/login", content="{", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"


def test_openapi_has_resolvable_contracts_and_error_models(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert "TelemetryRecord" in schema["components"]["schemas"]
    assert schema["paths"]["/internal/v1/telemetry"]["post"]["security"] == [
        {"APIKeyHeader": []}
    ]

    def check(node):
        if isinstance(node, dict):
            if "$ref" in node:
                target = schema
                for part in node["$ref"].removeprefix("#/").split("/"):
                    target = target[part]
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for item in node:
                check(item)

    check(schema)
