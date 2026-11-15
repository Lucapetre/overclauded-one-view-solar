"""Multi-device incident correlation: observation -> condition -> hypothesis -> episode.

Pure, explainable rules over an `EvidenceBundle` (supplied by an `EvidenceSource` adapter at
one analytical time). Each rule declares its required metrics, capability gates, compatible
boundary/plane, aligned 15-minute intervals, coverage, persistence/hysteresis, thresholds and
explanation text; when its evidence does not exist it returns ``not_evaluated`` with reasons and
never invents the missing corroboration. Thresholds are DEMO POLICY values, not manufacturer
limits, grid-code settings or a diagnosis. Results are candidate hypotheses for human review.

Evidence confidence is ordinal (no calibrated probabilities):

* ``reported``     - the source device or collector itself reports the alarm/state/error;
* ``corroborated`` - at least two independent physical instruments support the condition
                     (inverter/gateway mirrors of one measurement count once);
* ``suspected``    - one independent measured source supports it;
* ``insufficient`` - required evidence is partial; no episode is opened.

Rows later than the analytical time are dropped (`EvidenceBundle.clipped`) before any rule
runs. Runtime code never reads evaluation-only labels (tests guard this).
"""

from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

RULESET_VERSION = "correlation-demo-2026.11.15-1"
LOCAL = ZoneInfo("Europe/Bucharest")
SLOT = timedelta(minutes=15)

CONFIDENCE = ("reported", "corroborated", "suspected", "insufficient")
RESPONSIBILITY = (
    "customer_installation_service",
    "distributor_network_review",
    "monitoring_provider",
    "unknown",
)
ACTIONS = (
    "monitor",
    "remote_review",
    "remote_troubleshooting",
    "field_visit",
    "external_review",
)

# Rule library (DEMO POLICY). A change of any value is a new revision.
RULES: dict[str, dict] = {
    "weather_consistent_drop": {
        "revision": 1,
        "family": "Production",
        "title": "Weather-consistent production drop",
        "required_metrics": [
            "ac_pv_power_kw (15-min mean)",
            "poa_irradiance_wm2 (15-min mean)",
        ],
        "capability_gates": ["installed_kwp_known", "poa_on_compatible_plane"],
        "boundary": "AC PV output vs POA irradiance on the module plane",
        "window": "last complete local day vs up to 5 earlier complete days",
        "coverage": "daylight frames (POA >= 50 W/m2) with valid PV >= 90 %",
        "thresholds": {
            "pv_drop_min": 0.30,
            "poa_drop_min": 0.25,
            "pr_ratio_min": 0.85,
            "plane_tilt_tolerance_deg": 5,
            "plane_azimuth_tolerance_deg": 10,
            "daylight_wm2": 50,
            "min_daylight_frames": 20,
            "min_coverage": 0.9,
            "min_baseline_days": 2,
        },
        "persistence": "one complete day; recovers on the next complete normal day",
        "explanation": "Production fell together with measured plane-of-array irradiance; the "
        "performance ratio stayed normal, so the drop is consistent with weather.",
        "cannot_prove": "Does not rule out every equipment issue.",
    },
    "persistent_underperformance": {
        "revision": 1,
        "family": "Production",
        "title": "Persistent production underperformance vs measured POA",
        "required_metrics": [
            "ac_pv_power_kw (15-min mean)",
            "poa_irradiance_wm2 (15-min mean)",
        ],
        "capability_gates": ["installed_kwp_known", "poa_on_compatible_plane"],
        "boundary": "AC PV output vs POA irradiance on the module plane",
        "window": "valid daylight frames of the last 24 h; baseline = median daily PR of up "
        "to 7 complete earlier days",
        "coverage": "frames with POA >= 200 W/m2 and both values valid (coverage >= 0.5)",
        "thresholds": {
            "pr_ratio_trigger": 0.75,
            "pr_ratio_clear": 0.85,
            "persistence_frames": 8,
            "irradiance_wm2": 200,
            "min_baseline_days": 2,
        },
        "persistence": ">= 8 consecutive valid daylight frames (2 h) below the trigger; "
        "clears after >= 8 consecutive valid frames above the clear ratio",
        "explanation": "Measured AC production stayed well below what the site's own baseline "
        "performance ratio predicts for the measured POA irradiance.",
        "cannot_prove": "Does not identify a failed panel/string without string-level sensors.",
    },
    "battery_operational_restriction": {
        "revision": 1,
        "family": "Battery",
        "title": "Battery-related operational restriction (BMS-reported)",
        "required_metrics": [
            "battery_alarm_raw (documented channels)",
            "BMS limit registers",
        ],
        "capability_gates": ["battery_alarms_available or battery_limits_available"],
        "boundary": "battery service (DC battery boundary)",
        "window": "latest complete 15-min frames",
        "coverage": "frames present for the documented alarm/limit fields",
        "thresholds": {"persistence_frames": 2, "clear_frames": 4},
        "persistence": "alarm != 0 or limit below declared nominal in >= 2 consecutive frames; "
        "clears after 4 consecutive frames with no alarm and nominal limits",
        "explanation": "The battery management system reports an alarm and/or a reduced power "
        "limit; battery-assisted flexibility is removed until the service reviews it.",
        "cannot_prove": "Does not establish thermal runaway, failed cells or DSO ownership.",
    },
    "pcc_voltage_sustained": {
        "revision": 1,
        "family": "Voltage",
        "title": "Sustained phase-voltage anomaly at the PCC",
        "required_metrics": [
            "phase_voltage_v at a declared PCC meter (15-min mean/max)"
        ],
        "capability_gates": ["pcc_phase_voltage"],
        "boundary": "grid_pcc",
        "window": "latest complete 15-min frames",
        "coverage": "frame coverage >= 0.8",
        "thresholds": {"mean_above_v": 253.0, "clear_max_v": 253.0, "clear_frames": 2},
        "persistence": "any phase 15-min mean above 253 V (>= 15 min sustained; demo policy "
        "230 V + 10 %, illustrative); clears after 2 frames with every phase max <= 253 V",
        "explanation": "A PCC meter measured a sustained phase voltage above the demo review "
        "band; measured duration and range are attached for a voltage review.",
        "cannot_prove": "Sparse RMS samples do not establish transient compliance, fault "
        "location or that the voltage caused an inverter shutdown.",
    },
    "shared_monitoring_path": {
        "revision": 1,
        "family": "Telemetry",
        "title": "Shared monitoring-path issue (one declared collector)",
        "required_metrics": [
            "collection attempt outcomes",
            "per-endpoint frame freshness",
        ],
        "capability_gates": ["declared collector serving >= 2 sites"],
        "boundary": "monitoring path (collector), not the electrical installation",
        "window": "collection attempts up to the analytical time",
        "coverage": "failed attempts with documented error classes",
        "thresholds": {"min_sites": 2, "min_failed_attempts": 3, "recovery_frames": 2},
        "persistence": ">= 3 failed attempts on >= 2 sites of one collector, overlapping; "
        "clears after 2 successful frames on every affected site after the last failure",
        "explanation": "Several feeds behind one declared collector failed at overlapping "
        "times; one remote troubleshooting episode covers all of them.",
        "cannot_prove": "Missing feeds alone do not establish loss of electricity.",
    },
    "common_upstream": {
        "revision": 1,
        "family": "Area event",
        "title": "Possible common upstream episode (supplied relationship)",
        "required_metrics": ["compatible child anomalies on >= 2 related sites"],
        "capability_gates": ["explicitly supplied topology relationship"],
        "boundary": "supplied common feeder/asset relationship",
        "window": "overlapping active child conditions",
        "coverage": "child conditions matched",
        "thresholds": {"min_sites": 2},
        "persistence": "while >= 2 related children stay matched",
        "explanation": "Compatible anomalies on sites that share an explicitly supplied "
        "feeder/asset relationship; child evidence and uncertainty are retained.",
        "cannot_prove": "Spatial proximity or map area membership alone is not electrical "
        "topology; the common cause is a hypothesis.",
    },
}
UPSTREAM_COMPATIBLE = ("pcc_voltage_sustained", "persistent_underperformance")


