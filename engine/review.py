"""Review candidates for physical operating conditions (demo policies from config/review_policies.yaml).

Candidates point at preserved evidence for a human / virtual technician. They never modify, hide or clean values,
never claim a root cause and never send anything to a device.
"""
from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict

from .timeparse import local_date, local_day_bounds_ms, ms_to_iso

_CMP = {"gt": lambda a, b: a > b, "gte": lambda a, b: a >= b, "lt": lambda a, b: a < b, "lte": lambda a, b: a <= b}


def _cid(*parts):
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:16]


def evaluate(store, reg, sites):
    pol = reg.review_policies or {}
    con = store.con
    con.execute("DELETE FROM review_candidates")
    disclaimer = (pol.get("disclaimer") or "").strip()
    n = 0
    for p in pol.get("policies", []):
        if p["kind"] == "threshold_sustained":
            n += _threshold(store, p, disclaimer)
        elif p["kind"] == "peer_specific_yield":
            n += _peer(store, p, disclaimer, sites)
    store.commit()
    return n


def _threshold(store, p, disclaimer):
    cmp = _CMP[p["op"]]
    rows = store.q("SELECT obs_id, site_key, endpoint_key, COALESCE(device_key,''), COALESCE(channel,''), "
                   "effective_time_ms, canonical_value FROM observations WHERE metric_name=? AND "
                   "availability_status='available' AND is_conflicted=0 ORDER BY 2,3,4,5,6", (p["metric"],))
    series = defaultdict(list)
    for r in rows:
        series[r[1:5]].append((r[0], r[5], r[6]))
    gap = float(p.get("max_sample_gap_s", 1200)) * 1000
    n = 0
    for (sk, ek, dk, ch), pts in series.items():
        run = []

        def close(run):
            nonlocal n
            if len(run) >= 2 and (run[-1][1] - run[0][1]) / 1000.0 >= float(p["min_duration_s"]):
                peak = max(run, key=lambda x: x[2])
                ev = {"first_obs_id": run[0][0], "last_obs_id": run[-1][0], "peak_obs_id": peak[0],
                      "sample_obs_ids": [x[0] for x in run[:: max(1, len(run) // 8)]]}
                store.con.execute("INSERT OR REPLACE INTO review_candidates VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    _cid(p["policy_id"], sk, ek, dk, ch, run[0][1]), p["policy_id"], p["version"], sk, ek, dk, ch,
                    p["metric"], run[0][1], run[-1][1], (run[-1][1] - run[0][1]) / 1000.0, peak[2], len(run),
                    json.dumps(ev), "open_for_review", p["label"], disclaimer))
                n += 1

        for oid, t, v in pts:
            if v is not None and cmp(v, p["threshold"]) and (not run or t - run[-1][1] <= gap):
                run.append((oid, t, v))
            else:
                close(run)
                run = [(oid, t, v)] if (v is not None and cmp(v, p["threshold"])) else []
        close(run)
    return n


def _peer(store, p, disclaimer, sites):
    rows = store.q("SELECT site_key, endpoint_key, rule_id, priority, start_ms, end_ms, duration_s, energy_kwh FROM "
                   "interval_energy WHERE metric_name=? AND allocatable=1 AND energy_kwh IS NOT NULL",
                   (p["interval_metric"],))
    best = {}
    for sk, ek, rid, pr, *_ in rows:
        if sk not in best or pr < best[sk][1]:
            best[sk] = ((ek, rid), pr)
    daily = defaultdict(lambda: [0.0, 0.0])  # (site, local date) -> [kWh, covered seconds]
    for sk, ek, rid, pr, s, e, dur, kwh in rows:
        if best.get(sk, (None,))[0] != (ek, rid):
            continue
        tz = (sites.sites.get(sk) or {}).get("timezone", "UTC")
        dte = local_date(s, tz)
        daily[(sk, dte)][0] += kwh
        daily[(sk, dte)][1] += dur
    by_date = defaultdict(dict)
    for (sk, dte), (kwh, cov) in daily.items():
        site = sites.sites.get(sk) or {}
        a, b = local_day_bounds_ms(dte, site.get("timezone", "UTC"))
        coverage = cov / ((b - a) / 1000.0)
        cap = site.get(p["capacity_ref"].split(".", 1)[1])
        if coverage >= float(p["min_daily_coverage"]) and cap:
            by_date[dte][sk] = (kwh / cap, kwh, coverage)
    flagged = defaultdict(list)
    for dte, vals in sorted(by_date.items()):
        if len(vals) < int(p["min_peers"]):
            continue
        med = statistics.median(v[0] for v in vals.values())
        for sk, (spec, kwh, cov) in vals.items():
            if med > 0 and spec / med < float(p["ratio_below"]):
                flagged[sk].append((dte, spec, med, kwh, cov))
    n = 0
    for sk, days in flagged.items():
        runs, cur = [], []
        for d in days:
            if cur and (d[0] - cur[-1][0]).days != 1:
                runs.append(cur)
                cur = []
            cur.append(d)
        runs.append(cur)
        for r in runs:
            if len(r) >= int(p["min_consecutive_days"]):
                tz = (sites.sites.get(sk) or {}).get("timezone", "UTC")
                a = local_day_bounds_ms(r[0][0], tz)[0]
                b = local_day_bounds_ms(r[-1][0], tz)[1]
                ev = [{"local_date": str(d), "specific_yield_kwh_per_kwp": round(s, 3),
                       "peer_median_kwh_per_kwp": round(m, 3), "ratio": round(s / m, 3), "day_kwh": round(k, 3),
                       "coverage": round(c, 3)} for d, s, m, k, c in r]
                store.con.execute("INSERT OR REPLACE INTO review_candidates VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    _cid(p["policy_id"], sk, a), p["policy_id"], p["version"], sk, best[sk][0][0], "", "",
                    p["interval_metric"], a, b, (b - a) / 1000.0, min(e["ratio"] for e in ev), len(r),
                    json.dumps(ev), "open_for_review", " ".join(p["label"].split()), disclaimer))
                n += 1
    return n
