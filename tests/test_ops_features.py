"""Operations API: scope, incidents and their log, crews, assignments, revenue, video."""

import json
from pathlib import Path

import pytest

from backend.provisioning import add_crew_member, create_crew

OPS = "/api/v1/ops"
REQUESTS = "/api/v1/support/requests"
NORTH = {
    "demo-inc-north-05-production",
    "demo-inc-north-02-telemetry",
    "demo-inc-north-03-telemetry",
}
CENTRAL = {"demo-inc-central-05-area", "demo-inc-central-07-voltage"}
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
    incident = f"{OPS}/incidents/demo-inc-north-05-production"
    assert client.get(incident).status_code == 403
    for action in ("assign", "send-team", "resolve"):
        assert post(client, session, f"{incident}/{action}").status_code == 403
    assert post(client, session, f"{OPS}/dispatch/auto").status_code == 403


def test_scope_of_every_view_per_role(client, signed_in):
    signed_in("dispatcher")
    assert set(ids(client.get(f"{OPS}/incidents"))) == NORTH
    sites = client.get(f"{OPS}/map").json()["sites"]
    assert len(sites) == 8 and {site["area_id"] for site in sites} == {"north"}
    no_feed = next(site for site in sites if site["site_id"] == "north-03")
    assert (no_feed["freshness_status"], no_feed["worst_tier"]) == ("unavailable", "P3")
    assert no_feed["open_incidents"] == 1 and no_feed["zone"] == "Floreasca"
    assert [crew["name"] for crew in client.get(f"{OPS}/teams").json()["crews"]] == [
        "Solar Care"
    ]
    assert client.get(f"{OPS}/capacity").json() == {
        "areas": [
            {
                "area_id": "north",
                "alias": "Demo North",
                "sites": 8,
                "installed_kwp": 189,
            }
        ],
        "total_installed_kwp": 189,
    }
    assert client.get(f"{OPS}/revenue").json()["code"] == "supervisor_required"
    assert client.get(f"{OPS}/incidents/demo-inc-central-05-area").status_code == 404

    signed_in("supervisor")
    incidents = client.get(f"{OPS}/incidents").json()
    assert len(incidents) == 8
    order = [(item["tier"], item["created_at"]) for item in incidents]
    assert order == sorted(order) and incidents[0]["tier"] == "P0"
    assert all("Synthetic" in item["evidence"] for item in incidents)
    map_view = client.get(f"{OPS}/map").json()
    assert len(map_view["sites"]) == 24 and "SYNTHETIC" in map_view["note"]
    assert map_view["center"]["zoom"] == 12
    assert len(client.get(f"{OPS}/teams").json()["crews"]) == 3
    capacity = client.get(f"{OPS}/capacity").json()
    assert capacity["total_installed_kwp"] == sum(
        profile["installed_kwp"] for profile in PROFILES["profiles"]
    )

    signed_in("area-manager")
    assert set(ids(client.get(f"{OPS}/incidents"))) == NORTH
    assert {site["area_id"] for site in client.get(f"{OPS}/map").json()["sites"]} == {
        "north"
    }

    # A technician's zone is his crew's area, beyond his two telemetry site grants.
    signed_in("technician")
    assert set(ids(client.get(f"{OPS}/incidents"))) == NORTH
    assert client.get("/api/v1/sites/north-03").status_code == 404
    assert len(client.get(f"{OPS}/map").json()["sites"]) == 8
    assert [crew["name"] for crew in client.get(f"{OPS}/teams").json()["crews"]] == [
        "Solar Care"
    ]
    assert client.get(f"{OPS}/revenue").status_code == 403

    signed_in("technician-central")
    assert set(ids(client.get(f"{OPS}/incidents"))) == CENTRAL
    assert (
        client.get(f"{OPS}/incidents/demo-inc-north-05-production").status_code == 404
    )
    assert client.get(f"{OPS}/capacity").json()["areas"][0]["area_id"] == "central"