def rule_hash(rule_id: str) -> str:
    text = json.dumps(RULES[rule_id], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# ---------------------------------------------------------------- evidence model


@dataclass(frozen=True)
class Sample:
    """One aligned 15-minute frame value of one series (UTC)."""

    start: datetime
    value: float | None
    evidence_id: str
    coverage: float = 1.0

    @property
    def end(self) -> datetime:
        return self.start + SLOT


@dataclass
class Series:
    """A series from one physical instrument. `source_id` identifies the instrument;
    `mirror_of` names the instrument it copies (gateway/inverter mirror): not independent."""

    source_id: str
    samples: list[Sample] = field(default_factory=list)
    mirror_of: str | None = None
    label: str = ""

    def clipped(self, as_of: datetime) -> Series:
        return replace(self, samples=[s for s in self.samples if s.end <= as_of])

    def independent_id(self) -> str:
        return self.mirror_of or self.source_id


@dataclass
class SiteEvidence:
    site_id: str
    label: str = ""
    installed_kwp: float | None = None
    module_planes: list[tuple[float, float]] = field(default_factory=list)
    pv: Series | None = None
    poa: Series | None = None
    poa_plane: tuple[float, float] | None = None
    poa_basis: str | None = None  # site_sensor:<asset> | area_station:<asset>
    pcc_voltage_mean: dict[str, Series] = field(default_factory=dict)
    pcc_voltage_max: dict[str, Series] = field(default_factory=dict)
    pcc_asset_id: str | None = None
    inverter_voltage: dict[str, Series] = field(default_factory=dict)
    battery_asset_id: str | None = None
    battery_alarms: dict[str, Series] = field(default_factory=dict)
    battery_limits: dict[str, Series] = field(default_factory=dict)
    battery_nominal: dict[str, float] = field(default_factory=dict)
    capabilities: dict[str, str] = field(default_factory=dict)
    # Service-boundary registry: boundary -> (responsibility category, named service).
    responsibility: dict[str, tuple[str, str]] = field(default_factory=dict)

    def clipped(self, as_of: datetime) -> SiteEvidence:
        def clip(value):
            if isinstance(value, Series):
                return value.clipped(as_of)
            if (
                isinstance(value, dict)
                and value
                and all(isinstance(v, Series) for v in value.values())
            ):
                return {k: v.clipped(as_of) for k, v in value.items()}
            return value

        return replace(self, **{k: clip(v) for k, v in self.__dict__.items()})


@dataclass(frozen=True)
class CollectionFailure:
    at: datetime
    site_id: str
    failure_class: str
    evidence_id: str


@dataclass
class CollectorEvidence:
    collector_id: str
    site_ids: list[str]
    failures: list[CollectionFailure] = field(default_factory=list)
    # Successful frames on the collector's path per site (evidence of recovery).
    successes: dict[str, list[Sample]] = field(default_factory=dict)
    responsible: tuple[str, str] = ("monitoring_provider", "monitoring provider")

    def clipped(self, as_of: datetime) -> CollectorEvidence:
        return replace(
            self,
            failures=[f for f in self.failures if f.at <= as_of],
            successes={
                k: [s for s in v if s.end <= as_of] for k, v in self.successes.items()
            },
        )


@dataclass(frozen=True)
class TopologyRelation:
    """An EXPLICITLY supplied common feeder/asset relationship (never inferred)."""

    relation_id: str
    kind: str
    site_ids: tuple[str, ...]
    basis: str
    responsible: tuple[str, str] = ("distributor_network_review", "distributor review")


@dataclass
class EvidenceBundle:
    as_of: datetime
    sites: dict[str, SiteEvidence] = field(default_factory=dict)
    collectors: list[CollectorEvidence] = field(default_factory=list)
    relations: list[TopologyRelation] = field(default_factory=list)
    source: str = "fixture"

    def clipped(self, as_of: datetime | None = None) -> EvidenceBundle:
        """Drop every row that ends after the analytical time (no future evidence)."""
        moment = as_of or self.as_of
        return replace(
            self,
            as_of=moment,
            sites={k: v.clipped(moment) for k, v in self.sites.items()},
            collectors=[c.clipped(moment) for c in self.collectors],
        )


class EvidenceSource(Protocol):
    """Adapter interface: returns the evidence known at `as_of` (never later rows)."""

    def bundle(self, as_of: datetime) -> EvidenceBundle: ...


class StaticEvidenceSource:
    """Fixture adapter used by tests and offline runs."""

    def __init__(self, bundle: EvidenceBundle):
        self._bundle = bundle

    def bundle(self, as_of: datetime) -> EvidenceBundle:
        return self._bundle.clipped(as_of)


# ---------------------------------------------------------------- results


@dataclass(frozen=True)
class EvidenceRef:
    evidence_id: str
    kind: str
    source_id: str
    independent_group: str
    observed_from: datetime | None = None
    observed_to: datetime | None = None
    summary: str = ""
    mirror_of: str | None = None

    def as_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind,
            "source_id": self.source_id,
            "independent_group": self.independent_group,
            "mirror_of": self.mirror_of,
            "observed_from": _iso(self.observed_from),
            "observed_to": _iso(self.observed_to),
            "summary": self.summary,
        }


