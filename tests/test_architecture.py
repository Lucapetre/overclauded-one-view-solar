"""One engine, config-only extensibility, no evaluation leakage, no unsafe surfaces."""
import hashlib
import json
import re
from pathlib import Path

import pytest

from conftest import AS_OF, CONFIG, ROOT, obs

ENGINE_FILES = sorted((ROOT / "engine").glob("*.py")) + [ROOT / "scraper.py"]
VENDOR_WORDS = re.compile(r"huawei|fronius|solaredge|fusionsolar|gen24|snapinverter|storedge|schneider|iem3255|"
                          r"shelly|victron|venus|cerbo|enphase|\bkipp|zonen|smp10|campbell|cr1000|toa5|\bimt\b",
                          re.I)


def _hash_engine():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in ENGINE_FILES}


def test_engine_has_no_provider_branches_or_names():
    for p in ENGINE_FILES:
        text = p.read_text(encoding="utf-8")
        assert not VENDOR_WORDS.search(text), f"provider-specific name in {p.name}"
        assert not re.search(r"class\s+\w+Scraper", text)
        assert not re.search(r"\b(eval|exec|compile)\s*\(", text.replace("re.compile(", "")), p.name


def test_engine_never_references_evaluation_material_except_guard():
    for p in ENGINE_FILES:
        text = p.read_text(encoding="utf-8")
        if p.name == "transport.py":
            text = text.replace('FORBIDDEN_NAMES = {"ground_truth", "injection_manifest.json"}', "")
        assert "ground_truth" not in text and "injection_manifest" not in text, p.name
    import generate_demo  # noqa: F401  (fixture tool exists, but the engine must not import it)
    for p in ENGINE_FILES:
        assert "generate_demo" not in p.read_text(encoding="utf-8"), p.name


def test_guard_refuses_tests_directory(gen):
    from engine.transport import EvaluationMaterialError, discover, guard
    with pytest.raises(EvaluationMaterialError):
        list(discover(ROOT / "tests", {"delivery"}))
    with pytest.raises(EvaluationMaterialError):
        guard(gen / "truth" / "injection_manifest.json")


def test_registry_rejects_unknown_transform(tmp_path):
    import yaml
    from engine.registry import Registry, RegistryError
    doc = yaml.safe_load(CONFIG.read_text())
    doc.pop("requirements_registry")
    doc.pop("review_policies")
    ep = doc["profiles"]["fronius_solar_api_v1_rev021"]["endpoints"][0]
    ep["entities"][0]["fields"][0]["transform"] = "python_expression"
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump(doc))
    with pytest.raises(RegistryError, match="not in the supported library"):
        Registry([p])


FOURTH = """
profiles:
  acme_demo_json_v1:
    provider: acme_demo
    display_name: "Fourth tiny SYNTHETIC provider (config-only extensibility test)"
    profile_version: "acme demo v1 (fictional)"
    numeric: {allow_numeric_strings: true, decimal_separator: ",", thousands_separator: null}
    failure_detection:
      - when: {path: payload.status, op: ne, value: ok}
        code_path: payload.status
        default_class: provider_failure
    endpoints:
      - endpoint_key: readings
        variant: meter_v1
        route: []
        mapping_version: "acme-1.0"
        cadence_s: 300
        records:
          iterate: [{alias: rd, path: payload.readings, kind: list}]
          device_id: {path: rd.meter, required: true}
          entity_scope: inverter
          times:
            - {role: measurement_time, path: rd.ts, format: iso_offset, is_measurement: true, required: true}
          effective_time_roles: [measurement_time]
          known_keys: [{path: rd, keys: [ts, meter, pac, etot]}]
        entities:
          - scope: inverter
            fields:
              - {id: acme.pac, source: rd.pac, metric: inverter_ac_output_kw, unit: kW, boundary: ac_inverter_output}
              - {id: acme.etot, source: rd.etot, metric: lifetime_yield_kwh, unit: kWh, boundary: ac_inverter_output}
        derive:
          - {id: acme.interval, method: counter_difference, from_metric: lifetime_yield_kwh, to_metric: interval_yield_kwh, counter: lifetime, max_gap_s: 900, resolution: 0.01}
"""


