from datetime import datetime, timedelta
from typing import Annotated, Literal

from pydantic import Field, model_validator

from backend.models import Model

TaskKind = Literal[
    "laundry_batch", "dishwasher", "ev_charging", "water_heating", "pool_pump", "other"
]
TaskStatus = Literal["suggested", "accepted", "running", "completed", "cancelled"]
Text = Annotated[str, Field(min_length=1, max_length=80)]


def _aware(value: datetime | None, name: str):
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{name} must be a timezone-aware ISO 8601 time")


class TaskCreate(Model):
    """A flexible, non-interruptible task: it draws `power_kw` for energy/power hours."""

    label: Text
    kind: TaskKind = "other"
    power_kw: Annotated[float, Field(gt=0, le=50)]
    energy_kwh: Annotated[float, Field(gt=0, le=200)]
    earliest_start: datetime
    # The run must finish by the deadline.
    deadline: datetime
    latest_start: datetime | None = None
    # Optional local daily window the whole run must fit (minutes after local midnight;
    # end <= start crosses midnight).
    allowed_start_minute: Annotated[int, Field(ge=0, le=1439)] | None = None
    allowed_end_minute: Annotated[int, Field(ge=1, le=1440)] | None = None
    # The customer's usual time, used as the baseline; default baseline is "run now".
    usual_start: datetime | None = None
    # Optional site import limit at the connection point (kW), checked per interval.
    site_import_limit_kw: Annotated[float, Field(gt=0, le=1000)] | None = None
    assumption_note: Annotated[str, Field(max_length=200)] | None = None

    @model_validator(mode="after")
    def check(self):
        for name in ("earliest_start", "deadline", "latest_start", "usual_start"):
            _aware(getattr(self, name), name)
        duration = timedelta(hours=self.energy_kwh / self.power_kw)
        if duration > timedelta(hours=24):
            raise ValueError("A task may run for at most 24 hours")
        if duration < timedelta(minutes=1):
            raise ValueError("A task must run for at least one minute")
        if self.deadline - self.earliest_start > timedelta(hours=48):
            raise ValueError("Plan within at most 48 hours from the earliest start")
        if self.earliest_start + duration > self.deadline:
            raise ValueError("The run does not fit between earliest start and deadline")
        if self.latest_start is not None and not (
            self.earliest_start <= self.latest_start <= self.deadline
        ):
            raise ValueError(
                "latest_start must lie between earliest start and deadline"
            )
        if (self.allowed_start_minute is None) != (self.allowed_end_minute is None):
            raise ValueError("Give both allowed_start_minute and allowed_end_minute")
        return self


class TaskUpdate(TaskCreate):
    expected_revision: Annotated[int, Field(ge=1)]


class Commitment(Model):
    commitment_id: str
    task_revision: int
    start: datetime
    end: datetime
    # Analytical (event) time and real receipt time of the acceptance.
    accepted_at: datetime
    accepted_received_at: datetime
    recommendation_revision: str
    contract_version_id: str | None
    estimated_cost_ron: float | None
    baseline_cost_ron: float | None
    estimated_difference_ron: float | None
    # The baseline the accepted plan was compared with (run now or the usual start).
    baseline_kind: Literal["usual_time", "run_now"] | None = None
    baseline_start: datetime | None = None
    released_at: datetime | None = None
    release_reason: str | None = None


class Task(Model):
    task_id: str
    site_id: str
    label: str
    kind: TaskKind
    power_kw: float
    energy_kwh: float
    duration_minutes: float
    non_interruptible: Literal[True] = True
    earliest_start: datetime
    deadline: datetime
    latest_start: datetime | None
    allowed_start_minute: int | None
    allowed_end_minute: int | None
    usual_start: datetime | None
    site_import_limit_kw: float | None
    assumption_note: str | None
    # suggested -> accepted -> running -> completed follow the analytical clock.
    status: TaskStatus
    revision: int
    created_at: datetime
    commitment: Commitment | None


class AcceptTask(Model):
    # The revision of the recommendation the customer saw; a changed one is rejected.
    recommendation_revision: Annotated[str, Field(min_length=8, max_length=64)]
    # Defaults to the recommended start; any feasible candidate start may be chosen.
    start: datetime | None = None


class ReviewTask(Model):
    """Explicit review of an accepted commitment: release it so the task can be replanned."""

    action: Literal["release"]
    reason: Annotated[str, Field(min_length=1, max_length=200)]