@dataclass
class Hypothesis:
    interpretation: str
    uncertainty: str
    alternatives: list[str]
    cannot_prove: str

    def as_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class ConditionResult:
    rule_id: str
    identity: str
    status: str  # matched | clear | indeterminate | not_evaluated
    site_ids: list[str]
    reason_codes: list[str] = field(default_factory=list)
    asset_ids: list[str] = field(default_factory=list)
    window_start: datetime | None = None
    window_end: datetime | None = None
    first_observed: datetime | None = None
    metrics: dict = field(default_factory=dict)
    evidence: list[EvidenceRef] = field(default_factory=list)
    hypothesis: Hypothesis | None = None
    confidence: str = "insufficient"
    confidence_basis: str = ""
    action: str = "monitor"
    responsibility: str = "unknown"
    responsibility_basis: str = "no service-boundary registry entry"
    service_key: str | None = None  # named responsible service (planner authorization)
    impact: dict = field(default_factory=dict)
    children: list[str] = field(default_factory=list)  # identities (parent episodes)

    @property
    def rule_revision(self) -> int:
        return RULES[self.rule_id]["revision"]

    @property
    def family(self) -> str:
        return RULES[self.rule_id]["family"]

    @property
    def title(self) -> str:
        return RULES[self.rule_id]["title"]

    def summary(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "rule_revision": self.rule_revision,
            "identity": self.identity,
            "status": self.status,
            "site_ids": self.site_ids,
            "reason_codes": self.reason_codes,
        }


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat(timespec="seconds") if value else None


def independent_sources(refs: list[EvidenceRef]) -> set[str]:
    """Distinct physical instruments behind evidence; mirrors collapse to their original."""
    return {ref.mirror_of or ref.independent_group for ref in refs}


def confidence_from(refs: list[EvidenceRef], reported: bool) -> tuple[str, str]:
    if reported:
        return "reported", "the source device/collector reports the state itself"
    sources = independent_sources(refs)
    if len(sources) >= 2:
        return (
            "corroborated",
            f"{len(sources)} independent instruments: {', '.join(sorted(sources))}",
        )
    if sources:
        return "suspected", f"one independent instrument: {next(iter(sources))}"
    return "insufficient", "no usable evidence"


def _ref(series: Series, sample: Sample, kind: str, summary: str = "") -> EvidenceRef:
    return EvidenceRef(
        evidence_id=sample.evidence_id,
        kind=kind,
        source_id=series.source_id,
        independent_group=series.independent_id(),
        observed_from=sample.start,
        observed_to=sample.end,
        summary=summary,
        mirror_of=series.mirror_of,
    )


def _responsibility(site: SiteEvidence, boundary: str) -> tuple[str, str]:
    category, service = site.responsibility.get(boundary, ("unknown", ""))
    if category not in RESPONSIBILITY:
        category = "unknown"
    basis = (
        f"service-boundary registry: {boundary} -> {service or category}"
        if boundary in site.responsibility
        else f"no service-boundary registry entry for {boundary}"
    )
    return category, basis


def _service(site: SiteEvidence, boundary: str) -> str | None:
    entry = site.responsibility.get(boundary)
    return entry[1] if entry and entry[1] else (entry[0] if entry else None)


def _not_evaluated(rule_id, identity, site_ids, *reasons) -> ConditionResult:
    return ConditionResult(rule_id, identity, "not_evaluated", site_ids, list(reasons))


# ---------------------------------------------------------------- time helpers


def local_day(moment: datetime):
    return moment.astimezone(LOCAL).date()


def day_bounds(day) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=LOCAL)
    end = start + timedelta(days=1)
    # Wall-clock local midnight to local midnight (DST-safe: built in local time).
    end = datetime(end.year, end.month, end.day, tzinfo=LOCAL)
    return start.astimezone(UTC), end.astimezone(UTC)


def _by_start(series: Series | None) -> dict[datetime, Sample]:
    if series is None:
        return {}
    return {
        s.start: s for s in series.samples if s.value is not None and s.coverage >= 0.5
    }


def _plane_compatible(site: SiteEvidence, tolerances: dict) -> tuple[bool, str | None]:
    if site.poa is None or site.poa_plane is None:
        return False, "no_poa_irradiance_sensor"
    if not site.module_planes:
        return False, "module_plane_unknown"
    tilt, azimuth = site.poa_plane
    for plane_tilt, plane_az in site.module_planes:
        if (
            abs(plane_tilt - tilt) > tolerances["plane_tilt_tolerance_deg"]
            or abs(plane_az - azimuth) > tolerances["plane_azimuth_tolerance_deg"]
        ):
            return False, "sensor_plane_differs_from_module_plane"
    return True, None


def _pv_gates(rule_id: str, site: SiteEvidence) -> list[str]:
    reasons = []
    if not site.installed_kwp:
        reasons.append("installed_capacity_unknown")
    if site.pv is None or not site.pv.samples:
        reasons.append("no_ac_production_boundary_data")
    ok, why = _plane_compatible(site, RULES["weather_consistent_drop"]["thresholds"])
    if not ok:
        reasons.append(why)
    return reasons


