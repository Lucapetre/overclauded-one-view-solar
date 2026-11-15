"""Registered account/site/device bindings (onboarding metadata). Exact keys only; no fuzzy matching."""
from __future__ import annotations

import json
from pathlib import Path


def site_key(provider: str, account_id: str, site_id: str) -> str:
    return f"{provider}|{account_id}|{site_id}"


def device_key(skey: str, device_id: str | None) -> str:
    return f"{skey}|{device_id}" if device_id not in (None, "") else ""


def id_to_str(raw):
    """Identifiers stay strings: large integers are kept exact, leading zeros preserved. Returns (str|None, problem)."""
    if raw is None or raw == "":
        return None, "identifier null/empty"
    if isinstance(raw, bool):
        return None, "boolean identifier"
    if isinstance(raw, int):
        return str(raw), None
    if isinstance(raw, str):
        return raw, None
    if isinstance(raw, float):
        return None, "floating-point identifier (precision may already be lost); not coerced"
    return None, f"identifier of type {type(raw).__name__}"


class SiteRegistry:
    def __init__(self, path: Path):
        self.path = Path(path)
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        self.doc = doc
        self.synthetic = bool(doc.get("synthetic", False))
        self.sites: dict[str, dict] = {}
        self.devices: dict[tuple[str, str], dict] = {}
        for s in doc.get("sites", []):
            key = site_key(s["provider"], str(s["account_id"]), str(s["site_id"]))
            if key in self.sites:
                raise ValueError(f"duplicate site binding {key}")
            s = dict(s)
            s["site_key"] = key
            self.sites[key] = s
            for d in s.get("devices", []):
                self.devices[(key, str(d["device_id"]))] = dict(d)

    def lookup(self, provider, account_id, site_id):
        if account_id is None or site_id is None:
            return None
        return self.sites.get(site_key(provider, str(account_id), str(site_id)))

    def device(self, skey: str, device_id: str):
        return self.devices.get((skey, device_id))


# ------------------------------------------------------------------ component asset / capability registry
RESOURCE_PREFIX = "resource"


def resource_key(area_id: str, resource_id: str) -> str:
    return f"{RESOURCE_PREFIX}|{area_id}|{resource_id}"


class AssetRegistry(SiteRegistry):
    """Base site registry (unchanged bytes, sha256-pinned) plus an explicit asset/capability registry.

    * assets bind a collector source identity (asset_id) to exactly one registered site or area resource;
    * area resources (e.g. a shared weather station) are scoped entries explicitly linked to eligible sites;
    * collectors, authority declarations, scenario overlays and maintenance logs are declared data, never
      inferred from names. Unknown asset ids are not matched fuzzily (the caller quarantines them)."""

    def __init__(self, assets_path: Path, guard=None):
        import hashlib

        self.assets_path = Path(assets_path)
        doc = json.loads(self.assets_path.read_text(encoding="utf-8"))
        base = doc.get("base_site_registry") or {}
        if not base.get("path"):
            raise ValueError("asset registry must name its base_site_registry.path")
        base_path = (self.assets_path.parent / base["path"]).resolve()
        if guard is not None:
            base_path = guard(base_path)
        if base.get("sha256"):
            actual = hashlib.sha256(base_path.read_bytes()).hexdigest()
            if actual != base["sha256"]:
                raise ValueError(f"base site registry {base_path} sha256 {actual} differs from the pinned "
                                 f"{base['sha256']}; identities cannot be confirmed")
        super().__init__(base_path)
        self.asset_doc = doc
        self.scenario_version = doc.get("scenario_version")
        self.synthetic = self.synthetic or bool(doc.get("synthetic"))
        self.assets: dict[str, dict] = {}
        self.resources: dict[str, dict] = {}
        for r in doc.get("resources", []):
            key = resource_key(r["area_id"], r["resource_id"])
            if key in self.sites:
                raise ValueError(f"duplicate resource {key}")
            s = dict(r)
            s.update(site_key=key, provider=RESOURCE_PREFIX, account_id=r["area_id"], site_id=r["resource_id"],
                     capabilities=dict(r.get("capabilities") or {}))
            self.sites[key] = s
            self.resources[key] = s
        for a in doc.get("assets", []):
            aid = a["asset_id"]
            if aid in self.assets:
                raise ValueError(f"duplicate asset id {aid}")
            skey = a["site_key"]
            if skey not in self.sites:
                raise ValueError(f"asset {aid} references unknown site/resource {skey}")
            dev = dict(self.devices.get((skey, str(a["device_id"])), {}))
            dev.update(a)
            dev["device_id"] = str(a["device_id"])
            self.devices[(skey, dev["device_id"])] = dev
            self.assets[aid] = dev
        self.collectors = list(doc.get("collectors", []))
        self.authority = list(doc.get("authority", []))
        self.overlays = list(doc.get("business_overlays", []))
        self.maintenance = list(doc.get("maintenance_log", []))

    def lookup_asset(self, asset_id):
        if not isinstance(asset_id, str):
            return None, None
        dev = self.assets.get(asset_id)
        if dev is None:
            return None, None
        return self.sites.get(dev["site_key"]), dev

    def maintenance_events(self, skey: str, device_id: str | None, kind: str):
        out = []
        for ev in self.maintenance:
            a = self.assets.get(ev.get("asset_id"))
            if a and a["site_key"] == skey and a["device_id"] == device_id and ev.get("kind") == kind:
                out.append(ev)
        return out
