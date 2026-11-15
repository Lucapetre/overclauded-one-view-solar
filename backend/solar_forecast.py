"""Backend PV and base-load forecast for the planner, using only data known at decision time.

PV: a deterministic clear-sky model (Haurwitz global irradiance, a fixed diffuse share,
transposed to an assumed or registered module plane) scaled by installed kWp and the
existing frontend performance ratio, then multiplied by a bounded *clearness factor*:

* `k_base`: the site's measured PV energy over the previous complete local days divided by
  the clear-sky energy for those days (persistence of recent conditions), else 1.0;
* `k_recent`: measured / clear-sky over the last hour from a compatible like-for-like source
  (POA irradiance on the same plane, else measured AC PV), blended into `k_base` linearly
  over the next three hours (a short, bounded near-term adjustment).

The result is labelled an estimate. It never reads data after the decision time, and it is
not a weather forecast: without measurements it is a clear-sky upper envelope.

Base load: the mean measured site load at the same local time of day over up to three
previous days; else the existing typical consumption shape of the site's segment scaled by
its profile's monthly import (stated assumption); else unknown.
"""

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

LOCAL = ZoneInfo("Europe/Bucharest")
SLOT = timedelta(minutes=15)
PERFORMANCE_RATIO = 0.85  # same stated assumption as frontend/src/forecast.js MODEL
DIFFUSE_SHARE = 0.15
ALBEDO = 0.2
DEFAULT_LOCATION = (44.43, 26.10)  # city-level location used by the existing forecast
DEFAULT_PLANE = (30.0, 180.0)  # tilt, azimuth (south): stated assumption
K_BOUNDS = (0.05, 1.1)
NEAR_TERM = timedelta(hours=3)
TYPICAL_SELF_SUPPLY = 0.35  # frontend/src/dailyForecast.js

# frontend/src/dailyForecast.js SHAPES (relative hourly weights, local hours 00..23).
SHAPES = {
    "home": [
        0.6,
        0.5,
        0.5,
        0.5,
        0.5,
        0.6,
        0.9,
        1.3,
        1.2,
        0.9,
        0.8,
        0.8,
        0.9,
        0.8,
        0.8,
        0.9,
        1.1,
        1.5,
        1.9,
        2.0,
        1.8,
        1.5,
        1.1,
        0.8,
    ],  # fmt: skip
    "office": [
        0.4,
        0.4,
        0.4,
        0.4,
        0.4,
        0.4,
        0.6,
        1.0,
        1.6,
        1.8,
        1.8,
        1.8,
        1.7,
        1.8,
        1.8,
        1.7,
        1.5,
        1.0,
        0.6,
        0.5,
        0.4,
        0.4,
        0.4,
        0.4,
    ],  # fmt: skip
    "hospitality": [
        0.5,
        0.5,
        0.5,
        0.5,
        0.5,
        0.5,
        0.5,
        0.7,
        0.9,
        1.1,
        1.4,
        1.8,
        2.2,
        2.2,
        1.8,
        1.3,
        1.2,
        1.5,
        1.9,
        2.2,
        2.2,
        1.8,
        1.2,
        0.7,
    ],  # fmt: skip
    "industrial": [
        0.7,
        0.7,
        0.7,
        0.7,
        0.7,
        0.7,
        1.0,
        1.3,
        1.3,
        1.3,
        1.3,
        1.3,
        1.3,
        1.3,
        1.3,
        1.3,
        1.3,
        1.3,
        1.3,
        1.3,
        1.3,
        1.0,
        0.8,
        0.7,
    ],  # fmt: skip
}


def consumption_shape(segment: str, business_type: str | None) -> list[float]:
    """Port of frontend consumptionShape()."""
    if segment != "business":
        return SHAPES["home"]
    kind = (business_type or "").lower()
    if any(
        word in kind
        for word in ("restaurant", "bistro", "cafe", "café", "hotel", " bar")
    ):
        return SHAPES["hospitality"]
    if any(
        word in kind
        for word in (
            "factory",
            "warehouse",
            "supermarket",
            "plant",
            "storage",
            "logistics",
            "depot",
            "works",
        )
    ):
        return SHAPES["industrial"]
    return SHAPES["office"]


def solar_position(latitude: float, longitude: float, moment: datetime):
    """(cos zenith, azimuth degrees from north) — NOAA general solar position equations."""
    moment = moment.astimezone(UTC)
    day = moment.timetuple().tm_yday
    hour = moment.hour + moment.minute / 60 + moment.second / 3600
    gamma = 2 * math.pi / 365 * (day - 1 + (hour - 12) / 24)
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )
    declination = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )
    true_solar = hour * 60 + eqtime + 4 * longitude
    hour_angle = math.radians(true_solar / 4 - 180)
    lat = math.radians(latitude)
    cos_zenith = math.sin(lat) * math.sin(declination) + math.cos(lat) * math.cos(
        declination
    ) * math.cos(hour_angle)
    cos_zenith = max(-1.0, min(1.0, cos_zenith))
    zenith = math.acos(cos_zenith)
    if math.sin(zenith) < 1e-9:
        return cos_zenith, 180.0
    cos_azimuth = (math.sin(declination) - math.sin(lat) * cos_zenith) / (
        math.cos(lat) * math.sin(zenith)
    )
    azimuth = math.degrees(math.acos(max(-1.0, min(1.0, cos_azimuth))))
    if hour_angle > 0:
        azimuth = 360 - azimuth
    return cos_zenith, azimuth