def test_support_requests_open_logged_incidents(client, signed_in):
    session = signed_in()
    body = {
        "site_id": "north-01",
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

    # Severity first: the danger report gets the only north crew; billing has no crew.
    result = post(client, staff, f"{OPS}/dispatch/auto").json()
    assert result["assigned"] == [
        {"incident_id": danger["incident_id"], "crew_name": "Solar Care", "tier": "P0"}
    ]
    skipped = {item["incident_id"]: item for item in result["skipped"]}
    assert skipped[billing["incident_id"]]["reason"] == "no_eligible_crew"
    assert skipped["demo-inc-north-05-production"]["reason"] == "no_available_crew"
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
    target = f"{OPS}/incidents/demo-inc-north-05-production"
    denied = post(client, manager, f"{target}/assign")
    assert denied.json()["code"] == "dispatcher_required"
    assert post(client, manager, f"{OPS}/dispatch/auto").status_code == 403

    session = signed_in("dispatcher")
    wrong = post(client, session, f"{target}/assign", {"crew_id": "grid-response"})
    assert (wrong.status_code, wrong.json()["code"]) == (422, "crew_not_eligible")
    assert (
        post(client, session, f"{target}/assign", {"crew_id": "nope"}).status_code
        == 404
    )
    assert post(client, session, f"{target}/assign", {"crew": "x"}).status_code == 422
    out_of_scope = f"{OPS}/incidents/demo-inc-central-05-area/assign"
    assert post(client, session, out_of_scope).status_code == 404
    assert client.post(f"{target}/assign", json={}).status_code == 403  # CSRF

    assigned = post(client, session, f"{target}/assign").json()
    assert assigned["status"] == "assigned"
    assert assigned["assignment"]["crew_name"] == "Solar Care"
    assert assigned["assignment"]["kind"] == "dispatch"
    again = post(client, session, f"{target}/assign")
    assert (again.status_code, again.json()["code"]) == (409, "already_assigned")
    stale = f"{OPS}/incidents/demo-inc-north-02-telemetry/assign"
    busy = post(client, session, stale, {"crew_id": "solar-care"})
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
        "demo-inc-north-02-telemetry"
    ]
    assert ids(client.get(f"{OPS}/incidents")) == [
        "demo-inc-north-02-telemetry",
        "demo-inc-north-03-telemetry",
    ]
    assert "demo-inc-north-05-production" in ids(
        client.get(f"{OPS}/incidents", params={"status": "all"})
    )


def test_technician_send_team_and_meetings(client, signed_in, database):
    customer = signed_in()
    request = post(
        client,
        customer,
        REQUESTS,
        {
            "site_id": "north-01",
            "request_type": "solar",
            "description": "Production looks low today.",
        },
    ).json()
    incident = f"{OPS}/incidents/{request['incident_id']}"
    # A second north crew lets us test conflicts between crews in one zone.
    create_crew(
        database, "Night Crew", "north", ["Production", "Telemetry"], "18:00-23:00"
    )
    add_crew_member(database, "Night Crew", "technician-central")

    session = signed_in("technician")
    assert post(client, session, f"{incident}/assign").json()["code"] == (
        "dispatcher_required"
    )
    assert post(client, session, f"{OPS}/dispatch/auto").status_code == 403
    central = f"{OPS}/incidents/demo-inc-central-07-voltage"
    assert post(client, session, f"{central}/send-team").status_code == 404
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
    no_feed = f"{OPS}/incidents/demo-inc-north-03-telemetry"
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
    production = f"{OPS}/incidents/demo-inc-north-05-production"
    sent = post(client, session, f"{production}/send-team").json()
    assert sent["status"] == "team_sent"
    assert (sent["assignment"]["kind"], sent["assignment"]["status"]) == (
        "dispatch",
        "team_sent",
    )
    stale = f"{OPS}/incidents/demo-inc-north-02-telemetry"
    busy = post(client, session, f"{stale}/send-team")
    assert (busy.status_code, busy.json()["code"]) == (409, "crew_unavailable")
    assert post(client, session, f"{production}/send-team").status_code == 409

    other = signed_in("technician-central")
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
    assert crew["name"] == "Solar Care" and crew["available"] is True
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
        "crew_name": "Solar Care",
    }


