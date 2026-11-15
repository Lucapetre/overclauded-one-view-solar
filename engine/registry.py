"""Load, merge and validate the declarative provider registry. Rejects anything outside the schema."""
from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from .selectors import CONDITION_OPS, compile_path, condition
from .timeparse import TIME_FORMATS, zone
from .transforms import DERIVE_METHODS, REGISTER_TYPES, SCALE_MODES, TRANSFORMS, WORD_ORDERS

PRESENCE = {"required", "required_nullable", "optional"}
REQUIREMENT = {"integration_required", "vendor_response_required", "optional"}
ITER_KINDS = {"list", "map"}
COUNTERS = {"lifetime", "daily", "lifetime_nonresettable", "resettable"}
INPUT_FORMATS = {"ndjson_envelope", "header_csv"}
FAMILIES = {"meter", "battery", "weather"}
AGGREGATIONS = {"instantaneous", "interval_average", "interval_min", "interval_max", "interval_energy",
                "cumulative_counter_lifetime", "cumulative_counter_resettable", "last_valid_instantaneous", "state"}

# Strict key allowlists. They apply to every profile that declares a component `family` (new profiles); the
# original provider profiles keep their established schema. Unknown keys are rejected, never ignored.
COMPONENT_PROFILE_KEYS = {"provider", "family", "display_name", "profile_version", "evidence_ref", "evidence",
                          "provenance", "numeric", "transport", "failure_detection", "endpoints",
                          "accepts_envelope_profiles", "register_addressing", "value_object_keys", "outcome",
                          "capability_notes"}
COMPONENT_ENDPOINT_KEYS = {"endpoint_key", "variant", "route", "mapping_version", "input_format", "reader",
                           "realtime", "cadence_s", "expected_delay_s", "stale_after_s", "continuous_feed",
                           "request_window", "records", "entities", "derive", "failure_detection",
                           "empty_response", "mapping_versions", "cadence_note"}
COMPONENT_RECORD_KEYS = {"iterate", "device_id", "entity_scope", "times", "effective_time_roles", "known_keys",
                         "identity_checks", "register_checks", "decode_suspect_threshold", "withhold_if", "interval"}
COMPONENT_ENTITY_KEYS = {"scope", "iterate", "device_id", "known_keys", "fields"}
COMPONENT_FIELD_KEYS = {"id", "source", "metric", "unit", "unit_from", "allowed_units", "transform", "presence",
                        "requirement", "channel", "boundary", "requires_capability", "applies_if", "expect_sign",
                        "status_map", "model_behaviour", "assumption_basis", "evidence", "native_ref", "register",
                        "scale", "offset", "scale_register", "invalid_sentinels", "invalid_if_bits", "enum",
                        "sign_convention", "sign_from", "aggregation", "processing_from", "processing_map",
                        "sensor_position", "phase", "mounting", "capability", "reason", "label_in_state_column",
                        "numeric", "sign_split", "evidence_status", "absence"}
COMPONENT_REGISTER_KEYS = {"number", "address", "type", "word_order"}
COMPONENT_READER_KEYS = {"header_rows", "environment_row", "names_row", "units_row", "processing_row",
                         "expect_environment_first", "sidecar_suffix", "max_rows", "max_columns", "max_line_bytes"}
COMPONENT_DERIVE_KEYS = {"id", "method", "from_metric", "to_metric", "counter", "priority", "max_gap_s",
                         "max_rate_ref", "max_rate_factor", "resolution", "component", "hold", "reset_match_s",
                         "basis_note"}


class RegistryError(ValueError):
    pass


def _err(where, msg):
    raise RegistryError(f"{where}: {msg}")