class PlanInterval(Model):
    start: datetime
    end: datetime
    task_kw: float
    pv_forecast_kw: float | None
    base_load_kw: float | None
    # Battery AC power at the site boundary: + discharge, - charge. None = not used.
    battery_kw: float | None
    grid_import_kwh: float | None
    grid_export_kwh: float | None
    import_rate_ron_kwh: float | None
    export_value_ron_kwh: float | None
    band_id: str | None
    contract_version_id: str | None
    incremental_cost_ron: float | None
    price_gap_reason: str | None = None


class CostRange(Model):
    low_ron: float
    high_ron: float
    basis: str


class PlanCandidate(Model):
    start: datetime
    end: datetime
    feasible: bool
    estimated_cost_ron: float | None
    cost_range: CostRange | None
    violated_constraints: list[str]
    reason_codes: list[str]


class BatteryContribution(Model):
    available: bool
    used: bool
    reason_codes: list[str]
    soc_pct: float | None = None
    soc_as_of: datetime | None = None
    usable_capacity_kwh: float | None = None
    reserve_pct: float | None = None
    charge_limit_kw: float | None = None
    discharge_limit_kw: float | None = None
    charge_efficiency: float | None = None
    discharge_efficiency: float | None = None
    terminal_value_ron_per_stored_kwh: float | None = None
    terminal_energy_change_kwh: float | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class ForecastInfo(Model):
    issue_time: datetime
    pv_method: str
    load_method: str
    clearness_base: float | None
    clearness_recent: float | None
    recent_source: str | None
    location_basis: str
    plane_basis: str
    label: Literal["estimated"] = "estimated"


class InputCoverage(Model):
    pv_forecast: float
    base_load: float
    prices: float


class SourceFreshness(Model):
    source: str
    status: Literal["fresh", "stale", "missing", "not_applicable"]
    last_observed_at: datetime | None
    age_seconds: float | None


class PlanDecision(Model):
    site_id: str
    task_id: str
    task_revision: int
    decided_at: datetime
    clock_mode: Literal["live", "scenario"]
    status: Literal["recommended", "cost_unknown", "no_feasible_start"]
    recommendation_revision: str
    recommended_start: datetime | None
    recommended_end: datetime | None
    # Incremental site cost of running the task (with task minus without), RON, estimated.
    estimated_cost_ron: float | None
    baseline_start: datetime
    baseline_kind: Literal["usual_time", "run_now"]
    baseline_cost_ron: float | None
    # estimated_cost - baseline_cost (negative = estimated saving).
    estimated_difference_ron: float | None
    cost_range: CostRange | None
    cost_label: Literal["estimated"] = "estimated"
    currency: Literal["RON"] = "RON"
    interval_plan: list[PlanInterval]
    binding_constraints: list[str]
    constraints_applied: list[str]
    contract_version_id: str | None
    contract_version_ids: list[str]
    export_compensation: str | None
    horizon_start: datetime
    horizon_end: datetime
    forecast: ForecastInfo
    battery: BatteryContribution
    input_coverage: InputCoverage
    freshness: list[SourceFreshness]
    evidence_ids: list[str]
    reason_codes: list[str]
    candidates: list[PlanCandidate]
    commitment: Commitment | None
    review_suggested: bool
    source_mode: Literal["synthetic", "live"]


class MeasuredWindow(Model):
    grid_import_kwh: float | None
    grid_export_kwh: float | None
    import_coverage: float
    export_coverage: float
    source: str
    boundary: str | None
    evidence_ids: list[str]


class TaskProgress(Model):
    task_id: str
    site_id: str
    status: TaskStatus
    as_of: datetime
    window_start: datetime
    window_end: datetime
    measured: MeasuredWindow
    # Measured grid energy of the whole site over the elapsed window, priced with the
    # contract bands (None when coverage or prices are incomplete).
    measured_site_cost_ron: float | None
    # The accepted plan's estimated whole-site grid cost for the same elapsed slots.
    estimated_site_cost_ron: float | None
    comparison_label: Literal["estimated"] = "estimated"
    attribution_note: str
    reason_codes: list[str]


class ClockView(Model):
    mode: Literal["live", "scenario"]
    analytical_now: datetime
    wall_now: datetime
    scenario_id: str | None
    run_id: str | None
    scenario_started_at: datetime | None
    synthetic: bool
