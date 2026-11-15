"""Incident correlation: capability gates, weather vs equipment vs monitoring path, mirrors,
episode persistence, parent/child attribution and the no-future / no-truth-label guards."""

import math
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend import correlation as c
from backend.correlation import (
    CollectionFailure,
    CollectorEvidence,
    EpisodeState,
    EvidenceBundle,
    Sample,
    Series,
    SiteEvidence,
    StaticEvidenceSource,
    TopologyRelation,
    evaluate,
    reconcile,
)

ROOT = Path(__file__).resolve().parents[1]
DAY0 = datetime(2026, 7, 14, 21, 0, tzinfo=UTC)  # 2026-07-15 00:00 local
SLOT = timedelta(minutes=15)
RESP = {
    "pv_installation": ("customer_installation_service", "installer"),
    "grid_connection": ("distributor_network_review", "distributor"),
    "battery_service": ("customer_installation_service", "battery service partner"),
}


def poa_value(moment):
    hour = (moment + timedelta(hours=3)).hour + (moment.minute / 60)
    if hour < 6 or hour > 20:
        return 0.0
    return 900 * math.sin(math.pi * (hour - 6) / 14)


def pv_site(
    site_id="S2",
    days=5,
    weather=None,
    deficit_from=None,
    kwp=9.2,
    plane=(30, 195),
    sensor_plane=(30, 195),
    poa=True,
):
    """A site with aligned PV + POA frames. weather: {day_index: poa factor};
    deficit_from: datetime from which the PR halves (equipment issue)."""
    pv, irr = [], []
    for index in range(days * 96):
        start = DAY0 + index * SLOT
        factor = (weather or {}).get(index // 96, 1.0)
        g = poa_value(start) * factor
        pr = 0.8 * (0.5 if deficit_from and start >= deficit_from else 1.0)
        irr.append(Sample(start, g, f"poa:{site_id}:{index}"))
        pv.append(Sample(start, kwp * g / 1000 * pr, f"pv:{site_id}:{index}"))
    return SiteEvidence(
        site_id=site_id,
        installed_kwp=kwp,
        module_planes=[plane],
        pv=Series(f"inverter:{site_id}", pv),
        poa=Series(f"pyranometer:{site_id}", irr) if poa else None,
        poa_plane=sensor_plane if poa else None,
        poa_basis=f"site_sensor:{site_id}-POA",
        responsibility=RESP,
    )


def by_rule(results, rule_id, site=None):
    return [
        r
        for r in results
        if r.rule_id == rule_id and (site is None or site in r.site_ids)
    ]


def test_missing_capabilities_abstain_and_never_invent_corroboration():
    site = pv_site("S1", poa=False)
    site.module_planes = [(20, 180)]
    mismatch = pv_site("H2", plane=(15, 90), sensor_plane=(30, 180))
    no_kwp = pv_site("F3")
    no_kwp.installed_kwp = None
    bundle = EvidenceBundle(
        DAY0 + timedelta(days=4, hours=10),
        {s.site_id: s for s in (site, mismatch, no_kwp)},
    )
    results = evaluate(bundle)
    for site_id, reason in (
        ("S1", "no_poa_irradiance_sensor"),
        ("H2", "sensor_plane_differs_from_module_plane"),
        ("F3", "installed_capacity_unknown"),
    ):
        for rule in ("weather_consistent_drop", "persistent_underperformance"):
            [result] = by_rule(results, rule, site_id)
            assert result.status == "not_evaluated" and reason in result.reason_codes
            assert not result.evidence and result.hypothesis is None
    for site_id in ("S1", "H2", "F3"):
        assert by_rule(results, "battery_operational_restriction", site_id)[
            0
        ].status == ("not_evaluated")
        assert by_rule(results, "pcc_voltage_sustained", site_id)[0].reason_codes == [
            "no_pcc_phase_voltage"
        ]
    [upstream] = by_rule(results, "common_upstream")
    assert upstream.status == "not_evaluated"
    assert upstream.reason_codes == ["no_supplied_topology_relationship"]


def test_weather_consistent_drop_is_distinguished_from_underperformance():
    cloudy = pv_site(
        "F1", weather={3: 0.4}, plane=(35, 180), sensor_plane=(35, 180), kwp=5.5
    )
    deficit = pv_site("S2", deficit_from=DAY0 + timedelta(days=4, hours=4))
    now = DAY0 + timedelta(days=4, hours=11)  # 11:00 local on day 5
    results = evaluate(EvidenceBundle(now, {"F1": cloudy, "S2": deficit}))
    [weather] = by_rule(results, "weather_consistent_drop", "F1")
    assert weather.status == "matched" and weather.action == "monitor"
    assert (
        weather.confidence == "corroborated"
    )  # inverter + pyranometer, two instruments
    assert weather.metrics["pv_drop"] >= 0.3 and weather.metrics["poa_drop"] >= 0.25
    assert weather.impact["recoverable"] is False
    assert "Does not rule out" in weather.hypothesis.cannot_prove
    assert by_rule(results, "persistent_underperformance", "F1")[0].status != "matched"
    [under] = by_rule(results, "persistent_underperformance", "S2")
    assert under.status == "matched" and under.action == "field_visit"
    assert under.responsibility == "customer_installation_service"
    assert (
        under.metrics["pr_ratio"] < 0.75
        and under.impact["expected_lost_kwh_per_day"] > 0
    )
    assert by_rule(results, "weather_consistent_drop", "S2")[0].status == "clear"


def collector(failing=("H1", "H2"), until=None, recovered=False):
    start = datetime(2026, 7, 19, 6, 15, tzinfo=UTC)
    end = until or datetime(2026, 7, 19, 8, 45, tzinfo=UTC)
    failures = []
    moment = start
    while moment <= end:
        for site_id in failing:
            failures.append(
                CollectionFailure(moment, site_id, "timeout", f"d:{site_id}:{moment}")
            )
        moment += timedelta(minutes=7)
    successes = {}
    if recovered:
        successes = {
            s: [
                Sample(end + timedelta(minutes=15 * i), 4.0, f"ok:{s}:{i}")
                for i in range(1, 3)
            ]
            for s in failing
        }
    return CollectorEvidence("COL-1", ["H1", "H2"], failures, successes)


def test_shared_monitoring_path_is_one_episode_and_not_loss_of_supply():
    now = datetime(2026, 7, 19, 8, 30, tzinfo=UTC)
    [result] = [
        r
        for r in evaluate(EvidenceBundle(now, collectors=[collector()]))
        if r.rule_id == "shared_monitoring_path"
    ]
    assert result.status == "matched" and result.site_ids == ["H1", "H2"]
    assert result.action == "remote_troubleshooting"
    assert result.responsibility == "monitoring_provider"
    assert "missing_feeds_not_loss_of_supply" in result.reason_codes
    assert result.impact["expected_lost_kwh_per_day"] is None
    assert result.confidence == "reported"
    single = collector(failing=("H1",))
    assert evaluate(EvidenceBundle(now, collectors=[single]))[-2].status == "clear"
    later = datetime(2026, 7, 19, 9, 30, tzinfo=UTC)
    healed = [
        r
        for r in evaluate(EvidenceBundle(later, collectors=[collector(recovered=True)]))
        if r.rule_id == "shared_monitoring_path"
    ][0]
    assert (
        healed.status == "clear"
        and "collection_recovered_on_all_sites" in healed.reason_codes
    )


def voltage_site(mirror=False, corroborate=True, high_until=None, frames=8):
    start = datetime(2026, 7, 19, 8, 15, tzinfo=UTC)
    means, maxima, inverter = [], [], []
    for index in range(frames):
        moment = start + index * SLOT
        high = high_until is None or moment < high_until
        value = 254.6 if high else 247.0
        means.append(Sample(moment, value, f"pcc:mean:{index}"))
        maxima.append(Sample(moment, value + 0.8, f"pcc:max:{index}"))
        inverter.append(Sample(moment, value + 0.4 if high else 246.0, f"inv:{index}"))
    site = SiteEvidence(
        "H2",
        pcc_asset_id="H2-PCC",
        capabilities={"pcc_phase_voltage": "available"},
        pcc_voltage_mean={"L1": Series("pcc-meter", means)},
        pcc_voltage_max={"L1": Series("pcc-meter", maxima)},
        responsibility=RESP,
    )
    if corroborate:
        site.inverter_voltage = {
            "L1": Series(
                "inverter-H2", inverter, mirror_of="pcc-meter" if mirror else None
            )
        }
    return site


def test_voltage_review_mirrors_are_not_independent_and_no_shutdown_claim():
    now = datetime(2026, 7, 19, 9, 30, tzinfo=UTC)
    independent = evaluate(EvidenceBundle(now, {"H2": voltage_site()}))
    [result] = by_rule(independent, "pcc_voltage_sustained")
    assert result.status == "matched" and result.confidence == "corroborated"
    assert result.responsibility == "distributor_network_review"
    assert result.action == "external_review"
    assert (
        result.metrics["duration_minutes"] == 75
        and result.metrics["mean_max_v"] == 254.6
    )
    assert "no_shutdown_claim_without_reported_state" in result.reason_codes
    assert "shutdown" in result.hypothesis.cannot_prove
    mirrored = by_rule(
        evaluate(EvidenceBundle(now, {"H2": voltage_site(mirror=True)})),
        "pcc_voltage_sustained",
    )[0]
    assert mirrored.confidence == "suspected"  # a mirror of the same meter counts once
    assert c.independent_sources(mirrored.evidence) == {"pcc-meter"}
    alone = by_rule(
        evaluate(EvidenceBundle(now, {"H2": voltage_site(corroborate=False)})),
        "pcc_voltage_sustained",
    )[0]
    assert alone.confidence == "suspected"
    assert "no_independent_inverter_voltage_corroboration" in alone.reason_codes


def battery_site(alarm_from, frames, stop_after=None, clear_from=None):
    alarms, limits = [], []
    for index in range(frames):
        moment = alarm_from - 4 * SLOT + index * SLOT
        if stop_after is not None and index >= stop_after:
            break
        active = alarm_from <= moment and not (clear_from and moment >= clear_from)
        alarms.append(Sample(moment, 2.0 if active else 0.0, f"alarm:{index}"))
        limits.append(Sample(moment, 25.0 if active else 100.0, f"limit:{index}"))
    return SiteEvidence(
        "F1",
        battery_asset_id="F1-BMS",
        capabilities={
            "battery_alarms_available": "available",
            "battery_limits_available": "available",
        },
        battery_alarms={"internal_failure": Series("bms", alarms)},
        battery_limits={"battery_max_discharge_current_a": Series("bms", limits)},
        battery_nominal={"battery_max_discharge_current_a": 100.0},
        responsibility=RESP,
    )


def test_battery_restriction_and_feed_loss_never_resolves_an_active_fault():
    alarm = datetime(2026, 7, 18, 6, 30, tzinfo=UTC)
    now = alarm + 12 * SLOT
    [result] = by_rule(
        evaluate(EvidenceBundle(now, {"F1": battery_site(alarm, 40)})),
        "battery_operational_restriction",
    )
    assert result.status == "matched" and result.confidence == "reported"
    assert "battery_flexibility_removed" in result.reason_codes
    assert result.first_observed == alarm
    assert "thermal runaway" in result.hypothesis.cannot_prove
    episode = EpisodeState(
        "ep-1",
        result.identity,
        result.rule_id,
        {r.evidence_id for r in result.evidence},
    )
    [same] = reconcile([episode], [result])
    assert same.kind == "unchanged"  # a repeated firing is not a new episode
    later = by_rule(
        evaluate(EvidenceBundle(now + 2 * SLOT, {"F1": battery_site(alarm, 40)})),
        "battery_operational_restriction",
    )
    [action] = reconcile([episode], later)
    assert (
        action.kind == "update" and action.new_evidence
    )  # only new evidence is appended
    stale = evaluate(
        EvidenceBundle(now + 8 * SLOT, {"F1": battery_site(alarm, 40, stop_after=14)})
    )
    [held] = reconcile([episode], stale)
    assert held.kind == "hold" and "missing data never resolves" in held.note
    clear_at = alarm + 6 * SLOT
    recovered = evaluate(
        EvidenceBundle(
            alarm + 16 * SLOT, {"F1": battery_site(alarm, 30, clear_from=clear_at)}
        )
    )
    [recover] = reconcile([episode], recovered)
    assert recover.kind == "recover" and "explicit recovery rule" in recover.note
    assigned = EpisodeState("ep-1", result.identity, result.rule_id, set(), True)
    [awaiting] = reconcile([assigned], recovered)
    assert awaiting.kind == "hold" and "awaiting crew closure" in awaiting.note


def test_episode_dedup_opens_once_and_reconcile_is_deterministic():
    now = datetime(2026, 7, 19, 9, 30, tzinfo=UTC)
    results = evaluate(EvidenceBundle(now, {"H2": voltage_site()}))
    first = reconcile([], results)
    assert [a.kind for a in first] == ["open"]
    again = reconcile([], evaluate(EvidenceBundle(now, {"H2": voltage_site()})))
    assert [a.identity for a in again] == [a.identity for a in first]
    assert c.episode_key("x", 1) == c.episode_key("x", 1) != c.episode_key("x", 2)


def test_parent_child_attribution_counts_loss_once():
    deficit = DAY0 + timedelta(days=4, hours=4)
    now = DAY0 + timedelta(days=4, hours=11)
    sites = {
        "A": pv_site("A", deficit_from=deficit),
        "B": pv_site("B", deficit_from=deficit),
    }
    relation = TopologyRelation(
        "FEEDER-X",
        "common_feeder",
        ("A", "B"),
        "fixture relationship supplied by the test",
    )
    results = evaluate(EvidenceBundle(now, sites, relations=[relation]))
    children = by_rule(results, "persistent_underperformance")
    [parent] = by_rule(results, "common_upstream")
    assert parent.status == "matched" and parent.site_ids == ["A", "B"]
    assert sorted(parent.children) == sorted(ch.identity for ch in children)
    assert parent.impact["expected_lost_kwh_per_day"] is None  # never added on top
    total = sum(ch.impact["expected_lost_kwh_per_day"] for ch in children)
    assert parent.impact["children_lost_kwh_per_day"] == round(total, 2)
    assert (
        parent.confidence == "suspected" and "grouping_suspected" in parent.reason_codes
    )
    unrelated = TopologyRelation("FEEDER-Y", "common_feeder", ("A", "Z"), "fixture")
    lone = by_rule(
        evaluate(EvidenceBundle(now, sites, relations=[unrelated])), "common_upstream"
    )
    assert lone[0].status == "clear"  # one matched site is no common episode


def test_correlation_never_uses_rows_after_the_analytical_time():
    deficit = DAY0 + timedelta(days=4, hours=4)
    full = pv_site("S2", days=6, deficit_from=deficit)
    now = DAY0 + timedelta(days=4, hours=11)
    cut = pv_site("S2", days=6, deficit_from=deficit)
    cut.pv.samples = [s for s in cut.pv.samples if s.end <= now]
    cut.poa.samples = [s for s in cut.poa.samples if s.end <= now]
    a = evaluate(EvidenceBundle(now, {"S2": full}))
    b = evaluate(EvidenceBundle(now, {"S2": cut}))
    assert [(r.identity, r.status, r.metrics) for r in a] == [
        (r.identity, r.status, r.metrics) for r in b
    ]
    source = StaticEvidenceSource(EvidenceBundle(now, {"S2": full}))
    clipped = source.bundle(now)
    assert max(s.end for s in clipped.sites["S2"].pv.samples) <= now
    for result in a:
        for ref in result.evidence:
            assert ref.observed_to is None or ref.observed_to <= now


FORBIDDEN = re.compile(
    r"component_truth|fault_manifest|ground_truth|injection_manifest|"
    r"expected_fault|latent_15min"
)
VENDOR = re.compile(
    r"huawei|fronius|solaredge|shelly|victron|kipp|campbell|schneider|enphase", re.I
)


def test_runtime_modules_never_read_truth_labels_or_branch_on_vendors():
    for name in ("correlation", "ranking", "status", "crew_planner", "planning_models"):
        path = ROOT / "backend" / f"{name}.py"
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        assert not FORBIDDEN.search(text), name
        assert not VENDOR.search(text), name
    for path in (ROOT / "backend").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "component_truth" not in text and "fault_manifest" not in text, path.name
