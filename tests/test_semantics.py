"""Direction/sign semantics, units, availability states and time roles on small crafted payloads that go
through the real registry and engine (no re-implementation of the mapping in the test)."""
import pytest

from conftest import envelope, obs


def fr_pf(site_fields, inverters=None, ts="2026-07-16T12:00:01+03:00"):
    site = {"E_Day": None, "E_Total": 6000000.0, "E_Year": None, "Meter_Location": "grid", "Mode": "bidirectional",
            "P_Akku": None, "P_Grid": None, "P_Load": None, "P_PV": None, "rel_Autonomy": None,
            "rel_SelfConsumption": None}
    site.update(site_fields)
    return {"Body": {"Data": {"Inverters": inverters or {}, "Site": site, "Version": "12"}},
            "Head": {"RequestArguments": {}, "Status": {"Code": 0, "Reason": "", "UserMessage": ""}, "Timestamp": ts}}


def by_metric(rows):
    out = {}
    for r in rows:
        out.setdefault(r["metric"], []).append(r)
    return out


def test_fronius_signed_flows(mini):
    lines = [envelope("F3", "GetPowerFlowRealtimeData", fr_pf({"P_Grid": -1500.0, "P_Load": -900.0, "P_Akku": -800.0,
                                                               "P_PV": 3300.0}), delivery_id="a"),
             envelope("F3", "GetPowerFlowRealtimeData", fr_pf({"P_Grid": 700.0, "P_Load": -1200.0, "P_Akku": 500.0,
                                                               "P_PV": 0.0}, ts="2026-07-16T12:01:01+03:00"),
                      recorded="2026-07-16T09:01:01.500Z", delivery_id="b"),
             envelope("F3", "GetPowerFlowRealtimeData", fr_pf({"P_Grid": 0.0, "P_Load": -300.0, "P_Akku": 0.0,
                                                               "P_PV": 300.0}, ts="2026-07-16T12:02:01+03:00"),
                      recorded="2026-07-16T09:02:01.500Z", delivery_id="c")]
    con = mini(lines)
    m = by_metric(obs(con, where="ORDER BY o.effective_time_ms"))
    assert [r["value"] for r in m["grid_export_kw"]] == [1.5, 0.0, 0.0]
    assert [r["value"] for r in m["grid_import_kw"]] == [0.0, 0.7, 0.0]
    assert [r["value"] for r in m["battery_charge_kw"]] == [0.8, 0.0, 0.0]
    assert [r["value"] for r in m["battery_discharge_kw"]] == [0.0, 0.5, 0.0]
    assert [r["value"] for r in m["household_load_kw"]] == [0.9, 1.2, 0.3]
    assert all(r["avail"] == "available" for rs in m.values() for r in rs if r["metric"] != "daily_yield_kwh")
    # hybrid P_PV is DC generation: never pv_ac_kw / inverter output
    assert [r["value"] for r in m["pv_dc_kw"]] == [3.3, 0.0, 0.3]
    assert "pv_ac_kw" not in m and all(r["boundary"] == "dc_pv_input" for r in m["pv_dc_kw"])
    assert m["grid_export_kw"][0]["orig"] == "-1500.0"  # signed original preserved


