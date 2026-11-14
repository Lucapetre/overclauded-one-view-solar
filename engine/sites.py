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
