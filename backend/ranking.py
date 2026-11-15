"""One priority service for the queue, incident detail, map and crew planner.

Priority bands first (safety/emergency and mandatory response obligations above commercial
benefit), then a deterministic within-band score from explicit, bounded DEMO-POLICY weights
(`config/dispatch_policy.yaml`). Every result carries its band, factor values, unknowns, reason
codes, dominant criteria, policy version, evidence ids and `rank_as_of`, so every view that asks
for the same incident at the same revision gets the same explanation.

* Unknown economics never move a job down a band and never multiply a hazard down.
* An active P0 stays urgent even with incomplete evidence.
* An authorized override changes the effective band until it expires; the computed rank is
  preserved next to it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

import yaml

POLICY_PATH = Path(__file__).resolve().parents[1] / "config" / "dispatch_policy.yaml"


@lru_cache
def load_policy(path: str | None = None) -> dict:
    text = Path(path or POLICY_PATH).read_text(encoding="utf-8")
    policy = yaml.safe_load(text)
    weights = policy["weights"]
    if abs(sum(weights.values()) - 1.0) > 1e-9 or any(w < 0 for w in weights.values()):
        raise ValueError("Dispatch policy weights must be non-negative and sum to 1")
    return policy


def band_order(policy: dict) -> list[str]:
    return [band["band"] for band in policy["bands"]]


def band_info(policy: dict, band: str) -> dict:
    return next(b for b in policy["bands"] if b["band"] == band)


@dataclass
class Valuation:
    stakeholder: str
    low_ron_kwh: float
    high_ron_kwh: float
    basis: str


@dataclass
class RepairEstimate:
    currency: str
    low: float
    high: float
    source: str
    as_of: str


@dataclass
class JobFacts:
    incident_id: str
    band: str  # computed band (rule policy or the incident's tier)
    created_at: datetime
    title: str = ""
    family: str = "Other"
    site_ids: list[str] = field(default_factory=list)
    hazard: bool = False
    confidence: str | None = None  # None for incidents without correlated evidence
    persistence_minutes: float | None = None
    repeat_count: int = 0
    parent_id: str | None = None
    lost_function: str | None = None
    expected_lost_kwh_per_day: float | None = None
    lost_kwh_reason: str | None = None
    recoverable: bool | None = None
    valuation: Valuation | None = None
    repair: RepairEstimate | None = None
    action: str | None = None  # monitor | remote_* | field_visit | external_review
    has_commitment: bool = False
    evidence_ids: list[str] = field(default_factory=list)
    override: dict | None = None  # {band, reason, expires_at, override_id, created_by}


@dataclass
class RankResult:
    incident_id: str
    band: str
    band_label: str
    computed_band: str
    score: float
    factors: dict
    unknowns: list[str]
    reason_codes: list[str]
    dominant: list[str]
    policy_version: str
    evidence_ids: list[str]
    rank_as_of: datetime
    deadline_at: datetime | None
    deadline_mandatory: bool
    overdue_minutes: float | None
    economics: dict
    override: dict | None
    position: int = 0

    def sort_key(self, policy: dict, created_at: datetime) -> tuple:
        return (
            band_order(policy).index(self.band),
            -self.score,
            created_at,
            self.incident_id,
        )

    def as_dict(self) -> dict:
        return {
            "incident_id": self.incident_id,
            "position": self.position,
            "band": self.band,
            "band_label": self.band_label,
            "computed_band": self.computed_band,
            "score": self.score,
            "factors": self.factors,
            "unknowns": self.unknowns,
            "reason_codes": self.reason_codes,
            "dominant": self.dominant,
            "policy_version": self.policy_version,
            "evidence_ids": self.evidence_ids,
            "rank_as_of": self.rank_as_of.isoformat(),
            "deadline_at": self.deadline_at.isoformat() if self.deadline_at else None,
            "deadline_mandatory": self.deadline_mandatory,
            "overdue_minutes": self.overdue_minutes,
            "economics": self.economics,
            "override": self.override,
        }

    def digest(self) -> str:
        payload = json.dumps(self.as_dict(), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _active_override(job: JobFacts, now: datetime) -> dict | None:
    override = job.override
    if not override:
        return None
    expires = override.get("expires_at")
    if expires is not None:
        expires = (
            expires
            if isinstance(expires, datetime)
            else datetime.fromisoformat(expires)
        )
        if expires <= now:
            return None
    return override


def economics(job: JobFacts, policy: dict) -> dict:
    """Stakeholder-specific economics; unknown values stay null with a reason."""
    lost = job.expected_lost_kwh_per_day
    value = None
    if lost is not None and job.valuation is not None:
        value = {
            "stakeholder": job.valuation.stakeholder,
            "low_ron": round(lost * job.valuation.low_ron_kwh, 2),
            "high_ron": round(lost * job.valuation.high_ron_kwh, 2),
            "basis": job.valuation.basis,
        }
    repair = (
        {
            "currency": job.repair.currency,
            "low": job.repair.low,
            "high": job.repair.high,
            "source": job.repair.source,
            "as_of": job.repair.as_of,
        }
        if job.repair
        else None
    )
    return {
        "currency": policy["economics"]["currency"],
        "expected_lost_kwh_per_day": lost,
        "lost_kwh_reason": None
        if lost is not None
        else (job.lost_kwh_reason or "no_valid_baseline"),
        "value_per_day": value,
        "value_reason": None
        if value
        else (
            "no_lost_energy_estimate"
            if lost is None
            else "no_declared_stakeholder_valuation"
        ),
        "repair_estimate": repair,
        "repair_reason": None if repair else "no_catalog_estimate",
        "parent_attribution": "loss counted on child episodes only"
        if job.parent_id
        else None,
    }


def rank_job(job: JobFacts, now: datetime, policy: dict | None = None) -> RankResult:
    policy = policy or load_policy()
    weights, caps = policy["weights"], policy["caps"]
    override = _active_override(job, now)
    band = override["band"] if override else job.band
    info = band_info(policy, band)
    reasons: list[str] = [f"band_{band}_{info['name']}"]
    unknowns: list[str] = []
    factors: dict[str, dict] = {}

    def factor(name: str, raw, normalized: float, basis: str):
        normalized = max(0.0, min(1.0, float(normalized)))
        factors[name] = {
            "value": raw,
            "normalized": round(normalized, 4),
            "weight": weights[name],
            "contribution": round(normalized * weights[name], 4),
            "basis": basis,
        }

    created = job.created_at
    age_minutes = max(0.0, (now - created).total_seconds() / 60)
    deadline_at, overdue = None, None
    window = info.get("response_minutes")
    if window:
        deadline_at = created + timedelta(minutes=window)
        overdue = round(max(0.0, (now - deadline_at).total_seconds() / 60), 1)
        factor(
            "deadline_pressure",
            round(age_minutes, 1),
            age_minutes / window,
            f"elapsed share of the {band} response window ({window} min, demo policy)",
        )
        if overdue > 0:
            reasons.append("response_deadline_overdue")
    else:
        factor("deadline_pressure", None, 0.0, f"no response window for {band}")
    sites = len(job.site_ids) or 1
    impact = min(sites / caps["affected_sites"], 1.0) * 0.5 + (
        0.5 if job.lost_function else 0
    )
    factor(
        "evidenced_impact",
        {"affected_sites": sites, "lost_function": job.lost_function},
        impact,
        "affected installations (cap) and evidenced lost function",
    )
    if job.expected_lost_kwh_per_day is None:
        unknowns.append("expected_lost_kwh_per_day")
        factor(
            "recoverable_impact",
            None,
            0.0,
            job.lost_kwh_reason
            or "unknown loss: contributes 0 and never changes the band",
        )
    else:
        lost = job.expected_lost_kwh_per_day if job.recoverable is not False else 0.0
        factor(
            "recoverable_impact",
            lost,
            lost / caps["lost_kwh_per_day"],
            "expected recoverable kWh/day from a valid baseline (beneficiary: site customer)",
        )
    if job.confidence is None:
        unknowns.append("evidence_confidence")
        conf = policy["confidence_scores"]["insufficient"]
        persistence = 0.0
    else:
        conf = policy["confidence_scores"][job.confidence]
        persistence = min(
            (job.persistence_minutes or 0) / caps["persistence_minutes"], 1.0
        )
    factor(
        "confidence_persistence",
        {"confidence": job.confidence, "persistence_minutes": job.persistence_minutes},
        (conf + persistence) / 2,
        "ordinal confidence score and persistence (cap)",
    )
    factor(
        "age",
        round(age_minutes / 60, 2),
        age_minutes / 60 / caps["age_hours"],
        "analytical age (cap)",
    )
    repeat = min(job.repeat_count / caps["repeat"], 1.0) * (
        0.5 if job.parent_id else 1.0
    )
    factor(
        "repeat_dependency",
        {"repeat_count": job.repeat_count, "parent": job.parent_id},
        repeat + (0.5 if job.parent_id else 0),
        "repeat episodes; child of a shared parent",
    )
    factor(
        "commitments",
        job.has_commitment,
        1.0 if job.has_commitment else 0.0,
        "an active assignment already exists",
    )
    remote = job.action in ("remote_review", "remote_troubleshooting")
    factor(
        "remote_resolvable",
        job.action,
        1.0 if remote else 0.5,
        "remote work can resolve it without a field visit",
    )
    if job.hazard:
        reasons.append("hazard_reported_stays_urgent")
        if job.confidence in (None, "insufficient", "suspected"):
            reasons.append("urgent_review_incomplete_evidence")
    if override:
        reasons.append("priority_override_active")
    if job.action == "monitor":
        reasons.append("monitoring_only_no_field_visit")
    elif remote:
        reasons.append("remote_activity_not_field_visit")
    if job.parent_id:
        reasons.append("child_of_shared_parent_loss_counted_once")
    if unknowns:
        reasons.append("unknowns_do_not_demote")
    score = round(sum(f["contribution"] for f in factors.values()), 4)
    dominant = [
        name
        for name, f in sorted(
            factors.items(), key=lambda kv: (-kv[1]["contribution"], kv[0])
        )
        if f["contribution"] > 0
    ][:2]
    return RankResult(
        incident_id=job.incident_id,
        band=band,
        band_label=info["label"],
        computed_band=job.band,
        score=score,
        factors=factors,
        unknowns=unknowns,
        reason_codes=reasons,
        dominant=["priority_band"] + dominant,
        policy_version=policy["policy_version"],
        evidence_ids=list(job.evidence_ids)[:50],
        rank_as_of=now,
        deadline_at=deadline_at,
        deadline_mandatory=bool(info.get("deadline_mandatory")),
        overdue_minutes=overdue,
        economics=economics(job, policy),
        override=override,
    )


def rank_all(
    jobs: list[JobFacts], now: datetime, policy: dict | None = None
) -> list[RankResult]:
    """Deterministic ranked list: band, then within-band score, then age, then id."""
    policy = policy or load_policy()
    created = {job.incident_id: job.created_at for job in jobs}
    results = [rank_job(job, now, policy) for job in jobs]
    results.sort(key=lambda r: r.sort_key(policy, created[r.incident_id]))
    for index, result in enumerate(results, start=1):
        result.position = index
    return results


def rank_as_of(now: datetime, minutes: int = 5) -> datetime:
    """Quantized analytical time so every view requested in one slot shares one rank."""
    floored = now.replace(second=0, microsecond=0)
    return floored - timedelta(minutes=floored.minute % minutes)