def test_fronius_null_vs_zero_vs_missing_key(mini):
    lines = [envelope("F2", "GetPowerFlowRealtimeData", fr_pf({"P_Grid": None, "P_Load": None, "P_PV": None,
                                                               "E_Day": 0.0, "Mode": "meter"})),
             envelope("F2", "GetPowerFlowRealtimeData",
                      {"Body": {"Data": {"Inverters": {}, "Site": {"E_Day": 0.0, "E_Total": 1.0, "E_Year": 1.0,
                                                                   "P_Load": -100.0, "P_PV": 0.0, "P_Akku": None},
                                         "Version": "12"}},
                       "Head": {"RequestArguments": {}, "Status": {"Code": 0, "Reason": "", "UserMessage": ""},
                                "Timestamp": "2026-07-16T12:05:01+03:00"}}, recorded="2026-07-16T09:05:01.5Z",
                      delivery_id="z")]
    con = mini(lines)
    rows = obs(con, where="ORDER BY o.effective_time_ms, o.obs_id")
    first = [r for r in rows if r["metric"] in ("grid_import_kw", "pv_ac_kw")][:2]
    assert all(r["avail"] == "missing" and "vendor_permitted_null" in r["flags"] for r in first)
    pv0 = [r for r in rows if r["metric"] == "pv_ac_kw"][1]
    assert pv0["avail"] == "available" and pv0["value"] == 0.0  # zero is a value, null is not
    imp2 = [r for r in rows if r["metric"] == "grid_import_kw"][1]
    assert imp2["avail"] == "missing" and "required_key_missing" in imp2["flags"]
    load2 = [r for r in rows if r["metric"] == "household_load_kw"][1]
    assert load2["avail"] == "available" and load2["value"] == 0.1  # other fields of a damaged record survive
    assert con.execute("SELECT COUNT(*) FROM quality_issues WHERE issue_code='required_key_missing'").fetchone()[0] == 1
    # battery not installed on F2: capability state, not missing data
    assert not [r for r in rows if r["metric"].startswith("battery_")]
    st = con.execute("SELECT state FROM capability_states WHERE metric_name='battery_charge_kw'").fetchall()
    assert st == [("not_installed",)]


def se_flow(unit="kW", grid=0.0, load=0.0, pv=0.0, storage=None, conns=()):
    f = {"updateRefreshRate": 3, "unit": unit, "connections": [{"from": a, "to": b} for a, b in conns],
         "GRID": {"status": "Active", "currentPower": grid}, "LOAD": {"status": "Active", "currentPower": load},
         "PV": {"status": "Active", "currentPower": pv}}
    if storage is not None:
        f["STORAGE"] = {"status": "Active", "currentPower": storage, "chargeLevel": 60, "critical": False}
    return {"siteCurrentPowerFlow": f}


@pytest.mark.parametrize("payload,expect", [
    (se_flow(grid=2.0, load=3.0, pv=1.0, storage=0.0, conns=[("GRID", "Load"), ("PV", "Load")]),
     {"grid_import_kw": 2.0, "grid_export_kw": 0.0, "household_load_kw": 3.0, "battery_charge_kw": 0.0}),
    (se_flow(grid=1.5, load=1.0, pv=3.0, storage=0.5, conns=[("PV", "Load"), ("LOAD", "Grid"), ("PV", "Storage")]),
     {"grid_import_kw": 0.0, "grid_export_kw": 1.5, "battery_charge_kw": 0.5, "battery_discharge_kw": 0.0}),
    (se_flow(grid=0.0, load=0.8, pv=0.0, storage=0.8, conns=[("STORAGE", "Load")]),
     {"battery_discharge_kw": 0.8, "battery_charge_kw": 0.0, "grid_import_kw": 0.0, "grid_export_kw": 0.0}),
    (se_flow(unit="W", grid=2000.0, load=2000.0, storage=0.0, conns=[("GRID", "Load")]),
     {"grid_import_kw": 2.0, "household_load_kw": 2.0}),
    (se_flow(grid=0.0, load=0.0, pv=0.0, storage=0.0), {"grid_import_kw": 0.0, "grid_export_kw": 0.0}),
])
def test_solaredge_edge_directed_flows(mini, payload, expect):
    con = mini([envelope("S3", "currentPowerFlow", payload)])
    got = {r["metric"]: r["value"] for r in obs(con)}
    for k, v in expect.items():
        assert got[k] == pytest.approx(v), k


def test_solaredge_nonzero_magnitude_without_edge_is_not_guessed(mini):
    con = mini([envelope("S3", "currentPowerFlow", se_flow(grid=1.2, load=1.2, storage=0.0, conns=[]))])
    g = {r["metric"]: r for r in obs(con)}
    assert g["grid_import_kw"]["avail"] == "invalid" and g["grid_export_kw"]["avail"] == "invalid"
    assert g["household_load_kw"]["value"] == 1.2


