"""Derived interval energy and 15-minute site frames.

Policy (recompute): when a run adds observations to a (site, endpoint) series, every derive rule of that series is
recomputed over the full series ordered by SOURCE time (not arrival), and its previous derived rows/issues are
replaced. Re-running identical input therefore never adds intervals.

Counter policy:
* lifetime counter: difference consecutive valid readings. A drop beyond resolution is an unexpected reset: the
  crossing interval's energy is UNKNOWN, the new reading becomes the baseline, differences resume afterwards.
* daily counter: a new LOCAL calendar day starts a new segment (legitimate midnight reset, never a negative
  interval). The energy since local midnight equals the first reading; the remainder before midnight is unknown.
* spacing above max_gap_s: the counter difference is a known TOTAL for the whole span but is not allocatable to
  sub-intervals (allocatable = 0).
* power integration yields ESTIMATED energy (left Riemann sum over snapshots); never billing-grade.
"""
from __future__ import annotations

import json

import pandas as pd

from .selectors import resolve_ref
from .storage import ACTION_COLS, INTERVAL_COLS, ISSUE_COLS
from .timeparse import local_date, local_day_bounds_ms, local_day_frames, ms_to_iso, ms_to_local_iso


def _iv(rule, series_key, base, start, end, energy, status, allocatable, origin, formula, deps, rv):
    return (rule["id"], series_key, base["site_key"], base["endpoint_key"], base["device_key"], base["entity_scope"],
            base["channel"], rule["to_metric"], rule["from_metric"], int(rule.get("priority", 1)), int(start),
            int(end), (end - start) / 1000.0, energy, status, allocatable, origin, formula, json.dumps(deps), rv)


def counter_intervals(rows, rule, ctx, tz, series_key, base, rv):
    out, issues = [], []
    max_gap = float(rule.get("max_gap_s", 900))
    res = float(rule.get("resolution", 0.0))
    rate = resolve_ref(ctx, rule.get("max_rate_ref"))
    factor = float(rule.get("max_rate_factor", 1.3))
    daily = rule["counter"] == "daily"
    prev = None
    for oid, t, v in rows:
        if prev is None:
            prev = (oid, t, v)
            continue
        poid, pt, pv = prev
        if t == pt:
            continue
        dt = (t - pt) / 1000.0
        if daily and local_date(t, tz) != local_date(pt, tz):
            mid = local_day_bounds_ms(local_date(t, tz), tz)[0]
            if mid > pt:
                out.append(_iv(rule, series_key, base, pt, mid, None, "unknown_pre_midnight_remainder", 0, "derived",
                               "daily counter: final reading of the previous local day unknown", [poid], rv))
            if t > mid:
                lim = rate * (t - mid) / 3.6e6 * factor + res if rate else None
                ok = v >= -res and (lim is None or v <= lim) and (t - mid) / 1000.0 <= max_gap
                out.append(_iv(rule, series_key, base, mid, t, max(v, 0.0) if ok else None,
                               "daily_segment_start" if ok else "daily_segment_start_unverified", 1 if ok else 0,
                               "derived", f"local-midnight reset: E({ms_to_iso(t)}) - 0 = {v:g}", [oid], rv))
            prev = (oid, t, v)
            continue
        d = v - pv
        if d < -res:
            out.append(_iv(rule, series_key, base, pt, t, None, "unknown_counter_reset", 0, "derived",
                           f"{v:g} - {pv:g} < 0: counter reset; crossing energy unknown", [poid, oid], rv))
            issues.append(("lifetime_counter_reset" if not daily else "unexpected_daily_counter_reset", pt, t,
                           f"{pv:g} -> {v:g}", "baseline reset to the new reading; crossing-interval energy unknown; "
                                               "valid differences resume after the new baseline"))
            prev = (oid, t, v)
            continue
        d = max(d, 0.0)
        lim = rate * dt / 3600.0 * factor + res if rate else None
        if lim is not None and d > lim:
            out.append(_iv(rule, series_key, base, pt, t, None, "implausible_counter_jump", 0, "derived",
                           f"{v:g} - {pv:g} = {d:g} > {lim:g} (rate bound)", [poid, oid], rv))
            issues.append(("implausible_counter_jump", pt, t, f"{pv:g} -> {v:g}",
                           "difference exceeds rated power x duration; energy left unknown"))
            prev = (oid, t, v)
            continue
        if dt > max_gap:
            out.append(_iv(rule, series_key, base, pt, t, d, "gap_span_total", 0, "derived",
                           f"{v:g} - {pv:g} over a {dt:g} s span (> {max_gap:g} s): total only, not allocated",
                           [poid, oid], rv))
        else:
            out.append(_iv(rule, series_key, base, pt, t, d, "valid", 1, "derived", f"{v:g} - {pv:g}",
                           [poid, oid], rv))
        prev = (oid, t, v)
    return out, issues