def test_fourth_provider_is_config_only(mini, tmp_path):
    before = _hash_engine()
    extra = tmp_path / "fourth.yaml"
    extra.write_text(FOURTH)
    sites = {"synthetic": True, "sites": [{"provider": "acme_demo", "account_id": "acme-1", "site_id": "A-1",
                                           "timezone": "Europe/Bucharest", "pv_kwp": 5.0, "rated_ac_kw_total": 4.6,
                                           "capabilities": {}, "devices": [{"device_id": "M-001", "rated_ac_kw": 4.6,
                                                                            "max_ac_kw": 4.6}]}]}
    lines = []
    for i, (ts, pac, et) in enumerate([("2026-07-16T12:00:00+03:00", "4,2", "1000,00"),
                                       ("2026-07-16T12:05:00+03:00", "4,3", "1000,36"),
                                       ("2026-07-16T12:10:00+03:00", "4.4", "1000,72")]):
        lines.append(json.dumps({"mock_transport": {"synthetic": True, "delivery_id": f"A-{i}",
                                                    "provider_profile_id": "acme_demo_json_v1",
                                                    "endpoint_key": "readings",
                                                    "binding": {"account_id": "acme-1", "site_id": "A-1"},
                                                    "recorded_at_utc": "2026-07-16T09:20:00Z",
                                                    "received_at_utc": "2026-07-16T09:20:01Z", "http_status": 200},
                                 "payload": {"status": "ok", "readings": [{"ts": ts, "meter": "M-001", "pac": pac,
                                                                          "etot": et}]}}))
    con = mini(lines, [CONFIG, extra], sites)
    pac = obs(con, "inverter_ac_output_kw", "ORDER BY o.effective_time_ms")
    assert [round(o["value"], 6) if o["value"] is not None else None for o in pac] == [4.2, 4.3, None]
    assert pac[2]["avail"] == "invalid" and "ambiguous_number" in pac[2]["flags"]  # '.' is not this locale
    e = con.execute("SELECT ROUND(SUM(energy_kwh),3) FROM interval_energy WHERE status='valid'").fetchone()[0]
    assert e == pytest.approx(0.72)
    assert _hash_engine() == before, "engine code changed while adding a provider"


def test_no_secrets_or_write_interfaces(gen):
    secret = re.compile(r'"(api_?key|password|passwd|secret|token|authorization)"\s*:', re.I)
    for p in [gen / "demo_data" / "sites.json", gen / "demo_data" / "regulatory_metadata.json", CONFIG]:
        assert not secret.search(p.read_text(encoding="utf-8")), p
    head = (gen / "demo_data" / "solaredge" / "delivery" / "equipment_data.ndjson").read_text().splitlines()[0]
    assert not secret.search(head) and "api_key" not in head.lower()
    for p in ENGINE_FILES + [ROOT / "mock_server.py"]:
        t = p.read_text(encoding="utf-8")
        assert 'method="POST"' not in t and "data=" not in t.replace("data=data", ""), p.name
        if p.name != "transport.py":
            assert "urlopen(" not in t, p.name
    assert "def do_POST" in (ROOT / "mock_server.py").read_text() and "405" in (ROOT / "mock_server.py").read_text()


def test_datasets_are_visibly_different_and_labelled(gen):
    d = gen / "demo_data"
    hw = json.loads((d / "huawei" / "delivery" / "getDevHistoryKpi.ndjson").read_text().splitlines()[0])
    fr = json.loads((d / "fronius" / "delivery" / "GetPowerFlowRealtimeData.ndjson").read_text().splitlines()[0])
    se = json.loads((d / "solaredge" / "delivery" / "currentPowerFlow.ndjson").read_text().splitlines()[-1])
    assert {"success", "data", "failCode", "params", "message"} <= set(hw["payload"])
    assert {"Head", "Body"} <= set(fr["payload"]) and "Timestamp" in fr["payload"]["Head"]
    assert set(se["payload"]) <= {"siteCurrentPowerFlow"}
    for env in (hw, fr, se):
        assert env["mock_transport"]["synthetic"] is True
        assert "recorded_at_utc" not in env["payload"]  # mock transport metadata stays outside native payload
    for prov in ("huawei", "fronius", "solaredge"):
        m = json.loads((d / prov / "manifest.json").read_text())
        assert m["synthetic"] and "SYNTHETIC" in m["disclaimer"]
        assert {f["dataset"] for f in m["files"]} == {"delivery", "clean_reference"}
        assert all(len(f["sha256"]) == 64 for f in m["files"])
    reg = json.loads((d / "regulatory_metadata.json").read_text())
    assert "NOT a certification" in reg["scope_note"]
    assert all("connection_point_ref" in s and s["connection_point_ref"].startswith("SYNTH-") for s in reg["sites"])