def test_solaredge_empty_powerflow_is_capability_not_zero_home(mini):
    con = mini([envelope("S1", "currentPowerFlow", {})])
    assert obs(con) == []
    st = {r[0] for r in con.execute("SELECT state FROM capability_states").fetchall()}
    assert "unsupported" in st or "not_installed" in st
    assert con.execute("SELECT status FROM raw_deliveries").fetchone()[0] == "empty_response"


def test_storage_data_sign_differs_from_powerflow(mini):
    tel = {"timeStamp": "2026-07-16 12:00:00", "power": 1200.0, "batteryState": 3, "lifeTimeEnergyCharged": 1.0e6,
           "lifeTimeEnergyDischarged": 9.0e5, "internalTemp": 27.5, "stateOfCharge": 61.0}
    tel2 = dict(tel, timeStamp="2026-07-16 12:15:00", power=-700.0)
    pl = {"storageData": {"batteryCount": 1, "batteries": [{"serialNumber": "BAT-00A1B2C3", "telemetries": [tel, tel2]}]}}
    con = mini([envelope("S3", "storageData", pl)])
    m = by_metric(obs(con, where="ORDER BY o.effective_time_ms"))
    assert [r["value"] for r in m["battery_charge_kw"]] == [1.2, 0.0]
    assert [r["value"] for r in m["battery_discharge_kw"]] == [0.0, 0.7]
    assert m["battery_temperature_c"][0]["value"] == 27.5 and "inverter_temperature_c" not in m


def test_same_4200w_and_4_2kw_and_units(mini):
    hw = {"success": True, "failCode": 0, "message": None, "params": {"devTypeId": 38, "currentTime": 1784192700000},
          "data": [{"devId": 1000000035350464, "collectTime": 1784192400000, "dataItemMap": {"active_power": 4.2}}]}
    se = {"data": {"count": 1, "telemetries": [{"date": "2026-07-16 12:00:00", "totalActivePower": 4200.0}]}}
    fr = fr_pf({"P_PV": 4200.0, "Mode": "produce-only"}, {"1": {"DT": 123, "P": 4200.0}})
    con = mini([envelope("H1", "getDevHistoryKpi", hw, {"devTypeId": 38}, delivery_id="h"),
                envelope("S1", "equipment_data", se, {"serialNumber": "7E0412A3-6B"}, delivery_id="s"),
                envelope("F1", "GetPowerFlowRealtimeData", fr, delivery_id="f")])
    ac = obs(con, "inverter_ac_output_kw")
    assert len(ac) == 3 and all(r["value"] == pytest.approx(4.2) for r in ac)
    assert {r["boundary"] for r in ac} == {"ac_inverter_output"}
    assert sorted(r["orig"] for r in ac) == ["4.2", "4200.0", "4200.0"]
    # absent optional fields stay missing, not zero
    assert {r["avail"] for r in obs(con, "inverter_temperature_c")} == {"missing"}
    # large integer id kept exactly as a string
    assert con.execute("SELECT device_id FROM raw_records WHERE provider='huawei'").fetchone()[0] == "1000000035350464"


def test_response_time_is_not_promoted_to_measurement_time(mini):
    con = mini([envelope("F1", "GetPowerFlowRealtimeData", fr_pf({"P_PV": 100.0, "Mode": "produce-only"}))])
    m, r, basis = con.execute("SELECT measurement_time_ms, response_time_ms, effective_time_basis FROM raw_records").fetchone()
    assert m is None and r is not None and basis == "response_time"


def test_realtime_lagging_response_is_stale_not_dropped(mini):
    con = mini([envelope("F1", "GetPowerFlowRealtimeData", fr_pf({"P_PV": 100.0, "Mode": "produce-only"}),
                         recorded="2026-07-16T09:10:00Z")])  # captured 10 min after the response timestamp
    r = obs(con, "pv_ac_kw")[0]
    assert r["avail"] == "stale" and r["value"] == 0.1