def _daily(site: SiteEvidence, day, daylight_wm2: float):
    """Daily PV kWh, POA kWh/m2, PR and coverage over aligned frames of one local day."""
    lower, upper = day_bounds(day)
    pv, poa = _by_start(site.pv), _by_start(site.poa)
    daylight = [
        s for t, s in poa.items() if lower <= t < upper and s.value >= daylight_wm2
    ]
    if not daylight:
        return None
    paired = [s for s in daylight if s.start in pv]
    pv_kwh = sum(pv[t].value * 0.25 for t in pv if lower <= t < upper)
    poa_kwh = sum(s.value * 0.25 / 1000 for s in daylight)
    pr = pv_kwh / (site.installed_kwp * poa_kwh) if poa_kwh > 0 else None
    return {
        "day": day.isoformat(),
        "pv_kwh": round(pv_kwh, 3),
        "poa_kwh_m2": round(poa_kwh, 3),
        "pr": round(pr, 4) if pr is not None else None,
        "daylight_frames": len(daylight),
        "coverage": round(len(paired) / len(daylight), 3),
        "evidence": [pv[s.start].evidence_id for s in paired[:1]]
        + [s.evidence_id for s in daylight[:1]],
    }


# ---------------------------------------------------------------- rules


def weather_consistent_drop(site: SiteEvidence, as_of: datetime) -> ConditionResult:
    rule_id = "weather_consistent_drop"
    identity = f"{rule_id}:{site.site_id}"
    t = RULES[rule_id]["thresholds"]
    gates = _pv_gates(rule_id, site)
    if gates:
        return _not_evaluated(rule_id, identity, [site.site_id], *gates)
    last = local_day(as_of) - timedelta(days=1)
    days = []
    for offset in range(0, 6):
        stats = _daily(site, last - timedelta(days=offset), t["daylight_wm2"])
        if (
            stats
            and stats["daylight_frames"] >= t["min_daylight_frames"]
            and stats["coverage"] >= t["min_coverage"]
            and stats["pr"] is not None
        ):
            days.append(stats)
        elif offset == 0:
            return _not_evaluated(
                rule_id, identity, [site.site_id], "insufficient_daylight_coverage"
            )
    target, baseline = days[0], days[1:]
    if len(baseline) < t["min_baseline_days"]:
        return _not_evaluated(
            rule_id, identity, [site.site_id], "insufficient_baseline_days"
        )
    base_pv = statistics.median(d["pv_kwh"] for d in baseline)
    base_poa = statistics.median(d["poa_kwh_m2"] for d in baseline)
    base_pr = statistics.median(d["pr"] for d in baseline)
    pv_drop = 1 - target["pv_kwh"] / base_pv if base_pv > 0 else 0
    poa_drop = 1 - target["poa_kwh_m2"] / base_poa if base_poa > 0 else 0
    pr_ratio = target["pr"] / base_pr if base_pr else 0
    lower, upper = day_bounds(last)
    metrics = {
        "day": target["day"],
        "pv_kwh": target["pv_kwh"],
        "baseline_pv_kwh": round(base_pv, 3),
        "poa_kwh_m2": target["poa_kwh_m2"],
        "baseline_poa_kwh_m2": round(base_poa, 3),
        "pv_drop": round(pv_drop, 3),
        "poa_drop": round(poa_drop, 3),
        "pr": target["pr"],
        "baseline_pr": round(base_pr, 4),
        "baseline_days": [d["day"] for d in baseline],
        "poa_basis": site.poa_basis,
    }
    matched = (
        pv_drop >= t["pv_drop_min"]
        and poa_drop >= t["poa_drop_min"]
        and pr_ratio >= t["pr_ratio_min"]
    )
    result = ConditionResult(
        rule_id,
        identity,
        "matched" if matched else "clear",
        [site.site_id],
        ["pv_and_poa_dropped_pr_normal"]
        if matched
        else ["daily_production_consistent"],
        window_start=lower,
        window_end=upper,
        first_observed=lower,
        metrics=metrics,
    )
    if not matched:
        return result
    refs = [
        EvidenceRef(
            target["evidence"][0],
            "pv_daily_energy",
            site.pv.source_id,
            site.pv.independent_id(),
            lower,
            upper,
            f"PV {target['pv_kwh']} kWh vs baseline {round(base_pv, 1)} kWh",
            site.pv.mirror_of,
        ),
        EvidenceRef(
            target["evidence"][-1],
            "poa_daily_insolation",
            site.poa.source_id,
            site.poa.independent_id(),
            lower,
            upper,
            f"POA {target['poa_kwh_m2']} kWh/m2 vs baseline {round(base_poa, 2)}",
            site.poa.mirror_of,
        ),
    ]
    result.evidence = refs
    result.confidence, result.confidence_basis = confidence_from(refs, False)
    result.hypothesis = Hypothesis(
        "Weather-consistent variation: production and measured POA irradiance fell together "
        "while the performance ratio stayed normal. Retain monitoring; normally no field visit.",
        "Daily totals only; a short equipment outage within the day could be masked.",
        ["partial shading or soiling coinciding with clouds", "sensor soiling"],
        RULES[rule_id]["cannot_prove"],
    )
    result.action = "monitor"
    result.responsibility, result.responsibility_basis = _responsibility(
        site, "pv_installation"
    )
    result.service_key = _service(site, "pv_installation")
    result.impact = {
        "expected_lost_kwh_per_day": None,
        "lost_kwh_reason": "weather_variation_not_recoverable_by_service",
        "recoverable": False,
    }
    return result


