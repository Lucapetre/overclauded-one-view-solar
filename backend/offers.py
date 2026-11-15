"""Power Block Offers: manager offer management, client acceptance, attribution, settlement
and in-app notifications.

Scope is resolved on the server for every call: managers (supervisors) only see offers and
clients in their `user_areas`; clients only see offers targeted at one of their sites.
Objects outside scope are 404. All times are UTC; money is integer bani.
"""

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from backend.bridge import offer_meter_intervals
from backend.clock import clock_state
from backend.customer import require_customer
from backend.db import stamp
from backend.errors import ApiError
from backend.models import Metric, User, utc
from backend.offers_math import (
    Allocation,
    Commitment,
    attribute,
    bani,
    decimal_text,
    penalty_ron,
    penalty_rule_text,
    price_text,
    ron_text,
    settle,
    terms_text,
    window_text,
)
from backend.offers_models import (
    AuditEntry,
    ClientOffer,
    ClientSite,
    EligibleSite,
    ManagerClient,
    ManagerOffer,
    ManagerOfferDetail,
    Notification,
    NotificationList,
    OfferDraft,
    OfferPreview,
    OfferStats,
    OfferTaker,
    PreviewSummary,
    RemainingCapacity,
    SavingsSummary,
    SettlementSummary,
    SettlementView,
    UserOffer,
)
from backend.ops import profile_source

RUNNING = ("accepted", "active")
RUNNING_SQL = "('accepted','active')"
BUCHAREST = ZoneInfo("Europe/Bucharest")
METRICS = {"consume": Metric.grid_import, "export": Metric.grid_export}
WORKER = "offers-worker"
NOT_FOUND = ("not_found", "Resource not found")
OFFER_COLUMNS = (
    "type",
    "title",
    "energy_kwh",
    "offer_price_ron_per_kwh",
    "window_minutes",
    "penalty_type",
    "penalty_value",
    "offer_expires_at",
    "area_id",
    "target_mode",
    "target_segment",
    "target_min_kwp",
    "target_zone",
    "linked_incident_id",
    "max_takers",
    "max_total_kwh",
)
SETTLEMENT_COLUMNS = (
    "metered_kwh",
    "fulfilled_kwh",
    "unfulfilled_kwh",
    "excess_kwh",
    "coverage_ratio",
    "penalty_before_waiver_bani",
    "penalty_bani",
    "penalty_waived_reason",
    "energy_value_bani",
    "amount_bani",
    "direction",
    "savings_bani",
    "settled_at",
)
PENALTY_LIMITS = {
    "per_unfulfilled_kwh": (4, Decimal(10), "RON per kWh"),
    "percent_of_unfulfilled_value": (2, Decimal(100), "percent"),
    "flat": (2, Decimal(1000), "RON"),
}


