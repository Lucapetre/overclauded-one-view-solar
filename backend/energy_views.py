"""Customer energy views: the Home overview and production/consumption history.

Everything is SYNTHETIC demo data. Real values come from the site's own sources up to the analytical
clock; any day without data is filled from a clearly labelled deterministic seasonal profile.
Consumption is never measured here: it is derived (PV AC + grid import - grid export, with the AC
battery flow where the site has one) and an input that is missing makes the result `null`.
"""

import hashlib
import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from backend import bridge, components
from backend.clock import analytical_now, clock_state
from backend.db import site_from_row, stamp
from backend.energy import readings, records_between
from backend.errors import ApiError
from backend.models import Metric, Model, User
from backend.security import authorized_site

LOCAL = ZoneInfo("Europe/Bucharest")
SLOT = timedelta(minutes=15)
Origin = Literal["measured", "derived", "synthetic_profile"]
Period = Literal["today", "week", "month", "year"]


class OverviewMetric(Model):
    value: float | None
    unit: Literal["kW", "kWh"]
    origin: Literal["measured", "derived"] | None = None
    reason: str | None = None
    basis: str | None = None


class TodayTotals(Model):
    production: OverviewMetric
    grid_import: OverviewMetric
    grid_export: OverviewMetric
    consumption: OverviewMetric
    self_consumption_share: float | None = None


class EnergyOverview(Model):
    site_id: str
    as_of: datetime
    clock: Literal["scenario", "live"]
    source: Literal["component_meters", "provider_frames", "compact_telemetry", "none"]
    interval_start: datetime | None
    interval_end: datetime | None
    pv: OverviewMetric
    grid_import: OverviewMetric
    grid_export: OverviewMetric
    consumption: OverviewMetric
    today: TodayTotals
    synthetic: bool = True


class PeriodBucket(Model):
    start: datetime
    end: datetime
    label: str
    origin: Origin
    complete: bool
    production_kwh: float | None
    consumption_kwh: float | None
    grid_import_kwh: float | None
    grid_export_kwh: float | None


class PeriodTotals(Model):
    production_kwh: float | None
    consumption_kwh: float | None
    grid_import_kwh: float | None
    grid_export_kwh: float | None
    self_consumption_share: float | None
    peak_kw: float | None
    peak_kw_origin: str | None


class OriginSummary(Model):
    measured: int = 0
    derived: int = 0
    synthetic_profile: int = 0


class EnergyPeriods(Model):
    site_id: str
    period: Period
    as_of: datetime
    timezone: str
    resolution: Literal["hour", "day", "month"]
    start: datetime
    end: datetime
    buckets: list[PeriodBucket]
    totals: PeriodTotals
    origin_summary: OriginSummary
    synthetic: bool
    note: str


@dataclass
class Slot:
    start: datetime
    hours: float
    pv: float | None = None
    grid_import: float | None = None
    grid_export: float | None = None
    consumption: float | None = None
    pv_reason: str | None = None
    grid_reason: str | None = None
    consumption_reason: str | None = None


@dataclass
class Series:
    source: str
    slots: dict[datetime, Slot] = field(default_factory=dict)


def _local_day(moment: datetime) -> date:
    return moment.astimezone(LOCAL).date()


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time(0), LOCAL).astimezone(UTC)


def _iso(text: str) -> datetime:
    return datetime.fromisoformat(text)


# ---------------------------------------------------------------- measured series


