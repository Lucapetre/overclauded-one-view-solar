// Energy totals per period for the home chart. Missing data stays null, never zero.
export const PERIODS = {
  Today: { days: 1, bucket: "hour", title: "today, hour by hour" },
  Weekly: { days: 7, bucket: "day", title: "the last 7 days" },
  Monthly: { days: 30, bucket: "day", title: "the last 30 days" },
  Yearly: { days: 365, bucket: "month", title: "the last 12 months" },
};
const ZONE = "Europe/Bucharest";
const parts = (date, options) =>
  Object.fromEntries(
    new Intl.DateTimeFormat("en-GB", { timeZone: ZONE, ...options })
      .formatToParts(date)
      .map((part) => [part.type, part.value]),
  );

/** UTC instant of the most recent local midnight (exact except on DST-change days). */
export function localMidnight(asOf) {
  const p = parts(asOf, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
  return new Date(
    asOf.getTime() -
      ((+p.hour * 60 + +p.minute) * 60 + +p.second) * 1000 -
      asOf.getMilliseconds(),
  );
}

export function periodRange(period, asOf) {
  const spec = PERIODS[period];
  const from =
    spec.bucket === "hour"
      ? localMidnight(asOf)
      : new Date(localMidnight(asOf).getTime() - (spec.days - 1) * 86400000);
  return { from, to: asOf };
}

export function bucketLabel(date, bucket) {
  if (bucket === "hour") {
    const p = parts(date, { hour: "2-digit", hourCycle: "h23" });
    return { key: p.hour, label: `${p.hour}:00` };
  }
  const p = parts(date, { day: "2-digit", month: "short", year: "numeric" });
  return bucket === "day"
    ? { key: `${p.year}-${p.month}-${p.day}`, label: `${p.day} ${p.month}` }
    : { key: `${p.year}-${p.month}`, label: `${p.month} ${p.year.slice(2)}` };
}

/**
 * series: { name: [{ time: Date|string, kwh: number|null }] } ->
 * [{ label, name1: kWh|null, ... }] in time order.
 */
export function bucketEnergy(series, bucket) {
  const rows = new Map();
  const names = Object.keys(series);
  for (const name of names)
    for (const point of series[name]) {
      const date = new Date(point.time);
      if (Number.isNaN(date.getTime())) continue;
      const { key, label } = bucketLabel(date, bucket);
      if (!rows.has(key))
        rows.set(key, {
          label,
          order: date.getTime(),
          ...Object.fromEntries(names.map((n) => [n, null])),
        });
      const row = rows.get(key);
      row.order = Math.min(row.order, date.getTime());
      if (point.kwh != null && Number.isFinite(point.kwh))
        row[name] = (row[name] ?? 0) + point.kwh;
    }
  return [...rows.values()].sort((a, b) => a.order - b.order);
}

export const total = (points) => {
  const known = points.filter((point) => point.kwh != null);
  return known.length ? known.reduce((sum, point) => sum + point.kwh, 0) : null;
};

// Deterministic synthetic totals for the browser-only workflow demo.
export function demoBuckets(period, scale = 1) {
  const wave = (i, n) => 0.82 + 0.18 * Math.sin((i / n) * 9.4 + 1);
  if (period === "Weekly" || period === "Monthly") {
    const n = PERIODS[period].days;
    const end = Date.UTC(2026, 10, 14, 11);
    return Array.from({ length: n }, (_, i) => ({
      label: bucketLabel(new Date(end - (n - 1 - i) * 86400000), "day").label,
      production: +(24.8 * wave(i, n) * scale).toFixed(1),
      consumption: +(12.6 * (0.9 + 0.2 * Math.cos(i * 1.7)) * scale).toFixed(1),
    }));
  }
  const sun = [0.28, 0.4, 0.62, 0.8, 0.95, 1, 1, 0.93, 0.74, 0.52, 0.31, 0.24];
  return Array.from({ length: 12 }, (_, i) => {
    const month = (11 + i) % 12; // Dec 2025 … Nov 2026
    return {
      label: bucketLabel(new Date(Date.UTC(2025, 11 + i, 15)), "month").label,
      production: Math.round(880 * sun[month] * scale),
      consumption: Math.round((330 + 90 * (1 - sun[month])) * scale),
    };
  });
}
