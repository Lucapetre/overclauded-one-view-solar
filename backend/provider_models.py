from datetime import datetime
from typing import Literal

from pydantic import Field

from backend.models import Model


class ProviderSite(Model):
    site_id: str
    site_key: str
    provider: str
    account_id: str
    native_site_id: str
    display_name: str
    provider_profile_id: str
    capabilities: dict[str, str]
    source_mode: Literal["synthetic", "replay"]
    as_of_utc: datetime


class ProviderObservation(Model):
    obs_id: int
    provider: str
    account_id: str
    site_id: str
    device_id: str | None
    endpoint_key: str
    provider_profile_id: str
    provider_profile_version: str
    mapping_version: str
    profile_variant: str | None
    entity_scope: str
    channel: str | None
    source_time_role: str
    measurement_time_utc: datetime | None
    response_time_utc: datetime | None
    capture_time_utc: datetime | None
    received_at_utc: datetime | None
    effective_time_utc: datetime
    effective_time_basis: str
    metric_name: str
    metric_kind: str
    canonical_value: float | None
    canonical_text: str | None
    canonical_unit: str
    boundary: str | None
    value_origin: str
    availability_status: str
    quality_flags: str | None
    is_conflicted: int
    assumption_basis: str | None
    requirement_class: Literal[
        "integration_required", "vendor_response_required", "optional"
    ]
    field_rule_id: str
    record_status: str | None


class ProviderFrame(Model):
    provider: str
    account_id: str
    site_id: str
    site_key: str
    endpoint_key: str
    device_id: str | None
    channel: str | None
    metric_name: str
    aggregation: str
    frame_start_utc: datetime
    frame_end_utc: datetime
    frame_start_local: datetime
    value: float | None
    unit: str
    n_obs: int = Field(ge=0)
    original_cadence_s: float | None = Field(default=None, ge=0)
    coverage_ratio: float = Field(ge=0)
    value_origin: str
    frame_status: str


class ProviderSourceHealth(Model):
    endpoint_key: str
    device_key: str
    cadence_s: int | None
    latest_source_ms: int | None
    latest_received_ms: int | None
    latest_source_age_s: float | None
    stale_threshold_s: float | None
    freshness_status: str
    access_status: str
    notes: str | None


class ProviderLatest(Model):
    site: ProviderSite
    frames: list[ProviderFrame]
    source_health: list[ProviderSourceHealth]
    display_timezone: Literal["Europe/Bucharest"] = "Europe/Bucharest"


class ProviderObservations(Model):
    site: ProviderSite
    total: int
    limit: int
    offset: int
    items: list[ProviderObservation]


class ProviderFrames(Model):
    site: ProviderSite
    total: int
    limit: int
    offset: int
    items: list[ProviderFrame]