def power_intervals(rows, rule, series_key, base, rv):
    out = []
    max_gap = float(rule.get("max_gap_s", 180))
    for (poid, pt, pv), (oid, t, _v) in zip(rows, rows[1:]):
        dt = (t - pt) / 1000.0
        if 0 < dt <= max_gap:
            out.append(_iv(rule, series_key, base, pt, t, pv * dt / 3600.0, "estimated_from_power", 1, "estimated",
                           f"left Riemann: {pv:g} kW x {dt:g} s (snapshot, not billing-grade)", [poid], rv))
    return out, []


def recompute(store, reg, sites, run_id, affected=None):
    n_series = 0
    rv_c, rv_p = reg.rule_version("counter_difference"), reg.rule_version("power_integration")
    for pid, ep in reg.endpoints():
        rules = ep.get("derive") or []
        if not rules:
            continue
        ek = ep["endpoint_key"]
        for (skey,) in store.q("SELECT DISTINCT site_key FROM raw_records WHERE provider_profile_id=? AND "
                               "endpoint_key=? AND variant=?", (pid, ek, ep["variant"])):
            if affected is not None and (skey, ek) not in affected:
                continue
            site = sites.sites.get(skey) or {}
            tz = site.get("timezone")
            for rule in rules:
                for dkey, did, scope, ch in store.q(
                        "SELECT DISTINCT device_key, device_id, entity_scope, COALESCE(channel,'') FROM observations "
                        "WHERE site_key=? AND endpoint_key=? AND metric_name=?", (skey, ek, rule["from_metric"])):
                    n_series += 1
                    series_key = f"{rule['id']}::{skey}|{ek}|{dkey}|{ch}"
                    rows = store.q("SELECT obs_id, effective_time_ms, canonical_value FROM observations WHERE "
                                   "site_key=? AND endpoint_key=? AND metric_name=? AND device_key=? AND "
                                   "COALESCE(channel,'')=? AND availability_status='available' AND is_conflicted=0 "
                                   "AND canonical_value IS NOT NULL ORDER BY effective_time_ms, obs_id",
                                   (skey, ek, rule["from_metric"], dkey, ch))
                    base = dict(site_key=skey, endpoint_key=ek, device_key=dkey, entity_scope=scope, channel=ch)
                    ctx = {"site": site, "device": (sites.device(skey, did) if did else None) or {}}
                    if rule["method"] == "counter_difference":
                        ivs, issues = counter_intervals(rows, rule, ctx, tz, series_key, base, rv_c)
                    else:
                        ivs, issues = power_intervals(rows, rule, series_key, base, rv_p)
                    con = store.con
                    con.execute("DELETE FROM interval_energy WHERE rule_id=? AND series_key=?", (rule["id"], series_key))
                    con.execute("DELETE FROM quality_issues WHERE stage='derive' AND series_key=?", (series_key,))
                    con.execute("DELETE FROM audit_actions WHERE stage='derive' AND series_key=?", (series_key,))
                    store.insert_many("interval_energy", INTERVAL_COLS, ivs, "INSERT OR REPLACE")
                    prov = site.get("provider")
                    for code, a, b, orig, reason in issues:
                        iid = store.insert_one("quality_issues", ISSUE_COLS, [
                            run_id, "derive", "unresolved", code, "warning", prov, skey, ek, dkey, rule["to_metric"],
                            None, None, None, None, b, "counter_difference", rv_c, ep["mapping_version"], orig,
                            f"interval {ms_to_iso(a)}..{ms_to_iso(b)} energy unknown", reason, series_key])
                        store.insert_one("audit_actions", ACTION_COLS, [
                            run_id, "derive", "reset_counter_baseline", "unresolved", iid, None, None, prov, skey, ek,
                            rule["to_metric"], "counter_difference", rv_c, ep["mapping_version"], orig,
                            "crossing interval unknown; new baseline", reason, series_key])
    store.commit()
    return n_series


