import sqlite3
from pathlib import Path

import pytest
from conftest import CONFIG, envelope
from test_semantics import fr_pf

from backend.providers import backend_site_id, import_provider_snapshot, readonly
from backend.provisioning import grant_access
from engine.derive import build_frames
from engine.registry import Registry
from engine.sites import SiteRegistry
from engine.storage import Store


@pytest.fixture
def provider_import(database, mini, gen, tmp_path):
    source = mini(
        [
            envelope("S1", "currentPowerFlow", {}, delivery_id="S1-unsupported"),
            envelope(
                "F1",
                "GetPowerFlowRealtimeData",
                fr_pf({"P_PV": 4200.0, "Mode": "produce-only"}),
                delivery_id="F1",
            ),
            envelope(
                "F3",
                "GetPowerFlowRealtimeData",
                fr_pf(
                    {
                        "P_PV": 3300.0,
                        "P_Akku": -800.0,
                        "P_Grid": -1500.0,
                        "P_Load": -900.0,
                    }
                ),
                delivery_id="F3",
            ),
            envelope(
                "H1",
                "getDevHistoryKpi",
                {
                    "success": True,
                    "failCode": 0,
                    "message": None,
                    "params": {"devTypeId": 38, "currentTime": 1784192700000},
                    "data": [
                        {
                            "devId": 1000000035350464,
                            "collectTime": 1784192400000,
                            "dataItemMap": {"active_power": 4.2},
                        }
                    ],
                },
                {"devTypeId": 38},
                delivery_id="H1",
            ),
        ]
    )
    sites = gen / "demo_data/sites.json"
    path = tmp_path / "mini.sqlite"
    store = Store(path)
    frames = tmp_path / "frames.csv"
    build_frames(store, Registry([CONFIG]), SiteRegistry(sites)).to_csv(
        frames, index=False
    )
    store.close()
    result = import_provider_snapshot(database, path, sites, frames)
    identities = {item["native_site_id"]: item for item in result["sites"]}
    yield result, identities, (path, sites, frames)
    source.close()


def query():
    return {"from": "2026-07-16T09:00:00Z", "to": "2026-07-16T09:15:00Z"}


def test_import_is_idempotent_and_never_copies_vendor_role_grants(
    database, provider_import, client, signed_in
):
    result, identities, paths = provider_import
    assert result["status"] == "imported"
    assert len(identities) == 4
    assert import_provider_snapshot(database, *paths)["status"] == "duplicate"
    signed_in("supervisor")
    assert client.get("/api/v1/provider/sites").json() == []
    with database.connect() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM provider_imports").fetchone()[0]
            == 1
        )


