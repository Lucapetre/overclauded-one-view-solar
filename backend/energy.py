import math
from datetime import UTC, datetime, timedelta

from backend.db import site_from_row, stamp
from backend.errors import ApiError
from backend.models import (
    UNITS,
    EnergyHistory,
    EnergySnapshot,
    Freshness,
    HistoryPoint,
    Measurement,
    Metric,
    PublicProvenance,
    Site,
    TelemetryRecord,
)


def empty_readings(site: Site) -> dict[Metric, Measurement]:
    return {
        metric: Measurement(
            value=None,
            unit=UNITS[metric],
            requirement=site.measurement_requirements.get(metric, "optional"),
            availability="missing" if metric in site.capabilities else "unsupported",
            boundary="not_applicable",
        )
        for metric in Metric
    }


def readings(site: Site, record: TelemetryRecord) -> dict[Metric, Measurement]:
    result = empty_readings(site)
    result.update(record.measurements)
    # Derive only from simultaneous AC flows at the registered aggregate boundary.
    if (
        Metric.load not in site.capabilities
        or result[Metric.load].availability != "missing"
    ):
        return result
    required = [Metric.pv, Metric.grid_import, Metric.grid_export]
    battery = any(
        metric in site.capabilities
        for metric in (
            Metric.soc,
            Metric.battery_charge,
            Metric.battery_discharge,
        )
    )
    if battery:
        required += [Metric.battery_charge, Metric.battery_discharge]
    if any(result[m].value is None or result[m].boundary != "ac" for m in required):
        return result
    value = (
        result[Metric.pv].value
        + result[Metric.grid_import].value
        - result[Metric.grid_export].value
    )
    if battery:
        value += (
            result[Metric.battery_discharge].value - result[Metric.battery_charge].value
        )
    flags = sorted(
        {flag for metric in required for flag in result[metric].quality_flags}
        | {"derived_assuming_zero_losses"}
    )
    result[Metric.load] = Measurement(
        value=value if value >= 0 else None,
        unit="kW",
        requirement=site.measurement_requirements.get(Metric.load, "optional"),
        availability="available" if value >= 0 else "invalid",
        origin="derived",
        boundary="ac",
        quality_flags=flags if value >= 0 else flags + ["negative_derived_load"],
    )
    return result


def snapshot(connection, site: Site, now: datetime | None = None) -> EnergySnapshot:
    row = connection.execute(
        "SELECT payload FROM telemetry WHERE site_id=? ORDER BY interval_end DESC LIMIT 1",
        (site.site_id,),
    ).fetchone()
    if not row:
        return EnergySnapshot(
            site_id=site.site_id,
            interval_start=None,
            interval_end=None,
            received_at=None,
            freshness=Freshness(
                status="unavailable",
                age_seconds=None,
                clock="wall",
                evaluated_at=now or datetime.now(UTC),
            ),
            provenance=None,
            measurements=empty_readings(site),
            quality_flags=[],
            vendor_codes=[],
        )
    record = TelemetryRecord.model_validate_json(row["payload"])
    clock = "wall"
    reference = now or datetime.now(UTC)
    if record.source_mode != "live":
        setting = connection.execute(
            "SELECT value FROM settings WHERE key='replay_at'"
        ).fetchone()
        reference = datetime.fromisoformat(setting["value"]) if setting else None
        clock = "replay" if setting else "unconfigured"
    age = (reference - record.interval_end).total_seconds() if reference else None
    status = (
        "unknown_clock"
        if age is None
        else (
            "future"
            if age < 0
            else "stale"
            if age > site.stale_after_seconds
            else "fresh"
        )
    )
    return EnergySnapshot(
        site_id=site.site_id,
        interval_start=record.interval_start,
        interval_end=record.interval_end,
        received_at=record.received_at,
        freshness=Freshness(
            status=status, age_seconds=age, clock=clock, evaluated_at=reference
        ),
        provenance=PublicProvenance(
            source_mode=record.source_mode,
            source_id=record.source_id,
            source_date=record.interval_start.date().isoformat(),
        ),
        measurements=readings(site, record),
        quality_flags=record.quality_flags,
        vendor_codes=record.vendor_codes,
    )


