"""Operations API: scope, incidents and their log, crews, assignments, revenue, video."""

import json
from pathlib import Path

import pytest

from backend.provisioning import add_crew_member, create_crew

OPS = "/api/v1/ops"
REQUESTS = "/api/v1/support/requests"
SECTOR_6 = {
    "demo-inc-s6-09-production",
    "demo-inc-s6-02-telemetry",
    "demo-inc-s6-03-telemetry",
}
SECTOR_3 = {"demo-inc-s3-04-area", "demo-inc-s3-09-voltage"}
SOLAR_CARE = "Sector 6 Solar Care"
PROFILES = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "backend"
        / "fixtures"
        / "site_profiles.json"
    ).read_text(encoding="utf-8")
)
MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + bytes(range(256)) * 4
WEBM = b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01" + bytes(range(256)) * 4


def post(client, session, path, body=None):
    return client.post(
        path,
        json={} if body is None else body,
        headers={"X-CSRF-Token": session["csrf_token"]},
    )


def ids(response):
    assert response.status_code == 200, response.text
    return [item["incident_id"] for item in response.json()]


def upload(client, session, request_id, data, content_type="video/mp4", **query):
    headers = {"Content-Type": content_type}
    if session:
        headers["X-CSRF-Token"] = session["csrf_token"]
    return client.post(
        f"{REQUESTS}/{request_id}/media",
        params={"filename": "clip.mp4", **query},
        content=data,
        headers=headers,
    )


def test_customers_are_refused_operations(client, signed_in):
    session = signed_in()
    for path in ("map", "incidents", "teams", "revenue", "capacity"):
        response = client.get(f"{OPS}/{path}")
        assert response.status_code == 403, path
        assert response.json()["code"] == "operations_required"
    incident = f"{OPS}/incidents/demo-inc-s6-09-production"
    assert client.get(incident).status_code == 403
    for action in ("assign", "send-team", "resolve"):
        assert post(client, session, f"{incident}/{action}").status_code == 403
    assert post(client, session, f"{OPS}/dispatch/auto").status_code == 403


def test_scope_of_every_view_per_role(client, signed_in):
    signed_in("dispatcher")
    assert set(ids(client.get(f"{OPS}/incidents"))) == SECTOR_6
    view = client.get(f"{OPS}/map").json()
    sites = view["sites"]
    assert len(sites) == 14 and {site["area_id"] for site in sites} == {"sector-6"}
    assert {site["area_alias"] for site in sites} == {"Sector 6"}
    no_feed = next(site for site in sites if site["site_id"] == "s6-03")
    assert (no_feed["freshness_status"], no_feed["worst_tier"]) == ("unavailable", "P3")
    assert no_feed["open_incidents"] == 1 and no_feed["zone"] == "Militari"
    assert (no_feed["cluster"], no_feed["alias"]) == (
        "militari-homes",
        "Home · Militari 3",
    )
    # Only clusters with a site in scope, in fixture order, with their metadata.
    assert view["clusters"] == [
        cluster for cluster in PROFILES["clusters"] if cluster["area_id"] == "sector-6"
    ]
    assert [cluster["id"] for cluster in view["clusters"]] == [
        "militari-homes",
        "drumul-taberei-homes",
        "militari-platform",
    ]
    assert [crew["name"] for crew in client.get(f"{OPS}/teams").json()["crews"]] == [
        SOLAR_CARE
    ]
    assert client.get(f"{OPS}/capacity").json() == {
        "areas": [
            {
                "area_id": "sector-6",
                "alias": "Sector 6",
                "sites": 14,
                "installed_kwp": 360,
            }
        ],
        "total_installed_kwp": 360,
    }
    assert client.get(f"{OPS}/revenue").json()["code"] == "supervisor_required"
    assert client.get(f"{OPS}/incidents/demo-inc-s3-04-area").status_code == 404

    signed_in("supervisor")
    incidents = client.get(f"{OPS}/incidents").json()
    assert len(incidents) == 11
    order = [(item["tier"], item["created_at"]) for item in incidents]
    assert order == sorted(order) and incidents[0]["tier"] == "P0"
    assert all("Synthetic" in item["evidence"] for item in incidents)
    map_view = client.get(f"{OPS}/map").json()
    assert len(map_view["sites"]) == 60 and "SYNTHETIC" in map_view["note"]
    assert map_view["center"]["zoom"] == 11
    assert map_view["clusters"] == PROFILES["clusters"]
    assert {site["cluster"] for site in map_view["sites"]} - {None} == {
        cluster["id"] for cluster in PROFILES["clusters"]
    }
    crews = client.get(f"{OPS}/teams").json()["crews"]
    assert len(crews) == 7 and len({crew["area_id"] for crew in crews}) == 7
    assert all("Billing" not in crew["skills"] for crew in crews)
    capacity = client.get(f"{OPS}/capacity").json()
    assert capacity["total_installed_kwp"] == sum(
        profile["installed_kwp"] for profile in PROFILES["profiles"]
    )

    signed_in("area-manager")
    assert set(ids(client.get(f"{OPS}/incidents"))) == SECTOR_6
    assert {site["area_id"] for site in client.get(f"{OPS}/map").json()["sites"]} == {
        "sector-6"
    }

    # A technician's zone is his crew's area, beyond his two telemetry site grants.
    signed_in("technician")
    assert set(ids(client.get(f"{OPS}/incidents"))) == SECTOR_6
    assert client.get("/api/v1/sites/s6-03").status_code == 404
    assert len(client.get(f"{OPS}/map").json()["sites"]) == 14
    assert [crew["name"] for crew in client.get(f"{OPS}/teams").json()["crews"]] == [
        SOLAR_CARE
    ]
    assert client.get(f"{OPS}/revenue").status_code == 403

    signed_in("technician-s3")
    assert set(ids(client.get(f"{OPS}/incidents"))) == SECTOR_3
    assert client.get(f"{OPS}/incidents/demo-inc-s6-09-production").status_code == 404
    assert client.get(f"{OPS}/capacity").json()["areas"][0]["area_id"] == "sector-3"


