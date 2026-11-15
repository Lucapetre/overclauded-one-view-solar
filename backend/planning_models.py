"""API models for correlated episodes, ranking, the site-status projection and crew plans."""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from backend.models import Model
from backend.ops_models import Incident, IncidentDetail, Tier
from backend.status_models import (  # noqa: F401  (re-exported)
    Condition,
    CrewEta,
    CrewMarker,
    RouteLine,
    SitePosition,
    SiteStatus,
    StatusCounts,
    StatusProjection,
    TelemetryState,
    UnmappedSites,
    Workflow,
)

Confidence = Literal["reported", "corroborated", "suspected", "insufficient"]
Responsibility = Literal[
    "customer_installation_service",
    "distributor_network_review",
    "monitoring_provider",
    "unknown",
]
EpisodeAction = Literal[
    "monitor",
    "remote_review",
    "remote_troubleshooting",
    "field_visit",
    "external_review",
]
PlanStatus = Literal["draft", "reviewed", "applied", "superseded"]


class RankFactor(Model):
    value: Any = None
    normalized: float
    weight: float
    contribution: float
    basis: str


class ValuePerDay(Model):
    stakeholder: str
    low_ron: float
    high_ron: float
    basis: str


class RepairEstimateView(Model):
    currency: str
    low: float
    high: float
    source: str
    as_of: str


class Economics(Model):
    currency: str
    expected_lost_kwh_per_day: float | None
    lost_kwh_reason: str | None
    value_per_day: ValuePerDay | None
    value_reason: str | None
    repair_estimate: RepairEstimateView | None
    repair_reason: str | None
    parent_attribution: str | None


class OverrideView(Model):
    override_id: str
    band: Tier
    original_band: Tier
    reason: str
    created_by: str
    created_as_of: datetime
    expires_at: datetime
    revoked: bool = False


class RankExplanation(Model):
    incident_id: str
    position: int
    band: Tier
    band_label: str
    computed_band: Tier
    score: float
    factors: dict[str, RankFactor]
    unknowns: list[str]
    reason_codes: list[str]
    dominant: list[str]
    policy_version: str
    evidence_ids: list[str]
    rank_as_of: datetime
    deadline_at: datetime | None
    deadline_mandatory: bool
    overdue_minutes: float | None
    economics: Economics
    override: OverrideView | None


class EpisodeSummary(Model):
    rule_id: str
    rule_revision: int
    state: Literal["active", "resolved"]
    confidence: Confidence
    confidence_basis: str
    action: EpisodeAction
    responsibility: Responsibility
    responsibility_basis: str
    site_ids: list[str]
    asset_ids: list[str]
    parent_incident_id: str | None
    child_incident_ids: list[str]
    first_observed_at: datetime | None
    last_observed_at: datetime | None
    repeat_count: int
    revision: int
    acknowledged: bool
    resolution_kind: Literal["recovery_rule", "authorized_closure"] | None
    resolution_detail: str | None
    hold_note: str | None


class QueueItem(Model):
    incident: Incident
    episode: EpisodeSummary | None
    workflow: Workflow
    rank: RankExplanation


class QueueView(Model):
    revision: int
    rank_as_of: datetime
    policy_version: str
    policy_label: str
    items: list[QueueItem]
    remote_review_count: int
    field_count: int
    monitoring_count: int


class Hypothesis(Model):
    interpretation: str
    uncertainty: str
    alternatives: list[str]
    cannot_prove: str


class EvidenceView(Model):
    evidence_id: str
    kind: str
    source_id: str
    independent_group: str
    mirror_of: str | None
    observed_from: datetime | None
    observed_to: datetime | None
    summary: str
    added_revision: int
    added_as_of: datetime


class RankSnapshotView(Model):
    ops_revision: int
    context: str
    band: Tier
    score: float
    digest: str
    rank_as_of: datetime


class AssignmentRevisionView(Model):
    assignment_id: str
    crew_id: str
    revision: int
    status: str
    progress: str | None
    plan_id: str | None
    scheduled_start: datetime | None
    scheduled_end: datetime | None
    changed_as_of: datetime
    reason: str


class EpisodeDetail(Model):
    revision: int
    incident: IncidentDetail
    episode: EpisodeSummary | None
    hypothesis: Hypothesis | None
    metrics: dict[str, Any]
    impact: dict[str, Any]
    reason_codes: list[str]
    rule: dict[str, Any] | None
    evidence: list[EvidenceView]
    rank: RankExplanation
    rank_history: list[RankSnapshotView]
    overrides: list[OverrideView]
    assignment_history: list[AssignmentRevisionView]
    workflow: Workflow
    next_actions: list[str]
    customer_guidance: str


