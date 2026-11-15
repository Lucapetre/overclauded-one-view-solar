"""Shared ingestion pipeline: read -> extract -> map -> validate -> persist.

Every registered profile flows through exactly these functions. Profile differences are data (registry), never
code branches. The pipeline never repairs JSON punctuation, never guesses units, offsets or DST folds, never
clamps values and never invents identifiers or timestamps.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict

from decimal import Decimal

from .selectors import MISSING, condition, resolve_ref, select
from .sites import device_key, id_to_str
from .storage import ACTION_COLS, DELIVERY_COLS, ISSUE_COLS, OBS_COLS, RECORD_COLS
from .timeparse import parse_time, to_ms
from .transforms import (REGISTER_TYPES, convert_unit, decimal_text, decode_words, edge_flow_value, edge_set,
                         exact_convert, gather_words, parse_number, scale_from_register)


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def iterate(steps, ctx):
    """Expand declared iteration steps into record/entity contexts. Returns (contexts, problem|None)."""
    if not steps:
        return [ctx], None
    out, problems = [], []

    def walk(i, c):
        if i == len(steps):
            out.append(c)
            return
        st = steps[i]
        coll = select(c, st["path"])
        if coll is MISSING or coll is None:
            problems.append(f"{st['path']} absent or null")
            return
        if st["kind"] == "list":
            if not isinstance(coll, list):
                problems.append(f"{st['path']} is {type(coll).__name__}, expected list")
                return
            for j, item in enumerate(coll):
                c2 = dict(c)
                c2[st["alias"]] = item
                c2[st["alias"] + "#idx"] = j
                walk(i + 1, c2)
        else:
            if not isinstance(coll, dict):
                problems.append(f"{st['path']} is {type(coll).__name__}, expected object")
                return
            for k, v in coll.items():
                c2 = dict(c)
                c2[st["alias"]] = v
                c2[st["alias"] + "#key"] = k
                walk(i + 1, c2)

    walk(0, ctx)
    return out, (problems[0] if problems else None)


def _short(v, n=160):
    if v is MISSING:
        return "<absent>"
    s = v if isinstance(v, str) else canon(v)
    return s if len(s) <= n else s[:n] + "...(truncated in audit; full raw evidence retained)"


class Ingestor:
    FLUSH_AT = 20000

    def __init__(self, registry, sites, store, run_id: str, as_of_ms: int):
        self.reg, self.sites, self.store, self.run_id, self.as_of_ms = registry, sites, store, run_id, as_of_ms
        self.known = {r[0] for r in store.q("SELECT delivery_hash FROM raw_deliveries")}
        self.identity = defaultdict(list)
        for ik, rid, ch in store.q("SELECT identity_key, raw_record_id, content_hash FROM raw_records "
                                   "WHERE status IN ('accepted','conflict_version')"):
            self.identity[ik].append((rid, ch))
        self.obs_buf, self.rec_buf, self.del_buf, self.event_buf = [], [], [], []
        self.cap_counts = Counter()
        self.routine = Counter()
        self.stats = Counter()
        self.affected = set()
        self.unit_seen = {}
        self.late_s = float(registry.default("late_arrival_s", 3600))
        self.future_s = float(registry.default("future_tolerance_s", 300))
        self.tol = float(registry.default("conflict_abs_tolerance", 1e-7))
        rv = registry.rule_version
        self.rv = {k: rv(k) for k in registry.data.get("rule_versions", {})}
        self.obs_cols = getattr(store, "obs_cols", OBS_COLS)
        self.env_keys = list(registry.default("envelope_keys", ["mock_transport"]))
        self.file_ctx: dict = {}   # per-file reader context: profile_override {envelope profile -> mapping profile}
        self._cur_ctx = None
        self._rec_state = {"bad": 0, "objs": []}

    # ================================================================== audit helpers
    def issue(self, stage, category, code, severity, where: dict, *, metric=None, original=None, output=None,
              reason=None, rule="quarantine", action=None, series_key=None) -> int:
        row = [self.run_id, stage, category, code, severity, where.get("provider"), where.get("site_key"),
               where.get("endpoint_key"), where.get("device_key"), metric, where.get("raw_record_id"),
               where.get("delivery_hash"), where.get("source_path"), where.get("source_line"),
               where.get("effective_time_ms"), rule, self.reg.rule_version(rule), where.get("mapping_version"),
               None if original is None else _short(original), output, reason, series_key]
        iid = self.store.insert_one("quality_issues", ISSUE_COLS, row)
        self.action(action or f"{category}:{code}", category, where, metric=metric, original=original, output=output,
                    reason=reason, rule=rule, issue_id=iid, series_key=series_key)
        self.stats[f"issue:{code}"] += 1
        return iid

    def action(self, action, category, where, *, metric=None, original=None, output=None, reason=None,
               rule="quarantine", issue_id=None, series_key=None):
        row = [self.run_id, "ingest", action, category, issue_id, where.get("raw_record_id"),
               where.get("delivery_hash"), where.get("provider"), where.get("site_key"), where.get("endpoint_key"),
               metric, rule, self.reg.rule_version(rule), where.get("mapping_version"),
               None if original is None else _short(original), output, reason, series_key]
        self.store.insert_one("audit_actions", ACTION_COLS, row)

    # ================================================================== entry points
    def process_file(self, path, rel_path: str, dataset: str):
        with open(path, "r", encoding="utf-8", newline="") as fh:
            for line_no, line in enumerate(fh, 1):
                line = line.rstrip("\n").rstrip("\r")
                if line.strip():
                    self.process_line(line, rel_path, line_no, dataset)

    def process_line(self, line: str, source_path: str, line_no: int, dataset: str):
        self.stats["deliveries_seen"] += 1
        dh = sha(line)
        if dh in self.known:
            self.stats["deliveries_skipped_known"] += 1
            return
        self.known.add(dh)
        self.stats["deliveries_new"] += 1
        d = dict(delivery_hash=dh, first_run_id=self.run_id, source_path=source_path, source_line=line_no,
                 dataset=dataset)
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            d.update(status="unparseable_line", status_class="parse_error",
                     status_detail=f"JSON decode error: {e.msg} at char {e.pos}", raw_text=line)
            self._save_delivery(d)
            self.issue("ingest", "quarantined", "unparseable_transport_line", "error", d, original=line,
                       output="quarantined; raw line preserved verbatim in raw_deliveries.raw_text",
                       reason=f"{e.msg} at char {e.pos}; no punctuation or value repair attempted",
                       action="quarantine_line")
            return
        self._envelope(obj, d, line)
        if len(self.obs_buf) >= self.FLUSH_AT:
            self.flush()

    # ================================================================== envelope level
    def _quarantine_delivery(self, d, code, reason, line, category="quarantined"):
        d.update(status="quarantined", status_class=code, status_detail=reason, raw_text=line)
        self._save_delivery(d)
        self.issue("ingest", category, code, "error", d, original=line, output="delivery quarantined; raw kept",
                   reason=reason, action="quarantine_delivery")

    def _envelope(self, obj, d, line):
        env = None
        if isinstance(obj, dict):
            for k in self.env_keys:
                if isinstance(obj.get(k), dict):
                    env = obj[k]
                    break
        if not isinstance(env, dict):
            return self._quarantine_delivery(d, "invalid_transport_envelope", "no transport envelope object", line)
        d["delivery_id"] = env.get("delivery_id")
        d["synthetic"] = 1 if env.get("synthetic") or self.sites.synthetic else 0
        pid = env.get("provider_profile_id")
        d.update(provider_profile_id=pid, endpoint_key=env.get("endpoint_key"),
                 request_scope=canon(env.get("request_scope")), http_status=env.get("http_status"))
        rec_t = parse_time(env.get("recorded_at_utc", MISSING), "iso_offset")
        recv_t = parse_time(env.get("received_at_utc", MISSING), "iso_offset")
        d["recorded_at_ms"], d["received_at_ms"] = to_ms(rec_t.utc), to_ms(recv_t.utc)
        override = (self.file_ctx.get("profile_override") or {}).get(pid)
        if override:
            accepted = (self.reg.profiles.get(override) or {}).get("accepts_envelope_profiles") or []
            if pid not in accepted:
                return self._quarantine_delivery(d, "profile_override_not_accepted",
                                                 f"mapping profile {override!r} does not declare that it accepts "
                                                 f"envelopes of {pid!r}", line, "schema_review")
            pid = override
            d["provider_profile_id"] = pid
        prof = self.reg.profiles.get(pid)
        if prof is None:
            return self._quarantine_delivery(d, "unregistered_provider_profile",
                                             f"profile {pid!r} is not in the registry", line, "schema_review")
        d["provider"] = prof["provider"]
        b = env.get("binding") if isinstance(env.get("binding"), dict) else {}
        if "asset_id" in b:
            lookup = getattr(self.sites, "lookup_asset", None)
            site, adev = lookup(b.get("asset_id")) if lookup else (None, None)
            if site is None:
                return self._quarantine_delivery(d, "unregistered_source_identity",
                                                 f"source asset {b.get('asset_id')!r} is not in the asset registry; "
                                                 f"no customer/site guessed", line)
            if adev.get("profile_id") and adev["profile_id"] != pid:
                return self._quarantine_delivery(d, "asset_profile_mismatch",
                                                 f"asset {b.get('asset_id')!r} is registered for profile "
                                                 f"{adev['profile_id']!r}, envelope says {pid!r}", line,
                                                 "schema_review")
            acc, sid = site["account_id"], site["site_id"]
        else:
            acc, _ = id_to_str(b.get("account_id"))
            sid, _ = id_to_str(b.get("site_id"))
            site = self.sites.lookup(prof["provider"], acc, sid)
        d.update(account_id=acc, site_id=sid)
        if site is None:
            return self._quarantine_delivery(d, "unregistered_binding",
                                             f"account/site binding ({acc!r}, {sid!r}) is not registered; "
                                             f"no name or fuzzy matching", line)
        d["site_key"] = site["site_key"]
        payload = MISSING
        if "payload" in obj:
            payload = obj["payload"]
        elif "payload_text" in obj:
            try:
                payload = json.loads(obj["payload_text"])
            except (json.JSONDecodeError, TypeError) as e:
                d.update(status="payload_parse_error", status_class="truncated_or_invalid_json",
                         status_detail=str(e), raw_text=line)
                self._save_delivery(d)
                self.issue("ingest", "quarantined", "truncated_or_invalid_json", "error", d,
                           original=obj.get("payload_text"),
                           output="delivery quarantined; body preserved verbatim",
                           reason=f"payload body is not valid JSON ({e}); punctuation/values not repaired",
                           action="quarantine_delivery")
                return
        ctx = {"envelope": env, "payload": payload, "site": site}
        ep, why = self.reg.route(pid, env.get("endpoint_key"), ctx)
        if ep is None:
            return self._quarantine_delivery(d, "unrouted_endpoint", why, line, "schema_review")
        d.update(variant=ep["variant"], mapping_version=ep["mapping_version"])
        http, terr = env.get("http_status"), env.get("transport_error")
        ok = not terr and (http == 200 or (http is None and env.get("transport_status") == "ok"))
        if not ok:
            tcfg = prof.get("transport") or {}
            classes = tcfg.get("http_status_classes") or {}
            eclasses = tcfg.get("error_classes") or {}
            if terr and str(terr) in eclasses:
                cls = eclasses[str(terr)]
            else:
                cls = ("timeout" if terr and "timeout" in str(terr).lower() else
                       classes.get(str(http), "transport_error" if terr else "http_error"))
            detail = env.get("error_body_text") or terr or ""
            s, e_ = self._window(ep, ctx, site, d)
            self._event(d, cls, http, str(http), False, s, e_, None, detail)
            d.update(status="transport_error", status_class=cls, status_detail=detail, raw_text=line)
            self._save_delivery(d)
            out = ("access_denied: no values recorded, no substitute zeros, no bypass attempted"
                   if cls == "access_denied" else "no values recorded from this attempt")
            self.issue("ingest", "access" if cls in ("access_denied", "auth_failed") else "transport",
                       f"http_{cls}", "warning", d, original=f"HTTP {http} {detail}".strip(), output=out,
                       reason=f"transport status classified as {cls} by profile", rule="transport_status",
                       action="record_transport_state")
            return
        if payload is MISSING:
            return self._quarantine_delivery(d, "missing_payload", "HTTP 200 without a payload body", line)
        fail = self._detect_failure(prof, ep, ctx)
        if fail:
            cls, code, msg, info = fail
            et = self._time_without_iteration(ep, ctx, site)
            self._event(d, cls, http, code, info, None, None, et, msg)
            d.update(status="provider_failure", status_class=cls, status_detail=f"code {code}: {msg}",
                     effective_time_ms=et, raw_text=line)
            self._save_delivery(d)
            if info:
                self.stats["documented_unavailable_responses"] += 1
            else:
                self.issue("ingest", "provider_failure", f"provider_failure_{cls}", "warning", d,
                           original=f"code {code}: {msg}",
                           output="no values recorded; NOT interpreted as healthy zero output",
                           reason="HTTP 200 carrying the profile's configured failure envelope",
                           rule="provider_failure_envelope", action="record_provider_failure")
            return
        er = ep.get("empty_response")
        if er and select(ctx, er["when_path_empty"]) in ({}, [], None):
            for ent in ep["entities"]:
                for f in ent["fields"]:
                    for m in self._field_metrics(f):
                        self.cap_counts[(site["site_key"], ep["endpoint_key"], "", m, f.get("channel") or "",
                                         er["state"], er.get("note", "empty response"), f["id"])] += 1
            s, e_ = self._window(ep, ctx, site, d)
            self._event(d, er["state"], http, "empty", True, s, e_, None, er.get("note", ""))
            d.update(status="empty_response", status_class=er["state"], n_records=0)
            self._save_delivery(d)
            self.stats["capability_state_responses"] += 1
            return
        d["payload_hash"] = sha(canon(payload))
        recs, problem = iterate(ep["records"].get("iterate", []), ctx)
        if problem and not recs:
            self.issue("ingest", "schema_review", "unexpected_structure", "warning", d,
                       original=problem, output="no records extracted", reason=problem, rule="schema_review")
        for idx, rctx in enumerate(recs):
            self._record(prof, ep, site, d, rctx, idx)
        d.update(status="parsed_ok", n_records=len(recs))
        if not recs:
            s, e_ = self._window(ep, ctx, site, d)
            self._event(d, "empty_window", http, "no_records", True, s, e_, None, "response contained no records")
        self._save_delivery(d)

    def _detect_failure(self, prof, ep, ctx):
        rules = ep.get("failure_detection", prof.get("failure_detection")) or []
        for r in rules:
            if condition(ctx, r["when"]):
                code = select(ctx, r["code_path"]) if r.get("code_path") else None
                msg = select(ctx, r["message_path"]) if r.get("message_path") else None
                cc = (r.get("code_classes") or {}).get(str(code))
                cls = cc["class"] if cc else r.get("default_class", "provider_failure")
                return cls, str(code), None if msg is MISSING else msg, bool(cc and cc.get("informational"))
        return None

    def _time_without_iteration(self, ep, ctx, site):
        aliases = {st["alias"] for st in ep["records"].get("iterate", [])}
        for t in ep["records"]["times"]:
            if t["path"].split(".")[0] in aliases:
                continue
            res = parse_time(select(ctx, t["path"]), t["format"], site.get("timezone"), t.get("pattern"))
            if res.status == "ok":
                return to_ms(res.utc)
        return None

    def _window(self, ep, ctx, site, d):
        rw = ep.get("request_window")
        if rw:
            a = parse_time(select(ctx, rw["start"]["path"]), rw["start"]["format"], site.get("timezone"),
                           rw["start"].get("pattern"))
            b = parse_time(select(ctx, rw["end"]["path"]), rw["end"]["format"], site.get("timezone"),
                           rw["end"].get("pattern"))
            if a.status == "ok" and b.status == "ok":
                return to_ms(a.utc), to_ms(b.utc)
        return d.get("recorded_at_ms"), d.get("recorded_at_ms")

    def _event(self, d, cls, http, code, info, start, end, et, detail):
        self.event_buf.append((d["delivery_hash"], d.get("site_key"), d.get("endpoint_key"), cls, http, code,
                               1 if info else 0, start, end, et, None if detail is None else str(detail)[:300]))

    def _save_delivery(self, d):
        self.del_buf.append(tuple(d.get(c) for c in DELIVERY_COLS))

    # ================================================================== record level
    def _mapping_version(self, ep, rctx):
        for mv in ep.get("mapping_versions") or []:
            if condition(rctx, mv["detect"]):
                return mv.get("aliases") or {}, mv["version"], mv.get("extra_known_keys") or []
        return {}, ep["mapping_version"], []

    def _unknown_keys(self, specs, extra, ctx, aliases):
        extra_by_path = defaultdict(set)
        for e in extra:
            extra_by_path[e["path"]].update(e["keys"])
        unknown = []
        for spec in specs:
            obj = select(ctx, spec["path"])
            if isinstance(obj, dict):
                allowed = set(spec["keys"]) | extra_by_path[spec["path"]]
                unknown += [f"{spec['path']}.{k}" for k in obj if k not in allowed]
        return unknown

    def _quarantine_record(self, row, code, reason, item_json):
        row.update(status="quarantined", status_reason=f"{code}: {reason}", record_json=item_json)
        self.rec_buf.append(tuple(row.get(c) for c in RECORD_COLS))
        self.issue("ingest", "quarantined", code, "error", row, original=item_json,
                   output="record quarantined; other records of the delivery continue", reason=reason,
                   action="quarantine_record")
        self.stats["records_quarantined"] += 1

    def _record(self, prof, ep, site, d, rctx, idx):
        self.stats["records_input"] += 1
        rec = ep["records"]
        skey = site["site_key"]
        steps = rec.get("iterate", [])
        item = rctx[steps[-1]["alias"]] if steps else rctx["payload"]
        item_json = canon(item)
        rid = sha(f"{d['delivery_hash']}#{idx}")[:24]
        aliases, mv, extra_known = self._mapping_version(ep, rctx)
        row = dict(raw_record_id=rid, delivery_hash=d["delivery_hash"], record_index=idx, run_id=self.run_id,
                   provider=prof["provider"], provider_profile_id=ep["_profile_id"],
                   profile_version=prof["profile_version"], endpoint_key=ep["endpoint_key"], variant=ep["variant"],
                   mapping_version=mv, account_id=d["account_id"], site_id=d["site_id"], site_key=skey,
                   entity_scope=rec.get("entity_scope"), source_path=d["source_path"],
                   source_line=d["source_line"], payload_hash=d.get("payload_hash"),
                   capture_time_ms=d.get("recorded_at_ms"), received_at_ms=d.get("received_at_ms"))
        # ---- identity
        dev, did, dkey = None, None, ""
        if rec.get("device_id"):
            p = rec["device_id"]["path"]
            raw = select(rctx, aliases.get(p, p))
            did, prob = id_to_str(None if raw is MISSING else raw)
            if did is None:
                return self._quarantine_record(row, "missing_required_identifier",
                                               f"device identifier at {p}: {prob}; no device invented", item_json)
            row["device_id"] = did
            dev = self.sites.device(skey, did)
            if dev is None:
                return self._quarantine_record(row, "unregistered_device",
                                               f"device {did!r} is not registered under {skey}; no fuzzy matching",
                                               item_json)
            dkey = device_key(skey, did)
            row["device_key"] = dkey
        rctx["device"] = dev or {}
        # ---- declared identity / boundary / model checks (registry values vs. what the source says)
        for chk in rec.get("identity_checks") or []:
            got = select(rctx, chk["path"])
            want = chk["equals"] if "equals" in chk else select(rctx, chk["ref"])
            if got is MISSING or want is MISSING or str(got) != str(want):
                return self._quarantine_record(
                    row, chk.get("code", "identity_check_failed"),
                    f"{chk['path']} = {_short(got, 40)} but the registry declares {chk.get('ref', 'value')} = "
                    f"{_short(want, 40)}; not guessed", item_json)
        for chk in rec.get("register_checks") or []:
            n = REGISTER_TYPES[chk["type"]][0]
            words, prob = gather_words(None if select(rctx, chk["source"]) is MISSING else select(rctx, chk["source"]),
                                       chk["address"], n)
            val = decode_words(words, chk["type"], chk.get("word_order", "high_word_first"))[0] if words else None
            if val != chk["equals"]:
                return self._quarantine_record(
                    row, chk.get("code", "model_identity_mismatch"),
                    f"register {chk['address']} decodes to {val!r} ({prob or 'ok'}); the profile requires "
                    f"{chk['equals']!r}", item_json)
        # ---- times
        tz = site.get("timezone")
        times, parsed = {}, {}
        for t in rec["times"]:
            raw = select(rctx, aliases.get(t["path"], t["path"]))
            res = parse_time(raw, t["format"], t.get("timezone") or tz, t.get("pattern"))
            parsed[t["role"]] = (t, raw, res)
            times[t["role"]] = {"raw": None if raw is MISSING else raw, "status": res.status,
                                "utc_ms": to_ms(res.utc), "is_measurement": bool(t.get("is_measurement"))}
            if t.get("required") and res.status != "ok":
                row["times_json"] = canon(times)
                return self._quarantine_record(row, f"unusable_time_{res.status}",
                                               f"{t['role']} at {t['path']} = {raw if raw is not MISSING else '<absent>'!r}: "
                                               f"{res.detail}; no timestamp invented", item_json)
        eff = None
        for role in rec.get("effective_time_roles") or [t["role"] for t in rec["times"]]:
            t, raw, res = parsed[role]
            if res.status == "ok":
                eff = (role, t, raw, res)
                break
        if eff is None:
            return self._quarantine_record(row, "no_usable_time", "no declared time role resolved", item_json)
        role, tspec, raw_t, res = eff
        eff_ms = to_ms(res.utc)
        meas_ms = next((to_ms(r.utc) for (t, _, r) in parsed.values() if t.get("is_measurement") and r.status == "ok"),
                       None)
        resp_ms = next((to_ms(r.utc) for (t, _, r) in parsed.values() if t.get("is_response") and r.status == "ok"),
                       None)
        flags = []
        lag_s = None
        if d.get("received_at_ms") is not None:
            lag_s = (d["received_at_ms"] - eff_ms) / 1000.0
            if lag_s > self.late_s:
                flags.append("late_arrival")
                self.stats["late_arrival_records"] += 1
        stale = False
        if ep.get("realtime") and ep.get("stale_after_s") and d.get("recorded_at_ms") is not None:
            if (d["recorded_at_ms"] - eff_ms) / 1000.0 > float(ep["stale_after_s"]):
                stale = True
                flags.append("stale_response")
        identity_key = f"{skey}|{ep['endpoint_key']}|{dkey}|{eff_ms}"
        content_hash = sha(item_json + "|" + (did or ""))
        row.update(source_time_raw=None if raw_t is MISSING else str(raw_t), source_time_role=role,
                   times_json=canon(times), measurement_time_ms=meas_ms, response_time_ms=resp_ms,
                   effective_time_ms=eff_ms, effective_time_basis=role, arrival_lag_s=lag_s,
                   identity_key=identity_key, content_hash=content_hash)
        if eff_ms > self.as_of_ms + self.future_s * 1000:
            flags.append("future_relative_to_replay_clock")
            self.issue("ingest", "unresolved", "future_timestamp", "warning", row, original=raw_t,
                       output="kept; flagged", reason="source time is later than the replay clock", rule="freshness")
        prior = self.identity.get(identity_key, [])
        dup_of = next((r for r, c in prior if c == content_hash), None)
        if dup_of:
            row.update(status="exact_duplicate", duplicate_of=dup_of, record_flags=",".join(flags), record_json=None)
            self.rec_buf.append(tuple(row.get(c) for c in RECORD_COLS))
            self.stats["records_exact_duplicate"] += 1
            self.issue("ingest", "defect_repaired", "exact_duplicate_suppressed", "info", row,
                       original=f"delivery {d.get('delivery_id')} line {d['source_line']}",
                       output=f"counted once (duplicate of raw record {dup_of})",
                       reason="same provider/account/site/device scope, source time and content hash",
                       rule="dedupe_exact", action="suppress_duplicate")
            if stale:
                self.issue("ingest", "unresolved", "stale_repeated_response", "warning", row,
                           original=f"response time {raw_t}, captured {d.get('recorded_at_ms')}",
                           output="feed marked stale for this capture; repeated content not re-counted",
                           reason=f"response time lags capture time by more than {ep['stale_after_s']} s",
                           rule="freshness", action="flag_stale")
            return
        status = "conflict_version" if prior else "accepted"
        row.update(status=status, record_flags=",".join(flags), record_json=item_json)
        self.rec_buf.append(tuple(row.get(c) for c in RECORD_COLS))
        self.identity[identity_key].append((rid, content_hash))
        self.stats["records_accepted" if status == "accepted" else "records_conflict_version"] += 1
        if stale:
            self.issue("ingest", "unresolved", "stale_response", "warning", row, original=raw_t,
                       output="values kept with availability=stale",
                       reason=f"response time lags capture time by more than {ep['stale_after_s']} s",
                       rule="freshness", action="flag_stale")
        if mv != ep["mapping_version"]:
            self.action("registered_mapping_version_applied", "deterministic_transformation", row,
                        original=f"base {ep['mapping_version']}", output=f"applied {mv}",
                        reason="record matched a registered mapping-version detector", rule="mapping_version_select")
            self.stats["mapping_version_applied"] += 1
        unknown = self._unknown_keys(rec.get("known_keys", []), extra_known, rctx, aliases)
        origin = "simulated_observation" if d.get("synthetic") else "observation"
        obs = []
        base = dict(raw_record_id=rid, site_key=skey, endpoint_key=ep["endpoint_key"], effective_time_ms=eff_ms,
                    family=prof.get("family"), profile_version=prof["profile_version"],
                    scenario_version=getattr(self.sites, "scenario_version", None))
        iv = rec.get("interval")
        if iv:
            dur = int(float(iv["duration_s"]) * 1000)
            if iv.get("time_marks", "end") == "end":
                base.update(interval_start_ms=eff_ms - dur, interval_end_ms=eff_ms)
            else:
                base.update(interval_start_ms=eff_ms, interval_end_ms=eff_ms + dur)
        for w in rec.get("withhold_if") or []:
            if condition(rctx, w["when"]):
                base["_withhold"] = w["flag"]
                self.issue("ingest", "unresolved", w["flag"], "warning", row,
                           original=f"{w['when']['path']} {w['when']['op']} {w['when'].get('value')!r}",
                           output="record values kept as evidence but availability=withheld",
                           reason=w.get("reason", "source marks these values as not usable"), rule="quality_gate",
                           action="withhold_values")
                break
        self._rec_state = {"bad": 0, "objs": []}
        numeric_cfg = prof.get("numeric") or {}
        for ent in ep["entities"]:
            ectxs, _ = iterate(ent.get("iterate", []), rctx)
            for ectx in ectxs:
                edev, edid, edkey = dev, did, dkey
                if ent.get("device_id"):
                    raw = select(ectx, ent["device_id"]["path"])
                    edid, prob = id_to_str(None if raw is MISSING else raw)
                    edev = self.sites.device(skey, edid) if edid else None
                    if edev is None:
                        self.issue("ingest", "quarantined", "unresolved_entity_identifier", "error", row,
                                   original=raw, output=f"{ent['scope']} entity skipped; rest of record kept",
                                   reason=prob or f"device {edid!r} not registered under {skey}")
                        continue
                    edkey = device_key(skey, edid)
                elif ent["scope"] == "site":
                    edev, edid, edkey = None, None, ""
                ectx["device"] = edev or {}
                unknown += self._unknown_keys(ent.get("known_keys", []), extra_known, ectx, aliases)
                ob = dict(base, device_id=edid, device_key=edkey, entity_scope=ent["scope"],
                          physical_asset_id=(edev or {}).get("asset_id") or edid,
                          source_role=(edev or {}).get("source_role"))
                for f in ent["fields"]:
                    self._map_field(f, ectx, ob, prof, ep, aliases, stale, origin, site, row, numeric_cfg, obs)
        thr = rec.get("decode_suspect_threshold")
        if thr and self._rec_state["bad"] >= int(thr):
            for o in self._rec_state["objs"]:
                if o["availability_status"] in ("available", "stale", "withheld"):
                    o.update(availability_status="invalid", canonical_value=None, exact_value_text=None)
                o["quality_flags"] = ",".join(filter(None, [o["quality_flags"], "decode_configuration_suspect"]))
            self.issue("ingest", "unresolved", "register_decode_configuration_suspect", "warning", row,
                       original=f"{self._rec_state['bad']} decoded register fields failed validation in one snapshot",
                       output="all register-decoded values of this snapshot invalid; raw words preserved; "
                              "NOT re-decoded with another word order or unit",
                       reason="several implausible decodes in the same response point to a word-order/unit "
                              "configuration or capture problem; flagged for configuration review",
                       rule="register_decode", action="flag_decode_configuration")
        if unknown:
            self.issue("ingest", "schema_review", "unknown_field", "warning", row, original=", ".join(unknown),
                       output="sent to review; not mapped automatically",
                       reason=f"field(s) not registered for mapping version {mv}", rule="schema_review",
                       action="route_to_schema_review")
        if status == "conflict_version":
            self._resolve_conflict(prior, obs, row)
        self.obs_buf.extend(obs)
        self.affected.add((skey, ep["endpoint_key"]))
        self.stats["observations_added"] += len(obs)

    # ================================================================== field level
    @staticmethod
    def _field_metrics(f):
        tr = f.get("transform", "numeric")
        if tr == "sign_split":
            return [f["sign_split"]["positive"], f["sign_split"]["negative"]]
        if tr == "edge_flow":
            return [o["metric"] for o in f["outputs"]]
        return [f["metric"]]

    def _cap(self, ob, metric, f, state, reason):
        self.cap_counts[(ob["site_key"], ob["endpoint_key"], ob.get("device_key") or "", metric,
                         f.get("channel") or "", state, reason, f["id"])] += 1

    def _emit(self, out, ob, f, metric, *, raw, unit, cv=None, ctext=None, avail="available", flags=(), log=(),
              origin="simulated_observation", boundary=None, stale=False, exact_text=None, state_label=None,
              ctx=None):
        md = self.reg.metrics[metric]
        if stale and avail == "available":
            avail = "stale"
            flags = list(flags) + ["stale_response"]
        if ob.get("_withhold") and avail in ("available", "stale"):
            avail = "withheld"
            flags = list(flags) + [ob["_withhold"]]
        o = dict(ob)
        o.update(channel=f.get("channel"), metric_name=metric,
                 original_value=None if raw is MISSING else canon(raw), original_unit=unit,
                 canonical_value=cv, canonical_text=ctext, canonical_unit=md["unit"], metric_kind=md["kind"],
                 boundary=boundary or f.get("boundary"), value_origin=origin, availability_status=avail,
                 quality_flags=",".join(flags) or None, assumption_basis=f.get("assumption_basis", "documented"),
                 requirement_class=f.get("requirement", "optional"), transform_log=";".join(log) or None,
                 field_rule_id=f["id"], is_conflicted=0, exact_value_text=exact_text, state_label=state_label,
                 sensor_position=f.get("sensor_position"), phase=f.get("phase"),
                 aggregation=self._aggregation(f, ctx if ctx is not None else self._cur_ctx),
                 mounting=self._mounting(f, ctx if ctx is not None else self._cur_ctx))
        out.append(o)
        self.stats[f"avail:{avail}"] += 1
        return o

    @staticmethod
    def _aggregation(f, ctx):
        if f.get("processing_from") and ctx is not None:
            p = select(ctx, f["processing_from"])
            return (f.get("processing_map") or {}).get(p if isinstance(p, str) else "", f.get("aggregation"))
        return f.get("aggregation")

    @staticmethod
    def _mounting(f, ctx):
        if f.get("mounting") != "from_asset_registry":
            return f.get("mounting")
        dev = (ctx or {}).get("device") or {}
        m = dev.get("mounting")
        return (m.get("plane") if isinstance(m, dict) else m) or "unknown"

    def _bounds(self, metric, cv, ctx):
        b = self.reg.metrics[metric].get("bounds")
        if not b or cv is None:
            return None
        lo, hi, ref = b.get("min"), b.get("max"), None
        if b.get("max_ref"):
            ref = resolve_ref(ctx, b["max_ref"])
            hi = ref * float(b.get("max_factor", 1.0)) if ref is not None else None
        if b.get("abs_max_ref"):
            ref = resolve_ref(ctx, b["abs_max_ref"])
            if ref is not None:
                hi = ref * float(b.get("max_factor", 1.0))
                lo = -hi
                if abs(cv) > hi:
                    return (b.get("on_exceed", "out_of_range"),
                            f"|value| exceeds plausible bound {hi:g} (= {ref:g} x {b.get('max_factor', 1.0)})")
        if lo is not None and cv < lo:
            return "out_of_range", f"below minimum {lo}"
        if hi is not None and cv > hi:
            how = b.get("on_exceed", "out_of_range")
            if ref is not None:
                return how, f"exceeds plausible bound {hi:g} (= {ref:g} x {b.get('max_factor', 1.0)})"
            return how, f"above maximum {hi:g}"
        return None

    def _finish_numeric(self, out, ob, f, metric, v, unit, raw, log, flags, ctx, origin, stale, where, boundary=None,
                        exact=None):
        md = self.reg.metrics[metric]
        u = unit or md["unit"]
        cv, err = convert_unit(v, u, md["unit"], self.reg.units)
        exact_text = None
        if cv is not None:
            if exact is not None:  # integer source: exact decimal conversion, float only as the derived view
                ex = exact_convert(exact, u, self.reg.units)
                exact_text = decimal_text(ex)
                cv = float(ex)
            else:
                cv = round(cv, 9)  # remove binary floating-point residue of unit scaling (e.g. 700 W -> 0.7 kW)
        if err:
            self.issue("ingest", "unresolved", "unsupported_unit", "warning", where, metric=metric, original=raw,
                       output="invalid", reason=err, rule="unit_conversion")
            return self._emit(out, ob, f, metric, raw=raw, unit=u, avail="invalid", flags=flags + ["unsupported_unit"],
                              log=log, origin=origin, boundary=boundary, ctx=ctx)
        if self.reg.units[u]["factor"] != 1.0:
            log = log + [f"unit:{u}->{md['unit']}"]
            self.routine[(where["provider"], where["endpoint_key"], "unit_scale", f"{u}->{md['unit']}")] += 1
        bad = self._bounds(metric, cv, ctx)
        if bad:
            how, why = bad
            if how == "implausible_magnitude":
                self.issue("ingest", "unresolved", "implausible_magnitude_unit_ambiguity", "warning", where,
                           metric=metric, original=f"{raw} {u}",
                           output="value withheld (invalid); original preserved; NOT rescaled",
                           reason=f"canonical {cv:g} {md['unit']} {why}; no trustworthy unit-change evidence, "
                                  f"so dividing by 1000 would be a guess", rule="bounds", action="flag_unit_ambiguity")
                return self._emit(out, ob, f, metric, raw=raw, unit=u, avail="invalid",
                                  flags=flags + ["unit_ambiguity_suspected"], log=log, origin=origin, boundary=boundary,
                                  ctx=ctx)
            self.issue("ingest", "unresolved", "value_out_of_range", "warning", where, metric=metric,
                       original=f"{_short(raw, 120)} {u}", output="invalid; original preserved; never clamped",
                       reason=f"canonical {cv:g} {md['unit']} {why}", rule="bounds", action="flag_out_of_range")
            return self._emit(out, ob, f, metric, raw=raw, unit=u, avail="invalid", flags=flags + ["out_of_range"],
                              log=log, origin=origin, boundary=boundary, ctx=ctx)
        return self._emit(out, ob, f, metric, raw=raw, unit=u, cv=cv, flags=flags, log=log, origin=origin,
                          boundary=boundary, stale=stale, exact_text=exact_text, ctx=ctx)

    # ------------------------------------------------------------------ configured sign convention
    def _sign(self, f, ctx, where, metric):
        """Return (multiplier | None, log). 'sign_convention: negate' converts a documented opposite native
        convention; 'sign_from' takes the sign from DECLARED installation configuration (e.g. CT orientation).
        Nothing is ever auto-flipped from the value itself."""
        if f.get("sign_convention") == "negate":
            return -1, ["sign:documented_native_convention_negated"]
        sf = f.get("sign_from")
        if not sf:
            return 1, []
        v = select(ctx, sf["path"])
        m = (sf.get("map") or {}).get(str(v)) if v is not MISSING else None
        if m not in (1, -1):
            self.issue("ingest", "unresolved", "sign_configuration_missing", "warning", where, metric=metric,
                       original=f"{sf['path']} = {_short(v, 40)}", output="invalid; sign not guessed",
                       reason="the registry does not declare a usable orientation for this channel",
                       rule="sign_convention")
            return None, []
        return m, ([f"sign:configured_{v}"] if m == -1 else [f"sign:configured_{v}_unchanged"])

    # ------------------------------------------------------------------ captured register words
    def _register_field(self, f, ctx, ob, origin, stale, where, out):
        metric = f["metric"]
        spec = f["register"]
        rtype, order = spec["type"], spec.get("word_order", "high_word_first")
        n = REGISTER_TYPES[rtype][0]
        blocks = select(ctx, f["source"])
        words, prob = gather_words(None if blocks is MISSING else blocks, spec["address"], n)
        raw = {"register": spec.get("number"), "address": spec["address"], "type": rtype, "word_order": order,
               "words": words}
        unit = f.get("unit")
        st = self._rec_state

        def bad(code, flag, reason, avail="invalid"):
            if avail == "invalid":
                st["bad"] += 1
            self.issue("ingest", "unresolved" if avail == "invalid" else "informational", code,
                       "warning" if avail == "invalid" else "info", where, metric=metric, original=raw,
                       output=f"availability={avail}; raw words preserved; not repaired", reason=reason,
                       rule="register_decode", action="flag_register_value")
            o = self._emit(out, ob, f, metric, raw=raw, unit=unit, avail=avail, flags=[flag], origin=origin, ctx=ctx)
            st["objs"].append(o)

        if words is None:
            return bad("register_not_captured", "register_not_captured", prob, avail="missing")
        val, rawint, status, note = decode_words(words, rtype, order)
        if val is None:
            return bad("register_decode_invalid", status, note)
        raw["decoded"] = str(val) if isinstance(val, int) else repr(val)
        if rawint in (f.get("invalid_sentinels") or []):
            return bad("register_invalid_sentinel", "invalid_sentinel",
                       f"raw 0x{rawint:X} is a configured invalid sentinel for this register")
        vb = f.get("invalid_if_bits")
        if vb:
            bw, _ = gather_words(blocks, vb["address"], 1)
            flags_word = bw[0] if bw else None
            hit = [b for b in vb["bits"] if flags_word is not None and flags_word >> b & 1]
            if flags_word is None or hit:
                return bad("source_status_invalid", "source_status_invalid",
                           f"status register {vb['address']} = {flags_word!r}; validity bits {hit} set "
                           f"(documented status flags)" if flags_word is not None else "status register not captured")
        md = self.reg.metrics[metric]
        if md["kind"] == "state":
            text = str(val)
            label = (f.get("enum") or {}).get(text)
            o = self._emit(out, ob, f, metric, raw=raw, unit="none", cv=float(val), ctext=text, state_label=label,
                           log=[f"register:{rtype}@{spec['address']}"] + ([f"enum:{label}"] if label else
                                                                          ["raw_state_preserved"]),
                           origin=origin, stale=stale, ctx=ctx)
            st["objs"].append(o)
            return
        scale = Decimal(str(f.get("scale", 1)))
        log = [f"register:{rtype}@{spec['address']}:{order}"]
        sr = f.get("scale_register")
        if sr:
            sw, _ = gather_words(blocks, sr["address"], 1)
            sf = decode_words(sw, sr.get("type", "int16"), "high_word_first")[0] if sw else None
            raw["scale_factor"] = sf
            if sf is None or sf not in sr.get("allowed", [sf]):
                return bad("scale_factor_invalid", "scale_factor_invalid",
                           f"scale-factor register {sr['address']} = {sf!r} is not an allowed value; "
                           f"value not decoded by guessing")
            scale = scale * scale_from_register(sf, sr.get("mode", "pow10"))
            log.append(f"scale_register:{sf}")
        if scale != 1:
            log.append(f"scale:{decimal_text(scale)}")
        offset = Decimal(str(f.get("offset", 0)))
        if isinstance(val, int):
            exact = Decimal(val) * scale + offset
            num = float(exact)
        else:
            exact = None
            num = val * float(scale) + float(offset)
        sign, slog = self._sign(f, ctx, where, metric)
        if sign is None:
            o = self._emit(out, ob, f, metric, raw=raw, unit=unit, avail="invalid",
                           flags=["sign_configuration_missing"], origin=origin, ctx=ctx)
            st["objs"].append(o)
            return
        if sign == -1:
            num = -num
            exact = -exact if exact is not None else None
        o = self._finish_numeric(out, ob, f, metric, num, unit, raw, log + slog, [], ctx, origin, stale, where,
                                 exact=exact)
        if o["availability_status"] == "invalid":
            st["bad"] += 1
        st["objs"].append(o)

    def _track_unit(self, where, f, unit, raw):
        key = (where["site_key"], f["id"])
        prev = self.unit_seen.get(key)
        if prev is not None and prev != unit:
            self.action("declared_unit_change_converted", "deterministic_transformation", where,
                        original=f"declared unit {prev} -> {unit} (value {_short(raw, 60)})",
                        output=f"converted using declared unit {unit}",
                        reason="explicit unit metadata in the payload changed; supported unit", rule="unit_conversion")
            self.stats["declared_unit_changes"] += 1
        self.unit_seen[key] = unit

    def _map_field(self, f, ctx, ob, prof, ep, aliases, stale, origin, site, where, numeric_cfg, out):
        tr = f.get("transform", "numeric")
        metrics = self._field_metrics(f)
        if f.get("applies_if") and not condition(ctx, f["applies_if"]):
            for m in metrics:
                self._cap(ob, m, f, "not_installed", "not applicable to this device (applies_if)")
            return
        caps = site.get("capabilities") or {}
        dcaps = (ctx.get("device") or {}).get("capabilities")
        if isinstance(dcaps, dict) and dcaps:  # asset-level capability declarations refine the site's
            caps = {**caps, **dcaps}
        self._cur_ctx = ctx
        if f.get("capability") == "unsupported_on_model":
            for m in metrics:
                self._cap(ob, m, f, "unsupported", f.get("reason", "documented: not supported by this model"))
            return
        if tr == "edge_flow":
            return self._edge_flow(f, ctx, ob, caps, origin, stale, where, out)
        if tr == "register_words":
            return self._register_field(f, ctx, ob, origin, stale, where, out)
        path = aliases.get(f["source"], f["source"])
        raw = select(ctx, path)
        cstate = caps.get(f["requires_capability"]) if f.get("requires_capability") else None
        if cstate in ("not_installed", "unsupported"):
            if raw is MISSING and f.get("presence") in ("required", "required_nullable"):
                self.issue("ingest", "schema_damage", "required_key_missing", "warning", where,
                           metric=",".join(metrics), original=f"<{path} absent>",
                           output=f"no value expected (capability {cstate}); schema damage recorded",
                           reason="a key the pinned response version declares required is absent even though its "
                                  "value would be null on this site", rule="schema_review",
                           action="flag_schema_damage")
            for m in metrics:
                self._cap(ob, m, f, cstate, f"site capability {f['requires_capability']}={cstate}")
            return
        if f.get("model_behaviour") == "always_null" and (raw is None or raw is MISSING):
            for m in metrics:
                self._cap(ob, m, f, "unsupported", "documented model behaviour: field is null on this model family")
            return
        unit = f.get("unit")
        value = raw
        flags, log = [], []
        if tr == "value_object":
            keys = prof.get("value_object_keys") or {}
            if isinstance(raw, dict):
                value = raw.get(keys.get("value", "value"), MISSING)
                unit = raw.get(keys.get("unit", "unit"))
                if unit not in (f.get("allowed_units") or []):
                    self.issue("ingest", "unresolved", "unsupported_unit", "warning", where, metric=metrics[0],
                               original=raw, output="invalid", reason=f"declared unit {unit!r} not supported for "
                               f"this field", rule="unit_conversion")
                    for m in metrics:
                        self._emit(out, ob, f, m, raw=raw, unit=str(unit), avail="invalid", flags=["unsupported_unit"],
                                   origin=origin)
                    return
                self._track_unit(where, f, unit, value)
            elif raw is not MISSING and raw is not None:
                self.issue("ingest", "unresolved", "invalid_field_type", "warning", where, metric=metrics[0],
                           original=raw, output="invalid", reason="expected a value object", rule="numeric_parse")
                for m in metrics:
                    self._emit(out, ob, f, m, raw=raw, unit=unit, avail="invalid", flags=["invalid_type"], origin=origin)
                return
        elif f.get("unit_from"):
            unit = select(ctx, f["unit_from"])
            if unit not in (f.get("allowed_units") or []):
                for m in metrics:
                    self._emit(out, ob, f, m, raw=raw, unit=None if unit is MISSING else str(unit), avail="invalid",
                               flags=["unsupported_unit"], origin=origin)
                return
            self._track_unit(where, f, unit, raw)
        pres = f.get("presence", "optional")
        if value is MISSING and f.get("absence") == "normal":
            return  # documented: the key is present only when non-empty (e.g. an error list); absence = none reported
        if value is MISSING:
            if pres in ("required", "required_nullable"):
                self.issue("ingest", "schema_damage", "required_key_missing", "warning", where, metric=",".join(metrics),
                           original=f"<{path} absent>", output="availability=missing for this field only",
                           reason="a key the pinned response version declares required is absent: schema damage; "
                                  "other fields of the record are retained", rule="schema_review",
                           action="flag_schema_damage")
                fl = ["required_key_missing"]
            else:
                self.issue("ingest", "informational", "optional_field_absent", "info", where, metric=",".join(metrics),
                           original=f"<{path} absent>", output="availability=missing (null preserved)",
                           reason="optional field absent; other metrics remain valid", rule="capability",
                           action="preserve_absence")
                fl = ["optional_field_absent"]
            for m in metrics:
                self._emit(out, ob, f, m, raw=MISSING, unit=unit, avail="missing", flags=fl, origin=origin)
            return
        if value is None:
            if pres == "required":
                self.issue("ingest", "unresolved", "required_value_null", "warning", where, metric=",".join(metrics),
                           original=None, output="invalid", reason="required non-null value is null", rule="schema_review")
                for m in metrics:
                    self._emit(out, ob, f, m, raw=None, unit=unit, avail="invalid", flags=["required_value_null"],
                               origin=origin)
                return
            fl = ["vendor_permitted_null"] if pres == "required_nullable" else ["null_value"]
            for m in metrics:
                self._emit(out, ob, f, m, raw=None, unit=unit, avail="missing", flags=fl, origin=origin)
            return
        if tr == "state":
            text = value if isinstance(value, str) else canon(value)
            label = (f.get("status_map") or {}).get(text)
            log = [f"status_map:{label}"] if label else ["raw_state_preserved"]
            self._emit(out, ob, f, metrics[0], raw=value, unit="none", ctext=text, log=log, origin=origin, stale=stale,
                       state_label=label if f.get("label_in_state_column") else None)
            return
        if isinstance(value, str) and value in ((f.get("numeric") or numeric_cfg).get("missing_tokens") or []):
            self.issue("ingest", "informational", "source_missing_token", "info", where, metric=",".join(metrics),
                       original=value, output="availability=missing; never replaced by another sensor",
                       reason="configured missing-value token", rule="capability", action="preserve_absence")
            for m in metrics:
                self._emit(out, ob, f, m, raw=value, unit=unit, avail="missing", flags=["source_missing_token"],
                           origin=origin)
            return
        num, st, note = parse_number(value, f.get("numeric") or numeric_cfg)
        if num is None:
            code = "ambiguous_number" if st == "ambiguous_number" else "invalid_field_type"
            self.issue("ingest", "unresolved", code, "warning", where, metric=",".join(metrics), original=value,
                       output="invalid; not guessed", reason=note, rule="numeric_parse", action="flag_invalid_value")
            for m in metrics:
                self._emit(out, ob, f, m, raw=value, unit=unit, avail="invalid", flags=[st], origin=origin)
            return
        if st == "numeric_string_parsed":
            flags.append("numeric_string_parsed")
            log.append("numeric_string")
            self.action("numeric_string_parsed", "deterministic_transformation", where, metric=",".join(metrics),
                        original=value, output=f"{num:g}", reason=note, rule="numeric_parse")
            self.stats["numeric_strings_parsed"] += 1
        es = f.get("expect_sign")
        if (es == "nonpositive" and num > 0) or (es == "nonnegative" and num < 0):
            self.issue("ingest", "unresolved", "unexpected_sign", "warning", where, metric=",".join(metrics),
                       original=value, output="invalid", reason=f"profile documents {es} values for this field",
                       rule="sign_split")
            for m in metrics:
                self._emit(out, ob, f, m, raw=value, unit=unit, avail="invalid", flags=["unexpected_sign"],
                           origin=origin)
            return
        if f.get("sign_from") or f.get("sign_convention"):
            mult, slog = self._sign(f, ctx, where, ",".join(metrics))
            if mult is None:
                for m in metrics:
                    self._emit(out, ob, f, m, raw=value, unit=unit, avail="invalid",
                               flags=["sign_configuration_missing"], origin=origin)
                return
            num = num * mult
            log = log + slog
        if tr == "sign_split":
            pos, neg = f["sign_split"]["positive"], f["sign_split"]["negative"]
            self.routine[(where["provider"], where["endpoint_key"], "sign_split", f["id"])] += 1
            pairs = [(pos, max(num, 0.0)), (neg, max(-num, 0.0))]
            log = log + ["sign_split"]
        elif tr == "negate":
            self.routine[(where["provider"], where["endpoint_key"], "negate", f["id"])] += 1
            pairs = [(metrics[0], -num)]
            log = log + ["negate"]
        else:
            pairs = [(metrics[0], num)]
        for m, v in pairs:
            self._finish_numeric(out, ob, f, m, v, unit, value, log, flags, ctx, origin, stale, where)

    def _edge_flow(self, f, ctx, ob, caps, origin, stale, where, out):
        root = select(ctx, f["source"])
        unit = select(ctx, f["unit_from"]) if f.get("unit_from") else f.get("unit")
        conns = select(ctx, f["connections_path"]) if f.get("connections_path") else None
        ek = f.get("edge_keys") or {}
        edges, prob = edge_set(None if conns is MISSING else conns, ek.get("from", "from"), ek.get("to", "to"),
                               f.get("node_case_insensitive", True))
        if prob:
            self.issue("ingest", "unresolved", "malformed_connections", "warning", where, original=conns,
                       output="direction only from well-formed edges", reason=prob, rule="edge_flow")
        tracked = False
        for oc in f["outputs"]:
            m = oc["metric"]
            cstate = caps.get(oc["requires_capability"]) if oc.get("requires_capability") else None
            if cstate in ("not_installed", "unsupported"):
                self._cap(ob, m, f, cstate, f"site capability {oc['requires_capability']}={cstate}")
                continue
            if not isinstance(root, dict):
                self._emit(out, ob, f, m, raw=root, unit=None, avail="missing", flags=["required_key_missing"],
                           origin=origin, boundary=oc.get("boundary"))
                continue
            if unit not in (f.get("allowed_units") or []):
                self._emit(out, ob, f, m, raw=unit, unit=None if unit is MISSING else str(unit), avail="invalid",
                           flags=["unsupported_unit"], origin=origin, boundary=oc.get("boundary"))
                continue
            if not tracked:
                self._track_unit(where, f, unit, f"unit field = {unit}")
                tracked = True
            node = root.get(oc["node"], MISSING)
            if not isinstance(node, dict):
                self._emit(out, ob, f, m, raw=MISSING, unit=unit, avail="missing", flags=["flow_node_absent"],
                           origin=origin, boundary=oc.get("boundary"))
                continue
            mraw = node.get(f.get("magnitude_key", "value"), MISSING)
            mag, st, note = parse_number(mraw, {}) if mraw is not MISSING else (None, "missing", "magnitude absent")
            raw_desc = {"node": oc["node"], "magnitude": None if mraw is MISSING else mraw,
                        "edges": sorted("->".join(e) for e in edges)}
            if mag is None or mag < 0:
                why = note if mag is None else "negative magnitude; the profile documents nonnegative magnitudes"
                self.issue("ingest", "unresolved", "invalid_flow_magnitude", "warning", where, metric=m,
                           original=raw_desc, output="invalid", reason=why, rule="edge_flow")
                self._emit(out, ob, f, m, raw=raw_desc, unit=unit, avail="invalid", flags=["invalid_magnitude"],
                           origin=origin, boundary=oc.get("boundary"))
                continue
            val, how = edge_flow_value(mag, edges, oc)
            if val is None:
                self.issue("ingest", "unresolved", "flow_direction_unresolved", "warning", where, metric=m,
                           original=raw_desc, output="invalid; magnitude not treated as signed",
                           reason="nonzero magnitude without a direction-establishing connection", rule="edge_flow")
                self._emit(out, ob, f, m, raw=raw_desc, unit=unit, avail="invalid", flags=["direction_unresolved"],
                           origin=origin, boundary=oc.get("boundary"))
                continue
            self.routine[(where["provider"], where["endpoint_key"], "edge_flow", how)] += 1
            fl = ["zero_magnitude_no_edge"] if how == "zero_magnitude_no_edge" else []
            self._finish_numeric(out, ob, f, m, val, unit, raw_desc, [f"edge_flow:{how}"], fl, ctx, origin, stale,
                                 where, boundary=oc.get("boundary"))

    # ================================================================== conflicts
    def _resolve_conflict(self, prior, obs, row):
        self.flush()
        ids = [rid for rid, _ in prior]
        q = (f"SELECT obs_id, metric_name, channel, device_key, canonical_value, canonical_text FROM observations "
             f"WHERE raw_record_id IN ({','.join('?' * len(ids))})")
        idx = {}
        for oid, m, ch, dk, cv, ct in self.store.q(q, ids):
            idx.setdefault((m, ch, dk), []).append((oid, cv, ct))
        differing = 0
        for o in obs:
            for oid, cv, ct in idx.get((o["metric_name"], o["channel"], o["device_key"]), []):
                same = (ct == o["canonical_text"] and
                        ((cv is None and o["canonical_value"] is None) or
                         (cv is not None and o["canonical_value"] is not None and abs(cv - o["canonical_value"]) <= self.tol)))
                if not same:
                    differing += 1
                    o["is_conflicted"] = 1
                    o["quality_flags"] = ",".join(filter(None, [o["quality_flags"], "conflict_unresolved"]))
                    self.store.con.execute(
                        "UPDATE observations SET is_conflicted=1, quality_flags=COALESCE(quality_flags||',','')||"
                        "'conflict_unresolved' WHERE obs_id=? AND is_conflicted=0", (oid,))
                    self.issue("ingest", "unresolved", "conflicting_versions", "warning", row, metric=o["metric_name"],
                               original=f"earlier={cv if ct is None else ct} new={o['canonical_value'] if o['canonical_text'] is None else o['canonical_text']}",
                               output="both versions preserved; excluded from frames/counters until reviewed",
                               reason="same scoped identity and source time but different values; no version chosen",
                               rule="conflict_preserve", action="preserve_conflicting_versions")
        if not differing:
            self.issue("ingest", "informational", "conflict_without_metric_difference", "info", row,
                       output="new version stored", reason="content differs only in unmapped fields",
                       rule="conflict_preserve")

    # ================================================================== persistence
    def flush(self):
        st = self.store
        st.insert_many("raw_deliveries", DELIVERY_COLS, self.del_buf, "INSERT OR IGNORE")
        st.insert_many("raw_records", RECORD_COLS, self.rec_buf, "INSERT OR IGNORE")
        st.insert_many("observations", self.obs_cols, [tuple(o.get(c) for c in self.obs_cols) for o in self.obs_buf])
        st.insert_many("delivery_events", ["delivery_hash", "site_key", "endpoint_key", "status_class", "http_status",
                                           "code", "informational", "start_ms", "end_ms", "event_time_ms", "detail"],
                       self.event_buf, "INSERT OR IGNORE")
        self.del_buf, self.rec_buf, self.obs_buf, self.event_buf = [], [], [], []

    def finalize(self):
        self.flush()
        for (sk, ek, dk, m, ch, state, reason, fid), n in self.cap_counts.items():
            self.store.con.execute(
                "INSERT INTO capability_states VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(site_key, endpoint_key, "
                "device_key, metric_name, channel, state, reason) DO UPDATE SET n_records=n_records+excluded.n_records",
                (sk, ek, dk, m, ch, state, reason, fid, n))
        for (prov, ek, tr, detail), n in self.routine.items():
            self.store.con.execute(
                "INSERT INTO routine_transform_counts VALUES(?,?,?,?,?,?) ON CONFLICT DO UPDATE SET n=n+excluded.n",
                (self.run_id, prov, ek, tr, detail, n))
        self.cap_counts.clear()
        self.routine.clear()
        self.store.commit()