def test_support_requests_open_logged_incidents(client, signed_in):
    session = signed_in()
    body = {
        "site_id": "s6-01",
        "request_type": "battery",
        "description": "The battery has not charged since yesterday.",
    }
    standard = post(client, session, REQUESTS, body).json()
    danger = post(client, session, REQUESTS, {**body, "immediate_danger": True}).json()
    billing = post(
        client, session, REQUESTS, {**body, "request_type": "billing"}
    ).json()
    assert billing["routed_to"] == "Dispatch desk"
    assert standard["incident_id"] and standard["meeting"] is None
    assert standard["media"] is None
    replies = f"{REQUESTS}/{standard['request_id']}/replies"
    assert (
        post(client, session, replies, {"text": "It is still empty."}).status_code
        == 201
    )

    staff = signed_in("dispatcher")
    incidents = client.get(f"{OPS}/incidents").json()
    assert incidents[0]["incident_id"] == danger["incident_id"]
    assert (incidents[0]["tier"], incidents[0]["family"]) == ("P0", "Local issue")
    linked = {item["incident_id"]: item for item in incidents}
    assert linked[standard["incident_id"]]["title"] == (
        "Customer request: Battery or storage issue"
    )
    assert linked[standard["incident_id"]]["tier"] == "P2"
    assert linked[standard["incident_id"]]["source"] == "customer_request"
    assert (
        linked[standard["incident_id"]]["support_request_id"]
        == (standard["request_id"])
    )
    assert linked[standard["incident_id"]]["evidence"] == body["description"]
    assert linked[billing["incident_id"]]["family"] == "Billing"
    assert (
        post(client, staff, replies, {"text": "Checking the logs."}).status_code == 201
    )
    log = client.get(f"{OPS}/incidents/{standard['incident_id']}").json()["log"]
    assert [entry["action"] for entry in log] == [
        "opened",
        "customer_follow_up",
        "staff_reply",
    ]
    assert log[0]["actor"] == "customer" and "Checking the logs." in log[2]["detail"]

    # Severity first: the danger report gets the only Sector 6 crew; billing has none.
    result = post(client, staff, f"{OPS}/dispatch/auto").json()
    assert result["assigned"] == [
        {"incident_id": danger["incident_id"], "crew_name": SOLAR_CARE, "tier": "P0"}
    ]
    skipped = {item["incident_id"]: item for item in result["skipped"]}
    assert skipped[billing["incident_id"]]["reason"] == "no_eligible_crew"
    assert skipped["demo-inc-s6-09-production"]["reason"] == "no_available_crew"
    assert [item["tier"] for item in result["skipped"]] == sorted(
        item["tier"] for item in result["skipped"]
    )
    detail = client.get(f"{OPS}/incidents/{danger['incident_id']}").json()
    assert detail["status"] == "assigned"
    assert "Auto-assigned by severity" in detail["log"][-1]["detail"]
    # The dispatcher answers and resolves billing questions without a crew.
    resolved = post(client, staff, f"{OPS}/incidents/{billing['incident_id']}/resolve")
    assert resolved.json()["status"] == "resolved"


def test_dispatcher_assignment_rules(client, signed_in):
    manager = signed_in("supervisor")
    target = f"{OPS}/incidents/demo-inc-s6-09-production"
    denied = post(client, manager, f"{target}/assign")
    assert denied.json()["code"] == "dispatcher_required"
    assert post(client, manager, f"{OPS}/dispatch/auto").status_code == 403

    session = signed_in("dispatcher")
    wrong = post(
        client, session, f"{target}/assign", {"crew_id": "sector-3-solar-care"}
    )
    assert (wrong.status_code, wrong.json()["code"]) == (422, "crew_not_eligible")
    assert (
        post(client, session, f"{target}/assign", {"crew_id": "nope"}).status_code
        == 404
    )
    assert post(client, session, f"{target}/assign", {"crew": "x"}).status_code == 422
    out_of_scope = f"{OPS}/incidents/demo-inc-s3-04-area/assign"
    assert post(client, session, out_of_scope).status_code == 404
    assert client.post(f"{target}/assign", json={}).status_code == 403  # CSRF

    assigned = post(client, session, f"{target}/assign").json()
    assert assigned["status"] == "assigned"
    assert assigned["assignment"]["crew_name"] == SOLAR_CARE
    assert assigned["assignment"]["kind"] == "dispatch"
    again = post(client, session, f"{target}/assign")
    assert (again.status_code, again.json()["code"]) == (409, "already_assigned")
    stale = f"{OPS}/incidents/demo-inc-s6-02-telemetry/assign"
    busy = post(client, session, stale, {"crew_id": "sector-6-solar-care"})
    assert (busy.status_code, busy.json()["code"]) == (409, "crew_unavailable")
    none = post(client, session, stale)
    assert (none.status_code, none.json()["code"]) == (409, "no_available_crew")
    result = post(client, session, f"{OPS}/dispatch/auto").json()
    assert result["assigned"] == []
    assert [(item["tier"], item["reason"]) for item in result["skipped"]] == [
        ("P2", "no_available_crew"),
        ("P3", "no_available_crew"),
    ]

    done = post(client, session, f"{target}/resolve").json()
    assert done["status"] == "resolved" and done["assignment"] is None
    assert [entry["action"] for entry in done["log"]] == [
        "opened",
        "assigned",
        "resolved",
    ]
    assert post(client, session, f"{target}/resolve").status_code == 409
    assert post(client, session, f"{target}/assign").status_code == 409
    result = post(client, session, f"{OPS}/dispatch/auto").json()
    assert [item["incident_id"] for item in result["assigned"]] == [
        "demo-inc-s6-02-telemetry"
    ]
    assert ids(client.get(f"{OPS}/incidents")) == [
        "demo-inc-s6-02-telemetry",
        "demo-inc-s6-03-telemetry",
    ]
    assert "demo-inc-s6-09-production" in ids(
        client.get(f"{OPS}/incidents", params={"status": "all"})
    )