def persistent_underperformance(site: SiteEvidence, as_of: datetime) -> ConditionResult:
    rule_id = "persistent_underperformance"
    identity = f"{rule_id}:{site.site_id}"
    t = RULES[rule_id]["thresholds"]
    gates = _pv_gates(rule_id, site)
    if gates:
        return _not_evaluated(rule_id, identity, [site.site_id], *gates)
    window_start = as_of - timedelta(hours=24)
    first_day = local_day(window_start)
    baseline = []
    for offset in range(1, 8):
        stats = _daily(site, first_day - timedelta(days=offset), 50)
        if stats and stats["coverage"] >= 0.9 and stats["daylight_frames"] >= 20:
            baseline.append(stats)
    if len(baseline) < t["min_baseline_days"]:
        return _not_evaluated(
            rule_id, identity, [site.site_id], "insufficient_baseline_days"
        )
    base_pr = statistics.median(d["pr"] for d in baseline)
    pv, poa = _by_start(site.pv), _by_start(site.poa)
    frames = []
    for start in sorted(poa):
        sample = poa[start]
        if (
            start < window_start
            or sample.end > as_of
            or sample.value < t["irradiance_wm2"]
        ):
            continue
        if start not in pv:
            continue
        pr = pv[start].value / (site.installed_kwp * sample.value / 1000)
        frames.append((start, pr, pv[start], sample))
    if len(frames) < t["persistence_frames"]:
        return _not_evaluated(
            rule_id, identity, [site.site_id], "insufficient_valid_daylight_frames"
        )

    def trailing(predicate):
        run = []
        for frame in reversed(frames):
            if not predicate(frame[1] / base_pr):
                break
            run.append(frame)
        return list(reversed(run))

    low = trailing(lambda ratio: ratio < t["pr_ratio_trigger"])
    high = trailing(lambda ratio: ratio >= t["pr_ratio_clear"])
    metrics = {
        "baseline_pr": round(base_pr, 4),
        "baseline_days": [d["day"] for d in baseline],
        "valid_frames": len(frames),
        "poa_basis": site.poa_basis,
    }
    if len(high) >= t["persistence_frames"]:
        return ConditionResult(
            rule_id,
            identity,
            "clear",
            [site.site_id],
            ["pr_back_to_baseline"],
            window_start=frames[0][0],
            window_end=as_of,
            metrics=metrics,
        )
    if len(low) < t["persistence_frames"]:
        return ConditionResult(
            rule_id,
            identity,
            "indeterminate",
            [site.site_id],
            ["deficit_not_persistent_or_in_hysteresis_band"],
            window_start=frames[0][0],
            window_end=as_of,
            metrics=metrics,
        )
    observed = statistics.median(frame[1] for frame in low)
    expected_kwh = sum(
        site.installed_kwp * f[3].value / 1000 * base_pr * 0.25 for f in low
    )
    measured_kwh = sum(f[2].value * 0.25 for f in low)
    base_daily = statistics.median(d["pv_kwh"] for d in baseline)
    lost_per_day = max(0.0, base_daily * (1 - observed / base_pr))
    metrics.update(
        observed_pr=round(observed, 4),
        pr_ratio=round(observed / base_pr, 3),
        deficit_frames=len(low),
        window_expected_kwh=round(expected_kwh, 2),
        window_measured_kwh=round(measured_kwh, 2),
    )
    refs = [_ref(site.pv, low[0][2], "pv_frame", "first deficit frame")]
    refs += [_ref(site.pv, low[-1][2], "pv_frame", "latest deficit frame")]
    refs += [
        _ref(site.poa, low[-1][3], "poa_frame", "POA normal for the deficit frame")
    ]
    confidence, basis = confidence_from(refs, False)
    category, responsibility_basis = _responsibility(site, "pv_installation")
    return ConditionResult(
        rule_id,
        identity,
        "matched",
        [site.site_id],
        ["pr_below_baseline_persistent", "inverter_state_labels_not_established"],
        window_start=low[0][0],
        window_end=low[-1][0] + SLOT,
        first_observed=low[0][0],
        metrics=metrics,
        evidence=refs,
        hypothesis=Hypothesis(
            "Unexplained production underperformance: measured POA irradiance is normal but "
            "AC production is far below the site's own baseline ratio. Propose a remote "
            "review, then a visit if unresolved.",
            "Baseline from the site's own earlier days; a changed module plane or a new "
            "shading object would also lower the ratio.",
            [
                "string or connector fault",
                "inverter derating",
                "new shading or soiling",
                "sensor misalignment",
            ],
            RULES[rule_id]["cannot_prove"],
        ),
        confidence=confidence,
        confidence_basis=basis,
        action="field_visit",
        responsibility=category,
        responsibility_basis=responsibility_basis,
        service_key=_service(site, "pv_installation"),
        impact={
            "expected_lost_kwh_per_day": round(lost_per_day, 2),
            "lost_kwh_basis": "median baseline daily PV energy x (1 - observed PR / "
            "baseline PR); assumes future days resemble the baseline weather",
            "recoverable": True,
            "uncertainty": "weather of the coming days; baseline of "
            f"{len(baseline)} earlier days",
        },
    )


ALARM_CLEAR = (0, 0.0)


