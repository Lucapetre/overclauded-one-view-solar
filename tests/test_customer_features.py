import pytest

from backend.errors import ApiError
from backend.provisioning import create_user, set_account_type

CONTRACT = {
    "supplier": "Demo Energy",
    "pricing": "fixed",
    "import_price_ron_kwh": 1.3,
    "export_price_ron_kwh": 0.55,
    "installed_kwp": 6,
}
REQUESTS = "/api/v1/support/requests"


def post(client, session, path, body):
    return client.post(path, json=body, headers={"X-CSRF-Token": session["csrf_token"]})


def test_account_type_is_served_and_locally_managed(client, signed_in, database):
    assert signed_in()["user"]["account_type"] == "home"
    assert signed_in("business-customer")["user"]["account_type"] == "business"
    set_account_type(database, "customer", "business")
    assert signed_in()["user"]["account_type"] == "business"
    with pytest.raises(ApiError, match="customer"):
        set_account_type(database, "dispatcher", "business")
    with pytest.raises(ApiError, match="business applies"):
        create_user(database, "ops-two", "a-long-password", "dispatcher", "business")


def test_contract_is_scoped_validated_and_csrf_protected(client, signed_in):
    session = signed_in()
    path = "/api/v1/sites/north-01/contract"
    assert client.get(path).json() == {
        "site_id": "north-01",
        "contract": None,
        "updated_at": None,
    }
    assert client.post(path, json=CONTRACT).status_code == 403
    saved = post(client, session, path, CONTRACT)
    assert saved.status_code == 200
    assert saved.json()["contract"] == CONTRACT
    changed = post(client, session, path, {**CONTRACT, "import_price_ron_kwh": 1.1})
    assert changed.json()["contract"]["import_price_ron_kwh"] == 1.1
    invalid = post(client, session, path, {**CONTRACT, "import_price_ron_kwh": 0})
    assert invalid.status_code == 422
    other = "/api/v1/sites/south-01/contract"
    assert client.get(other).status_code == 404
    assert post(client, session, other, CONTRACT).status_code == 404
    staff = signed_in("technician")
    assert client.get(path).json()["contract"]["supplier"] == "Demo Energy"
    assert post(client, staff, path, CONTRACT).status_code == 403


def test_support_request_conversation_and_scope(client, signed_in):
    session = signed_in()
    kinds = client.get("/api/v1/support/request-types").json()
    assert len(kinds) >= 12 and kinds[-1]["id"] == "other"
    teams = {kind["id"]: kind["routed_to"] for kind in kinds}
    assert teams["billing"] == teams["meter"] == "Dispatch desk"
    assert "Supplier support" not in teams.values()
    body = {
        "site_id": "north-01",
        "request_type": "battery",
        "description": "The battery has not charged since yesterday.",
    }
    assert client.post(REQUESTS, json=body).status_code == 403
    created = post(client, session, REQUESTS, body)
    assert created.status_code == 201, created.text
    request = created.json()
    assert (request["priority"], request["routed_to"], request["status"]) == (
        "standard",
        "Solar maintenance",
        "awaiting_review",
    )
    # Every request opens a linked operations incident; no meeting or video yet.
    assert request["incident_id"] and request["meeting"] is None
    assert request["media"] is None
    danger = post(client, session, REQUESTS, {**body, "immediate_danger": True}).json()
    assert (danger["priority"], danger["routed_to"]) == ("immediate_danger", "Triage")
    for wrong in (
        {**body, "site_id": "south-01"},
        {**body, "request_type": "nope"},
        {**body, "description": "   "},
        {**body, "urgent": True},
    ):
        assert post(client, session, REQUESTS, wrong).status_code in (404, 422)
    replies = f"{REQUESTS}/{request['request_id']}/replies"

    other = signed_in("other-customer")
    assert client.get(REQUESTS).json() == []
    assert post(client, other, replies, {"text": "hello"}).status_code == 404

    # The supervisor's areas include north; south-only staff would not see it.
    staff = signed_in("technician")
    assert len(client.get(REQUESTS).json()) == 2
    assert post(client, staff, REQUESTS, body).status_code == 403
    answered = post(client, staff, replies, {"text": "We will check the logs."}).json()
    assert answered["status"] == "answered"
    assert answered["replies"][0]["kind"] == "staff"

    session = signed_in()
    followed = post(client, session, replies, {"text": "Thank you."}).json()
    assert followed["status"] == "awaiting_review"
    assert [reply["kind"] for reply in followed["replies"]] == ["staff", "customer"]
    assert {item["request_id"] for item in client.get(REQUESTS).json()} == {
        request["request_id"],
        danger["request_id"],
    }

    # A business customer on another site has no view of this conversation.
    signed_in("business-customer")
    assert client.get(REQUESTS).json() == []


def test_lessons_hide_answers_and_reward_once(client, signed_in):
    session = signed_in()
    catalog = client.get("/api/v1/lessons").json()
    assert len(catalog["lessons"]) == 4 and catalog["total_reward_ron"] == 0
    assert "answer" not in str(catalog["lessons"][0]["questions"])
    assert "not money" in catalog["reward_note"]
    path = "/api/v1/lessons/follow-the-energy/complete"
    assert client.post(path, json={"answers": [1, 0]}).status_code == 403
    wrong = post(client, session, path, {"answers": [0, 0]}).json()
    assert (wrong["passed"], wrong["correct"], wrong["reward_ron"]) == (False, 1, 0)
    assert post(client, session, path, {"answers": [1]}).status_code == 422
    right = post(client, session, path, {"answers": [1, 0]}).json()
    assert (right["passed"], right["reward_ron"], right["total_reward_ron"]) == (
        True,
        2,
        2,
    )
    again = post(client, session, path, {"answers": [1, 0]}).json()
    assert (again["reward_ron"], again["already_completed"]) == (0, True)
    assert again["total_reward_ron"] == 2
    missing = post(client, session, "/api/v1/lessons/nope/complete", {"answers": []})
    assert missing.status_code == 404
    catalog = client.get("/api/v1/lessons").json()
    assert catalog["lessons"][0]["completed"] and catalog["total_reward_ron"] == 2
    signed_in("other-customer")
    assert client.get("/api/v1/lessons").json()["total_reward_ron"] == 0
