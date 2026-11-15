"""Component datasets end to end: generation -> shared engine -> canonical snapshot, checked against the
evaluation-only truth (tests/component_truth layout, generated into a temp dir). The engine never receives the
truth path; only these tests read it.

Runtime: ~2.5 min (one generation + one full component scrape, shared by the module)."""

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMP_CONFIG = ROOT / "config" / "component_profiles.yaml"
AS_OF = "2026-07-22T00:00:00+03:00"
F1, F2, H2 = (
    "fronius|fr-lan-gw-0001|FR-SITE-0001",
    "fronius|fr-lan-gw-0002|FR-SITE-0002",
    "huawei|hw-nbi-demo-01|NE=33554792",
)
S3 = "solaredge|se-acct-demo-02|1618033"


def ms(iso):
    return int(
        round(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)
    )


@pytest.fixture(scope="module")
def comp(gen):
    import generate_components
    import scraper

    out, truth = gen / "demo_components", gen / "component_truth"
    if not (out / "manifest.json").exists():
        generate_components.main(
            [
                "--seed",
                "42",
                "--start",
                "2026-07-15",
                "--days",
                "7",
                "--out",
                str(out),
                "--truth-out",
                str(truth),
                "--provider-data",
                str(gen / "demo_data"),
            ]
        )
    build = gen / "components"
    if not (build / "component.sqlite").exists():
        scraper.main(
            [
                "--component",
                "all",
                "--config",
                str(COMP_CONFIG),
                "--input",
                str(out),
                "--out",
                str(build),
                "--as-of",
                AS_OF,
            ]
        )
    con = sqlite3.connect(str(build / "component.sqlite"))
    fm = json.loads((truth / "fault_manifest.json").read_text(encoding="utf-8"))
    yield {
        "out": out,
        "truth": truth,
        "build": build,
        "con": con,
        "faults": {f["fault_id"]: f for f in fm["faults"]},
    }
    con.close()


def q(c, sql, args=()):
    return c["con"].execute(sql, args).fetchall()


# ------------------------------------------------------------------ determinism, manifests, original fixtures
def test_original_generator_manifest_reproduces(gen):
    assert (gen / "demo_data" / "manifest.json").read_bytes() == (
        ROOT / "demo_data" / "manifest.json"
    ).read_bytes()


def test_generator_is_deterministic_and_matches_committed_fixtures(comp, gen):
    import generate_components

    again = gen / "demo_components_again"
    generate_components.main(
        [
            "--out",
            str(again),
            "--truth-out",
            str(gen / "component_truth_again"),
            "--provider-data",
            str(gen / "demo_data"),
        ]
    )
    files = sorted(
        p.relative_to(comp["out"]) for p in comp["out"].rglob("*") if p.is_file()
    )
    assert files and files == sorted(
        p.relative_to(again) for p in again.rglob("*") if p.is_file()
    )
    for rel in files:
        assert (comp["out"] / rel).read_bytes() == (again / rel).read_bytes(), rel
        assert (comp["out"] / rel).read_bytes() == (
            ROOT / "demo_components" / rel
        ).read_bytes(), f"committed {rel}"
    for rel in ("fault_manifest.json", "latent_15min.csv"):
        assert (comp["truth"] / rel).read_bytes() == (
            gen / "component_truth_again" / rel
        ).read_bytes()


def test_manifest_sha256_and_existing_references(comp):
    man = json.loads((comp["out"] / "manifest.json").read_text(encoding="utf-8"))
    for f in man["files"]:
        p = (comp["out"] / f["path"]).resolve()
        assert hashlib.sha256(p.read_bytes()).hexdigest() == f["sha256"], f["path"]
    ext = [f for f in man["files"] if f.get("external_root")]
    assert {f["role"] for f in ext} == {"existing_reference", "mirror_evidence"}
    assert not list(
        comp["out"].rglob("storageData*")
    )  # B2 reuses the existing file; no second battery dataset
    size = sum(p.stat().st_size for p in comp["out"].rglob("*") if p.is_file())
    assert size < 25e6


