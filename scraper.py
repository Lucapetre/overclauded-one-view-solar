#!/usr/bin/env python3
"""ONE shared scraper / ingestion entry point for every registered provider profile.

    python scraper.py --config config/provider_profiles.yaml --input demo_data --out build \
        --as-of 2026-07-22T00:00:00+03:00

Reads manifest-listed native payloads (or, with --http, a loopback mock server), routes each delivery through the
same fetch/read -> extract -> map -> validate -> persist -> report functions, and writes SQLite + CSV/JSON +
an HTML report. Provider differences live only in the YAML registry. Read-only: no device commands exist.
All demo inputs are SYNTHETIC.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time as _time
from datetime import datetime, timezone
from pathlib import Path

from engine import ENGINE_VERSION
from engine import derive, health, report, review
from engine.pipeline import Ingestor
from engine.registry import Registry
from engine.sites import SiteRegistry
from engine.storage import Store
from engine.timeparse import parse_time, to_ms
from engine.transport import HttpReplayTransport, discover, guard, sha256_file

ROOT = Path(__file__).resolve().parent


def engine_hash() -> str:
    h = hashlib.sha256()
    for p in sorted((ROOT / "engine").glob("*.py")) + [ROOT / "scraper.py"]:
        h.update(p.read_bytes())
    return h.hexdigest()


def ingest(config_paths, input_root: Path, db_path: Path, as_of: str, datasets, http_url=None, log=print,
           http_timeout_s: float = 5.0):
    reg = Registry(config_paths)
    sites = SiteRegistry(guard(input_root / "sites.json"))
    res = parse_time(as_of, "iso_offset")
    if res.status != "ok":
        raise SystemExit(f"--as-of must be an ISO time with an explicit offset: {res.detail}")
    as_of_ms = to_ms(res.utc)
    store = Store(db_path)
    started = datetime.now(timezone.utc)
    run_id = started.strftime("%Y%m%dT%H%M%S%fZ") + "-" + hashlib.sha256(str(_time.time_ns()).encode()).hexdigest()[:6]
    ing = Ingestor(reg, sites, store, run_id, as_of_ms)
    files = 0
    if http_url:
        tr = HttpReplayTransport(http_url, timeout_s=http_timeout_s)
        for i, (src, line) in enumerate(tr.lines(), 1):
            ing.process_line(line, f"http:{src}", i, "http_replay")
        ing.stats["http_retry_attempts"] = len(tr.log)
        ing.retry_log = tr.log
    else:
        for path, rel, ds, sha_m in discover(input_root, set(datasets)):
            actual = sha256_file(path)
            ok = sha_m is None or sha_m == actual
            lines = sum(1 for _ in open(path, "rb"))
            store.con.execute("INSERT INTO input_files VALUES(?,?,?,?,?,?,?)", (run_id, rel, ds, sha_m, actual, int(ok),
                                                                                 lines))
            if not ok:
                ing.issue("ingest", "quarantined", "manifest_checksum_mismatch", "error",
                          {"source_path": rel}, original=f"manifest {sha_m}", output="file skipped",
                          reason=f"sha256 {actual} differs from manifest; evidence integrity cannot be confirmed")
                continue
            files += 1
            ing.process_file(path, rel, ds)
    ing.finalize()
    n_series = derive.recompute(store, reg, sites, run_id, ing.affected)
    health.compute(store, reg, sites, run_id, as_of_ms)
    n_cand = review.evaluate(store, reg, sites)
    st = ing.stats
    store.con.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        run_id, started.isoformat(), datetime.now(timezone.utc).isoformat(), res.utc.isoformat(),
        "http_replay" if http_url else "file_replay", ",".join(datasets), str(input_root), reg.config_hash,
        engine_hash(), reg.registry_version, st["deliveries_seen"], st["deliveries_new"],
        st["deliveries_skipped_known"], st["observations_added"], "completed",
        json.dumps({k: v for k, v in st.items() if not k.startswith("avail:")}, sort_keys=True)))
    store.commit()
    log(f"[scraper] run {run_id}: files={files} deliveries seen={st['deliveries_seen']} new={st['deliveries_new']} "
        f"skipped(already ingested)={st['deliveries_skipped_known']} records={st['records_input']} "
        f"observations added={st['observations_added']} derived series recomputed={n_series} "
        f"review candidates={n_cand}")
    return reg, sites, store, as_of_ms


def side_summary(store, dataset):
    if dataset == "golden_equivalence":
        return report._rows(store, "SELECT provider, profile_variant AS variant, field_rule_id, original_value, "
                                   "original_unit, metric_name, canonical_value, canonical_unit, boundary, "
                                   "effective_time_utc FROM canonical_observations WHERE metric_name IN "
                                   "('inverter_ac_output_kw','pv_ac_kw','pv_dc_kw') ORDER BY metric_name, provider")
    rows = report._rows(store, "SELECT provider, endpoint_key, site_key, source_time_raw, source_time_role, status, "
                               "status_reason, effective_time_ms FROM raw_records ORDER BY provider, source_time_raw")
    for r in rows:
        r["effective_time_utc"] = report.ms_to_iso(r.pop("effective_time_ms"))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", action="append", required=True,
                    help="registry YAML (repeatable; later files may add profiles)")
    ap.add_argument("--input", required=True, help="input root with manifest.json and sites.json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--as-of", required=True, help="replay clock, ISO with offset")
    ap.add_argument("--dataset", default="delivery", help="comma-separated manifest datasets to ingest")
    ap.add_argument("--side-datasets", default="golden_equivalence,dst_edge_cases",
                    help="datasets ingested into separate side databases for the report ('' to skip)")
    ap.add_argument("--db", default=None, help="SQLite path (default <out>/scraper.sqlite)")
    ap.add_argument("--http", default=None, help="loopback mock server base URL (optional HTTP replay mode)")
    ap.add_argument("--no-report", action="store_true")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    input_root = Path(args.input)
    datasets = [d for d in args.dataset.split(",") if d]
    db = Path(args.db) if args.db else out / "scraper.sqlite"
    t0 = _time.time()
    reg, sites, store, as_of_ms = ingest(args.config, input_root, db, args.as_of, datasets, args.http)
    side = {}
    for ds in [d for d in args.side_datasets.split(",") if d]:
        if not any(True for _ in discover(input_root, {ds})):
            continue
        sp = out / "side" / f"{ds}.sqlite"
        _, _, sstore, _ = ingest(args.config, input_root, sp, args.as_of, [ds], log=lambda m: print("  (side) " + m))
        side[ds] = side_summary(sstore, ds)
        sstore.close()
    if not args.no_report:
        frames = derive.build_frames(store, reg, sites)
        report.export_tables(store, out, frames)
        n = report.export_canonical(store, out)
        q = report.quality_report(store, reg, sites, as_of_ms, ENGINE_VERSION, side)
        (out / "quality_report.json").write_text(json.dumps(q, indent=1, default=str), encoding="utf-8")
        report.demo_report(store, reg, sites, q, side, out)
        print(f"[scraper] exported {n} canonical observations, {len(frames)} frame rows -> {out.resolve()}")
    store.close()
    print(f"[scraper] done in {_time.time() - t0:.1f} s (SYNTHETIC DEMONSTRATION)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