class Registry:
    def __init__(self, paths):
        self.paths = [Path(p) for p in paths]
        if not self.paths:
            raise RegistryError("no registry file given")
        h = hashlib.sha256()
        data: dict = {"profiles": {}, "units": {}, "canonical_metrics": {}, "rule_versions": {}, "defaults": {}}
        expanded = []
        for p in self.paths:
            # `extends: [file.yaml]` (relative to the extending file) loads base registries FIRST, so a component
            # registry reuses the provider profiles/metrics without copying or editing them.
            first = yaml.safe_load(Path(p).read_bytes()) or {}
            for e in first.get("extends") or []:
                q = (Path(p).parent / e).resolve()
                if q not in expanded:
                    expanded.append(q)
            if Path(p).resolve() not in expanded:
                expanded.append(Path(p).resolve())
        own = {Path(x).resolve() for x in self.paths}
        self.extended_from = [q for q in expanded if q not in own]
        for p in expanded:
            raw = p.read_bytes()
            h.update(raw)
            doc = yaml.safe_load(raw) or {}
            for key, val in doc.items():
                if key in ("profiles", "units", "canonical_metrics", "rule_versions", "defaults"):
                    for k, v in (val or {}).items():
                        if key == "profiles" and k in data[key]:
                            _err(p, f"duplicate profile id {k!r}")
                        if key in ("units", "canonical_metrics") and k in data[key] and data[key][k] != v:
                            _err(p, f"conflicting redefinition of {key}.{k}")
                        data[key][k] = v
                elif key == "extends":
                    continue
                elif key not in data:
                    data[key] = val
        self.base_dir = expanded[0].parent
        self.requirements = self._side_file(data.get("requirements_registry"), h)
        self.review_policies = self._side_file(data.get("review_policies"), h)
        self.config_hash = h.hexdigest()
        self.data = data
        self.registry_version = data.get("registry_version", "unversioned")
        self.units = data["units"]
        self.metrics = data["canonical_metrics"]
        self.profiles = data["profiles"]
        self.defaults = data["defaults"]
        self._endpoints: dict[tuple[str, str], list[dict]] = {}
        self._validate()

    def _side_file(self, name, h):
        if not name:
            return {}
        p = self.base_dir / name
        raw = p.read_bytes()
        h.update(raw)
        return yaml.safe_load(raw) or {}

    # ------------------------------------------------------------------ validation
    def _validate(self):
        for u, d in self.units.items():
            for k in ("dimension", "canonical", "factor"):
                if k not in d:
                    _err(f"units.{u}", f"missing {k}")
        for m, d in self.metrics.items():
            if d.get("unit") not in self.units:
                _err(f"canonical_metrics.{m}", f"unknown unit {d.get('unit')!r}")
        for pid, prof in self.profiles.items():
            where = f"profiles.{pid}"
            for k in ("provider", "profile_version", "endpoints"):
                if k not in prof:
                    _err(where, f"missing {k}")
            if "family" in prof:
                if prof["family"] not in FAMILIES:
                    _err(where, f"unknown family {prof['family']!r}")
                self._keys(where, prof, COMPONENT_PROFILE_KEYS)
                for i, ep in enumerate(prof["endpoints"]):
                    self._strict_endpoint(f"{where}.endpoints[{i}]", ep)
                self._check_register_addressing(where, prof)
            for i, rule in enumerate(prof.get("failure_detection") or []):
                self._cond(f"{where}.failure_detection[{i}].when", rule.get("when"))
            for i, ep in enumerate(prof["endpoints"]):
                self._validate_endpoint(f"{where}.endpoints[{i}]", ep)
                ep["_profile_id"] = pid
                self._endpoints.setdefault((pid, ep["endpoint_key"]), []).append(ep)

    @staticmethod
    def _keys(where, obj, allowed):
        if not isinstance(obj, dict):
            _err(where, "expected a mapping")
        unknown = sorted(set(obj) - allowed)
        if unknown:
            _err(where, f"unknown key(s) {unknown}; allowed: {sorted(allowed)}")

    def _strict_endpoint(self, where, ep):
        self._keys(where, ep, COMPONENT_ENDPOINT_KEYS)
        fmt = ep.get("input_format", "ndjson_envelope")
        if fmt not in INPUT_FORMATS:
            _err(where, f"input_format {fmt!r} not in {sorted(INPUT_FORMATS)}")
        if fmt == "header_csv":
            rd = ep.get("reader") or {}
            self._keys(f"{where}.reader", rd, COMPONENT_READER_KEYS)
            for k in ("header_rows", "names_row"):
                if not isinstance(rd.get(k), int) or rd[k] < 1:
                    _err(f"{where}.reader", f"{k} must be a positive integer")
        rec = ep.get("records") or {}
        self._keys(f"{where}.records", rec, COMPONENT_RECORD_KEYS)
        for c in rec.get("identity_checks") or []:
            self._path(where, c["path"])
            if "equals" not in c:
                self._path(where, c["ref"])
        for c in rec.get("register_checks") or []:
            if c.get("type") not in REGISTER_TYPES:
                _err(f"{where}.register_checks", f"bad type {c.get('type')!r}")
        for w in rec.get("withhold_if") or []:
            self._cond(f"{where}.withhold_if", w.get("when"))
            if not w.get("flag"):
                _err(f"{where}.withhold_if", "needs a flag")
        for t in rec.get("times") or []:
            if t.get("timezone"):
                try:
                    zone(t["timezone"])
                except Exception:  # noqa: BLE001 - any zoneinfo failure is a configuration error
                    _err(f"{where}.records.times", f"unknown timezone {t['timezone']!r}")
        for ent in ep.get("entities") or []:
            self._keys(f"{where}.entities", ent, COMPONENT_ENTITY_KEYS)
            for f in ent.get("fields", []):
                fw = f"{where}.fields.{f.get('id')}"
                self._keys(fw, f, COMPONENT_FIELD_KEYS)
                if f.get("aggregation") and f["aggregation"] not in AGGREGATIONS:
                    _err(fw, f"aggregation {f['aggregation']!r} not in {sorted(AGGREGATIONS)}")
                for a in (f.get("processing_map") or {}).values():
                    if a not in AGGREGATIONS:
                        _err(fw, f"processing_map value {a!r} not an aggregation")
                if f.get("sign_convention") not in (None, "negate"):
                    _err(fw, "sign_convention must be 'negate'")
                if f.get("sign_from"):
                    self._path(fw, f["sign_from"]["path"])
                    if not set((f["sign_from"].get("map") or {}).values()) <= {1, -1}:
                        _err(fw, "sign_from.map values must be 1 or -1")
                if f.get("transform") == "register_words":
                    r = f.get("register") or {}
                    self._keys(f"{fw}.register", r, COMPONENT_REGISTER_KEYS)
                    if r.get("type") not in REGISTER_TYPES:
                        _err(fw, f"register.type {r.get('type')!r} not in {sorted(REGISTER_TYPES)}")
                    if r.get("word_order", "high_word_first") not in WORD_ORDERS:
                        _err(fw, f"register.word_order {r.get('word_order')!r} not in {sorted(WORD_ORDERS)}")
                    if isinstance(r.get("address"), bool) or not isinstance(r.get("address"), int) or r["address"] < 0:
                        _err(fw, "register.address must be a non-negative protocol address")
                    sr = f.get("scale_register")
                    if sr and sr.get("mode", "pow10") not in SCALE_MODES:
                        _err(fw, f"scale_register.mode not in {sorted(SCALE_MODES)}")
        for d in ep.get("derive", []) or []:
            self._keys(f"{where}.derive.{d.get('id')}", d, COMPONENT_DERIVE_KEYS)
            if d.get("component") not in (None, "positive", "negative"):
                _err(f"{where}.derive.{d.get('id')}", "component must be positive or negative")

    def _check_register_addressing(self, where, prof):
        """Register number vs zero-based protocol address is CONFIGURATION, checked field by field."""
        ra = prof.get("register_addressing") or {}
        off = ra.get("register_minus_address")
        if off is None:
            return
        for ep in prof["endpoints"]:
            for ent in ep["entities"]:
                for f in ent.get("fields", []):
                    r = f.get("register") or {}
                    if f.get("transform") == "register_words" and r.get("number") is not None \
                            and r["number"] - r["address"] != off:
                        _err(f"{where}.fields.{f['id']}", f"register number {r['number']} and protocol address "
                                                         f"{r['address']} violate register - address = {off}")

    def _cond(self, where, c):
        if not isinstance(c, dict) or "path" not in c or c.get("op") not in CONDITION_OPS:
            _err(where, f"invalid condition {c!r}")
        compile_path(c["path"])

    def _path(self, where, p):
        try:
            compile_path(p)
        except ValueError as e:
            _err(where, str(e))

    def _validate_endpoint(self, where, ep):
        for k in ("endpoint_key", "variant", "mapping_version", "cadence_s", "records", "entities"):
            if k not in ep:
                _err(where, f"missing {k}")
        for c in ep.get("route", []):
            self._cond(f"{where}.route", c)
        rec = ep["records"]
        for st in rec.get("iterate", []):
            if st.get("kind") not in ITER_KINDS:
                _err(f"{where}.records.iterate", f"bad kind {st.get('kind')!r}")
            self._path(where, st["path"])
        if not rec.get("times"):
            _err(where, "records.times must declare at least one time role")
        roles = set()
        for t in rec["times"]:
            if t.get("format") not in TIME_FORMATS:
                _err(f"{where}.records.times", f"unsupported format {t.get('format')!r}")
            self._path(where, t["path"])
            roles.add(t["role"])
        for r in rec.get("effective_time_roles", []):
            if r not in roles:
                _err(where, f"effective_time_roles references undeclared role {r!r}")
        for mv in ep.get("mapping_versions", []) or []:
            if "version" not in mv or "detect" not in mv:
                _err(f"{where}.mapping_versions", "each version needs version + detect")
            self._cond(f"{where}.mapping_versions.{mv['version']}.detect", mv["detect"])
        ids = set()
        for ent in ep["entities"]:
            for st in ent.get("iterate", []):
                if st.get("kind") not in ITER_KINDS:
                    _err(f"{where}.entities.iterate", f"bad kind {st.get('kind')!r}")
            for f in ent.get("fields", []):
                fw = f"{where}.fields.{f.get('id')}"
                if not f.get("id") or f["id"] in ids:
                    _err(fw, "field id missing or duplicated within endpoint")
                ids.add(f["id"])
                tr = f.get("transform", "numeric")
                if tr not in TRANSFORMS:
                    _err(fw, f"transform {tr!r} not in the supported library {sorted(TRANSFORMS)}")
                if f.get("presence", "optional") not in PRESENCE:
                    _err(fw, f"bad presence {f.get('presence')!r}")
                if f.get("requirement", "optional") not in REQUIREMENT:
                    _err(fw, f"bad requirement {f.get('requirement')!r}")
                self._path(fw, f["source"])
                metrics = []
                if tr == "sign_split":
                    metrics = [f["sign_split"]["positive"], f["sign_split"]["negative"]]
                elif tr == "edge_flow":
                    metrics = [o["metric"] for o in f["outputs"]]
                    for u in f.get("allowed_units", []):
                        if u not in self.units:
                            _err(fw, f"unknown allowed unit {u!r}")
                else:
                    metrics = [f["metric"]]
                for m in metrics:
                    if m not in self.metrics:
                        _err(fw, f"unknown canonical metric {m!r}")
                if "unit" in f and f["unit"] not in self.units:
                    _err(fw, f"unknown unit {f['unit']!r}")
                if tr in ("numeric", "sign_split", "negate") and "unit" not in f and "unit_from" not in f:
                    _err(fw, "numeric fields must declare unit or unit_from (units are never assumed)")
                if tr == "register_words" and "unit" not in f and self.metrics[metrics[0]]["kind"] != "state":
                    _err(fw, "register fields must declare a unit (units are never assumed)")
                if (tr == "value_object" or "unit_from" in f) and not f.get("allowed_units"):
                    _err(fw, "metadata-declared units need an allowed_units list")
                if f.get("applies_if"):
                    self._cond(fw, f["applies_if"])
        for d in ep.get("derive", []) or []:
            if d.get("method") not in DERIVE_METHODS:
                _err(f"{where}.derive", f"unsupported method {d.get('method')!r}")
            for m in (d["from_metric"], d["to_metric"]):
                if m not in self.metrics:
                    _err(f"{where}.derive.{d.get('id')}", f"unknown metric {m!r}")
            if d["method"] == "counter_difference" and d.get("counter") not in COUNTERS:
                _err(f"{where}.derive.{d.get('id')}", "counter must be lifetime or daily")

    # ------------------------------------------------------------------ lookups
    def rule_version(self, name: str) -> str:
        return str(self.data["rule_versions"].get(name, "1.0"))

    def default(self, name, fallback):
        return self.defaults.get(name, fallback)

    def route(self, profile_id: str, endpoint_key, ctx: dict):
        cands = self._endpoints.get((profile_id, endpoint_key), [])
        if not cands:
            return None, f"endpoint {endpoint_key!r} is not registered for profile {profile_id!r}"
        hits = [ep for ep in cands if all(condition(ctx, c) for c in ep.get("route", []))]
        if len(hits) == 1:
            return hits[0], None
        if not hits:
            return None, f"no registered variant of {endpoint_key!r} matches this envelope/site"
        return None, f"ambiguous route: {len(hits)} variants of {endpoint_key!r} match"

    def endpoints(self):
        for (pid, key), eps in self._endpoints.items():
            for ep in eps:
                yield pid, ep

    def endpoint(self, profile_id: str, endpoint_key: str, variant: str):
        for ep in self._endpoints.get((profile_id, endpoint_key), []):
            if ep["variant"] == variant:
                return ep
        return None
