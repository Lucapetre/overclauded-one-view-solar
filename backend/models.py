from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")]
Flag = Annotated[str, Field(max_length=128)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Metric(StrEnum):
    pv = "pv_power"
    load = "home_load"
    grid_import = "grid_import"
    grid_export = "grid_export"
    battery_charge = "battery_charge"
    battery_discharge = "battery_discharge"
    soc = "battery_soc"
    voltage = "voltage"
    temperature = "temperature"


UNITS = {metric: "kW" for metric in Metric}
UNITS.update({Metric.soc: "%", Metric.voltage: "V", Metric.temperature: "degC"})
Requirement = Literal["mandatory", "optional"]
SourceMode = Literal["live", "replay", "synthetic"]


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timezone-aware ISO 8601 timestamps are required")
    return value.astimezone(UTC)


class Measurement(Model):
    value: float | None
    unit: Literal["kW", "%", "V", "degC"]
    requirement: Requirement
    availability: Literal["available", "missing", "unsupported", "invalid"] = (
        "available"
    )
    origin: Literal["measured", "derived"] = "measured"
    boundary: Literal["ac", "dc", "not_applicable"]
    quality_flags: list[Flag] = Field(default_factory=list)

    @field_validator("value", mode="before")
    @classmethod
    def numeric_value(cls, value):
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, (int, float))
        ):
            raise ValueError("Measurement values must be JSON numbers or null")
        return value

    @model_validator(mode="after")
    def check_availability(self):
        if (self.availability == "available") != (self.value is not None):
            raise ValueError("Only available measurements have a numeric value")
        return self


class TelemetryRecord(Model):
    schema_version: Literal["1.0"]
    record_id: Identifier
    site_id: Identifier
    device_id: Identifier
    source_id: Identifier
    interval_start: datetime
    interval_end: datetime
    received_at: datetime
    source_mode: SourceMode
    raw_record_ref: Annotated[str, Field(min_length=1, max_length=512)]
    measurements: dict[Metric, Measurement] = Field(max_length=len(Metric))
    quality_flags: list[Flag] = Field(default_factory=list)
    vendor_codes: list[Annotated[str, Field(max_length=128)]] = Field(
        default_factory=list, max_length=32
    )

    @field_validator("interval_start", "interval_end", "received_at", mode="before")
    @classmethod
    def timestamps(cls, value):
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if not isinstance(value, datetime):
            raise ValueError("Timestamps must be timezone-aware ISO 8601 strings")
        return utc(value)

    @model_validator(mode="after")
    def check_record(self):
        duration = (self.interval_end - self.interval_start).total_seconds()
        if not 0 < duration <= 172800:
            raise ValueError(
                "Measurement intervals must be positive and at most 48 elapsed hours"
            )
        if self.received_at < self.interval_end:
            raise ValueError("received_at must not precede interval_end")
        for metric, reading in self.measurements.items():
            if reading.unit != UNITS[metric]:
                raise ValueError(
                    f"{metric.value} requires standardized unit {UNITS[metric]}"
                )
            if reading.value is None:
                continue
            if metric == Metric.temperature:
                if not -80 <= reading.value <= 200:
                    raise ValueError(
                        "Temperature outside the demo input validation range"
                    )
            elif reading.value < 0:
                raise ValueError(f"{metric.value} must be nonnegative")
            if metric == Metric.soc and reading.value > 100:
                raise ValueError("Battery state of charge must be between 0 and 100")
            if metric == Metric.voltage and reading.value > 1000:
                raise ValueError("Voltage outside the demo input validation range")
            if reading.unit == "kW" and reading.boundary == "not_applicable":
                raise ValueError(
                    "Power readings require an AC or DC measurement boundary"
                )
        return self


class Site(Model):
    site_id: Identifier
    alias: Annotated[str, Field(min_length=1, max_length=128)]
    area_id: Identifier | None
    topology_mode: Literal["simulated", "authorized", "unknown"]
    reporting_interval_seconds: Annotated[int, Field(gt=0, le=86400)]
    stale_after_seconds: Annotated[int, Field(gt=0)]
    capabilities: list[Metric] = Field(max_length=len(Metric))
    measurement_requirements: dict[Metric, Requirement]

    @model_validator(mode="after")
    def check_capabilities(self):
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("Site capabilities must be unique")
        if set(self.capabilities) != set(self.measurement_requirements):
            raise ValueError(
                "Every supported measurement needs exactly one requirement classification"
            )
        if self.stale_after_seconds < self.reporting_interval_seconds:
            raise ValueError(
                "Freshness allowance cannot be shorter than the reporting interval"
            )
        return self


class User(Model):
    user_id: str
    username: str
    role: Literal["customer", "dispatcher", "technician", "supervisor"]
    account_type: Literal["home", "business"] = "home"


class SessionView(Model):
    user: User
    csrf_token: str
    expires_at: datetime


class Login(Model):
    username: Annotated[str, Field(min_length=1, max_length=96)]
    password: Annotated[str, Field(min_length=1, max_length=256)]


class ErrorEnvelope(Model):
    code: str
    message: str
    request_id: str


class Freshness(Model):
    status: Literal["fresh", "stale", "future", "unavailable", "unknown_clock"]
    age_seconds: float | None
    clock: Literal["wall", "replay", "unconfigured"]
    evaluated_at: datetime | None


class PublicProvenance(Model):
    source_mode: SourceMode
    source_id: str
    source_date: str


class EnergySnapshot(Model):
    site_id: str
    display_timezone: Literal["Europe/Bucharest"] = "Europe/Bucharest"
    interval_start: datetime | None
    interval_end: datetime | None
    received_at: datetime | None
    freshness: Freshness
    provenance: PublicProvenance | None
    measurements: dict[Metric, Measurement]
    quality_flags: list[str]
    vendor_codes: list[str]


class HistoryPoint(Model):
    interval_start: datetime
    interval_end: datetime
    measurements: dict[Metric, Measurement]
    coverage: dict[Metric, float]
    energy_kwh: dict[Metric, float | None]
    source_modes: list[SourceMode]
    quality_flags: list[str]
    sample_count: int
    source_interval_seconds: list[float]


class EnergyHistory(Model):
    site_id: str
    display_timezone: Literal["Europe/Bucharest"] = "Europe/Bucharest"
    start: datetime
    end: datetime
    resolution: Literal["raw", "15m", "1h", "1d"]
    points: list[HistoryPoint]


class Area(Model):
    area_id: Identifier
    alias: Annotated[str, Field(min_length=1, max_length=128)]
    topology_mode: Literal["simulated", "authorized", "unknown"]


class SiteRegistration(Model):
    site: Site
    device_id: Identifier
    source_id: Identifier
    area: Area | None = None

    @model_validator(mode="after")
    def check_area(self):
        if self.area and self.site.area_id != self.area.area_id:
            raise ValueError("Site and area identifiers must match")
        return self


class AreaSummary(Model):
    area: Area
    monitored_sites: int
    recent_sites: int
    stale_sites: int
    unavailable_sites: int
    unassessed_sites: int
    incident_status: Literal["not_evaluated"] = "not_evaluated"
    sites: list[EnergySnapshot]


class IngestResult(Model):
    record_id: str
    status: Literal["accepted", "duplicate"]
    quality_flags: list[str]