def test_technician_send_team_and_meetings(client, signed_in, database):
    customer = signed_in()
    request = post(
        client,
        customer,
        REQUESTS,
        {
            "site_id": "s6-01",
            "request_type": "solar",
            "description": "Production looks low today.",
        },
    ).json()
    incident = f"{OPS}/incidents/{request['incident_id']}"
    # A second Sector 6 crew lets us test conflicts between crews in one zone.
    create_crew(
        database, "Night Crew", "sector-6", ["Production", "Telemetry"], "18:00-23:00"
    )
    add_crew_member(database, "Night Crew", "technician-s3")

    session = signed_in("technician")
    assert post(client, session, f"{incident}/assign").json()["code"] == (
        "dispatcher_required"
    )
    assert post(client, session, f"{OPS}/dispatch/auto").status_code == 403
    elsewhere = f"{OPS}/incidents/demo-inc-s3-09-voltage"
    assert post(client, session, f"{elsewhere}/send-team").status_code == 404
    slot = {"start": "2026-07-16T10:00:00Z", "end": "2026-07-16T11:00:00Z"}
    for bad in (
        {"start": slot["end"], "end": slot["start"]},
        {"start": slot["start"], "end": "2026-07-16T14:30:00Z"},
        {"start": "2026-07-16T10:00:00", "end": "2026-07-16T11:00:00"},
    ):
        assert post(client, session, f"{incident}/meeting", bad).status_code == 422
    booked = post(client, session, f"{incident}/meeting", slot).json()
    assert booked["status"] == "meeting_scheduled"
    assert booked["assignment"]["kind"] == "meeting"
    assert booked["log"][-1]["action"] == "meeting_scheduled"
    assert "by technician" in booked["log"][-1]["detail"]
    no_feed = f"{OPS}/incidents/demo-inc-s6-03-telemetry"
    overlap = post(
        client,
        session,
        f"{no_feed}/meeting",
        {"start": "2026-07-16T10:30:00Z", "end": "2026-07-16T11:30:00Z"},
    )
    assert (overlap.status_code, overlap.json()["code"]) == (409, "meeting_overlap")
    adjacent = {"start": "2026-07-16T11:00:00Z", "end": "2026-07-16T12:00:00Z"}
    assert post(client, session, f"{no_feed}/meeting", adjacent).status_code == 200

    # Meetings do not block the crew; an on-site dispatch does.
    production = f"{OPS}/incidents/demo-inc-s6-09-production"
    sent = post(client, session, f"{production}/send-team").json()
    assert sent["status"] == "team_sent"
    assert (sent["assignment"]["kind"], sent["assignment"]["status"]) == (
        "dispatch",
        "team_sent",
    )
    stale = f"{OPS}/incidents/demo-inc-s6-02-telemetry"
    busy = post(client, session, f"{stale}/send-team")
    assert (busy.status_code, busy.json()["code"]) == (409, "crew_unavailable")
    assert post(client, session, f"{production}/send-team").status_code == 409

    other = signed_in("technician-s3")
    taken = post(client, other, f"{production}/send-team")
    assert (taken.status_code, taken.json()["code"]) == (409, "assigned_to_other_crew")
    taken = post(client, other, f"{incident}/meeting", adjacent)
    assert taken.json()["code"] == "assigned_to_other_crew"
    refused = post(client, other, f"{production}/resolve")
    assert (refused.status_code, refused.json()["code"]) == (
        403,
        "crew_member_required",
    )
    night = post(client, other, f"{stale}/send-team").json()
    assert night["assignment"]["crew_name"] == "Night Crew"

    session = signed_in("technician")
    done = post(client, session, f"{production}/resolve").json()
    assert done["status"] == "resolved"
    crew = client.get(f"{OPS}/teams").json()["crews"][0]
    assert crew["name"] == SOLAR_CARE and crew["available"] is True
    assert crew["active_assignment"]["kind"] == "meeting"

    signed_in()
    mine = next(
        item
        for item in client.get(REQUESTS).json()
        if item["request_id"] == request["request_id"]
    )
    assert mine["meeting"] == {
        "start": "2026-07-16T10:00:00Z",
        "end": "2026-07-16T11:00:00Z",
        "crew_name": SOLAR_CARE,
    }


def test_teams_report_matches_for_area_and_overall_managers(client, signed_in):
    session = signed_in("dispatcher")
    first = post(client, session, f"{OPS}/dispatch/auto").json()["assigned"][0]
    post(client, session, f"{OPS}/incidents/{first['incident_id']}/resolve")
    post(client, session, f"{OPS}/dispatch/auto")

    signed_in("supervisor")
    overall = client.get(f"{OPS}/teams").json()
    solar = next(crew for crew in overall["crews"] if crew["name"] == SOLAR_CARE)
    assert solar["report"] == {
        "assigned_total": 2,
        "completed_total": 1,
        "open_by_tier": {"P0": 0, "P1": 0, "P2": 1, "P3": 0},
        "completed_by_tier": {"P0": 0, "P1": 1, "P2": 0, "P3": 0},
    }
    assert solar["available"] is False and solar["members"] == ["technician"]
    assert solar["active_assignment"]["incident_id"] == "demo-inc-s6-02-telemetry"
    assert solar["area_alias"] == "Sector 6"
    assert overall["unassigned_incidents"] == 9
    report = overall["assignments"]
    assert [(row["tier"], row["status"]) for row in report] == [
        ("P2", "assigned"),
        ("P1", "completed"),
    ]
    assert report[1]["created_by"] == "dispatcher" and report[1]["completed_at"]

    signed_in("area-manager")
    sector = client.get(f"{OPS}/teams").json()
    assert sector["crews"] == [solar]
    assert sector["assignments"] == report
    assert sector["unassigned_incidents"] == 1