def battery_operational_restriction(
    site: SiteEvidence, as_of: datetime
) -> ConditionResult:
    rule_id = "battery_operational_restriction"
    identity = f"{rule_id}:{site.battery_asset_id or site.site_id}"
    t = RULES[rule_id]["thresholds"]
    if not site.battery_asset_id:
        return _not_evaluated(rule_id, identity, [site.site_id], "no_battery_asset")
    alarms_ok = site.capabilities.get("battery_alarms_available") == "available"
    limits_ok = site.capabilities.get("battery_limits_available") == "available"
    if not (alarms_ok or limits_ok):
        return _not_evaluated(
            rule_id, identity, [site.site_id], "battery_alarms_and_limits_not_declared"
        )

    def recent(series: Series, count: int) -> list[Sample] | None:
        latest = [s for s in series.samples if s.end <= as_of][-count:]
        if len(latest) < count or any(s.value is None for s in latest):
            return None
        if any(
            (b.start - a.start) != SLOT
            for a, b in zip(latest, latest[1:], strict=False)
        ):
            return None  # not consecutive
        if (as_of - latest[-1].end) > 2 * SLOT:
            return None  # stale feed: no decision either way
        return latest

    active, refs, missing = [], [], False
    first = None
    for channel, series in sorted(site.battery_alarms.items()) if alarms_ok else []:
        latest = recent(series, t["persistence_frames"])
        if latest is None:
            missing = True
            continue
        if all(s.value not in ALARM_CLEAR for s in latest):
            active.append(f"alarm:{channel}")
            run = [s for s in series.samples if s.end <= as_of]
            start = latest[0].start
            for sample in reversed(run):
                if sample.value in ALARM_CLEAR or sample.value is None:
                    break
                start = sample.start
            first = min(first, start) if first else start
            refs.append(
                _ref(series, latest[-1], "battery_alarm", f"{channel} reported")
            )
    for metric, series in sorted(site.battery_limits.items()) if limits_ok else []:
        nominal = site.battery_nominal.get(metric)
        latest = recent(series, t["persistence_frames"])
        if nominal is None:
            continue
        if latest is None:
            missing = True
            continue
        if all(s.value < nominal for s in latest):
            active.append(f"derated:{metric}")
            refs.append(
                _ref(
                    series,
                    latest[-1],
                    "battery_limit",
                    f"{metric} {latest[-1].value} < declared nominal {nominal}",
                )
            )
    if not active:
        if missing:
            return ConditionResult(
                rule_id,
                identity,
                "indeterminate",
                [site.site_id],
                ["battery_feed_missing_not_resolved"],
                asset_ids=[site.battery_asset_id],
            )
        clear = all(
            (latest := recent(series, t["clear_frames"])) is not None
            and all(s.value in ALARM_CLEAR for s in latest)
            for series in site.battery_alarms.values()
        ) and all(
            (latest := recent(series, t["clear_frames"])) is not None
            and all(s.value >= site.battery_nominal.get(metric, 0) for s in latest)
            for metric, series in site.battery_limits.items()
        )
        return ConditionResult(
            rule_id,
            identity,
            "clear" if clear else "indeterminate",
            [site.site_id],
            ["no_alarm_nominal_limits"] if clear else ["recovery_not_yet_confirmed"],
            asset_ids=[site.battery_asset_id],
        )
    category, basis = _responsibility(site, "battery_service")
    return ConditionResult(
        rule_id,
        identity,
        "matched",
        [site.site_id],
        ["bms_reported_restriction", *active, "battery_flexibility_removed"],
        asset_ids=[site.battery_asset_id],
        window_start=first,
        window_end=as_of,
        first_observed=first,
        metrics={"active": active},
        evidence=refs,
        hypothesis=Hypothesis(
            "Battery-related operational restriction reported by the BMS; battery-assisted "
            "flexibility is removed and the responsible battery service should review it.",
            "Reported alarm codes are taken as documented; the cause is not established.",
            [
                "sensor or communication fault inside the BMS",
                "temporary protective derating",
            ],
            RULES[rule_id]["cannot_prove"],
        ),
        confidence="reported",
        confidence_basis="the battery management system reports the alarm/limit itself",
        action="field_visit",
        responsibility=category,
        responsibility_basis=basis,
        service_key=_service(site, "battery_service"),
        impact={
            "expected_lost_kwh_per_day": None,
            "lost_kwh_reason": "battery flexibility value needs a planner comparison; "
            "not a production loss",
            "lost_function": "battery_assisted_planning",
            "recoverable": True,
        },
    )


def pcc_voltage_sustained(site: SiteEvidence, as_of: datetime) -> ConditionResult:
    rule_id = "pcc_voltage_sustained"
    identity = f"{rule_id}:{site.pcc_asset_id or site.site_id}"
    t = RULES[rule_id]["thresholds"]
    if (
        site.capabilities.get("pcc_phase_voltage") != "available"
        or not site.pcc_voltage_mean
    ):
        return _not_evaluated(rule_id, identity, [site.site_id], "no_pcc_phase_voltage")
    phases = sorted(site.pcc_voltage_mean)
    means = {p: _by_start(site.pcc_voltage_mean[p]) for p in phases}
    maxima = {p: _by_start(site.pcc_voltage_max.get(p)) for p in phases}
    starts = sorted(set().union(*(set(m) for m in means.values())))
    starts = [s for s in starts if s + SLOT <= as_of]
    if not starts or (as_of - (starts[-1] + SLOT)) > 2 * SLOT:
        return ConditionResult(
            rule_id,
            identity,
            "indeterminate",
            [site.site_id],
            ["pcc_voltage_feed_missing_not_resolved"],
            asset_ids=[site.pcc_asset_id],
        )

    def above(start):
        return [
            p
            for p in phases
            if start in means[p]
            and means[p][start].coverage >= 0.8
            and means[p][start].value > t["mean_above_v"]
        ]

    run = []
    for start in reversed(starts):
        if not above(start) or (run and run[0] - start != SLOT):
            break
        run.insert(0, start)
    if not run:
        tail = starts[-t["clear_frames"] :]
        clear = len(tail) == t["clear_frames"] and all(
            all(
                (maxima[p].get(s) or means[p].get(s)) is not None
                and (maxima[p].get(s) or means[p][s]).value <= t["clear_max_v"]
                for p in phases
            )
            for s in tail
        )
        return ConditionResult(
            rule_id,
            identity,
            "clear" if clear else "indeterminate",
            [site.site_id],
            ["voltage_within_review_band"] if clear else ["recovery_not_yet_confirmed"],
            asset_ids=[site.pcc_asset_id],
        )
    affected = sorted({p for s in run for p in above(s)})
    values = [means[p][s].value for s in run for p in affected if s in means[p]]
    peaks = [maxima[p][s].value for s in run for p in affected if s in maxima[p]]
    refs = [
        _ref(
            site.pcc_voltage_mean[p],
            means[p][run[-1]],
            "pcc_phase_voltage",
            f"{p} mean {round(means[p][run[-1]].value, 1)} V",
        )
        for p in affected
        if run[-1] in means[p]
    ]
    corroboration = []
    for phase, series in sorted(site.inverter_voltage.items()):
        overlap = [
            s
            for s in series.samples
            if s.start in run and s.value is not None and s.value > t["mean_above_v"]
        ]
        if overlap:
            corroboration.append(
                _ref(
                    series,
                    overlap[-1],
                    "inverter_phase_voltage",
                    f"inverter {phase} {round(overlap[-1].value, 1)} V",
                )
            )
    refs += corroboration
    confidence, basis = confidence_from(refs, False)
    category, responsibility_basis = _responsibility(site, "grid_connection")
    return ConditionResult(
        rule_id,
        identity,
        "matched",
        [site.site_id],
        [
            "pcc_phase_voltage_above_review_band",
            "no_shutdown_claim_without_reported_state",
        ]
        + ([] if corroboration else ["no_independent_inverter_voltage_corroboration"]),
        asset_ids=[site.pcc_asset_id],
        window_start=run[0],
        window_end=run[-1] + SLOT,
        first_observed=run[0],
        metrics={
            "phases": affected,
            "duration_minutes": len(run) * 15,
            "mean_min_v": round(min(values), 1),
            "mean_max_v": round(max(values), 1),
            "peak_v": round(max(peaks), 1) if peaks else None,
            "threshold_v": t["mean_above_v"],
        },
        evidence=refs,
        hypothesis=Hypothesis(
            "Voltage-related review: a sustained phase voltage above the demo review band "
            "was measured at the PCC (duration and range attached).",
            "15-minute RMS means; transients and the location of the cause are unknown.",
            [
                "local generation raising the feeder voltage",
                "network-side voltage setting",
                "meter phase mapping error",
            ],
            RULES[rule_id]["cannot_prove"],
        ),
        confidence=confidence,
        confidence_basis=basis,
        action="external_review",
        responsibility=category,
        responsibility_basis=responsibility_basis,
        service_key=category,
        impact={
            "expected_lost_kwh_per_day": None,
            "lost_kwh_reason": "no evidenced production loss attached to the voltage review",
            "recoverable": None,
        },
    )


