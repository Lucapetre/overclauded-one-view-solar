"""Customer features: supply contract, support requests and rewarded lessons.

Every read and write resolves the caller's site scope on the server.
"""

import json
import uuid
from datetime import UTC
from functools import lru_cache
from pathlib import Path

from backend import tariff
from backend.clock import analytical_now
from backend.customer_models import (
    Contract,
    ContractVersionView,
    ContractView,
    Lesson,
    LessonCatalog,
    LessonResult,
    RequestType,
    SupportMedia,
    SupportMeeting,
    SupportReply,
    SupportRequest,
    SupportRequestCreate,
    TariffBand,
)
from backend.db import stamp
from backend.errors import ApiError
from backend.models import User
from backend.ops import log_incident, open_incident, request_meeting
from backend.security import accessible_sites, authorized_site

REQUEST_TYPES = [
    RequestType(id=key, label=label, routed_to=team)
    for key, label, team in (
        ("solar", "Solar production looks low", "Solar maintenance"),
        (
            "device-warning",
            "Inverter warning, error code or overheating",
            "Solar maintenance",
        ),
        ("inverter-offline", "Inverter is off or not starting", "Solar maintenance"),
        ("battery", "Battery or storage issue", "Solar maintenance"),
        ("panel-damage", "Panel damage, dirt or shading", "Solar maintenance"),
        ("monitoring", "App data missing or not updating", "Monitoring support"),
        ("grid", "Grid connection or voltage", "Grid response"),
        ("outage", "Power cut or frequent disconnections", "Grid response"),
        ("electrical", "Electrical issue inside the building", "Field service"),
        ("meter", "Meter reading or prosumer settlement", "Dispatch desk"),
        ("billing", "Billing or contract question", "Dispatch desk"),
        ("upgrade", "Extend the system (panels, battery, EV charger)", "Sales advice"),
        ("other", "Other or not sure", "Triage"),
    )
]
_TYPES = {item.id: item for item in REQUEST_TYPES}
# Incident family opened for each request type; Billing has no crew and stays with dispatch.
REQUEST_FAMILIES = {
    "solar": "Production",
    "device-warning": "Temperature",
    "inverter-offline": "Production",
    "battery": "Local issue",
    "panel-damage": "Local issue",
    "monitoring": "Telemetry",
    "grid": "Voltage",
    "outage": "Area event",
    "electrical": "Local issue",
    "meter": "Billing",
    "billing": "Billing",
    "upgrade": "Other",
    "other": "Other",
}
MAX_OPEN_REQUESTS = 50


def require_customer(user: User):
    if user.role != "customer":
        raise ApiError(403, "customer_required", "A customer account is required")


def _band_model(band: tariff.Band) -> TariffBand:
    return TariffBand(
        band_id=band.band_id,
        label=band.label,
        days=list(band.days),
        start_minute=band.start_minute,
        end_minute=band.end_minute,
        import_rate_ron_kwh=band.import_rate,
        export_value_ron_kwh=band.export_value,
        valid_from=band.valid_from,
        valid_to=band.valid_to,
    )


def _uncovered(bands) -> int:
    covered = set()
    for band in bands:
        covered |= tariff._week_minutes(band)
    return 7 * 1440 - len(covered)


def _contract_fields(row, stored) -> dict:
    fields = {
        key: row[key]
        for key in (
            "supplier",
            "pricing",
            "import_price_ron_kwh",
            "export_price_ron_kwh",
            "installed_kwp",
        )
    }
    if row["export_compensation"] != "unspecified":
        fields["export_compensation"] = row["export_compensation"]
    if stored and row["pricing"] == "time_of_use":
        fields["bands"] = [_band_model(band) for band in stored.bands]
    return fields


def get_contract(connection, user: User, site_id: str) -> ContractView:
    authorized_site(connection, user, site_id)
    row = connection.execute(
        "SELECT * FROM contracts WHERE site_id=?", (site_id,)
    ).fetchone()
    if not row:
        return ContractView(site_id=site_id, contract=None, updated_at=None)
    versions = tariff.load_versions(connection, site_id)
    version = tariff.current_version(versions, analytical_now(connection))
    if version is None and versions:
        # A version scheduled to start later is still the one the customer just saved.
        version = max(versions, key=lambda v: (v.effective_from, v.version_no))
    stored = next(
        (v for v in versions if v.version_id == row["current_version_id"]), version
    )
    return ContractView(
        site_id=site_id,
        # Only stated fields are set, so a fixed contract keeps its original response shape
        # (the routes serialize with exclude_unset).
        contract=Contract(**_contract_fields(row, stored)),
        updated_at=row["updated_at"],
        version=ContractVersionView(
            version_id=version.version_id,
            version_no=version.version_no,
            pricing=version.pricing,
            timezone=tariff.TIMEZONE,
            export_compensation=version.export_compensation,
            effective_from=version.effective_from,
            valid_to=version.valid_to,
            bands=[_band_model(band) for band in version.bands],
            uncovered_week_minutes=_uncovered(version.bands),
        )
        if version
        else None,
        version_count=len(versions),
    )