def money(value):
    return round(value, 2)


def test_revenue_estimate_is_scoped_and_uses_contract_prices(client, signed_in):
    business = signed_in("business-customer")
    contract = {
        "supplier": "Demo Energy",
        "pricing": "fixed",
        "import_price_ron_kwh": 1.2,
        "export_price_ron_kwh": 0.5,
    }
    saved = post(client, business, "/api/v1/sites/s3-06/contract", contract)
    assert saved.status_code == 200

    signed_in("dispatcher")
    assert client.get(f"{OPS}/revenue").json()["code"] == "supervisor_required"

    signed_in("supervisor")
    view = client.get(f"{OPS}/revenue").json()
    assert (view["period"], view["currency"]) == ("monthly", "RON")
    assert "synthetic" in view["basis"] and "not invoices" in view["basis"]
    accounts = {item["site_id"]: item for item in view["business_accounts"]}
    # By hand: 2600 kWh x 1.2 + 160 fee - 180 kWh x 0.5 = 3190 RON.
    bistro = accounts["s3-06"]
    assert (bistro["energy_sales_ron"], bistro["export_payments_ron"]) == (3120, 90)
    assert (bistro["service_fees_ron"], bistro["net_revenue_ron"]) == (160, 3190)
    assert bistro["price_source"] == "contract"
    # Default tariff 1.3 / 0.55: 14000 x 1.3 + 600 - 3000 x 0.55 = 17150 RON.
    factory = accounts["s6-13"]
    assert (factory["net_revenue_ron"], factory["price_source"]) == (
        17150,
        "default_tariff",
    )
    nets = [item["net_revenue_ron"] for item in view["business_accounts"]]
    assert nets == sorted(nets, reverse=True) and len(nets) == 25

    tariff = PROFILES["default_tariff"]
    expected = {"home": 0.0, "business": 0.0}
    for profile in PROFILES["profiles"]:
        prices = (
            (1.2, 0.5)
            if profile["site_id"] == "s3-06"
            else (tariff["import_price_ron_kwh"], tariff["export_price_ron_kwh"])
        )
        expected[profile["segment"]] += (
            profile["monthly_import_kwh"] * prices[0]
            + profile["service_fee_ron"]
            - profile["monthly_export_kwh"] * prices[1]
        )
    total = sum(expected.values())
    assert view["totals"]["sites"] == 60
    assert view["totals"]["net_revenue_ron"] == money(total)
    assert view["annualized_net_revenue_ron"] == money(total * 12)
    segments = view["by_segment"]
    assert segments["business"]["net_revenue_ron"] == money(expected["business"])
    assert segments["business"]["sites"] == 25 and segments["home"]["sites"] == 35
    assert (
        abs(segments["business"]["share_of_net"] - expected["business"] / total) < 1e-3
    )
    assert segments["business"]["share_of_net"] > 0.9
    assert [area["area_id"] for area in view["by_area"]] == ["ilfov"] + [
        f"sector-{n}" for n in range(1, 7)
    ]
    assert sum(area["business_sites"] for area in view["by_area"]) == 25
    ilfov = view["by_area"][0]
    assert (ilfov["alias"], ilfov["sites"], ilfov["business_sites"]) == (
        "Ilfov",
        10,
        10,
    )

    signed_in("area-manager")
    sector = client.get(f"{OPS}/revenue").json()
    assert [area["area_id"] for area in sector["by_area"]] == ["sector-6"]
    assert sector["totals"]["sites"] == 14
    assert {item["area_id"] for item in sector["business_accounts"]} == {"sector-6"}


