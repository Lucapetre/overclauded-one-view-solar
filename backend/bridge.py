"""Equipment-to-decision bridge: the only place planner and offers read measured evidence.

Only metrics with a compatible unit, boundary, aggregation and coverage cross this bridge, and
every derived input names the observations or frames behind it (evidence ids). Two sources
exist:

* the compact `telemetry` stream (one designated aggregate AC stream per site), and
* imported component evidence (authoritative PCC meter interval energy, battery state and
  irradiance frames), see `backend/components.py`.

Rules kept here: a hybrid inverter's net AC output is never PV generation; battery DC power
is never grid energy; a gateway mirror of the authoritative meter is never added to it.
Data after the analytical (scenario) clock is not known yet and is never read.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from backend.clock import scenario_now
from backend.db import site_from_row, stamp
from backend.energy import readings, records_between
from backend.models import Metric
from backend.offers_math import MeterInterval
from backend.solar_forecast import Sample

SLOT = timedelta(minutes=15)
GRID_METRICS = {"consume": Metric.grid_import, "export": Metric.grid_export}


@dataclass
class MeterSeries:
    """Directional grid energy per interval for one site, with its provenance."""

    metric: str
    source: str  # "component_meter" | "compact_telemetry" | "none"
    intervals: list[MeterInterval] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    boundary: str | None = None
    note: str | None = None

    def energy_kwh(self) -> float | None:
        known = [item for item in self.intervals if item.kw is not None]
        if not known:
            return None
        return float(
            sum(
                item.kw * Decimal((item.end - item.start).total_seconds()) / 3600
                for item in known
            )
        )

    def coverage(self, start: datetime, end: datetime) -> float:
        span = (end - start).total_seconds()
        if span <= 0:
            return 0.0
        covered = sum(
            (min(end, item.end) - max(start, item.start)).total_seconds()
            for item in self.intervals
            if item.kw is not None and item.end > start and item.start < end
        )
        return max(0.0, min(1.0, covered / span))


def _cap(connection, end: datetime) -> datetime:
    known = scenario_now(connection)
    return min(end, known) if known else end


def compact_meter_series(
    connection, site_id: str, metric: Metric, start: datetime, end: datetime
) -> MeterSeries:
    """The compact aggregate AC stream: kW interval averages of grid import or export."""
    series = MeterSeries(metric.value, "compact_telemetry", boundary="ac")
    known = scenario_now(connection)
    upper = min(end, known) if known else end
    if upper <= start:
        return series
    for record in records_between(connection, site_id, start, upper):
        if known and record.interval_end > known:
            continue  # not complete at the analytical (scenario) time yet
        reading = record.measurements.get(metric)
        available = (
            reading is not None
            and reading.availability == "available"
            and reading.value is not None
            and reading.boundary == "ac"
        )
        series.intervals.append(
            MeterInterval(
                start=record.interval_start,
                end=record.interval_end,
                kw=Decimal(str(reading.value)) if available else None,
            )
        )
        series.evidence_ids.append(f"telemetry:{record.source_id}:{record.record_id}")
    return series


def component_meter_series(
    connection, site_id: str, metric: Metric, start: datetime, end: datetime
) -> MeterSeries | None:
    """Authoritative imported PCC meter energy, or None when the site has none."""
    from backend import components  # local import: components imports this module

    return components.grid_meter_series(
        connection, site_id, metric, start, _cap(connection, end)
    )


def meter_series(
    connection, site_id: str, metric: Metric, start: datetime, end: datetime
) -> MeterSeries:
    """Authoritative grid energy for offers and plan progress.

    An imported authoritative component meter wins for its site; otherwise the compact
    aggregate stream is used. Sources are never summed.
    """
    component = component_meter_series(connection, site_id, metric, start, end)
    if component is not None:
        return component
    return compact_meter_series(connection, site_id, metric, start, end)


def offer_meter_intervals(
    connection, site_id: str, offer_type: str, start: datetime, end: datetime
) -> list[MeterInterval]:
    """Consume offers are fulfilled from grid import, export offers from grid export."""
    return meter_series(
        connection, site_id, GRID_METRICS[offer_type], start, end
    ).intervals


def window_label(start: datetime, end: datetime) -> str:
    return f"{stamp(start)}/{stamp(end)}"


# ---------------------------------------------------------------- planning inputs

# AC PV generation metrics of provider frames. `inverter_ac_output_kw` is PV only on a
# site without a hybrid (battery) inverter; a hybrid's net output is never PV.
PV_AC_METRICS = ("pv_ac_kw", "pv_production_kw")
INVERTER_AC = "inverter_ac_output_kw"
LOAD_METRICS = ("household_load_kw",)
MIN_FRAME_COVERAGE = 0.5


@dataclass
class History:
    samples: list = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    source: str = "none"
    plane: tuple[float, float] | None = None


@dataclass
class BatteryCapability:
    params: (
        object | None
    )  # planner.BatteryParams when battery-assisted planning is available
    reason_codes: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def view(self) -> dict:
        keys = (
            "soc_pct",
            "soc_as_of",
            "usable_capacity_kwh",
            "reserve_pct",
            "charge_limit_kw",
            "discharge_limit_kw",
            "charge_efficiency",
            "discharge_efficiency",
        )
        return {key: self.details.get(key) for key in keys}


def _provider_binding(connection, site_id: str):
    return connection.execute(
        "SELECT import_id, identity FROM provider_sites WHERE site_id=?", (site_id,)
    ).fetchone()


def _provider_frames(connection, site_id, metrics, start, end):
    binding = _provider_binding(connection, site_id)
    if not binding:
        return []
    placeholders = ",".join("?" for _ in metrics)
    return connection.execute(
        "SELECT metric_name, endpoint_key, device_id, frame_start, frame_end, payload "
        "FROM provider_frames WHERE site_id=? AND import_id=? "
        f"AND metric_name IN ({placeholders}) AND frame_start>=? AND frame_end<=? "
        "ORDER BY frame_start LIMIT 5000",
        (site_id, binding["import_id"], *metrics, stamp(start), stamp(end)),
    ).fetchall()


def _hybrid(connection, site_id: str) -> bool:
    binding = _provider_binding(connection, site_id)
    if not binding:
        return True
    capabilities = json.loads(binding["identity"]).get("capabilities", {})
    return capabilities.get("battery") != "not_installed"


def _frame_samples(rows) -> list[Sample]:
    samples = {}
    for row in rows:
        frame = json.loads(row["payload"])
        if frame.get("value") is None or frame.get("unit") != "kW":
            continue
        if frame.get("coverage_ratio", 0) < MIN_FRAME_COVERAGE:
            continue
        start = datetime.fromisoformat(row["frame_start"])
        if start in samples:
            continue  # the first preferred metric wins; sources are never summed
        samples[start] = Sample(
            start,
            float(frame["value"]),
            f"frame:{row['endpoint_key']}:{row['metric_name']}:{row['frame_start']}",
        )
    return [samples[key] for key in sorted(samples)]


def _compact_samples(connection, site_id, metric: Metric, start, end) -> list[Sample]:
    row = connection.execute(
        "SELECT * FROM sites WHERE site_id=?", (site_id,)
    ).fetchone()
    if not row:
        return []
    site = site_from_row(row)
    samples = []
    for record in records_between(connection, site_id, start, end, limit=2000):
        if record.interval_end > end:
            continue
        value = readings(site, record).get(metric)
        if value is None or value.value is None:
            continue
        if metric != Metric.soc and value.boundary != "ac":
            continue
        # Interval averages are only used as 15-minute samples when they are 15 minutes.
        if metric != Metric.soc and record.interval_end - record.interval_start != SLOT:
            continue
        samples.append(
            Sample(
                record.interval_start,
                value.value,
                f"telemetry:{record.source_id}:{record.record_id}",
            )
        )
    return samples


def pv_history(connection, site_id: str, start: datetime, end: datetime) -> History:
    """Measured AC PV generation (kW per 15 minutes) up to the analytical time."""
    end = _cap(connection, end)
    history = History()
    rows = _provider_frames(connection, site_id, PV_AC_METRICS, start, end)
    if not rows and not _hybrid(connection, site_id):
        rows = _provider_frames(connection, site_id, (INVERTER_AC,), start, end)
    if rows:
        history.samples = _frame_samples(rows)
        history.source = "provider_frames_ac_pv"
    else:
        history.samples = _compact_samples(connection, site_id, Metric.pv, start, end)
        history.source = "compact_telemetry" if history.samples else "none"
    if not history.samples:
        history.reasons.append("no_measured_ac_pv_history")
    return history


def load_history(connection, site_id: str, start: datetime, end: datetime) -> History:
    """Measured or derived whole-site load (kW per 15 minutes) up to the analytical time."""
    from backend import components

    end = _cap(connection, end)
    history = History()
    derived = components.derived_load_samples(connection, site_id, start, end)
    if derived:
        history.samples, history.source = derived, "component_meter_balance"
        return history
    rows = _provider_frames(connection, site_id, LOAD_METRICS, start, end)
    if rows:
        history.samples = _frame_samples(rows)
        history.source = "provider_frames_site_load"
    else:
        history.samples = _compact_samples(connection, site_id, Metric.load, start, end)
        history.source = "compact_telemetry" if history.samples else "none"
    if not history.samples:
        history.reasons.append("no_measured_site_load_history")
    return history


def irradiance_recent(connection, site_id: str, start: datetime, end: datetime):
    """Recent POA irradiance on a registered plane (None when no compatible sensor)."""
    from backend import components

    return components.poa_history(connection, site_id, start, _cap(connection, end))


def battery_capability(connection, site_id: str, now: datetime) -> BatteryCapability:
    """Battery-assisted planning only with fresh SoC, capacity, reserve, limits, efficiency."""
    from backend import components

    capability = components.battery_capability(connection, site_id, now)
    if capability is not None:
        return capability
    soc = _compact_samples(
        connection, site_id, Metric.soc, now - timedelta(hours=2), _cap(connection, now)
    )
    if soc:
        # A state of charge alone is no capacity, reserve or power-limit basis.
        return BatteryCapability(
            None,
            ["battery_limits_unavailable", "grid_solar_only_plan"],
            [soc[-1].evidence_id],
        )
    return BatteryCapability(None, ["no_battery_evidence", "grid_solar_only_plan"])


def planning_equipment(connection, site_id: str) -> dict:
    from backend import components

    return components.planning_equipment(connection, site_id)


def source_freshness(connection, site_id: str, now: datetime) -> list[dict]:
    """Freshness of the sources behind a decision, judged at the analytical time."""
    from backend import components

    result = components.source_freshness(connection, site_id, now)
    site = connection.execute(
        "SELECT stale_after_seconds FROM sites WHERE site_id=?", (site_id,)
    ).fetchone()
    stale_after = site["stale_after_seconds"] if site else 2700
    latest = connection.execute(
        "SELECT MAX(interval_end) FROM telemetry WHERE site_id=? AND interval_end<=?",
        (site_id, stamp(now)),
    ).fetchone()[0]
    if latest:
        last = datetime.fromisoformat(latest)
        age = (now - last).total_seconds()
        result.append(
            {
                "source": "compact_telemetry",
                "status": "fresh" if age <= stale_after else "stale",
                "last_observed_at": last,
                "age_seconds": age,
            }
        )
    binding = _provider_binding(connection, site_id)
    if binding:
        latest = connection.execute(
            "SELECT MAX(frame_end) FROM provider_frames WHERE site_id=? AND import_id=? "
            "AND frame_end<=?",
            (site_id, binding["import_id"], stamp(now)),
        ).fetchone()[0]
        last = datetime.fromisoformat(latest) if latest else None
        age = (now - last).total_seconds() if last else None
        result.append(
            {
                "source": "inverter_frames",
                "status": "missing"
                if last is None
                else ("fresh" if age <= stale_after else "stale"),
                "last_observed_at": last,
                "age_seconds": age,
            }
        )
    return result


def is_synthetic(connection, site_id: str) -> bool:
    binding = _provider_binding(connection, site_id)
    if binding:
        return json.loads(binding["identity"]).get("source_mode") == "synthetic"
    row = connection.execute(
        "SELECT payload FROM telemetry WHERE site_id=? ORDER BY interval_end DESC LIMIT 1",
        (site_id,),
    ).fetchone()
    return bool(row) and json.loads(row["payload"]).get("source_mode") != "live"
