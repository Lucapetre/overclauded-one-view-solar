"""Backend business task planner.

This is the backend port and generalization of the browser demo's `recommend()`
(`frontend/src/domain.js`): a task with energy and power, an allowed window, a deadline and
an accepted-plan state. Constants of the demo (fixed PV shape, flat prices, half-hour steps)
are replaced by contract time bands, a decision-time forecast and equipment constraints.

For every feasible 15-minute start of a contiguous (non-interruptible) run:

    site_cost = sum(import_kwh x band import rate - export_kwh x band export value)
                - terminal stored battery energy x discharge efficiency x terminal import rate
    incremental cost = site_cost(with task) - site_cost(without task)

on one common horizon, with the same forecast, initial battery state and constraints. Running
on solar therefore costs the export value it displaces, and battery energy is never free:
energy drawn from storage lowers the terminal state, valued at what it would displace. A
battery only participates when the bridge reports battery-assisted planning as available.
Unknown inputs give a null cost with reasons (or explicit tariff bounds), never zero.
"""

import hashlib
import json
import math
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from backend import bridge, solar_forecast, tariff
from backend.clock import clock_state
from backend.customer import require_customer
from backend.db import stamp
from backend.errors import ApiError
from backend.models import Metric, User
from backend.planner_models import (
    AcceptTask,
    BatteryContribution,
    Commitment,
    CostRange,
    ForecastInfo,
    InputCoverage,
    MeasuredWindow,
    PlanCandidate,
    PlanDecision,
    PlanInterval,
    ReviewTask,
    SourceFreshness,
    Task,
    TaskCreate,
    TaskProgress,
    TaskUpdate,
)
from backend.security import authorized_site

SLOT = timedelta(minutes=15)
EPS = 1e-9
MAX_TASKS = 50
MAX_CANDIDATES = 192
ATTRIBUTION_NOTE = (
    "The connection-point (PCC) meter measures the whole site, not the appliance alone. "
    "Measured energy includes the base load and solar production in the same window; the "
    "comparison with the plan is an estimate, and one observed run cannot prove what the "
    "other start time would have cost."
)
DEFAULT_TARIFF_VERSION = "default-tariff"


# ---------------------------------------------------------------- pure planning core


@dataclass(frozen=True)
class BatteryParams:
    usable_kwh: float
    soc_pct: float
    reserve_pct: float
    charge_limit_kw: float
    discharge_limit_kw: float
    charge_efficiency: float
    discharge_efficiency: float
    as_of: datetime | None = None
    evidence_ids: tuple[str, ...] = ()


@dataclass
class SlotInput:
    start: datetime
    end: datetime
    pv_kw: float | None
    base_kw: float | None
    import_rate: float | None
    export_value: float | None
    band_id: str | None = None
    version_id: str | None = None
    gap_reason: str | None = None

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600


@dataclass
class TaskSpec:
    power_kw: float
    energy_kwh: float
    earliest_start: datetime
    deadline: datetime
    latest_start: datetime | None = None
    allowed_window: tuple[int, int] | None = None
    usual_start: datetime | None = None
    import_limit_kw: float | None = None

    @property
    def duration(self) -> timedelta:
        return timedelta(hours=self.energy_kwh / self.power_kw)


@dataclass
class Simulation:
    import_kwh: list[float | None]
    export_kwh: list[float | None]
    battery_kw: list[float | None]
    stored_kwh: float | None


@dataclass
class Evaluation:
    start: datetime
    end: datetime
    cost: float | None
    low: float | None
    high: float | None
    violated: list[str]
    reasons: list[str]
    simulation: Simulation | None = None
    profile: list[float] = field(default_factory=list)
    slot_costs: list[float | None] = field(default_factory=list)
    terminal_change_kwh: float | None = None


def ceil_slot(moment: datetime) -> datetime:
    seconds = moment.astimezone(UTC).timestamp()
    return datetime.fromtimestamp(math.ceil(seconds / 900 - 1e-9) * 900, UTC)


def floor_slot(moment: datetime) -> datetime:
    seconds = moment.astimezone(UTC).timestamp()
    return datetime.fromtimestamp(math.floor(seconds / 900 + 1e-9) * 900, UTC)


def task_profile(
    slots: list[SlotInput], start: datetime, spec: TaskSpec
) -> list[float]:
    """Average task kW per slot for one contiguous run starting at `start`."""
    end = start + spec.duration
    profile = []
    for slot in slots:
        overlap = (min(end, slot.end) - max(start, slot.start)).total_seconds()
        span = (slot.end - slot.start).total_seconds()
        profile.append(spec.power_kw * overlap / span if overlap > 0 else 0.0)
    return profile


def simulate(
    slots: list[SlotInput], extra_kw: list[float], battery: BatteryParams | None
) -> Simulation:
    """Grid flows per slot under a deterministic self-consumption battery policy.

    The battery (if any) charges only from solar surplus and discharges only to cover site
    demand, within reserve, usable capacity, power limits and efficiencies. It never
    exports from storage and never charges from the grid.
    """
    imports: list[float | None] = []
    exports: list[float | None] = []
    power: list[float | None] = []
    stored = None
    if battery:
        stored = battery.usable_kwh * battery.soc_pct / 100
        floor = battery.usable_kwh * battery.reserve_pct / 100
        ceiling = battery.usable_kwh
    for slot, extra in zip(slots, extra_kw, strict=True):
        if slot.pv_kw is None or slot.base_kw is None:
            imports.append(None)
            exports.append(None)
            power.append(None)
            if battery:
                stored = None
                battery = None  # state unknown from here on
            continue
        hours = slot.hours
        net = slot.base_kw + extra - slot.pv_kw
        flow = 0.0
        if battery and stored is not None:
            if net < 0:
                room = max(0.0, ceiling - stored) / (battery.charge_efficiency * hours)
                charge = min(-net, battery.charge_limit_kw, room)
                stored += charge * battery.charge_efficiency * hours
                flow = -charge
                net += charge
            elif net > 0:
                available = (
                    max(0.0, stored - floor) * battery.discharge_efficiency / hours
                )
                discharge = min(net, battery.discharge_limit_kw, available)
                stored -= discharge * hours / battery.discharge_efficiency
                flow = discharge
                net -= discharge
        imports.append(max(net, 0.0) * hours)
        exports.append(max(-net, 0.0) * hours)
        power.append(flow if battery else None)
    return Simulation(imports, exports, power, stored)