def test_support_video_upload_and_download(client, signed_in):
    session = signed_in()
    body = {
        "site_id": "s6-01",
        "request_type": "panel-damage",
        "description": "There is a crack on one panel.",
    }
    first, second, third = (
        post(client, session, REQUESTS, body).json() for _ in range(3)
    )
    danger = post(client, session, REQUESTS, {**body, "immediate_danger": True}).json()

    assert upload(client, None, first["request_id"], MP4).status_code == 403  # CSRF
    created = upload(
        client, session, first["request_id"], MP4, filename="../../My clip?.mp4"
    )
    assert created.status_code == 201, created.text
    media = created.json()["media"]
    assert (media["filename"], media["content_type"]) == ("My clip_.mp4", "video/mp4")
    assert media["size_bytes"] == len(MP4)
    again = upload(client, session, first["request_id"], MP4)
    assert (again.status_code, again.json()["code"]) == (409, "media_exists")
    webm = upload(client, session, second["request_id"], WEBM, "video/webm")
    assert (
        webm.status_code == 201 and webm.json()["media"]["content_type"] == "video/webm"
    )

    target = third["request_id"]
    for data, kind, status, code in (
        (MP4, "image/png", 415, "unsupported_media_type"),
        (WEBM, "video/mp4", 422, "invalid_media"),
        (MP4, "video/webm", 422, "invalid_media"),
        (b"", "video/mp4", 422, "invalid_media"),
        (b"\0" * (30 * 1024 * 1024 + 1), "video/mp4", 413, "media_too_large"),
    ):
        refused = upload(client, session, target, data, kind)
        assert (refused.status_code, refused.json()["code"]) == (status, code)
    refused = upload(client, session, danger["request_id"], MP4)
    assert (refused.status_code, refused.json()["code"]) == (422, "media_not_allowed")
    # Other routes keep the small JSON body limit.
    big = post(client, session, f"{REQUESTS}/{target}/replies", {"text": "x" * 300000})
    assert (big.status_code, big.json()["code"]) == (413, "request_too_large")

    stored = list(client.app.state.settings.media_dir.iterdir())
    assert len(stored) == 2 and all("clip" not in path.name for path in stored)
    path = f"/api/v1/support/media/{media['media_id']}"
    download = client.get(path)
    assert download.status_code == 200 and download.content == MP4
    assert download.headers["content-type"] == "video/mp4"
    assert download.headers["content-disposition"].startswith("inline")
    assert download.headers["cache-control"] == "no-store"
    partial = client.get(path, headers={"Range": "bytes=0-7"})
    assert partial.status_code == 206 and partial.content == MP4[:8]
    listed = client.get(REQUESTS).json()
    assert {item["request_id"]: item["media"] for item in listed}[
        first["request_id"]
    ] == media

    other = signed_in("other-customer")
    assert client.get(path).status_code == 404
    assert upload(client, other, third["request_id"], MP4).status_code == 404

    staff = signed_in("dispatcher")
    assert client.get(path).content == MP4
    refused = upload(client, staff, third["request_id"], MP4)
    assert refused.json()["code"] == "customer_required"
    assert client.get("/api/v1/support/media/unknown").status_code == 404
    log = client.get(f"{OPS}/incidents/{first['incident_id']}").json()["log"]
    assert log[-1]["action"] == "customer_video"


def test_crew_cli_creates_crews_and_members(database, monkeypatch, capsys):
    from backend.__main__ import main

    monkeypatch.setenv("SOLAR_DATABASE", str(database.path))
    main(
        [
            "create-crew",
            "Night Crew",
            "--area",
            "sector-4",
            "--skills",
            "Production, Area event",
            "--shift",
            "18:00-23:00",
        ]
    )
    main(["add-crew-member", "Night Crew", "technician"])
    assert "Created crew Night Crew (night-crew)" in capsys.readouterr().out
    with database.connect() as connection:
        crew = connection.execute(
            "SELECT * FROM crews WHERE crew_id='night-crew'"
        ).fetchone()
        members = connection.execute(
            "SELECT user_id FROM crew_members WHERE crew_id='night-crew'"
        ).fetchall()
    assert json.loads(crew["skills"]) == ["Production", "Area event"]
    assert (crew["area_id"], crew["shift"]) == ("sector-4", "18:00-23:00")
    assert [row["user_id"] for row in members] == ["technician"]
    for argv in (
        ["create-crew", "Night Crew", "--area", "sector-4", "--skills", "Other"],
        ["create-crew", "X", "--area", "sector-4", "--skills", "Wizardry"],
        ["create-crew", "X", "--area", "nowhere", "--skills", "Other"],
        ["create-crew", "X", "--area", "sector-4", "--skills", "Other", "--shift", "9"],
        ["add-crew-member", "Night Crew", "dispatcher"],
        ["add-crew-member", "No Crew", "technician"],
    ):
        with pytest.raises(SystemExit) as error:
            main(argv)
        assert error.value.code == 2, argv
    errors = capsys.readouterr().err
    for code in (
        "crew_exists",
        "invalid_skills",
        "not_found",
        "invalid_shift",
        "invalid_account",
    ):
        assert code in errors


# ------------------------------------------------------- correlated episodes and crew plans


