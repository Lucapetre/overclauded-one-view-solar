from datetime import datetime
from typing import Literal

from backend.models import Model

Family = Literal["meter", "battery", "weather"]


class CapabilityDecision(Model):
    """A feature decision (not a raw declaration): may this evidence drive the feature now?"""

    capability: Literal[
        "grid_energy_verified",
        "battery_assisted_planning",
        "irradiance_explanation",
        "pv_performance_review",
    ]
    available: bool
    reason_codes: list[str]
    evidence_ids: list[str]


class EquipmentAsset(Model):
    asset_id: str
    profile_id: str
    role: str
    boundary: str | None
    mounting: str | None
    shared_resource: bool
    link_basis: str | None
    # Irradiance sensors: is the sensor plane the site's module plane (one shared check)?
    plane_match: (
        Literal["module_plane", "differs_from_module_plane", "unknown"] | None
    ) = None


class EquipmentValue(Model):
    metric: str
    channel: str | None
    value: float | None
    unit: str
    observed_at: datetime | None
    frame_start: datetime
    frame_end: datetime
    aggregation: str
    origin: str
    coverage_ratio: float
    evidence_id: str


class Freshness(Model):
    status: Literal["fresh", "stale", "missing"]
    last_observed_at: datetime | None
    age_seconds: float | None
    stale_after_seconds: int


class EquipmentFamily(Model):
    family: Family
    availability: Literal["available", "declared_not_observed", "not_installed"]
    selected_source: str | None
    assets: list[EquipmentAsset]
    latest: list[EquipmentValue]
    freshness: Freshness
    declared_capabilities: dict[str, str]
    notes: list[str]


class EquipmentSummary(Model):
    site_id: str
    as_of: datetime
    clock_mode: Literal["live", "scenario"]
    source_mode: Literal["synthetic", "replay", "none"]
    scenario_version: str | None
    import_id: str | None
    families: list[EquipmentFamily]
    capabilities: list[CapabilityDecision]
    label: str


class EvidenceItem(Model):
    evidence_id: str
    asset_id: str | None
    family: str | None
    endpoint_key: str
    metric: str
    channel: str | None
    boundary: str | None
    mounting: str | None
    aggregation: str
    basis: str | None
    frame_start: datetime
    frame_end: datetime
    value: float | None
    unit: str
    coverage_ratio: float
    value_origin: str | None
    frame_status: str | None


class EquipmentEvidence(Model):
    site_id: str
    family: Family | None
    as_of: datetime
    total: int
    limit: int
    offset: int
    items: list[EvidenceItem]
