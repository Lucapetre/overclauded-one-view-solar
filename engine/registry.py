"""Load, merge and validate the declarative provider registry. Rejects anything outside the schema."""
from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from .selectors import CONDITION_OPS, compile_path, condition
from .timeparse import TIME_FORMATS
from .transforms import DERIVE_METHODS, TRANSFORMS

PRESENCE = {"required", "required_nullable", "optional"}
REQUIREMENT = {"integration_required", "vendor_response_required", "optional"}
ITER_KINDS = {"list", "map"}
COUNTERS = {"lifetime", "daily"}


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
        for p in self.paths:
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
                elif key not in data:
                    data[key] = val
        self.base_dir = self.paths[0].parent
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
            for i, rule in enumerate(prof.get("failure_detection") or []):
                self._cond(f"{where}.failure_detection[{i}].when", rule.get("when"))
            for i, ep in enumerate(prof["endpoints"]):
                self._validate_endpoint(f"{where}.endpoints[{i}]", ep)
                ep["_profile_id"] = pid
                self._endpoints.setdefault((pid, ep["endpoint_key"]), []).append(ep)

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