def _terminal_rate(slots: list[SlotInput]) -> float | None:
    for slot in reversed(slots):
        if slot.import_rate is not None:
            return slot.import_rate
    return None


def evaluate(
    slots: list[SlotInput],
    spec: TaskSpec,
    start: datetime,
    baseline: Simulation,
    battery: BatteryParams | None,
) -> Evaluation:
    """Incremental site cost of one start, plus the constraints it violates."""
    end = start + spec.duration
    violated = []
    reasons = []
    if start < spec.earliest_start:
        violated.append("earliest_start")
    if end > spec.deadline:
        violated.append("deadline")
    if spec.latest_start is not None and start > spec.latest_start:
        violated.append("latest_start")
    if spec.allowed_window and not within_window(start, end, spec.allowed_window):
        violated.append("allowed_window")
    profile = task_profile(slots, start, spec)
    simulation = simulate(slots, profile, battery)
    first = next(i for i, kw in enumerate(profile) if kw > 0)
    differing = {
        i
        for i in range(len(slots))
        if profile[i] > 0 or (battery is not None and i >= first)
    }
    cost = 0.0
    low = high = 0.0
    exact = True
    bounded = True
    slot_costs: list[float | None] = []
    for i in range(len(slots)):
        if i not in differing:
            slot_costs.append(0.0)
            continue
        slot = slots[i]
        with_import, with_export = simulation.import_kwh[i], simulation.export_kwh[i]
        base_import, base_export = baseline.import_kwh[i], baseline.export_kwh[i]
        task_kwh = profile[i] * slot.hours
        if None in (with_import, with_export, base_import, base_export):
            exact = False
            slot_costs.append(None)
            if slot.import_rate is None or slot.export_value is None:
                bounded = False
                continue
            # Unknown solar/base load: the task kWh is supplied either by extra import
            # or by displaced export (at most the forecast solar energy, when known), so
            # its cost lies between those two valuations.
            displaced = task_kwh
            if slot.pv_kw is not None:
                displaced = min(task_kwh, max(0.0, slot.pv_kw) * slot.hours)
            values = (
                task_kwh * slot.import_rate,
                displaced * slot.export_value
                + (task_kwh - displaced) * slot.import_rate,
            )
            low += min(values)
            high += max(values)
            continue
        delta_import = with_import - base_import
        delta_export = with_export - base_export
        if abs(delta_import) < EPS and abs(delta_export) < EPS:
            slot_costs.append(0.0)
            continue
        if slot.import_rate is None or slot.export_value is None:
            exact = bounded = False
            slot_costs.append(None)
            reasons.append("price_gap_in_run")
            continue
        value = delta_import * slot.import_rate - delta_export * slot.export_value
        cost += value
        low += value
        high += value
        slot_costs.append(value)
        if (
            spec.import_limit_kw is not None
            and with_import / slot.hours > spec.import_limit_kw + EPS
            and with_import > base_import + EPS
        ):
            if "site_import_limit" not in violated:
                violated.append("site_import_limit")
    terminal_change = None
    if battery is not None:
        rate = _terminal_rate(slots)
        if simulation.stored_kwh is None or baseline.stored_kwh is None or rate is None:
            exact = bounded = False
            reasons.append("battery_terminal_state_unknown")
        else:
            terminal_change = simulation.stored_kwh - baseline.stored_kwh
            terminal = terminal_change * battery.discharge_efficiency * rate
            cost -= terminal
            low -= terminal
            high -= terminal
    if spec.import_limit_kw is not None and not exact:
        if spec.power_kw > spec.import_limit_kw + EPS:
            if "site_import_limit" not in violated:
                violated.append("site_import_limit")
        reasons.append("import_limit_checked_against_task_power_only")
    if not exact and bounded:
        reasons.append("cost_bounded_by_tariff_unknown_solar_or_load")
    if not bounded:
        reasons.append("price_coverage_missing")
    return Evaluation(
        start,
        end,
        round(cost, 6) if exact else None,
        round(low, 6) if bounded else None,
        round(high, 6) if bounded else None,
        violated,
        sorted(set(reasons)),
        simulation,
        profile,
        slot_costs,
        terminal_change,
    )


def within_window(start: datetime, end: datetime, window: tuple[int, int]) -> bool:
    """True when [start, end) lies inside one local occurrence of the daily window."""
    begin, finish = window
    local_day = start.astimezone(tariff.LOCAL).date()
    for day in (local_day - timedelta(days=1), local_day):
        lower = tariff.local_to_utc(day, begin)
        upper = (
            tariff.local_to_utc(day + timedelta(days=1), finish)
            if finish <= begin
            else tariff.local_to_utc(day, finish)
        )
        if lower <= start and end <= upper:
            return True
    return False


