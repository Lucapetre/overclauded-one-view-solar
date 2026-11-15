"""Deterministic, bounded crew planning: which eligible crew handles each job, in what order
and approximately when. The result is a **feasible heuristic proposal**, not a guaranteed
global optimum.

Method (spec 9.7):

1. Filter jobs by responsibility/authorization, area permission, qualifications, tools,
   parts, crew size, known location/duration/access window and remote-triage requirement.
   Monitoring-only items never become jobs; remote activities go to the remote desk.
2. Reserve locked/started commitments and break blocks (never moved or dropped).
3. Process priority bands and mandatory deadlines first (then within-band rank), with
   dependencies before their dependents.
4. For each job evaluate every insertion position in every eligible crew's route; recheck the
   complete affected routes (travel, service duration, access windows, shifts, breaks,
   member-level availability across crews, dependencies) after every candidate insertion.
5. Pick the insertion by lexicographic goals: (a) hard constraints, (b) timely response of
   higher bands is never reduced, earliest start for P0/P1, (c) lower expected delay loss,
   (d) less added travel, balanced workload; deterministic tie-breaks (crew id, position).
6. A bounded local improvement relocates lower-band jobs only when total travel strictly falls
   and no band's timely count drops.

A feasible FIFO baseline runs under identical constraints (arrival order, append-only,
first eligible crew by name) and both are compared honestly.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta

BANDS = ("P0", "P1", "P2", "P3")
FIELD = "field_visit"
REMOTE = ("remote_review", "remote_troubleshooting")


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime

    def overlaps(self, start: datetime, end: datetime) -> bool:
        return start < self.end and self.start < end


@dataclass(frozen=True)
class Commitment:
    """A locked or started job: fixed in time and place, never moved by the planner."""

    job_id: str
    incident_id: str
    node: str | None
    start: datetime
    end: datetime
    started: bool = False


@dataclass
class CrewInput:
    crew_id: str
    name: str
    kind: str  # field | remote_desk
    organisation: str
    authorised_services: set[str]
    qualifications: set[str]
    tools: set[str]
    areas: set[str]
    members: list[str]
    shift: Window | None
    breaks: list[Window] = field(default_factory=list)
    base_node: str | None = None
    location_reported_at: datetime | None = None
    commitments: list[Commitment] = field(default_factory=list)


@dataclass
class JobInput:
    job_id: str
    incident_id: str
    site_id: str
    title: str
    band: str
    rank_position: int
    rank_score: float
    created_at: datetime
    activity: str
    service_key: str
    area: str | None
    node: str | None
    service_minutes: int | None
    access_windows: list[Window] | None
    qualifications: set[str] = field(default_factory=set)
    tools: set[str] = field(default_factory=set)
    parts_required: list[str] = field(default_factory=list)
    parts_ready: bool | None = None
    crew_size: int = 1
    deadline: datetime | None = None
    deadline_mandatory: bool = False
    depends_on: list[str] = field(default_factory=list)
    expected_lost_kwh_per_day: float | None = None


@dataclass
class PlanningInputs:
    now: datetime
    horizon_end: datetime
    crews: list[CrewInput]
    jobs: list[JobInput]
    travel: dict[tuple[str, str], int]
    travel_source: str
    member_unavailability: list[tuple[str, Window, str]] = field(default_factory=list)
    overtime_minutes: int = 0
    local_improvement_passes: int = 2
    max_evaluations: int = 20000
    monitoring: list[dict] = field(default_factory=list)

    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(_snapshot(self), sort_keys=True, default=str).encode()
        ).hexdigest()


def _snapshot(inputs: PlanningInputs) -> dict:
    def window(w):
        return [w.start.isoformat(), w.end.isoformat()] if w else None

    return {
        "now": inputs.now.isoformat(),
        "horizon_end": inputs.horizon_end.isoformat(),
        "travel_source": inputs.travel_source,
        "overtime_minutes": inputs.overtime_minutes,
        "crews": [
            {
                "crew_id": c.crew_id,
                "kind": c.kind,
                "organisation": c.organisation,
                "authorised_services": sorted(c.authorised_services),
                "qualifications": sorted(c.qualifications),
                "tools": sorted(c.tools),
                "areas": sorted(c.areas),
                "members": len(c.members),
                # Pseudonymous digest: membership changes invalidate a plan, ids stay out.
                "member_digest": hashlib.sha256(
                    "|".join(sorted(c.members)).encode()
                ).hexdigest()[:16],
                "shift": window(c.shift),
                "breaks": [window(b) for b in c.breaks],
                "base_node": c.base_node,
                "location_reported_at": c.location_reported_at.isoformat()
                if c.location_reported_at
                else None,
                "commitments": [
                    [
                        m.job_id,
                        m.node,
                        m.start.isoformat(),
                        m.end.isoformat(),
                        m.started,
                    ]
                    for m in c.commitments
                ],
            }
            for c in sorted(inputs.crews, key=lambda c: c.crew_id)
        ],
        "jobs": [
            {
                "job_id": j.job_id,
                "incident_id": j.incident_id,
                "band": j.band,
                "rank_position": j.rank_position,
                "activity": j.activity,
                "service_key": j.service_key,
                "area": j.area,
                "node": j.node,
                "service_minutes": j.service_minutes,
                "access_windows": [window(w) for w in j.access_windows]
                if j.access_windows is not None
                else None,
                "qualifications": sorted(j.qualifications),
                "tools": sorted(j.tools),
                "parts_required": j.parts_required,
                "parts_ready": j.parts_ready,
                "crew_size": j.crew_size,
                "deadline": j.deadline.isoformat() if j.deadline else None,
                "deadline_mandatory": j.deadline_mandatory,
                "depends_on": sorted(j.depends_on),
            }
            for j in sorted(inputs.jobs, key=lambda j: j.job_id)
        ],
        "unavailability": sorted(
            [hashlib.sha256(m.encode()).hexdigest()[:12], window(w)]
            for m, w, _ in inputs.member_unavailability
        ),
        "travel_digest": hashlib.sha256(
            json.dumps(sorted([list(k), v] for k, v in inputs.travel.items())).encode()
        ).hexdigest()[:16],
        "travel_pairs": len(inputs.travel),
    }


# ---------------------------------------------------------------- eligibility


def static_reasons(job: JobInput, crew: CrewInput, inputs: PlanningInputs) -> list[str]:
    """Why `crew` can never take `job` (empty = statically eligible)."""
    reasons = []
    remote_job = job.activity in REMOTE
    if remote_job != (crew.kind == "remote_desk"):
        reasons.append(
            "activity_requires_remote_desk" if remote_job else "remote_desk_no_field"
        )
    if job.service_key not in crew.authorised_services:
        reasons.append("crew_not_authorised_for_responsible_service")
    if job.area and crew.areas and job.area not in crew.areas:
        reasons.append("outside_crew_area_permission")
    missing = sorted(job.qualifications - crew.qualifications)
    if missing:
        reasons.append("missing_qualification:" + ",".join(missing))
    tools = sorted(job.tools - crew.tools)
    if tools:
        reasons.append("missing_tools:" + ",".join(tools))
    if job.crew_size > len(crew.members):
        reasons.append("crew_too_small")
    if crew.shift is None:
        reasons.append("crew_shift_unknown")
    if not remote_job:
        if crew.base_node is None:
            reasons.append("crew_location_unknown")
        elif (
            job.node is not None
            and travel_minutes(inputs, crew.base_node, job.node) is None
        ):
            reasons.append("travel_time_unknown")
    return reasons


def job_reasons(job: JobInput) -> list[str]:
    """Unknown critical values make a job unplannable (never zero duration / fake ETA)."""
    reasons = []
    if job.activity == FIELD and job.node is None:
        reasons.append("job_location_unknown")
    if job.service_minutes is None or job.service_minutes <= 0:
        reasons.append("service_duration_unknown")
    if job.access_windows is None:
        reasons.append("access_window_unknown")
    if job.parts_required and job.parts_ready is not True:
        reasons.append(
            "parts_not_ready" if job.parts_ready is False else "parts_readiness_unknown"
        )
    return reasons


def travel_minutes(inputs: PlanningInputs, a: str | None, b: str | None) -> int | None:
    if a is None or b is None:
        return None
    if a == b:
        return 0
    return inputs.travel.get((a, b), inputs.travel.get((b, a)))


# ---------------------------------------------------------------- simulation


@dataclass
class Stop:
    job: JobInput | None
    commitment: Commitment | None = None


@dataclass
class Timing:
    job_id: str
    incident_id: str
    depart: datetime
    arrive: datetime
    start: datetime
    finish: datetime
    travel: int
    service: int
    fixed: bool
    late: bool


def _after_breaks(moment: datetime, minutes: int, breaks: list[Window]) -> datetime:
    """Earliest start >= moment so that [start, start+minutes) avoids every break."""
    changed = True
    while changed:
        changed = False
        for block in breaks:
            if block.overlaps(moment, moment + timedelta(minutes=minutes)):
                moment, changed = block.end, True
    return moment


class Planner:
    def __init__(self, inputs: PlanningInputs):
        self.inputs = inputs
        self.crews = sorted(inputs.crews, key=lambda c: c.crew_id)
        self.unavailable: dict[str, list[Window]] = {}
        for member, window, _ in inputs.member_unavailability:
            self.unavailable.setdefault(member, []).append(window)
        self.evaluations = 0
        self._jobs = {j.job_id: j for j in inputs.jobs}

    def _base_route(self, crew: CrewInput) -> list[Stop]:
        return [Stop(None, c) for c in sorted(crew.commitments, key=lambda c: c.start)]

    def simulate_all(self, routes: dict[str, list[Stop]]):
        """Simulate every route (crew-id order); returns timings or (None, reason)."""
        finishes: dict[str, datetime] = {}
        result = None
        for _ in range(3):  # fixed point for cross-crew dependencies
            occupancy: dict[str, list[tuple[datetime, datetime]]] = {}
            result = {}
            for crew in self.crews:
                timings, reason = self._simulate(
                    crew, routes[crew.crew_id], finishes, occupancy
                )
                if timings is None:
                    return None, f"{crew.crew_id}:{reason}"
                result[crew.crew_id] = timings
            new_finishes = {t.job_id: t.finish for ts in result.values() for t in ts}
            if new_finishes == finishes:
                break
            finishes = new_finishes
        else:
            return None, "dependency_times_unstable"
        for ts in result.values():
            for timing in ts:
                job = self._jobs.get(timing.job_id)
                if job is None:
                    continue
                for dep in job.depends_on:
                    if dep not in finishes:
                        return None, f"dependency_not_scheduled:{dep}"
                    if finishes[dep] > timing.start:
                        return None, f"dependency_order:{dep}"
        return result, None

    def _members_available(self, crew, start, end, occupancy) -> int:
        free = 0
        for member in crew.members:
            if any(w.overlaps(start, end) for w in self.unavailable.get(member, [])):
                continue
            if any(s < end and start < e for s, e in occupancy.get(member, [])):
                continue
            free += 1
        return free

    def _simulate(self, crew, route, finishes, occupancy):
        inputs = self.inputs
        shift = crew.shift
        if shift is None:
            return (
                (None, "crew_shift_unknown")
                if any(s.job for s in route)
                else ([], None)
            )
        limit = min(
            shift.end + timedelta(minutes=inputs.overtime_minutes), inputs.horizon_end
        )
        moment = max(inputs.now, shift.start)
        position = crew.base_node
        timings: list[Timing] = []
        remote = crew.kind == "remote_desk"
        for stop in route:
            if stop.commitment is not None:
                c = stop.commitment
                if c.started or remote:
                    position, moment = c.node or position, max(moment, c.end)
                else:
                    travel = travel_minutes(inputs, position, c.node) or 0
                    if moment + timedelta(minutes=travel) > c.start:
                        return None, f"cannot_reach_locked_commitment:{c.job_id}"
                    position, moment = c.node, max(moment, c.end)
                timings.append(
                    Timing(
                        c.job_id,
                        c.incident_id,
                        c.start,
                        c.start,
                        c.start,
                        c.end,
                        0,
                        int((c.end - c.start).total_seconds() // 60),
                        True,
                        False,
                    )
                )
                continue
            job = stop.job
            travel = 0 if remote else travel_minutes(inputs, position, job.node)
            if travel is None:
                return None, f"travel_time_unknown:{job.job_id}"
            depart = _after_breaks(moment, travel, crew.breaks) if travel else moment
            arrive = depart + timedelta(minutes=travel)
            earliest = arrive
            for dep in job.depends_on:
                if dep in finishes:
                    earliest = max(earliest, finishes[dep])
            start = None
            for window in sorted(job.access_windows or [], key=lambda w: w.start):
                candidate = _after_breaks(
                    max(earliest, window.start), job.service_minutes, crew.breaks
                )
                if candidate + timedelta(minutes=job.service_minutes) <= window.end:
                    start = candidate
                    break
            if start is None:
                return None, f"no_access_window_slot:{job.job_id}"
            finish = start + timedelta(minutes=job.service_minutes)
            if travel and start > arrive:
                # Just-in-time departure when the crew would otherwise wait on site, unless
                # that travel would cross a break.
                late_depart = start - timedelta(minutes=travel)
                if not any(b.overlaps(late_depart, start) for b in crew.breaks):
                    depart, arrive = late_depart, start
            if finish > limit:
                return None, f"exceeds_shift_or_horizon:{job.job_id}"
            late = job.deadline is not None and start > job.deadline
            # A deadline already passed at planning time cannot be met by anyone: the job is
            # scheduled as early as feasible and reported as an urgent exception instead.
            if late and job.deadline_mandatory and job.deadline >= inputs.now:
                return None, f"mandatory_deadline_unreachable:{job.job_id}"
            if self._members_available(crew, depart, finish, occupancy) < job.crew_size:
                return None, f"members_unavailable:{job.job_id}"
            if any(
                c.commitment
                and c.commitment.start < finish
                and start < c.commitment.end
                for c in route
                if c.commitment
            ):
                return None, f"overlaps_locked_commitment:{job.job_id}"
            timings.append(
                Timing(
                    job.job_id,
                    job.incident_id,
                    depart,
                    arrive,
                    start,
                    finish,
                    travel,
                    job.service_minutes,
                    False,
                    late,
                )
            )
            position, moment = job.node if not remote else position, finish
        for timing in timings:
            for member in crew.members:
                occupancy.setdefault(member, []).append((timing.depart, timing.finish))
        return timings, None

    # ------------------------------------------------------------ objective helpers

    def _timely(self, timings) -> dict[str, int]:
        counts = dict.fromkeys(BANDS, 0)
        for ts in timings.values():
            for t in ts:
                job = self._jobs.get(t.job_id)
                if job and not t.fixed and not t.late:
                    counts[job.band] += 1
        return counts

    @staticmethod
    def _travel(timings) -> int:
        return sum(t.travel for ts in timings.values() for t in ts if not t.fixed)

    def _delay_loss(self, timings) -> float:
        total = 0.0
        for ts in timings.values():
            for t in ts:
                job = self._jobs.get(t.job_id)
                if job and job.expected_lost_kwh_per_day:
                    hours = max(0.0, (t.start - self.inputs.now).total_seconds() / 3600)
                    total += job.expected_lost_kwh_per_day * hours / 24
        return round(total, 3)

    # ------------------------------------------------------------ planning

    def order(self, jobs: list[JobInput], fifo: bool = False) -> list[JobInput]:
        if fifo:
            ordered = sorted(jobs, key=lambda j: (j.created_at, j.job_id))
        else:
            ordered = sorted(
                jobs,
                key=lambda j: (
                    BANDS.index(j.band),
                    0 if j.deadline_mandatory else 1,
                    j.deadline or self.inputs.horizon_end,
                    j.rank_position,
                    j.job_id,
                ),
            )
        # Dependencies before dependents (stable).
        placed, result, pending = set(), [], list(ordered)
        ids = {j.job_id for j in jobs}
        while pending:
            progressed = False
            for job in list(pending):
                if all(d in placed or d not in ids for d in job.depends_on):
                    result.append(job)
                    placed.add(job.job_id)
                    pending.remove(job)
                    progressed = True
                    break
            if not progressed:
                result += pending
                break
        return result

    def run(self, fifo: bool = False) -> dict:
        inputs = self.inputs
        routes = {c.crew_id: self._base_route(c) for c in self.crews}
        timings, reason = self.simulate_all(routes)
        if timings is None:
            raise ValueError(f"Locked commitments are infeasible: {reason}")
        unassigned: dict[str, list[str]] = {}
        eligible_map: dict[str, list[CrewInput]] = {}
        plannable = []
        for job in inputs.jobs:
            reasons = job_reasons(job)
            eligible, why = [], []
            for crew in self.crews:
                crew_reasons = static_reasons(job, crew, inputs)
                if crew_reasons:
                    why += [f"{crew.crew_id}:{r}" for r in crew_reasons]
                else:
                    eligible.append(crew)
            if reasons:
                unassigned[job.job_id] = reasons
            elif not eligible:
                summary = sorted({w.split(":", 1)[1].split(":")[0] for w in why})
                unassigned[job.job_id] = ["no_eligible_crew"] + summary + why
            else:
                eligible_map[job.job_id] = (
                    sorted(eligible, key=lambda c: c.name) if fifo else eligible
                )
                plannable.append(job)
        for job in self.order(plannable, fifo):
            if any(d in unassigned for d in job.depends_on):
                unassigned[job.job_id] = ["dependency_not_scheduled"]
                continue
            best, failures = None, []
            before = self._timely(timings)
            for crew in eligible_map[job.job_id]:
                route = routes[crew.crew_id]
                positions = [len(route)] if fifo else range(len(route) + 1)
                for position in positions:
                    if (
                        position < len(route)
                        and route[position].commitment is not None
                        and (route[position].commitment.started)
                    ):
                        continue
                    self.evaluations += 1
                    if self.evaluations > inputs.max_evaluations:
                        failures.append("evaluation_budget_exhausted")
                        break
                    candidate = dict(routes)
                    candidate[crew.crew_id] = (
                        route[:position] + [Stop(job)] + route[position:]
                    )
                    result, why = self.simulate_all(candidate)
                    if result is None:
                        failures.append(why)
                        continue
                    after = self._timely(result)
                    # Goal 2: never reduce the timely count of an already-placed band.
                    if any(after[b] < before[b] for b in BANDS):
                        failures.append(
                            f"{crew.crew_id}:would_delay_higher_priority_job"
                        )
                        continue
                    own = next(
                        t for t in result[crew.crew_id] if t.job_id == job.job_id
                    )
                    key = (
                        1 if own.late else 0,
                        (own.start - inputs.now).total_seconds()
                        if job.band in ("P0", "P1")
                        else 0,
                        self._delay_loss(result),
                        self._travel(result) - self._travel(timings),
                        own.finish,
                        sum(1 for s in candidate[crew.crew_id] if s.job),
                        crew.crew_id,
                        position,
                    )
                    if fifo:
                        best = (key, crew, candidate, result)
                        break
                    if best is None or key < best[0]:
                        best = (key, crew, candidate, result)
                if fifo and best:
                    break
            if best is None:
                specific = sorted(
                    {f.split(":", 1)[-1].split(":")[0] for f in failures if f}
                )
                unassigned[job.job_id] = ["no_feasible_insertion"] + specific
                continue
            _, crew, routes, timings = best
        if not fifo:
            routes, timings = self._improve(routes, timings)
        return self._result(routes, timings, unassigned, fifo)

    def _improve(self, routes, timings):
        """Bounded local improvement: relocate P2/P3 jobs if total travel strictly falls."""
        for _ in range(self.inputs.local_improvement_passes):
            improved = False
            movable = [
                s.job
                for c in self.crews
                for s in routes[c.crew_id]
                if s.job and s.job.band in ("P2", "P3")
            ]
            for job in sorted(movable, key=lambda j: j.job_id):
                base_timely, base_travel = self._timely(timings), self._travel(timings)
                stripped = {
                    cid: [
                        s for s in route if not (s.job and s.job.job_id == job.job_id)
                    ]
                    for cid, route in routes.items()
                }
                best = None
                for crew in self.crews:
                    if static_reasons(job, crew, self.inputs):
                        continue
                    route = stripped[crew.crew_id]
                    for position in range(len(route) + 1):
                        self.evaluations += 1
                        if self.evaluations > self.inputs.max_evaluations:
                            return routes, timings
                        candidate = dict(stripped)
                        candidate[crew.crew_id] = (
                            route[:position] + [Stop(job)] + route[position:]
                        )
                        result, _ = self.simulate_all(candidate)
                        if result is None:
                            continue
                        timely = self._timely(result)
                        if any(timely[b] < base_timely[b] for b in BANDS):
                            continue
                        travel = self._travel(result)
                        if travel < base_travel and (best is None or travel < best[0]):
                            best = (travel, candidate, result)
                if best:
                    _, routes, timings = best
                    improved = True
            if not improved:
                break
        return routes, timings

    def _result(self, routes, timings, unassigned, fifo) -> dict:
        inputs = self.inputs
        crews = {c.crew_id: c for c in self.crews}
        visits, remote = [], []
        for crew_id in sorted(timings):
            sequence = 0
            for timing in timings[crew_id]:
                if timing.fixed:
                    continue
                job = self._jobs[timing.job_id]
                sequence += 1
                item = {
                    "crew_id": crew_id,
                    "crew_name": crews[crew_id].name,
                    "job_id": job.job_id,
                    "incident_id": job.incident_id,
                    "site_id": job.site_id,
                    "title": job.title,
                    "activity": job.activity,
                    "sequence": sequence,
                    "band": job.band,
                    "rank_position": job.rank_position,
                    "depart_at": timing.depart,
                    "arrive_at": timing.arrive,
                    "start_at": timing.start,
                    "finish_at": timing.finish,
                    "travel_minutes": timing.travel,
                    "service_minutes": timing.service,
                    "deadline_at": job.deadline,
                    "deadline_met": not timing.late,
                    "constraints_checked": [
                        "authorised_service",
                        "area_permission",
                        "qualifications",
                        "tools_parts",
                        "crew_size_member_availability",
                        "shift_and_breaks",
                        "access_window",
                        "locked_commitments",
                        "dependencies",
                        "no_overlap",
                    ],
                    "reason": self._reason(job, crews[crew_id], fifo),
                }
                (remote if job.activity in REMOTE else visits).append(item)
        urgent = []
        for job in inputs.jobs:
            if job.band == "P0":
                urgent.append(
                    {
                        "job_id": job.job_id,
                        "incident_id": job.incident_id,
                        "band": job.band,
                        "reason": "emergency_escalation_required: a scheduling estimate does not "
                        "substitute local emergency handling",
                    }
                )
            elif job.band == "P1" and job.deadline and job.deadline < inputs.now:
                urgent.append(
                    {
                        "job_id": job.job_id,
                        "incident_id": job.incident_id,
                        "band": job.band,
                        "reason": "response_deadline_already_overdue: scheduled as early as "
                        "feasible; escalate",
                    }
                )
            elif job.job_id in unassigned and job.band == "P1":
                urgent.append(
                    {
                        "job_id": job.job_id,
                        "incident_id": job.incident_id,
                        "band": job.band,
                        "reason": "urgent_job_unserved: escalate ("
                        + unassigned[job.job_id][0]
                        + ")",
                    }
                )
        return {
            "method": "fifo_baseline" if fifo else "feasible_heuristic_proposal",
            "visits": visits,
            "remote_items": remote,
            "unassigned": [
                {
                    "job_id": job_id,
                    "incident_id": self._jobs[job_id].incident_id,
                    "site_id": self._jobs[job_id].site_id,
                    "title": self._jobs[job_id].title,
                    "band": self._jobs[job_id].band,
                    "activity": self._jobs[job_id].activity,
                    "reasons": reasons[:12],
                }
                for job_id, reasons in sorted(unassigned.items())
            ],
            "urgent_exceptions": urgent,
            "metrics": self._metrics(timings, unassigned),
            "evaluations": self.evaluations,
        }

    @staticmethod
    def _reason(job: JobInput, crew: CrewInput, fifo: bool) -> str:
        if fifo:
            return (
                "FIFO baseline: first eligible crew by name, appended in arrival order"
            )
        parts = [f"{job.band} processed before lower bands"]
        if job.qualifications:
            parts.append("qualified: " + ", ".join(sorted(job.qualifications)))
        parts.append(f"authorised for {job.service_key}")
        parts.append("best feasible insertion (timeliness, delay loss, travel)")
        return "; ".join(parts)

    def _metrics(self, timings, unassigned) -> dict:
        by_band = {b: {"jobs": 0, "served": 0, "timely": 0} for b in BANDS}
        response = {b: [] for b in BANDS}
        for job in self.inputs.jobs:
            by_band[job.band]["jobs"] += 1
        for ts in timings.values():
            for t in ts:
                job = self._jobs.get(t.job_id)
                if not job or t.fixed:
                    continue
                by_band[job.band]["served"] += 1
                by_band[job.band]["timely"] += 0 if t.late else 1
                response[job.band].append(
                    (t.start - self.inputs.now).total_seconds() / 60
                )
        unserved_loss = sum(
            (self._jobs[j].expected_lost_kwh_per_day or 0)
            * (self.inputs.horizon_end - self.inputs.now).total_seconds()
            / 86400
            for j in unassigned
        )
        return {
            "jobs_served": sum(v["served"] for v in by_band.values()),
            "jobs_total": len(self.inputs.jobs),
            "travel_minutes": self._travel(timings),
            "by_band": by_band,
            "mean_response_minutes": {
                b: round(sum(v) / len(v), 1) if v else None for b, v in response.items()
            },
            "delay_loss_kwh": round(self._delay_loss(timings) + unserved_loss, 3),
            "overtime_minutes": 0,
        }


def completeness(inputs: PlanningInputs) -> dict:
    nodes = {c.base_node for c in inputs.crews if c.kind != "remote_desk"} | {
        j.node for j in inputs.jobs if j.activity == FIELD
    }
    nodes.discard(None)
    pairs = [(a, b) for a in nodes for b in nodes if a < b]
    known = sum(1 for a, b in pairs if travel_minutes(inputs, a, b) is not None)
    jobs = {j.job_id: job_reasons(j) for j in inputs.jobs}
    crews = {
        c.crew_id: [
            r
            for r, missing in (
                ("crew_shift_unknown", c.shift is None),
                (
                    "crew_location_unknown",
                    c.base_node is None and c.kind != "remote_desk",
                ),
            )
            if missing
        ]
        for c in inputs.crews
    }
    complete = all(not v for v in jobs.values()) and all(not v for v in crews.values())
    return {
        "status": "complete" if complete and known == len(pairs) else "partial",
        "jobs_missing": {k: v for k, v in jobs.items() if v},
        "crews_missing": {k: v for k, v in crews.items() if v},
        "travel_pairs_known": known,
        "travel_pairs_needed": len(pairs),
        "travel_source": inputs.travel_source,
    }


def compare(heuristic: dict, baseline: dict) -> dict:
    h, b = heuristic["metrics"], baseline["metrics"]
    findings = []

    def note(label, hv, bv, better_low=True):
        if hv == bv:
            findings.append(f"{label}: no difference ({hv})")
        elif (hv < bv) == better_low:
            findings.append(f"{label}: heuristic better ({hv} vs baseline {bv})")
        else:
            findings.append(f"{label}: baseline better ({bv} vs heuristic {hv})")

    note("jobs served", h["jobs_served"], b["jobs_served"], better_low=False)
    for band in BANDS:
        if h["by_band"][band]["jobs"]:
            note(
                f"{band} timely",
                h["by_band"][band]["timely"],
                b["by_band"][band]["timely"],
                better_low=False,
            )
    note("travel minutes", h["travel_minutes"], b["travel_minutes"])
    note("delay loss kWh", h["delay_loss_kwh"], b["delay_loss_kwh"])
    improved = any("heuristic better" in f for f in findings)
    worse = any("baseline better" in f for f in findings)
    return {
        "baseline_definition": "Feasible FIFO baseline under identical hard constraints: jobs "
        "in arrival order (dependencies first), first eligible crew by name, appended to the "
        "end of its route; no insertion search and no local improvement.",
        "heuristic": h,
        "baseline": b,
        "findings": findings,
        "verdict": "heuristic_improves"
        if improved and not worse
        else ("mixed" if improved else "no_improvement"),
    }


def plan(inputs: PlanningInputs) -> dict:
    heuristic = Planner(inputs).run()
    baseline = Planner(inputs).run(fifo=True)
    return {
        **heuristic,
        "label": "feasible heuristic proposal (not a guaranteed optimum)",
        "travel_source": inputs.travel_source,
        "input_completeness": completeness(inputs),
        "monitoring": inputs.monitoring,
        "baseline": {
            "visits": baseline["visits"],
            "remote_items": baseline["remote_items"],
            "unassigned": baseline["unassigned"],
        },
        "comparison": compare(heuristic, baseline),
        "input_digest": inputs.digest(),
    }
