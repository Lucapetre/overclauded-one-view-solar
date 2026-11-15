"""Exports (CSV/JSON), quality_report.json and the standalone HTML demo report. Everything is labelled
SYNTHETIC DEMONSTRATION; no statistic here is a real-world accuracy claim."""
from __future__ import annotations

import csv
import gzip
import html
import json
from collections import defaultdict
from pathlib import Path

from .timeparse import ms_to_iso, ms_to_local_iso

NOTICE = ("SYNTHETIC DEMONSTRATION. All payloads are generated fixtures shaped after pinned public references; "
          "they are not real vendor or customer data. Counts below describe this synthetic "
          "replay only: they are not field fault-detection accuracy and not a compliance certification.")

CANON_COLS = ["obs_id", "provider", "provider_profile_id", "provider_profile_version", "mapping_version",
              "endpoint_key", "profile_variant", "account_id", "site_id", "site_key", "device_id", "device_key",
              "entity_scope", "channel", "raw_record_id", "payload_hash", "source_path", "source_line",
              "source_time_raw", "source_time_role", "measurement_time_utc", "response_time_utc", "capture_time_utc",
              "received_at_utc", "effective_time_utc", "effective_time_basis", "metric_name", "original_value",
              "original_unit", "canonical_value", "canonical_text", "canonical_unit", "metric_kind", "boundary",
              "value_origin", "availability_status", "quality_flags", "is_conflicted", "assumption_basis",
              "requirement_class", "transform_log", "field_rule_id", "record_status"]


def _rows(store, sql, args=()):
    cur = store.con.execute(sql, args)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


REC_PART = ["provider", "provider_profile_id", "profile_version", "mapping_version", "endpoint_key", "variant",
            "account_id", "site_id", "payload_hash", "source_path", "source_line", "source_time_raw",
            "source_time_role", "measurement_time_ms", "response_time_ms", "capture_time_ms", "received_at_ms",
            "effective_time_basis", "status"]
OBS_PART = ["obs_id", "raw_record_id", "site_key", "device_id", "device_key", "entity_scope", "channel",
            "effective_time_ms", "metric_name", "original_value", "original_unit", "canonical_value",
            "canonical_text", "canonical_unit", "metric_kind", "boundary", "value_origin", "availability_status",
            "quality_flags", "is_conflicted", "assumption_basis", "requirement_class", "transform_log",
            "field_rule_id"]


def _canonical_rows(store, where="", args=()):
    """Join observations with record provenance in Python (avoids per-row SQL time formatting)."""
    recs = {}
    for r in store.q(f"SELECT raw_record_id, {','.join(REC_PART)} FROM raw_records "
                     f"WHERE status IN ('accepted','conflict_version')"):
        d = dict(zip(REC_PART, r[1:]))
        for k in ("measurement_time_ms", "response_time_ms", "capture_time_ms", "received_at_ms"):
            d[k] = ms_to_iso(d[k])
        recs[r[0]] = d
    cur = store.con.execute(f"SELECT {','.join(OBS_PART)} FROM observations {where} ORDER BY obs_id", args)
    while True:
        chunk = cur.fetchmany(20000)
        if not chunk:
            return
        for row in chunk:
            o = dict(zip(OBS_PART, row))
            r = recs.get(o["raw_record_id"], {})
            yield [o["obs_id"], r.get("provider"), r.get("provider_profile_id"), r.get("profile_version"),
                   r.get("mapping_version"), r.get("endpoint_key"), r.get("variant"), r.get("account_id"),
                   r.get("site_id"), o["site_key"], o["device_id"], o["device_key"], o["entity_scope"], o["channel"],
                   o["raw_record_id"], r.get("payload_hash"), r.get("source_path"), r.get("source_line"),
                   r.get("source_time_raw"), r.get("source_time_role"), r.get("measurement_time_ms"),
                   r.get("response_time_ms"), r.get("capture_time_ms"), r.get("received_at_ms"),
                   ms_to_iso(o["effective_time_ms"]), r.get("effective_time_basis"), o["metric_name"],
                   o["original_value"], o["original_unit"], o["canonical_value"], o["canonical_text"],
                   o["canonical_unit"], o["metric_kind"], o["boundary"], o["value_origin"],
                   o["availability_status"], o["quality_flags"], o["is_conflicted"], o["assumption_basis"],
                   o["requirement_class"], o["transform_log"], o["field_rule_id"], r.get("status")]


