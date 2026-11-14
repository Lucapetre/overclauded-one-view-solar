"""Session fixtures: one fresh SYNTHETIC generation + full ingestion in a temp dir, shared by outcome tests.

Hidden ground truth and the injection manifest are written to a separate temp folder and only the TESTS read
them; the engine never receives their path.
"""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONFIG = ROOT / "config" / "provider_profiles.yaml"
AS_OF = "2026-07-22T00:00:00+03:00"


@pytest.fixture(scope="session")
def gen(tmp_path_factory):
    import generate_demo

    base = tmp_path_factory.mktemp("gen")
    generate_demo.main(["--seed", "42", "--sites-per-provider", "3", "--start", "2026-07-15", "--days", "7",
                        "--out", str(base / "demo_data"), "--truth-out", str(base / "truth")])
    return base


@pytest.fixture(scope="session")
def build(gen):
    import scraper

    out = gen / "build"
    scraper.main(["--config", str(CONFIG), "--input", str(gen / "demo_data"), "--out", str(out), "--as-of", AS_OF])
    return out


@pytest.fixture(scope="session")
def db(build):
    con = sqlite3.connect(str(build / "scraper.sqlite"))
    yield con
    con.close()


@pytest.fixture(scope="session")
def truth(gen):
    t = gen / "truth"
    return {"daily": json.loads((t / "ground_truth" / "daily_totals.json").read_text())["sites"],
            "injections": json.loads((t / "injection_manifest.json").read_text())["injections"]}


@pytest.fixture(scope="session")
def site_keys(gen):
    doc = json.loads((gen / "demo_data" / "sites.json").read_text())
    return {s["demo_site_key"]: f"{s['provider']}|{s['account_id']}|{s['site_id']}" for s in doc["sites"]}


# ------------------------------------------------------------------ crafted payloads through the real engine
PROFILE = {"huawei": "huawei_smartpvms_nbi_2025_07_28", "fronius": "fronius_solar_api_v1_rev021",
           "solaredge": "solaredge_monitoring_api_2026_03"}
BIND = {"H1": ("huawei", "hw-nbi-demo-01", "NE=33554791"), "H3": ("huawei", "hw-nbi-demo-02", "NE=33554850"),
        "F1": ("fronius", "fr-lan-gw-0001", "FR-SITE-0001"), "F2": ("fronius", "fr-lan-gw-0002", "FR-SITE-0002"),
        "F3": ("fronius", "fr-lan-gw-0003", "FR-SITE-0003"), "S1": ("solaredge", "se-acct-demo-01", "2718281"),
        "S2": ("solaredge", "se-acct-demo-01", "3141592"), "S3": ("solaredge", "se-acct-demo-02", "1618033")}


def envelope(site, endpoint, payload=None, scope=None, recorded="2026-07-16T09:00:01.500Z",
             received="2026-07-16T09:00:03.000Z", http=200, payload_text=None, delivery_id="T-1"):
    prov, acc, sid = BIND[site]
    env = {"transport_schema": "demo-mock-transport/1", "synthetic": True, "delivery_id": delivery_id,
           "provider_profile_id": PROFILE[prov], "endpoint_key": endpoint,
           "binding": {"account_id": acc, "site_id": sid}, "request_scope": scope or {},
           "recorded_at_utc": recorded, "received_at_utc": received, "http_status": http, "transport_error": None}
    obj = {"mock_transport": env}
    if payload is not None:
        obj["payload"] = payload
    if payload_text is not None:
        obj["payload_text"] = payload_text
    return json.dumps(obj, separators=(",", ":"))


@pytest.fixture
def mini(gen, tmp_path):
    """mini(lines, config_paths=None, sites_doc=None) -> sqlite3 connection of a fresh ingestion."""
    import scraper

    def run(lines, config_paths=None, sites_doc=None, as_of=AS_OF):
        inp = tmp_path / "input"
        (inp / "t").mkdir(parents=True, exist_ok=True)
        if sites_doc is None:
            (inp / "sites.json").write_text((gen / "demo_data" / "sites.json").read_text())
        else:
            (inp / "sites.json").write_text(json.dumps(sites_doc))
        f = inp / "t" / "case.ndjson"
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        sha = hashlib.sha256(f.read_bytes()).hexdigest()
        (inp / "t" / "manifest.json").write_text(json.dumps({"files": [{"dataset": "t", "path": "case.ndjson",
                                                                         "sha256": sha}]}))
        (inp / "manifest.json").write_text(json.dumps({"files": [{"path": "t/manifest.json"}]}))
        _, _, store, _ = scraper.ingest(config_paths or [CONFIG], inp, tmp_path / "mini.sqlite", as_of, ["t"],
                                        log=lambda m: None)
        store.commit()
        return store.con

    return run


def obs(con, metric=None, where="", args=()):
    sql = ("SELECT o.metric_name, o.canonical_value, o.availability_status, o.quality_flags, o.original_value, "
           "o.boundary, o.canonical_text, r.status FROM observations o JOIN raw_records r USING(raw_record_id) WHERE 1=1")
    a = []
    if metric:
        sql += " AND o.metric_name=?"
        a.append(metric)
    return [dict(zip(["metric", "value", "avail", "flags", "orig", "boundary", "text", "rstatus"], r))
            for r in con.execute(sql + " " + where, tuple(a) + tuple(args)).fetchall()]