def _scenario_ops(database):
    """Correlated episodes on compact sector-6 sites from fixture evidence, plus synthetic
    planning inputs (crew profiles, shifts, a remote desk, windows, travel)."""
    from datetime import UTC, datetime, timedelta

    from backend.clock import start_scenario
    from backend.correlation import (
        EvidenceBundle,
        Sample,
        Series,
        SiteEvidence,
        StaticEvidenceSource,
    )
    from backend.dispatch import run_correlation

    now = datetime(2026, 7, 15, 12, 30, tzinfo=UTC)
    start_scenario(database, "ops-test", now)
    slot = timedelta(minutes=15)
    frames = [now - slot * (i + 1) for i in reversed(range(6))]

    def series(source, value, prefix):
        return Series(
            source, [Sample(t, value, f"{prefix}:{i}") for i, t in enumerate(frames)]
        )

    voltage = SiteEvidence(
        "s6-01",
        pcc_asset_id="s6-01-pcc",
        capabilities={"pcc_phase_voltage": "available"},
        pcc_voltage_mean={"L1": series("pcc-meter", 255.0, "v")},
        pcc_voltage_max={"L1": series("pcc-meter", 256.0, "vmax")},
        responsibility={
            "grid_connection": ("distributor_network_review", "distributor")
        },
    )
    battery = SiteEvidence(
        "s6-02",
        battery_asset_id="s6-02-bms",
        capabilities={"battery_alarms_available": "available"},
        battery_alarms={"internal_failure": series("bms", 2.0, "alarm")},
        responsibility={
            "battery_service": ("customer_installation_service", "battery_partner")
        },
    )
    bundle = EvidenceBundle(now, {"s6-01": voltage, "s6-02": battery})
    run_correlation(database, source=StaticEvidenceSource(bundle))
    day = "2026-07-15"
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO crews(crew_id,name,area_id,skills,shift) VALUES "
            "('test-desk','Test Remote Desk','sector-6','[\"Telemetry\"]','08:00-18:00')"
        )
        connection.execute(
            "INSERT INTO crew_members SELECT 'test-desk', user_id FROM users "
            "WHERE username='technician-s5'"
        )
        for crew_id, kind, services, quals, node in (
            (
                "sector-6-solar-care",
                "field",
                ["battery_partner"],
                ["battery_storage_service", "electrical_lv"],
                "DEPOT-6",
            ),
            (
                "test-desk",
                "remote_desk",
                ["monitoring_provider"],
                ["remote_triage"],
                None,
            ),
        ):
            connection.execute(
                "INSERT INTO crew_profiles VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    crew_id,
                    kind,
                    "test-org",
                    json.dumps(services),
                    json.dumps(quals),
                    json.dumps(["battery_diagnostic_kit"]),
                    json.dumps(["sector-6"]),
                    node,
                    f"{day}T05:00:00.000000+00:00",
                    "fictional test depot",
                    "test",
                    "test",
                ),
            )
            connection.execute(
                "INSERT INTO crew_shifts VALUES (?,?,?,?)",
                (
                    crew_id,
                    f"{day}T05:00:00.000000+00:00",
                    f"{day}T15:00:00.000000+00:00",
                    "[]",
                ),
            )
        for node, site, lat, lon in (
            ("DEPOT-6", None, 44.43, 26.02),
            ("s6-01", "s6-01", 44.431, 26.03),
            ("s6-02", "s6-02", 44.432, 26.04),
        ):
            connection.execute(
                "INSERT INTO planning_nodes VALUES (?,?,?,?,'test node',1)",
                (node, site, lat, lon),
            )
        for a, b, minutes in (
            ("DEPOT-6", "s6-01", 15),
            ("DEPOT-6", "s6-02", 20),
            ("s6-01", "s6-02", 10),
        ):
            connection.execute(
                "INSERT INTO travel_times VALUES (?,?,?,'approximate demo "
                "matrix (test)','2026-07-15')",
                (a, b, minutes),
            )
        connection.execute(
            "INSERT INTO job_templates VALUES ('battery_operational_restriction',1,"
            "'field_visit',?)",
            (
                json.dumps(
                    {
                        "service_minutes": 60,
                        "qualifications": ["battery_storage_service"],
                        "tools": ["battery_diagnostic_kit"],
                        "crew_size": 1,
                    }
                ),
            ),
        )
        connection.execute(
            "INSERT INTO job_templates VALUES ('pcc_voltage_sustained',1,'external_review',?)",
            (json.dumps({"service_minutes": 45}),),
        )
        for site in ("s6-01", "s6-02"):
            connection.execute(
                "INSERT INTO site_access_windows VALUES (?,?,'test')",
                (site, json.dumps([{"start": "08:00", "end": "20:00"}])),
            )
    return now


@pytest.fixture
def scenario_ops(database):
    _scenario_ops(database)
    return database


def episode_ids(client):
    view = client.get(f"{OPS}/queue").json()
    return {
        item["episode"]["rule_id"]: item["incident"]["incident_id"]
        for item in view["items"]
        if item["episode"]
    }


def test_queue_detail_map_and_teams_share_ids_ranks_and_revisions(
    scenario_ops, client, signed_in
):
    signed_in("dispatcher")
    queue = client.get(f"{OPS}/queue").json()
    revision = queue["revision"]
    episodes = {i["incident"]["incident_id"]: i for i in queue["items"] if i["episode"]}
    assert {i["episode"]["rule_id"] for i in episodes.values()} == {
        "battery_operational_restriction",
        "pcc_voltage_sustained",
    }
    bands = [item["rank"]["band"] for item in queue["items"]]
    assert bands == sorted(bands)  # priority bands first
    battery = next(
        i
        for i in episodes.values()
        if i["episode"]["rule_id"] == "battery_operational_restriction"
    )
    assert (
        battery["rank"]["band"] == "P1"
        and battery["episode"]["confidence"] == "reported"
    )
    detail = client.get(f"{OPS}/episodes/{battery['incident']['incident_id']}").json()
    assert detail["revision"] == revision
    assert (
        detail["rank"] == battery["rank"]
    )  # identical explanation in queue and drawer
    assert detail["hypothesis"]["cannot_prove"].startswith("Does not establish")
    assert detail["evidence"] and detail["episode"]["responsibility"] == (
        "customer_installation_service"
    )
    assert "do not open equipment" in detail["customer_guidance"]
    view = client.get(f"{OPS}/map").json()
    assert view["revision"] == revision == client.get(f"{OPS}/teams").json()["revision"]
    by_site = {s["site_id"]: s for s in view["status_sites"] + view["unmapped"]}
    assert set(by_site["s6-02"]["episode_ids"]) >= {battery["incident"]["incident_id"]}
    marker = next(s for s in view["sites"] if s["site_id"] == "s6-02")
    assert marker["episode_ids"] == by_site["s6-02"]["episode_ids"]
    # Freshness is a separate dimension from the asset condition.
    assert by_site["s6-02"]["condition"] == "observed_active"
    assert by_site["s6-02"]["telemetry"]["state"] == "stale"
    assert "telemetry_stale" in by_site["s6-02"]["badges"]
    counts = view["counts"]
    assert counts["unique_episodes"] == len(
        {i["incident"]["incident_id"] for i in queue["items"]}
    )
    assert counts["affected_sites"] == sum(
        1 for s in by_site.values() if s["episode_ids"]
    )


