// Pure presentation of the customer energy overview and periods endpoints
// (GET /sites/{id}/energy/overview and /energy/periods). No React, no fetch. Missing values
// stay null with their reason; consumption is always labelled "derived"; synthetic seasonal
// profile buckets are labelled and never presented as measured.
import { bucharestParts } from "./bucharestTime.js";

export const PERIOD_CHOICES = [
  { key: "today", label: "Today", title: "today, hour by hour" },
  { key: "week", label: "Week", title: "the last 7 days" },
  { key: "month", label: "Month", title: "the last 30 days" },
  { key: "year", label: "Year", title: "the last 12 months" },
];

const kw = (value) =>
  value == null ? null : new Intl.NumberFormat("en-GB", { maximumFractionDigits: value < 10 ? 2 : 1 }).format(value);
export const fmtNumber = (value, digits = 1) =>
  value == null || !Number.isFinite(value)
    ? "—"
    : new Intl.NumberFormat("en-GB", { maximumFractionDigits: digits }).format(value);

const REASONS = {
  no_grid_meter: "This site has no grid meter",
  grid_frame_unknown: "The grid meter did not report this interval",
  pv_unknown: "No solar reading for this interval",
};
export const reasonText = (code) =>
  REASONS[code] || (code ? String(code).replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase()) : "Not available");

/** One display card from an OverviewMetric: value or the plain reason; origin shown as a label. */
export function metricCard(name, metric, { consumption = false } = {}) {
  const has = metric && metric.value != null;
  return {
    name,
    value: has ? kw(metric.value) : null,
    unit: has ? metric.unit : "",
    origin: has ? (consumption ? "derived" : metric.origin) : null,
    reason: has ? null : reasonText(metric?.reason),
    basis: metric?.basis || null,
  };
}

/** The four Home cards, in order: solar, consumption (derived), grid import, grid export. */
export function overviewCards(overview, accountType = "home") {
  const consumptionName = accountType === "business" ? "Business consumption" : "Home consumption";
  if (!overview)
    return [
      { name: "Solar production" },
      { name: consumptionName },
      { name: "Grid import" },
      { name: "Grid export" },
    ].map((c) => ({ ...c, value: null, unit: "", origin: null, reason: "Loading…", basis: null }));
  return [
    metricCard("Solar production", overview.pv),
    metricCard(consumptionName, overview.consumption, { consumption: true }),
    metricCard("Grid import", overview.grid_import),
    metricCard("Grid export", overview.grid_export),
  ];
}

/** Periods → rows for EnergyBars ({label, production, consumption}) plus chart facts. */
export function chartBuckets(periods) {
  const buckets = (periods?.buckets || []).map((b) => ({
    label: b.label,
    production: b.production_kwh,
    consumption: b.consumption_kwh,
    synthetic: b.origin === "synthetic_profile",
  }));
  return {
    buckets,
    synthetic: Boolean(periods?.synthetic),
    syntheticCount: buckets.filter((b) => b.synthetic).length,
    note: periods?.note || "",
    totals: periods?.totals || null,
  };
}

/** Short rows for the "Show details" table: one line per bucket with grid import/export too. */
export function detailRows(periods) {
  return (periods?.buckets || []).map((b) => ({
    key: b.start,
    label: b.label,
    production: b.production_kwh,
    consumption: b.consumption_kwh,
    gridImport: b.grid_import_kwh,
    gridExport: b.grid_export_kwh,
    origin:
      b.origin === "synthetic_profile" ? "Typical profile" : b.origin === "derived" ? "Measured, derived" : "Measured",
    partial: b.complete === false,
  }));
}