def _provider_series(
    connection, site_id: str, start: datetime, end: datetime
) -> Series:
    has_meter = connection.execute(
        "SELECT 1 FROM component_grid_frames cg JOIN component_sites cs "
        "ON cs.import_id=cg.import_id AND cs.site_id=cg.site_id WHERE cg.site_id=? LIMIT 1",
        (site_id,),
    ).fetchone()
    series = Series("component_meters" if has_meter else "provider_frames")
    pv = {
        s.start: s.value
        for s in bridge.pv_history(connection, site_id, start, end).samples
    }
    for moment, kw in pv.items():
        series.slots[moment] = Slot(moment, 0.25, pv=kw * 0.25)
    if not has_meter:
        for slot in series.slots.values():
            slot.grid_reason = "no_grid_meter"
            slot.consumption_reason = "no_grid_meter"
        return series
    active = components._active(connection, site_id)
    grid: dict[datetime, dict[str, tuple]] = {}
    for row in connection.execute(
        "SELECT metric, frame_start, value_kwh, value_origin FROM component_grid_frames "
        "WHERE import_id=? AND site_id=? AND frame_start>=? AND frame_end<=?",
        (active["import_id"], site_id, stamp(start), stamp(end)),
    ):
        grid.setdefault(_iso(row["frame_start"]), {})[row["metric"]] = (
            row["value_kwh"],
            row["value_origin"],
        )
    derived = {
        s.start: s.value
        for s in components.derived_load_samples(connection, site_id, start, end)
    }
    placement = connection.execute(
        "SELECT latitude, longitude FROM site_placements WHERE site_id=?", (site_id,)
    ).fetchone()
    location = (
        (placement["latitude"], placement["longitude"])
        if placement
        else components.DEFAULT_LOCATION
    )
    for moment in sorted(set(grid) | set(pv)):
        slot = series.slots.setdefault(moment, Slot(moment, 0.25))
        if (
            slot.pv is None
            and moment in grid
            and components._sun_down(location, moment)
        ):
            slot.pv = 0.0  # inverter silent with the sun below the horizon: no AC PV
        flows = grid.get(moment, {})
        for key, attribute in (
            ("grid_import", "grid_import"),
            ("grid_export", "grid_export"),
        ):
            value, origin = flows.get(key, (None, None))
            if value is not None and origin == "measured":
                setattr(slot, attribute, float(value))
        if slot.grid_import is None or slot.grid_export is None:
            slot.grid_reason = "grid_frame_unknown"
        if slot.pv is None:
            slot.pv_reason = "pv_unknown"
        if slot.grid_import is None or slot.grid_export is None:
            slot.consumption_reason = "grid_frame_unknown"
        elif slot.pv is None:
            slot.consumption_reason = "pv_unknown"
        elif moment in derived:
            slot.consumption = derived[moment] * 0.25
        else:
            slot.consumption_reason = "battery_or_pv_input_missing"
    return series


def _compact_series(connection, site_row, start: datetime, end: datetime) -> Series:
    site = site_from_row(site_row)
    series = Series("compact_telemetry")
    for record in records_between(connection, site.site_id, start, end, limit=10001):
        if record.interval_end > end:
            continue
        hours = (record.interval_end - record.interval_start).total_seconds() / 3600
        values = readings(site, record)
        slot = Slot(record.interval_start, hours)
        for attribute, metric in (
            ("pv", Metric.pv),
            ("grid_import", Metric.grid_import),
            ("grid_export", Metric.grid_export),
            ("consumption", Metric.load),
        ):
            value = values[metric]
            if value.value is not None and value.boundary in ("ac", "not_applicable"):
                setattr(slot, attribute, value.value * hours)
        if slot.pv is None:
            slot.pv_reason = "pv_unknown"
        if slot.grid_import is None or slot.grid_export is None:
            slot.grid_reason = "no_grid_meter"
        if slot.consumption is None:
            slot.consumption_reason = (
                "no_grid_meter" if slot.grid_reason else "input_missing"
            )
        series.slots[record.interval_start] = slot
    return series


def measured_series(connection, site_row, start: datetime, end: datetime) -> Series:
    now = analytical_now(connection)
    end = min(end, now)
    start = max(start, end - timedelta(days=8))
    if end <= start:
        return Series("none")
    site_id = site_row["site_id"]
    if connection.execute(
        "SELECT 1 FROM provider_sites WHERE site_id=?", (site_id,)
    ).fetchone():
        return _provider_series(connection, site_id, start, end)
    return _compact_series(connection, site_row, start, end)


# ---------------------------------------------------------------- overview


