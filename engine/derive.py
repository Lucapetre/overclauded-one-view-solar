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

Component counter segments (counter: lifetime_nonresettable | resettable):
* non-resettable lifetime counter: a decrease is an unexplained DISCONTINUITY. It is flagged, its interval energy is
  unknown (never negative), the new reading becomes the baseline. No reset is invented.
* documented-resettable counter: a decrease starts a NEW SEGMENT. If the asset registry's maintenance log records a
  reset inside the crossing interval it is a known reset; otherwise the segment start is flagged as unlogged. The
  delta across the reset is withheld in both cases; later deltas inside the new segment are valid.
* bounded gaps: a delta over a span longer than max_gap_s is a TOTAL for its span, not allocated to sub-intervals.
"""
from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal

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


def segment_counter_intervals(rows, rule, ctx, series_key, base, rv):
    """Counter deltas within compatible segments of ONE physical counter (see module docstring).

    rows: (obs_id, t_ms, value_kwh[, exact_text]). Exact decimal text, when present, is differenced exactly."""
    out, issues = [], []
    max_gap = float(rule.get("max_gap_s", 900))
    res = float(rule.get("resolution", 0.0))
    rate = resolve_ref(ctx, rule.get("max_rate_ref"))
    factor = float(rule.get("max_rate_factor", 1.3))
    resettable = rule["counter"] == "resettable"
    resets = sorted(ctx.get("resets_ms") or [])
    slack = float(rule.get("reset_match_s", 120)) * 1000
    prev = None
    for row in rows:
        oid, t, v = row[0], row[1], row[2]
        ex = row[3] if len(row) > 3 else None
        if prev is None:
            prev = row
            continue
        poid, pt, pv = prev[0], prev[1], prev[2]
        pex = prev[3] if len(prev) > 3 else None
        if t == pt:
            continue
        dt = (t - pt) / 1000.0
        d = float(Decimal(ex) - Decimal(pex)) if ex is not None and pex is not None else v - pv
        if d < -res:
            if resettable:
                known = [r for r in resets if pt - slack <= r <= t + slack]
                st = "segment_start_known_reset" if known else "segment_start_unlogged_decrease"
                out.append(_iv(rule, series_key, base, pt, t, None, st, 0, "derived",
                               f"{v:g} < {pv:g} on a documented-resettable counter: new segment; delta across the "
                               f"reset withheld", [poid, oid], rv))
                if known:
                    issues.append(("known_counter_reset_new_segment", pt, t, f"{pv:g} -> {v:g}",
                                   "logged reset of a resettable counter: new segment, crossing delta withheld, later "
                                   "deltas valid", "info", "informational"))
                else:
                    issues.append(("resettable_counter_decrease_unlogged", pt, t, f"{pv:g} -> {v:g}",
                                   "decrease of a resettable counter without a logged reset: new segment, crossing "
                                   "delta withheld; flagged for review", "warning", "unresolved"))
            else:
                out.append(_iv(rule, series_key, base, pt, t, None, "counter_discontinuity", 0, "derived",
                               f"{v:g} - {pv:g} < 0 on a non-resettable counter: discontinuity; no reset invented, "
                               f"energy unknown (never negative)", [poid, oid], rv))
                issues.append(("unexplained_counter_decrease", pt, t, f"{pv:g} -> {v:g}",
                               "non-resettable counter went backwards: discontinuity flagged, no reset or negative "
                               "energy invented; later deltas use the new reading as baseline", "warning",
                               "unresolved"))
            prev = row
            continue
        d = max(d, 0.0)
        lim = rate * dt / 3600.0 * factor + res if rate else None
        if lim is not None and d > lim:
            out.append(_iv(rule, series_key, base, pt, t, None, "implausible_counter_jump", 0, "derived",
                           f"{v:g} - {pv:g} = {d:g} > {lim:g} (rate bound)", [poid, oid], rv))
            issues.append(("implausible_counter_jump", pt, t, f"{pv:g} -> {v:g}",
                           "difference exceeds rated power x duration; energy left unknown", "warning", "unresolved"))
            prev = row
            continue
        if dt > max_gap:
            out.append(_iv(rule, series_key, base, pt, t, d, "gap_span_total", 0, "derived",
                           f"{v:g} - {pv:g} over a {dt:g} s span (> {max_gap:g} s): total only, not allocated",
                           [poid, oid], rv))
        else:
            out.append(_iv(rule, series_key, base, pt, t, d, "valid", 1, "derived", f"{v:g} - {pv:g}",
                           [poid, oid], rv))
        prev = row
    return out, issues


def power_intervals(rows, rule, series_key, base, rv):
    out = []
    max_gap = float(rule.get("max_gap_s", 180))
    comp = rule.get("component")
    for (poid, pt, pv), (oid, t, _v) in zip(rows, rows[1:]):
        dt = (t - pt) / 1000.0
        if 0 < dt <= max_gap:
            if comp is None:
                out.append(_iv(rule, series_key, base, pt, t, pv * dt / 3600.0, "estimated_from_power", 1,
                               "estimated", f"left Riemann: {pv:g} kW x {dt:g} s (snapshot, not billing-grade)",
                               [poid], rv))
            else:
                part = max(pv, 0.0) if comp == "positive" else max(-pv, 0.0)
                out.append(_iv(rule, series_key, base, pt, t, part * dt / 3600.0, "estimated_from_power", 1,
                               "estimated", f"{comp} part of {pv:g} kW held for {dt:g} s (bounded hold "
                               f"<= {max_gap:g} s; snapshot estimate, not billing-grade)", [poid], rv))
    return out, []


def recompute(store, reg, sites, run_id, affected=None):
    n_series = 0
    rv_c, rv_p = reg.rule_version("counter_difference"), reg.rule_version("power_integration")
    exact_col = "exact_value_text" if getattr(store, "extended", False) else "NULL"
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
                    segmented = rule["method"] == "counter_difference" and rule["counter"] in (
                        "lifetime_nonresettable", "resettable")
                    cols = f"obs_id, effective_time_ms, canonical_value{', ' + exact_col if segmented else ''}"
                    rows = store.q(f"SELECT {cols} FROM observations WHERE "
                                   "site_key=? AND endpoint_key=? AND metric_name=? AND device_key=? AND "
                                   "COALESCE(channel,'')=? AND availability_status='available' AND is_conflicted=0 "
                                   "AND canonical_value IS NOT NULL ORDER BY effective_time_ms, obs_id",
                                   (skey, ek, rule["from_metric"], dkey, ch))
                    base = dict(site_key=skey, endpoint_key=ek, device_key=dkey, entity_scope=scope, channel=ch)
                    ctx = {"site": site, "device": (sites.device(skey, did) if did else None) or {}}
                    if segmented:
                        ev = getattr(sites, "maintenance_events", None)
                        ctx["resets_ms"] = [_iso_ms(e["time_utc"]) for e in (ev(skey, did, "counter_reset")
                                                                              if ev and did else [])]
                        ivs, issues = segment_counter_intervals(rows, rule, ctx, series_key, base, rv_c)
                    elif rule["method"] == "counter_difference":
                        ivs, issues = counter_intervals(rows, rule, ctx, tz, series_key, base, rv_c)
                    else:
                        ivs, issues = power_intervals(rows, rule, series_key, base, rv_p)
                    con = store.con
                    con.execute("DELETE FROM interval_energy WHERE rule_id=? AND series_key=?", (rule["id"], series_key))
                    con.execute("DELETE FROM quality_issues WHERE stage='derive' AND series_key=?", (series_key,))
                    con.execute("DELETE FROM audit_actions WHERE stage='derive' AND series_key=?", (series_key,))
                    store.insert_many("interval_energy", INTERVAL_COLS, ivs, "INSERT OR REPLACE")
                    prov = site.get("provider")
                    for issue in issues:
                        code, a, b, orig, reason = issue[:5]
                        sev, cat = (issue[5], issue[6]) if len(issue) > 5 else ("warning", "unresolved")
                        iid = store.insert_one("quality_issues", ISSUE_COLS, [
                            run_id, "derive", cat, code, sev, prov, skey, ek, dkey, rule["to_metric"],
                            None, None, None, None, b, "counter_difference", rv_c, ep["mapping_version"], orig,
                            f"interval {ms_to_iso(a)}..{ms_to_iso(b)} energy unknown", reason, series_key])
                        store.insert_one("audit_actions", ACTION_COLS, [
                            run_id, "derive", "reset_counter_baseline", cat, iid, None, None, prov, skey, ek,
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


def _iso_ms(text):
    from .timeparse import parse_time, to_ms
    r = parse_time(text, "iso_offset")
    return to_ms(r.utc)


# ============================================================================== component frames & authority
# Frame aggregation by (metric kind, source aggregation). Means of instantaneous snapshots are labelled as such;
# SoC/limits use the LAST VALID observation with its timestamp (never averaged); min/max are retained.
_KIND_AGGS = {"power": ["mean"], "current": ["mean"], "frequency": ["mean"], "irradiance": ["mean"],
              "voltage": ["mean", "min", "max"], "temperature": ["mean", "max"], "percent": ["last_valid"],
              "limit": ["last_valid"], "capacity": ["last_valid"], "state": ["last"]}


def _frame_aggs(kind, agg):
    if agg == "interval_max":
        return ["max"]
    if agg == "interval_min":
        return ["min"]
    if agg == "last_valid_instantaneous":
        return ["last_valid"]
    return _KIND_AGGS.get(kind, [])


def _basis(rule):
    if rule is None:
        return None
    if rule["method"] == "counter_difference":
        return "measured_counter_delta"
    return "estimated_power_integration"


def _site_label(sites, skey):
    s = sites.sites.get(skey) or {}
    return s.get("demo_site_key") or s.get("resource_id")


def build_component_frames(store, reg, sites, frame_s=900, boundary_tol_s=10.0, min_cov=0.995):
    """Observations + interval energy -> 15-min frames with explicit aggregation semantics.

    Energy: an interval whose ends are within boundary_tol_s of one frame is allocated to that frame (snapshot timing
    tolerance); an interval spanning several frames is NOT split (unallocated, flagged in frame_status)."""
    F = frame_s * 1000
    tol = boundary_tol_s * 1000
    cadence = {(pid, ep["endpoint_key"], ep["variant"]): int(ep["cadence_s"]) for pid, ep in reg.endpoints()}
    rules = {d["id"]: d for _, ep in reg.endpoints() for d in (ep.get("derive") or [])}
    series_meta = {}
    for skey, ek, pid, var in store.q("SELECT DISTINCT site_key, endpoint_key, provider_profile_id, variant FROM "
                                       "raw_records"):
        series_meta[(skey, ek)] = (pid, cadence.get((pid, ek, var), 0))
    df = pd.read_sql_query(
        "SELECT site_key, endpoint_key, COALESCE(device_key,'') device_key, physical_asset_id, family, metric_name, "
        "metric_kind, COALESCE(channel,'') channel, phase, boundary, mounting, sensor_position, "
        "COALESCE(aggregation,'instantaneous') aggregation, effective_time_ms t, interval_start_ms a, "
        "interval_end_ms b, canonical_value v, availability_status av, value_origin, scenario_version "
        "FROM observations WHERE is_conflicted=0", store.con)
    rows = []
    if not df.empty:
        df["mid"] = df["t"].where(df["a"].isna(), (df["a"] + df["b"]) / 2)
        df["frame"] = (df["mid"] // F).astype("int64") * F
        keys = ["site_key", "endpoint_key", "device_key", "metric_name", "channel", "aggregation"]
        for key, g in df.groupby(keys, sort=True):
            skey, ek, dkey, m, ch, agg = key
            kind = g["metric_kind"].iloc[0]
            aggs = _frame_aggs(kind, agg)
            if not aggs:
                continue
            site = sites.sites.get(skey) or {}
            tz = site.get("timezone", "UTC")
            pid, cad = series_meta.get((skey, ek), (None, 0))
            cad = cad or frame_s
            av = g[(g["av"] == "available") & g["v"].notna()].sort_values(["t"])
            first = g.iloc[0]
            interval_based = agg.startswith("interval_")
            if interval_based and not av.empty:
                av = av.assign(cover=(av["b"] - av["a"]).clip(lower=0) / 1000.0)
            grouped = {fs: x for fs, x in av.groupby("frame")}
            non_av = g[g["av"] != "available"].groupby("frame")["av"].agg(lambda x: sorted(set(x))[0])
            d0, d1 = local_date(int(g["t"].min()), tz), local_date(int(g["t"].max()), tz)
            day = d0
            while day <= d1:
                for fs, fe in local_day_frames(day, tz, frame_s):
                    x = grouped.get(fs)
                    n = 0 if x is None else len(x)
                    dur = (fe - fs) / 1000.0
                    if n:
                        cov = (float(x["cover"].sum()) if interval_based else n * cad) / dur
                    else:
                        cov = 0.0
                    status = "ok" if n and cov >= min_cov else ("partial" if n else "no_data")
                    if not n and fs in non_av.index:
                        status = f"only_{non_av.loc[fs]}"
                    for fa in aggs:
                        val, vt = None, None
                        if n:
                            if fa == "mean":
                                val = float(x["v"].mean())
                            elif fa == "max":
                                val = float(x["v"].max())
                            elif fa == "min":
                                val = float(x["v"].min())
                            else:  # last / last_valid: the observation itself, with its own timestamp
                                val = float(x["v"].iloc[-1])
                                vt = ms_to_iso(int(x["t"].iloc[-1]))
                        rows.append((skey, _site_label(sites, skey), ek, pid, first["family"],
                                     first["physical_asset_id"], dkey, m, ch or None, first["phase"],
                                     first["boundary"], first["mounting"], first["sensor_position"], agg, fa, None, None,
                                     ms_to_iso(fs), ms_to_iso(fe), ms_to_local_iso(fs, tz), int(fs), val, vt,
                                     reg.metrics[m]["unit"], n, cad, round(min(cov, 1.0), 4), first["value_origin"],
                                     status, first["scenario_version"]))
                day = day.fromordinal(day.toordinal() + 1)
    # ---- interval energy (every rule kept separately; authority picks among them later)
    iv = pd.read_sql_query("SELECT rule_id, site_key, endpoint_key, device_key, channel, metric_name, start_ms, end_ms, "
                           "duration_s, energy_kwh, status, allocatable, value_origin FROM interval_energy",
                           store.con)
    assets_by_dev = {}
    for (skey, did), dev in sites.devices.items():
        assets_by_dev[f"{skey}|{did}"] = dev
    for key, g in iv.groupby(["rule_id", "site_key", "endpoint_key", "device_key", "channel", "metric_name"],
                             sort=True):
        rid, skey, ek, dkey, ch, m = key
        site = sites.sites.get(skey) or {}
        tz = site.get("timezone", "UTC")
        dev = assets_by_dev.get(dkey) or {}
        pid, _ = series_meta.get((skey, ek), (None, 0))
        alloc, unalloc = defaultdict(lambda: [0.0, 0.0, 0]), []
        for a, b, e, stt, al in zip(g["start_ms"], g["end_ms"], g["energy_kwh"], g["status"], g["allocatable"]):
            fs = int(((a + tol) // F) * F)
            if al == 1 and e is not None and not pd.isna(e) and a >= fs - tol and b <= fs + F + tol:
                cell = alloc[fs]
                cell[0] += float(e)
                cell[1] += (min(b, fs + F) - max(a, fs)) / 1000.0
                cell[2] += 1
            else:
                unalloc.append((a, b, stt))
        d0, d1 = local_date(int(g["start_ms"].min()), tz), local_date(int(g["end_ms"].max()) - 1, tz)
        day = d0
        rule = rules.get(rid)
        while day <= d1:
            for fs, fe in local_day_frames(day, tz, frame_s):
                cell = alloc.get(fs)
                n = cell[2] if cell else 0
                cov = (cell[1] / ((fe - fs) / 1000.0)) if cell else 0.0
                status = "ok" if n and cov >= min_cov else ("partial" if n else "no_data")
                over = sorted({st for a, b, st in unalloc if a < fe and b > fs})
                if over:
                    status = (status + "+" if n else "") + "unallocated_" + over[0]
                rows.append((skey, _site_label(sites, skey), ek, pid, dev.get("family"),
                             dev.get("asset_id") or (dkey.rsplit("|", 1)[-1] if dkey else None), dkey, m, ch or None,
                             None, dev.get("boundary"), None, None, "interval_energy", "sum", rid, _basis(rule),
                             ms_to_iso(fs), ms_to_iso(fe), ms_to_local_iso(fs, tz), int(fs),
                             cell[0] if n else None, None, "kWh", n, None, round(min(cov, 1.0), 4),
                             g["value_origin"].iloc[0], status, getattr(sites, "scenario_version", None)))
            day = day.fromordinal(day.toordinal() + 1)
    from .storage import FRAME_COLS
    return pd.DataFrame(rows, columns=FRAME_COLS)


def compute_authority(store, sites, frames: pd.DataFrame, policy_version="authority-1.0"):
    """One authoritative source per site x boundary x metric x 15-min frame, with quality-aware fallback.

    Candidates come ONLY from the asset registry's declarations (rank order). Mirrored copies of the same physical
    meter are never summed; they may be used as a labelled fallback if declared so. Disagreements between the
    selected source and another complete candidate are recorded as conflicts (selection unchanged)."""
    from .storage import AUTH_COLS
    con = store.con
    con.execute("DELETE FROM authority_frames")
    con.execute("DELETE FROM authority_conflicts")
    energy = frames[frames["frame_aggregation"] == "sum"] if not frames.empty else frames
    out, conflicts = [], []
    for decl in getattr(sites, "authority", []):
        skey, boundary = decl["site_key"], decl["boundary"]
        min_cov = float(decl.get("min_coverage", 0.995))
        tol_abs = float((decl.get("conflict_tolerance") or {}).get("abs_kwh", 0.05))
        tol_rel = float((decl.get("conflict_tolerance") or {}).get("rel", 0.15))
        mirrors = [m.get("label") or m.get("endpoint_key") for m in decl.get("mirrors", [])]
        for metric, cands in sorted(decl["metrics"].items()):
            per = []
            for c in sorted(cands, key=lambda c: c["rank"]):
                sel = energy[(energy["site_key"] == skey) & (energy["metric_name"] == metric) &
                             (energy["rule_id"] == c["rule_id"]) & (energy["endpoint_key"] == c["endpoint_key"])]
                if c.get("asset_id"):
                    sel = sel[sel["physical_asset_id"] == c["asset_id"]]
                per.append((c, {int(r.frame_start_ms): r for r in sel.itertuples(index=False)}))
            starts = sorted({fs for _, d in per for fs in d})
            for fs in starts:
                cj, chosen = [], None
                for c, d in per:
                    r = d.get(fs)
                    ok = r is not None and r.value is not None and not pd.isna(r.value) and r.coverage_ratio >= min_cov \
                        and r.frame_status == "ok"
                    cj.append({"rank": c["rank"], "role": c["role"], "basis": c.get("basis"),
                               "asset_id": c.get("asset_id"), "endpoint_key": c["endpoint_key"], "rule_id": c["rule_id"],
                               "value_kwh": None if r is None or pd.isna(r.value) else round(float(r.value), 6),
                               "coverage": None if r is None else float(r.coverage_ratio),
                               "frame_status": None if r is None else r.frame_status, "complete": bool(ok)})
                    if ok and chosen is None:
                        chosen = (c, r)
                any_r = next((d[fs] for _, d in per if fs in d), None)
                if chosen:
                    c, r = chosen
                    status = "selected_primary" if c["role"] == "primary" else f"selected_{c['role']}"
                    reason = ("primary source complete" if c["role"] == "primary" else
                              "higher-ranked candidates incomplete: " + ", ".join(
                                  f"rank {x['rank']} {x['frame_status']}" for x in cj if x["rank"] < c["rank"]))
                    val = float(r.value)
                    origin = "measured" if c.get("basis") == "measured_counter_delta" else "estimated"
                    for x in cj:
                        comparable = x["basis"] == c.get("basis") or x["role"].startswith("mirror")
                        if x["complete"] and x["rank"] != c["rank"] and x["value_kwh"] is not None and comparable:
                            diff = abs(x["value_kwh"] - val)
                            lim = max(tol_abs, tol_rel * max(abs(val), abs(x["value_kwh"])))
                            if diff > lim:
                                conflicts.append((skey, boundary, metric, ms_to_iso(fs), fs, val, x["role"],
                                                  x["asset_id"], x["endpoint_key"], x["basis"], x["value_kwh"],
                                                  round(diff, 6), round(lim, 6), "selected_source_retained"))
                    out.append((skey, _site_label(sites, skey), boundary, metric, ms_to_iso(fs),
                                any_r.frame_end_utc, fs, val, c["rank"], c["role"], c.get("basis"), c.get("asset_id"),
                                c["endpoint_key"], c["rule_id"], float(r.coverage_ratio), origin, status, reason,
                                json.dumps(mirrors), json.dumps(cj), decl.get("policy_version", policy_version)))
                else:
                    out.append((skey, _site_label(sites, skey), boundary, metric, ms_to_iso(fs),
                                any_r.frame_end_utc, fs, None, None, None, None, None, None, None, None, None,
                                "no_complete_source", "no declared candidate is complete for this frame; value "
                                "unknown (no zero, no estimate promoted silently)", json.dumps(mirrors),
                                json.dumps(cj), decl.get("policy_version", policy_version)))
    store.insert_many("authority_frames", AUTH_COLS, out, "INSERT OR REPLACE")
    store.insert_many("authority_conflicts", ["site_key", "boundary", "metric_name", "frame_start_utc",
                                              "frame_start_ms", "primary_value", "other_role", "other_asset_id",
                                              "other_endpoint_key", "other_basis", "other_value", "abs_diff",
                                              "tolerance", "resolution"], conflicts)
    store.commit()
    return len(out), len(conflicts)


# ------------------------------------------------------------------------------ derived component tables
def compute_state_tables(store, reg, sites, as_of_ms):
    """State episodes (documented alarm/status codes != normal), BMS limit history and battery status."""
    con = store.con
    for t in ("state_episodes", "limit_history", "battery_status"):
        con.execute(f"DELETE FROM {t}")
    normal = reg.default("normal_state_values", {})
    rows = store.q("SELECT obs_id, site_key, physical_asset_id, metric_name, COALESCE(channel,''), effective_time_ms, "
                   "canonical_value, canonical_text, state_label FROM observations WHERE metric_kind='state' AND "
                   "availability_status='available' AND is_conflicted=0 AND physical_asset_id IS NOT NULL "
                   "ORDER BY site_key, physical_asset_id, metric_name, channel, effective_time_ms, obs_id")
    eps = []
    cur = None
    for oid, sk, aid, m, ch, t, cv, ct, lab in rows:
        if m not in normal:  # only metrics with DOCUMENTED normal values; raw-only states (no labels) stay raw
            continue
        norm = [str(x) for x in normal.get(m, [])]
        is_normal = ct in norm or (ct in ("[]", "null", None) and m in normal)
        k = (sk, aid, m, ch)
        if cur and (cur["k"] != k or cur["v"] != ct):
            eps.append(cur)
            cur = None
        if not is_normal and cur is None:
            cur = {"k": k, "v": ct, "lab": lab, "a": t, "b": t, "n": 0, "o1": oid, "o2": oid}
        if cur is not None:
            cur.update(b=t, n=cur["n"] + 1, o2=oid)
    if cur:
        eps.append(cur)
    last_seen = {}
    for sk, aid, m, ch, t in store.q("SELECT site_key, physical_asset_id, metric_name, COALESCE(channel,''), "
                                    "MAX(effective_time_ms) FROM observations WHERE metric_kind='state' GROUP BY 1,2,3,4"):
        last_seen[(sk, aid, m, ch)] = t
    for e in eps:
        sk, aid, m, ch = e["k"]
        active = int(last_seen.get(e["k"]) == e["b"] and e["b"] <= as_of_ms)
        con.execute("INSERT INTO state_episodes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sk, aid, m, ch or None, e["v"], e["lab"], ms_to_iso(e["a"]), ms_to_iso(e["b"]), e["a"], e["b"],
                     e["n"], active, e["o1"], e["o2"]))
    lim_metrics = [m for m, d in reg.metrics.items() if d["kind"] == "limit"]
    if lim_metrics:
        q = ",".join("?" * len(lim_metrics))
        rows = store.q(f"SELECT obs_id, site_key, physical_asset_id, metric_name, effective_time_ms, canonical_value "
                       f"FROM observations WHERE metric_name IN ({q}) AND availability_status='available' AND "
                       f"canonical_value IS NOT NULL ORDER BY site_key, physical_asset_id, metric_name, "
                       f"effective_time_ms, obs_id", lim_metrics)
        cur = None
        runs = []
        for oid, sk, aid, m, t, v in rows:
            k = (sk, aid, m)
            if cur and (cur["k"] != k or abs(cur["v"] - v) > 1e-9):
                runs.append(cur)
                cur = None
            if cur is None:
                cur = {"k": k, "v": v, "a": t, "b": t, "n": 0, "o1": oid, "o2": oid}
            cur.update(b=t, n=cur["n"] + 1, o2=oid)
        if cur:
            runs.append(cur)
        for r_ in runs:
            sk, aid, m = r_["k"]
            dev = getattr(sites, "assets", {}).get(aid) or {}
            nom = (dev.get("declared_nominal_limits") or {}).get(m)
            con.execute("INSERT INTO limit_history VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (sk, aid, m, r_["v"], reg.metrics[m]["unit"], ms_to_iso(r_["a"]), ms_to_iso(r_["b"]), r_["a"],
                         r_["b"], r_["n"], nom, None if nom is None else int(r_["v"] < nom - 1e-9), r_["o1"], r_["o2"]))
    # ---- battery status at as_of (last valid observations; capability flags from the profile declaration)
    for aid, dev in sorted(getattr(sites, "assets", {}).items()):
        if dev.get("family") != "battery" or dev.get("source_role") == "test_only":
            continue
        sk = dev["site_key"]

        def last(metric, extra=""):
            r_ = store.q(f"SELECT obs_id, effective_time_ms, canonical_value, canonical_text FROM observations WHERE "
                         f"physical_asset_id=? AND metric_name=? AND availability_status='available' AND "
                         f"is_conflicted=0 AND effective_time_ms<=? {extra} ORDER BY effective_time_ms DESC, obs_id DESC "
                         f"LIMIT 1", (aid, metric, as_of_ms))
            return r_[0] if r_ else None

        soc = last("soc_pct")
        prof = reg.profiles.get(dev.get("profile_id")) or {}
        mapped = {f["metric"] for ep in prof.get("endpoints", []) for ent in ep["entities"] for f in ent["fields"]
                  if "metric" in f}
        lim_names = ["battery_max_charge_current_a", "battery_max_discharge_current_a", "battery_max_charge_voltage_v",
                     "battery_min_discharge_voltage_v"]
        lims = {m: last(m) for m in lim_names}
        limits_declared = {"battery_max_charge_current_a", "battery_max_discharge_current_a"} <= mapped
        limits_available = int(limits_declared and all(lims[m] for m in lim_names[:2]))
        alarms = store.q("SELECT channel, state_value, state_label, start_utc FROM state_episodes WHERE "
                         "physical_asset_id=? AND active_at_as_of=1 AND metric_name='battery_alarm_raw' ORDER BY channel",
                         (aid,))
        st = last("battery_state_raw")
        cap = last("battery_capacity_ah")
        lt = [x[1] for x in lims.values() if x]
        con.execute("INSERT INTO battery_status VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            sk, _site_label(sites, sk), aid, dev.get("profile_id"), ms_to_iso(as_of_ms),
            soc[2] if soc else None, ms_to_iso(soc[1]) if soc else None, soc[0] if soc else None,
            (as_of_ms - soc[1]) / 1000.0 if soc else None, limits_available,
            *[(lims[m][2] if lims[m] else None) for m in lim_names], ms_to_iso(max(lt)) if lt else None,
            json.dumps([{"alarm": a[0], "value": a[1], "label": a[2], "since_utc": a[3]} for a in alarms]),
            st[3] if st else None, cap[2] if cap else None, json.dumps(dev.get("declared") or {}, sort_keys=True),
            json.dumps({"soc_mapped": "soc_pct" in mapped, "limits_mapped": limits_declared,
                        "alarms_mapped": "battery_alarm_raw" in mapped,
                        "energy_throughput_mapped": bool(mapped & {"lifetime_battery_charge_kwh", "battery_net_kw"})},
                       sort_keys=True)))
    store.commit()


def compute_collector_outages(store, sites, min_sources=2, join_gap_s=1800):
    """Windows where >= min_sources sources served by ONE declared collector failed at overlapping times."""
    con = store.con
    con.execute("DELETE FROM collector_outages")
    n = 0
    for col in getattr(sites, "collectors", []):
        served = [(x["site_key"], x["endpoint_key"]) for x in col.get("serves", [])]
        runs = {}
        for sk, ek in served:
            ev = store.q("SELECT d.recorded_at_ms, d.status, d.status_class, d.delivery_hash FROM raw_deliveries d "
                         "WHERE d.site_key=? AND d.endpoint_key=? AND d.recorded_at_ms IS NOT NULL ORDER BY "
                         "d.recorded_at_ms", (sk, ek))
            rr, cur = [], None
            for t, status, cls, dh in ev:
                failed = status in ("transport_error", "provider_failure")
                if failed:
                    if cur and t - cur["b"] <= join_gap_s * 1000:
                        cur.update(b=t, n=cur["n"] + 1)
                        cur["cls"].add(cls)
                        cur["dh"].append(dh)
                    else:
                        if cur:
                            rr.append(cur)
                        cur = {"a": t, "b": t, "n": 1, "cls": {cls}, "dh": [dh]}
                elif cur:
                    rr.append(cur)
                    cur = None
            if cur:
                rr.append(cur)
            runs[(sk, ek)] = rr
        allr = [(k, r_) for k, rr in runs.items() for r_ in rr]
        allr.sort(key=lambda x: x[1]["a"])
        used = set()
        for i, (k, r_) in enumerate(allr):
            if i in used:
                continue
            group = [(k, r_)]
            a, b = r_["a"], r_["b"]
            for j in range(i + 1, len(allr)):
                k2, r2 = allr[j]
                if r2["a"] <= b and r2["b"] >= a and k2 != k:
                    group.append((k2, r2))
                    used.add(j)
                    a, b = max(a, r2["a"]), min(b, r2["b"])
            if len({g[0][0] for g in group}) >= min_sources:
                con.execute("INSERT INTO collector_outages VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                    col["collector_id"], ms_to_iso(min(g[1]["a"] for g in group)),
                    ms_to_iso(max(g[1]["b"] for g in group)), min(g[1]["a"] for g in group),
                    max(g[1]["b"] for g in group), json.dumps(sorted({g[0][0] for g in group})),
                    json.dumps(sorted({g[0][1] for g in group})), sum(g[1]["n"] for g in group),
                    json.dumps(sorted({c for g in group for c in g[1]["cls"] if c})),
                    json.dumps([h for g in group for h in g[1]["dh"]][:50]),
                    f"{len(group)} sources served by declared collector {col['collector_id']} failed at overlapping "
                    f"times (first failure .. last failure); missing feeds alone do not establish loss of supply"))
                n += 1
    store.commit()
    return n


def compute_capabilities(store, reg, sites):
    """capability_registry: declaration (profile of an asset at the site maps the metric) vs observed valid data.

    Area resources contribute to their explicitly linked sites (declared_basis names the resource)."""
    con = store.con
    con.execute("DELETE FROM capability_registry")
    defs = reg.data.get("capability_definitions") or {}
    assets = getattr(sites, "assets", {})
    by_site = defaultdict(list)
    for aid, a in assets.items():
        if a.get("source_role") == "test_only":
            continue
        by_site[a["site_key"]].append(a)
    links = defaultdict(list)
    for rk, r_ in getattr(sites, "resources", {}).items():
        for sk in r_.get("linked_site_keys") or []:
            links[sk].append(rk)
    mapped = {}
    for pid, prof in reg.profiles.items():
        mapped[pid] = {f["metric"] for ep in prof["endpoints"] for ent in ep["entities"] for f in ent["fields"]
                       if "metric" in f and f.get("capability") != "unsupported_on_model"}
    targets = sorted(set(by_site) | set(links))
    for sk in targets:
        for cap, d in sorted(defs.items()):
            need = d.get("metrics_all") or d.get("metrics_any") or []
            mode_all = "metrics_all" in d
            srcs = [(sk, a, "asset") for a in by_site.get(sk, [])]
            srcs += [(rk, a, f"linked_area_resource:{rk}") for rk in links.get(sk, []) for a in by_site.get(rk, [])]
            hits = []
            for owner, a, basis in srcs:
                m = mapped.get(a.get("profile_id"), set())
                ok = all(x in m for x in need) if mode_all else any(x in m for x in need)
                if d.get("boundary") and a.get("boundary") != d["boundary"]:
                    ok = False
                plane = (a.get("mounting") or {}).get("plane") if isinstance(a.get("mounting"), dict) else None
                if d.get("mounting") and plane != d["mounting"]:
                    ok = False
                if ok:
                    hits.append((owner, a, basis))
            declared = int(bool(hits))
            n, t0, t1 = 0, None, None
            for owner, a, basis in hits:
                q = ",".join("?" * len(need))
                extra, args = "", list(need)
                if d.get("mounting"):
                    extra = " AND mounting=?"
                    args.append(d["mounting"])
                row = store.q(f"SELECT COUNT(*), MIN(effective_time_ms), MAX(effective_time_ms) FROM observations "
                              f"WHERE physical_asset_id=? AND metric_name IN ({q}) AND availability_status='available'"
                              f"{extra}", [a["asset_id"]] + args)[0]
                n += row[0] or 0
                t0 = row[1] if t0 is None or (row[1] is not None and row[1] < t0) else t0
                t1 = row[2] if t1 is None or (row[2] is not None and row[2] > t1) else t1
            state = ("available" if declared and n else "declared_not_observed" if declared else "not_declared")
            reason = d.get("description", "")
            if not declared:
                reason = "no registered asset/profile at this site exposes " + "+".join(need)
            con.execute("INSERT INTO capability_registry VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                sk, _site_label(sites, sk), cap, declared, ";".join(sorted({b for _, _, b in hits})) or None,
                json.dumps(sorted({a["asset_id"] for _, a, _ in hits})), n, ms_to_iso(t0), ms_to_iso(t1), state,
                reason))
    store.commit()


def write_registry_tables(store, reg, sites, meta: dict):
    con = store.con
    for t in ("site_registry", "asset_registry", "component_meta"):
        con.execute(f"DELETE FROM {t}")
    import hashlib as _h
    for sk, s in sorted(sites.sites.items()):
        kind = "area_resource" if sk in getattr(sites, "resources", {}) else "site"
        bsid = None if kind == "area_resource" else "provider-" + _h.sha256(sk.encode()).hexdigest()[:24]
        con.execute("INSERT INTO site_registry VALUES(?,?,?,?,?,?)",
                    (sk, kind, s.get("demo_site_key"), bsid, s.get("timezone"),
                     json.dumps({k: v for k, v in s.items() if k not in ("devices", "site_key")}, sort_keys=True,
                                default=str)))
    for aid, a in sorted(getattr(sites, "assets", {}).items()):
        mnt = a.get("mounting")
        con.execute("INSERT INTO asset_registry VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (aid, a["site_key"], a.get("demo_site_key"), a.get("family"), a.get("profile_id"),
                     a.get("device_id"), a.get("source_role"), a.get("boundary"),
                     (mnt.get("plane") if isinstance(mnt, dict) else mnt), json.dumps(a, sort_keys=True, default=str)))
    for k, v in sorted(meta.items()):
        con.execute("INSERT INTO component_meta VALUES(?,?)", (k, v if isinstance(v, str) else json.dumps(v)))
    store.commit()
