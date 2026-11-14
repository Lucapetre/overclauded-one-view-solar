"""Outcome tests on the full SYNTHETIC 9-site, 7-day replay. Expectations come from the hidden ground truth /
injection manifest (read here, never by the engine) and from physical invariants."""
import json
import sqlite3
from datetime import date

import pytest

from conftest import AS_OF, CONFIG, obs

DAYS = [str(date(2026, 7, d)) for d in range(15, 22)]


def q(db, sql, args=()):
    return db.execute(sql, args).fetchall()


def daily_yield(db, sk):
    """Day totals from counter-derived interval_yield (best-priority rule): allocatable intervals plus known
    gap-span totals (a valid counter establishes the span total; it is just not allocated to minutes)."""
    import engine.timeparse as tp
    rows = q(db, "SELECT rule_id, priority, start_ms, energy_kwh FROM interval_energy WHERE site_key=? AND "
                 "metric_name='interval_yield_kwh' AND energy_kwh IS NOT NULL AND (allocatable=1 OR "
                 "status='gap_span_total')", (sk,))
    best = min(r[1] for r in rows)
    rid = sorted({r[0] for r in rows if r[1] == best})[0]
    out = {}
    for r, p, s, e in rows:
        if r == rid:
            d = str(tp.local_date(s, "Europe/Bucharest"))
            out[d] = out.get(d, 0.0) + e
    return out