def _metric(value, unit, origin, reason, basis=None) -> OverviewMetric:
    if value is None:
        return OverviewMetric(value=None, unit=unit, reason=reason or "no_data")
    return OverviewMetric(value=round(value, 4), unit=unit, origin=origin, basis=basis)


FORMULA = (
    "PV AC + grid import - grid export (+ AC battery flow where the site has a battery)"
)


def overview(connection, user: User, site_id: str) -> EnergyOverview:
    row = authorized_site(connection, user, site_id)
    state = clock_state(connection)
    now = analytical_now(connection)
    midnight = _day_start(_local_day(now))
    series = measured_series(connection, row, midnight - SLOT, now)
    complete = sorted(
        (s for s in series.slots.values() if s.start + timedelta(hours=s.hours) <= now),
        key=lambda s: s.start,
    )
    latest = complete[-1] if complete else None

    def power(slot: Slot | None, attribute: str, reason_attribute: str, origin: str):
        if slot is None:
            return _metric(None, "kW", None, "no_data_before_as_of")
        value = getattr(slot, attribute)
        return _metric(
            None if value is None else value / slot.hours,
            "kW",
            origin,
            getattr(slot, reason_attribute) or "input_missing",
            FORMULA if attribute == "consumption" else None,
        )

    today_slots = [s for s in complete if s.start >= midnight]

    def total(attribute: str, origin: str, reason: str):
        values = [getattr(s, attribute) for s in today_slots]
        if not today_slots or any(v is None for v in values):
            known = [v for v in values if v is not None]
            if not known:
                return _metric(None, "kWh", None, reason)
            # Partial day: sum the known slots and say so; never impute the missing ones.
            return OverviewMetric(
                value=round(sum(known), 3),
                unit="kWh",
                origin=origin,
                reason=f"partial_coverage:{len(known)}_of_{len(today_slots)}_intervals",
                basis=FORMULA if attribute == "consumption" else None,
            )
        return _metric(
            sum(values),
            "kWh",
            origin,
            reason,
            FORMULA if attribute == "consumption" else None,
        )

    production = total("pv", "measured", "pv_unknown")
    exported = total("grid_export", "measured", "no_grid_meter")
    share = None
    if production.value and exported.value is not None:
        share = round(
            max(0.0, min(1.0, (production.value - exported.value) / production.value)),
            4,
        )
    return EnergyOverview(
        site_id=site_id,
        as_of=now,
        clock="scenario" if state.mode == "scenario" else "live",
        source=series.source if latest else "none",
        interval_start=latest.start if latest else None,
        interval_end=latest.start + timedelta(hours=latest.hours) if latest else None,
        pv=power(latest, "pv", "pv_reason", "measured"),
        grid_import=power(latest, "grid_import", "grid_reason", "measured"),
        grid_export=power(latest, "grid_export", "grid_reason", "measured"),
        consumption=power(latest, "consumption", "consumption_reason", "derived"),
        today=TodayTotals(
            production=production,
            grid_import=total("grid_import", "measured", "no_grid_meter"),
            grid_export=exported,
            consumption=total("consumption", "derived", "no_grid_meter"),
            self_consumption_share=share,
        ),
    )


# ---------------------------------------------------------------- synthetic seasonal profile

# Typical clear-ish daily yield per installed kWp in Bucharest (kWh/kWp/day), January..December.
YIELD = (1.1, 1.9, 3.0, 4.0, 4.9, 5.3, 5.4, 5.0, 3.9, 2.6, 1.4, 0.9)
HOME_SHAPE = (
    0.02,
    0.018,
    0.017,
    0.017,
    0.02,
    0.03,
    0.06,
    0.07,
    0.05,
    0.035,
    0.03,
    0.03,
    0.035,
    0.03,
    0.03,
    0.035,
    0.05,
    0.075,
    0.09,
    0.095,
    0.085,
    0.065,
    0.04,
    0.026,
)  # morning bump, evening peak
BUSINESS_SHAPE = (
    0.01,
    0.01,
    0.01,
    0.01,
    0.012,
    0.02,
    0.04,
    0.07,
    0.085,
    0.09,
    0.095,
    0.095,
    0.09,
    0.09,
    0.09,
    0.085,
    0.075,
    0.055,
    0.035,
    0.025,
    0.018,
    0.014,
    0.012,
    0.01,
)  # daytime
SEVEN_DAY_BUSINESS = ("laundry", "restaurant", "café", "cafe", "bistro", "hotel", "bar")