def test_projection_is_scoped_and_lists_unmapped_sites(scenario_ops, client, signed_in):
    from backend.models import Site, SiteRegistration
    from backend.provisioning import register_site

    register_site(
        scenario_ops,
        SiteRegistration(
            site=Site(
                site_id="s6-nomap",
                alias="No coordinates",
                area_id="sector-6",
                topology_mode="simulated",
                reporting_interval_seconds=900,
                stale_after_seconds=2700,
                capabilities=["pv_power"],
                measurement_requirements={"pv_power": "mandatory"},
            ),
            device_id="d-nomap",
            source_id="test",
        ),
    )
    signed_in("dispatcher")
    unmapped = client.get(f"{OPS}/unmapped").json()
    assert [s["site_id"] for s in unmapped["sites"]] == ["s6-nomap"]
    assert unmapped["sites"][0]["position"] is None and unmapped["count"] == 1
    status = client.get(f"{OPS}/status").json()
    assert all(s["area_id"] == "sector-6" for s in status["sites"] + status["unmapped"])
    assert status["counts"]["unmapped_sites"] == 1
    signed_in("area-manager")  # supervisor of sector-6 only
    assert (
        client.get(f"{OPS}/status").json()["counts"]["sites"]
        == status["counts"]["sites"]
    )
    signed_in("technician-s3")  # another zone: none of the sector-6 episodes
    other = client.get(f"{OPS}/status").json()
    assert not {e for s in other["sites"] for e in s["episode_ids"]} & set(
        e for s in status["sites"] for e in s["episode_ids"]
    )
    signed_in("customer")
    assert client.get(f"{OPS}/status").status_code == 403
    assert client.get(f"{OPS}/queue").status_code == 403