def contract_bands(contract: Contract) -> list[tariff.Band]:
    if contract.pricing == "fixed":
        return [
            tariff.all_day(contract.import_price_ron_kwh, contract.export_price_ron_kwh)
        ]
    return [
        tariff.Band(
            band_id=band.band_id,
            days=tuple(sorted(set(band.days))),
            start_minute=band.start_minute,
            end_minute=band.end_minute,
            import_rate=band.import_rate_ron_kwh,
            export_value=band.export_value_ron_kwh,
            label=band.label,
            valid_from=band.valid_from,
            valid_to=band.valid_to,
        )
        for band in contract.bands or []
    ]


def store_contract(
    connection,
    site_id: str,
    contract: Contract,
    user_id: str,
    now,
    effective_from=None,
) -> str:
    """Write the reference contract row and a new immutable version; returns its id."""
    bands = contract_bands(contract)
    errors = tariff.validate_bands(bands)
    if errors:
        raise ApiError(422, "invalid_tariff_bands", "; ".join(errors[:5]))
    effective = effective_from or contract.effective_from or now
    effective = effective.astimezone(UTC)
    if effective_from is None and contract.effective_from and effective < now:
        raise ApiError(
            422,
            "retroactive_tariff",
            "A contract version cannot start before the current time",
        )
    version_id = tariff.insert_version(
        connection,
        site_id,
        supplier=contract.supplier.strip(),
        pricing=contract.pricing,
        export_compensation=contract.export_compensation,
        bands=bands,
        effective_from=effective,
        valid_to=None,
        created_by=user_id,
        created_as_of=now,
    )
    connection.execute(
        "INSERT INTO contracts(site_id,supplier,pricing,import_price_ron_kwh,"
        "export_price_ron_kwh,installed_kwp,updated_by,updated_at,export_compensation,"
        "current_version_id) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(site_id) DO UPDATE SET "
        "supplier=excluded.supplier, pricing=excluded.pricing, "
        "import_price_ron_kwh=excluded.import_price_ron_kwh, "
        "export_price_ron_kwh=excluded.export_price_ron_kwh, "
        "installed_kwp=excluded.installed_kwp, updated_by=excluded.updated_by, "
        "updated_at=excluded.updated_at, export_compensation=excluded.export_compensation, "
        "current_version_id=excluded.current_version_id",
        (
            site_id,
            contract.supplier.strip(),
            contract.pricing,
            contract.import_price_ron_kwh,
            contract.export_price_ron_kwh,
            contract.installed_kwp,
            user_id,
            stamp(),
            contract.export_compensation,
            version_id,
        ),
    )
    return version_id


def save_contract(
    database, connection, user: User, site_id: str, contract: Contract, request_id: str
) -> ContractView:
    require_customer(user)
    authorized_site(connection, user, site_id)
    connection.execute("BEGIN IMMEDIATE")
    now = analytical_now(connection)
    version_id = store_contract(connection, site_id, contract, user.user_id, now)
    database.audit(
        connection,
        user.user_id,
        "contract.saved",
        site_id,
        request_id,
        {"version_id": version_id, "analytical_at": stamp(now)},
    )
    return get_contract(connection, user, site_id)


