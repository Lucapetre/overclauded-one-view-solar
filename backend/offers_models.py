"""Power Block Offers API models.

kWh and RON/kWh prices are decimal strings; money is integer bani (1 RON = 100 bani);
timestamps are UTC ISO 8601.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field

from backend.models import Identifier, Model

OfferType = Literal["consume", "export"]
PenaltyType = Literal["per_unfulfilled_kwh", "percent_of_unfulfilled_value", "flat"]
OfferStatus = Literal["draft", "available", "cancelled", "expired"]
UserOfferStatus = Literal[
    "accepted", "active", "completed", "partial", "expired_unfulfilled", "cancelled"
]
TargetMode = Literal["all", "segment", "clients"]
TargetSegment = Literal["consumers", "prosumers"]
ReferenceSource = Literal["contract", "default_tariff"]
WaivedReason = Literal["meter_data_incomplete", "cancelled_by_distributor"]
NotificationKind = Literal[
    "offer_new",
    "offer_accepted",
    "offer_reminder_30",
    "offer_reminder_10",
    "offer_settled",
]
# Plain decimal strings only (never JSON numbers); ranges and places are checked by the server.
DecimalText = Annotated[str, Field(pattern=r"^\d{1,7}(\.\d{1,6})?$", max_length=14)]


class OfferDraft(Model):
    type: OfferType
    title: Annotated[str, Field(max_length=80)] | None = None
    energy_kwh: DecimalText
    offer_price_ron_per_kwh: DecimalText
    window_minutes: int
    penalty_type: PenaltyType
    penalty_value: DecimalText
    offer_expires_at: datetime
    area_id: Identifier
    target_mode: TargetMode = "all"
    target_segment: TargetSegment | None = None
    target_min_kwp: DecimalText | None = None
    target_user_ids: Annotated[list[Identifier], Field(max_length=500)] = Field(
        default_factory=list
    )
    max_takers: Annotated[int, Field(ge=1, le=100000)] | None = None
    max_total_kwh: DecimalText | None = None
    linked_incident_id: Identifier | None = None
    target_zone: Annotated[str, Field(min_length=1, max_length=80)] | None = None


class OfferStats(Model):
    targeted: int
    accepted: int
    active: int
    fulfilled: int
    partial: int
    failed: int
    cancelled: int
    total_kwh_committed: str
    total_kwh_delivered: str
    total_penalties_bani: int
    charges_bani: int
    payouts_bani: int
    client_savings_bani: int


class ManagerOffer(Model):
    offer_id: str
    type: OfferType
    title: str | None
    energy_kwh: str
    offer_price_ron_per_kwh: str
    window_minutes: int
    penalty_type: PenaltyType
    penalty_value: str
    offer_expires_at: datetime
    area_id: str
    status: OfferStatus
    target_mode: TargetMode
    target_segment: TargetSegment | None
    target_min_kwp: str | None
    target_zone: str | None
    target_user_ids: list[str]
    max_takers: int | None
    max_total_kwh: str | None
    linked_incident_id: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    cancelled_at: datetime | None
    locked: bool
    penalty_rule_text: str
    terms_text: str
    max_penalty_bani: int
    block_value_bani: int
    audience_size: int
    stats: OfferStats


class OfferTaker(Model):
    user_offer_id: str
    username: str
    site_id: str
    site_alias: str
    status: UserOfferStatus
    accepted_at: datetime
    window_end: datetime
    metered_kwh: str
    fulfilled_kwh: str
    coverage_ratio: float
    penalty_bani: int | None
    amount_bani: int | None
    savings_bani: int | None


class ManagerOfferDetail(ManagerOffer):
    takers: list[OfferTaker]


class PreviewSummary(Model):
    terms_text: str
    penalty_rule_text: str
    max_penalty_bani: int
    block_value_bani: int
    max_client_value_bani: int


class OfferPreview(Model):
    audience_size: int
    sites: int
    sample_clients: list[str]
    warnings: list[str]
    errors: list[str]
    summary: PreviewSummary | None


class ClientSite(Model):
    site_id: str
    alias: str
    area_id: str | None
    zone: str | None
    segment: TargetSegment
    installed_kwp: str | None
    has_pv: bool
    export_capable: bool
    has_meter: bool


class ManagerClient(Model):
    user_id: str
    username: str
    sites: list[ClientSite]


class AuditEntry(Model):
    actor: str
    action: str
    subject: str
    detail: dict[str, Any] | None
    created_at: datetime
    request_id: str


class EligibleSite(Model):
    site_id: str
    alias: str
    reference_price_ron_per_kwh: str
    reference_price_source: ReferenceSource
    export_capable: bool
    has_meter: bool
    savings_if_completed_bani: int


class RemainingCapacity(Model):
    takers_left: int | None
    kwh_left: str | None
    full: bool


class ClientOffer(Model):
    offer_id: str
    type: OfferType
    title: str | None
    area_id: str
    energy_kwh: str
    offer_price_ron_per_kwh: str
    window_minutes: int
    penalty_type: PenaltyType
    penalty_value: str
    penalty_rule_text: str
    terms_text: str
    max_penalty_bani: int
    block_value_bani: int
    offer_expires_at: datetime
    published_at: datetime | None
    eligible_sites: list[EligibleSite]
    remaining_capacity: RemainingCapacity | None


class AcceptOffer(Model):
    site_id: Identifier | None = None


class SettlementView(Model):
    metered_kwh: str
    fulfilled_kwh: str
    unfulfilled_kwh: str
    excess_kwh: str
    coverage_ratio: float
    penalty_before_waiver_bani: int
    penalty_bani: int
    penalty_waived_reason: WaivedReason | None
    energy_value_bani: int
    amount_bani: int
    direction: Literal["charge", "credit"]
    savings_bani: int
    settled_at: datetime


class UserOffer(Model):
    user_offer_id: str
    offer_id: str
    type: OfferType
    title: str | None
    site_id: str
    site_alias: str
    energy_kwh: str
    offer_price_ron_per_kwh: str
    reference_price_ron_per_kwh: str
    reference_price_source: ReferenceSource
    window_minutes: int
    penalty_type: PenaltyType
    penalty_value: str
    penalty_rule_text: str
    terms_text: str
    status: UserOfferStatus
    accepted_at: datetime
    window_start: datetime
    window_end: datetime
    cancelled_at: datetime | None
    metered_kwh: str
    remaining_kwh: str
    coverage_ratio: float
    max_penalty_bani: int
    projected_penalty_bani: int
    settlement: SettlementView | None


class SettlementSummary(Model):
    user_offer_id: str
    offer_id: str
    type: OfferType
    title: str | None
    site_alias: str
    status: UserOfferStatus
    energy_kwh: str
    fulfilled_kwh: str
    penalty_bani: int
    amount_bani: int
    direction: Literal["charge", "credit"]
    savings_bani: int
    settled_at: datetime


class SavingsSummary(Model):
    lifetime_bani: int
    this_month_bani: int
    penalties_paid_bani: int
    consume_bani: int
    export_bani: int
    settled_count: int
    last_settled_at: datetime | None
    display_timezone: Literal["Europe/Bucharest"] = "Europe/Bucharest"
    recent: list[SettlementSummary]


class Notification(Model):
    notification_id: str
    kind: NotificationKind
    title: str
    body: str
    link: str | None
    created_at: datetime
    read_at: datetime | None


class NotificationList(Model):
    unread_count: int
    notifications: list[Notification]