def _unit(*parts) -> float:
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
    return int.from_bytes(digest[:4], "big") / 2**32


def profile_day(
    kwp: float | None, segment: str, business_type: str | None, site_id: str, day: date
) -> tuple[list[float], list[float]]:
    """Deterministic typical day: hourly (production, consumption) kWh. SYNTHETIC."""
    doy = day.timetuple().tm_yday
    season = math.cos(2 * math.pi * (doy - 20) / 365)  # +1 mid January, -1 mid July
    # Weather is shared by the whole city for a date, with a little per-site variation.
    weather = 0.55 + 0.45 * _unit("weather", day.isoformat())
    weather *= 0.97 + 0.06 * _unit("site", site_id, day.isoformat())
    length = 12.15 + 3.35 * math.sin(2 * math.pi * (doy - 80) / 365)
    noon = 13.3 if 4 <= day.month <= 10 else 12.3
    shape = []
    for hour in range(24):
        x = (hour + 0.5 - noon) / (length / 2)
        shape.append(math.cos(math.pi * x / 2) ** 2 if abs(x) < 1 else 0.0)
    total = sum(shape) or 1.0
    daily = (kwp or 0.0) * YIELD[day.month - 1] * weather
    production = [daily * value / total for value in shape]
    size = kwp or 5.0
    if segment == "business":
        weekend = day.weekday() >= 5
        seven = any(
            word in (business_type or "").lower() for word in SEVEN_DAY_BUSINESS
        )
        factor = (1.1 if seven else 0.5) if weekend else 1.0
        daily_load = (18 + 2.8 * size) * (1 + 0.12 * season) * factor
        weights = BUSINESS_SHAPE
    else:
        daily_load = (4 + 1.0 * size) * (1 + 0.30 * season)
        weights = HOME_SHAPE
    scale = sum(weights)
    consumption = [daily_load * w / scale for w in weights]
    return production, consumption


@dataclass
class Aggregate:
    production: float = 0.0
    consumption: float = 0.0
    grid_import: float = 0.0
    grid_export: float = 0.0
    peak: float = 0.0


def _profile_totals(profile, days: list[date], factors=(1.0, 1.0)) -> Aggregate:
    result = Aggregate()
    for day in days:
        production, consumption = profile(day)
        for p, c in zip(production, consumption, strict=True):
            p, c = p * factors[0], c * factors[1]
            direct = min(p, c)
            result.production += p
            result.consumption += c
            result.grid_export += p - direct
            result.grid_import += c - direct
            result.peak = max(result.peak, c)
    return result


# ---------------------------------------------------------------- periods

NOTE = (
    "Measured or derived buckets come from this site's own data up to the scenario time (consumption is "
    "derived: PV + grid import - grid export). Buckets labelled synthetic_profile are a deterministic "
    "typical-season estimate from installed capacity and customer type, not measurements."
)


def _site_profile(connection, site_id: str):
    placement = connection.execute(
        "SELECT installed_kwp, segment, business_type FROM site_placements WHERE site_id=?",
        (site_id,),
    ).fetchone()
    if placement:
        return (
            placement["installed_kwp"],
            placement["segment"],
            placement["business_type"],
        )
    profile = connection.execute(
        "SELECT installed_kwp, segment, business_type FROM site_profiles WHERE site_id=?",
        (site_id,),
    ).fetchone()
    if profile:
        return profile["installed_kwp"], profile["segment"], profile["business_type"]
    contract = connection.execute(
        "SELECT installed_kwp FROM contracts WHERE site_id=?", (site_id,)
    ).fetchone()
    return (contract["installed_kwp"] if contract else None), "home", None


