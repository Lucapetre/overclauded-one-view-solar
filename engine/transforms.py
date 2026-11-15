"""The small, closed transform library: numeric parsing, unit scaling, sign splitting, edge-directed flow,
value objects and captured register-word decoding. Anything outside this list is rejected when the registry
loads."""
from __future__ import annotations

import math
import re
import struct
from decimal import Decimal
from functools import lru_cache

TRANSFORMS = {"numeric", "value_object", "sign_split", "negate", "edge_flow", "state", "register_words"}
DERIVE_METHODS = {"counter_difference", "power_integration"}

# ------------------------------------------------------------------ captured 16-bit register words
# type -> (number of 16-bit words, signed?, kind)
REGISTER_TYPES = {
    "uint16": (1, False, "int"), "int16": (1, True, "int"),
    "uint32": (2, False, "int"), "int32": (2, True, "int"),
    "uint64": (4, False, "int"), "int64": (4, True, "int"),
    "float32": (2, None, "float"),
}
WORD_ORDERS = {"high_word_first", "low_word_first"}
SCALE_MODES = {"pow10", "pow10_negated"}


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


def exact_convert(exact: Decimal, unit: str, units: dict) -> Decimal:
    """Exact decimal unit conversion (e.g. integer Wh -> kWh) without passing through binary floating point."""
    return exact * Decimal(str(units[unit]["factor"]))


def decimal_text(d: Decimal) -> str:
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def gather_words(blocks, address: int, count: int):
    """Return (words | None, problem) for `count` registers starting at protocol `address` from captured blocks
    [{start_address, words: [uint16...]}]."""
    if not isinstance(blocks, list):
        return None, "captured register blocks absent or not a list"
    for b in blocks:
        if not isinstance(b, dict):
            return None, "malformed register block"
        start, words = b.get("start_address"), b.get("words")
        if isinstance(start, bool) or not isinstance(start, int) or not isinstance(words, list):
            return None, "malformed register block"
        if start <= address and address + count <= start + len(words):
            w = words[address - start: address - start + count]
            for x in w:
                if isinstance(x, bool) or not isinstance(x, int) or not 0 <= x <= 0xFFFF:
                    return None, f"register word {x!r} is not an unsigned 16-bit integer"
            return list(w), None
    return None, f"registers {address}..{address + count - 1} were not part of the captured response"


def decode_words(words, rtype: str, word_order: str):
    """Decode captured 16-bit words. Returns (value, raw_int, status, note).

    Integers are decoded with Python ints (Int64 stays exact). Float32 that is NaN/inf is reported as
    status 'nonfinite_float' (our invalid rule; e.g. 0x7FC00000 / 0xFFC00000)."""
    n, signed, kind = REGISTER_TYPES[rtype]
    if len(words) != n:
        return None, None, "invalid_word_count", f"{rtype} needs {n} words, got {len(words)}"
    ordered = list(words) if word_order == "high_word_first" else list(reversed(words))
    raw = 0
    for w in ordered:
        raw = (raw << 16) | w
    if kind == "float":
        f = struct.unpack(">f", raw.to_bytes(4, "big"))[0]
        if math.isnan(f) or math.isinf(f):
            return None, raw, "nonfinite_float", f"Float32 bit pattern 0x{raw:08X} is NaN/inf"
        return f, raw, "ok", ""
    bits = 16 * n
    if signed and raw >= 1 << (bits - 1):
        return raw - (1 << bits), raw, "ok", ""
    return raw, raw, "ok", ""


def scale_from_register(sf: int, mode: str):
    """Scale-factor register (SunSpec-style pow10, or vendor 'x / 10^sf' style pow10_negated) -> Decimal."""
    return Decimal(10) ** (sf if mode == "pow10" else -sf)


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