/** Band of a contract at an instant (Bucharest weekday and minute of day), or null. */
export function bandAt(bands = [], iso) {
  const parts = bucharestParts(iso);
  if (!parts) return null;
  const [y, m, d] = parts.date.split("-").map(Number);
  const [h, min] = parts.time.split(":").map(Number);
  const weekday = ((new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7) + 1;
  const minute = h * 60 + min;
  return (
    bands.find(
      (b) =>
        (b.days || []).includes(weekday) &&
        minute >= b.start_minute &&
        (minute < b.end_minute || b.end_minute === 1440 || b.end_minute < b.start_minute),
    ) || null
  );
}

/**
 * Estimated cost so far today from the hourly grid import and export and the contract:
 * time-of-use bands when present, else the fixed prices. Returns { ron, importKwh, basis } or
 * null when an input is missing. It is an estimate, not a bill.
 */
export function estimateDayCost(periods, contract, bands = []) {
  const list = (periods?.buckets || []).filter((b) => b.origin !== "synthetic_profile");
  if (!list.length || !contract) return null;
  let ron = 0,
    importKwh = 0,
    known = 0;
  for (const b of list) {
    if (b.grid_import_kwh == null) continue;
    const band = bands.length ? bandAt(bands, b.start) : null;
    const rate = band ? band.import_rate_ron_kwh : contract.import_price_ron_kwh;
    const exportRate = band ? band.export_value_ron_kwh : contract.export_price_ron_kwh;
    if (rate == null) return null;
    ron += b.grid_import_kwh * rate - (b.grid_export_kwh || 0) * (exportRate || 0);
    importKwh += b.grid_import_kwh;
    known += 1;
  }
  if (!known) return null;
  return {
    ron,
    importKwh,
    basis: bands.length
      ? "Hourly grid import and export × your contract's time bands"
      : "Grid import and export × your contract's fixed prices",
  };
}

/** Share of the day's consumption covered by solar: self-consumption / consumption, from totals. */
export function solarCoverage(totals) {
  if (!totals || totals.consumption_kwh == null || totals.consumption_kwh <= 0 || totals.production_kwh == null) return null;
  const direct = Math.max(0, totals.production_kwh - (totals.grid_export_kwh || 0));
  return Math.min(1, direct / totals.consumption_kwh);
}

/** Business header tiles from today's periods, the overview and the contract. */
export function businessHeader(periodsToday, overview, contract, bands) {
  const totals = periodsToday?.totals || null;
  const cost = estimateDayCost(periodsToday, contract, bands);
  const share = totals?.self_consumption_share ?? overview?.today?.self_consumption_share ?? null;
  const coverage = solarCoverage(totals);
  const pct = (v) => (v == null ? null : `${Math.round(v * 100)} %`);
  return {
    cost,
    tiles: [
      {
        key: "cost",
        label: "Today's cost estimate",
        value: cost ? `${fmtNumber(cost.ron, 2)} RON` : null,
        note: cost ? `${cost.basis}. An estimate, not a bill.` : "Needs your contract prices and grid meter readings",
      },
      {
        key: "peak",
        label: "Peak demand today",
        value: totals?.peak_kw != null ? `${fmtNumber(totals.peak_kw, 1)} kW` : null,
        note: totals?.peak_kw != null ? "Highest consumption in a single interval (derived)" : "Not available yet",
      },
      {
        key: "self",
        label: "Self-consumption",
        value: pct(share),
        note: share != null ? "Share of your solar energy used on site" : "Not available yet",
      },
      {
        key: "coverage",
        label: "Solar coverage",
        value: pct(coverage),
        note: coverage != null ? "Share of today's consumption met by your own solar" : "Not available yet",
      },
    ],
  };
}

/** Footnote under the chart for synthetic seasonal profile buckets. */
export function profileNote(chart) {
  if (!chart.syntheticCount) return null;
  return chart.syntheticCount === chart.buckets.length
    ? "Typical seasonal profile (synthetic), not measured readings."
    : `${chart.syntheticCount} of ${chart.buckets.length} periods use a typical seasonal profile (synthetic); the rest are measured.`;
}

/** Offers the customer may still accept, newest first (a short "New offer" teaser). */
export function newOffer(offers = [], mine = []) {
  const taken = new Set(mine.filter((o) => o.status === "active" || o.status === "accepted").map((o) => o.offer_id));
  return [...offers].filter((o) => !taken.has(o.offer_id)).sort((a, b) => String(b.published_at || "").localeCompare(String(a.published_at || "")))[0] || null;
}