def test_http_403_400_429_and_failure_envelope_are_distinct(mini):
    hw_fail = {"success": False, "data": None, "failCode": 407, "params": {"devTypeId": 38}, "message": "x"}
    con = mini([envelope("S3", "storageData", None, {"query": {}}, http=403, delivery_id="1"),
                envelope("S3", "storageData", None, {"query": {}}, http=400, delivery_id="2"),
                envelope("S2", "equipment_data", None, {"serialNumber": "0071F2A3-9C"}, http=429, delivery_id="3"),
                envelope("H1", "getDevHistoryKpi", hw_fail, {"devTypeId": 38}, delivery_id="4")])
    cls = sorted(r[0] for r in con.execute("SELECT status_class FROM raw_deliveries").fetchall())
    assert cls == ["access_denied", "rate_limited", "rate_limited", "request_validation_error"]
    st = dict(con.execute("SELECT delivery_id, status FROM raw_deliveries").fetchall())
    assert st["4"] == "provider_failure" and st["1"] == "transport_error"
    assert obs(con) == []  # no substitute zeros anywhere


def test_malformed_record_does_not_stop_neighbours(mini):
    good = {"data": {"count": 1, "telemetries": [{"date": "2026-07-16 12:00:00", "totalActivePower": 1000.0}]}}
    bad_items = {"data": {"count": 2, "telemetries": [{"date": None, "totalActivePower": 5.0},
                                                      {"date": "2026-07-16 12:15:00", "totalActivePower": 2000.0}]}}
    con = mini([envelope("S1", "equipment_data", good, {"serialNumber": "7E0412A3-6B"}, delivery_id="1"),
                '{"mock_transport": {"delivery_id": "broken", "payload": {"tru',
                envelope("S1", "equipment_data", None, {"serialNumber": "7E0412A3-6B"}, payload_text='{"data": {"cou',
                         delivery_id="3"),
                envelope("S1", "equipment_data", bad_items, {"serialNumber": "7E0412A3-6B"}, delivery_id="4")])
    vals = sorted(r["value"] for r in obs(con, "inverter_ac_output_kw"))
    assert vals == [1.0, 2.0]
    st = sorted(r[0] for r in con.execute("SELECT status FROM raw_deliveries").fetchall())
    assert st == ["parsed_ok", "parsed_ok", "payload_parse_error", "unparseable_line"]
    raw = con.execute("SELECT raw_text FROM raw_deliveries WHERE status='unparseable_line'").fetchone()[0]
    assert raw.endswith('"tru')  # evidence preserved verbatim, not repaired


def test_unregistered_device_and_binding_are_quarantined(mini):
    tel = {"data": {"count": 1, "telemetries": [{"date": "2026-07-16 12:00:00", "totalActivePower": 1000.0}]}}
    line = envelope("S1", "equipment_data", tel, {"serialNumber": "7E0412A3-6C"})  # one char off: no fuzzy match
    other = line.replace('"2718281"', '"2718282"').replace('"T-1"', '"T-2"')
    con = mini([line, other])
    assert obs(con) == []
    codes = sorted(r[0] for r in con.execute("SELECT issue_code FROM quality_issues").fetchall())
    assert codes == ["unregistered_binding", "unregistered_device"]


def test_unregistered_or_missing_timezone_is_unresolved(mini, gen):
    import json
    sites = json.loads((gen / "demo_data" / "sites.json").read_text())
    for s in sites["sites"]:
        s.pop("timezone", None)
    tel = {"data": {"count": 1, "telemetries": [{"date": "2026-07-16 12:00:00", "totalActivePower": 1000.0}]}}
    con = mini([envelope("S1", "equipment_data", tel, {"serialNumber": "7E0412A3-6B"})], sites_doc=sites)
    assert obs(con) == []
    assert con.execute("SELECT status_reason FROM raw_records").fetchone()[0].startswith("unusable_time_missing_timezone")