def test_teams_report_matches_for_area_and_overall_managers(client, signed_in):
    session = signed_in("dispatcher")
    first = post(client, session, f"{OPS}/dispatch/auto").json()["assigned"][0]
    post(client, session, f"{OPS}/incidents/{first['incident_id']}/resolve")
    post(client, session, f"{OPS}/dispatch/auto")

    signed_in("supervisor")
    overall = client.get(f"{OPS}/teams").json()
    solar = next(crew for crew in overall["crews"] if crew["name"] == "Solar Care")
    assert solar["report"] == {
        "assigned_total": 2,
        "completed_total": 1,
        "open_by_tier": {"P0": 0, "P1": 0, "P2": 1, "P3": 0},
        "completed_by_tier": {"P0": 0, "P1": 1, "P2": 0, "P3": 0},
    }
    assert solar["available"] is False and solar["members"] == ["technician"]
    assert solar["active_assignment"]["incident_id"] == "demo-inc-north-02-telemetry"
    assert solar["area_alias"] == "Demo North"
    assert overall["unassigned_incidents"] == 6
    report = overall["assignments"]
    assert [(row["tier"], row["status"]) for row in report] == [
        ("P2", "assigned"),
        ("P1", "completed"),
    ]
    assert report[1]["created_by"] == "dispatcher" and report[1]["completed_at"]

    signed_in("area-manager")
    north = client.get(f"{OPS}/teams").json()
    assert north["crews"] == [solar]
    assert north["assignments"] == report
    assert north["unassigned_incidents"] == 1


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
    saved = post(client, business, "/api/v1/sites/central-03/contract", contract)
    assert saved.status_code == 200

    signed_in("dispatcher")
    assert client.get(f"{OPS}/revenue").json()["code"] == "supervisor_required"

    signed_in("supervisor")
    view = client.get(f"{OPS}/revenue").json()
    assert (view["period"], view["currency"]) == ("monthly", "RON")
    assert "synthetic" in view["basis"] and "not invoices" in view["basis"]
    accounts = {item["site_id"]: item for item in view["business_accounts"]}
    # By hand: 2600 kWh x 1.2 + 160 fee - 180 kWh x 0.5 = 3190 RON.
    bistro = accounts["central-03"]
    assert (bistro["energy_sales_ron"], bistro["export_payments_ron"]) == (3120, 90)
    assert (bistro["service_fees_ron"], bistro["net_revenue_ron"]) == (160, 3190)
    assert bistro["price_source"] == "contract"
    # Default tariff 1.3 / 0.55: 14000 x 1.3 + 600 - 3000 x 0.55 = 17150 RON.
    factory = accounts["central-07"]
    assert (factory["net_revenue_ron"], factory["price_source"]) == (
        17150,
        "default_tariff",
    )
    nets = [item["net_revenue_ron"] for item in view["business_accounts"]]
    assert nets == sorted(nets, reverse=True) and len(nets) == 7

    tariff = PROFILES["default_tariff"]
    expected = {"home": 0.0, "business": 0.0}
    for profile in PROFILES["profiles"]:
        site = f"{profile['area']}-{profile['number']:02d}"
        prices = (
            (1.2, 0.5)
            if site == "central-03"
            else (tariff["import_price_ron_kwh"], tariff["export_price_ron_kwh"])
        )
        expected[profile["segment"]] += (
            profile["monthly_import_kwh"] * prices[0]
            + profile["service_fee_ron"]
            - profile["monthly_export_kwh"] * prices[1]
        )
    total = sum(expected.values())
    assert view["totals"]["sites"] == 24
    assert view["totals"]["net_revenue_ron"] == money(total)
    assert view["annualized_net_revenue_ron"] == money(total * 12)
    segments = view["by_segment"]
    assert segments["business"]["net_revenue_ron"] == money(expected["business"])
    assert segments["business"]["sites"] == 7 and segments["home"]["sites"] == 17
    assert (
        abs(segments["business"]["share_of_net"] - expected["business"] / total) < 1e-3
    )
    assert segments["business"]["share_of_net"] > 0.9
    assert [area["area_id"] for area in view["by_area"]] == [
        "central",
        "north",
        "south",
    ]
    assert sum(area["business_sites"] for area in view["by_area"]) == 7

    signed_in("area-manager")
    north = client.get(f"{OPS}/revenue").json()
    assert [area["area_id"] for area in north["by_area"]] == ["north"]
    assert north["totals"]["sites"] == 8
    assert {item["area_id"] for item in north["business_accounts"]} == {"north"}


def test_support_video_upload_and_download(client, signed_in):
    session = signed_in()
    body = {
        "site_id": "north-01",
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
            "south",
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
    assert (crew["area_id"], crew["shift"]) == ("south", "18:00-23:00")
    assert [row["user_id"] for row in members] == ["technician"]
    for argv in (
        ["create-crew", "Night Crew", "--area", "south", "--skills", "Other"],
        ["create-crew", "X", "--area", "south", "--skills", "Wizardry"],
        ["create-crew", "X", "--area", "nowhere", "--skills", "Other"],
        ["create-crew", "X", "--area", "south", "--skills", "Other", "--shift", "9"],
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
