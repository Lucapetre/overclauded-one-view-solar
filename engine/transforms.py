"""The small, closed transform library: numeric parsing, unit scaling, sign splitting, edge-directed flow
and value objects. Anything outside this list is rejected when the registry loads."""
from __future__ import annotations

import math
import re
from functools import lru_cache

TRANSFORMS = {"numeric", "value_object", "sign_split", "negate", "edge_flow", "state"}
DERIVE_METHODS = {"counter_difference", "power_integration"}


@lru_cache(maxsize=32)
def _number_regex(decimal: str, thousands: str | None):
    d = re.escape(decimal)
    simple = rf"[+-]?\d+(?:{d}\d+)?"
    if thousands:
        t = re.escape(thousands)
        grouped = rf"[+-]?\d{{1,3}}(?:{t}\d{{3}})+(?:{d}\d+)?"
        return re.compile(rf"^(?:{grouped}|{simple})$")
    return re.compile(rf"^{simple}$")


def parse_number(raw, cfg: dict):
    """Return (value | None, status, note). status: ok | numeric_string_parsed | invalid_type | ambiguous_number."""
    if isinstance(raw, bool):
        return None, "invalid_type", "boolean is not a number"
    if isinstance(raw, (int, float)):
        f = float(raw)
        if math.isnan(f) or math.isinf(f):
            return None, "invalid_type", "non-finite number"
        return f, "ok", ""
    if isinstance(raw, str):
        if not cfg.get("allow_numeric_strings", False):
            return None, "invalid_type", f"string {raw!r} where the profile requires a JSON number"
        dec = cfg.get("decimal_separator", ".")
        th = cfg.get("thousands_separator")
        s = raw.strip()
        if not _number_regex(dec, th).match(s):
            return None, "ambiguous_number", (f"{raw!r} does not match the allowed numeric format "
                                              f"(decimal {dec!r}, thousands {th!r}); not guessed")
        if th:
            s = s.replace(th, "")
        if dec != ".":
            s = s.replace(dec, ".")
        return float(s), "numeric_string_parsed", f"numeric string {raw!r} parsed with decimal {dec!r}"
    return None, "invalid_type", f"{type(raw).__name__} is not numeric"


def convert_unit(value: float, unit: str, target: str, units: dict):
    u = units.get(unit)
    if u is None:
        return None, f"unit {unit!r} is not a supported declared unit"
    if u["canonical"] != target:
        return None, f"unit {unit!r} cannot be converted to {target!r}"
    return value * u["factor"], None


def edge_set(connections, from_key: str, to_key: str, case_insensitive: bool = True):
    """Return ({(source, target)}, problem|None) from a list of edge objects with configured key names."""
    if connections is None:
        return set(), None
    if not isinstance(connections, list):
        return set(), "connections is not a list"
    out = set()
    for c in connections:
        if not isinstance(c, dict) or not isinstance(c.get(from_key), str) or not isinstance(c.get(to_key), str):
            return out, "malformed connection entry"
        a, b = c[from_key], c[to_key]
        out.add((a.upper(), b.upper()) if case_insensitive else (a, b))
    return out, None


def edge_flow_value(magnitude: float, edges: set, out_cfg: dict):
    """Directed value from a nonnegative magnitude and the edges. Returns (value | None, how)."""
    if out_cfg.get("direction") == "none":
        return magnitude, "magnitude"
    fwd = {tuple(e) for e in out_cfg.get("direction_any", [])}
    opp = {tuple(e) for e in out_cfg.get("opposite_any", [])}
    if edges & fwd:
        return magnitude, "edge_direction"
    if edges & opp:
        return 0.0, "opposite_edge"
    if magnitude == 0:
        return 0.0, "zero_magnitude_no_edge"
    return None, "direction_unresolved"