def test_canonical_values_boundaries_requirements_and_time_roles_survive(
    database, provider_import, client, signed_in
):
    _, identities, _ = provider_import
    identity = identities["FR-SITE-0003"]
    grant_access(database, "customer", identity["site_id"], "site")
    signed_in()
    sites = client.get("/api/v1/provider/sites").json()
    assert sites == [identity]
    response = client.get(
        f"/api/v1/sites/{identity['site_id']}/provider/observations",
        params={**query(), "metric": "pv_dc_kw"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    reading = body["items"][0]
    assert reading["canonical_value"] == 3.3
    assert reading["canonical_unit"] == "kW"
    assert reading["boundary"] == "dc_pv_input"
    assert reading["requirement_class"] == "vendor_response_required"
    assert reading["measurement_time_utc"] is None
    assert reading["effective_time_basis"] == "response_time"
    assert reading["value_origin"] == "simulated_observation"
    assert body["site"]["source_mode"] == "synthetic"
    assert "raw_record" not in response.text and "source_path" not in response.text


def test_optional_nulls_and_large_device_ids_are_preserved(
    database, provider_import, client, signed_in
):
    _, identities, _ = provider_import
    site = identities["NE=33554791"]["site_id"]
    grant_access(database, "customer", site, "site")
    signed_in()
    response = client.get(
        f"/api/v1/sites/{site}/provider/observations",
        params={**query(), "metric": "inverter_temperature_c"},
    )
    assert response.status_code == 200, response.text
    reading = response.json()["items"][0]
    assert reading["device_id"] == "1000000035350464"
    assert reading["canonical_value"] is None
    assert reading["availability_status"] == "missing"
    assert reading["requirement_class"] == "optional"


@pytest.mark.parametrize("route", ["latest", "observations", "frames"])
def test_provider_routes_reject_cross_customer_access(
    database, provider_import, client, signed_in, route
):
    _, identities, _ = provider_import
    mine = identities["FR-SITE-0003"]["site_id"]
    other = identities["FR-SITE-0001"]["site_id"]
    grant_access(database, "customer", mine, "site")
    grant_access(database, "other-customer", other, "site")
    signed_in()
    response = client.get(f"/api/v1/sites/{other}/provider/{route}", params=query())
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_frames_and_latest_preserve_source_granularity_and_health(
    database, provider_import, client, signed_in
):
    _, identities, _ = provider_import
    site = identities["FR-SITE-0003"]["site_id"]
    grant_access(database, "customer", site, "site")
    signed_in()
    response = client.get(
        f"/api/v1/sites/{site}/provider/frames",
        params={**query(), "metric": "pv_dc_kw"},
    )
    assert response.status_code == 200, response.text
    frame = response.json()["items"][0]
    assert frame["value"] == 3.3
    assert frame["aggregation"] == "mean"
    assert frame["coverage_ratio"] < 1
    assert frame["original_cadence_s"] == 60
    latest = client.get(f"/api/v1/sites/{site}/provider/latest")
    assert latest.status_code == 200, latest.text
    assert latest.json()["source_health"][0]["freshness_status"] == "stale"
    assert latest.json()["site"]["as_of_utc"] == "2026-07-21T21:00:00Z"


def test_provider_filters_and_pagination_are_bounded(
    database, provider_import, client, signed_in
):
    _, identities, _ = provider_import
    site = identities["FR-SITE-0003"]["site_id"]
    grant_access(database, "customer", site, "site")
    signed_in()
    path = f"/api/v1/sites/{site}/provider/observations"
    first = client.get(path, params={**query(), "limit": 1}).json()
    second = client.get(path, params={**query(), "limit": 1, "offset": 1}).json()
    assert first["total"] > 1 and second["total"] == first["total"]
    assert first["items"][0]["obs_id"] != second["items"][0]["obs_id"]
    assert client.get(path, params={**query(), "limit": 1001}).status_code == 422
    assert (
        client.get(path, params={**query(), "metric": "' OR 1=1 --"}).json()["total"]
        == 0
    )
    assert (
        client.get(path, params={**query(), "from": "2026-07-16T09:00:00"}).status_code
        == 422
    )


def test_source_snapshots_are_read_only_and_wal_updates_create_new_import(
    database, provider_import
):
    first, _, paths = provider_import
    with database.connect() as connection:
        path = connection.execute(
            "SELECT database_path FROM provider_imports"
        ).fetchone()[0]
    with readonly(Path(path)) as source:
        with pytest.raises(sqlite3.OperationalError):
            source.execute("DELETE FROM observations")
    # Keep the source WAL open: hashing just the main file would miss this update.
    with sqlite3.connect(paths[0]) as source:
        source.execute("UPDATE runs SET as_of_utc='2026-07-22T21:00:00+00:00'")
        source.commit()
        second = import_provider_snapshot(database, *paths)
    assert second["status"] == "imported"
    assert second["import_id"] != first["import_id"]


def test_identity_hashes_do_not_collapse_provider_or_account_scope():
    keys = ["a|account1|007", "a|account2|007", "b|account1|007", "a|account1|7"]
    assert len({backend_site_id(key) for key in keys}) == 4


def test_unsupported_source_keeps_unknown_cadence_and_no_fabricated_frames(
    database, provider_import, client, signed_in
):
    _, identities, _ = provider_import
    site = identities["2718281"]["site_id"]
    grant_access(database, "customer", site, "site")
    signed_in()
    response = client.get(f"/api/v1/sites/{site}/provider/latest")
    assert response.status_code == 200, response.text
    assert response.json()["frames"] == []
    health = response.json()["source_health"][0]
    assert health["freshness_status"] == "capability_unsupported"
    assert health["cadence_s"] is None
    assert health["stale_threshold_s"] is None


def test_missing_snapshot_returns_a_service_error(
    database, provider_import, client, signed_in
):
    _, identities, _ = provider_import
    site = identities["FR-SITE-0003"]["site_id"]
    grant_access(database, "customer", site, "site")
    with database.connect() as connection:
        connection.execute(
            "UPDATE provider_imports SET database_path=?",
            (str(database.path.parent / "absent.sqlite"),),
        )
    signed_in()
    response = client.get(f"/api/v1/sites/{site}/provider/observations", params=query())
    assert response.status_code == 503
    assert response.json()["code"] == "provider_snapshot_unavailable"
