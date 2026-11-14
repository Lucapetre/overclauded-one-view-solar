"""Profile-declared timestamp parsing. Never guesses an offset, a unit or a DST fold."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import NamedTuple
from zoneinfo import ZoneInfo

from .selectors import MISSING

UTC = timezone.utc
TIME_FORMATS = {"epoch_ms", "epoch_s", "iso_offset", "local_naive"}
_MIN_EPOCH, _MAX_EPOCH = 946684800, 4102444800  # 2000-01-01 .. 2100-01-01


class TimeResult(NamedTuple):
    utc: datetime | None
    status: str  # ok | missing | invalid | missing_offset | missing_timezone | ambiguous_local_time | nonexistent_local_time
    detail: str


@lru_cache(maxsize=64)
def zone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def resolve_local(naive: datetime, tz_name: str) -> TimeResult:
    tz = zone(tz_name)
    a = naive.replace(tzinfo=tz, fold=0)
    b = naive.replace(tzinfo=tz, fold=1)
    if a.utcoffset() == b.utcoffset():
        return TimeResult(a.astimezone(UTC), "ok", "")
    round_trip = a.astimezone(UTC).astimezone(tz).replace(tzinfo=None)
    if round_trip != naive:
        return TimeResult(None, "nonexistent_local_time",
                          f"{naive.isoformat(sep=' ')} does not exist in {tz_name} (DST gap); not shifted")
    return TimeResult(None, "ambiguous_local_time",
                      f"{naive.isoformat(sep=' ')} occurs twice in {tz_name} (DST fold) and the source gives no "
                      f"offset; not disambiguated")


def parse_time(raw, fmt: str, tz_name: str | None = None, pattern: str | None = None) -> TimeResult:
    if raw is MISSING:
        return TimeResult(None, "missing", "time key absent")
    if raw is None or raw == "":
        return TimeResult(None, "missing", "time value null/empty")
    if fmt in ("epoch_ms", "epoch_s"):
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return TimeResult(None, "invalid", f"non-numeric epoch value {raw!r}")
        secs = raw / 1000.0 if fmt == "epoch_ms" else float(raw)
        if not (_MIN_EPOCH <= secs <= _MAX_EPOCH):
            return TimeResult(None, "invalid", f"epoch {raw!r} outside plausible range for {fmt}; unit not guessed")
        return TimeResult(datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=secs), "ok", "")
    if fmt == "iso_offset":
        if not isinstance(raw, str):
            return TimeResult(None, "invalid", f"ISO time must be a string, got {type(raw).__name__}")
        s = raw.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return TimeResult(None, "invalid", f"unparseable ISO time {raw!r}")
        if dt.tzinfo is None or dt.utcoffset() is None:
            return TimeResult(None, "missing_offset", f"ISO time {raw!r} has no UTC offset; not guessed")
        return TimeResult(dt.astimezone(UTC), "ok", "")
    if fmt == "local_naive":
        if not isinstance(raw, str):
            return TimeResult(None, "invalid", f"local time must be a string, got {type(raw).__name__}")
        if not tz_name:
            return TimeResult(None, "missing_timezone", "local naive time but the site has no registered timezone")
        try:
            naive = datetime.strptime(raw, pattern or "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return TimeResult(None, "invalid", f"local time {raw!r} does not match pattern {pattern!r}")
        return resolve_local(naive, tz_name)
    return TimeResult(None, "invalid", f"unsupported time format {fmt!r}")


def to_ms(dt: datetime | None) -> int | None:
    return None if dt is None else int(round(dt.timestamp() * 1000))


def ms_to_iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    return (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=int(ms))).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def ms_to_local_iso(ms: int | None, tz_name: str) -> str | None:
    if ms is None:
        return None
    return (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=int(ms))).astimezone(zone(tz_name)).isoformat(
        timespec="seconds")


def local_date(ms: int, tz_name: str):
    return (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=int(ms))).astimezone(zone(tz_name)).date()


def local_day_bounds_ms(day, tz_name: str) -> tuple[int, int]:
    """[start, end) of a local calendar day in UTC ms (23, 24 or 25 hours around DST)."""
    tz = zone(tz_name)
    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    nxt = day + timedelta(days=1)
    end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=tz)
    return to_ms(start), to_ms(end)


def local_day_frames(day, tz_name: str, frame_s: int = 900) -> list[tuple[int, int]]:
    """Quarter-hour frames covering one local day: 92 / 96 / 100 frames on DST-change days."""
    a, b = local_day_bounds_ms(day, tz_name)
    step = frame_s * 1000
    return [(t, min(t + step, b)) for t in range(a, b, step)]
