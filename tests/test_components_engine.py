"""Fast unit tests for the component extensions of the shared engine (no dataset generation needed)."""

import json
import re
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
COMP_CONFIG = ROOT / "config" / "component_profiles.yaml"
EVIDENCE = ROOT / "config" / "component_evidence.yaml"


# ------------------------------------------------------------------ register words
def test_register_decode_types_signedness_and_word_order():
    from engine.transforms import decode_words

    assert (
        decode_words([0xFFD5], "int16", "high_word_first")[0] == -43
    )  # signed INT16 two's complement
    assert decode_words([0xFFD5], "uint16", "high_word_first")[0] == 65493
    assert decode_words([0x0001, 0x0002], "uint32", "high_word_first")[0] == 0x00010002
    assert decode_words([0x0001, 0x0002], "uint32", "low_word_first")[0] == 0x00020001
    assert decode_words([0xFFFF, 0xFFFE], "int32", "high_word_first")[0] == -2
    v, raw, st, _ = decode_words([0x4316, 0x0000], "float32", "high_word_first")
    assert (v, st) == (150.0, "ok")
    for nan in ([0x7FC0, 0x0000], [0xFFC0, 0x0000], [0x7F80, 0x0000]):
        assert decode_words(nan, "float32", "high_word_first")[2] == "nonfinite_float"


def test_int64_counter_stays_exact_beyond_float_precision():
    from engine.transforms import decimal_text, decode_words, exact_convert

    big = 2**53 + 1  # not representable as float64
    words = [(big >> s) & 0xFFFF for s in (48, 32, 16, 0)]
    val = decode_words(words, "int64", "high_word_first")[0]
    assert val == big and isinstance(val, int)
    units = {"Wh": {"canonical": "kWh", "factor": 0.001}}
    assert decimal_text(exact_convert(Decimal(val), "Wh", units)) == "9007199254740.993"
    assert float(big) != big  # the float view alone would lose the last Wh


def test_gather_words_and_scale_factor_register():
    from engine.transforms import gather_words, scale_from_register

    blocks = [{"start_address": 3027, "words": [1, 2, 3, 4, 5, 6]}]
    assert gather_words(blocks, 3029, 2) == ([3, 4], None)
    assert (
        gather_words(blocks, 3031, 4)[0] is None
    )  # beyond the captured block -> not invented
    assert gather_words([{"start_address": 0, "words": [70000]}], 0, 1)[0] is None
    assert scale_from_register(2, "pow10_negated") == Decimal("0.01")
    assert scale_from_register(-1, "pow10_negated") == Decimal("10")
    assert scale_from_register(-2, "pow10") == Decimal("0.01")  # SunSpec-style


# ------------------------------------------------------------------ registry validation
def _load_doc():
    return yaml.safe_load(COMP_CONFIG.read_text(encoding="utf-8"))


def _write(tmp_path, doc):
    p = tmp_path / "component_profiles.yaml"
    doc = dict(doc)
    doc["extends"] = [str(ROOT / "config" / "provider_profiles.yaml")]
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return p


def test_component_registry_loads_and_extends_provider_registry():
    from engine.registry import Registry

    reg = Registry([COMP_CONFIG])
    fam = {pid: p["family"] for pid, p in reg.profiles.items() if "family" in p}
    assert sorted(fam) == [
        "b1_victron_gx_battery_modbus",
        "b2_solaredge_storagedata",
        "m1_schneider_iem3255_modbus",
        "m2_fronius_smart_meter_solar_api",
        "m3_shelly_pro3em_rpc",
        "w1_imt_si_rs485tc",
        "w2_kipp_smp10x_modbus",
        "w3_campbell_toa5_station",
    ]
    assert (
        "b3_enphase_battery_telemetry" not in reg.profiles
    )  # excluded by the feasibility gate
    assert (
        "huawei_smartpvms_nbi_2025_07_28" in reg.profiles
    )  # reused unchanged via extends


@pytest.mark.parametrize(
    "mutate,match",
    [
        (
            lambda d: d["profiles"]["m1_schneider_iem3255_modbus"]["endpoints"][0][
                "entities"
            ][0]["fields"][0].update(python_expr="1+1"),
            "unknown key",
        ),
        (
            lambda d: d["profiles"]["m1_schneider_iem3255_modbus"]["endpoints"][0][
                "entities"
            ][0]["fields"][0].update(transform="eval"),
            "not in the supported library",
        ),
        (
            lambda d: d["profiles"]["m1_schneider_iem3255_modbus"]["endpoints"][0][
                "entities"
            ][0]["fields"][0]["register"].update(address=3060),
            "violate register - address",
        ),
        (
            lambda d: d["profiles"]["m1_schneider_iem3255_modbus"]["endpoints"][0][
                "entities"
            ][0]["fields"][0]["register"].update(word_order="middle_endian"),
            "word_order",
        ),
        (
            lambda d: d["profiles"]["w3_campbell_toa5_station"]["endpoints"][0].update(
                input_format="xml"
            ),
            "input_format",
        ),
        (
            lambda d: d["profiles"]["m1_schneider_iem3255_modbus"].update(
                shell="rm -rf /"
            ),
            "unknown key",
        ),
    ],
)
def test_registry_rejects_unknown_keys_and_transforms(tmp_path, mutate, match):
    from engine.registry import Registry, RegistryError

    doc = _load_doc()
    mutate(doc)
    with pytest.raises(RegistryError, match=match):
        Registry([_write(tmp_path, doc)])


