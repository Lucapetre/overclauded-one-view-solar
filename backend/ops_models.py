from datetime import datetime
from typing import Literal

from backend.models import Identifier, Model
from backend.status_models import (
    Condition,
    CrewMarker,
    CrewProfileView,
    RouteLine,
    SiteStatus,
    StatusCounts,
    TelemetryState,
    Workflow,
)

Tier = Literal["P0", "P1", "P2", "P3"]
TIERS: tuple[str, ...] = ("P0", "P1", "P2", "P3")
Family = Literal[
    "Production",
    "Temperature",
    "Telemetry",
    "Voltage",
    "Area event",
    "Local issue",
    "Billing",
    "Battery",
    "Other",
]
FAMILIES: tuple[str, ...] = Family.__args__
IncidentStatus = Literal[
    "new", "assigned", "team_sent", "meeting_scheduled", "resolved"
]
IncidentSource = Literal["synthetic_replay", "customer_request"]
AssignmentKind = Literal["dispatch", "meeting"]
AssignmentStatus = Literal[
    "assigned", "team_sent", "meeting_scheduled", "completed", "cancelled"
]
Segment = Literal["home", "business"]
FreshnessStatus = Literal["fresh", "stale", "unavailable", "future", "unknown_clock"]


class MapCenter(Model):
    latitude: float
    longitude: float
    zoom: int


class MapSite(Model):
    site_id: str
    alias: str
    area_id: str | None
    area_alias: str | None
    cluster: str | None
    latitude: float
    longitude: float
    zone: str
    character: str
    segment: Segment
    business_type: str | None
    installed_kwp: float
    freshness_status: FreshnessStatus
    open_incidents: int
    worst_tier: Tier | None
    # From the common site-status projection (same revision as the queue).
    condition: Condition | None = None
    telemetry_state: TelemetryState | None = None
    workflow: Workflow | None = None
    highest_priority: Tier | None = None
    episode_ids: list[str] = []


ClusterKind = Literal[
    "residential", "hospitality", "commercial", "industrial", "logistics"
]


class MapCluster(Model):
    """A named group of nearby demo installations, drawn as one highlight."""

    id: str
    name: str
    area_id: str
    kind: ClusterKind


class OpsMap(Model):
    center: MapCenter
    note: str
    sites: list[MapSite]
    clusters: list[MapCluster]
    # Common status projection: every scoped site (provider scenario sites included), the
    # unmapped list, scoped counts, authorized crew markers and labelled schematic routes.
    revision: int = 0
    status_as_of: datetime | None = None
    status_sites: list[SiteStatus] = []
    unmapped: list[SiteStatus] = []
    counts: StatusCounts | None = None
    crews: list[CrewMarker] = []
    routes: list[RouteLine] = []


class AssignmentSummary(Model):
    assignment_id: str
    crew_id: str
    crew_name: str
    kind: AssignmentKind
    status: AssignmentStatus
    scheduled_start: datetime | None
    scheduled_end: datetime | None


class Incident(Model):
    incident_id: str
    site_id: str
    site_alias: str
    area_id: str | None
    zone: str | None
    segment: Segment | None
    title: str
    family: Family
    tier: Tier
    status: IncidentStatus
    source: IncidentSource
    evidence: str
    created_at: datetime
    updated_at: datetime
    support_request_id: str | None
    assignment: AssignmentSummary | None


class IncidentLogEntry(Model):
    actor: str
    action: str
    detail: str
    created_at: datetime


class IncidentDetail(Incident):
    log: list[IncidentLogEntry]


class AssignRequest(Model):
    crew_id: Identifier | None = None


class MeetingRequest(Model):
    start: datetime
    end: datetime


class AutoAssigned(Model):
    incident_id: str
    crew_name: str
    tier: Tier


class AutoSkipped(Model):
    incident_id: str
    tier: Tier
    reason: Literal["no_eligible_crew", "no_available_crew"]


class AutoDispatchResult(Model):
    assigned: list[AutoAssigned]
    skipped: list[AutoSkipped]


class TierCounts(Model):
    P0: int
    P1: int
    P2: int
    P3: int


class CrewReport(Model):
    assigned_total: int
    completed_total: int
    open_by_tier: TierCounts
    completed_by_tier: TierCounts


class CrewActiveAssignment(Model):
    assignment_id: str
    incident_id: str
    incident_title: str
    tier: Tier
    site_id: str
    site_alias: str
    kind: AssignmentKind
    status: AssignmentStatus
    scheduled_start: datetime | None
    scheduled_end: datetime | None


class Crew(Model):
    crew_id: str
    name: str
    area_id: str
    area_alias: str
    skills: list[str]
    shift: str
    members: list[str]
    available: bool
    active_assignment: CrewActiveAssignment | None
    report: CrewReport
    profile: CrewProfileView | None = None


class AssignmentReportRow(Model):
    assignment_id: str
    incident_id: str
    incident_title: str
    tier: Tier
    site_alias: str
    area_id: str | None
    crew_name: str
    kind: AssignmentKind
    status: AssignmentStatus
    created_by: str
    created_at: datetime
    scheduled_start: datetime | None
    scheduled_end: datetime | None
    completed_at: datetime | None


class TeamsView(Model):
    crews: list[Crew]
    unassigned_incidents: int
    assignments: list[AssignmentReportRow]
    revision: int = 0


class RevenueAmounts(Model):
    energy_sales_ron: float
    export_payments_ron: float
    service_fees_ron: float
    net_revenue_ron: float


class RevenueTotals(RevenueAmounts):
    sites: int


class SegmentRevenue(RevenueTotals):
    share_of_net: float


class RevenueBySegment(Model):
    home: SegmentRevenue
    business: SegmentRevenue


class AreaRevenue(RevenueTotals):
    area_id: str
    alias: str
    business_sites: int
    business_net_revenue_ron: float


class BusinessAccount(RevenueAmounts):
    site_id: str
    alias: str
    area_id: str | None
    zone: str
    business_type: str | None
    installed_kwp: float
    monthly_import_kwh: float
    monthly_export_kwh: float
    import_price_ron_kwh: float
    export_price_ron_kwh: float
    price_source: Literal["contract", "default_tariff"]


class RevenueView(Model):
    period: Literal["monthly"]
    basis: str
    currency: Literal["RON"]
    totals: RevenueTotals
    by_segment: RevenueBySegment
    by_area: list[AreaRevenue]
    business_accounts: list[BusinessAccount]
    annualized_net_revenue_ron: float


class AreaCapacity(Model):
    area_id: str
    alias: str
    sites: int
    installed_kwp: float


class CapacityView(Model):
    areas: list[AreaCapacity]
    total_installed_kwp: float