def aggregate(
    site: Site, records: list[TelemetryRecord], start: datetime, end: datetime
) -> HistoryPoint:
    output = empty_readings(site)
    coverage = {metric: 0.0 for metric in Metric}
    energy = {metric: None for metric in Metric if UNITS[metric] == "kW"}
    prepared = [(record, readings(site, record)) for record in records]
    flags = {flag for record in records for flag in record.quality_flags}
    if any(
        record.interval_start < start or record.interval_end > end for record in records
    ):
        flags.add("interval_average_distributed")
    for metric in Metric:
        usable = []
        for record, values in prepared:
            value = values[metric]
            seconds = (
                min(end, record.interval_end) - max(start, record.interval_start)
            ).total_seconds()
            if value.value is not None and seconds > 0:
                usable.append((record, value, seconds))
        if not usable:
            candidates = [values[metric] for _, values in prepared]
            if candidates:
                reading = next(
                    (
                        candidate
                        for candidate in reversed(candidates)
                        if candidate.availability == "invalid"
                    ),
                    candidates[-1],
                )
                output[metric] = reading.model_copy(
                    update={
                        "quality_flags": sorted(
                            {
                                flag
                                for candidate in candidates
                                for flag in candidate.quality_flags
                            }
                        ),
                    }
                )
            continue
        total_seconds = sum(seconds for _, _, seconds in usable)
        # A mixed AC/DC aggregate would hide incompatible measurement boundaries.
        boundaries = {value.boundary for _, value, _ in usable}
        if len(boundaries) != 1:
            output[metric] = output[metric].model_copy(
                update={
                    "availability": "invalid",
                    "quality_flags": ["mixed_measurement_boundaries"],
                }
            )
            continue
        coverage[metric] = total_seconds / (end - start).total_seconds()
        if metric == Metric.soc:
            # SoC is an endpoint gauge, not an average power or an energy sum.
            observed = [
                (record, value)
                for record, value, _ in usable
                if record.interval_end <= end
            ]
            if not observed:
                coverage[metric] = 0.0
                continue
            _, reading = max(observed, key=lambda item: item[0].interval_end)
            value = reading.value
        else:
            reading = usable[-1][1]
            value = (
                sum(reading.value * seconds for _, reading, seconds in usable)
                / total_seconds
            )
        metric_flags = {
            flag for _, values in prepared for flag in values[metric].quality_flags
        }
        if coverage[metric] < 1:
            metric_flags.add("partial_coverage")
        output[metric] = Measurement(
            value=value,
            unit=UNITS[metric],
            requirement=reading.requirement,
            availability="available",
            origin="derived"
            if any(v.origin == "derived" for _, v, _ in usable)
            else "measured",
            boundary=reading.boundary,
            quality_flags=sorted(metric_flags),
        )
        if metric in energy:
            energy[metric] = sum(
                reading.value * seconds / 3600 for _, reading, seconds in usable
            )
    return HistoryPoint(
        interval_start=start,
        interval_end=end,
        measurements=output,
        coverage=coverage,
        energy_kwh=energy,
        source_modes=sorted({record.source_mode for record in records}),
        quality_flags=sorted(flags),
        sample_count=len(records),
        source_interval_seconds=sorted(
            {
                (record.interval_end - record.interval_start).total_seconds()
                for record in records
            }
        ),
    )


def history(
    connection, site_row, start: datetime, end: datetime, resolution: str
) -> EnergyHistory:
    if end <= start or end - start > timedelta(days=31):
        raise ApiError(
            422,
            "invalid_time_range",
            "Use a positive time range of at most 31 elapsed days",
        )
    site = site_from_row(site_row)
    rows = connection.execute(
        "SELECT payload FROM telemetry WHERE site_id=? AND interval_start<? AND interval_end>? "
        "ORDER BY interval_start LIMIT 10001",
        (site.site_id, stamp(end), stamp(start)),
    ).fetchall()
    if len(rows) > 10000:
        raise ApiError(
            422,
            "too_many_samples",
            "Narrow the requested time range (maximum 10000 source records)",
        )
    records = [TelemetryRecord.model_validate_json(row["payload"]) for row in rows]
    if resolution == "raw":
        points = [
            aggregate(
                site,
                [record],
                max(start, record.interval_start),
                min(end, record.interval_end),
            )
            for record in records
        ]
    else:
        seconds = {"15m": 900, "1h": 3600, "1d": 86400}[resolution]
        cursor = datetime.fromtimestamp(
            math.floor(start.timestamp() / seconds) * seconds, UTC
        )
        points = []
        # Walk sorted, non-overlapping source intervals once per intersecting bucket.
        offset = 0
        while cursor < end:
            lower, upper = (
                max(start, cursor),
                min(end, cursor + timedelta(seconds=seconds)),
            )
            while offset < len(records) and records[offset].interval_end <= lower:
                offset += 1
            selected = []
            index = offset
            while index < len(records) and records[index].interval_start < upper:
                selected.append(records[index])
                index += 1
            points.append(aggregate(site, selected, lower, upper))
            cursor += timedelta(seconds=seconds)
    return EnergyHistory(
        site_id=site.site_id, start=start, end=end, resolution=resolution, points=points
    )