def shared_monitoring_path(
    collector: CollectorEvidence, as_of: datetime
) -> ConditionResult:
    rule_id = "shared_monitoring_path"
    identity = f"{rule_id}:{collector.collector_id}"
    t = RULES[rule_id]["thresholds"]
    if len(collector.site_ids) < t["min_sites"]:
        return _not_evaluated(
            rule_id, identity, collector.site_ids, "collector_serves_one_site"
        )
    failures = sorted(collector.failures, key=lambda f: (f.at, f.site_id))
    by_site: dict[str, list[CollectionFailure]] = {}
    for failure in failures:
        by_site.setdefault(failure.site_id, []).append(failure)
    affected = sorted(
        s for s, items in by_site.items() if len(items) >= t["min_failed_attempts"]
    )

    def recovered(site_id: str) -> bool:
        last_failure = by_site[site_id][-1].at if site_id in by_site else None
        ok = [
            s
            for s in collector.successes.get(site_id, [])
            if s.value is not None and (last_failure is None or s.start >= last_failure)
        ]
        return len(ok) >= t["recovery_frames"]

    if len(affected) < t["min_sites"]:
        return ConditionResult(
            rule_id,
            identity,
            "clear",
            collector.site_ids,
            ["no_overlapping_collection_failures"],
        )
    windows = {s: (by_site[s][0].at, by_site[s][-1].at) for s in affected}
    overlap = max(w[0] for w in windows.values()) <= min(w[1] for w in windows.values())
    if not overlap:
        return ConditionResult(
            rule_id, identity, "clear", collector.site_ids, ["failures_not_overlapping"]
        )
    if all(recovered(s) for s in affected):
        return ConditionResult(
            rule_id,
            identity,
            "clear",
            affected,
            ["collection_recovered_on_all_sites"],
            window_start=min(w[0] for w in windows.values()),
            window_end=max(w[1] for w in windows.values()),
        )
    refs = [
        EvidenceRef(
            f.evidence_id,
            "collection_failure",
            f"{collector.collector_id}:{f.site_id}",
            collector.collector_id,
            f.at,
            f.at,
            f"{f.site_id}: {f.failure_class}",
        )
        for s in affected
        for f in (by_site[s][0], by_site[s][-1])
    ]
    category, service = collector.responsible
    return ConditionResult(
        rule_id,
        identity,
        "matched",
        affected,
        ["shared_collector_failures_overlap", "missing_feeds_not_loss_of_supply"],
        asset_ids=[collector.collector_id],
        window_start=min(w[0] for w in windows.values()),
        window_end=max(w[1] for w in windows.values()),
        first_observed=min(w[0] for w in windows.values()),
        metrics={
            "collector_id": collector.collector_id,
            "failed_attempts": {s: len(by_site[s]) for s in affected},
            "failure_classes": sorted({f.failure_class for f in failures}),
        },
        evidence=refs,
        hypothesis=Hypothesis(
            "Shared monitoring-path issue: feeds behind one declared collector failed at "
            "overlapping times. One remote troubleshooting episode covers all affected sites.",
            "The collector's own error classes are reported; the root cause on the path "
            "(account, network, vendor cloud) is unknown.",
            ["vendor cloud outage", "expired credentials", "local network outage"],
            RULES[rule_id]["cannot_prove"],
        ),
        confidence="reported",
        confidence_basis="the collector logged the failed collection attempts itself",
        action="remote_troubleshooting",
        responsibility=category if category in RESPONSIBILITY else "unknown",
        responsibility_basis=f"declared collector {collector.collector_id} -> {service}",
        service_key=category,
        impact={
            "expected_lost_kwh_per_day": None,
            "lost_kwh_reason": "monitoring outage: missing feeds are not lost energy",
            "lost_function": "monitoring_visibility",
            "recoverable": True,
        },
    )