def test_crew_plan_lifecycle_permissions_stale_and_idempotent_apply(
    scenario_ops, client, signed_in
):
    supervisor = signed_in("area-manager")
    proposal = post(client, supervisor, f"{OPS}/plans")
    assert proposal.status_code == 201  # proposing is a read/proposal operation
    plan = proposal.json()
    assert plan["status"] == "draft" and plan["label"].startswith("feasible heuristic")
    assert (
        post(client, supervisor, f"{OPS}/plans/{plan['plan_id']}/review").status_code
        == 403
    )
    denied = post(
        client,
        supervisor,
        f"{OPS}/plans/{plan['plan_id']}/apply",
        {"expected_input_digest": plan["input_digest"]},
    )
    assert (
        denied.status_code == 403
        and denied.json()["code"] == "dispatch_capability_required"
    )
    dispatcher = signed_in("dispatcher")
    [visit] = plan["visits"]
    assert visit["crew_id"] == "sector-6-solar-care" and visit["travel_minutes"] == 20
    assert "qualifications" in visit["constraints_checked"]
    reasons = {u["activity"]: u["reasons"] for u in plan["unassigned"]}
    assert "crew_not_authorised_for_responsible_service" in reasons["external_review"]
    assert any(
        "service_duration_unknown" in r for r in reasons["field_visit"]
    )  # legacy
    assert plan["comparison"]["verdict"] in (
        "heuristic_improves",
        "mixed",
        "no_improvement",
    )
    assert post(
        client,
        dispatcher,
        f"{OPS}/plans/{plan['plan_id']}/apply",
        {"expected_input_digest": plan["input_digest"]},
    ).json()["code"] == ("plan_not_reviewed")
    assert (
        post(client, dispatcher, f"{OPS}/plans/{plan['plan_id']}/review").status_code
        == 200
    )
    other = post(client, dispatcher, f"{OPS}/plans").json()
    post(client, dispatcher, f"{OPS}/plans/{other['plan_id']}/review")
    headers = {"X-CSRF-Token": dispatcher["csrf_token"], "Idempotency-Key": "apply-1"}
    body = {"expected_input_digest": plan["input_digest"]}
    applied = client.post(
        f"{OPS}/plans/{plan['plan_id']}/apply", json=body, headers=headers
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied"
    again = client.post(
        f"{OPS}/plans/{plan['plan_id']}/apply", json=body, headers=headers
    )
    assert (
        again.json()["applied_assignment_ids"]
        == applied.json()["applied_assignment_ids"]
    )
    other_key = client.post(
        f"{OPS}/plans/{plan['plan_id']}/apply",
        json=body,
        headers={**headers, "Idempotency-Key": "apply-2"},
    )
    assert (
        other_key.status_code == 409
        and other_key.json()["code"] == "plan_already_applied"
    )
    # The concurrent proposal was superseded: it can never double-book the crew.
    second = post(
        client,
        dispatcher,
        f"{OPS}/plans/{other['plan_id']}/apply",
        {"expected_input_digest": other["input_digest"]},
    )
    assert second.status_code == 409 and second.json()["code"] == "plan_superseded"
    with scenario_ops.connect() as connection:
        active = connection.execute(
            "SELECT crew_id, COUNT(*) FROM assignments WHERE status IN "
            "('assigned','team_sent','meeting_scheduled') AND plan_id IS NOT NULL "
            "GROUP BY crew_id"
        ).fetchall()
    assert [tuple(r) for r in active] == [("sector-6-solar-care", 1)]
    view = client.get(f"{OPS}/map").json()
    assert [r["state"] for r in view["routes"]] == ["applied"]
    assert "Schematic" in view["routes"][0]["label"]


def test_stale_proposal_is_rejected_and_recomputed(scenario_ops, client, signed_in):
    dispatcher = signed_in("dispatcher")
    plan = post(client, dispatcher, f"{OPS}/plans").json()
    post(client, dispatcher, f"{OPS}/plans/{plan['plan_id']}/review")
    voltage = episode_ids(client)["pcc_voltage_sustained"]
    override = post(
        client,
        dispatcher,
        f"{OPS}/episodes/{voltage}/priority-override",
        {
            "band": "P1",
            "reason": "demo: customer reports flicker",
            "expires_at": "2026-07-15T18:00:00+00:00",
        },
    )
    assert override.status_code == 200
    rank = override.json()["rank"]
    assert (rank["band"], rank["computed_band"]) == ("P1", "P2")
    stale = post(
        client,
        dispatcher,
        f"{OPS}/plans/{plan['plan_id']}/apply",
        {"expected_input_digest": plan["input_digest"]},
    )
    assert stale.status_code == 409 and stale.json()["code"] == "plan_stale"
    latest = client.get(f"{OPS}/plans/latest").json()
    assert latest["plan_id"] != plan["plan_id"] and latest["status"] == "draft"
    assert client.get(f"{OPS}/plans/{plan['plan_id']}").json()["status"] == "superseded"


def test_technician_agenda_progress_and_documented_closure(
    scenario_ops, client, signed_in
):
    dispatcher = signed_in("dispatcher")
    plan = post(client, dispatcher, f"{OPS}/plans").json()
    post(client, dispatcher, f"{OPS}/plans/{plan['plan_id']}/review")
    post(
        client,
        dispatcher,
        f"{OPS}/plans/{plan['plan_id']}/apply",
        {"expected_input_digest": plan["input_digest"]},
    )
    battery = episode_ids(client)["battery_operational_restriction"]
    outsider = signed_in("technician-s3")
    assert client.get(f"{OPS}/agenda").json()["items"] == []
    technician = signed_in("technician")
    [item] = client.get(f"{OPS}/agenda").json()["items"]
    assert item["incident_id"] == battery and item["eta_arrival"]
    path = f"{OPS}/assignments/{item['assignment_id']}/progress"
    stale = post(
        client, technician, path, {"state": "en_route", "expected_revision": 9}
    )
    assert stale.status_code == 409 and stale.json()["code"] == "assignment_changed"
    assert (
        post(
            client, technician, path, {"state": "en_route", "expected_revision": 1}
        ).status_code
        == 200
    )
    assert (
        post(
            client, technician, path, {"state": "on_site", "expected_revision": 2}
        ).status_code
        == 200
    )
    done = post(
        client,
        technician,
        path,
        {
            "state": "done",
            "expected_revision": 3,
            "outcome": "resolved",
            "note": "BMS reset by service",
        },
    )
    assert done.status_code == 200
    signed_in("dispatcher")
    detail = client.get(f"{OPS}/episodes/{battery}").json()
    assert detail["episode"]["resolution_kind"] == "authorized_closure"
    assert detail["incident"]["status"] == "resolved"
    assert [h["status"] for h in detail["assignment_history"]][-1] == "completed"
    assert outsider and post(
        client, outsider, path, {"state": "done", "expected_revision": 4}
    ).status_code in (403, 404)


def test_losing_the_feed_never_resolves_an_episode(scenario_ops, client, signed_in):
    from datetime import UTC, datetime

    from backend.clock import advance_scenario
    from backend.correlation import EvidenceBundle, StaticEvidenceSource
    from backend.dispatch import run_correlation

    advance_scenario(scenario_ops, to=datetime(2026, 7, 15, 14, 0, tzinfo=UTC))
    empty = EvidenceBundle(datetime(2026, 7, 15, 14, 0, tzinfo=UTC), {})
    result = run_correlation(scenario_ops, source=StaticEvidenceSource(empty))
    assert result["recovered"] == 0
    signed_in("dispatcher")
    assert set(episode_ids(client)) == {
        "battery_operational_restriction",
        "pcc_voltage_sustained",
    }


def test_correlated_episodes_reject_legacy_mutations_but_keep_reviewed_workflow(
    scenario_ops, client, signed_in
):
    dispatcher = signed_in("dispatcher")
    battery = episode_ids(client)["battery_operational_restriction"]
    legacy = f"{OPS}/incidents/{battery}"
    for action in ("assign", "resolve"):
        response = post(client, dispatcher, f"{legacy}/{action}")
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "episode_workflow_required"

    plan = post(client, dispatcher, f"{OPS}/plans").json()
    assert (
        post(client, dispatcher, f"{OPS}/plans/{plan['plan_id']}/review").status_code
        == 200
    )
    applied = post(
        client,
        dispatcher,
        f"{OPS}/plans/{plan['plan_id']}/apply",
        {"expected_input_digest": plan["input_digest"]},
    )
    assert applied.status_code == 200, applied.text
    technician = signed_in("technician")
    for action, body in (
        ("send-team", {}),
        (
            "meeting",
            {
                "start": "2026-07-15T13:00:00Z",
                "end": "2026-07-15T14:00:00Z",
            },
        ),
        ("resolve", {}),
    ):
        response = post(client, technician, f"{legacy}/{action}", body)
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "episode_workflow_required"
    [item] = client.get(f"{OPS}/agenda").json()["items"]
    progress = post(
        client,
        technician,
        f"{OPS}/assignments/{item['assignment_id']}/progress",
        {"state": "en_route", "expected_revision": item["revision"]},
    )
    assert progress.status_code == 200, progress.text
    closure = post(
        client,
        technician,
        f"{OPS}/episodes/{battery}/close",
        {"reason_code": "repaired", "note": "Service inspected and repaired BMS"},
    )
    assert closure.status_code == 200, closure.text
    assert closure.json()["episode"]["resolution_kind"] == "authorized_closure"


def test_legacy_auto_dispatch_excludes_correlated_work_and_keeps_compact_demo(
    scenario_ops, client, signed_in
):
    dispatcher = signed_in("dispatcher")
    episodes = set(episode_ids(client).values())
    response = post(client, dispatcher, f"{OPS}/dispatch/auto")
    assert response.status_code == 200, response.text
    result = response.json()
    assigned = {item["incident_id"] for item in result["assigned"]}
    skipped = {item["incident_id"] for item in result["skipped"]}
    assert "demo-inc-s6-09-production" in assigned
    assert assigned <= SECTOR_6
    assert not episodes.intersection(assigned | skipped)
    with scenario_ops.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM assignments WHERE incident_id IN "
                "(SELECT incident_id FROM episodes)"
            ).fetchone()[0]
            == 0
        )