@dataclass
class CoreResult:
    status: str
    selected: Evaluation | None
    baseline: Evaluation | None
    baseline_kind: str
    feasible: list[Evaluation]
    binding: list[str]
    reasons: list[str]
    battery_used: bool
    horizon_start: datetime
    horizon_end: datetime


def horizon(now: datetime, spec: TaskSpec) -> tuple[datetime, datetime]:
    start = ceil_slot(now)
    usual_end = (
        floor_slot(spec.usual_start) + spec.duration if spec.usual_start else start
    )
    end = ceil_slot(
        max(spec.deadline + spec.duration, usual_end, start + spec.duration)
    )
    return start, min(end, start + timedelta(hours=96))


def optimize(
    slots: list[SlotInput],
    spec: TaskSpec,
    battery: BatteryParams | None,
) -> CoreResult:
    """Choose the cheapest feasible start; ties go to the earliest start."""
    reasons = []
    h_start, h_end = slots[0].start, slots[-1].end
    if battery is not None and any(s.pv_kw is None or s.base_kw is None for s in slots):
        battery = None
        reasons.append("battery_needs_complete_forecast")
    baseline_sim = simulate(slots, [0.0] * len(slots), battery)
    duration = spec.duration
    grid = []
    cursor = h_start
    while cursor + duration <= h_end + timedelta(seconds=1):
        grid.append(cursor)
        cursor += SLOT
    evaluations = [evaluate(slots, spec, s, baseline_sim, battery) for s in grid]
    feasible = [e for e in evaluations if not e.violated]
    known = [e for e in feasible if e.cost is not None]
    status = "recommended"
    selected = None
    if not feasible:
        status = "no_feasible_start"
        reasons.append("no_start_satisfies_constraints")
    elif known:
        selected = min(known, key=lambda e: (round(e.cost, 6), e.start))
    else:
        status = "cost_unknown"
        bounded = [e for e in feasible if e.high is not None]
        if bounded:
            selected = min(
                bounded, key=lambda e: (round(e.high, 6), round(e.low, 6), e.start)
            )
            reasons.append("ranked_by_cost_bounds")
        else:
            reasons.append("price_coverage_missing")
    # Baseline: the usual time if still ahead, else "run now" (first feasible start).
    baseline_kind = "run_now"
    baseline_start = feasible[0].start if feasible else (grid[0] if grid else h_start)
    if spec.usual_start is not None:
        usual = floor_slot(spec.usual_start)
        if usual >= h_start and usual + duration <= h_end + timedelta(seconds=1):
            baseline_start, baseline_kind = usual, "usual_time"
        else:
            reasons.append("usual_time_outside_horizon_used_run_now")
    baseline = next((e for e in evaluations if e.start == baseline_start), None)
    binding = set()
    if selected is not None:
        reference = selected.cost if selected.cost is not None else selected.high
        for item in evaluations:
            value = item.cost if item.cost is not None else item.high
            if item.violated and value is not None and value < reference - 1e-6:
                binding.update(item.violated)
    return CoreResult(
        status,
        selected,
        baseline,
        baseline_kind,
        feasible,
        sorted(binding),
        reasons,
        battery is not None,
        h_start,
        h_end,
    )


# ---------------------------------------------------------------- persistence and inputs


def _when(text):
    return datetime.fromisoformat(text) if text else None


def _effective_status(row, commitment, now: datetime) -> str:
    if row["status"] == "cancelled":
        return "cancelled"
    if commitment is None or commitment["released_at"]:
        return "suggested"
    if now >= _when(commitment["end_at"]):
        return "completed"
    if now >= _when(commitment["start_at"]):
        return "running"
    return "accepted"


def _commitment(connection, task_id: str):
    return connection.execute(
        "SELECT * FROM planner_commitments WHERE task_id=? AND released_at IS NULL",
        (task_id,),
    ).fetchone()


def _commitment_view(row) -> Commitment | None:
    if row is None:
        return None
    return Commitment(
        commitment_id=row["commitment_id"],
        task_revision=row["task_revision"],
        start=row["start_at"],
        end=row["end_at"],
        accepted_at=row["accepted_at"],
        accepted_received_at=row["accepted_received_at"],
        recommendation_revision=row["recommendation_revision"],
        contract_version_id=row["contract_version_id"],
        estimated_cost_ron=row["estimated_cost_ron"],
        baseline_cost_ron=row["baseline_cost_ron"],
        estimated_difference_ron=row["estimated_difference_ron"],
        baseline_kind=row["baseline_kind"],
        baseline_start=row["baseline_start"],
        released_at=row["released_at"],
        release_reason=row["release_reason"],
    )


def _task_view(connection, row, now: datetime) -> Task:
    commitment = _commitment(connection, row["task_id"])
    return Task(
        task_id=row["task_id"],
        site_id=row["site_id"],
        label=row["label"],
        kind=row["kind"],
        power_kw=row["power_kw"],
        energy_kwh=row["energy_kwh"],
        duration_minutes=round(row["energy_kwh"] / row["power_kw"] * 60, 3),
        earliest_start=row["earliest_start"],
        deadline=row["deadline"],
        latest_start=row["latest_start"],
        allowed_start_minute=row["allowed_start_minute"],
        allowed_end_minute=row["allowed_end_minute"],
        usual_start=row["usual_start"],
        site_import_limit_kw=row["site_import_limit_kw"],
        assumption_note=row["assumption_note"],
        status=_effective_status(row, commitment, now),
        revision=row["revision"],
        created_at=row["created_at"],
        commitment=_commitment_view(commitment),
    )