def clear_sky(
    latitude: float, longitude: float, moment: datetime, plane=DEFAULT_PLANE
) -> tuple[float, float]:
    """Clear-sky (global horizontal, plane-of-array) irradiance in W/m2 at one instant."""
    cos_zenith, azimuth = solar_position(latitude, longitude, moment)
    if cos_zenith <= 0.01:
        return 0.0, 0.0
    ghi = 1098 * cos_zenith * math.exp(-0.057 / cos_zenith)
    diffuse = DIFFUSE_SHARE * ghi
    beam_normal = (ghi - diffuse) / cos_zenith
    tilt, plane_azimuth = (math.radians(plane[0]), plane[1])
    zenith = math.acos(cos_zenith)
    cos_incidence = cos_zenith * math.cos(tilt) + math.sin(zenith) * math.sin(
        tilt
    ) * math.cos(math.radians(azimuth - plane_azimuth))
    poa = (
        beam_normal * max(0.0, cos_incidence)
        + diffuse * (1 + math.cos(tilt)) / 2
        + ghi * ALBEDO * (1 - math.cos(tilt)) / 2
    )
    return ghi, poa


def slot_clear_sky(latitude, longitude, start: datetime, plane=DEFAULT_PLANE):
    """Mean clear-sky (GHI, POA) over a 15-minute slot (three-point average)."""
    points = [start + SLOT * fraction for fraction in (1 / 6, 1 / 2, 5 / 6)]
    values = [clear_sky(latitude, longitude, point, plane) for point in points]
    return (
        sum(v[0] for v in values) / len(values),
        sum(v[1] for v in values) / len(values),
    )


def clear_sky_pv_kw(kwp: float, poa_wm2: float) -> float:
    return min(kwp, kwp * poa_wm2 / 1000 * PERFORMANCE_RATIO)


def arrays_pv_kw(latitude, longitude, start, arrays) -> float:
    """Clear-sky AC PV over a slot for module arrays [(kwp, tilt, azimuth)]."""
    total = 0.0
    for kwp, tilt, azimuth in arrays:
        _, poa = slot_clear_sky(latitude, longitude, start, (tilt, azimuth))
        total += clear_sky_pv_kw(kwp, poa)
    return total


@dataclass
class Sample:
    start: datetime
    value: float
    evidence_id: str | None = None


@dataclass
class PvForecast:
    issue_time: datetime
    method: str
    values: dict[datetime, float]
    k_base: float | None
    k_recent: float | None
    recent_source: str | None
    reason_codes: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    location_basis: str = "site"
    plane_basis: str = "assumed"


def _bounded(value: float) -> float:
    return max(K_BOUNDS[0], min(K_BOUNDS[1], value))