# ------------------------------------------------------------------ physical consistency
def _truth_rows(comp):
    import csv

    with open(comp["truth"] / "latent_15min.csv", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_latent_ac_balance_storage_energy_and_soc_bounds(comp):
    rows = _truth_rows(comp)
    for r in rows:
        lhs = (
            float(r["F1_pv_ac_kwh"])
            + float(r["F1_import_kwh"])
            + float(r["F1_batt_discharge_ac_kwh"])
        )
        rhs = (
            float(r["F1_load_kwh"])
            + float(r["F1_export_kwh"])
            + float(r["F1_batt_charge_ac_kwh"])
        )
        assert abs(lhs - rhs) < 5e-6  # 6-decimal rounding of the published truth
        assert 20.0 - 1e-6 <= float(r["F1_soc_pct_start"]) <= 100.0 + 1e-6
    for a, b in zip(rows, rows[1:], strict=False):
        e_next = (
            float(a["F1_storage_kwh_start"])
            + 0.95 * float(a["F1_batt_charge_ac_kwh"])
            - float(a["F1_batt_discharge_ac_kwh"]) / 0.95
        )
        assert abs(e_next - float(b["F1_storage_kwh_start"])) < 1e-4


def test_pv_equals_existing_inverter_fixture(comp, gen):
    import generate_components

    tl, _wx, _specs, sims = generate_components.latent(
        42, generate_components.date(2026, 7, 15), 7
    )
    seen = 0
    for line in (
        gen
        / "demo_data"
        / "fronius"
        / "clean_reference"
        / "GetPowerFlowRealtimeData.ndjson"
    ).open(encoding="utf-8"):
        obj = json.loads(line)
        if obj["mock_transport"]["binding"]["site_id"] != "FR-SITE-0001":
            continue
        pv = obj["payload"]["Body"]["Data"]["Site"]["P_PV"]
        if pv is None:
            continue
        i = int(
            (
                ms(obj["payload"]["Head"]["Timestamp"])
                - 1000
                - tl.start_utc.timestamp() * 1000
            )
            // 60000
        )
        assert abs(pv - sims["F1"]["inv_ac"][i] * 1000) <= 0.05
        seen += 1
        if seen > 500:
            break
    assert seen > 500


def test_counter_energy_matches_latent_flows_on_measured_frames(comp):
    truth = {ms(r["frame_start_utc"]): r for r in _truth_rows(comp)}
    for site, col in ((F1, "F1"), (F2, "F2"), (H2, "H2")):
        for metric, key in (
            ("interval_grid_import_kwh", "import"),
            ("interval_grid_export_kwh", "export"),
        ):
            rows = q(
                comp,
                "SELECT frame_start_ms, value_kwh FROM authority_frames WHERE site_key=? AND metric_name=? "
                "AND value_origin='measured'",
                (site, metric),
            )
            assert len(rows) > 600
            for fs, v in rows:
                assert abs(v - float(truth[fs][f"{col}_{key}_kwh"])) <= 0.0025, (
                    site,
                    metric,
                    fs,
                )


def test_both_directions_accumulate_within_intervals(comp):
    n = q(
        comp,
        "SELECT COUNT(*) FROM authority_frames a JOIN authority_frames b USING(site_key, frame_start_ms) WHERE "
        "a.metric_name='interval_grid_import_kwh' AND b.metric_name='interval_grid_export_kwh' AND "
        "a.value_kwh > 0.001 AND b.value_kwh > 0.001 AND a.value_origin='measured'",
    )[0][0]
    assert n > 10


def test_per_phase_power_sums_to_total(comp):
    rows = q(
        comp,
        "SELECT o.raw_record_id, o.metric_name, o.canonical_value FROM observations o WHERE "
        "o.physical_asset_id IN ('F1-M1-PCC','F2-M2-FEEDIN','H2-M3-PCC') AND o.availability_status='available' "
        "AND o.metric_name IN ('grid_net_kw','phase_active_power_kw')",
    )
    agg = {}
    for rid, m, v in rows:
        a = agg.setdefault(rid, [0.0, None, 0])
        if m == "grid_net_kw":
            a[1] = v
        else:
            a[0] += v
            a[2] += 1
    full = [a for a in agg.values() if a[1] is not None and a[2] == 3]
    assert len(full) > 5000
    assert (
        max(abs(a[0] - a[1]) for a in full) < 0.0005
    )  # Float32 / 0.1 W rounding tolerance


def test_battery_limits_and_soc_respected_in_normal_windows(comp):
    rows = q(
        comp,
        "SELECT c.canonical_value, l.canonical_value FROM observations c JOIN observations l ON "
        "l.raw_record_id=c.raw_record_id AND l.metric_name='battery_max_discharge_current_a' WHERE "
        "c.metric_name='battery_current_a' AND c.availability_status='available' AND c.canonical_value>0",
    )
    assert rows and all(i <= lim + 0.11 for i, lim in rows)
    assert (
        q(
            comp,
            "SELECT MAX(canonical_value) FROM observations WHERE metric_name='soc_pct' AND "
            "availability_status='available'",
        )[0][0]
        <= 100.0
    )


# ------------------------------------------------------------------ golden windows (per profile)
def _obs(comp, asset, metric, t_ms, channel=None):
    return q(
        comp,
        "SELECT canonical_value, exact_value_text, mounting, aggregation, interval_start_ms FROM observations "
        "WHERE physical_asset_id=? AND metric_name=? AND COALESCE(channel,'')=COALESCE(?,'') AND "
        "effective_time_ms=? AND availability_status='available'",
        (asset, metric, channel, t_ms),
    )


def _check(comp, asset, t_iso, expected, tol):
    for e in expected:
        rows = _obs(comp, asset, e["metric"], ms(t_iso), e.get("channel"))
        assert len(rows) == 1, (asset, e, t_iso)
        v, ex, mnt, agg, ivs = rows[0]
        if "exact" in e:
            assert ex == e["exact"], (asset, e)
        else:
            assert abs(v - e["value"]) <= max(tol, 1e-9), (asset, e, v)
        if e.get("mounting"):
            assert mnt == e["mounting"]
        if e.get("aggregation"):
            assert agg == e["aggregation"]


def test_golden_windows_every_profile(comp):
    g = {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in (comp["truth"] / "golden").glob("*.json")
    }
    assert set(g) >= {
        "m1_schneider_iem3255_modbus",
        "m2_fronius_smart_meter_solar_api",
        "m3_shelly_pro3em_rpc",
        "b1_victron_gx_battery_modbus",
        "b2_solaredge_storagedata",
        "w1_imt_si_rs485tc",
        "w2_kipp_smp10x_modbus",
        "w3_campbell_toa5_station",
        "equivalence",
    }
    for pid, d in g.items():
        if pid == "equivalence":
            continue
        if pid == "m3_shelly_pro3em_rpc":
            em = [e for e in d["expected"] if not e["metric"].startswith("resettable")]
            _check(comp, d["asset_id"], d["effective_time_utc_em"], em, d["tolerance"])
            _check(
                comp,
                d["asset_id"],
                d["effective_time_utc_emdata"],
                [e for e in d["expected"] if e["metric"].startswith("resettable")],
                d["tolerance"],
            )
        elif "windows" in d:
            for w in d["windows"]:
                _check(
                    comp,
                    d["asset_id"],
                    w["effective_time_utc"],
                    w["expected"],
                    w["tolerance"],
                )
        else:
            _check(
                comp,
                d["asset_id"],
                d["effective_time_utc"],
                d["expected"],
                d["tolerance"],
            )
    w3 = g["w3_campbell_toa5_station"]
    row = _obs(
        comp, w3["asset_id"], "irradiance_wm2", ms(w3["effective_time_utc"]), "avg"
    )[0]
    assert row[4] == ms(
        w3["interval_start_utc"]
    )  # TIMESTAMP labels the interval END (logger clock UTC+2)


# ------------------------------------------------------------------ equivalence across profiles (test-only bench)
def test_equivalent_meter_and_weather_encodings_normalise_identically(comp):
    con = sqlite3.connect(str(comp["build"] / "side" / "component_equivalence.sqlite"))
    eq = json.loads(
        (comp["truth"] / "golden" / "equivalence.json").read_text(encoding="utf-8")
    )

    def val(asset, metric, channel=None, order=0):
        r = con.execute(
            "SELECT canonical_value FROM observations WHERE physical_asset_id=? AND metric_name=? AND "
            "COALESCE(channel,'')=COALESCE(?,'') AND availability_status='available' ORDER BY "
            "effective_time_ms",
            (asset, metric, channel),
        ).fetchall()
        return r[order][0]

    counters = {
        "EQ-M1": "lifetime_grid",
        "EQ-M2": "lifetime_grid",
        "EQ-M3": "resettable_grid",
    }
    for a in ("EQ-M1", "EQ-M2", "EQ-M3"):
        assert val(a, "grid_net_kw", order=0) == pytest.approx(-1.234, abs=1e-6)
        assert val(a, "grid_net_kw", order=1) == pytest.approx(0.75, abs=1e-6)
        assert val(a, "phase_active_power_kw", "L1") == pytest.approx(-0.6, abs=1e-6)
        assert val(a, "phase_voltage_v", "L2") == pytest.approx(229.8, abs=1e-4)
        assert val(a, f"{counters[a]}_import_kwh") == pytest.approx(12345.678, abs=1e-9)
        assert val(a, f"{counters[a]}_export_kwh", order=1) == pytest.approx(
            9876.601, abs=1e-9
        )
        for m, want in (
            ("interval_grid_import_kwh", 0.042),
            ("interval_grid_export_kwh", 0.058),
        ):
            e = con.execute(
                "SELECT energy_kwh FROM interval_energy i WHERE metric_name=? AND status='valid' AND "
                "device_key LIKE ?",
                (
                    m,
                    f"%|{con.execute('SELECT device_id FROM observations WHERE physical_asset_id=? LIMIT 1', (a,)).fetchone()[0]}",
                ),
            ).fetchall()
            assert [round(x[0], 9) for x in e] == [want], (a, m)
    assert (
        con.execute(
            "SELECT exact_value_text FROM observations WHERE physical_asset_id='EQ-M1' AND "
            "metric_name='lifetime_grid_import_kwh' ORDER BY effective_time_ms"
        ).fetchone()[0]
        == "12345.678"
    )
    for a, ch in (("EQ-W1", None), ("EQ-W2-POA", None), ("EQ-W3", "avg")):
        assert val(a, "irradiance_wm2", ch) == pytest.approx(
            eq["weather"]["poa_wm2"], abs=1e-9
        )
    for a in ("EQ-W1", "EQ-W3"):
        assert val(a, "module_temperature_c") == pytest.approx(41.3, abs=1e-9)
    ghi = con.execute(
        "SELECT canonical_value, mounting FROM observations WHERE physical_asset_id='EQ-W2-GHI' AND "
        "metric_name='irradiance_wm2'"
    ).fetchall()
    assert ghi == [
        (640.0, "horizontal")
    ]  # scale factor 0 and horizontal mounting from the registry
    sc = eq["weather"]["signed_cases"]
    assert val("EQ-W1", "reference_cell_temperature_c", order=1) == pytest.approx(
        sc["w1_cell_c"]
    )
    assert val("EQ-W1", "module_temperature_c", order=1) == pytest.approx(
        sc["w1_module_c"]
    )
    assert val("EQ-W2-POA", "sensor_body_temperature_c") == pytest.approx(
        sc["w2_body_c"]
    )
    assert val("EQ-W2-POA", "irradiance_wm2", order=1) == pytest.approx(
        sc["w2_night_offset_wm2"]
    )
    rev = con.execute(
        "SELECT canonical_value, transform_log FROM observations WHERE physical_asset_id='EQ-M3-CTREV' "
        "AND metric_name='phase_active_power_kw' AND channel='L3'"
    ).fetchone()
    assert rev[0] == pytest.approx(0.23) and "sign:configured_reversed" in rev[1]
    # equivalence encodings never reach the production snapshot
    assert not q(
        comp, "SELECT 1 FROM observations WHERE physical_asset_id LIKE 'EQ-%' LIMIT 1"
    )
    con.close()


# ------------------------------------------------------------------ field semantics
def test_units_signs_and_exact_counters(comp):
    # W -> kW (Fronius/Shelly), kW native (Schneider), Wh -> kWh with exact text for Int64
    r = q(
        comp,
        "SELECT original_unit, transform_log FROM observations WHERE physical_asset_id='F2-M2-FEEDIN' AND "
        "metric_name='grid_net_kw' LIMIT 1",
    )[0]
    assert r[0] == "W" and "unit:W->kW" in r[1]
    r = q(
        comp,
        "SELECT original_unit, exact_value_text, canonical_value FROM observations WHERE "
        "physical_asset_id='F1-M1-PCC' AND metric_name='lifetime_grid_import_kwh' AND "
        "availability_status='available' LIMIT 1",
    )[0]
    assert r[0] == "Wh" and r[1] is not None and float(r[1]) == r[2]
    # B2: native + charging -> canonical + discharge ; B1 current/power negated with provenance
    raw = q(
        comp,
        "SELECT original_value, canonical_value FROM observations WHERE physical_asset_id='S3-B2-BAT' AND "
        "metric_name='battery_net_kw' AND canonical_value<>0 LIMIT 50",
    )
    assert raw and all(abs(float(o) / 1000.0 + v) < 1e-9 for o, v in raw)
    log = q(
        comp,
        "SELECT transform_log FROM observations WHERE physical_asset_id='F1-B1-BMS' AND "
        "metric_name='battery_current_a' LIMIT 1",
    )[0][0]
    assert "sign:documented_native_convention_negated" in log
    # register number vs protocol address preserved in raw evidence
    ov = json.loads(
        q(
            comp,
            "SELECT original_value FROM observations WHERE field_rule_id='m1.p_total' LIMIT 1",
        )[0][0]
    )
    assert (
        ov["register"] == 3060
        and ov["address"] == 3059
        and ov["word_order"] == "high_word_first"
    )


def test_boundaries_and_sensor_positions_are_kept_apart(comp):
    b = dict(
        q(
            comp,
            "SELECT metric_name, GROUP_CONCAT(DISTINCT boundary) FROM observations WHERE family IS NOT NULL "
            "AND metric_name IN ('battery_net_kw','grid_net_kw','interval_grid_import_kwh') GROUP BY 1",
        )
    )
    assert b == {"battery_net_kw": "dc_battery", "grid_net_kw": "grid_pcc"}
    pos = dict(
        q(
            comp,
            "SELECT metric_name, GROUP_CONCAT(DISTINCT sensor_position) FROM observations WHERE metric_name "
            "LIKE '%temperature_c' AND family IS NOT NULL GROUP BY 1",
        )
    )
    assert pos["module_temperature_c"] == "back_of_module"
    assert pos["sensor_body_temperature_c"] == "instrument_body"
    assert pos["reference_cell_temperature_c"] == "irradiance_reference_cell"
    assert pos["ambient_temperature_c"] == "shielded_ambient"
    assert set(pos["battery_temperature_c"].split(",")) == {
        "battery",
        "battery_internal",
    }
    assert not q(
        comp,
        "SELECT 1 FROM observations WHERE metric_name='ambient_temperature_c' AND physical_asset_id<>"
        "'WX-S1-CS01-LOGGER'",
    )
    assert {
        r[0]
        for r in q(
            comp,
            "SELECT DISTINCT mounting FROM observations WHERE metric_name='irradiance_wm2'",
        )
    } == {"poa"}
    assert not q(
        comp,
        "SELECT 1 FROM observations WHERE metric_name IN ('pv_ac_kw','pv_dc_kw') AND family IS NOT NULL",
    )


def test_unsupported_registers_are_unavailable_not_zero(comp):
    caps = q(
        comp,
        "SELECT metric_name, channel, state FROM capability_states WHERE field_rule_id IN "
        "('w1.reg9_unsupported','w1.reg3_unsupported')",
    )
    assert {(m, s) for m, _c, s in caps} == {
        ("module_temperature_c", "unsupported"),
        ("wind_speed_ms", "unsupported"),
    }
    assert not q(
        comp,
        "SELECT 1 FROM observations WHERE metric_name='wind_speed_ms' OR channel='external_temperature_2'",
    )


# ------------------------------------------------------------------ defects per fault manifest
def test_fault_manifest_cases_are_handled(comp):
    f = comp["faults"]
    assert len(f) >= 15
    # access failure M1
    a, b = map(ms, f["F-M1-ACCESS"]["window_utc"])
    assert (
        q(
            comp,
            "SELECT COUNT(*) FROM delivery_events WHERE site_key=? AND endpoint_key='register_snapshot' AND "
            "status_class='timeout'",
            (F1,),
        )[0][0]
        == 9
    )
    nulls = q(
        comp,
        "SELECT COUNT(*) FROM authority_frames WHERE site_key=? AND frame_start_ms BETWEEN ? AND ? AND "
        "value_kwh IS NULL",
        (F1, a - 900000, b),
    )[0][0]
    assert nulls >= 4 and not q(
        comp,
        "SELECT 1 FROM authority_frames WHERE value_kwh=0 AND authority_status="
        "'no_complete_source'",
    )
    # word order without evidence: flagged, never re-decoded
    assert (
        q(
            comp,
            "SELECT COUNT(*) FROM quality_issues WHERE issue_code='register_decode_configuration_suspect'",
        )[0][0]
        == 6
    )
    a, b = map(ms, f["F-M1-WORDORDER"]["window_utc"])
    assert not q(
        comp,
        "SELECT 1 FROM observations WHERE physical_asset_id='F1-M1-PCC' AND effective_time_ms BETWEEN ? "
        "AND ? AND availability_status='available' AND metric_kind<>'state'",
        (a, b + 60000),
    )
    # invalid SoC never clamped
    a, _ = map(ms, f["F-B1-SOC108"]["window_utc"])
    r = q(
        comp,
        "SELECT availability_status, original_value, canonical_value FROM observations WHERE "
        "physical_asset_id='F1-B1-BMS' AND metric_name='soc_pct' AND effective_time_ms BETWEEN ? AND ?",
        (a, a + 60000),
    )[0]
    assert r[0] == "invalid" and '"1080"' in r[1] and r[2] is None
    assert (
        q(
            comp,
            "SELECT COUNT(*) FROM observations WHERE physical_asset_id='F1-B1-BMS' AND effective_time_ms BETWEEN "
            "? AND ? AND availability_status='available'",
            (a, a + 60000),
        )[0][0]
        >= 15
    )
    # reported fault + derating (genuine event)
    ep = q(
        comp,
        "SELECT start_utc, active_at_as_of FROM state_episodes WHERE physical_asset_id='F1-B1-BMS' AND "
        "channel='internal_failure'",
    )
    assert ep == [("2026-07-18T06:40:01.277Z", 1)] or (
        len(ep) == 1 and ep[0][1] == 1 and ep[0][0].startswith("2026-07-18T06:40")
    )
    assert q(
        comp,
        "SELECT value, below_declared_nominal FROM limit_history WHERE physical_asset_id='F1-B1-BMS' AND "
        "metric_name='battery_max_discharge_current_a' ORDER BY start_ms",
    ) == [(100.0, 0), (25.0, 1)]
    # Fronius Visible=0 -> withheld
    assert (
        q(
            comp,
            "SELECT COUNT(DISTINCT raw_record_id) FROM observations WHERE physical_asset_id='F2-M2-FEEDIN' AND "
            "availability_status='withheld'",
        )[0][0]
        == 3
    )
    # unexplained backwards step: flagged, no invented reset, no negative energy
    assert q(
        comp,
        "SELECT status FROM interval_energy WHERE rule_id='m2.export_from_counter' AND energy_kwh IS NULL",
    ) == [("counter_discontinuity",)]
    assert (
        q(
            comp,
            "SELECT COUNT(*) FROM quality_issues WHERE issue_code='unexplained_counter_decrease'",
        )[0][0]
        == 1
    )
    assert q(comp, "SELECT MIN(energy_kwh) FROM interval_energy")[0][0] >= 0
    # Shelly known reset: new segment, delta withheld, later deltas valid
    st = q(
        comp,
        "SELECT status, start_ms FROM interval_energy WHERE rule_id='m3.import_from_counter' ORDER BY start_ms",
    )
    i = [k for k, (s, _) in enumerate(st) if s == "segment_start_known_reset"]
    assert len(i) == 1 and st[i[0] + 1][0] == "valid"
    # gap: total over the span, not allocated
    assert "gap_span_total" in {s for s, _ in st}
    # exact duplicate, out-of-order
    assert (
        q(
            comp,
            "SELECT COUNT(*) FROM raw_records WHERE status='exact_duplicate' AND site_key=?",
            (H2,),
        )[0][0]
        == 7
    )
    a, b = map(ms, f["F-M3-OOO"]["window_utc"])
    late = q(
        comp,
        "SELECT COUNT(*) FROM raw_records WHERE endpoint_key='EM.GetStatus' AND effective_time_ms BETWEEN ? "
        "AND ? AND record_flags LIKE '%late_arrival%'",
        (a, b + 60000),
    )[0][0]
    assert late == 13
    # missing optional sensor: module temperature missing, ambient intact
    assert (
        q(
            comp,
            "SELECT COUNT(*) FROM observations WHERE metric_name='module_temperature_c' AND "
            "physical_asset_id='WX-S1-CS01-LOGGER' AND availability_status='missing' AND quality_flags LIKE "
            "'%source_missing_token%'",
        )[0][0]
        == 300
    )
    assert (
        q(
            comp,
            "SELECT COUNT(*) FROM observations WHERE metric_name='ambient_temperature_c' AND "
            "availability_status='available'",
        )[0][0]
        == 10080
    )
    # night offsets are not faults
    assert (
        q(
            comp,
            "SELECT COUNT(*) FROM observations WHERE physical_asset_id='S2-W2-POA' AND metric_name="
            "'irradiance_wm2' AND canonical_value<0 AND availability_status='available'",
        )[0][0]
        > 3000
    )
    assert not q(
        comp, "SELECT 1 FROM review_candidates WHERE metric_name='irradiance_wm2'"
    )
    # shared collector outage H1 + H2
    out = q(
        comp,
        "SELECT affected_site_keys, start_ms, end_ms FROM collector_outages WHERE collector_id='COL-HW-NBI-01'",
    )
    a, b = map(ms, f["F-H1H2-COLLECTOR"]["window_utc"])
    assert (
        len(out) == 1
        and len(json.loads(out[0][0])) == 2
        and a <= out[0][1]
        and out[0][2] <= b
    )
    # existing B2 access denial stays an access state (no zeros)
    assert (
        q(
            comp,
            "SELECT COUNT(*) FROM delivery_events WHERE site_key=? AND status_class='access_denied'",
            (S3,),
        )[0][0]
        == 24
    )


# ------------------------------------------------------------------ authority, mirrors, capabilities
def test_one_authoritative_grid_stream_and_mirror_never_summed(comp):
    rows = q(
        comp,
        "SELECT frame_start_ms, value_kwh, selected_role, candidates_json, mirrors_excluded FROM "
        "authority_frames WHERE site_key=? AND metric_name='interval_grid_import_kwh'",
        (F2,),
    )
    assert len(rows) == 672
    roles = {}
    for _fs, v, role, cj, mir in rows:
        roles[role] = roles.get(role, 0) + 1
        cands = json.loads(cj)
        assert "GetPowerFlowRealtimeData" in mir
        if v is not None:
            sel = [c for c in cands if c["role"] == role][0]
            assert sel["value_kwh"] == pytest.approx(
                v, abs=1e-6
            )  # exactly one source, never a sum
            assert all(not c["complete"] for c in cands if c["rank"] < sel["rank"])
    assert roles["primary"] > 650 and roles.get("mirror_fallback", 0) <= 3
    truth = sum(float(r["F2_import_kwh"]) for r in _truth_rows(comp))
    total = sum(v for _, v, *_ in rows if v is not None)
    assert total == pytest.approx(
        truth, rel=0.02
    )  # no double counting of the mirrored meter


def test_capability_degradation_energy_only_battery(comp):
    caps = {
        (s, c): st
        for s, c, st in q(
            comp, "SELECT site_key, capability, state FROM capability_registry"
        )
    }
    assert caps[(S3, "battery_limits_available")] == "not_declared"
    assert caps[(S3, "battery_soc_available")] == "available"
    assert caps[(F1, "battery_limits_available")] == "available"
    assert caps[(H2, "grid_energy_measured")] == "available"
    assert (
        caps[("huawei|hw-nbi-demo-01|NE=33554791", "irradiance_poa_available")]
        == "available"
    )  # via linked station
    bs = {
        a: (lim, soc)
        for a, lim, soc in q(
            comp,
            "SELECT physical_asset_id, limits_available, soc_pct FROM battery_status",
        )
    }
    assert (
        bs["S3-B2-BAT"][0] == 0
        and bs["F1-B1-BMS"][0] == 1
        and bs["F1-B1-BMS"][1] <= 100
    )


def test_b2_reuses_existing_identity(comp):
    assert q(
        comp,
        "SELECT DISTINCT device_id FROM observations WHERE physical_asset_id='S3-B2-BAT'",
    ) == [("BAT-00A1B2C3",)]
    assert q(
        comp,
        "SELECT DISTINCT provider_profile_id FROM raw_records WHERE endpoint_key='storageData'",
    ) == [("b2_solaredge_storagedata",)]


def test_repeat_scrape_is_idempotent(comp, gen):
    import scraper

    before = q(comp, "SELECT COUNT(*) FROM observations")[0][0]
    auth = q(
        comp,
        "SELECT site_key, metric_name, frame_start_ms, value_kwh, authority_status FROM authority_frames "
        "ORDER BY 1,2,3",
    )
    reg, sites, store, _, _ = scraper.component_ingest(
        [COMP_CONFIG],
        comp["out"],
        comp["build"] / "component.sqlite",
        AS_OF,
        None,
        log=lambda m: None,
    )
    assert store.q(
        "SELECT deliveries_new, observations_added FROM runs ORDER BY started_at_utc DESC LIMIT 1"
    )[0] == (0, 0)
    store.close()
    assert q(comp, "SELECT COUNT(*) FROM observations")[0][0] == before
    assert (
        q(
            comp,
            "SELECT site_key, metric_name, frame_start_ms, value_kwh, authority_status FROM authority_frames "
            "ORDER BY 1,2,3",
        )
        == auth
    )


def test_component_subset_selection(comp, gen):
    import scraper

    db = gen / "components_battery" / "c.sqlite"
    _, _, store, _, _ = scraper.component_ingest(
        [COMP_CONFIG], comp["out"], db, AS_OF, {"battery"}, log=lambda m: None
    )
    fams = {r[0] for r in store.q("SELECT DISTINCT family FROM observations")}
    assert fams == {"battery"}
    store.close()