def _task_row(connection, site_id: str, task_id: str):
    row = connection.execute(
        "SELECT * FROM planner_tasks WHERE task_id=? AND site_id=?", (task_id, site_id)
    ).fetchone()
    if not row:
        raise ApiError(404, "not_found", "Resource not found")
    return row


def _spec(row) -> TaskSpec:
    window = (
        (row["allowed_start_minute"], row["allowed_end_minute"])
        if row["allowed_start_minute"] is not None
        else None
    )
    return TaskSpec(
        power_kw=row["power_kw"],
        energy_kwh=row["energy_kwh"],
        earliest_start=_when(row["earliest_start"]),
        deadline=_when(row["deadline"]),
        latest_start=_when(row["latest_start"]),
        allowed_window=window,
        usual_start=_when(row["usual_start"]),
        import_limit_kw=row["site_import_limit_kw"],
    )


def site_context(connection, site_id: str) -> dict:
    """Installed kWp, location and segment from explicit records (contract first)."""
    context = {
        "kwp": None,
        "kwp_basis": None,
        "location": None,
        "arrays": None,
        "profile": None,
    }
    contract = connection.execute(
        "SELECT installed_kwp FROM contracts WHERE site_id=?", (site_id,)
    ).fetchone()
    profile = connection.execute(
        "SELECT * FROM site_profiles WHERE site_id=?", (site_id,)
    ).fetchone()
    placement = connection.execute(
        "SELECT * FROM site_placements WHERE site_id=?", (site_id,)
    ).fetchone()
    if contract and contract["installed_kwp"]:
        context["kwp"], context["kwp_basis"] = contract["installed_kwp"], "contract"
    if profile:
        context["location"] = (profile["latitude"], profile["longitude"])
        context["profile"] = dict(profile)
        if context["kwp"] is None:
            context["kwp"], context["kwp_basis"] = profile["installed_kwp"], "profile"
    if placement:
        context["location"] = context["location"] or (
            placement["latitude"],
            placement["longitude"],
        )
        if placement["module_arrays"]:
            context["arrays"] = [
                (float(item["kwp"]), float(item["tilt"]), float(item["az"]))
                for item in json.loads(placement["module_arrays"])
            ]
        if context["kwp"] is None and placement["installed_kwp"]:
            context["kwp"], context["kwp_basis"] = (
                placement["installed_kwp"],
                "provider_registry",
            )
    equipment = bridge.planning_equipment(connection, site_id)
    if equipment.get("arrays") and not context["arrays"]:
        context["arrays"] = equipment["arrays"]
    if context["kwp"] is None and equipment.get("kwp"):
        context["kwp"], context["kwp_basis"] = equipment["kwp"], "asset_registry"
    return context


def _price_slots(connection, site_id: str, starts: list[datetime]):
    versions = tariff.load_versions(connection, site_id)
    reasons = []
    compensation = None
    if not versions:
        # Same fallback as offers: the published default tariff, visibly assumed.
        from backend.ops import profile_source

        default = profile_source()["default_tariff"]
        versions = [
            tariff.ContractVersion(
                DEFAULT_TARIFF_VERSION,
                0,
                tariff.EPOCH,
                (
                    tariff.all_day(
                        default["import_price_ron_kwh"], default["export_price_ron_kwh"]
                    ),
                ),
            )
        ]
        reasons.append("default_tariff_assumed_no_contract")
    prices = []
    for start in starts:
        priced = tariff.price(versions, start, start + SLOT)
        prices.append(priced)
    if versions:
        latest = versions[-1]
        compensation = latest.export_compensation
        if compensation == "credit":
            reasons.append("export_valued_as_contract_credit")
        elif compensation == "unspecified":
            reasons.append("export_compensation_type_unspecified")
    return prices, reasons, compensation


def _other_commitments(connection, site_id: str, task_id: str, start, end):
    return connection.execute(
        "SELECT start_at,end_at,power_kw FROM planner_commitments WHERE site_id=? "
        "AND task_id<>? AND released_at IS NULL AND start_at<? AND end_at>?",
        (site_id, task_id, stamp(end), stamp(start)),
    ).fetchall()