def forecast_pv(
    slots: list[datetime],
    issue_time: datetime,
    kwp: float | None,
    location: tuple[float, float] | None,
    arrays: list[tuple[float, float, float]] | None,
    pv_history: list[Sample],
    poa_recent: list[Sample] | None = None,
    sensor_plane: tuple[float, float] | None = None,
) -> PvForecast:
    """PV kW per slot start. `pv_history`/`poa_recent` must end at or before `issue_time`.

    `arrays` are registered module arrays (kwp, tilt, azimuth); `sensor_plane` is the
    registered plane of a POA irradiance sensor, required to compare like with like.
    """
    reasons = []
    if kwp is None:
        return PvForecast(
            issue_time, "unavailable", {}, None, None, None, ["installed_kwp_unknown"]
        )
    latitude, longitude = location or DEFAULT_LOCATION
    if location is None:
        reasons.append("location_assumed_city_level")
    planes = arrays or [(kwp, *DEFAULT_PLANE)]
    if not arrays:
        reasons.append("module_plane_assumed")

    def expected_pv(start):
        return arrays_pv_kw(latitude, longitude, start, planes)

    history = [s for s in pv_history if s.start + SLOT <= issue_time]
    evidence = []
    # Persistence of recent days: measured / clear-sky energy over previous complete days.
    today = issue_time.astimezone(LOCAL).date()
    measured = clear = 0.0
    days = set()
    for sample in history:
        local_day = sample.start.astimezone(LOCAL).date()
        if not (today - timedelta(days=3) <= local_day < today):
            continue
        expected = expected_pv(sample.start)
        if expected > 0.05 * kwp:
            measured += sample.value
            clear += expected
            days.add(local_day)
    k_base = _bounded(measured / clear) if clear > 0 and days else None
    if k_base is None:
        reasons.append("no_recent_production_history")
    # Near-term: last hour of compatible measurements before the decision time.
    recent_source = None
    k_recent = None
    window = issue_time - timedelta(hours=1)
    if poa_recent and sensor_plane is not None:
        numerator = denominator = 0.0
        for sample in poa_recent:
            if window <= sample.start and sample.start + SLOT <= issue_time:
                _, poa = slot_clear_sky(latitude, longitude, sample.start, sensor_plane)
                if poa > 50:
                    numerator += sample.value
                    denominator += poa
                    if sample.evidence_id:
                        evidence.append(sample.evidence_id)
        if denominator > 0:
            k_recent = _bounded(numerator / denominator)
            recent_source = "poa_irradiance"
    if k_recent is None:
        numerator = denominator = 0.0
        for sample in history:
            if window <= sample.start:
                expected = expected_pv(sample.start)
                if expected > 0.05 * kwp:
                    numerator += sample.value
                    denominator += expected
                    if sample.evidence_id:
                        evidence.append(sample.evidence_id)
        if denominator > 0:
            k_recent = _bounded(numerator / denominator)
            recent_source = "measured_ac_pv"
    if k_recent is None:
        reasons.append("no_recent_compatible_measurement")
    base = k_base if k_base is not None else 1.0
    values = {}
    for start in slots:
        factor = base
        if k_recent is not None:
            lead = (start - issue_time).total_seconds()
            weight = max(0.0, 1 - lead / NEAR_TERM.total_seconds())
            factor = base + (k_recent - base) * weight
        values[start] = round(expected_pv(start) * factor, 4)
    if k_base is None and k_recent is None:
        method = "clear_sky_envelope_unadjusted"
    elif k_recent is None:
        method = "clear_sky_scaled_by_recent_days"
    else:
        method = "clear_sky_scaled_with_near_term_adjustment"
    evidence.extend(s.evidence_id for s in history[-4:] if s.evidence_id)
    return PvForecast(
        issue_time,
        method,
        values,
        round(k_base, 4) if k_base is not None else None,
        round(k_recent, 4) if k_recent is not None else None,
        recent_source,
        reasons,
        list(dict.fromkeys(evidence)),
        "site" if location else "city_default",
        "registered" if arrays else "assumed",
    )


@dataclass
class LoadForecast:
    issue_time: datetime
    method: str
    values: dict[datetime, float | None]
    reason_codes: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)


def forecast_load(
    slots: list[datetime],
    issue_time: datetime,
    load_history: list[Sample],
    profile: dict | None = None,
) -> LoadForecast:
    """Base site load kW per slot start (excluding planned tasks)."""
    history = [s for s in load_history if s.start + SLOT <= issue_time]
    by_time: dict[tuple[int, int], list[float]] = {}
    lower = issue_time - timedelta(days=3)
    for sample in history:
        if sample.start < lower:
            continue
        local = sample.start.astimezone(LOCAL)
        by_time.setdefault((local.hour, local.minute), []).append(sample.value)
    if by_time:
        values = {}
        missing = 0
        filled = 0

        def profile_at(moment):
            local = moment.astimezone(LOCAL)
            samples = by_time.get((local.hour, local.minute))
            return sum(samples) / len(samples) if samples else None

        for start in slots:
            value = profile_at(start)
            if value is None:
                # Bounded gap fill: the mean of measured neighbours within 30 minutes.
                near = [
                    profile_at(start + SLOT * step)
                    for step in (-2, -1, 1, 2)
                    if profile_at(start + SLOT * step) is not None
                ]
                if near:
                    value = sum(near) / len(near)
                    filled += 1
            if value is None:
                missing += 1
            values[start] = None if value is None else round(value, 4)
        reasons = ["load_profile_partial"] if missing else []
        if filled:
            reasons.append("load_profile_gap_filled_from_adjacent_slots")
        return LoadForecast(
            issue_time,
            "measured_same_time_of_day_mean_3d",
            values,
            reasons,
            [s.evidence_id for s in history[-4:] if s.evidence_id],
        )
    monthly = (profile or {}).get("monthly_import_kwh")
    if monthly and monthly > 0:
        daily = monthly / 30 / (1 - TYPICAL_SELF_SUPPLY)
        shape = consumption_shape(
            profile.get("segment", "home"), profile.get("business_type")
        )
        total = sum(shape)
        values = {}
        for start in slots:
            hour = start.astimezone(LOCAL).hour
            values[start] = round(daily * shape[hour] / total, 4)  # kWh per hour = kW
        return LoadForecast(
            issue_time,
            "typical_shape_from_profile_assumption",
            values,
            ["load_from_typical_shape_assumption"],
        )
    return LoadForecast(
        issue_time, "unavailable", dict.fromkeys(slots), ["base_load_unknown"]
    )