# ------------------------------------------------------------------------------- idempotency / counting
def test_second_identical_ingestion_adds_nothing(build, gen):
    import scraper
    con = sqlite3.connect(str(build / "scraper.sqlite"))
    tables = ["observations", "interval_energy", "raw_records", "raw_deliveries"]
    before = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    e_before = con.execute("SELECT ROUND(SUM(energy_kwh),6) FROM interval_energy").fetchone()[0]
    con.close()
    _, _, store, _ = scraper.ingest([CONFIG], gen / "demo_data", build / "scraper.sqlite", AS_OF, ["delivery"],
                                    log=lambda m: None)
    after = {t: store.con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
    e_after = store.con.execute("SELECT ROUND(SUM(energy_kwh),6) FROM interval_energy").fetchone()[0]
    runs = store.con.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    store.close()
    assert after == before and e_after == e_before
    assert runs >= 2  # the operational log records the extra attempt


def test_no_double_counting_and_no_negative_energy(db):
    dup = q(db, "SELECT identity_key, COUNT(*) FROM raw_records WHERE status='accepted' GROUP BY 1 HAVING COUNT(*)>1")
    assert dup == []
    assert q(db, "SELECT COUNT(*) FROM interval_energy WHERE energy_kwh < 0")[0][0] == 0
    over = q(db, "SELECT COUNT(*) FROM (SELECT rule_id, series_key, start_ms, end_ms FROM interval_energy "
                 "GROUP BY 1,2,3,4 HAVING COUNT(*)>1)")[0][0]
    assert over == 0


def test_exact_duplicates_counted_once(db, truth, site_keys):
    inj = next(i for i in truth["injections"] if i["injection_id"] == "INJ-HW-01")
    sk = site_keys["H1"]
    n_acc = q(db, "SELECT COUNT(*) FROM raw_records WHERE site_key=? AND endpoint_key='getDevHistoryKpi' AND status="
                  "'accepted' AND effective_time_ms BETWEEN strftime('%s',?)*1000 AND strftime('%s',?)*1000-1",
              (sk, inj["window_utc"][0][:19], inj["window_utc"][1][:19]))[0][0]
    n_dup = q(db, "SELECT COUNT(*) FROM raw_records WHERE site_key=? AND status='exact_duplicate' AND endpoint_key="
                  "'getDevHistoryKpi'", (sk,))[0][0]
    assert n_acc == 12 and n_dup == 12


@pytest.mark.parametrize("site", ["H1", "H2", "H3", "F1", "F2", "F3", "S1", "S2"])
def test_counter_energy_matches_hidden_truth(db, truth, site_keys, site):
    got = daily_yield(db, site_keys[site])
    for d in DAYS:
        if site == "H2" and d == "2026-07-21":
            continue  # feed stops mid-day: unknown remainder, checked elsewhere
        exp = truth["daily"][site][d]["inverter_ac_kwh"]
        assert got.get(d, 0.0) == pytest.approx(exp, rel=0.005, abs=0.06), (site, d)


def test_unexpected_lifetime_reset_leaves_crossing_unknown(db, truth, site_keys, gen):
    sk = site_keys["S3"]
    reset = q(db, "SELECT start_ms, end_ms, energy_kwh, allocatable FROM interval_energy WHERE site_key=? AND "
                  "status='unknown_counter_reset'", (sk,))
    assert len(reset) == 1 and reset[0][2] is None and reset[0][3] == 0
    s, e = reset[0][:2]
    after = q(db, "SELECT status FROM interval_energy WHERE site_key=? AND endpoint_key='equipment_data' AND "
                  "start_ms >= ? ORDER BY start_ms LIMIT 8", (sk, e))
    assert after and all(a[0] == "valid" for a in after)  # differences resume after the new baseline
    import csv
    from engine.timeparse import ms_to_iso
    with open(gen / "truth" / "ground_truth" / "latent_15min.csv", newline="") as fh:
        crossing = next(float(r["inverter_ac_kwh"]) for r in csv.DictReader(fh)
                        if r["site_key"] == "S3" and r["frame_start_utc"] == ms_to_iso(s))
    assert crossing > 0.05
    got = daily_yield(db, sk)["2026-07-18"]
    exp = truth["daily"]["S3"]["2026-07-18"]["inverter_ac_kwh"]
    # the unknown crossing energy is NOT silently filled in: the day total is short by exactly that interval
    assert got == pytest.approx(exp - crossing, abs=0.02)
    assert q(db, "SELECT COUNT(*) FROM quality_issues WHERE issue_code='lifetime_counter_reset' AND site_key=?",
             (sk,))[0][0] == 1


def test_local_midnight_daily_resets_are_segments_not_negative(db, site_keys):
    rows = q(db, "SELECT status, COUNT(*) FROM interval_energy WHERE site_key=? AND rule_id='frpf.interval_from_E_Day' "
                 "GROUP BY 1", (site_keys["F1"],))
    st = dict(rows)
    assert st.get("daily_segment_start", 0) == 6 and "unknown_counter_reset" not in st
    assert q(db, "SELECT COUNT(*) FROM quality_issues WHERE issue_code='unexpected_daily_counter_reset'")[0][0] == 0


def test_out_of_order_records_are_ordered_by_source_time(db, site_keys):
    sk = site_keys["F2"]
    late = q(db, "SELECT COUNT(*) FROM raw_records WHERE site_key=? AND record_flags LIKE '%late_arrival%'", (sk,))[0][0]
    assert late >= 60
    bad = q(db, "SELECT COUNT(*) FROM interval_energy WHERE site_key=? AND rule_id='frpf.interval_from_E_Total' AND "
                "status <> 'valid' AND start_ms BETWEEN strftime('%s','2026-07-17T10:00:00')*1000 AND "
                "strftime('%s','2026-07-17T11:00:00')*1000", (sk,))[0][0]
    assert bad == 0


# ------------------------------------------------------------------------------- distinct states
def test_availability_states_are_distinct(db, site_keys):
    states = {r[0] for r in q(db, "SELECT DISTINCT availability_status FROM observations")}
    assert {"available", "missing", "invalid"} <= states
    caps = {(r[0], r[1]) for r in q(db, "SELECT metric_name, state FROM capability_states WHERE site_key=?",
                                    (site_keys["F1"],))}
    assert ("grid_import_kw", "not_installed") in caps
    assert ("grid_import_kw", "unsupported") in {(r[0], r[1]) for r in q(db, "SELECT metric_name, state FROM "
                                                                               "capability_states WHERE site_key=?",
                                                                               (site_keys["S1"],))}
    # night: Huawei reports zero (a value); SnapInverter P_PV is null (documented unavailable, not zero)
    hz = q(db, "SELECT COUNT(*) FROM observations WHERE site_key=? AND metric_name='inverter_ac_output_kw' AND "
               "availability_status='available' AND canonical_value=0", (site_keys["H1"],))[0][0]
    fn = q(db, "SELECT COUNT(*), SUM(canonical_value IS NULL) FROM observations WHERE site_key=? AND "
               "metric_name='pv_ac_kw' AND availability_status='missing' AND quality_flags LIKE "
               "'%vendor_permitted_null%'", (site_keys["F1"],))[0]
    assert hz > 500 and fn[0] > 1000 and fn[0] == fn[1]
    denied = q(db, "SELECT COUNT(*) FROM delivery_events WHERE site_key=? AND endpoint_key='storageData' AND "
                   "status_class='access_denied'", (site_keys["S3"],))[0][0]
    assert denied == 24
    zero_in_denied = q(db, "SELECT COUNT(*) FROM observations WHERE site_key=? AND endpoint_key='storageData' AND "
                           "effective_time_ms BETWEEN strftime('%s','2026-07-18T21:00:00')*1000 AND "
                           "strftime('%s','2026-07-19T20:59:00')*1000", (site_keys["S3"],))[0][0]
    assert zero_in_denied == 0


def test_soc_out_of_range_invalid_not_clamped(db, site_keys):
    r = q(db, "SELECT o.canonical_value, o.original_value, o.availability_status, o.raw_record_id FROM observations o "
              "WHERE o.site_key=? AND o.metric_name='soc_pct' AND o.availability_status='invalid'", (site_keys["H3"],))
    assert len(r) == 1 and r[0][0] is None and r[0][1] == "104.5"
    others = q(db, "SELECT COUNT(*) FROM observations WHERE raw_record_id=? AND availability_status='available'",
               (r[0][3],))[0][0]
    assert others >= 4


def test_unannounced_1000x_spike_is_not_rescaled(db, site_keys):
    r = q(db, "SELECT canonical_value, original_value, quality_flags FROM observations WHERE site_key=? AND "
              "metric_name='inverter_ac_output_kw' AND availability_status='invalid'", (site_keys["H2"],))
    assert len(r) == 3
    assert all(v is None and float(o) > 1000 and "unit_ambiguity_suspected" in f for v, o, f in r)


def test_declared_unit_change_is_converted(db, site_keys):
    sk = site_keys["S2"]
    acts = q(db, "SELECT COUNT(*) FROM audit_actions WHERE action='declared_unit_change_converted' AND site_key=?",
             (sk,))[0][0]
    assert acts >= 1
    mx = q(db, "SELECT MAX(canonical_value) FROM observations WHERE site_key=? AND endpoint_key='currentPowerFlow' AND "
               "metric_name='household_load_kw'", (sk,))[0][0]
    assert 2 < mx < 20


def test_numeric_strings_and_ambiguous_locale(db, site_keys):
    sk = site_keys["H1"]
    parsed = q(db, "SELECT COUNT(*) FROM observations WHERE site_key=? AND quality_flags LIKE '%numeric_string_parsed%'",
               (sk,))[0][0]
    assert parsed >= 100
    amb = q(db, "SELECT original_value, availability_status FROM observations WHERE site_key=? AND quality_flags LIKE "
                "'%ambiguous_number%'", (sk,))
    assert len(amb) == 2 and all(a == "invalid" and "," in o for o, a in amb)


def test_conflicts_preserved_and_excluded(db, site_keys):
    rows = q(db, "SELECT o.metric_name, o.canonical_value, r.status FROM observations o JOIN raw_records r "
                 "USING(raw_record_id) WHERE o.is_conflicted=1 AND o.site_key=?", (site_keys["H3"],))
    assert len(rows) == 8 and {r[2] for r in rows} == {"accepted", "conflict_version"}
    assert {r[0] for r in rows} == {"inverter_ac_output_kw", "inverter_temperature_c"}


def test_schema_alias_and_unknown_change(db, site_keys):
    sk = site_keys["S2"]
    mv = dict(q(db, "SELECT mapping_version, COUNT(*) FROM raw_records WHERE site_key=? AND endpoint_key="
                    "'equipment_data' AND status='accepted' GROUP BY 1", (sk,)))
    assert mv.get("se-tel-1.1-synthetic-alias") == 96
    t = q(db, "SELECT COUNT(*) FROM observations o JOIN raw_records r USING(raw_record_id) WHERE o.site_key=? AND "
              "r.mapping_version='se-tel-1.1-synthetic-alias' AND o.metric_name='inverter_temperature_c' AND "
              "o.availability_status='available'", (sk,))[0][0]
    assert t == 96
    unk = q(db, "SELECT original_value FROM quality_issues WHERE issue_code='unknown_field' AND site_key=?", (sk,))
    assert len(unk) == 4 and all("acActivePowerTotal" in u[0] for u in unk)


def test_quarantine_isolates_only_the_bad_record(db, site_keys):
    sk = site_keys["H1"]
    qr = q(db, "SELECT delivery_hash, status_reason FROM raw_records WHERE site_key=? AND status='quarantined'", (sk,))
    assert len(qr) == 1 and qr[0][1].startswith("missing_required_identifier")
    sib = q(db, "SELECT COUNT(*) FROM raw_records WHERE delivery_hash=? AND status='accepted'", (qr[0][0],))[0][0]
    assert sib == 11
    assert q(db, "SELECT COUNT(*) FROM raw_deliveries WHERE status='unparseable_line' AND raw_text IS NOT NULL")[0][0] == 1
    assert q(db, "SELECT COUNT(*) FROM raw_deliveries WHERE status='payload_parse_error'")[0][0] == 1


def test_provider_failure_envelope_is_not_zero_and_backfill_arrives(db, site_keys):
    sk = site_keys["H3"]
    f = q(db, "SELECT delivery_hash FROM raw_deliveries WHERE site_key=? AND status='provider_failure'", (sk,))
    assert len(f) == 3
    assert q(db, f"SELECT COUNT(*) FROM raw_records WHERE delivery_hash IN ({','.join('?' * 3)})",
             [x[0] for x in f])[0][0] == 0
    gaps = q(db, "SELECT COUNT(*) FROM data_gaps WHERE site_key=? AND endpoint_key='getDevHistoryKpi'", (sk,))[0][0]
    assert gaps == 0  # retries backfilled the window


def test_rate_limit_retry_commits_once(db, site_keys):
    sk = site_keys["S2"]
    st = q(db, "SELECT status, status_class FROM raw_deliveries WHERE site_key=? AND http_status=429", (sk,))
    assert st == [("transport_error", "rate_limited")]
    n = q(db, "SELECT COUNT(*) FROM raw_records WHERE site_key=? AND endpoint_key='equipment_data' AND status="
              "'accepted' AND effective_time_ms >= strftime('%s','2026-07-16T05:00:00')*1000 AND effective_time_ms < "
              "strftime('%s','2026-07-16T06:00:00')*1000", (sk,))[0][0]
    assert n == 4


# ------------------------------------------------------------------------------- freshness and physical conditions
def test_freshness_uses_replay_clock(db, site_keys):
    fresh = dict(((r[0], r[1]), r[2]) for r in q(db, "SELECT site_key, endpoint_key, freshness_status FROM source_health"))
    assert fresh[(site_keys["H2"], "getDevHistoryKpi")] == "stale"
    assert fresh[(site_keys["H1"], "getDevHistoryKpi")] == "fresh"
    assert fresh[(site_keys["F1"], "GetInverterRealtimeData.CommonInverterData")].startswith("fresh")
    assert q(db, "SELECT COUNT(*) FROM observations WHERE availability_status='stale'")[0][0] == 0  # old != stale
    assert q(db, "SELECT COUNT(*) FROM quality_issues WHERE issue_code='stale_repeated_response'")[0][0] == 19
    gaps = {r[0] for r in q(db, "SELECT gap_class FROM data_gaps")}
    assert {"access_denied", "trailing_gap_feed_stale", "stale_feed_repeated_response"} <= gaps


def test_physical_conditions_survive_and_become_candidates(db, truth, site_keys):
    c = q(db, "SELECT policy_id, site_key, peak_value, start_ms FROM review_candidates")
    pol = {(p, s) for p, s, _, _ in c}
    assert pol == {("demo_high_inverter_temperature", site_keys["H1"]),
                   ("demo_phase_voltage_high", site_keys["H2"]),
                   ("demo_sustained_underproduction_peer", site_keys["S2"])}
    hot = next(x for x in c if x[0] == "demo_high_inverter_temperature")
    assert hot[2] == pytest.approx(truth["daily"]["H1"]["2026-07-20"]["max_inverter_temp_c"], abs=0.6)
    under = next(x for x in c if x[0] == "demo_sustained_underproduction_peer")
    ev = json.loads(q(db, "SELECT evidence FROM review_candidates WHERE policy_id=?", (under[0],))[0][0])
    assert ev[0]["local_date"] == "2026-07-19" and all(e["ratio"] < 0.6 for e in ev)
    assert "2026-07-18" not in {e["local_date"] for e in ev}  # overcast day is a negative example
    raw_max = q(db, "SELECT MAX(canonical_value) FROM observations WHERE site_key=? AND metric_name="
                    "'inverter_temperature_c'", (site_keys["H1"],))[0][0]
    assert raw_max >= 70  # values were not overwritten to look healthy


def test_frames_respect_cadence_and_access(build):
    import pandas as pd
    f = pd.read_csv(build / "site_frames_15min.csv", dtype={"device_id": str, "channel": str})
    se = f[(f.metric_name == "inverter_ac_output_kw") & (f.endpoint_key == "equipment_data") & (f.frame_status == "ok")]
    assert (se.n_obs == 1).all() and (se.original_cadence_s == 900).all()
    fr = f[(f.metric_name == "pv_ac_kw") & (f.frame_status == "ok")]
    assert (fr.n_obs == 15).all()
    assert (f[(f.endpoint_key == "storageData")].frame_status == "access_denied").sum() >= 90
    per_day = f[(f.metric_name == "inverter_ac_output_kw") & (f.endpoint_key == "equipment_data")]
    assert per_day.groupby(per_day.frame_start_local.str[:10]).size().max() <= 96 * 3


# ------------------------------------------------------------------------------- provenance and reports
def test_every_rejected_or_transformed_value_has_provenance(db):
    orphan = q(db, "SELECT COUNT(*) FROM observations o LEFT JOIN raw_records r USING(raw_record_id) WHERE "
                   "r.raw_record_id IS NULL OR r.source_path IS NULL")[0][0]
    assert orphan == 0
    qr = q(db, "SELECT raw_record_id FROM raw_records WHERE status='quarantined'")
    for (rid,) in qr:
        assert q(db, "SELECT COUNT(*) FROM quality_issues WHERE raw_record_id=? AND reason IS NOT NULL", (rid,))[0][0]
    issues_wo_action = q(db, "SELECT COUNT(*) FROM quality_issues i LEFT JOIN audit_actions a ON a.issue_id=i.issue_id "
                             "WHERE a.action_id IS NULL")[0][0]
    assert issues_wo_action == 0
    assert q(db, "SELECT COUNT(*) FROM interval_energy WHERE formula IS NULL OR dependencies IS NULL")[0][0] == 0
    assert q(db, "SELECT COUNT(DISTINCT value_origin) FROM interval_energy")[0][0] == 2  # derived + estimated


def test_boundaries_and_temperatures_never_merged(db):
    m = dict(q(db, "SELECT field_rule_id, metric_name FROM observations GROUP BY 1"))
    assert m["frpf.P_PV.gen24"] == "pv_dc_kw" and m["frpf.P_PV.snap"] == "pv_ac_kw"
    assert m["sest.internalTemp"] == "battery_temperature_c"
    assert {m["hw38.temperature"], m["setel.temperature"]} == {"inverter_temperature_c"}
    b = q(db, "SELECT DISTINCT endpoint_key FROM observations WHERE metric_name='battery_temperature_c'")
    assert b == [("storageData",)]


def test_reports_exist_and_say_synthetic(build):
    import jsonschema
    qr = json.loads((build / "quality_report.json").read_text())
    assert qr["synthetic_demonstration"] is True and "SYNTHETIC" in qr["notice"]
    for prov in ("huawei", "fronius", "solaredge"):
        r = qr["record_level"]["by_provider"][prov]
        assert r["records_input"] == r["records_accepted"] + r["records_exact_duplicate"] + \
            r["records_conflict_version"] + r["records_quarantined"]
        m = qr["metric_level"]["by_provider"][prov]
        assert m["denominator"] >= m["observations_total"] + m["quarantined_record_metric_slots_estimate"]
    html = (build / "demo_report.html").read_text(encoding="utf-8")
    assert "SYNTHETIC DEMONSTRATION" in html and "4,200 W" in html
    import csv
    from conftest import ROOT
    schema = json.loads((ROOT / "schemas" / "canonical_measurement.schema.json").read_text())
    with open(build / "canonical_measurements_sample.csv", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) > 100
    num = {"obs_id", "source_line", "is_conflicted"}
    for row in rows[:400]:
        doc = {k: (None if v == "" else (int(v) if k in num and v else v)) for k, v in row.items()}
        if doc["canonical_value"] is not None:
            doc["canonical_value"] = float(doc["canonical_value"])
        jsonschema.validate(doc, schema)


def test_golden_cross_provider_equivalence(build):
    con = sqlite3.connect(str(build / "side" / "golden_equivalence.sqlite"))
    ac = con.execute("SELECT r.provider, r.variant, o.canonical_value, o.boundary FROM observations o JOIN raw_records r "
                     "USING(raw_record_id) WHERE o.metric_name='inverter_ac_output_kw'").fetchall()
    non_hybrid = [a for a in ac if a[1] != "gen24_hybrid"]
    assert {a[0] for a in non_hybrid} == {"huawei", "fronius", "solaredge"}
    assert all(a[2] == pytest.approx(4.2, abs=1e-9) and a[3] == "ac_inverter_output" for a in non_hybrid)
    hyb = con.execute("SELECT o.metric_name, o.canonical_value FROM observations o JOIN raw_records r "
                      "USING(raw_record_id) WHERE r.variant='gen24_hybrid' AND o.field_rule_id LIKE 'frpf.P_PV%'").fetchall()
    assert hyb == [("pv_dc_kw", pytest.approx(4.2))]
    hyb_ac = [a for a in ac if a[1] == "gen24_hybrid"]
    assert hyb_ac and hyb_ac[0][2] == pytest.approx(3.95)  # hybrid net AC is NOT equated to DC generation
