"""Source health against the REPLAY clock, and historical gap detection.

Latest-source freshness (is the feed current at --as-of?) is reported separately from historical validity (were
old rows complete / late?). Historical rows are never marked stale merely because they are old.
"""
from __future__ import annotations

import json
from collections import defaultdict

from .storage import ACTION_COLS, ISSUE_COLS
from .timeparse import ms_to_iso


def compute(store, reg, sites, run_id, as_of_ms):
    con = store.con
    con.execute("DELETE FROM source_health")
    con.execute("DELETE FROM data_gaps")
    con.execute("DELETE FROM audit_actions WHERE stage='health'")
    con.execute("DELETE FROM quality_issues WHERE stage='health'")
    grace = float(reg.default("freshness_grace_factor", 3.0))
    gap_factor = float(reg.default("gap_factor", 2.5))
    late_s = float(reg.default("late_arrival_s", 3600))
    events = defaultdict(list)
    for dh, sk, ek, cls, http, code, info, s, e, et, detail in store.q(
            "SELECT delivery_hash, site_key, endpoint_key, status_class, http_status, code, informational, start_ms, "
            "end_ms, event_time_ms, detail FROM delivery_events"):
        events[(sk, ek)].append(dict(cls=cls, http=http, code=code, info=info, start=s, end=e, t=et, detail=detail))
    stale_times = defaultdict(list)
    for sk, ek, dk, t in store.q("SELECT site_key, endpoint_key, COALESCE(device_key,''), effective_time_ms FROM "
                                 "raw_records WHERE status='exact_duplicate' AND record_flags LIKE '%stale_response%'"):
        stale_times[(sk, ek)].append(t)
    groups = store.q(
        "SELECT site_key, endpoint_key, COALESCE(device_key,''), provider, provider_profile_id, variant, COUNT(*), "
        "MIN(effective_time_ms), MAX(effective_time_ms), MAX(received_at_ms), "
        "SUM(CASE WHEN arrival_lag_s > ? THEN 1 ELSE 0 END) FROM raw_records "
        "WHERE status IN ('accepted','conflict_version') GROUP BY 1,2,3", (late_s,))
    seen = set()
    for sk, ek, dk, prov, pid, var, n, tmin, tmax, rmax, late in groups:
        seen.add((sk, ek))
        ep = reg.endpoint(pid, ek, var) or {}
        cad = int(ep.get("cadence_s", 300))
        thr = cad * grace + float(ep.get("expected_delay_s", 0))
        ev = events.get((sk, ek), [])
        # documented-unavailable responses (e.g. device asleep) are source contact, not silence
        doc_t = [e["t"] for e in ev if e["info"] and e["t"] is not None]
        latest_contact = max([tmax] + doc_t)
        age = (as_of_ms - latest_contact) / 1000.0
        continuous = ep.get("continuous_feed", True)
        if not continuous:
            fresh = "not_continuously_polled"
        elif age < 0:
            fresh = "future_relative_to_replay_clock"
        else:
            fresh = "fresh" if age <= thr else "stale"
            if fresh == "fresh" and latest_contact > tmax:
                fresh = "fresh_documented_unavailable"
        cls_counts = defaultdict(int)
        for e in ev:
            cls_counts[e["cls"]] += 1
        access = "access_denied_windows" if cls_counts.get("access_denied") else "granted"
        # ---- historical gaps
        times = [t for (t,) in store.q("SELECT DISTINCT effective_time_ms FROM raw_records WHERE site_key=? AND "
                                       "endpoint_key=? AND COALESCE(device_key,'')=? AND status IN "
                                       "('accepted','conflict_version') ORDER BY 1", (sk, ek, dk))]
        covered = sorted(set(times) | {e["t"] for e in ev if e["info"] and e["t"] is not None})
        gaps = []
        if continuous:
            lim = cad * gap_factor * 1000
            for a, b in zip(covered, covered[1:]):
                if b - a > lim:
                    gaps.append((a, b))
            if fresh == "stale":
                gaps.append((latest_contact, as_of_ms))
        for a, b in gaps:
            trailing = b == as_of_ms
            cls = "trailing_gap_feed_stale" if trailing else "data_gap"
            denied = [e for e in ev if e["cls"] == "access_denied" and e["start"] is not None
                      and e["start"] < b and e["end"] > a]
            failed = [e for e in ev if not e["info"] and e["cls"] not in ("access_denied",)
                      and (e["start"] or e["t"] or 0) < b and (e["end"] or e["t"] or 0) >= a]
            stale = [t for t in stale_times.get((sk, ek), []) if a <= t <= b]
            if denied:
                cls = "access_denied"
            elif any(a <= t < b for t in stale_times.get((sk, ek), [])) or stale:
                cls = "stale_feed_repeated_response"
            elif failed and not trailing:
                cls = "provider_or_transport_failure"
            detail = f"no accepted records between {ms_to_iso(a)} and {ms_to_iso(b)}"
            con.execute("INSERT INTO data_gaps VALUES(?,?,?,?,?,?,?,?)", (sk, ek, dk, a, b, (b - a) / 1000.0, cls,
                                                                           detail))
            iid = store.insert_one("quality_issues", ISSUE_COLS, [
                run_id, "health", "data_gap" if cls != "access_denied" else "access", f"gap_{cls}",
                "warning", prov, sk, ek, dk, None, None, None, None, None, a, "freshness",
                reg.rule_version("freshness"), ep.get("mapping_version"), None,
                "unresolved: values in the gap stay unknown (no interpolation, no zeros)", detail, None])
            store.insert_one("audit_actions", ACTION_COLS, [
                run_id, "health", "record_gap", "unresolved", iid, None, None, prov, sk, ek, None, "freshness",
                reg.rule_version("freshness"), ep.get("mapping_version"), None, cls, detail, None])
        notes = []
        if ep.get("realtime"):
            notes.append("realtime endpoint: response/capture time is the time anchor, not a sensor time"
                         if not any(t.get("is_measurement") for t in ep.get("records", {}).get("times", [])) else "")
        con.execute("INSERT INTO source_health VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            sk, ek, dk, prov, var, n, tmin, tmax, rmax, cad, as_of_ms, age, thr, fresh, late, len(gaps),
            json.dumps(dict(cls_counts), sort_keys=True), access, "; ".join(x for x in notes if x) or None))
    # endpoints that only ever produced events (e.g. unsupported / denied for the whole period)
    for (sk, ek), ev in events.items():
        if (sk, ek) in seen:
            continue
        site = sites.sites.get(sk) or {}
        cls_counts = defaultdict(int)
        for e in ev:
            cls_counts[e["cls"]] += 1
        state = "capability_unsupported" if cls_counts.get("unsupported") else (
            "access_denied" if cls_counts.get("access_denied") else "no_accepted_records")
        con.execute("INSERT INTO source_health VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            sk, ek, "", site.get("provider"), None, 0, None, None, None, None, as_of_ms, None, None, state, 0, 0,
            json.dumps(dict(cls_counts), sort_keys=True), state, "no accepted records; see events"))
    store.commit()