class OverrideRequest(Model):
    band: Tier
    reason: str = Field(min_length=5, max_length=300)
    expires_at: datetime


class CloseRequest(Model):
    reason_code: Literal[
        "repaired",
        "remote_resolved",
        "no_fault_found_documented",
        "external_handoff",
        "duplicate",
    ]
    note: str = Field(min_length=3, max_length=500)


class PlanVisit(Model):
    crew_id: str
    crew_name: str
    job_id: str
    incident_id: str
    site_id: str
    title: str
    activity: str
    sequence: int
    band: Tier
    rank_position: int
    depart_at: datetime
    arrive_at: datetime
    start_at: datetime
    finish_at: datetime
    travel_minutes: int
    service_minutes: int
    deadline_at: datetime | None
    deadline_met: bool
    constraints_checked: list[str]
    reason: str


class PlanUnassigned(Model):
    job_id: str
    incident_id: str
    site_id: str
    title: str
    band: Tier
    activity: str
    reasons: list[str]


class PlanException(Model):
    job_id: str
    incident_id: str
    band: Tier
    reason: str


class PlanMonitoring(Model):
    incident_id: str
    site_id: str
    title: str
    band: Tier
    reason: str


class PlanBaseline(Model):
    visits: list[PlanVisit]
    remote_items: list[PlanVisit]
    unassigned: list[PlanUnassigned]


class PlanComparison(Model):
    baseline_definition: str
    heuristic: dict[str, Any]
    baseline: dict[str, Any]
    findings: list[str]
    verdict: Literal["heuristic_improves", "mixed", "no_improvement"]


class PlanApproval(Model):
    created_by: str
    reviewed_by: str | None
    reviewed_at: datetime | None
    applied_by: str | None
    applied_at: datetime | None
    applied_as_of: datetime | None


class CrewPlanView(Model):
    plan_id: str
    status: PlanStatus
    ops_revision: int
    current_revision: int
    created_at: datetime
    created_as_of: datetime
    horizon_start: datetime
    horizon_end: datetime
    label: str
    method: str
    travel_source: str
    policy_version: str
    input_digest: str
    input_completeness: dict[str, Any]
    visits: list[PlanVisit]
    remote_items: list[PlanVisit]
    unassigned: list[PlanUnassigned]
    urgent_exceptions: list[PlanException]
    monitoring: list[PlanMonitoring]
    baseline: PlanBaseline
    comparison: PlanComparison
    approval: PlanApproval
    superseded_reason: str | None
    superseded_by: str | None
    redacted_items: int
    applied_assignment_ids: list[str]


class ProposeRequest(Model):
    horizon_hours: int = Field(default=12, ge=1, le=24)


class ApplyRequest(Model):
    expected_input_digest: str = Field(min_length=8, max_length=128)


class AgendaMedia(Model):
    media_id: str
    filename: str
    content_type: str
    size_bytes: int


class AgendaItem(Model):
    assignment_id: str
    crew_id: str
    crew_name: str
    incident_id: str
    title: str
    tier: Tier
    site_id: str
    site_alias: str
    activity: str | None
    kind: str
    status: str
    progress: str | None
    revision: int
    scheduled_start: datetime | None
    scheduled_end: datetime | None
    eta_arrival: datetime | None
    travel_minutes: int | None
    position: SitePosition | None
    plan_id: str | None
    # Where, why and (for a linked customer request) the video; added for the technician agenda.
    zone: str | None = None
    reason: str | None = None
    window_label: str | None = None
    support_request_id: str | None = None
    media: AgendaMedia | None = None


class DeferredItem(Model):
    plan_id: str
    crew_id: str
    incident_id: str
    activity: str
    start_at: datetime
    reason: str


class AgendaView(Model):
    as_of: datetime
    crews: list[str]
    items: list[AgendaItem]
    deferred: list[DeferredItem]
    eta_label: str
    # Recently completed work (last 72 h), newest first.
    history: list[AgendaItem] = []


class ProgressRequest(Model):
    state: Literal["en_route", "on_site", "done"]
    expected_revision: int = Field(ge=1)
    outcome: (
        Literal["resolved", "field_visit_needed", "further_evidence_needed"] | None
    ) = None
    note: str | None = Field(default=None, max_length=500)


class CorrelationRunView(Model):
    run_id: str
    as_of: datetime
    revision: int
    opened: int
    updated: int
    recovered: int
    held: int
    not_evaluated: int
