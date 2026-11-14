// Presentation of computed API facts. No inferred diagnosis, savings, or AC/DC conversion.
export const metricLabels = {
  pv_power: "Solar production",
  pv_ac_kw: "Solar production · AC",
  pv_dc_kw: "Solar production · DC",
  pv_production_kw: "Solar production · boundary unspecified",
  inverter_ac_output_kw: "Inverter AC output",
  home_load: "Home consumption",
  household_load_kw: "Home consumption",
  grid_import: "Grid import",
  grid_import_kw: "Grid import",
  grid_export: "Grid export",
  grid_export_kw: "Grid export",
  battery_charge: "Battery charging",
  battery_charge_kw: "Battery charging",
  battery_discharge: "Battery discharge",
  battery_discharge_kw: "Battery discharge",
  battery_soc: "Battery state of charge",
  soc_pct: "Battery state of charge",
  temperature: "Device temperature",
  inverter_temperature_c: "Inverter temperature",
  battery_temperature_c: "Battery temperature",
  voltage: "Voltage",
  phase_voltage_v: "Phase voltage",
  ac_voltage_v: "AC voltage",
  interval_yield_kwh: "Generation energy",
  daily_yield_kwh: "Daily generation counter",
  lifetime_yield_kwh: "Lifetime generation counter",
};
export const label = (name) => metricLabels[name] || name.replaceAll("_", " ");
export const unit = (value) => (value === "pct" ? "%" : value);
export const number = (value, digits = 2) =>
  value == null || !Number.isFinite(value)
    ? "Unavailable"
    : new Intl.NumberFormat("en-GB", { maximumFractionDigits: digits }).format(
        value,
      );
export function when(value) {
  if (!value) return "Unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Unavailable"
    : new Intl.DateTimeFormat("en-GB", {
        timeZone: "Europe/Bucharest",
        day: "2-digit",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        timeZoneName: "short",
      }).format(date);
}
export const seriesKey = (frame) =>
  JSON.stringify([
    frame.metric_name,
    frame.endpoint_key,
    frame.device_id || "",
    frame.channel || "",
  ]);

export function providerStatus(snapshot) {
  const states = snapshot.source_health.map(
    (source) => source.freshness_status,
  );
  if (states.some((state) => state.includes("stale"))) return "stale";
  if (states.some((state) => state.startsWith("fresh"))) return "fresh";
  if (states.some((state) => state.includes("future"))) return "future";
  return "unavailable";
}

export function readings(snapshot, provider = false) {
  if (!snapshot) return [];
  if (!provider)
    return Object.entries(snapshot.measurements).map(([name, reading]) => ({
      key: name,
      name:
        name === "pv_power" && reading.boundary === "dc"
          ? "Solar production · DC"
          : label(name),
      value: reading.value,
      unit: reading.unit,
      state: reading.availability,
      detail: `${reading.origin} · ${reading.boundary} · ${reading.requirement}`,
      time: snapshot.interval_end,
      flags: reading.quality_flags || [],
      boundary: reading.boundary,
    }));
  return snapshot.frames.map((frame) => ({
    key: seriesKey(frame),
    name: label(frame.metric_name),
    value: frame.value,
    unit: unit(frame.unit),
    state: frame.frame_status,
    time: frame.frame_end_utc,
    detail: `${frame.aggregation} · ${number(frame.coverage_ratio * 100, 0)}% coverage${frame.channel ? ` · ${frame.channel}` : ""}`,
    flags: [
      frame.value_origin,
      frame.original_cadence_s
        ? `${frame.original_cadence_s}s source cadence`
        : "source cadence unknown",
    ],
    frame,
  }));
}

export function primaryReadings(snapshot, provider = false) {
  const all = readings(snapshot, provider);
  if (!provider) {
    const keys = [
      "pv_power",
      "home_load",
      "grid_import",
      "grid_export",
      "battery_soc",
      "temperature",
    ];
    return keys
      .map((key) => all.find((reading) => reading.key === key))
      .filter(Boolean);
  }
  const priorities = [
    ["pv_ac_kw", "pv_dc_kw", "pv_production_kw", "inverter_ac_output_kw"],
    ["household_load_kw"],
    ["grid_import_kw"],
    ["grid_export_kw"],
    ["soc_pct"],
    ["inverter_temperature_c"],
  ];
  return priorities.map((names) => {
    for (const name of names) {
      const found = all
        .filter((reading) => reading.frame.metric_name === name)
        .sort((a, b) =>
          (a.frame.device_id || "").localeCompare(b.frame.device_id || ""),
        );
      if (found.length) return found[0];
    }
    return {
      key: names[0],
      name: label(names[0]),
      value: null,
      unit: "",
      state: "unavailable",
      detail: "No supported reading",
      flags: [],
    };
  });
}

export function sourceInfo(record) {
  if (!record?.data) return { status: "loading", mode: "unknown", time: null };
  if (record.provider)
    return {
      status: providerStatus(record.data),
      mode: record.data.site.source_mode,
      time: record.data.site.as_of_utc,
    };
  return {
    status: record.data.freshness.status,
    mode: record.data.provenance?.source_mode || "unknown",
    time: record.data.freshness.evaluated_at,
  };
}

export function defaultRange(record) {
  const end = new Date(
    record?.provider
      ? record.data.site.as_of_utc
      : record?.data.interval_end || Date.now(),
  );
  const start = new Date(end.getTime() - 24 * 3600 * 1000);
  return {
    from: start.toISOString().slice(0, 16),
    to: end.toISOString().slice(0, 16),
  };
}

export function matchesSeries(frame, selected) {
  return seriesKey(frame) === seriesKey(selected);
}

// Break the line at missing frames instead of drawing across a data gap.
export function chartSegments(points) {
  const segments = [];
  let current = [];
  for (const point of points) {
    if (point.value == null || !Number.isFinite(point.value)) {
      if (current.length) segments.push(current);
      current = [];
    } else current.push(point);
  }
  if (current.length) segments.push(current);
  return segments;
}

export function errorMessage(error) {
  return (
    error?.detail?.message ||
    error?.message ||
    "Unable to reach the service. Please try again."
  );
}