# ------------------------------------------------------------------ evidence allowlist
def _evidence():
    return yaml.safe_load(EVIDENCE.read_text(encoding="utf-8"))["profiles"]


def test_every_mapped_native_field_exists_in_the_evidence_registry():
    ev = _evidence()
    doc = _load_doc()
    checked = 0
    for pid, prof in doc["profiles"].items():
        e = ev[prof["evidence_ref"]]
        assert (
            e["outcome"] in ("include", "narrow") and prof["outcome"] == e["outcome"]
        ), pid
        natives = {f["native"]: f for f in e["fields"]}
        for ep in prof["endpoints"]:
            for ent in ep["entities"]:
                for f in ent["fields"]:
                    if f.get("capability") == "unsupported_on_model":
                        continue  # declared unavailable; nothing is mapped
                    assert f.get("native_ref") in natives, (
                        f"{pid}:{f['id']} maps {f.get('native_ref')!r} not in evidence"
                    )
                    evf = natives[f["native_ref"]]
                    if f.get("transform") == "register_words":
                        addr = (
                            evf["address"]
                            if isinstance(evf["address"], list)
                            else [evf["address"]]
                        )
                        assert f["register"]["address"] in addr, f["id"]
                        norm = {
                            "u16": "uint16",
                            "s16": "int16",
                            "bitmap": "uint16",
                        }  # 1-word bitmap read as uint16
                        etype = str(evf["type"]).lower()
                        assert f["register"]["type"] == norm.get(etype, etype), f["id"]
                        if (
                            "register" in evf
                            and f["register"].get("number") is not None
                        ):
                            reg = (
                                evf["register"]
                                if isinstance(evf["register"], list)
                                else [evf["register"]]
                            )
                            assert f["register"]["number"] in reg, f["id"]
                    elif f.get("source", "").split(".")[-1] not in ("", None):
                        key = f["source"].split(".")[-1]
                        assert (
                            key.split("_Phase_")[0] in evf["native"]
                            or key in str(evf.get("path", ""))
                            or key in evf["native"]
                        ), f["id"]
                    checked += 1
    assert checked >= 70


def test_excluded_and_narrowed_profiles_generate_nothing_unlisted():
    ev = _evidence()
    assert ev["b3_enphase_battery_telemetry"]["outcome"] == "exclude"
    man = json.loads(
        (ROOT / "demo_components" / "manifest.json").read_text(encoding="utf-8")
    )
    assert not any(
        "enphase" in f["profile_id"] for f in man["files"] if f.get("profile_id")
    )
    assert man["delivered_source_datasets"]["count"] == 8
    assert man["excluded_profiles"][0]["profile_id"] == "b3_enphase_battery_telemetry"


def test_committed_fixtures_only_use_allowlisted_native_keys():
    """Spot-check native payload keys of the committed fixtures against the evidence allowlist."""
    root = ROOT / "demo_components"
    em = json.loads(
        (root / "meters" / "H2_shelly_pro3em_EM.GetStatus.ndjson")
        .read_text()
        .splitlines()[0]
    )
    allowed = {"id", "total_act_power", "errors"} | {
        f"{p}_{k}" for p in "abc" for k in ("act_power", "voltage", "current", "errors")
    }
    assert set(em["payload"]) <= allowed
    fr = json.loads(
        (root / "meters" / "F2_fronius_smart_meter_GetMeterRealtimeData.ndjson")
        .read_text()
        .splitlines()[0]
    )
    dev = fr["payload"]["Body"]["Data"]["0"]
    ev_paths = " ".join(
        f["native"] + " " + f.get("path", "")
        for f in _evidence()["m2_fronius_smart_meter_solar_api"]["fields"]
    )
    for k in dev:
        assert k.split("_Phase_")[0] in ev_paths, k
    assert "recorded_at_utc" not in json.dumps(
        fr["payload"]
    )  # collector metadata stays outside the payload