def _requests(connection, user: User, where: str, parameters: tuple):
    rows = connection.execute(
        "SELECT r.*, s.alias AS site_alias, u.username AS requested_by, "
        "i.incident_id, m.media_id, m.filename AS media_filename, "
        "m.content_type AS media_content_type, m.size_bytes AS media_size_bytes "
        "FROM support_requests r JOIN sites s ON s.site_id=r.site_id "
        "JOIN users u ON u.user_id=r.user_id "
        "LEFT JOIN incidents i ON i.support_request_id=r.request_id "
        "LEFT JOIN support_media m ON m.request_id=r.request_id WHERE "
        + where
        + " ORDER BY r.created_at DESC LIMIT 200",
        parameters,
    ).fetchall()
    result = []
    for row in rows:
        replies = connection.execute(
            "SELECT p.kind,p.text,p.created_at,u.username AS author FROM support_replies p "
            "JOIN users u ON u.user_id=p.author_id WHERE p.request_id=? ORDER BY p.id",
            (row["request_id"],),
        ).fetchall()
        kind = _TYPES.get(row["request_type"])
        meeting = (
            request_meeting(connection, row["incident_id"])
            if row["incident_id"]
            else None
        )
        result.append(
            SupportRequest(
                **{
                    key: row[key]
                    for key in (
                        "request_id",
                        "site_id",
                        "site_alias",
                        "requested_by",
                        "request_type",
                        "priority",
                        "routed_to",
                        "description",
                        "status",
                        "created_at",
                        "updated_at",
                    )
                },
                request_label=kind.label if kind else row["request_type"],
                replies=[SupportReply(**dict(reply)) for reply in replies],
                incident_id=row["incident_id"],
                meeting=SupportMeeting(**dict(meeting)) if meeting else None,
                media=SupportMedia(
                    media_id=row["media_id"],
                    filename=row["media_filename"],
                    content_type=row["media_content_type"],
                    size_bytes=row["media_size_bytes"],
                )
                if row["media_id"]
                else None,
            )
        )
    return result


# A technician has no request inbox: a request (and its video) is visible only through an
# assignment the dispatcher created on its incident for one of the technician's crews.
LINKED_TO_CREW_MEMBER = (
    "EXISTS (SELECT 1 FROM incidents li JOIN assignments la ON la.incident_id=li.incident_id "
    "JOIN crew_members lm ON lm.crew_id=la.crew_id WHERE li.support_request_id=r.request_id "
    "AND lm.user_id=? AND la.status != 'cancelled')"
)


def list_requests(connection, user: User) -> list[SupportRequest]:
    if user.role == "customer":
        return _requests(connection, user, "r.user_id=?", (user.user_id,))
    if user.role == "technician":
        return _requests(connection, user, LINKED_TO_CREW_MEMBER, (user.user_id,))
    sites = [row["site_id"] for row in accessible_sites(connection, user)]
    if not sites:
        return []
    marks = ",".join("?" * len(sites))
    return _requests(connection, user, f"r.site_id IN ({marks})", tuple(sites))


def _visible_request(connection, user: User, request_id: str):
    row = connection.execute(
        "SELECT * FROM support_requests WHERE request_id=?", (request_id,)
    ).fetchone()
    if row and user.role == "customer" and row["user_id"] == user.user_id:
        return row
    if row and user.role == "technician":
        linked = connection.execute(
            "SELECT 1 FROM support_requests r WHERE r.request_id=? AND "
            + LINKED_TO_CREW_MEMBER,
            (request_id, user.user_id),
        ).fetchone()
        if linked:
            return row
    elif row and user.role != "customer":
        authorized_site(connection, user, row["site_id"])
        return row
    raise ApiError(404, "not_found", "Resource not found")


def create_request(
    database, connection, user: User, payload: SupportRequestCreate, request_id: str
) -> SupportRequest:
    require_customer(user)
    authorized_site(connection, user, payload.site_id)
    kind = _TYPES.get(payload.request_type)
    if not kind:
        raise ApiError(422, "unknown_request_type", "Choose a listed request type")
    description = payload.description.strip()
    if not description:
        raise ApiError(422, "invalid_request", "Describe what you have noticed")
    waiting = connection.execute(
        "SELECT COUNT(*) FROM support_requests WHERE user_id=? AND status='awaiting_review'",
        (user.user_id,),
    ).fetchone()[0]
    if waiting >= MAX_OPEN_REQUESTS:
        raise ApiError(
            429, "too_many_requests", "Too many requests are already awaiting review"
        )
    identifier = uuid.uuid4().hex
    now = stamp()
    connection.execute(
        "INSERT INTO support_requests(request_id,site_id,user_id,request_type,priority,"
        "routed_to,description,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            identifier,
            payload.site_id,
            user.user_id,
            kind.id,
            "immediate_danger" if payload.immediate_danger else "standard",
            # Danger reports are never routed by the customer's guess.
            "Triage" if payload.immediate_danger else kind.routed_to,
            description,
            "awaiting_review",
            now,
            now,
        ),
    )
    danger = payload.immediate_danger
    incident = open_incident(
        connection,
        site_id=payload.site_id,
        title=f"Customer request: {kind.label}",
        family=REQUEST_FAMILIES.get(kind.id, "Other"),
        tier="P0" if danger else "P2",
        source="customer_request",
        evidence=description,
        actor=user.username,
        detail=f"Opened from {'an immediate danger' if danger else 'a standard'} "
        f"support request by {user.username}",
        support_request_id=identifier,
        now=now,
    )
    database.audit(
        connection, user.user_id, "support.request.created", identifier, request_id
    )
    database.audit(connection, user.user_id, "incident.opened", incident, request_id)
    return _requests(connection, user, "r.request_id=?", (identifier,))[0]