def common_upstream(
    relations: list[TopologyRelation], children: list[ConditionResult], as_of: datetime
) -> list[ConditionResult]:
    if not relations:
        return [
            _not_evaluated(
                "common_upstream",
                "common_upstream:none",
                [],
                "no_supplied_topology_relationship",
            )
        ]
    results = []
    matched = [
        c
        for c in children
        if c.status == "matched" and c.rule_id in UPSTREAM_COMPATIBLE
    ]
    for relation in sorted(relations, key=lambda r: r.relation_id):
        identity = f"common_upstream:{relation.relation_id}"
        members = [c for c in matched if set(c.site_ids) & set(relation.site_ids)]
        sites = sorted(
            {s for c in members for s in c.site_ids if s in relation.site_ids}
        )
        overlap = members and max(c.window_start for c in members) <= min(
            c.window_end for c in members
        )
        if (
            len(sites) < RULES["common_upstream"]["thresholds"]["min_sites"]
            or not overlap
        ):
            results.append(
                ConditionResult(
                    "common_upstream",
                    identity,
                    "clear",
                    list(relation.site_ids),
                    ["children_not_overlapping"],
                )
            )
            continue
        refs = [ref for c in members for ref in c.evidence[:1]]
        attributed = {
            c.identity: c.impact.get("expected_lost_kwh_per_day") for c in members
        }
        known = [v for v in attributed.values() if v is not None]
        results.append(
            ConditionResult(
                "common_upstream",
                identity,
                "matched",
                sites,
                [
                    "supplied_relationship",
                    "child_anomalies_overlap",
                    "grouping_suspected",
                ],
                window_start=min(c.window_start for c in members),
                window_end=max(c.window_end for c in members),
                first_observed=min(c.first_observed or c.window_start for c in members),
                metrics={
                    "relation_id": relation.relation_id,
                    "relation_basis": relation.basis,
                    "children": [c.identity for c in members],
                },
                evidence=refs,
                hypothesis=Hypothesis(
                    "Possible common upstream episode on a supplied relationship; affected-site "
                    "evidence and uncertainty are retained on the children.",
                    "Grouping is suspected; each child may still have its own cause.",
                    ["independent local issues coinciding"],
                    RULES["common_upstream"]["cannot_prove"],
                ),
                confidence="suspected",
                confidence_basis="overlapping child conditions on a supplied relationship",
                action="external_review",
                responsibility=relation.responsible[0],
                service_key=relation.responsible[0],
                responsibility_basis=f"supplied relationship {relation.relation_id} "
                f"({relation.basis}) -> {relation.responsible[1]}",
                impact={
                    # Physical loss stays attributed to the children; the parent only
                    # reports their sum once and is never added to the totals again.
                    "expected_lost_kwh_per_day": None,
                    "children_lost_kwh_per_day": round(sum(known), 2)
                    if known
                    else None,
                    "attribution": "children",
                    "attributed": attributed,
                },
                children=[c.identity for c in members],
            )
        )
    return results


SITE_RULES = (
    weather_consistent_drop,
    persistent_underperformance,
    battery_operational_restriction,
    pcc_voltage_sustained,
)


def evaluate(
    bundle: EvidenceBundle, as_of: datetime | None = None
) -> list[ConditionResult]:
    """Run the rule library at one analytical time over evidence clipped to that time."""
    moment = (as_of or bundle.as_of).astimezone(UTC)
    clipped = bundle.clipped(moment)
    results = []
    for site_id in sorted(clipped.sites):
        site = clipped.sites[site_id]
        results += [rule(site, moment) for rule in SITE_RULES]
    for collector in sorted(clipped.collectors, key=lambda c: c.collector_id):
        results.append(shared_monitoring_path(collector, moment))
    results += common_upstream(clipped.relations, results, moment)
    return results


# ---------------------------------------------------------------- episode reconciliation


@dataclass
class EpisodeState:
    incident_id: str
    identity: str
    rule_id: str
    evidence_ids: set[str]
    has_active_assignment: bool = False
    parent_identity: str | None = None


@dataclass
class EpisodeAction:
    kind: str  # open | update | recover | hold | unchanged
    identity: str
    result: ConditionResult | None = None
    incident_id: str | None = None
    new_evidence: list[EvidenceRef] = field(default_factory=list)
    note: str = ""


def reconcile(
    active: list[EpisodeState], results: list[ConditionResult]
) -> list[EpisodeAction]:
    """Deduplicate rule firings into episodes (identity + persistence).

    * matched + no active episode         -> open
    * matched + active episode            -> update (only new evidence is appended)
    * clear (explicit recovery rule)      -> recover (or hold while a crew is assigned)
    * indeterminate / not evaluated       -> hold: losing a feed never resolves a fault
    """
    by_identity = {r.identity: r for r in results}
    actions = []
    known = {e.identity: e for e in active}
    for result in sorted(results, key=lambda r: r.identity):
        if result.status != "matched":
            continue
        episode = known.get(result.identity)
        if episode is None:
            actions.append(EpisodeAction("open", result.identity, result))
            continue
        fresh = [
            r for r in result.evidence if r.evidence_id not in episode.evidence_ids
        ]
        actions.append(
            EpisodeAction(
                "update" if fresh else "unchanged",
                result.identity,
                result,
                episode.incident_id,
                fresh,
            )
        )
    for episode in sorted(active, key=lambda e: e.identity):
        result = by_identity.get(episode.identity)
        if result is not None and result.status == "matched":
            continue
        if result is not None and result.status == "clear":
            if episode.has_active_assignment:
                actions.append(
                    EpisodeAction(
                        "hold",
                        episode.identity,
                        result,
                        episode.incident_id,
                        note="condition cleared by the recovery rule; awaiting crew closure",
                    )
                )
            else:
                actions.append(
                    EpisodeAction(
                        "recover",
                        episode.identity,
                        result,
                        episode.incident_id,
                        note="resolved by explicit recovery rule: "
                        + ", ".join(result.reason_codes),
                    )
                )
            continue
        reasons = result.reason_codes if result else ["rule_not_evaluated"]
        actions.append(
            EpisodeAction(
                "hold",
                episode.identity,
                result,
                episode.incident_id,
                note="evidence unavailable or not conclusive ("
                + ", ".join(reasons)
                + "); the episode stays active - missing data never resolves it",
            )
        )
    return actions


def episode_key(identity: str, sequence: int) -> str:
    digest = hashlib.sha256(f"{identity}|{sequence}".encode()).hexdigest()[:20]
    return f"ep-{digest}"