# ------------------------------------------------------------------ readers / guards
def test_header_csv_reader_quoting_missing_tokens_and_bounds(tmp_path):
    from engine.readers import ReaderError, header_csv_deliveries

    cfg = {
        "header_rows": 4,
        "environment_row": 1,
        "names_row": 2,
        "units_row": 3,
        "processing_row": 4,
        "expect_environment_first": "TOA5",
        "max_rows": 2,
    }
    f = tmp_path / "t.dat"
    f.write_text(
        '"TOA5","ST","CR1000X","1","OS","PROG","1","OneMin"\n"TIMESTAMP","RECORD","A","B"\n'
        '"TS","RN","W/m^2","Deg C"\n"","","Avg","Avg"\n"2026-07-16 10:01:00",5,812.4,"NAN"\n',
        encoding="utf-8",
    )
    with pytest.raises(ReaderError, match="sidecar"):
        list(header_csv_deliveries(f, cfg))
    (tmp_path / "t.dat.collector.json").write_text(
        json.dumps(
            {
                "binding": {"asset_id": "X"},
                "collections": [
                    {
                        "through_line": 99,
                        "recorded_at_utc": "2026-07-16T07:05:00Z",
                        "received_at_utc": "2026-07-16T07:05:02Z",
                    }
                ],
            }
        )
    )
    ((n, line),) = list(header_csv_deliveries(f, cfg))
    obj = json.loads(line)
    row = obj["payload"]["row"]
    assert n == 5 and row == {
        "TIMESTAMP": "2026-07-16 10:01:00",
        "RECORD": 5,
        "A": 812.4,
        "B": "NAN",
    }
    assert (
        obj["payload"]["header"]["units"]["A"] == "W/m^2"
        and obj["payload"]["header"]["processing"]["A"] == "Avg"
    )
    assert obj["collector"]["recorded_at_utc"] == "2026-07-16T07:05:00Z"
    f.write_text(
        f.read_text() + '"2026-07-16 10:02:00",6,1,2\n"2026-07-16 10:03:00",7,1,2\n',
        encoding="utf-8",
    )
    with pytest.raises(ReaderError, match="more than 2"):
        list(header_csv_deliveries(f, cfg))


def test_readers_refuse_evaluation_material(tmp_path):
    from engine.readers import eval_guard
    from engine.transport import EvaluationMaterialError

    for p in (
        ROOT / "tests" / "component_truth" / "fault_manifest.json",
        tmp_path / "component_truth" / "x.json",
        tmp_path / "fault_manifest.json",
    ):
        with pytest.raises(EvaluationMaterialError):
            eval_guard(p)


def test_runtime_never_reads_component_truth_or_expected_labels():
    files = (
        sorted((ROOT / "engine").glob("*.py"))
        + [ROOT / "scraper.py"]
        + sorted((ROOT / "backend").rglob("*.py"))
    )
    for p in files:
        text = p.read_text(encoding="utf-8")
        if p.name == "readers.py":
            text = text.replace(
                'EVALUATION_NAMES = {"component_truth", "fault_manifest.json"}', ""
            )
        assert "component_truth" not in text and "fault_manifest" not in text, p
        assert not re.search(r"expected_(handling|engine_response)", text), p
    gen = (ROOT / "generate_components.py").read_text(encoding="utf-8")
    assert (
        "import scraper" not in gen and "from engine" not in gen
    )  # fixture tool and engine stay independent


def test_provider_mode_store_schema_unchanged(tmp_path):
    from engine.storage import OBS_COLS, Store

    st = Store(tmp_path / "p.sqlite")
    cols = [r[1] for r in st.con.execute("PRAGMA table_info(observations)")]
    assert cols == ["obs_id"] + OBS_COLS
    assert not st.q(
        "SELECT name FROM sqlite_master WHERE name IN ('authority_frames','component_frames')"
    )
    st.close()
    ext = Store(tmp_path / "c.sqlite", extended=True)
    assert "exact_value_text" in [
        r[1] for r in ext.con.execute("PRAGMA table_info(observations)")
    ]
    ext.close()


def test_asset_registry_pins_base_sites_and_rejects_unknown_sites(tmp_path):
    from engine.sites import AssetRegistry

    doc = json.loads(
        (ROOT / "demo_components" / "assets.json").read_text(encoding="utf-8")
    )
    doc["base_site_registry"]["path"] = str(ROOT / "demo_data" / "sites.json")
    p = tmp_path / "assets.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    reg = AssetRegistry(p)
    site, dev = reg.lookup_asset("F1-M1-PCC")
    assert site["demo_site_key"] == "F1" and dev["boundary"] == "grid_pcc"
    assert reg.lookup_asset("F1-M1-PCX") == (None, None)  # no fuzzy matching
    assert (
        reg.device("solaredge|se-acct-demo-02|1618033", "BAT-00A1B2C3")["asset_id"]
        == "S3-B2-BAT"
    )
    bad = dict(doc, base_site_registry=dict(doc["base_site_registry"], sha256="0" * 64))
    p.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="sha256"):
        AssetRegistry(p)
    doc["assets"].append(
        dict(doc["assets"][0], asset_id="ORPHAN", site_key="fronius|nope|nope")
    )
    doc["base_site_registry"] = bad["base_site_registry"] | {"sha256": None}
    p.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown site"):
        AssetRegistry(p)