def add_reply(
    database, connection, user: User, identifier: str, text: str, request_id: str
) -> SupportRequest:
    row = _visible_request(connection, user, identifier)
    text = text.strip()
    if not text:
        raise ApiError(422, "invalid_request", "Write a reply")
    replies = connection.execute(
        "SELECT COUNT(*) FROM support_replies WHERE request_id=?", (identifier,)
    ).fetchone()[0]
    if replies >= 200:
        raise ApiError(409, "conversation_full", "Open a new request to continue")
    kind = "customer" if user.role == "customer" else "staff"
    now = stamp()
    connection.execute(
        "INSERT INTO support_replies(request_id,author_id,kind,text,created_at) VALUES (?,?,?,?,?)",
        (identifier, user.user_id, kind, text, now),
    )
    connection.execute(
        "UPDATE support_requests SET status=?, updated_at=? WHERE request_id=?",
        ("awaiting_review" if kind == "customer" else "answered", now, identifier),
    )
    incident = connection.execute(
        "SELECT incident_id FROM incidents WHERE support_request_id=?", (identifier,)
    ).fetchone()
    if incident:
        log_incident(
            connection,
            incident["incident_id"],
            user.username,
            "customer_follow_up" if kind == "customer" else "staff_reply",
            f"{'Customer follow-up' if kind == 'customer' else 'Staff reply'} "
            f"by {user.username}: {text[:300]}",
            now,
        )
        connection.execute(
            "UPDATE incidents SET updated_at=? WHERE incident_id=?",
            (now, incident["incident_id"]),
        )
    database.audit(
        connection, user.user_id, f"support.reply.{kind}", identifier, request_id
    )
    return _requests(connection, user, "r.request_id=?", (row["request_id"],))[0]


@lru_cache
def _lesson_source() -> dict:
    return json.loads(
        (Path(__file__).parent / "fixtures" / "lessons.json").read_text(
            encoding="utf-8"
        )
    )


def _completed(connection, user: User) -> dict[str, float]:
    return {
        row["lesson_id"]: row["reward_ron"]
        for row in connection.execute(
            "SELECT lesson_id,reward_ron FROM lesson_completions WHERE user_id=?",
            (user.user_id,),
        )
    }


def lesson_catalog(connection, user: User) -> LessonCatalog:
    source = _lesson_source()
    done = _completed(connection, user)
    return LessonCatalog(
        lessons=[
            Lesson(
                **{
                    key: item[key]
                    for key in (
                        "id",
                        "title",
                        "summary",
                        "minutes",
                        "reward_ron",
                        "steps",
                        "example",
                    )
                },
                # The answer key never leaves the server.
                questions=[
                    {"text": question["text"], "options": question["options"]}
                    for question in item["questions"]
                ],
                completed=item["id"] in done,
            )
            for item in source["lessons"]
        ],
        total_reward_ron=round(sum(done.values()), 2),
        reward_note=source["reward_note"],
    )


def complete_lesson(
    database,
    connection,
    user: User,
    lesson_id: str,
    answers: list[int],
    request_id: str,
) -> LessonResult:
    lesson = next(
        (item for item in _lesson_source()["lessons"] if item["id"] == lesson_id), None
    )
    if not lesson:
        raise ApiError(404, "not_found", "Resource not found")
    key = [question["answer"] for question in lesson["questions"]]
    if len(answers) != len(key):
        raise ApiError(422, "invalid_request", "Answer every question")
    correct = sum(
        1 for given, expected in zip(answers, key, strict=True) if given == expected
    )
    passed = correct == len(key)
    connection.execute("BEGIN IMMEDIATE")
    done = _completed(connection, user)
    already = lesson_id in done
    reward = 0.0
    if passed and not already:
        reward = float(lesson["reward_ron"])
        connection.execute(
            "INSERT INTO lesson_completions VALUES (?,?,?,?)",
            (user.user_id, lesson_id, reward, stamp()),
        )
        database.audit(
            connection, user.user_id, "lesson.completed", lesson_id, request_id
        )
        done[lesson_id] = reward
    return LessonResult(
        lesson_id=lesson_id,
        passed=passed,
        correct=correct,
        total=len(key),
        reward_ron=reward,
        already_completed=already,
        total_reward_ron=round(sum(done.values()), 2),
    )
