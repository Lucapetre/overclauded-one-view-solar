"""Contract time-band evaluator: customer import rate and export value for any UTC interval.

Bands are local Europe/Bucharest wall-clock rules: ISO weekdays of the day an occurrence
*starts*, a start minute and an end minute (end <= start crosses local midnight), optional
local-date validity. Versions are immutable and superseded from their `effective_from`
instant. Intervals are split at every band, version and validity boundary; DST days have
23 or 25 elapsed hours because occurrences are converted from local wall time. A local
boundary inside the spring-forward gap maps to the first existing instant after it.

Missing coverage is an explicit gap (rates None plus a reason), never a zero price.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from backend.db import stamp

TIMEZONE = "Europe/Bucharest"
LOCAL = ZoneInfo(TIMEZONE)
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
MAX_SPAN = timedelta(days=62)


@dataclass(frozen=True)
class Band:
    band_id: str
    days: tuple[int, ...]
    start_minute: int
    end_minute: int
    import_rate: float
    export_value: float
    label: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None  # exclusive local date

    def applies_on(self, day: date) -> bool:
        return (
            day.isoweekday() in self.days
            and (self.valid_from is None or day >= self.valid_from)
            and (self.valid_to is None or day < self.valid_to)
        )

    @property
    def crosses_midnight(self) -> bool:
        return self.end_minute <= self.start_minute


@dataclass(frozen=True)
class ContractVersion:
    version_id: str
    version_no: int
    effective_from: datetime
    bands: tuple[Band, ...]
    pricing: str = "fixed"
    export_compensation: str = "unspecified"
    valid_to: datetime | None = None
    supplier: str = ""


@dataclass(frozen=True)
class PriceSegment:
    start: datetime
    end: datetime
    import_rate: float | None
    export_value: float | None
    band_id: str | None
    version_id: str | None
    gap_reason: str | None = None

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600


@dataclass
class IntervalPrice:
    """Time-weighted rates over one interval, with the segments behind them."""

    start: datetime
    end: datetime
    segments: list[PriceSegment] = field(default_factory=list)

    @property
    def covered(self) -> bool:
        return all(segment.gap_reason is None for segment in self.segments)

    @property
    def gap_reasons(self) -> list[str]:
        return sorted(
            {segment.gap_reason for segment in self.segments if segment.gap_reason}
        )

    def _weighted(self, attribute: str) -> float | None:
        if not self.covered or not self.segments:
            return None
        total = sum(segment.hours for segment in self.segments)
        return sum(getattr(s, attribute) * s.hours for s in self.segments) / total

    @property
    def import_rate(self) -> float | None:
        return self._weighted("import_rate")

    @property
    def export_value(self) -> float | None:
        return self._weighted("export_value")

    @property
    def band_ids(self) -> list[str]:
        return list(dict.fromkeys(s.band_id for s in self.segments if s.band_id))

    @property
    def version_ids(self) -> list[str]:
        return list(dict.fromkeys(s.version_id for s in self.segments if s.version_id))


def local_to_utc(day: date, minute: int) -> datetime:
    """Local wall time `minute` after midnight of `day` as UTC (minute 1440 = next midnight)."""
    moment = datetime.combine(day, time()) + timedelta(minutes=minute)
    # A wall time inside the spring-forward gap does not exist: use the gap's end.
    for _ in range(181):
        aware = moment.replace(tzinfo=LOCAL)
        converted = aware.astimezone(UTC)
        if converted.astimezone(LOCAL).replace(tzinfo=None) == moment:
            return converted
        moment += timedelta(minutes=1)
    raise ValueError("Local time could not be resolved")


def _occurrences(band: Band, day: date) -> tuple[datetime, datetime]:
    start = local_to_utc(day, band.start_minute)
    if band.crosses_midnight:
        end = local_to_utc(day + timedelta(days=1), band.end_minute)
    else:
        end = local_to_utc(day, band.end_minute)
    return start, end


def _version_windows(
    versions: list[ContractVersion], start: datetime, end: datetime
) -> list[tuple[ContractVersion, datetime, datetime]]:
    ordered = sorted(versions, key=lambda v: (v.effective_from, v.version_no))
    windows = []
    for index, version in enumerate(ordered):
        upper = ordered[index + 1].effective_from if index + 1 < len(ordered) else None
        if version.valid_to is not None:
            upper = min(upper, version.valid_to) if upper else version.valid_to
        lower = max(version.effective_from, start)
        upper = min(upper, end) if upper else end
        if lower < upper:
            windows.append((version, lower, upper))
    return windows


def segments(
    versions: list[ContractVersion], start: datetime, end: datetime
) -> list[PriceSegment]:
    """Ordered, contiguous segments covering [start, end) exactly; gaps are explicit."""
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    if end <= start:
        return []
    if end - start > MAX_SPAN:
        raise ValueError("Price a span of at most 62 days at a time")
    found: list[PriceSegment] = []
    for version, lower, upper in _version_windows(versions, start, end):
        first = lower.astimezone(LOCAL).date() - timedelta(days=1)
        last = upper.astimezone(LOCAL).date()
        day = first
        while day <= last:
            for band in version.bands:
                if not band.applies_on(day):
                    continue
                begin, finish = _occurrences(band, day)
                begin, finish = max(begin, lower), min(finish, upper)
                if begin < finish:
                    found.append(
                        PriceSegment(
                            begin,
                            finish,
                            band.import_rate,
                            band.export_value,
                            band.band_id,
                            version.version_id,
                        )
                    )
            day += timedelta(days=1)
    found.sort(key=lambda s: (s.start, s.end, s.band_id or ""))
    result: list[PriceSegment] = []
    cursor = start
    windows = _version_windows(versions, start, end)
    for segment in found:
        if segment.start > cursor:
            result.append(_gap(cursor, segment.start, windows))
        if segment.end <= cursor:
            continue  # validated versions never overlap; be safe against duplicates
        result.append(
            segment
            if segment.start >= cursor
            else PriceSegment(
                cursor,
                segment.end,
                segment.import_rate,
                segment.export_value,
                segment.band_id,
                segment.version_id,
            )
        )
        cursor = segment.end
    if cursor < end:
        result.append(_gap(cursor, end, windows))
    return result


def _gap(start: datetime, end: datetime, windows) -> PriceSegment:
    inside = any(lower <= start and end <= upper for _, lower, upper in windows)
    version = next(
        (v.version_id for v, lower, upper in windows if lower <= start < upper), None
    )
    return PriceSegment(
        start,
        end,
        None,
        None,
        None,
        version,
        "no_band_coverage" if inside or version else "no_contract_version",
    )


def price(versions: list[ContractVersion], start: datetime, end: datetime):
    return IntervalPrice(start, end, segments(versions, start, end))


def validate_bands(bands: list[Band]) -> list[str]:
    """Errors for invalid or overlapping bands of one version (minute grid per week)."""
    errors = []
    for index, band in enumerate(bands):
        if not band.days or any(day not in range(1, 8) for day in band.days):
            errors.append(f"Band {band.band_id}: days must be ISO weekdays 1-7")
        if band.valid_from and band.valid_to and band.valid_to <= band.valid_from:
            errors.append(f"Band {band.band_id}: valid_to must follow valid_from")
        for other in bands[index + 1 :]:
            if other.band_id == band.band_id:
                errors.append(f"Duplicate band id {band.band_id}")
                continue
            if not _validity_overlaps(band, other):
                continue
            if _week_minutes(band) & _week_minutes(other):
                errors.append(f"Bands {band.band_id} and {other.band_id} overlap")
    return errors


def _validity_overlaps(a: Band, b: Band) -> bool:
    low = max(a.valid_from or date.min, b.valid_from or date.min)
    high = min(a.valid_to or date.max, b.valid_to or date.max)
    return low < high


def _week_minutes(band: Band) -> set[int]:
    minutes = set()
    week = 7 * 1440
    for day in band.days:
        base = (day - 1) * 1440
        length = (
            band.end_minute - band.start_minute
            if not band.crosses_midnight
            else 1440 - band.start_minute + band.end_minute
        )
        # Minute grid over one week (a midnight-crossing band spills into the next weekday).
        for offset in range(length):
            minutes.add((base + band.start_minute + offset) % week)
    return minutes


# ---------------------------------------------------------------- persistence helpers


def _date(text):
    return date.fromisoformat(text) if text else None


def _instant(text):
    return datetime.fromisoformat(text).astimezone(UTC) if text else None


def load_versions(connection, site_id: str) -> list[ContractVersion]:
    versions = []
    for row in connection.execute(
        "SELECT * FROM contract_versions WHERE site_id=? ORDER BY effective_from, version_no",
        (site_id,),
    ).fetchall():
        bands = tuple(
            Band(
                band_id=band["band_id"],
                days=tuple(json.loads(band["days"])),
                start_minute=band["start_minute"],
                end_minute=band["end_minute"],
                import_rate=band["import_rate_ron_kwh"],
                export_value=band["export_value_ron_kwh"],
                label=band["label"],
                valid_from=_date(band["valid_from"]),
                valid_to=_date(band["valid_to"]),
            )
            for band in connection.execute(
                "SELECT * FROM contract_bands WHERE version_id=? ORDER BY start_minute, band_id",
                (row["version_id"],),
            )
        )
        versions.append(
            ContractVersion(
                version_id=row["version_id"],
                version_no=row["version_no"],
                effective_from=_instant(row["effective_from"]),
                bands=bands,
                pricing=row["pricing"],
                export_compensation=row["export_compensation"],
                valid_to=_instant(row["valid_to"]),
                supplier=row["supplier"],
            )
        )
    return versions


def current_version(versions: list[ContractVersion], at: datetime):
    active = [v for v in versions if v.effective_from <= at]
    if not active:
        return None
    version = max(active, key=lambda v: (v.effective_from, v.version_no))
    if version.valid_to is not None and version.valid_to <= at:
        return None
    return version


def insert_version(
    connection,
    site_id: str,
    *,
    supplier: str,
    pricing: str,
    export_compensation: str,
    bands: list[Band],
    effective_from: datetime,
    valid_to: datetime | None,
    created_by: str,
    created_as_of: datetime,
) -> str:
    number = (
        connection.execute(
            "SELECT COALESCE(MAX(version_no),0) FROM contract_versions WHERE site_id=?",
            (site_id,),
        ).fetchone()[0]
        + 1
    )
    previous = connection.execute(
        "SELECT MAX(effective_from) FROM contract_versions WHERE site_id=?", (site_id,)
    ).fetchone()[0]
    if previous and _instant(previous) > effective_from:
        # Versions only supersede forward; a later-dated version keeps priority otherwise.
        effective_from = _instant(previous)
    version_id = f"cv-{site_id}-{number}"
    connection.execute(
        "INSERT INTO contract_versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            version_id,
            site_id,
            number,
            supplier,
            pricing,
            TIMEZONE,
            export_compensation,
            stamp(effective_from),
            stamp(valid_to) if valid_to else None,
            created_by,
            stamp(),
            stamp(created_as_of),
        ),
    )
    connection.executemany(
        "INSERT INTO contract_bands VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            (
                version_id,
                band.band_id,
                band.label,
                json.dumps(sorted(band.days)),
                band.start_minute,
                band.end_minute,
                band.import_rate,
                band.export_value,
                band.valid_from.isoformat() if band.valid_from else None,
                band.valid_to.isoformat() if band.valid_to else None,
            )
            for band in bands
        ],
    )
    return version_id


def all_day(import_rate: float, export_value: float) -> Band:
    return Band(
        "all-day", (1, 2, 3, 4, 5, 6, 7), 0, 1440, import_rate, export_value, "All day"
    )


__all__ = [
    "EPOCH",
    "LOCAL",
    "TIMEZONE",
    "Band",
    "ContractVersion",
    "IntervalPrice",
    "PriceSegment",
    "all_day",
    "current_version",
    "insert_version",
    "load_versions",
    "local_to_utc",
    "price",
    "segments",
    "validate_bands",
]
