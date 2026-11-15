"""Site-status projection, crew marker and route models (shared by ops and planning)."""

from datetime import datetime
from typing import Literal

from backend.models import Model

Tier = Literal["P0", "P1", "P2", "P3"]

Workflow = Literal[
    "needs_review",
    "monitoring",
    "remote_triage",
    "field_action_needed",
    "proposed",
    "assigned",
    "en_route",
    "on_site",
    "resolved",
    "none",
]

Condition = Literal[
    "observed_active",
    "suspected",
    "no_active_issue_under_evaluated_rules",
    "not_evaluated",
]

TelemetryState = Literal["fresh", "partial", "stale", "missing", "access_error"]


class SitePosition(Model):
    latitude: float
    longitude: float
    fictional: bool
    label: str | None


class TelemetrySource(Model):
    source: str
    status: str
    last_observed_at: datetime | None = None
    age_seconds: float | None = None


class AccessError(Model):
    source: str
    failure_class: str
    last_at: datetime
    count: int


class TelemetryView(Model):
    state: TelemetryState
    coverage: float
    sources: list[TelemetrySource]
    access_errors: list[AccessError]
    unsupported_capabilities: list[str]


class NotEvaluated(Model):
    rule_id: str
    reason_codes: list[str]


class CrewEta(Model):
    crew_id: str | None
    crew_name: str | None
    status: str | None
    progress: str | None
    eta: datetime | None
    eta_label: str


class SiteStatus(Model):
    site_id: str
    alias: str
    area_id: str | None
    area_alias: str | None
    population: Literal["compact", "provider_scenario"]
    position: SitePosition | None
    segment: str | None
    installed_kwp: float | None
    condition: Condition
    condition_note: str | None
    telemetry: TelemetryView
    workflow: Workflow
    highest_priority: Tier | None
    attention: str
    badges: list[str]
    episode_ids: list[str]
    resolved_episode_ids: list[str]
    parent_episode_ids: list[str]
    affected_assets: list[str]
    evaluated_rules: list[str]
    not_evaluated_rules: list[NotEvaluated]
    crew: CrewEta | None


class StatusCounts(Model):
    sites: int
    mapped_sites: int
    unmapped_sites: int
    affected_sites: int
    unique_episodes: int
    episodes_by_band: dict[str, int]
    affected_sites_by_band: dict[str, int]
    sites_by_workflow: dict[str, int]
    sites_by_telemetry: dict[str, int]
    sites_by_condition: dict[str, int]


class CrewMarker(Model):
    crew_id: str
    name: str
    kind: Literal["field", "remote_desk"]
    position: SitePosition | None
    location_reported_at: datetime | None
    location_basis: str


class RouteStop(Model):
    sequence: int
    incident_id: str
    site_id: str
    position: SitePosition | None
    start_at: datetime
    finish_at: datetime


class RouteLine(Model):
    crew_id: str
    plan_id: str | None
    state: Literal["proposed", "applied"]
    stops: list[RouteStop]
    redacted_stops: int
    label: str


class StatusProjection(Model):
    revision: int
    status_as_of: datetime
    sites: list[SiteStatus]
    unmapped: list[SiteStatus]
    counts: StatusCounts
    note: str


class UnmappedSites(Model):
    revision: int
    status_as_of: datetime
    count: int
    sites: list[SiteStatus]


class CrewProfileView(Model):
    kind: Literal["field", "remote_desk"]
    organisation: str
    authorised_services: list[str]
    qualifications: list[str]
    tools: list[str]
    areas: list[str]
    base: SitePosition | None
    location_reported_at: datetime | None
    location_basis: str
    shift_start: datetime | None
    shift_end: datetime | None
    label: str