def export_canonical(store, out: Path, sample_hours=1):
    n = 0
    with gzip.open(out / "canonical_measurements.csv.gz", "wt", newline="", encoding="utf-8", compresslevel=3) as fh:
        w = csv.writer(fh)
        w.writerow(CANON_COLS)
        for row in _canonical_rows(store):
            w.writerow(row)
            n += 1
    # small inspectable sample: one hour around the median source time + every non-available / conflicted row
    med = store.q("SELECT effective_time_ms FROM observations ORDER BY effective_time_ms LIMIT 1 OFFSET "
                  "(SELECT COUNT(*)/2 FROM observations)")
    with open(out / "canonical_measurements_sample.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(CANON_COLS)
        if med:
            t0 = (med[0][0] // 3600000) * 3600000
            w.writerows(_canonical_rows(store, "WHERE effective_time_ms >= ? AND effective_time_ms < ?",
                                        (t0, t0 + sample_hours * 3600000)))
        odd = list(_canonical_rows(store, "WHERE (availability_status <> 'available' AND COALESCE(quality_flags,'') "
                                          "NOT LIKE '%vendor_permitted_null%' AND COALESCE(quality_flags,'') NOT LIKE "
                                          "'%null_value%') OR is_conflicted=1"))
        w.writerows(odd[:4000])
    return n


def _count(store, sql, args=()):
    out = defaultdict(dict)
    for r in store.q(sql, args):
        *keys, n = r
        d = out
        for k in keys[:-1]:
            d = d.setdefault(str(k), {})
        d[str(keys[-1])] = n
    return out


def quality_report(store, reg, sites, as_of_ms, engine_version, side=None):
    fields_per_endpoint = {}
    for pid, ep in reg.endpoints():
        n = sum(len(_metrics(f)) for ent in ep["entities"] for f in ent["fields"])
        fields_per_endpoint[(pid, ep["endpoint_key"], ep["variant"])] = n
    rec = {}
    for prov, in store.q("SELECT DISTINCT provider FROM raw_deliveries WHERE provider IS NOT NULL"):
        deliv = dict(store.q("SELECT status, COUNT(*) FROM raw_deliveries WHERE provider=? GROUP BY 1", (prov,)))
        rstat = dict(store.q("SELECT status, COUNT(*) FROM raw_records WHERE provider=? GROUP BY 1", (prov,)))
        tclass = dict(store.q("SELECT status_class, COUNT(*) FROM raw_deliveries WHERE provider=? AND "
                              "status='transport_error' GROUP BY 1", (prov,)))
        fclass = dict(store.q("SELECT status_class, COUNT(*) FROM raw_deliveries WHERE provider=? AND "
                              "status='provider_failure' GROUP BY 1", (prov,)))
        rec[prov] = {"deliveries_total": sum(deliv.values()), "deliveries_by_status": deliv,
                     "records_input": sum(rstat.values()), "records_accepted": rstat.get("accepted", 0),
                     "records_retained": rstat.get("accepted", 0) + rstat.get("conflict_version", 0),
                     "records_exact_duplicate": rstat.get("exact_duplicate", 0),
                     "records_conflict_version": rstat.get("conflict_version", 0),
                     "records_quarantined": rstat.get("quarantined", 0),
                     "transport_errors_by_class": tclass, "provider_failure_envelopes_by_class": fclass}
    unparsed = store.q("SELECT COUNT(*) FROM raw_deliveries WHERE provider IS NULL")[0][0]
    # metric level
    metric = {}
    agg = defaultdict(lambda: {"av": defaultdict(int), "permitted": 0, "conflicted": 0})
    site_prov = {sk: s.get("provider") for sk, s in sites.sites.items()}
    for sk, a, permitted, conflicted, n in store.q(
            "SELECT site_key, availability_status, COALESCE(quality_flags,'') LIKE '%vendor_permitted_null%', "
            "is_conflicted, COUNT(*) FROM observations GROUP BY 1,2,3,4"):
        g = agg[site_prov.get(sk)]
        g["av"][a] += n
        g["permitted"] += n if permitted else 0
        g["conflicted"] += n if conflicted else 0
    for prov, in store.q("SELECT DISTINCT provider FROM raw_records"):
        av, permitted, conflicted = dict(agg[prov]["av"]), agg[prov]["permitted"], agg[prov]["conflicted"]
        slots = 0
        for pid, ek, var, n in store.q("SELECT provider_profile_id, endpoint_key, variant, COUNT(*) FROM raw_records "
                                        "WHERE provider=? AND status='quarantined' GROUP BY 1,2,3", (prov,)):
            slots += n * fields_per_endpoint.get((pid, ek, var), 0)
        total = sum(av.values())
        denom = total + slots
        metric[prov] = {"observations_total": total, "by_availability": av,
                        "of_which_vendor_permitted_null": permitted, "conflicted_observations": conflicted,
                        "quarantined_record_metric_slots_estimate": slots,
                        "denominator": denom,
                        "available_unconflicted_share": round((av.get("available", 0) - conflicted) / denom, 4)
                        if denom else None}
    by_metric = _count(store, "SELECT metric_name, availability_status, COUNT(*) FROM observations GROUP BY 1,2")
    by_site_metric = _count(store, "SELECT site_key, metric_name, availability_status, COUNT(*) FROM observations "
                                   "GROUP BY 1,2,3")
    by_endpoint = _count(store, "SELECT endpoint_key, status, COUNT(*) FROM raw_records GROUP BY 1,2")
    by_site_records = _count(store, "SELECT site_key, status, COUNT(*) FROM raw_records GROUP BY 1,2")
    issues_code = dict(store.q("SELECT issue_code, COUNT(*) FROM quality_issues GROUP BY 1 ORDER BY 2 DESC"))
    issues_cat = dict(store.q("SELECT category, COUNT(*) FROM quality_issues GROUP BY 1"))
    issues_prov = _count(store, "SELECT COALESCE(provider,'(unparsed)'), issue_code, COUNT(*) FROM quality_issues "
                                "GROUP BY 1,2")
    issues_site = _count(store, "SELECT COALESCE(site_key,'(unbound)'), issue_code, COUNT(*) FROM quality_issues "
                                "GROUP BY 1,2")
    issues_metric = _count(store, "SELECT COALESCE(metric_name,'(record-level)'), issue_code, COUNT(*) FROM "
                                  "quality_issues GROUP BY 1,2")
    routine = _rows(store, "SELECT provider, endpoint_key, transform, detail, SUM(n) n FROM routine_transform_counts "
                           "GROUP BY 1,2,3,4 ORDER BY 1,2,3,4")
    det = dict(store.q("SELECT action, COUNT(*) FROM audit_actions WHERE category='deterministic_transformation' "
                       "GROUP BY 1"))
    ivs = _count(store, "SELECT metric_name, status, COUNT(*) FROM interval_energy GROUP BY 1,2")
    discont = _rows(store, "SELECT site_key, endpoint_key, metric_name, status, start_ms, end_ms, formula FROM "
                           "interval_energy WHERE status IN ('unknown_counter_reset','implausible_counter_jump',"
                           "'daily_segment_start_unverified') ORDER BY start_ms")
    for d in discont:
        d["start_utc"], d["end_utc"] = ms_to_iso(d.pop("start_ms")), ms_to_iso(d.pop("end_ms"))
    midnight = store.q("SELECT COUNT(*) FROM interval_energy WHERE status='daily_segment_start'")[0][0]
    gaps = _rows(store, "SELECT site_key, endpoint_key, device_key, start_ms, end_ms, duration_s, gap_class FROM "
                        "data_gaps ORDER BY site_key, start_ms")
    for g in gaps:
        g["start_utc"], g["end_utc"] = ms_to_iso(g.pop("start_ms")), ms_to_iso(g.pop("end_ms"))
    access = _rows(store, "SELECT site_key, endpoint_key, status_class, http_status, COUNT(*) n, MIN(start_ms) s, "
                          "MAX(end_ms) e, MIN(detail) detail FROM delivery_events WHERE informational=0 GROUP BY 1,2,3,4")
    for a in access:
        a["first_window_start_utc"], a["last_window_end_utc"] = ms_to_iso(a.pop("s")), ms_to_iso(a.pop("e"))
    health = _rows(store, "SELECT * FROM source_health ORDER BY site_key, endpoint_key")
    for h in health:
        for k in ("first_source_ms", "latest_source_ms", "latest_received_ms", "as_of_ms"):
            h[k.replace("_ms", "_utc")] = ms_to_iso(h.pop(k))
        h["events"] = json.loads(h.pop("events_json") or "{}")
    caps = _rows(store, "SELECT site_key, endpoint_key, metric_name, channel, state, reason, SUM(n_records) n_records "
                        "FROM capability_states GROUP BY 1,2,3,4,5,6 ORDER BY 1,2,3")
    observed = _rows(store, "SELECT site_key, metric_name, COUNT(*) n_obs, SUM(availability_status='available') "
                            "n_available FROM observations GROUP BY 1,2 ORDER BY 1,2")
    cands = _rows(store, "SELECT * FROM review_candidates ORDER BY policy_id, site_key, start_ms")
    for c in cands:
        c["start_utc"], c["end_utc"] = ms_to_iso(c.pop("start_ms")), ms_to_iso(c.pop("end_ms"))
        c["evidence"] = json.loads(c["evidence"])
    runs = _rows(store, "SELECT * FROM runs ORDER BY started_at_utc")
    return {
        "synthetic_demonstration": True,
        "notice": NOTICE,
        "as_of_utc": ms_to_iso(as_of_ms),
        "registry_version": reg.registry_version,
        "config_hash": reg.config_hash,
        "engine_version": engine_version,
        "runs": runs,
        "record_level": {
            "denominator_note": ("Record-level counts use extracted records as the denominator. Deliveries that could "
                                 "not be parsed contribute an UNKNOWN number of records and are counted separately."),
            "unparseable_or_unbound_deliveries": unparsed,
            "by_provider": rec, "by_site": by_site_records, "by_endpoint": by_endpoint},
        "metric_level": {
            "denominator_note": ("Metric-level denominator = all emitted observation slots (available, missing, "
                                 "invalid, stale, access-denied) PLUS an estimate of metric slots lost in quarantined "
                                 "records. Unknown data never leaves the denominator. not_installed / unsupported "
                                 "capability states are reported under capability_coverage, not as data loss."),
            "by_provider": metric, "by_metric": by_metric, "by_site_metric": by_site_metric},
        "issues": {"by_code": issues_code, "by_category": issues_cat, "by_provider": issues_prov,
                   "by_site": issues_site, "by_metric": issues_metric,
                   "category_legend": {
                       "defect_repaired": "a delivery defect neutralised deterministically (e.g. duplicate suppressed)",
                       "quarantined": "record/delivery isolated with raw evidence; nothing invented",
                       "unresolved": "value or interval left unknown/invalid on purpose (ambiguity, conflict, reset)",
                       "schema_damage": "vendor-required key absent", "schema_review": "unknown/unrouted shape",
                       "access": "access denied or authentication state", "transport": "HTTP/transport state",
                       "provider_failure": "HTTP 200 carrying a provider failure envelope",
                       "data_gap": "no accepted records for longer than the cadence policy",
                       "informational": "documented legitimate state"}},
        "deterministic_transformations": {
            "routine_normalisation_note": "Routine unit scaling / sign handling of correct data; NOT defect repair.",
            "routine_normalisation": routine,
            "format_and_metadata_normalisation": det},
        "defect_repairs": {k: v for k, v in issues_code.items() if k in ("exact_duplicate_suppressed",)},
        "unresolved": dict(store.q("SELECT issue_code, COUNT(*) FROM quality_issues WHERE category='unresolved' "
                                   "GROUP BY 1")),
        "quarantined": dict(store.q("SELECT issue_code, COUNT(*) FROM quality_issues WHERE category='quarantined' "
                                    "GROUP BY 1")),
        "invalid_fields": dict(store.q("SELECT metric_name, COUNT(*) FROM observations WHERE "
                                       "availability_status='invalid' GROUP BY 1")),
        "unresolved_conflicts": store.q("SELECT COUNT(*) FROM observations WHERE is_conflicted=1")[0][0],
        "interval_energy_by_status": ivs,
        "counter_discontinuities": discont,
        "legitimate_local_midnight_daily_resets": midnight,
        "data_gaps": gaps,
        "access_and_transport_issues": access,
        "source_health": health,
        "capability_coverage": {"declared_states": caps, "observed": observed},
        "review_candidates": cands,
        "side_datasets": side or {},
    }


def _metrics(f):
    tr = f.get("transform", "numeric")
    if tr == "sign_split":
        return [f["sign_split"]["positive"], f["sign_split"]["negative"]]
    if tr == "edge_flow":
        return [o["metric"] for o in f["outputs"]]
    return [f["metric"]]


# ------------------------------------------------------------------------------------------- HTML
CSS = """
:root{--bg:#f7f7f5;--fg:#1d1d1b;--muted:#5f5f5a;--card:#fff;--line:#deded8;--accent:#2f5d8a;--warn:#9a5b00;--bad:#a32020;--ok:#2d6a33}
@media (prefers-color-scheme: dark){:root{--bg:#161615;--fg:#ecece8;--muted:#a3a39c;--card:#20201f;--line:#3a3a37;--accent:#8fb8e6;--warn:#e0a84a;--bad:#f08a8a;--ok:#8fd19a}}
body{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;padding:0 16px 48px}
main{max-width:1100px;margin:0 auto}
.banner{background:var(--warn);color:#fff;padding:8px 14px;border-radius:6px;margin:16px 0;font-weight:600}
h1{font-size:24px;margin:24px 0 4px}h2{font-size:18px;margin:32px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
h3{font-size:15px;margin:18px 0 6px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin:10px 0;overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:12.5px}th,td{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600}pre{font:12px/1.4 ui-monospace,Consolas,monospace;white-space:pre-wrap;word-break:break-all;margin:0}
.muted{color:var(--muted)}.bad{color:var(--bad);font-weight:600}.ok{color:var(--ok);font-weight:600}.warn{color:var(--warn);font-weight:600}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}.kpi{font-size:22px;font-weight:700}
"""


def _t(rows, cols=None, max_rows=40):
    if not rows:
        return "<p class='muted'>(none)</p>"
    cols = cols or list(rows[0].keys())
    h = "".join(f"<th>{html.escape(str(c))}</th>" for c in cols)
    body = []
    for r in rows[:max_rows]:
        cells = []
        for c in cols:
            v = r.get(c)
            if isinstance(v, float):
                v = f"{v:.4g}"
            s = html.escape("" if v is None else str(v))
            if c in ("availability_status", "status", "freshness_status", "frame_status"):
                cls = "ok" if s in ("available", "valid", "fresh", "accepted", "ok") else (
                    "bad" if s in ("invalid", "stale", "access_denied", "unknown_counter_reset", "quarantined") else "warn")
                s = f"<span class='{cls}'>{s}</span>"
            cells.append(f"<td>{s}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    more = f"<p class='muted'>... {len(rows) - max_rows} more rows</p>" if len(rows) > max_rows else ""
    return f"<table><thead><tr>{h}</tr></thead><tbody>{''.join(body)}</tbody></table>{more}"


def _pre(obj):
    s = obj if isinstance(obj, str) else json.dumps(obj, indent=1, ensure_ascii=False)
    return f"<pre>{html.escape(s)}</pre>"


OBS_SHOW = ["metric_name", "channel", "original_value", "original_unit", "canonical_value", "canonical_text",
            "canonical_unit", "boundary", "availability_status", "quality_flags", "transform_log", "value_origin"]


def demo_report(store, reg, sites, quality, side_dbs, out: Path):
    S = []
    S.append(f"<div class='banner'>SYNTHETIC DEMONSTRATION &mdash; generated fixtures, not real customer data, "
             f"not vendor output, not a compliance or accuracy claim.</div>")
    S.append("<h1>Inverter ingestion demo report</h1>")
    S.append(f"<p class='muted'>Replay clock (as-of): {quality['as_of_utc']} &middot; registry "
             f"{html.escape(quality['registry_version'])} &middot; config {quality['config_hash'][:12]} &middot; "
             f"one shared engine for all profiles</p>")
    kp = []
    for prov, r in quality["record_level"]["by_provider"].items():
        m = quality["metric_level"]["by_provider"].get(prov, {})
        kp.append(f"<div class='card'><div class='muted'>{html.escape(prov)}</div><div class='kpi'>"
                  f"{r['records_retained']:,}</div><div class='muted'>records retained of {r['records_input']:,} "
                  f"input &middot; {r['records_exact_duplicate']} exact dup &middot; {r['records_quarantined']} "
                  f"quarantined<br>{m.get('observations_total', 0):,} observations, available share "
                  f"{m.get('available_unconflicted_share')}</div></div>")
    S.append("<div class='grid'>" + "".join(kp) + "</div>")

    # 1. native payload examples
    S.append("<h2>1 &middot; Three native payloads and their canonical result</h2>")
    S.append("<p>Each provider keeps its own envelope and semantics. The mock transport block (binding, "
             "capture/received times) is stored separately from the native payload.</p>")
    for prov, in store.q("SELECT DISTINCT provider FROM raw_records ORDER BY 1"):
        pick = _rows(store, "SELECT raw_record_id, site_key, endpoint_key, variant, mapping_version, record_json, "
                            "source_time_raw, source_time_role, effective_time_ms FROM raw_records WHERE provider=? "
                            "AND status='accepted' AND record_json IS NOT NULL ORDER BY "
                            "(SELECT COUNT(*) FROM observations o WHERE o.raw_record_id=raw_records.raw_record_id "
                            "AND o.availability_status='available') DESC, effective_time_ms LIMIT 1", (prov,))
        if not pick:
            continue
        p = pick[0]
        obs = _rows(store, f"SELECT {','.join(OBS_SHOW)} FROM observations WHERE raw_record_id=? ORDER BY obs_id",
                    (p["raw_record_id"],))
        rec_json = json.loads(p["record_json"])
        S.append(f"<h3>{html.escape(prov)} &middot; {html.escape(p['endpoint_key'])} ({html.escape(p['variant'])}, "
                 f"mapping {html.escape(p['mapping_version'])})</h3><div class='card'><p class='muted'>site "
                 f"{html.escape(p['site_key'])} &middot; time role <b>{html.escape(p['source_time_role'])}</b> raw "
                 f"{html.escape(str(p['source_time_raw']))}</p>{_pre(rec_json)}</div>"
                 f"<div class='card'>{_t(obs, OBS_SHOW)}</div>")

    # 2. exact duplicate
    S.append("<h2>2 &middot; Exact duplicate delivery: before / after</h2>")
    dup = _rows(store, "SELECT r.delivery_hash, r.duplicate_of, r.site_key, r.endpoint_key FROM raw_records r WHERE "
                       "r.status='exact_duplicate' AND r.record_flags NOT LIKE '%stale%' ORDER BY r.rowid LIMIT 1")
    if dup:
        dh = dup[0]["delivery_hash"]
        orig_dh = store.q("SELECT delivery_hash FROM raw_records WHERE raw_record_id=?", (dup[0]["duplicate_of"],))[0][0]
        rows = []
        for label, h in (("original delivery", orig_dh), ("re-delivery", dh)):
            d = _rows(store, "SELECT delivery_id, source_path, source_line, received_at_ms FROM raw_deliveries WHERE "
                             "delivery_hash=?", (h,))[0]
            st = dict(store.q("SELECT status, COUNT(*) FROM raw_records WHERE delivery_hash=? GROUP BY 1", (h,)))
            nobs = store.q("SELECT COUNT(*) FROM observations o JOIN raw_records r ON r.raw_record_id=o.raw_record_id "
                           "WHERE r.delivery_hash=?", (h,))[0][0]
            rows.append({"delivery": label, "delivery_id": d["delivery_id"], "line": f"{d['source_path']}:{d['source_line']}",
                         "received_at_utc": ms_to_iso(d["received_at_ms"]), "records": json.dumps(st),
                         "observations_committed": nobs})
        S.append(f"<div class='card'>{_t(rows)}<p>The re-delivery is kept as raw evidence (status "
                 f"<code>exact_duplicate</code>, pointer to the original) but adds <b>zero</b> observations.</p></div>")

    # 3. counter reset
    S.append("<h2>3 &middot; Counter handling: unexpected reset and local-midnight segments</h2>")
    rs = _rows(store, "SELECT series_key, effective_time_ms, original_value, reason FROM quality_issues WHERE "
                      "issue_code='lifetime_counter_reset' ORDER BY issue_id LIMIT 1")
    if rs:
        sk = rs[0]["series_key"]
        t = rs[0]["effective_time_ms"]
        ivs = _rows(store, "SELECT start_ms, end_ms, energy_kwh, status, allocatable, formula FROM interval_energy WHERE "
                           "series_key=? AND end_ms BETWEEN ? AND ? ORDER BY start_ms", (sk, t - 3 * 3600000, t + 2 * 3600000))
        for i in ivs:
            i["start_utc"], i["end_utc"] = ms_to_iso(i.pop("start_ms")), ms_to_iso(i.pop("end_ms"))
        S.append(f"<div class='card'><p>Series <code>{html.escape(sk)}</code>: readings "
                 f"{html.escape(rs[0]['original_value'] or '')}. {html.escape(rs[0]['reason'] or '')}</p>"
                 f"{_t(ivs, ['start_utc', 'end_utc', 'energy_kwh', 'status', 'allocatable', 'formula'], 24)}</div>")
    S.append(f"<p>Legitimate local-midnight daily-counter segment starts recognised: "
             f"<b>{quality['legitimate_local_midnight_daily_resets']}</b> (never negative intervals).</p>")

    # 4. stale / denied
    S.append("<h2>4 &middot; Stale and denied feeds (replay clock, not wall clock)</h2>")
    sh = [h for h in quality["source_health"] if h["freshness_status"] not in ("fresh",)]
    S.append(f"<div class='card'>{_t(sh, ['site_key', 'endpoint_key', 'device_key', 'freshness_status', 'latest_source_utc', 'latest_source_age_s', 'stale_threshold_s', 'access_status', 'events'])}</div>")
    S.append(f"<div class='card'><h3>Access / transport / provider-failure events</h3>"
             f"{_t(quality['access_and_transport_issues'])}</div>")
    gaps = [g for g in quality["data_gaps"]]
    S.append(f"<div class='card'><h3>Historical gaps (classified)</h3>{_t(gaps)}</div>")

    # 5. unit ambiguity
    S.append("<h2>5 &middot; Unresolved unit ambiguity (never divided by 1,000)</h2>")
    ua = _rows(store, "SELECT q.site_key, q.metric_name, q.original_value, q.output_state, q.reason, q.rule_version "
                      "FROM quality_issues q WHERE q.issue_code='implausible_magnitude_unit_ambiguity' ORDER BY "
                      "q.issue_id LIMIT 5")
    S.append(f"<div class='card'>{_t(ua)}</div>")
    amb = _rows(store, "SELECT site_key, metric_name, original_value, output_state, reason FROM quality_issues WHERE "
                       "issue_code='ambiguous_number' ORDER BY issue_id LIMIT 5")
    S.append(f"<div class='card'><h3>Ambiguous decimal locale (not guessed)</h3>{_t(amb)}</div>")

    # 6. high temperature
    S.append("<h2>6 &middot; Physical conditions retained for review (values not cleaned)</h2>")
    cands = [{k: c[k] for k in ("policy_id", "site_key", "channel", "metric_name", "start_utc", "end_utc", "duration_s",
                                "peak_value", "n_samples", "status")} for c in quality["review_candidates"]]
    S.append(f"<div class='card'>{_t(cands)}<p class='muted'>{html.escape((reg.review_policies or {}).get('disclaimer', ''))}</p></div>")
    hot = [c for c in quality["review_candidates"] if c["policy_id"] == "demo_high_inverter_temperature"]
    if hot:
        oid = hot[0]["evidence"]["peak_obs_id"]
        o = _rows(store, f"SELECT site_key, effective_time_utc, {','.join(OBS_SHOW)} FROM canonical_observations WHERE obs_id=?",
                  (oid,))
        S.append(f"<div class='card'><h3>Peak evidence observation (stored unchanged)</h3>{_t(o)}</div>")

    # 7. golden equivalence
    S.append("<h2>7 &middot; 4,200 W and 4.2 kW normalise equivalently &mdash; AC output vs DC generation kept apart</h2>")
    g = side_dbs.get("golden_equivalence")
    if g:
        S.append(f"<div class='card'>{_t(g, ['provider', 'variant', 'field_rule_id', 'original_value', 'original_unit', 'metric_name', 'canonical_value', 'canonical_unit', 'boundary'])}"
                 f"<p>Matched non-hybrid inverter AC output (same instant, same boundary) is equal after "
                 f"normalisation. The hybrid DC <code>P_PV</code> becomes <code>pv_dc_kw</code>, never "
                 f"<code>inverter_ac_output_kw</code> or <code>pv_ac_kw</code>.</p></div>")
    else:
        S.append("<p class='muted'>golden_equivalence side dataset not ingested.</p>")
    dst = side_dbs.get("dst_edge_cases")
    if dst:
        S.append("<h2>DST edge cases (Europe/Bucharest)</h2>")
        S.append(f"<div class='card'>{_t(dst)}</div>")

    S.append("<h2>Repairs vs unresolved</h2>")
    rows = [{"category": k, "issues": v, "meaning": quality["issues"]["category_legend"].get(k, "")}
            for k, v in sorted(quality["issues"]["by_category"].items())]
    S.append(f"<div class='card'>{_t(rows)}</div>")
    S.append(f"<div class='card'><h3>Issue codes</h3>{_t([{'issue_code': k, 'count': v} for k, v in quality['issues']['by_code'].items()], max_rows=80)}</div>")
    S.append(f"<div class='card'><h3>Routine normalisation (not defect repair)</h3>{_t(quality['deterministic_transformations']['routine_normalisation'], max_rows=60)}</div>")
    S.append(f"<p class='muted'>{html.escape(NOTICE)}</p>")
    doc = (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
           f"content='width=device-width,initial-scale=1'><title>Ingestion demo report</title><style>{CSS}</style>"
           f"</head><body><main>{''.join(S)}</main></body></html>")
    (out / "demo_report.html").write_text(doc, encoding="utf-8")


def export_tables(store, out: Path, frames):
    frames.to_csv(out / "site_frames_15min.csv", index=False)
    for name, sql in (("interval_energy.csv", "SELECT * FROM interval_energy ORDER BY site_key, metric_name, start_ms"),
                      ("source_health.csv", "SELECT * FROM source_health"),
                      ("data_gaps.csv", "SELECT * FROM data_gaps"),
                      ("quality_issues.csv", "SELECT * FROM quality_issues ORDER BY issue_id"),
                      ("audit_actions.csv", "SELECT * FROM audit_actions ORDER BY action_id")):
        cur = store.con.execute(sql)
        with open(out / name, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow([c[0] for c in cur.description])
            w.writerows(cur.fetchall())
    cands = _rows(store, "SELECT * FROM review_candidates ORDER BY policy_id, site_key, start_ms")
    for c in cands:
        c["start_utc"], c["end_utc"] = ms_to_iso(c["start_ms"]), ms_to_iso(c["end_ms"])
        c["evidence"] = json.loads(c["evidence"])
    (out / "review_candidates.json").write_text(json.dumps({"synthetic_demonstration": True, "candidates": cands},
                                                           indent=1), encoding="utf-8")


# ============================================================================== component snapshot exports
COMPONENT_NOTICE = ("SYNTHETIC DEMONSTRATION. Component payloads are generated fixtures shaped after pinned public "
                    "references (docs/COMPONENT_SOURCE_NOTES.md); internal/PCC operational meters are NOT certified "
                    "billing meters; nothing here is a field-accuracy or compliance claim.")


def _csv(store, out: Path, name, sql, args=(), gz=False):
    cur = store.con.execute(sql, args)
    if gz:
        fh = gzip.open(out / name, "wt", newline="", encoding="utf-8", compresslevel=3)
    else:
        fh = open(out / name, "w", newline="", encoding="utf-8")
    n = 0
    with fh:
        w = csv.writer(fh)
        w.writerow([c[0] for c in cur.description])
        while True:
            chunk = cur.fetchmany(20000)
            if not chunk:
                break
            w.writerows(chunk)
            n += len(chunk)
    return n


def mapping_notes(reg):
    notes = {"synthetic_demonstration": True, "profiles": {}}
    keys = ("id", "native_ref", "source", "register", "metric", "unit", "unit_from", "channel", "boundary",
            "aggregation", "processing_map", "mounting", "sensor_position", "sign_convention", "sign_from", "scale",
            "scale_register", "assumption_basis", "evidence_status", "capability", "reason")
    for pid, prof in sorted(reg.profiles.items()):
        if "family" not in prof:
            continue
        eps = []
        for ep in prof["endpoints"]:
            fields = [{k: f.get(k) for k in keys if f.get(k) is not None}
                      for ent in ep["entities"] for f in ent["fields"]]
            eps.append({"endpoint_key": ep["endpoint_key"], "variant": ep["variant"],
                        "input_format": ep.get("input_format", "ndjson_envelope"), "cadence_s": ep["cadence_s"],
                        "cadence_note": ep.get("cadence_note"), "mapping_version": ep["mapping_version"],
                        "fields": fields, "derive": ep.get("derive") or []})
        notes["profiles"][pid] = {"family": prof["family"], "provider": prof["provider"],
                                  "outcome": prof.get("outcome"), "profile_version": prof["profile_version"],
                                  "provenance": " ".join(str(prof.get("provenance", "")).split()),
                                  "evidence_ref": prof.get("evidence_ref"), "endpoints": eps}
    notes["excluded_profiles"] = list(reg.data.get("excluded_profiles") or [])
    return notes


def quality_summary(store, reg, sites, as_of_ms, engine_version, side):
    q = {"synthetic_demonstration": True, "notice": COMPONENT_NOTICE, "engine_version": engine_version,
         "registry_version": reg.registry_version, "scenario_version": getattr(sites, "scenario_version", None),
         "as_of_utc": ms_to_iso(as_of_ms), "sources": []}
    for pid, ek, sk, _n in store.q("SELECT provider_profile_id, endpoint_key, site_key, COUNT(*) FROM raw_deliveries "
                                   "WHERE provider_profile_id IS NOT NULL GROUP BY 1,2,3 ORDER BY 1,2,3"):
        d = dict(store.q("SELECT status, COUNT(*) FROM raw_deliveries WHERE provider_profile_id=? AND endpoint_key=? "
                         "AND site_key=? GROUP BY 1", (pid, ek, sk)))
        r_ = dict(store.q("SELECT status, COUNT(*) FROM raw_records WHERE provider_profile_id=? AND endpoint_key=? AND "
                          "site_key=? GROUP BY 1", (pid, ek, sk)))
        o = dict(store.q("SELECT availability_status, COUNT(*) FROM observations WHERE endpoint_key=? AND site_key=? "
                         "GROUP BY 1", (ek, sk)))
        iss = dict(store.q("SELECT issue_code, COUNT(*) FROM quality_issues WHERE endpoint_key=? AND site_key=? "
                           "GROUP BY 1 ORDER BY 1", (ek, sk)))
        h = store.q("SELECT freshness_status, latest_source_age_s, historical_gaps FROM source_health WHERE "
                    "endpoint_key=? AND site_key=? LIMIT 1", (ek, sk))
        q["sources"].append({"profile_id": pid, "endpoint_key": ek, "site_key": sk,
                             "site_label": (sites.sites.get(sk) or {}).get("demo_site_key") or sk,
                             "deliveries": d, "records": r_, "observations_by_availability": o, "issues": iss,
                             "freshness": h[0][0] if h else None, "historical_gaps": h[0][2] if h else None})
    q["authority"] = [dict(zip(["site_key", "metric_name", "status", "n"], r)) for r in store.q(
        "SELECT site_key, metric_name, authority_status, COUNT(*) FROM authority_frames GROUP BY 1,2,3 ORDER BY 1,2,3")]
    q["authority_conflicts"] = store.q("SELECT COUNT(*) FROM authority_conflicts")[0][0]
    q["collector_outages"] = _rows(store, "SELECT collector_id, start_utc, end_utc, affected_site_keys, failed_attempts "
                                          "FROM collector_outages ORDER BY start_ms")
    q["state_episodes"] = _rows(store, "SELECT site_key, physical_asset_id, metric_name, channel, state_value, "
                                       "state_label, start_utc, last_seen_utc, active_at_as_of FROM state_episodes "
                                       "ORDER BY start_ms")
    q["side_databases"] = side
    return q


COMPONENT_TABLE_EXPORTS = (
    ("authority_frames.csv", "SELECT * FROM authority_frames ORDER BY site_key, metric_name, frame_start_ms"),
    ("authority_conflicts.csv", "SELECT * FROM authority_conflicts ORDER BY site_key, metric_name, frame_start_ms, "
                                "other_role"),
    ("capability_registry.csv", "SELECT * FROM capability_registry ORDER BY site_key, capability"),
    ("battery_status.csv", "SELECT * FROM battery_status ORDER BY site_key, physical_asset_id"),
    ("state_episodes.csv", "SELECT * FROM state_episodes ORDER BY site_key, physical_asset_id, start_ms"),
    ("limit_history.csv", "SELECT * FROM limit_history ORDER BY site_key, physical_asset_id, metric_name, start_ms"),
    ("collector_outages.csv", "SELECT * FROM collector_outages ORDER BY collector_id, start_ms"),
    ("interval_energy.csv", "SELECT * FROM interval_energy ORDER BY site_key, endpoint_key, rule_id, start_ms"),
    ("source_health.csv", "SELECT site_key, endpoint_key, device_key, provider, variant, n_records, first_source_ms, "
                          "latest_source_ms, latest_received_ms, cadence_s, as_of_ms, latest_source_age_s, "
                          "stale_threshold_s, freshness_status, late_arrivals, historical_gaps, events_json, "
                          "access_status, notes FROM source_health ORDER BY site_key, endpoint_key, device_key"),
    ("data_gaps.csv", "SELECT * FROM data_gaps ORDER BY site_key, endpoint_key, start_ms"),
    ("quality_issues.csv", "SELECT stage, category, issue_code, severity, provider, site_key, endpoint_key, "
                           "device_key, metric_name, raw_record_id, delivery_hash, source_path, source_line, "
                           "effective_time_ms, rule_id, rule_version, mapping_version, original_value, output_state, "
                           "reason, series_key FROM quality_issues ORDER BY site_key, endpoint_key, effective_time_ms, "
                           "issue_code, raw_record_id, source_line, metric_name"),
    ("quarantine.csv", "SELECT 'delivery' AS level, delivery_hash AS ref, provider_profile_id, endpoint_key, site_key, "
                       "source_path, source_line, status, status_class AS code, status_detail AS reason FROM "
                       "raw_deliveries WHERE status <> 'parsed_ok' UNION ALL SELECT 'record', raw_record_id, "
                       "provider_profile_id, endpoint_key, site_key, source_path, source_line, status, NULL, "
                       "status_reason FROM raw_records WHERE status IN ('quarantined','exact_duplicate',"
                       "'conflict_version') ORDER BY 5, 4, 6, 7, 2"),
    ("field_rejections.csv", "SELECT obs_id, site_key, physical_asset_id, endpoint_key, metric_name, channel, "
                             "effective_time_ms, original_value, availability_status, quality_flags, field_rule_id "
                             "FROM observations WHERE availability_status IN ('invalid','withheld') ORDER BY site_key, "
                             "endpoint_key, effective_time_ms, obs_id"),
)


def export_components(store, reg, sites, out: Path, frames, as_of_ms, engine_version, side=None):
    out = Path(out)
    n = _csv(store, out, "component_observations.csv.gz",
             "SELECT * FROM component_observations ORDER BY site_key, physical_asset_id, endpoint_key, metric_name, "
             "channel, effective_time_ms, obs_id", gz=True)
    with gzip.open(out / "component_frames_15min.csv.gz", "wt", newline="", encoding="utf-8", compresslevel=3) as fh:
        frames.to_csv(fh, index=False)
    for name, sql in COMPONENT_TABLE_EXPORTS:
        _csv(store, out, name, sql)
    doc = {"synthetic_demonstration": True, "notice": COMPONENT_NOTICE,
           "asset_registry": getattr(sites, "asset_doc", {}),
           "capabilities": _rows(store, "SELECT * FROM capability_registry ORDER BY site_key, capability"),
           "battery_status": _rows(store, "SELECT * FROM battery_status ORDER BY site_key")}
    (out / "assets_capabilities.json").write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")
    (out / "mapping_notes.json").write_text(json.dumps(mapping_notes(reg), indent=1, default=str), encoding="utf-8")
    (out / "quality_summary.json").write_text(json.dumps(quality_summary(store, reg, sites, as_of_ms, engine_version,
                                                                         side or {}), indent=1, default=str),
                                              encoding="utf-8")
    return n
