"""Generic JSON selector over named contexts, plus a tiny declarative condition evaluator.

Path syntax: "<context>.<key>.<key>"; list elements by numeric segment; "<alias>.__key__" returns the key of
a map-iteration item. There is no expression language, eval or exec.
"""
from __future__ import annotations


class _Missing:
    __slots__ = ()

    def __repr__(self):
        return "<MISSING>"

    def __bool__(self):
        return False


MISSING = _Missing()
_CACHE: dict[str, tuple[str, ...]] = {}


def compile_path(path: str) -> tuple[str, ...]:
    parts = _CACHE.get(path)
    if parts is None:
        if not isinstance(path, str) or not path or any(not p for p in path.split(".")):
            raise ValueError(f"invalid selector path: {path!r}")
        parts = tuple(path.split("."))
        _CACHE[path] = parts
    return parts


def select(ctx: dict, path: str):
    """Return the value at `path` or MISSING. A present JSON null is returned as None (not MISSING)."""
    parts = compile_path(path)
    if len(parts) == 2 and parts[1] == "__key__":
        return ctx.get(parts[0] + "#key", MISSING)
    cur = ctx.get(parts[0], MISSING)
    for p in parts[1:]:
        if isinstance(cur, dict):
            cur = cur.get(p, MISSING)
        elif isinstance(cur, list) and p.isdigit():
            i = int(p)
            cur = cur[i] if i < len(cur) else MISSING
        else:
            return MISSING
        if cur is MISSING:
            return MISSING
    return cur


_OPS = {
    "eq": lambda a, b: a == b and isinstance(a, bool) == isinstance(b, bool),
    "ne": lambda a, b: not (a == b and isinstance(a, bool) == isinstance(b, bool)),
    "gt": lambda a, b: _num(a) and a > b,
    "gte": lambda a, b: _num(a) and a >= b,
    "lt": lambda a, b: _num(a) and a < b,
    "lte": lambda a, b: _num(a) and a <= b,
    "in": lambda a, b: a in b,
}
CONDITION_OPS = set(_OPS) | {"present", "absent"}


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def condition(ctx: dict, cond: dict) -> bool:
    """Evaluate {path, op, value}. A MISSING operand satisfies only 'absent'."""
    v = select(ctx, cond["path"])
    op = cond["op"]
    if op == "present":
        return v is not MISSING
    if op == "absent":
        return v is MISSING
    if v is MISSING:
        return False
    target = cond.get("value")
    if op == "eq" and isinstance(target, bool):
        return v is target
    try:
        return bool(_OPS[op](v, target))
    except TypeError:
        return False


def resolve_ref(ctx: dict, refs) -> float | None:
    """First numeric value among an ordered list of registry paths (e.g. device.rated_ac_kw)."""
    for ref in refs or []:
        v = select(ctx, ref)
        if _num(v):
            return float(v)
    return None
