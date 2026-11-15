"""Ranking: bands dominate, unknown economics never demote hazards, explanations are complete
and deterministic, overrides keep the computed rank and expire."""

from datetime import UTC, datetime, timedelta

from backend.ranking import (
    JobFacts,
    RepairEstimate,
    Valuation,
    load_policy,
    rank_all,
    rank_as_of,
    rank_job,
)

NOW = datetime(2026, 7, 19, 8, 30, tzinfo=UTC)


def job(incident_id, band, minutes=60, **extra):
    return JobFacts(
        incident_id=incident_id,
        band=band,
        created_at=NOW - timedelta(minutes=minutes),
        **extra,
    )


def test_policy_is_versioned_demo_and_weights_bounded():
    policy = load_policy()
    assert policy["policy_version"].startswith("demo-")
    assert "not a validated or learned model" in policy["label"]
    assert abs(sum(policy["weights"].values()) - 1) < 1e-9
    assert [b["band"] for b in policy["bands"]] == ["P0", "P1", "P2", "P3"]


def test_safety_and_deadlines_dominate_commercial_benefit():
    hazard = job("hazard", "P0", minutes=1, hazard=True, confidence="insufficient")
    rich = job(
        "rich",
        "P2",
        minutes=600,
        expected_lost_kwh_per_day=500.0,
        recoverable=True,
        confidence="reported",
        persistence_minutes=600,
        repeat_count=5,
        site_ids=["a", "b", "c", "d", "e", "f"],
        lost_function="pv",
    )
    battery = job(
        "battery", "P1", minutes=30, confidence="reported", lost_function="battery"
    )
    monitor = job("weather", "P3", minutes=900, action="monitor")
    ranked = rank_all([monitor, rich, battery, hazard], NOW)
    assert [r.incident_id for r in ranked] == ["hazard", "battery", "rich", "weather"]
    top = ranked[0]
    assert top.band == "P0" and "urgent_review_incomplete_evidence" in top.reason_codes
    assert "hazard_reported_stays_urgent" in top.reason_codes
    assert top.deadline_mandatory and top.deadline_at == hazard.created_at + timedelta(
        hours=1
    )
    assert "monitoring_only_no_field_visit" in ranked[-1].reason_codes


def test_unknown_loss_never_suppresses_a_hazard_and_is_listed():
    hazard = job("u", "P1", confidence="reported")
    valuable = job(
        "k",
        "P2",
        expected_lost_kwh_per_day=30.0,
        recoverable=True,
        confidence="reported",
    )
    unknown, known = rank_job(hazard, NOW), rank_job(valuable, NOW)
    assert "expected_lost_kwh_per_day" in unknown.unknowns
    assert "unknowns_do_not_demote" in unknown.reason_codes
    assert unknown.factors["recoverable_impact"]["normalized"] == 0
    assert unknown.economics["expected_lost_kwh_per_day"] is None
    assert unknown.economics["lost_kwh_reason"]
    assert known.score > unknown.score - 1  # a richer P2 never overtakes the P1
    assert rank_all([valuable, hazard], NOW)[0].incident_id == "u"


def test_economics_are_stakeholder_specific_and_labelled():
    facts = job(
        "e",
        "P2",
        expected_lost_kwh_per_day=20.0,
        recoverable=True,
        valuation=Valuation("site customer", 0.45, 1.28, "contract export..import"),
        repair=RepairEstimate("RON", 300, 1200, "manual demo catalog", "2026-07-01"),
    )
    result = rank_job(facts, NOW)
    value = result.economics["value_per_day"]
    assert value == {
        "stakeholder": "site customer",
        "low_ron": 9.0,
        "high_ron": 25.6,
        "basis": "contract export..import",
    }
    assert result.economics["repair_estimate"]["source"] == "manual demo catalog"
    plain = rank_job(job("p", "P2", expected_lost_kwh_per_day=20.0), NOW)
    assert plain.economics["value_per_day"] is None
    assert plain.economics["value_reason"] == "no_declared_stakeholder_valuation"
    assert plain.economics["repair_reason"] == "no_catalog_estimate"
    child = rank_job(job("c", "P2", parent_id="parent"), NOW)
    assert (
        child.economics["parent_attribution"] == "loss counted on child episodes only"
    )


def test_explanations_are_complete_deterministic_and_overrides_expire():
    facts = job(
        "x",
        "P2",
        confidence="corroborated",
        persistence_minutes=90,
        evidence_ids=["ev1", "ev2"],
    )
    a, b = rank_job(facts, NOW), rank_job(facts, NOW)
    assert a.as_dict() == b.as_dict() and a.digest() == b.digest()
    for key in (
        "band",
        "factors",
        "unknowns",
        "reason_codes",
        "dominant",
        "policy_version",
        "evidence_ids",
        "rank_as_of",
    ):
        assert key in a.as_dict()
    assert a.dominant[0] == "priority_band" and len(a.dominant) <= 3
    for factor in a.factors.values():
        assert 0 <= factor["normalized"] <= 1 and factor["basis"]
    overridden = job(
        "x",
        "P2",
        override={
            "band": "P1",
            "reason": "customer is a clinic",
            "expires_at": NOW + timedelta(hours=2),
        },
    )
    result = rank_job(overridden, NOW)
    assert (result.band, result.computed_band) == ("P1", "P2")
    assert "priority_override_active" in result.reason_codes
    expired = rank_job(overridden, NOW + timedelta(hours=3))
    assert (expired.band, expired.override) == ("P2", None)
    assert rank_as_of(datetime(2026, 7, 19, 8, 33, 41, tzinfo=UTC)) == datetime(
        2026, 7, 19, 8, 30, tzinfo=UTC
    )