def when(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def effective_end(row) -> datetime:
    """A distributor cancellation closes the window early."""
    end = when(row["window_end"])
    cancelled = when(row["cancelled_at"])
    return min(end, cancelled) if cancelled else end


def effective_status(row, now: datetime) -> str:
    if row["status"] == "available" and when(row["offer_expires_at"]) <= now:
        return "expired"
    return row["status"]


# ---------------------------------------------------------------- notifications


def notify(connection, user_id: str, kind: str, title: str, body: str, link, now):
    connection.execute(
        "INSERT INTO notifications(notification_id,user_id,kind,title,body,link,created_at,"
        "read_at) VALUES (?,?,?,?,?,?,?,NULL)",
        (uuid.uuid4().hex, user_id, kind, title, body, link, stamp(now)),
    )


def list_notifications(connection, user: User, unread: bool) -> NotificationList:
    rows = connection.execute(
        "SELECT * FROM notifications WHERE user_id=?"
        + (" AND read_at IS NULL" if unread else "")
        + " ORDER BY created_at DESC, notification_id LIMIT 50",
        (user.user_id,),
    ).fetchall()
    count = connection.execute(
        "SELECT COUNT(*) FROM notifications WHERE user_id=? AND read_at IS NULL",
        (user.user_id,),
    ).fetchone()[0]
    return NotificationList(
        unread_count=count,
        notifications=[
            Notification(
                **{key: row[key] for key in Notification.model_fields},
            )
            for row in rows
        ],
    )


def mark_read(connection, user: User, notification_id: str, now) -> NotificationList:
    row = connection.execute(
        "SELECT read_at FROM notifications WHERE notification_id=? AND user_id=?",
        (notification_id, user.user_id),
    ).fetchone()
    if not row:
        raise ApiError(404, *NOT_FOUND)
    connection.execute(
        "UPDATE notifications SET read_at=? WHERE notification_id=? AND read_at IS NULL",
        (stamp(now), notification_id),
    )
    return list_notifications(connection, user, False)


def mark_all_read(connection, user: User, now) -> NotificationList:
    connection.execute(
        "UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL",
        (stamp(now), user.user_id),
    )
    return list_notifications(connection, user, False)


# ---------------------------------------------------------------- terms and audience


def _texts(offer) -> tuple[str, str, int, int]:
    """(penalty rule, full terms, max penalty bani, block value bani) for stored terms."""
    energy = Decimal(offer["energy_kwh"])
    price = Decimal(offer["offer_price_ron_per_kwh"])
    value = Decimal(offer["penalty_value"])
    arguments = (
        offer["type"],
        energy,
        offer["window_minutes"],
        offer["penalty_type"],
        value,
        price,
    )
    return (
        penalty_rule_text(*arguments),
        terms_text(*arguments),
        bani(penalty_ron(offer["penalty_type"], value, energy, price)),
        bani(energy * price),
    )


def _kwp(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _site_info(row) -> dict:
    capabilities = json.loads(row["capabilities"])
    kwp = _kwp(row["installed_kwp"])
    has_pv = Metric.pv.value in capabilities and (kwp is None or kwp > 0)
    return {
        "user_id": row["user_id"],
        "username": row["username"],
        "site_id": row["site_id"],
        "alias": row["alias"],
        "area_id": row["area_id"],
        "zone": row["zone"],
        "installed_kwp": kwp,
        "has_pv": has_pv,
        "segment": "prosumers" if has_pv else "consumers",
        # An imported authoritative PCC meter (component evidence) measures both directions.
        "export_capable": Metric.grid_export.value in capabilities
        or bool(row["component_meter"]),
        "import_capable": Metric.grid_import.value in capabilities
        or bool(row["component_meter"]),
        "has_meter": bool(row["has_meter"]),
    }


CLIENT_SITES = (
    "SELECT u.user_id, u.username, s.site_id, s.alias, s.area_id, s.capabilities, "
    "p.zone, p.installed_kwp, "
    "EXISTS (SELECT 1 FROM energy_streams e WHERE e.site_id=s.site_id) AS has_meter, "
    "EXISTS (SELECT 1 FROM component_sites cs JOIN component_capabilities cc "
    "ON cc.import_id=cs.import_id AND cc.site_id=cs.site_id WHERE cs.site_id=s.site_id "
    "AND cc.capability='grid_energy_measured' AND cc.state='available') AS component_meter "
    "FROM users u JOIN user_sites us ON us.user_id=u.user_id "
    "JOIN sites s ON s.site_id=us.site_id LEFT JOIN site_profiles p ON p.site_id=s.site_id "
    "WHERE u.role='customer' "
)


def audience(connection, offer: dict, user_id: str | None = None) -> list[dict]:
    """(client, site) pairs in the offer's area that match its targeting."""
    rows = connection.execute(
        CLIENT_SITES
        + "AND s.area_id=?"
        + (" AND u.user_id=?" if user_id else "")
        + " ORDER BY u.username, s.site_id",
        (offer["area_id"], *((user_id,) if user_id else ())),
    ).fetchall()
    mode = offer["target_mode"]
    targets = set(offer.get("target_user_ids") or ())
    minimum = offer.get("target_min_kwp")
    minimum = Decimal(minimum) if minimum else None
    result = []
    for row in rows:
        site = _site_info(row)
        if mode == "clients" and site["user_id"] not in targets:
            continue
        if mode == "segment" and site["segment"] != offer["target_segment"]:
            continue
        if minimum is not None and (
            site["installed_kwp"] is None or site["installed_kwp"] < minimum
        ):
            continue
        if offer.get("target_zone") and site["zone"] != offer["target_zone"]:
            continue
        result.append(site)
    return result


def reference_price(connection, site_id: str, offer_type: str) -> tuple[Decimal, str]:
    key = "import_price_ron_kwh" if offer_type == "consume" else "export_price_ron_kwh"
    row = connection.execute(
        f"SELECT {key} FROM contracts WHERE site_id=?", (site_id,)
    ).fetchone()
    if row:
        return Decimal(str(row[key])), "contract"
    return Decimal(str(profile_source()["default_tariff"][key])), "default_tariff"


def _gain(offer_type: str, energy: Decimal, price: Decimal, reference: Decimal):
    """Savings (consume) or extra earnings (export) versus the reference, per block."""
    if offer_type == "consume":
        return energy * (reference - price)
    return energy * (price - reference)


# ---------------------------------------------------------------- manager scope and validation


def require_manager(user: User):
    if user.role != "supervisor":
        raise ApiError(
            403,
            "manager_required",
            "A distributor manager (supervisor) account is required",
        )


def manager_areas(connection, user: User) -> list[str]:
    require_manager(user)
    return [
        row["area_id"]
        for row in connection.execute(
            "SELECT area_id FROM user_areas WHERE user_id=? ORDER BY area_id",
            (user.user_id,),
        )
    ]


def _number(text, label, places, high, errors, *, positive=False, unit=""):
    if text is None:
        return None
    value = Decimal(text)
    exponent = value.normalize().as_tuple().exponent
    if -exponent > places:
        errors.append(f"{label} allows at most {places} decimals")
        return None
    if value > high or value < 0 or (positive and value == 0):
        low = "greater than 0" if positive else "at least 0"
        errors.append(f"{label} must be {low} and at most {decimal_text(high)}{unit}")
        return None
    return value


def normalize_draft(
    connection, draft: OfferDraft, areas: list[str]
) -> tuple[dict, list[str]]:
    """Validated, stored representation of a draft and the list of term errors.

    Scope violations raise immediately; term problems are returned so previews can show them.
    """
    errors: list[str] = []
    if draft.area_id not in areas:
        raise ApiError(
            422, "area_out_of_scope", "The offer's area is not one of your areas"
        )
    energy = _number(
        draft.energy_kwh, "energy_kwh", 3, Decimal(10000), errors, positive=True
    )
    price = _number(
        draft.offer_price_ron_per_kwh, "offer_price_ron_per_kwh", 4, Decimal(10), errors
    )
    places, high, unit = PENALTY_LIMITS[draft.penalty_type]
    penalty = _number(
        draft.penalty_value, "penalty_value", places, high, errors, unit=f" {unit}"
    )
    if not 15 <= draft.window_minutes <= 1440:
        errors.append("window_minutes must be between 15 and 1440")
    minimum = _number(draft.target_min_kwp, "target_min_kwp", 3, Decimal(1000), errors)
    total = _number(
        draft.max_total_kwh, "max_total_kwh", 3, Decimal(1000000), errors, positive=True
    )
    if total is not None and energy is not None and total < energy:
        errors.append("max_total_kwh must be at least energy_kwh")
    if (draft.target_mode == "segment") != (draft.target_segment is not None):
        errors.append("target_segment is required for, and only allowed with, segment")
    targets = list(dict.fromkeys(draft.target_user_ids))
    if (draft.target_mode == "clients") != bool(targets):
        errors.append("target_user_ids is required for, and only allowed with, clients")
    try:
        expires = stamp(utc(draft.offer_expires_at))
    except ValueError:
        expires = None
        errors.append("offer_expires_at must include a timezone")
    if targets:
        marks = ",".join("?" * len(targets))
        allowed = {
            row["user_id"]
            for row in connection.execute(
                CLIENT_SITES + f"AND s.area_id=? AND u.user_id IN ({marks})",
                (draft.area_id, *targets),
            )
        }
        if set(targets) - allowed:
            raise ApiError(
                422,
                "client_out_of_scope",
                "Every hand-picked client must have a site in the offer's area",
            )
    if draft.linked_incident_id:
        incident = connection.execute(
            "SELECT s.area_id, p.zone FROM incidents i JOIN sites s ON s.site_id=i.site_id "
            "LEFT JOIN site_profiles p ON p.site_id=i.site_id WHERE i.incident_id=?",
            (draft.linked_incident_id,),
        ).fetchone()
        if not incident or incident["area_id"] != draft.area_id:
            raise ApiError(
                422,
                "incident_out_of_scope",
                "The linked incident must be in the offer's area",
            )
        if draft.target_zone and draft.target_zone != incident["zone"]:
            errors.append("target_zone must be the linked incident site's zone")
    elif draft.target_zone:
        errors.append("target_zone requires linked_incident_id")
    title = (draft.title or "").strip() or None

    def text(value, raw):
        return decimal_text(value) if value is not None else raw

    return {
        "type": draft.type,
        "title": title,
        "energy_kwh": text(energy, draft.energy_kwh),
        "offer_price_ron_per_kwh": text(price, draft.offer_price_ron_per_kwh),
        "window_minutes": draft.window_minutes,
        "penalty_type": draft.penalty_type,
        "penalty_value": text(penalty, draft.penalty_value),
        "offer_expires_at": expires,
        "area_id": draft.area_id,
        "target_mode": draft.target_mode,
        "target_segment": draft.target_segment,
        "target_min_kwp": text(minimum, draft.target_min_kwp),
        "target_zone": draft.target_zone,
        "linked_incident_id": draft.linked_incident_id,
        "max_takers": draft.max_takers,
        "max_total_kwh": text(total, draft.max_total_kwh),
        "target_user_ids": targets,
    }, errors


def _invalid(errors: list[str]):
    if errors:
        raise ApiError(422, "invalid_offer_terms", "; ".join(errors))


def _require_future(offer: dict, now: datetime):
    if when(offer["offer_expires_at"]) <= now:
        raise ApiError(422, "expiry_in_past", "The offer must expire in the future")


def _offer(connection, offer_id: str):
    row = connection.execute(
        "SELECT o.*, u.username AS created_by_username FROM offers o "
        "JOIN users u ON u.user_id=o.created_by WHERE o.offer_id=?",
        (offer_id,),
    ).fetchone()
    if not row:
        return None
    offer = dict(row)
    offer["target_user_ids"] = [
        item["user_id"]
        for item in connection.execute(
            "SELECT user_id FROM offer_targets WHERE offer_id=? ORDER BY user_id",
            (offer_id,),
        )
    ]
    return offer


def _scoped_offer(connection, user: User, offer_id: str) -> dict:
    areas = manager_areas(connection, user)
    offer = _offer(connection, offer_id)
    if not offer or offer["area_id"] not in areas:
        raise ApiError(404, *NOT_FOUND)
    return offer


# ---------------------------------------------------------------- metering and settlement


def _group(connection, site_id: str, offer_type: str, lower: str, upper: str):
    """All user offers on the site and metric connected to [lower, upper) by overlapping windows."""
    while True:
        rows = connection.execute(
            "SELECT uo.*, st.fulfilled_kwh AS settled_fulfilled_kwh FROM user_offers uo "
            "LEFT JOIN offer_settlements st ON st.user_offer_id=uo.user_offer_id "
            "WHERE uo.site_id=? AND uo.type=? AND uo.window_start<=? "
            "AND MIN(uo.window_end, COALESCE(uo.cancelled_at, uo.window_end))>=?",
            (site_id, offer_type, upper, lower),
        ).fetchall()
        low = min([lower, *(row["window_start"] for row in rows)])
        high = max([upper, *(stamp(effective_end(row)) for row in rows)])
        if (low, high) == (lower, upper):
            return rows
        lower, upper = low, high


def allocate(connection, site_id: str, offer_type: str, rows) -> dict[str, Allocation]:
    """FIFO allocations for the given user offers (and every offer they overlap with)."""
    lower = min(row["window_start"] for row in rows)
    upper = max(stamp(effective_end(row)) for row in rows)
    group = _group(connection, site_id, offer_type, lower, upper)
    start = min(when(row["window_start"]) for row in group)
    end = max(effective_end(row) for row in group)
    # The bridge picks the site's authoritative grid meter (imported component meter, else
    # the compact stream) and never reads data after the analytical scenario clock.
    intervals = offer_meter_intervals(connection, site_id, offer_type, start, end)
    commitments = [
        Commitment(
            user_offer_id=row["user_offer_id"],
            accepted_at=when(row["accepted_at"]),
            window_start=when(row["window_start"]),
            window_end=effective_end(row),
            # Settled blocks keep exactly what they were credited with.
            capacity_kwh=Decimal(row["settled_fulfilled_kwh"] or row["energy_kwh"]),
        )
        for row in group
    ]
    return attribute(intervals, commitments)


def live_allocations(connection, rows) -> dict[str, Allocation]:
    groups: dict[tuple[str, str], list] = {}
    for row in rows:
        if row["status"] in RUNNING:
            groups.setdefault((row["site_id"], row["type"]), []).append(row)
    result = {}
    for (site_id, offer_type), members in groups.items():
        result.update(allocate(connection, site_id, offer_type, members))
    return result


def _settlement_body(row, result, title: str) -> str:
    verb = "used" if row["type"] == "consume" else "fed into the grid"
    parts = [
        f"{title}: you {verb} {decimal_text(result.fulfilled_kwh)} of "
        f"{decimal_text(Decimal(row['energy_kwh']))} kWh."
    ]
    if row["type"] == "consume":
        parts.append(f"You pay {ron_text(result.amount_bani)} for this energy.")
    elif result.amount_bani >= 0:
        parts.append(f"You receive {ron_text(result.amount_bani)}.")
    else:
        parts.append(f"You pay {ron_text(-result.amount_bani)} after the penalty.")
    if result.penalty_waived_reason == "meter_data_incomplete":
        parts.append("No penalty: your meter data for the window was incomplete.")
    elif result.penalty_waived_reason == "cancelled_by_distributor":
        parts.append("No penalty: the distributor cancelled the offer.")
    elif result.penalty_bani:
        parts.append(f"Penalty included: {ron_text(result.penalty_bani)}.")
    noun = "savings" if row["type"] == "consume" else "extra earnings"
    if result.savings_bani >= 0:
        parts.append(
            f"Your {noun} compared with your normal tariff: "
            f"{ron_text(result.savings_bani)}."
        )
    else:
        parts.append(
            f"This cost you {ron_text(-result.savings_bani)} more than your normal tariff."
        )
    return " ".join(parts)


OUTCOME_TITLES = {
    "completed": "Offer completed",
    "partial": "Offer partly fulfilled",
    "expired_unfulfilled": "Offer not fulfilled",
    "cancelled": "Offer cancelled by the distributor",
}


def settle_user_offer(
    database,
    connection,
    row,
    allocation: Allocation,
    now: datetime,
    *,
    cancelled: bool = False,
    actor: str = WORKER,
    request_id: str = WORKER,
) -> bool:
    """Write the ledger row, counters and notification once. Caller holds BEGIN IMMEDIATE."""
    result = settle(
        offer_type=row["type"],
        energy_kwh=Decimal(row["energy_kwh"]),
        metered_kwh=allocation.metered_kwh,
        offer_price=Decimal(row["offer_price_ron_per_kwh"]),
        reference_price=Decimal(row["reference_price_ron_per_kwh"]),
        penalty_type=row["penalty_type"],
        penalty_value=Decimal(row["penalty_value"]),
        coverage_ratio=allocation.coverage_ratio,
        cancelled=cancelled,
    )
    at = stamp(now)
    coverage = float(round(result.coverage_ratio, 4))
    # The status guard makes retries, restarts and concurrent workers settle exactly once.
    if not connection.execute(
        "UPDATE user_offers SET status=?, metered_kwh=?, coverage_ratio=?, progress_at=?, "
        f"settled_at=? WHERE user_offer_id=? AND status IN {RUNNING_SQL}",
        (
            result.outcome,
            decimal_text(result.metered_kwh),
            coverage,
            at,
            at,
            row["user_offer_id"],
        ),
    ).rowcount:
        return False
    connection.execute(
        "INSERT INTO offer_settlements(user_offer_id,offer_id,user_id,site_id,type,outcome,"
        "energy_kwh,metered_kwh,fulfilled_kwh,unfulfilled_kwh,excess_kwh,coverage_ratio,"
        "offer_price_ron_per_kwh,reference_price_ron_per_kwh,penalty_type,penalty_value,"
        "penalty_before_waiver_bani,penalty_waived_reason,energy_value_bani,penalty_bani,"
        "amount_bani,direction,savings_bani,settled_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            row["user_offer_id"],
            row["offer_id"],
            row["user_id"],
            row["site_id"],
            row["type"],
            result.outcome,
            row["energy_kwh"],
            decimal_text(result.metered_kwh),
            decimal_text(result.fulfilled_kwh),
            decimal_text(result.unfulfilled_kwh),
            decimal_text(result.excess_kwh),
            coverage,
            row["offer_price_ron_per_kwh"],
            row["reference_price_ron_per_kwh"],
            row["penalty_type"],
            row["penalty_value"],
            result.penalty_before_waiver_bani,
            result.penalty_waived_reason,
            result.energy_value_bani,
            result.penalty_bani,
            result.amount_bani,
            result.direction,
            result.savings_bani,
            at,
        ),
    )
    consume = result.savings_bani if row["type"] == "consume" else 0
    connection.execute(
        "INSERT INTO savings_totals(user_id,lifetime_bani,consume_bani,export_bani,"
        "penalties_bani,settled_count,updated_at) VALUES (?,?,?,?,?,1,?) "
        "ON CONFLICT(user_id) DO UPDATE SET "
        "lifetime_bani=lifetime_bani+excluded.lifetime_bani, "
        "consume_bani=consume_bani+excluded.consume_bani, "
        "export_bani=export_bani+excluded.export_bani, "
        "penalties_bani=penalties_bani+excluded.penalties_bani, "
        "settled_count=settled_count+1, updated_at=excluded.updated_at",
        (
            row["user_id"],
            result.savings_bani,
            consume,
            result.savings_bani - consume,
            result.penalty_bani,
            at,
        ),
    )
    title = OUTCOME_TITLES[result.outcome]
    notify(
        connection,
        row["user_id"],
        "offer_settled",
        title,
        _settlement_body(row, result, title),
        f"offers/mine/{row['user_offer_id']}",
        now,
    )
    database.audit(
        connection,
        actor,
        "offer.settled",
        row["offer_id"],
        request_id,
        {
            "user_offer_id": row["user_offer_id"],
            "outcome": result.outcome,
            "fulfilled_kwh": decimal_text(result.fulfilled_kwh),
            "amount_bani": result.amount_bani,
            "penalty_bani": result.penalty_bani,
            "penalty_waived_reason": result.penalty_waived_reason,
            "settled_at": at,
        },
    )
    return True


# ---------------------------------------------------------------- manager views

USER_OFFER_SELECT = (
    "SELECT uo.*, o.title, s.alias AS site_alias, u.username, "
    + ", ".join(f"st.{column} AS st_{column}" for column in SETTLEMENT_COLUMNS)
    + " FROM user_offers uo JOIN offers o ON o.offer_id=uo.offer_id "
    "JOIN sites s ON s.site_id=uo.site_id JOIN users u ON u.user_id=uo.user_id "
    "LEFT JOIN offer_settlements st ON st.user_offer_id=uo.user_offer_id "
)


def _metered(row, allocations) -> Decimal:
    if row["status"] in RUNNING and row["user_offer_id"] in allocations:
        return allocations[row["user_offer_id"]].metered_kwh
    return Decimal(row["metered_kwh"])


def _coverage(row, allocations) -> float:
    if row["status"] in RUNNING and row["user_offer_id"] in allocations:
        return float(round(allocations[row["user_offer_id"]].coverage_ratio, 4))
    return float(row["coverage_ratio"])


def _live_status(row, allocations) -> str:
    if row["status"] == "accepted" and _metered(row, allocations) > 0:
        return "active"
    return row["status"]


def _stats(offer: dict, takers, allocations, targeted: int) -> OfferStats:
    statuses = [_live_status(row, allocations) for row in takers]
    energy = Decimal(offer["energy_kwh"])
    delivered = sum(
        (
            Decimal(row["st_fulfilled_kwh"])
            if row["st_fulfilled_kwh"] is not None
            else min(_metered(row, allocations), Decimal(row["energy_kwh"]))
            for row in takers
        ),
        Decimal(0),
    )
    settled = [row for row in takers if row["st_settled_at"] is not None]
    return OfferStats(
        targeted=targeted,
        accepted=len(takers),
        active=sum(status in RUNNING for status in statuses),
        fulfilled=statuses.count("completed"),
        partial=statuses.count("partial"),
        failed=statuses.count("expired_unfulfilled"),
        cancelled=statuses.count("cancelled"),
        total_kwh_committed=decimal_text(energy * len(takers)),
        total_kwh_delivered=decimal_text(delivered),
        total_penalties_bani=sum(row["st_penalty_bani"] for row in settled),
        charges_bani=sum(
            row["st_amount_bani"] for row in settled if row["st_direction"] == "charge"
        ),
        payouts_bani=sum(
            row["st_amount_bani"] for row in settled if row["st_direction"] == "credit"
        ),
        client_savings_bani=sum(row["st_savings_bani"] for row in settled),
    )


def _manager_offer(connection, offer: dict, takers, allocations, now) -> dict:
    rule, terms, worst, block = _texts(offer)
    size = len({site["user_id"] for site in audience(connection, offer)})
    return ManagerOffer(
        **{key: offer[key] for key in OFFER_COLUMNS},
        offer_id=offer["offer_id"],
        status=effective_status(offer, now),
        target_user_ids=offer["target_user_ids"],
        created_by=offer["created_by_username"],
        created_at=offer["created_at"],
        updated_at=offer["updated_at"],
        published_at=offer["published_at"],
        cancelled_at=offer["cancelled_at"],
        locked=bool(takers),
        penalty_rule_text=rule,
        terms_text=terms,
        max_penalty_bani=worst,
        block_value_bani=block,
        audience_size=size,
        stats=_stats(offer, takers, allocations, size),
    ).model_dump()


def list_manager_offers(
    connection, user: User, status: str | None, now: datetime
) -> list[ManagerOffer]:
    areas = manager_areas(connection, user)
    if not areas:
        return []
    marks = ",".join("?" * len(areas))
    ids = [
        row["offer_id"]
        for row in connection.execute(
            f"SELECT offer_id FROM offers WHERE area_id IN ({marks}) "
            "ORDER BY created_at DESC, offer_id LIMIT 200",
            areas,
        )
    ]
    offers = [_offer(connection, offer_id) for offer_id in ids]
    if status:
        offers = [offer for offer in offers if effective_status(offer, now) == status]
    if not offers:
        return []
    marks = ",".join("?" * len(offers))
    takers = connection.execute(
        USER_OFFER_SELECT + f"WHERE uo.offer_id IN ({marks})",
        [offer["offer_id"] for offer in offers],
    ).fetchall()
    allocations = live_allocations(connection, takers)
    return [
        ManagerOffer(
            **_manager_offer(
                connection,
                offer,
                [row for row in takers if row["offer_id"] == offer["offer_id"]],
                allocations,
                now,
            )
        )
        for offer in offers
    ]


def manager_offer_detail(
    connection, user: User, offer_id: str, now: datetime
) -> ManagerOfferDetail:
    offer = _scoped_offer(connection, user, offer_id)
    takers = connection.execute(
        USER_OFFER_SELECT
        + "WHERE uo.offer_id=? ORDER BY uo.accepted_at, uo.user_offer_id",
        (offer_id,),
    ).fetchall()
    allocations = live_allocations(connection, takers)
    return ManagerOfferDetail(
        **_manager_offer(connection, offer, takers, allocations, now),
        takers=[
            OfferTaker(
                user_offer_id=row["user_offer_id"],
                username=row["username"],
                site_id=row["site_id"],
                site_alias=row["site_alias"],
                status=_live_status(row, allocations),
                accepted_at=row["accepted_at"],
                window_end=row["window_end"],
                metered_kwh=decimal_text(_metered(row, allocations)),
                fulfilled_kwh=decimal_text(
                    Decimal(row["st_fulfilled_kwh"])
                    if row["st_fulfilled_kwh"] is not None
                    else min(_metered(row, allocations), Decimal(row["energy_kwh"]))
                ),
                coverage_ratio=_coverage(row, allocations),
                penalty_bani=row["st_penalty_bani"],
                amount_bani=row["st_amount_bani"],
                savings_bani=row["st_savings_bani"],
            )
            for row in takers
        ],
    )


def _save_targets(connection, offer_id: str, targets: list[str]):
    connection.execute("DELETE FROM offer_targets WHERE offer_id=?", (offer_id,))
    connection.executemany(
        "INSERT INTO offer_targets(offer_id,user_id) VALUES (?,?)",
        [(offer_id, user_id) for user_id in targets],
    )


def create_offer(
    database, connection, user: User, draft: OfferDraft, rid: str, now: datetime
) -> ManagerOfferDetail:
    connection.execute("BEGIN IMMEDIATE")
    offer, errors = normalize_draft(connection, draft, manager_areas(connection, user))
    _invalid(errors)
    offer_id = uuid.uuid4().hex
    at = stamp(now)
    columns = (
        *OFFER_COLUMNS,
        "offer_id",
        "status",
        "created_by",
        "created_at",
        "updated_at",
    )
    values = {
        **offer,
        "offer_id": offer_id,
        "status": "draft",
        "created_by": user.user_id,
        "created_at": at,
        "updated_at": at,
    }
    connection.execute(
        f"INSERT INTO offers({','.join(columns)}) VALUES ({','.join('?' * len(columns))})",
        [values[column] for column in columns],
    )
    _save_targets(connection, offer_id, offer["target_user_ids"])
    database.audit(
        connection,
        user.user_id,
        "offer.created",
        offer_id,
        rid,
        {key: offer[key] for key in (*OFFER_COLUMNS, "target_user_ids")},
    )
    return manager_offer_detail(connection, user, offer_id, now)


def _locked(connection, offer_id: str) -> bool:
    return bool(
        connection.execute(
            "SELECT 1 FROM user_offers WHERE offer_id=? LIMIT 1", (offer_id,)
        ).fetchone()
    )


def update_offer(
    database,
    connection,
    user: User,
    offer_id: str,
    draft: OfferDraft,
    rid: str,
    now: datetime,
) -> ManagerOfferDetail:
    connection.execute("BEGIN IMMEDIATE")
    previous = _scoped_offer(connection, user, offer_id)
    status = effective_status(previous, now)
    if status not in ("draft", "available"):
        raise ApiError(409, "offer_closed", f"A {status} offer cannot be edited")
    if _locked(connection, offer_id):
        raise ApiError(
            409, "offer_locked", "The offer cannot be edited after a client accepted it"
        )
    offer, errors = normalize_draft(connection, draft, manager_areas(connection, user))
    _invalid(errors)
    if status == "available":
        _require_future(offer, now)
        if not audience(connection, offer):
            raise ApiError(422, "empty_audience", "No client matches this targeting")
    changed = {
        key: [previous[key], offer[key]]
        for key in (*OFFER_COLUMNS, "target_user_ids")
        if previous[key] != offer[key]
    }
    connection.execute(
        f"UPDATE offers SET {', '.join(f'{key}=?' for key in OFFER_COLUMNS)}, updated_at=? "
        "WHERE offer_id=?",
        [*(offer[key] for key in OFFER_COLUMNS), stamp(now), offer_id],
    )
    _save_targets(connection, offer_id, offer["target_user_ids"])
    database.audit(
        connection, user.user_id, "offer.updated", offer_id, rid, {"changed": changed}
    )
    return manager_offer_detail(connection, user, offer_id, now)


def _new_offer_notice(offer: dict) -> tuple[str, str]:
    rule, _, _, _ = _texts(offer)
    energy = decimal_text(Decimal(offer["energy_kwh"]))
    price = price_text(Decimal(offer["offer_price_ron_per_kwh"]))
    window = window_text(offer["window_minutes"])
    if offer["type"] == "consume":
        headline = f"Use {energy} kWh at {price} RON/kWh"
        body = f"Use {energy} kWh within {window} of accepting at {price} RON/kWh."
    else:
        headline = f"Feed {energy} kWh into the grid at {price} RON/kWh"
        body = (
            f"Feed {energy} kWh into the grid within {window} of accepting "
            f"at {price} RON/kWh."
        )
    return f"New offer: {offer['title'] or headline}", f"{body} {rule}"


def publish(database, connection, offer: dict, actor: str, rid: str, now: datetime):
    """Make a validated draft available and notify its audience."""
    clients = sorted({site["user_id"] for site in audience(connection, offer)})
    connection.execute(
        "UPDATE offers SET status='available', published_at=?, updated_at=? "
        "WHERE offer_id=? AND status='draft'",
        (stamp(now), stamp(now), offer["offer_id"]),
    )
    title, body = _new_offer_notice(offer)
    for user_id in clients:
        notify(
            connection,
            user_id,
            "offer_new",
            title,
            body,
            f"offers/{offer['offer_id']}",
            now,
        )
    database.audit(
        connection,
        actor,
        "offer.published",
        offer["offer_id"],
        rid,
        {"audience_size": len(clients)},
    )


def _draft_of(offer: dict) -> OfferDraft:
    return OfferDraft(
        **{
            key: offer[key]
            for key in (*OFFER_COLUMNS, "target_user_ids")
            if key != "offer_expires_at"
        },
        offer_expires_at=when(offer["offer_expires_at"]),
    )


def publish_offer(
    database, connection, user: User, offer_id: str, rid: str, now: datetime
) -> ManagerOfferDetail:
    connection.execute("BEGIN IMMEDIATE")
    offer = _scoped_offer(connection, user, offer_id)
    if offer["status"] != "draft":
        raise ApiError(409, "offer_not_draft", "Only a draft offer can be published")
    # Re-validate the stored terms and scope at publish time.
    _, errors = normalize_draft(
        connection, _draft_of(offer), manager_areas(connection, user)
    )
    _invalid(errors)
    _require_future(offer, now)
    if not audience(connection, offer):
        raise ApiError(422, "empty_audience", "No client matches this targeting")
    publish(database, connection, offer, user.user_id, rid, now)
    return manager_offer_detail(connection, user, offer_id, now)


def cancel_offer(
    database, connection, user: User, offer_id: str, rid: str, now: datetime
) -> ManagerOfferDetail:
    connection.execute("BEGIN IMMEDIATE")
    offer = _scoped_offer(connection, user, offer_id)
    if offer["status"] not in ("draft", "available"):
        raise ApiError(
            409,
            "offer_not_cancellable",
            "Only draft or available offers can be cancelled",
        )
    at = stamp(now)
    connection.execute(
        "UPDATE offers SET status='cancelled', cancelled_at=?, updated_at=? WHERE offer_id=?",
        (at, at, offer_id),
    )
    # Running windows close now; delivered energy settles with the penalty waived.
    connection.execute(
        "UPDATE user_offers SET cancelled_at=? "
        f"WHERE offer_id=? AND status IN {RUNNING_SQL} AND window_end>?",
        (at, offer_id, at),
    )
    running = connection.execute(
        f"SELECT * FROM user_offers WHERE offer_id=? AND status IN {RUNNING_SQL} "
        "AND cancelled_at IS NOT NULL",
        (offer_id,),
    ).fetchall()
    allocations = live_allocations(connection, running)
    for row in running:
        settle_user_offer(
            database,
            connection,
            row,
            allocations[row["user_offer_id"]],
            now,
            cancelled=True,
            actor=user.user_id,
            request_id=rid,
        )
    database.audit(
        connection,
        user.user_id,
        "offer.cancelled",
        offer_id,
        rid,
        {"previous_status": offer["status"], "running_windows_closed": len(running)},
    )
    return manager_offer_detail(connection, user, offer_id, now)


def _preview(connection, offer: dict, errors: list[str], now) -> OfferPreview:
    sites = audience(connection, offer)
    clients = sorted({site["username"] for site in sites})
    warnings: list[str] = []
    expires = when(offer["offer_expires_at"]) if offer["offer_expires_at"] else None
    if expires and expires <= now:
        errors = [*errors, "The offer must expire in the future"]
    if not sites:
        errors = [*errors, "No client matches this targeting"]
    if errors:
        return OfferPreview(
            audience_size=len(clients),
            sites=len(sites),
            sample_clients=clients[:10],
            warnings=warnings,
            errors=errors,
            summary=None,
        )
    rule, terms, worst, block = _texts(offer)
    energy = Decimal(offer["energy_kwh"])
    price = Decimal(offer["offer_price_ron_per_kwh"])
    tariff = profile_source()["default_tariff"]
    key = (
        "import_price_ron_kwh" if offer["type"] == "consume" else "export_price_ron_kwh"
    )
    default = Decimal(str(tariff[key]))
    losing = sum(
        _gain(
            offer["type"],
            energy,
            price,
            reference_price(connection, s["site_id"], offer["type"])[0],
        )
        < 0
        for s in sites
    )
    if offer["type"] == "consume" and price > default:
        warnings.append(
            f"The offer price ({price_text(price)} RON/kWh) is above the default import "
            f"tariff ({price_text(default)} RON/kWh): clients would lose money compared "
            "with their normal tariff."
        )
    if offer["type"] == "export" and price < default:
        warnings.append(
            f"The offer price ({price_text(price)} RON/kWh) is below the default export "
            f"tariff ({price_text(default)} RON/kWh): clients would lose money compared "
            "with their normal tariff."
        )
    if losing:
        warnings.append(
            f"{losing} of {len(sites)} targeted sites would be worse off than with their "
            "own contract or default tariff."
        )
    if worst > block:
        warnings.append(
            f"The maximum penalty ({ron_text(worst)}) is higher than the value of the "
            f"block ({ron_text(block)})."
        )
    if offer["window_minutes"] < 30:
        warnings.append("A window shorter than 30 minutes is hard for clients to meet.")
    if offer["type"] == "export":
        blocked = sum(not site["export_capable"] for site in sites)
        if blocked:
            warnings.append(
                f"{blocked} targeted sites cannot measure grid export and cannot accept."
            )
    if offer["type"] == "consume":
        blocked = sum(not site["import_capable"] for site in sites)
        if blocked:
            warnings.append(
                f"{blocked} targeted sites cannot measure grid import and cannot accept."
            )
    missing = sum(not site["has_meter"] for site in sites)
    if missing:
        warnings.append(
            f"{missing} targeted sites have no linked meter and cannot accept."
        )
    return OfferPreview(
        audience_size=len(clients),
        sites=len(sites),
        sample_clients=clients[:10],
        warnings=warnings,
        errors=[],
        summary=PreviewSummary(
            terms_text=terms,
            penalty_rule_text=rule,
            max_penalty_bani=worst,
            block_value_bani=block,
            max_client_value_bani=bani(_gain(offer["type"], energy, price, default)),
        ),
    )


def preview_draft(connection, user: User, draft: OfferDraft, now) -> OfferPreview:
    offer, errors = normalize_draft(connection, draft, manager_areas(connection, user))
    return _preview(connection, offer, errors, now)


def preview_offer(connection, user: User, offer_id: str, now) -> OfferPreview:
    offer = _scoped_offer(connection, user, offer_id)
    _, errors = normalize_draft(
        connection, _draft_of(offer), manager_areas(connection, user)
    )
    return _preview(connection, offer, errors, now)


def manager_clients(connection, user: User, area_id: str | None) -> list[ManagerClient]:
    areas = manager_areas(connection, user)
    if area_id is not None:
        if area_id not in areas:
            raise ApiError(404, *NOT_FOUND)
        areas = [area_id]
    if not areas:
        return []
    marks = ",".join("?" * len(areas))
    clients: dict[str, ManagerClient] = {}
    for row in connection.execute(
        CLIENT_SITES + f"AND s.area_id IN ({marks}) ORDER BY u.username, s.site_id",
        areas,
    ):
        site = _site_info(row)
        client = clients.setdefault(
            row["user_id"],
            ManagerClient(user_id=row["user_id"], username=row["username"], sites=[]),
        )
        client.sites.append(
            ClientSite(
                **{
                    key: site[key]
                    for key in (
                        "site_id",
                        "alias",
                        "area_id",
                        "zone",
                        "segment",
                        "has_pv",
                        "export_capable",
                        "has_meter",
                    )
                },
                installed_kwp=None
                if site["installed_kwp"] is None
                else decimal_text(site["installed_kwp"]),
            )
        )
    return list(clients.values())


def offer_audit(connection, user: User, offer_id: str) -> list[AuditEntry]:
    _scoped_offer(connection, user, offer_id)
    rows = connection.execute(
        "SELECT a.*, COALESCE(u.username, a.actor) AS actor_name FROM audit a "
        "LEFT JOIN users u ON u.user_id=a.actor "
        "WHERE a.subject=? AND a.action LIKE 'offer.%' ORDER BY a.id",
        (offer_id,),
    ).fetchall()
    return [
        AuditEntry(
            actor=row["actor_name"],
            action=row["action"],
            subject=row["subject"],
            detail=json.loads(row["detail"]) if row["detail"] else None,
            created_at=row["received_at"],
            request_id=row["request_id"],
        )
        for row in rows
    ]


# ---------------------------------------------------------------- client views


def _capacity(connection, offer: dict) -> RemainingCapacity | None:
    if offer["max_takers"] is None and offer["max_total_kwh"] is None:
        return None
    takers, committed = _taken(connection, offer["offer_id"])
    takers_left = (
        None if offer["max_takers"] is None else max(0, offer["max_takers"] - takers)
    )
    kwh_left = (
        None
        if offer["max_total_kwh"] is None
        else max(Decimal(0), Decimal(offer["max_total_kwh"]) - committed)
    )
    full = takers_left == 0 or (
        kwh_left is not None and kwh_left < Decimal(offer["energy_kwh"])
    )
    return RemainingCapacity(
        takers_left=takers_left,
        kwh_left=None if kwh_left is None else decimal_text(kwh_left),
        full=full,
    )


def _taken(connection, offer_id: str) -> tuple[int, Decimal]:
    rows = connection.execute(
        "SELECT energy_kwh FROM user_offers WHERE offer_id=?", (offer_id,)
    ).fetchall()
    return len(rows), sum((Decimal(row["energy_kwh"]) for row in rows), Decimal(0))


def client_offers(connection, user: User, now: datetime) -> list[ClientOffer]:
    require_customer(user)
    rows = connection.execute(
        "SELECT o.offer_id FROM offers o WHERE o.status='available' AND o.offer_expires_at>? "
        "AND o.area_id IN (SELECT s.area_id FROM user_sites us JOIN sites s "
        "ON s.site_id=us.site_id WHERE us.user_id=?) "
        "AND NOT EXISTS (SELECT 1 FROM user_offers uo WHERE uo.offer_id=o.offer_id "
        "AND uo.user_id=?) ORDER BY o.published_at DESC, o.offer_id LIMIT 100",
        (stamp(now), user.user_id, user.user_id),
    ).fetchall()
    result = []
    for row in rows:
        offer = _offer(connection, row["offer_id"])
        sites = audience(connection, offer, user.user_id)
        if not sites:
            continue
        rule, terms, worst, block = _texts(offer)
        energy = Decimal(offer["energy_kwh"])
        price = Decimal(offer["offer_price_ron_per_kwh"])
        eligible = []
        for site in sites:
            reference, source = reference_price(
                connection, site["site_id"], offer["type"]
            )
            eligible.append(
                EligibleSite(
                    site_id=site["site_id"],
                    alias=site["alias"],
                    reference_price_ron_per_kwh=decimal_text(reference),
                    reference_price_source=source,
                    export_capable=site["export_capable"],
                    has_meter=site["has_meter"],
                    savings_if_completed_bani=bani(
                        _gain(offer["type"], energy, price, reference)
                    ),
                )
            )
        result.append(
            ClientOffer(
                **{
                    key: offer[key]
                    for key in (
                        "offer_id",
                        "type",
                        "title",
                        "area_id",
                        "energy_kwh",
                        "offer_price_ron_per_kwh",
                        "window_minutes",
                        "penalty_type",
                        "penalty_value",
                        "offer_expires_at",
                        "published_at",
                    )
                },
                penalty_rule_text=rule,
                terms_text=terms,
                max_penalty_bani=worst,
                block_value_bani=block,
                eligible_sites=eligible,
                remaining_capacity=_capacity(connection, offer),
            )
        )
    return result


def _user_offer_view(row, allocations) -> UserOffer:
    rule, terms, worst, _ = _texts(row)
    energy = Decimal(row["energy_kwh"])
    metered = _metered(row, allocations)
    settled = row["st_settled_at"] is not None
    fulfilled = Decimal(row["st_fulfilled_kwh"]) if settled else min(metered, energy)
    projected = (
        row["st_penalty_bani"]
        if settled
        else bani(
            penalty_ron(
                row["penalty_type"],
                Decimal(row["penalty_value"]),
                energy - fulfilled,
                Decimal(row["offer_price_ron_per_kwh"]),
            )
        )
    )
    return UserOffer(
        **{
            key: row[key]
            for key in (
                "user_offer_id",
                "offer_id",
                "type",
                "title",
                "site_id",
                "site_alias",
                "energy_kwh",
                "offer_price_ron_per_kwh",
                "reference_price_ron_per_kwh",
                "reference_price_source",
                "window_minutes",
                "penalty_type",
                "penalty_value",
                "accepted_at",
                "window_start",
                "window_end",
                "cancelled_at",
            )
        },
        penalty_rule_text=rule,
        terms_text=terms,
        status=_live_status(row, allocations),
        metered_kwh=decimal_text(metered),
        remaining_kwh=decimal_text(energy - fulfilled),
        coverage_ratio=_coverage(row, allocations),
        max_penalty_bani=worst,
        projected_penalty_bani=projected,
        settlement=SettlementView(
            **{column: row[f"st_{column}"] for column in SETTLEMENT_COLUMNS}
        )
        if settled
        else None,
    )


def my_offers(connection, user: User, scope: str) -> list[UserOffer]:
    require_customer(user)
    where = {
        "active": f" AND uo.status IN {RUNNING_SQL}",
        "history": f" AND uo.status NOT IN {RUNNING_SQL}",
        "all": "",
    }[scope]
    rows = connection.execute(
        USER_OFFER_SELECT
        + "WHERE uo.user_id=?"
        + where
        + " ORDER BY uo.accepted_at DESC, uo.user_offer_id LIMIT 200",
        (user.user_id,),
    ).fetchall()
    allocations = live_allocations(connection, rows)
    return [_user_offer_view(row, allocations) for row in rows]


def _user_offer(connection, user_offer_id: str) -> UserOffer:
    rows = connection.execute(
        USER_OFFER_SELECT + "WHERE uo.user_offer_id=?", (user_offer_id,)
    ).fetchall()
    return _user_offer_view(rows[0], live_allocations(connection, rows))


def accept_offer(
    database,
    connection,
    user: User,
    offer_id: str,
    site_id: str | None,
    idempotency_key: str | None,
    rid: str,
    now: datetime,
    max_active: int,
) -> tuple[UserOffer, bool]:
    """Accept for one eligible site. Returns (user offer, created)."""
    require_customer(user)
    connection.execute("BEGIN IMMEDIATE")
    if idempotency_key:
        existing = connection.execute(
            "SELECT user_offer_id, offer_id FROM user_offers "
            "WHERE user_id=? AND idempotency_key=?",
            (user.user_id, idempotency_key),
        ).fetchone()
        if existing:
            if existing["offer_id"] != offer_id:
                raise ApiError(
                    409,
                    "idempotency_key_reused",
                    "This Idempotency-Key was already used for another offer",
                )
            return _user_offer(connection, existing["user_offer_id"]), False
    offer = _offer(connection, offer_id)
    sites = audience(connection, offer, user.user_id) if offer else []
    if not offer or offer["status"] == "draft" or not sites:
        raise ApiError(404, *NOT_FOUND)
    if effective_status(offer, now) != "available":
        raise ApiError(409, "offer_unavailable", "This offer is no longer available")
    if connection.execute(
        "SELECT 1 FROM user_offers WHERE offer_id=? AND user_id=?",
        (offer_id, user.user_id),
    ).fetchone():
        raise ApiError(409, "already_accepted", "You have already accepted this offer")
    if site_id is None:
        if len(sites) != 1:
            raise ApiError(
                422, "site_required", "Choose which of your sites accepts this offer"
            )
        site = sites[0]
    else:
        site = next((item for item in sites if item["site_id"] == site_id), None)
        if not site:
            raise ApiError(
                422, "site_not_eligible", "This site is not eligible for the offer"
            )
    if not site["has_meter"]:
        raise ApiError(422, "meter_required", "This site has no linked meter")
    if offer["type"] == "export" and not site["export_capable"]:
        raise ApiError(
            422,
            "export_meter_required",
            "This site's meter does not measure grid export",
        )
    if offer["type"] == "consume" and not site["import_capable"]:
        raise ApiError(
            422,
            "import_meter_required",
            "This site's meter does not measure grid import",
        )
    active = connection.execute(
        f"SELECT COUNT(*) FROM user_offers WHERE user_id=? AND status IN {RUNNING_SQL}",
        (user.user_id,),
    ).fetchone()[0]
    if active >= max_active:
        raise ApiError(
            409,
            "too_many_active_offers",
            f"You can have at most {max_active} offers running at the same time",
        )
    takers, committed = _taken(connection, offer_id)
    energy = Decimal(offer["energy_kwh"])
    if (offer["max_takers"] is not None and takers >= offer["max_takers"]) or (
        offer["max_total_kwh"] is not None
        and committed + energy > Decimal(offer["max_total_kwh"])
    ):
        raise ApiError(409, "offer_full", "This offer has no capacity left")
    reference, source = reference_price(connection, site["site_id"], offer["type"])
    user_offer_id = uuid.uuid4().hex
    start = now.astimezone(UTC)
    end = start + timedelta(minutes=offer["window_minutes"])
    try:
        connection.execute(
            "INSERT INTO user_offers(user_offer_id,offer_id,user_id,site_id,type,energy_kwh,"
            "offer_price_ron_per_kwh,window_minutes,penalty_type,penalty_value,"
            "reference_price_ron_per_kwh,reference_price_source,status,accepted_at,"
            "window_start,window_end,idempotency_key) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'accepted',?,?,?,?)",
            (
                user_offer_id,
                offer_id,
                user.user_id,
                site["site_id"],
                offer["type"],
                offer["energy_kwh"],
                offer["offer_price_ron_per_kwh"],
                offer["window_minutes"],
                offer["penalty_type"],
                offer["penalty_value"],
                decimal_text(reference),
                source,
                stamp(start),
                stamp(start),
                stamp(end),
                idempotency_key,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ApiError(
            409, "already_accepted", "You have already accepted this offer"
        ) from exc
    verb = "Use" if offer["type"] == "consume" else "Feed"
    notify(
        connection,
        user.user_id,
        "offer_accepted",
        "Offer accepted",
        f"Your window for {site['alias']} has started and lasts "
        f"{window_text(offer['window_minutes'])}. {verb} {decimal_text(energy)} kWh"
        f"{' into the grid' if offer['type'] == 'export' else ''} at "
        f"{price_text(Decimal(offer['offer_price_ron_per_kwh']))} RON/kWh before it ends.",
        f"offers/mine/{user_offer_id}",
        now,
    )
    database.audit(
        connection,
        user.user_id,
        "offer.accepted",
        offer_id,
        rid,
        {
            "user_offer_id": user_offer_id,
            "site_id": site["site_id"],
            "reference_price_ron_per_kwh": decimal_text(reference),
            "reference_price_source": source,
            # Event (analytical) time; audit.received_at keeps the real receipt time.
            "accepted_at": stamp(start),
            "clock": clock_state(connection).mode,
        },
    )
    return _user_offer(connection, user_offer_id), True


def savings_summary(connection, user: User, now: datetime) -> SavingsSummary:
    require_customer(user)
    totals = connection.execute(
        "SELECT * FROM savings_totals WHERE user_id=?", (user.user_id,)
    ).fetchone()
    local = now.astimezone(BUCHAREST)
    month = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    this_month = connection.execute(
        "SELECT COALESCE(SUM(savings_bani),0) FROM offer_settlements "
        "WHERE user_id=? AND settled_at>=?",
        (user.user_id, stamp(month.astimezone(UTC))),
    ).fetchone()[0]
    recent = connection.execute(
        "SELECT st.*, uo.status, o.title, s.alias AS site_alias FROM offer_settlements st "
        "JOIN user_offers uo ON uo.user_offer_id=st.user_offer_id "
        "JOIN offers o ON o.offer_id=st.offer_id JOIN sites s ON s.site_id=st.site_id "
        "WHERE st.user_id=? ORDER BY st.settled_at DESC, st.settlement_id DESC LIMIT 10",
        (user.user_id,),
    ).fetchall()
    return SavingsSummary(
        lifetime_bani=totals["lifetime_bani"] if totals else 0,
        this_month_bani=this_month,
        penalties_paid_bani=totals["penalties_bani"] if totals else 0,
        consume_bani=totals["consume_bani"] if totals else 0,
        export_bani=totals["export_bani"] if totals else 0,
        settled_count=totals["settled_count"] if totals else 0,
        last_settled_at=recent[0]["settled_at"] if recent else None,
        recent=[
            SettlementSummary(
                **{
                    key: row[key]
                    for key in (
                        "user_offer_id",
                        "offer_id",
                        "type",
                        "title",
                        "site_alias",
                        "status",
                        "energy_kwh",
                        "fulfilled_kwh",
                        "penalty_bani",
                        "amount_bani",
                        "direction",
                        "savings_bani",
                        "settled_at",
                    )
                }
            )
            for row in recent
        ],
    )