# ------------------------------------------------------------------------------ frames
FRAME_S = 900
AGG_BY_KIND = {"power": "mean", "percent": "mean", "temperature": "max"}


def _frame_metric_agg(md, boundary):
    if md["kind"] == "voltage" and boundary == "ac_phase":
        return "max"
    return AGG_BY_KIND.get(md["kind"])


def build_frames(store, reg, sites) -> pd.DataFrame:
    """Measurement-level observations -> 15-min frames per (site, endpoint, device, channel, metric).

    Uses each series' original cadence for coverage; never duplicates samples to fake a finer cadence; uses the
    actual frame duration (local days of 92/96/100 quarter-hours around DST)."""
    cadence = {}
    for pid, ep in reg.endpoints():
        cadence[(pid, ep["endpoint_key"], ep["variant"])] = int(ep["cadence_s"])
    ep_cad = {}
    for skey, ek, pid, var in store.q("SELECT DISTINCT site_key, endpoint_key, provider_profile_id, variant "
                                       "FROM raw_records"):
        ep_cad[(skey, ek)] = cadence.get((pid, ek, var), 0)
    df = pd.read_sql_query(
        "SELECT site_key, endpoint_key, device_id, COALESCE(device_key,'') device_key, COALESCE(channel,'') channel,"
        " metric_name, boundary, effective_time_ms t, canonical_value v, availability_status a, value_origin "
        "FROM observations WHERE is_conflicted=0", store.con)
    rows = []
    if not df.empty:
        df["agg"] = [(_frame_metric_agg(reg.metrics[m], b)) for m, b in zip(df["metric_name"], df["boundary"])]
        df = df[df["agg"].notna()].copy()
        df["frame"] = (df["t"] // (FRAME_S * 1000)) * (FRAME_S * 1000)
        access = store.q("SELECT site_key, endpoint_key, start_ms, end_ms FROM delivery_events WHERE "
                         "status_class='access_denied'")
        keys = ["site_key", "endpoint_key", "device_key", "channel", "metric_name"]
        for key, g in df.groupby(keys, sort=False):
            skey, ek, dkey, ch, m = key
            site = sites.sites.get(skey) or {}
            tz = site.get("timezone", "UTC")
            agg = g["agg"].iloc[0]
            cad = ep_cad.get((skey, ek), 0) or FRAME_S
            avail = g[g["a"] == "available"]
            stats = avail.groupby("frame")["v"].agg(["mean", "max", "count"])
            stale = g[g["a"] == "stale"].groupby("frame").size()
            d0, d1 = local_date(int(g["t"].min()), tz), local_date(int(g["t"].max()), tz)
            day = d0
            acc = [(a, b) for (s2, e2, a, b) in access if s2 == skey and e2 == ek and a is not None]
            while day <= d1:
                for fs, fe in local_day_frames(day, tz, FRAME_S):
                    n = int(stats["count"].get(fs, 0)) if fs in stats.index else 0
                    val = None
                    if n:
                        val = float(stats.loc[fs, "mean" if agg == "mean" else "max"])
                    status = "ok" if n else "no_data"
                    cov = min(1.0, n * cad / ((fe - fs) / 1000.0)) if n else 0.0
                    if n and cov < 0.999:
                        status = "partial"
                    if not n and int(stale.get(fs, 0)):
                        status = "stale_only"
                    if not n and any(a < fe and b > fs for a, b in acc):
                        status = "access_denied"
                    rows.append((site.get("provider"), site.get("account_id"), site.get("site_id"), skey, ek,
                                 g["device_id"].iloc[0], ch, m, agg, ms_to_iso(fs), ms_to_iso(fe),
                                 ms_to_local_iso(fs, tz), val, reg.metrics[m]["unit"], n, cad, round(cov, 4),
                                 g["value_origin"].iloc[0], status))
                day = day.fromordinal(day.toordinal() + 1)
    # energy frames from allocatable intervals of the best-priority rule per series
    iv = pd.read_sql_query("SELECT rule_id, site_key, endpoint_key, device_key, channel, metric_name, priority, "
                           "start_ms, end_ms, duration_s, energy_kwh, status, allocatable, value_origin "
                           "FROM interval_energy", store.con)
    if not iv.empty:
        best = iv.groupby(["site_key", "endpoint_key", "device_key", "channel", "metric_name"])["priority"].transform("min")
        iv = iv[iv["priority"] == best]
        for key, g in iv.groupby(["site_key", "endpoint_key", "device_key", "channel", "metric_name"], sort=False):
            skey, ek, dkey, ch, m = key
            site = sites.sites.get(skey) or {}
            tz = site.get("timezone", "UTC")
            good = g[(g["allocatable"] == 1) & g["energy_kwh"].notna()]
            unalloc = g[(g["allocatable"] == 0)]
            fstart = (good["start_ms"] // (FRAME_S * 1000)) * (FRAME_S * 1000)
            inside = good[good["end_ms"] <= fstart + FRAME_S * 1000]
            fs_inside = fstart[inside.index]
            sums = inside.groupby(fs_inside)["energy_kwh"].sum()
            durs = inside.groupby(fs_inside)["duration_s"].sum()
            cnts = inside.groupby(fs_inside).size()
            d0, d1 = local_date(int(g["start_ms"].min()), tz), local_date(int(g["end_ms"].max()) - 1, tz)
            day = d0
            un = list(zip(unalloc["start_ms"], unalloc["end_ms"], unalloc["status"]))
            device_id = dkey.rsplit("|", 1)[-1] if dkey else None
            while day <= d1:
                for fs, fe in local_day_frames(day, tz, FRAME_S):
                    n = int(cnts.get(fs, 0))
                    cov = float(durs.get(fs, 0.0)) / ((fe - fs) / 1000.0)
                    val = float(sums.get(fs)) if n else None
                    over = [s for a, b, s in un if a < fe and b > fs]
                    status = "ok" if n and cov >= 0.999 else ("partial" if n else "no_data")
                    if over:
                        status = (status + "+" if n else "") + "unallocated_" + sorted(set(over))[0]
                    rows.append((site.get("provider"), site.get("account_id"), site.get("site_id"), skey, ek,
                                 device_id, ch, m, "sum", ms_to_iso(fs), ms_to_iso(fe), ms_to_local_iso(fs, tz), val,
                                 "kWh", n, None, round(min(cov, 1.0), 4), g["value_origin"].iloc[0], status))
                day = day.fromordinal(day.toordinal() + 1)
    cols = ["provider", "account_id", "site_id", "site_key", "endpoint_key", "device_id", "channel", "metric_name",
            "aggregation", "frame_start_utc", "frame_end_utc", "frame_start_local", "value", "unit", "n_obs",
            "original_cadence_s", "coverage_ratio", "value_origin", "frame_status"]
    return pd.DataFrame(rows, columns=cols)