def _sum(values):
    known = [v for v in values if v is not None]
    return round(sum(known), 3) if known else None


def _bucket_from_slots(slots: list[Slot], start, end, label, complete) -> PeriodBucket:
    def add(attribute):
        values = [getattr(s, attribute) for s in slots]
        known = [v for v in values if v is not None]
        return round(sum(known), 3) if known else None

    consumption = add("consumption")
    return PeriodBucket(
        start=start,
        end=end,
        label=label,
        origin="derived" if consumption is not None else "measured",
        complete=complete,
        production_kwh=add("pv"),
        consumption_kwh=consumption,
        grid_import_kwh=add("grid_import"),
        grid_export_kwh=add("grid_export"),
    )


def _synthetic_bucket(profile, days, start, end, label, factors) -> PeriodBucket:
    aggregate = _profile_totals(profile, days, factors)
    return PeriodBucket(
        start=start,
        end=end,
        label=label,
        origin="synthetic_profile",
        complete=True,
        production_kwh=round(aggregate.production, 3),
        consumption_kwh=round(aggregate.consumption, 3),
        grid_import_kwh=round(aggregate.grid_import, 3),
        grid_export_kwh=round(aggregate.grid_export, 3),
    )


def periods(connection, user: User, site_id: str, period: str) -> EnergyPeriods:
    if period not in ("today", "week", "month", "year"):
        raise ApiError(422, "invalid_period", "Use today, week, month or year")
    row = authorized_site(connection, user, site_id)
    now = analytical_now(connection)
    today = _local_day(now)
    kwp, segment, business_type = _site_profile(connection, site_id)
    profile = lambda day: profile_day(kwp, segment, business_type, site_id, day)  # noqa: E731
    buckets: list[PeriodBucket] = []
    peak_kw, peak_origin = None, None

    if period == "today":
        start = _day_start(today)
        series = measured_series(connection, row, start, now)
        slots = sorted(series.slots.values(), key=lambda s: s.start)
        if slots:
            for hour in range(24):
                lower = start + timedelta(hours=hour)
                upper = lower + timedelta(hours=1)
                if lower >= now:
                    break
                inside = [
                    s
                    for s in slots
                    if lower <= s.start < upper
                    and s.start + timedelta(hours=s.hours) <= now
                ]
                if not inside:
                    continue
                buckets.append(
                    _bucket_from_slots(
                        inside, lower, min(upper, now), f"{hour:02d}:00", upper <= now
                    )
                )
            kws = [s.consumption / s.hours for s in slots if s.consumption is not None]
            if kws:
                peak_kw, peak_origin = round(max(kws), 3), "measured_15min_derived"
        else:
            # Live mode without data: the typical profile for the day, up to the current hour.
            production, consumption = profile(today)
            for hour in range(24):
                lower = start + timedelta(hours=hour)
                if lower >= now:
                    break
                direct = min(production[hour], consumption[hour])
                buckets.append(
                    PeriodBucket(
                        start=lower,
                        end=lower + timedelta(hours=1),
                        label=f"{hour:02d}:00",
                        origin="synthetic_profile",
                        complete=True,
                        production_kwh=round(production[hour], 3),
                        consumption_kwh=round(consumption[hour], 3),
                        grid_import_kwh=round(consumption[hour] - direct, 3),
                        grid_export_kwh=round(production[hour] - direct, 3),
                    )
                )
            if buckets:
                peak_kw = round(max(b.consumption_kwh for b in buckets), 3)
                peak_origin = "synthetic_profile"
        resolution, window_start, window_end = "hour", start, now
    elif period in ("week", "month"):
        count = 7 if period == "week" else 30
        days = [today - timedelta(days=offset) for offset in range(count - 1, -1, -1)]
        window_start, window_end = _day_start(days[0]), now
        series = measured_series(connection, row, window_start, now)
        by_day: dict[date, list[Slot]] = {}
        for slot in series.slots.values():
            by_day.setdefault(_local_day(slot.start), []).append(slot)
        # Calibrate the profile to this site's complete measured days (kept within 0.5-2x).
        factors = (1.0, 1.0)
        measured_days = [
            d
            for d in days
            if len(by_day.get(d, [])) >= 90 and _day_start(d) + timedelta(days=1) <= now
        ]
        if measured_days:
            real = _bucket_totals([s for d in measured_days for s in by_day[d]])
            typical = _profile_totals(profile, measured_days)
            factors = tuple(
                max(0.5, min(2.0, real[i] / typical_value))
                if real[i] and typical_value
                else 1.0
                for i, typical_value in enumerate(
                    (typical.production, typical.consumption)
                )
            )
        kws = []
        for day in days:
            lower = _day_start(day)
            upper = _day_start(day + timedelta(days=1))
            slots = by_day.get(day, [])
            label = day.strftime("%a %d %b")
            if slots:
                buckets.append(
                    _bucket_from_slots(
                        slots,
                        lower,
                        min(upper, now),
                        label,
                        upper <= now and len(slots) >= 90,
                    )
                )
                kws += [
                    s.consumption / s.hours for s in slots if s.consumption is not None
                ]
            else:
                buckets.append(
                    _synthetic_bucket(profile, [day], lower, upper, label, factors)
                )
        if kws:
            peak_kw, peak_origin = round(max(kws), 3), "measured_15min_derived"
        else:
            peak_kw = round(
                max(profile(d)[1][h] for d in days for h in range(24)) * factors[1], 3
            )
            peak_origin = "synthetic_profile"
        resolution = "day"
    else:
        months = []
        year, month = today.year, today.month
        for _ in range(12):
            months.append((year, month))
            month -= 1
            if month == 0:
                year, month = year - 1, 12
        months.reverse()
        window_start = _day_start(date(*months[0], 1))
        window_end = now
        for year, month in months:
            first = date(year, month, 1)
            following = date(year + (month == 12), month % 12 + 1, 1)
            days = [first + timedelta(days=n) for n in range((following - first).days)]
            buckets.append(
                _synthetic_bucket(
                    profile,
                    days,
                    _day_start(first),
                    _day_start(following),
                    first.strftime("%b %Y"),
                    (1.0, 1.0),
                )
            )
        peak_kw = round(
            max(
                profile(d)[1][h]
                for d in (date(today.year, 1, 15), date(today.year, 7, 15))
                for h in range(24)
            ),
            3,
        )
        peak_origin = "synthetic_profile"
        resolution = "month"

    totals = PeriodTotals(
        production_kwh=_sum(b.production_kwh for b in buckets),
        consumption_kwh=_sum(b.consumption_kwh for b in buckets),
        grid_import_kwh=_sum(b.grid_import_kwh for b in buckets),
        grid_export_kwh=_sum(b.grid_export_kwh for b in buckets),
        self_consumption_share=None,
        peak_kw=peak_kw,
        peak_kw_origin=peak_origin,
    )
    if totals.production_kwh and totals.grid_export_kwh is not None:
        totals.self_consumption_share = round(
            max(
                0.0,
                min(
                    1.0,
                    (totals.production_kwh - totals.grid_export_kwh)
                    / totals.production_kwh,
                ),
            ),
            4,
        )
    summary = OriginSummary()
    for bucket in buckets:
        setattr(summary, bucket.origin, getattr(summary, bucket.origin) + 1)
    return EnergyPeriods(
        site_id=site_id,
        period=period,
        as_of=now,
        timezone="Europe/Bucharest",
        resolution=resolution,
        start=window_start,
        end=window_end,
        buckets=buckets,
        totals=totals,
        origin_summary=summary,
        synthetic=summary.synthetic_profile > 0,
        note=NOTE,
    )


def _bucket_totals(slots: list[Slot]) -> tuple[float, float]:
    return (
        sum(s.pv or 0.0 for s in slots),
        sum(s.consumption or 0.0 for s in slots),
    )
