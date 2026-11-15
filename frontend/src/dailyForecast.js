// Daily production, consumption and profit estimate from the hourly weather forecast.
// Consumption follows a typical hourly shape for the kind of site; all values are estimates.

// Relative hourly weights (local hours 00..23). Only the shape matters; totals are scaled.
const SHAPES = {
  home: [
    0.6, 0.5, 0.5, 0.5, 0.5, 0.6, 0.9, 1.3, 1.2, 0.9, 0.8, 0.8, 0.9, 0.8, 0.8,
    0.9, 1.1, 1.5, 1.9, 2.0, 1.8, 1.5, 1.1, 0.8,
  ],
  office: [
    0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.6, 1.0, 1.6, 1.8, 1.8, 1.8, 1.7, 1.8, 1.8,
    1.7, 1.5, 1.0, 0.6, 0.5, 0.4, 0.4, 0.4, 0.4,
  ],
  hospitality: [
    0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.7, 0.9, 1.1, 1.4, 1.8, 2.2, 2.2, 1.8,
    1.3, 1.2, 1.5, 1.9, 2.2, 2.2, 1.8, 1.2, 0.7,
  ],
  industrial: [
    0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 1.0, 1.3, 1.3, 1.3, 1.3, 1.3, 1.3, 1.3, 1.3,
    1.3, 1.3, 1.3, 1.3, 1.3, 1.3, 1.0, 0.8, 0.7,
  ],
};

/** Typical hourly consumption shape for a home or a kind of business. */
export function consumptionShape(segment, businessType = "") {
  if (segment !== "business") return SHAPES.home;
  const type = (businessType || "").toLowerCase();
  if (/restaurant|bistro|caf[eé]|hotel|\bbar\b/.test(type)) return SHAPES.hospitality;
  if (
    /factory|warehouse|supermarket|plant|storage|logistics|depot|data cent|works/.test(
      type,
    )
  )
    return SHAPES.industrial;
  return SHAPES.office;
}

// Share of a solar site's use that its own panels typically cover (stated assumption).
export const TYPICAL_SELF_SUPPLY = 0.35;

/** Typical daily consumption from the site's monthly grid import (synthetic billing profile). */
export function typicalDailyConsumption(profile) {
  const monthly = profile?.monthly_import_kwh;
  if (!Number.isFinite(monthly) || monthly <= 0) return null;
  return monthly / 30 / (1 - TYPICAL_SELF_SUPPLY);
}

const hourOf = (time) => Number(String(time).slice(11, 13));

/**
 * hours: [{ time: "YYYY-MM-DDTHH:MM" (local), kw }] from dailyForecast().
 * Returns null when any production hour or an input is unknown (never guessed as zero).
 */
export function estimateDay(hours, dailyConsumption, shape, prices) {
  if (
    !hours?.length ||
    !Number.isFinite(dailyConsumption) ||
    dailyConsumption <= 0 ||
    !prices ||
    !Number.isFinite(prices.importPrice) ||
    !Number.isFinite(prices.exportPrice) ||
    hours.some((hour) => hour.kw == null || !Number.isFinite(hour.kw))
  )
    return null;
  const weights = hours.map((hour) => shape[hourOf(hour.time)] ?? 1);
  const totalWeight = weights.reduce((a, b) => a + b, 0);
  let production = 0,
    consumption = 0,
    selfUse = 0;
  hours.forEach((hour, index) => {
    const load = (dailyConsumption * weights[index]) / totalWeight;
    // An hourly mean power over one hour equals that hour's energy in kWh.
    production += hour.kw;
    consumption += load;
    selfUse += Math.min(hour.kw, load);
  });
  const exported = production - selfUse;
  const imported = consumption - selfUse;
  const savings = selfUse * prices.importPrice;
  const exportEarnings = exported * prices.exportPrice;
  return {
    production,
    consumption,
    selfUse,
    exported,
    imported,
    selfShare: consumption > 0 ? selfUse / consumption : 0,
    savings,
    exportEarnings,
    profit: savings + exportEarnings,
    gridCost: imported * prices.importPrice,
  };
}