def compute_decision(connection, site_row, task_row) -> tuple[PlanDecision, dict]:
    """Plan one task at the analytical time; returns the decision and a cost snapshot."""
    state = clock_state(connection)
    now = state.now
    site_id = site_row["site_id"]
    spec = _spec(task_row)
    h_start, h_end = horizon(now, spec)
    starts = []
    cursor = h_start
    while cursor < h_end:
        starts.append(cursor)
        cursor += SLOT
    reasons: list[str] = []
    evidence: list[str] = []
    context = site_context(connection, site_id)
    history_start = h_start - timedelta(days=4)
    pv_history = bridge.pv_history(connection, site_id, history_start, now)
    load_history = bridge.load_history(connection, site_id, history_start, now)
    poa = bridge.irradiance_recent(connection, site_id, now - timedelta(hours=1), now)
    pv = solar_forecast.forecast_pv(
        starts,
        now,
        context["kwp"],
        context["location"],
        context["arrays"],
        pv_history.samples,
        poa.samples if poa else None,
        poa.plane if poa else None,
    )
    load = solar_forecast.forecast_load(
        starts, now, load_history.samples, context["profile"]
    )
    reasons += pv.reason_codes + load.reason_codes + pv_history.reasons
    reasons += load_history.reasons + (poa.reasons if poa else [])
    evidence += pv.evidence_ids + load.evidence_ids
    prices, price_reasons, compensation = _price_slots(connection, site_id, starts)
    reasons += price_reasons
    others = _other_commitments(
        connection, site_id, task_row["task_id"], h_start, h_end
    )
    if others:
        reasons.append("other_accepted_tasks_in_base_load")
    slots = []
    for start, priced in zip(starts, prices, strict=True):
        base = load.values.get(start)
        if base is not None:
            for other in others:
                overlap = (
                    min(start + SLOT, _when(other["end_at"]))
                    - max(start, _when(other["start_at"]))
                ).total_seconds()
                if overlap > 0:
                    base += other["power_kw"] * overlap / SLOT.total_seconds()
        slots.append(
            SlotInput(
                start,
                start + SLOT,
                pv.values.get(start),
                base,
                priced.import_rate,
                priced.export_value,
                (priced.band_ids or [None])[0],
                (priced.version_ids or [None])[0],
                (priced.gap_reasons or [None])[0],
            )
        )
    capability = bridge.battery_capability(connection, site_id, now)
    reasons += capability.reason_codes
    evidence += list(capability.evidence_ids)
    core = optimize(slots, spec, capability.params)
    reasons += core.reasons
    selected = core.selected
    baseline = core.baseline
    if baseline is not None and baseline.violated:
        reasons.append("baseline_violates_" + "_and_".join(baseline.violated))
    interval_plan = []
    snapshot_slots = []
    if selected is not None:
        for i, slot in enumerate(slots):
            if selected.profile[i] <= 0:
                continue
            simulation = selected.simulation
            imported = simulation.import_kwh[i]
            exported = simulation.export_kwh[i]
            interval_plan.append(
                PlanInterval(
                    start=slot.start,
                    end=slot.end,
                    task_kw=round(selected.profile[i], 4),
                    pv_forecast_kw=slot.pv_kw,
                    base_load_kw=None
                    if slot.base_kw is None
                    else round(slot.base_kw, 4),
                    battery_kw=None
                    if simulation.battery_kw[i] is None
                    else round(simulation.battery_kw[i], 4),
                    grid_import_kwh=None if imported is None else round(imported, 4),
                    grid_export_kwh=None if exported is None else round(exported, 4),
                    import_rate_ron_kwh=slot.import_rate,
                    export_value_ron_kwh=slot.export_value,
                    band_id=slot.band_id,
                    contract_version_id=slot.version_id,
                    incremental_cost_ron=None
                    if selected.slot_costs[i] is None
                    else round(selected.slot_costs[i], 4),
                    price_gap_reason=slot.gap_reason,
                )
            )
            site_cost = (
                None
                if None in (imported, exported, slot.import_rate, slot.export_value)
                else imported * slot.import_rate - exported * slot.export_value
            )
            snapshot_slots.append(
                {
                    "start": stamp(slot.start),
                    "end": stamp(slot.end),
                    "grid_import_kwh": imported,
                    "grid_export_kwh": exported,
                    "site_cost_ron": site_cost,
                }
            )
    est = selected.cost if selected else None
    base_cost = baseline.cost if baseline else None
    difference = (
        round(est - base_cost, 4) if est is not None and base_cost is not None else None
    )
    cost_range = None
    if selected is not None and selected.cost is None and selected.high is not None:
        cost_range = CostRange(
            low_ron=round(selected.low, 4),
            high_ron=round(selected.high, 4),
            basis="tariff_bounds_unknown_solar_or_load",
        )
    version_ids = sorted({s.version_id for s in slots if s.version_id})
    selected_version = interval_plan[0].contract_version_id if interval_plan else None
    battery_view = BatteryContribution(
        available=capability.params is not None,
        used=core.battery_used and selected is not None,
        reason_codes=capability.reason_codes,
        evidence_ids=list(capability.evidence_ids),
        **capability.view(),
        terminal_value_ron_per_stored_kwh=round(
            capability.params.discharge_efficiency * (bridge_terminal(slots) or 0), 4
        )
        if capability.params and bridge_terminal(slots) is not None
        else None,
        terminal_energy_change_kwh=round(selected.terminal_change_kwh, 4)
        if selected is not None and selected.terminal_change_kwh is not None
        else None,
    )
    coverage = InputCoverage(
        pv_forecast=round(sum(s.pv_kw is not None for s in slots) / len(slots), 4),
        base_load=round(sum(s.base_kw is not None for s in slots) / len(slots), 4),
        prices=round(sum(s.import_rate is not None for s in slots) / len(slots), 4),
    )
    freshness = [
        SourceFreshness(**item)
        for item in bridge.source_freshness(connection, site_id, now)
    ]
    commitment = _commitment(connection, task_row["task_id"])
    commitment_view = _commitment_view(commitment)
    review = False
    if (
        commitment is not None
        and _effective_status(task_row, commitment, now) == "accepted"
    ):
        changed = selected is None or stamp(selected.start) != commitment["start_at"]
        if (
            not changed
            and est is not None
            and commitment["estimated_cost_ron"] is not None
        ):
            changed = abs(est - commitment["estimated_cost_ron"]) > 0.05
        if changed:
            review = True
            reasons.append("current_recommendation_differs_from_commitment")
    candidates = [
        PlanCandidate(
            start=item.start,
            end=item.end,
            feasible=True,
            estimated_cost_ron=None if item.cost is None else round(item.cost, 4),
            cost_range=None
            if item.cost is not None or item.high is None
            else CostRange(
                low_ron=round(item.low, 4),
                high_ron=round(item.high, 4),
                basis="tariff_bounds_unknown_solar_or_load",
            ),
            violated_constraints=[],
            reason_codes=item.reasons,
        )
        for item in core.feasible[:MAX_CANDIDATES]
    ]
    applied = ["non_interruptible_run", "earliest_start", "deadline"]
    if spec.latest_start:
        applied.append("latest_start")
    if spec.allowed_window:
        applied.append("allowed_window")
    if spec.import_limit_kw:
        applied.append("site_import_limit")
    if core.battery_used:
        applied += ["battery_reserve", "battery_power_limits", "battery_terminal_value"]
    reason_codes = sorted(set(reasons))
    core_hash = {
        "task": task_row["task_id"],
        "revision": task_row["revision"],
        "start": stamp(selected.start) if selected else None,
        "cost": None if est is None else round(est, 4),
        "baseline": None if base_cost is None else round(base_cost, 4),
        "versions": version_ids,
        "forecast": [pv.method, pv.k_base, pv.k_recent, load.method],
        "battery": [capability.params is not None, list(capability.evidence_ids)],
        "horizon": stamp(h_start),
        "reasons": reason_codes,
    }
    revision = hashlib.sha256(
        json.dumps(core_hash, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    synthetic = state.mode == "scenario" or bridge.is_synthetic(connection, site_id)
    decision = PlanDecision(
        site_id=site_id,
        task_id=task_row["task_id"],
        task_revision=task_row["revision"],
        decided_at=now,
        clock_mode=state.mode,
        status=core.status,
        recommendation_revision=revision,
        recommended_start=selected.start if selected else None,
        recommended_end=selected.end if selected else None,
        estimated_cost_ron=None if est is None else round(est, 4),
        baseline_start=baseline.start if baseline else core.horizon_start,
        baseline_kind=core.baseline_kind,
        baseline_cost_ron=None if base_cost is None else round(base_cost, 4),
        estimated_difference_ron=difference,
        cost_range=cost_range,
        interval_plan=interval_plan,
        binding_constraints=core.binding,
        constraints_applied=applied,
        contract_version_id=selected_version,
        contract_version_ids=version_ids,
        export_compensation=compensation,
        horizon_start=core.horizon_start,
        horizon_end=core.horizon_end,
        forecast=ForecastInfo(
            issue_time=pv.issue_time,
            pv_method=pv.method,
            load_method=load.method,
            clearness_base=pv.k_base,
            clearness_recent=pv.k_recent,
            recent_source=pv.recent_source,
            location_basis=pv.location_basis,
            plane_basis=pv.plane_basis,
        ),
        battery=battery_view,
        input_coverage=coverage,
        freshness=freshness,
        evidence_ids=list(dict.fromkeys(evidence))[:50],
        reason_codes=reason_codes,
        candidates=candidates,
        commitment=commitment_view,
        review_suggested=review,
        source_mode="synthetic" if synthetic else "live",
    )
    return decision, {"slots": snapshot_slots}


def bridge_terminal(slots: list[SlotInput]) -> float | None:
    return _terminal_rate(slots)


# ---------------------------------------------------------------- API services


def list_tasks(connection, user: User, site_id: str) -> list[Task]:
    authorized_site(connection, user, site_id)
    now = clock_state(connection).now
    rows = connection.execute(
        "SELECT * FROM planner_tasks WHERE site_id=? ORDER BY earliest_start, task_id LIMIT 100",
        (site_id,),
    ).fetchall()
    return [_task_view(connection, row, now) for row in rows]


def _values(payload: TaskCreate) -> tuple:
    return (
        payload.label.strip(),
        payload.kind,
        payload.power_kw,
        payload.energy_kwh,
        stamp(payload.earliest_start),
        stamp(payload.deadline),
        stamp(payload.latest_start) if payload.latest_start else None,
        payload.allowed_start_minute,
        payload.allowed_end_minute,
        stamp(payload.usual_start) if payload.usual_start else None,
        payload.site_import_limit_kw,
        payload.assumption_note,
    )


COLUMNS = (
    "label,kind,power_kw,energy_kwh,earliest_start,deadline,latest_start,"
    "allowed_start_minute,allowed_end_minute,usual_start,site_import_limit_kw,assumption_note"
)


def create_task(
    database, connection, user: User, site_id: str, payload: TaskCreate, rid: str
) -> Task:
    require_customer(user)
    authorized_site(connection, user, site_id)
    connection.execute("BEGIN IMMEDIATE")
    now = clock_state(connection).now
    count = connection.execute(
        "SELECT COUNT(*) FROM planner_tasks WHERE site_id=? AND status<>'cancelled'",
        (site_id,),
    ).fetchone()[0]
    if count >= MAX_TASKS:
        raise ApiError(409, "too_many_tasks", "Cancel or finish older tasks first")
    if payload.deadline <= now:
        raise ApiError(422, "deadline_passed", "The deadline has already passed")
    task_id = uuid.uuid4().hex
    connection.execute(
        f"INSERT INTO planner_tasks(task_id,site_id,created_by,{COLUMNS},status,revision,"
        "created_at,created_as_of,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
        "'suggested',1,?,?,?)",
        (
            task_id,
            site_id,
            user.user_id,
            *_values(payload),
            stamp(),
            stamp(now),
            stamp(),
        ),
    )
    database.audit(
        connection,
        user.user_id,
        "planner.task.created",
        task_id,
        rid,
        {"site_id": site_id, "analytical_at": stamp(now)},
    )
    return _task_view(connection, _task_row(connection, site_id, task_id), now)


def update_task(
    database,
    connection,
    user: User,
    site_id: str,
    task_id: str,
    payload: TaskUpdate,
    rid: str,
) -> Task:
    require_customer(user)
    authorized_site(connection, user, site_id)
    connection.execute("BEGIN IMMEDIATE")
    now = clock_state(connection).now
    row = _task_row(connection, site_id, task_id)
    if row["status"] == "cancelled":
        raise ApiError(409, "task_cancelled", "This task was cancelled")
    if _commitment(connection, task_id) is not None:
        raise ApiError(
            409,
            "task_committed",
            "An accepted task is not changed silently; review (release) it first",
        )
    if row["revision"] != payload.expected_revision:
        raise ApiError(409, "stale_revision", "The task changed; reload it first")
    data = TaskCreate.model_validate(payload.model_dump(exclude={"expected_revision"}))
    assignments = ",".join(f"{column}=?" for column in COLUMNS.split(","))
    connection.execute(
        f"UPDATE planner_tasks SET {assignments},revision=revision+1,updated_at=? "
        "WHERE task_id=?",
        (*_values(data), stamp(), task_id),
    )
    database.audit(
        connection,
        user.user_id,
        "planner.task.updated",
        task_id,
        rid,
        {"revision": row["revision"] + 1, "analytical_at": stamp(now)},
    )
    return _task_view(connection, _task_row(connection, site_id, task_id), now)


def cancel_task(
    database, connection, user: User, site_id: str, task_id: str, rid: str
) -> Task:
    require_customer(user)
    authorized_site(connection, user, site_id)
    connection.execute("BEGIN IMMEDIATE")
    now = clock_state(connection).now
    row = _task_row(connection, site_id, task_id)
    if _commitment(connection, task_id) is not None:
        raise ApiError(
            409,
            "task_committed",
            "Review (release) the accepted plan before cancelling",
        )
    if row["status"] != "cancelled":
        connection.execute(
            "UPDATE planner_tasks SET status='cancelled',revision=revision+1,updated_at=? "
            "WHERE task_id=?",
            (stamp(), task_id),
        )
        database.audit(connection, user.user_id, "planner.task.cancelled", task_id, rid)
    return _task_view(connection, _task_row(connection, site_id, task_id), now)


def plan(connection, user: User, site_id: str, task_id: str) -> PlanDecision:
    site_row = authorized_site(connection, user, site_id)
    row = _task_row(connection, site_id, task_id)
    if row["status"] == "cancelled":
        raise ApiError(409, "task_cancelled", "This task was cancelled")
    return compute_decision(connection, site_row, row)[0]


def accept_task(
    database,
    connection,
    user: User,
    site_id: str,
    task_id: str,
    payload: AcceptTask,
    idempotency_key: str | None,
    rid: str,
) -> tuple[Task, bool]:
    require_customer(user)
    site_row = authorized_site(connection, user, site_id)
    connection.execute("BEGIN IMMEDIATE")
    now = clock_state(connection).now
    if idempotency_key:
        existing = connection.execute(
            "SELECT task_id FROM planner_commitments WHERE user_id=? AND idempotency_key=?",
            (user.user_id, idempotency_key),
        ).fetchone()
        if existing:
            if existing["task_id"] != task_id:
                raise ApiError(
                    409,
                    "idempotency_key_reused",
                    "This Idempotency-Key was already used for another task",
                )
            return _task_view(
                connection, _task_row(connection, site_id, task_id), now
            ), False
    row = _task_row(connection, site_id, task_id)
    if row["status"] == "cancelled":
        raise ApiError(409, "task_cancelled", "This task was cancelled")
    if _commitment(connection, task_id) is not None:
        raise ApiError(
            409, "already_accepted", "This task already has an accepted plan"
        )
    decision, snapshot = compute_decision(connection, site_row, row)
    if decision.recommendation_revision != payload.recommendation_revision:
        raise ApiError(
            409,
            "recommendation_changed",
            "The recommendation changed since it was shown; review the new one",
        )
    start = payload.start or decision.recommended_start
    if start is None:
        raise ApiError(409, "no_recommendation", "There is no feasible start to accept")
    start = start.astimezone(UTC)
    chosen = next((c for c in decision.candidates if c.start == start), None)
    if chosen is None:
        raise ApiError(422, "start_not_feasible", "Choose one of the feasible starts")
    if start < now:
        raise ApiError(409, "start_passed", "This start time has already passed")
    if start != decision.recommended_start:
        snapshot = {"slots": [], "note": "customer_chose_non_recommended_start"}
    end = start + timedelta(hours=row["energy_kwh"] / row["power_kw"])
    commitment_id = uuid.uuid4().hex
    record = decision.model_dump(mode="json")
    record["accepted_start"] = stamp(start)
    record["snapshot"] = snapshot
    try:
        connection.execute(
            "INSERT INTO planner_commitments(commitment_id,task_id,task_revision,site_id,"
            "user_id,start_at,end_at,power_kw,energy_kwh,recommendation_revision,"
            "contract_version_id,estimated_cost_ron,baseline_cost_ron,"
            "estimated_difference_ron,decision,accepted_at,accepted_received_at,"
            "idempotency_key,baseline_kind,baseline_start) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                commitment_id,
                task_id,
                row["revision"],
                site_id,
                user.user_id,
                stamp(start),
                stamp(end),
                row["power_kw"],
                row["energy_kwh"],
                decision.recommendation_revision,
                decision.contract_version_id,
                chosen.estimated_cost_ron,
                decision.baseline_cost_ron,
                round(chosen.estimated_cost_ron - decision.baseline_cost_ron, 4)
                if chosen.estimated_cost_ron is not None
                and decision.baseline_cost_ron is not None
                else None,
                json.dumps(record, sort_keys=True),
                stamp(now),
                stamp(),
                idempotency_key,
                decision.baseline_kind,
                stamp(decision.baseline_start) if decision.baseline_start else None,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ApiError(
            409, "already_accepted", "This task already has an accepted plan"
        ) from exc
    connection.execute(
        "UPDATE planner_tasks SET status='accepted',updated_at=? WHERE task_id=?",
        (stamp(), task_id),
    )
    database.audit(
        connection,
        user.user_id,
        "planner.task.accepted",
        task_id,
        rid,
        {
            "commitment_id": commitment_id,
            "start": stamp(start),
            "recommendation_revision": decision.recommendation_revision,
            "contract_version_id": decision.contract_version_id,
            "accepted_at": stamp(now),
        },
    )
    return _task_view(connection, _task_row(connection, site_id, task_id), now), True


def review_task(
    database,
    connection,
    user: User,
    site_id: str,
    task_id: str,
    payload: ReviewTask,
    rid: str,
) -> Task:
    """Explicit review: release an accepted plan that has not started yet."""
    require_customer(user)
    authorized_site(connection, user, site_id)
    connection.execute("BEGIN IMMEDIATE")
    now = clock_state(connection).now
    _task_row(connection, site_id, task_id)
    commitment = _commitment(connection, task_id)
    if commitment is None:
        raise ApiError(409, "not_committed", "This task has no accepted plan")
    if now >= _when(commitment["start_at"]):
        raise ApiError(
            409, "task_started", "A plan that has started cannot be released"
        )
    connection.execute(
        "UPDATE planner_commitments SET released_at=?,released_received_at=?,release_reason=? "
        "WHERE commitment_id=? AND released_at IS NULL",
        (stamp(now), stamp(), payload.reason.strip(), commitment["commitment_id"]),
    )
    connection.execute(
        "UPDATE planner_tasks SET status='suggested',revision=revision+1,updated_at=? "
        "WHERE task_id=?",
        (stamp(), task_id),
    )
    database.audit(
        connection,
        user.user_id,
        "planner.task.released",
        task_id,
        rid,
        {"commitment_id": commitment["commitment_id"], "analytical_at": stamp(now)},
    )
    return _task_view(connection, _task_row(connection, site_id, task_id), now)


def task_progress(connection, user: User, site_id: str, task_id: str) -> TaskProgress:
    authorized_site(connection, user, site_id)
    row = _task_row(connection, site_id, task_id)
    now = clock_state(connection).now
    commitment = _commitment(connection, task_id)
    if commitment is None:
        raise ApiError(409, "not_committed", "This task has no accepted plan")
    start, end = _when(commitment["start_at"]), _when(commitment["end_at"])
    upper = min(end, now)
    reasons = []
    if now < start:
        reasons.append("run_not_started")
        upper = start
    imports = bridge.meter_series(connection, site_id, Metric.grid_import, start, upper)
    exports = bridge.meter_series(connection, site_id, Metric.grid_export, start, upper)
    span_end = max(upper, start)
    import_coverage = imports.coverage(start, span_end) if upper > start else 0.0
    export_coverage = exports.coverage(start, span_end) if upper > start else 0.0
    if imports.source == "none" or (not imports.intervals and upper > start):
        reasons.append("no_authoritative_grid_meter_data")
    measured_cost = None
    complete = upper > start and import_coverage >= 0.999 and export_coverage >= 0.999
    if upper > start and not complete:
        reasons.append("meter_coverage_incomplete")
    versions = tariff.load_versions(connection, site_id)
    if complete and versions:
        total = 0.0
        ok = True
        for series, sign, attribute in (
            (imports, 1, "import_rate"),
            (exports, -1, "export_value"),
        ):
            for item in series.intervals:
                if item.kw is None:
                    ok = False
                    break
                lower, higher = max(item.start, start), min(item.end, upper)
                if higher <= lower:
                    continue
                priced = tariff.price(versions, lower, higher)
                rate = getattr(priced, attribute)
                if rate is None:
                    ok = False
                    break
                total += (
                    sign
                    * float(item.kw)
                    * (higher - lower).total_seconds()
                    / 3600
                    * rate
                )
        if ok:
            measured_cost = round(total, 4)
        else:
            reasons.append("price_or_meter_gap")
    elif complete:
        reasons.append("no_contract_bands_for_measured_cost")
    decision = json.loads(commitment["decision"])
    estimated = None
    slots = decision.get("snapshot", {}).get("slots", [])
    if slots:
        elapsed = [
            s
            for s in slots
            if _when(s["end"]) <= upper and s["site_cost_ron"] is not None
        ]
        if elapsed and len(elapsed) == sum(_when(s["end"]) <= upper for s in slots):
            estimated = round(sum(s["site_cost_ron"] for s in elapsed), 4)
    else:
        reasons.append("no_estimate_snapshot_for_chosen_start")
    return TaskProgress(
        task_id=task_id,
        site_id=site_id,
        status=_effective_status(row, commitment, now),
        as_of=now,
        window_start=start,
        window_end=end,
        measured=MeasuredWindow(
            grid_import_kwh=None
            if imports.energy_kwh() is None
            else round(imports.energy_kwh(), 4),
            grid_export_kwh=None
            if exports.energy_kwh() is None
            else round(exports.energy_kwh(), 4),
            import_coverage=round(import_coverage, 4),
            export_coverage=round(export_coverage, 4),
            source=imports.source,
            boundary=imports.boundary,
            evidence_ids=(imports.evidence_ids + exports.evidence_ids)[:50],
        ),
        measured_site_cost_ron=measured_cost,
        estimated_site_cost_ron=estimated,
        attribution_note=ATTRIBUTION_NOTE,
        reason_codes=sorted(set(reasons)),
    )
