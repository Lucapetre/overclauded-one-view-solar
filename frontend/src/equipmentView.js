// Pure presentation for the customer equipment evidence cards (Grid, Battery,
// Solar conditions) built from GET /sites/{id}/equipment/summary. Values, freshness
// and reason codes come from the backend; this only chooses plain words.
import { ageText, humanize, localDateTime, reasonText } from "./planView.js";

export const FAMILY_ORDER = ["meter", "battery", "weather"];

const TITLES = { meter: "Grid", battery: "Battery", weather: "Solar conditions" };
const CAPABILITY = {
  meter: "grid_energy_verified",
  battery: "battery_assisted_planning",
  weather: "irradiance_explanation",
};
const NONE = {
  meter: "No grid meter at your connection point is connected.",
  battery: "No battery is connected to this site.",
  weather: "No sunlight sensor is linked to this site.",
};

const UNITS = { pct: "%", degC: "°C", "W/m2": "W/m²", none: "" };
export const unitText = (unit) => (unit in UNITS ? UNITS[unit] : unit || "");

const number = (value, digits = 1) =>
  Number.isFinite(value)
    ? new Intl.NumberFormat("en-GB", { maximumFractionDigits: digits }).format(value)
    : "—";

/** Plain description of the selected device. */
export function deviceText(family, asset) {
  if (!asset) return null;
  if (family === "meter")
    return asset.boundary === "grid_pcc"
      ? "Grid meter at your connection point"
      : "Grid meter (location not at the connection point)";
  if (family === "battery") return "Battery monitor: charge level, power and limits";
  if (family === "weather") {
    const plane = asset.mounting === "poa" ? "in the plane of your panels" : asset.mounting ? `(${humanize(asset.mounting).toLowerCase()} mounting)` : "";
    // A shared station's tilted sensor is not necessarily aligned with this site's panels.
    return asset.shared_resource
      ? `Shared weather station nearby${asset.mounting === "poa" ? ", tilted sunlight sensor" : ""}`
      : `Sunlight sensor on your site, ${plane}`.replace(/, $/, "");
  }
  return humanize(asset.role);
}

/** Value origin → "measured" | "derived" | "assumed" (synthetic observations count as measured). */
export function originKind(origin) {
  const value = String(origin || "");
  if (/assum|declar|config|default/.test(value)) return "assumed";
  if (/deriv|estim|integrat|model|forecast/.test(value)) return "derived";
  return "measured";
}

/** One latest value → { label, value, unit, sentence }. */
export function valueText(family, item) {
  const v = item.value;
  const unit = unitText(item.unit);
  switch (item.metric) {
    case "grid_net_kw":
      if (!Number.isFinite(v)) return { label: "Grid exchange", value: "—", unit, sentence: "Grid exchange unavailable" };
      if (Math.abs(v) < 0.05)
        return { label: "Grid exchange", value: number(Math.abs(v), 2), unit, sentence: "Almost no grid exchange" };
      return v > 0
        ? { label: "Taking from the grid", value: number(v, 2), unit, sentence: `Taking ${number(v, 2)} kW from the grid` }
        : { label: "Sending to the grid", value: number(-v, 2), unit, sentence: `Sending ${number(-v, 2)} kW to the grid` };
    case "soc_pct":
      return { label: "Charge level", value: number(v, 0), unit, sentence: `Charge level ${number(v, 0)} %` };
    case "battery_net_kw":
      if (!Number.isFinite(v) || Math.abs(v) < 0.05)
        return { label: "Battery power", value: number(Math.abs(v ?? NaN), 2), unit, sentence: "Battery idle" };
      return v > 0
        ? { label: "Discharging", value: number(v, 2), unit, sentence: `Discharging ${number(v, 2)} kW` }
        : { label: "Charging", value: number(-v, 2), unit, sentence: `Charging ${number(-v, 2)} kW` };
    case "battery_max_discharge_current_a":
      return { label: "Discharge limit (battery-reported)", value: number(v, 0), unit, sentence: `Discharge limit ${number(v, 0)} A` };
    case "battery_max_charge_current_a":
      return { label: "Charge limit (battery-reported)", value: number(v, 0), unit, sentence: `Charge limit ${number(v, 0)} A` };
    case "irradiance_wm2":
      return { label: "Sunlight on the panel plane", value: number(v, 0), unit, sentence: `Sunlight ${number(v, 0)} W/m²` };
    case "module_temperature_c":
      return { label: "Panel temperature", value: number(v, 1), unit, sentence: `Panels at ${number(v, 1)} °C` };
    case "ambient_temperature_c":
      return { label: "Air temperature", value: number(v, 1), unit, sentence: `Air ${number(v, 1)} °C` };
    default:
      return { label: humanize(item.metric), value: number(v, 2), unit, sentence: `${humanize(item.metric)} ${number(v, 2)} ${unit}` };
  }
}

const FRESHNESS = {
  fresh: { label: "Up to date", tone: "green" },
  stale: { label: "Delayed", tone: "orange" },
  missing: { label: "No recent readings", tone: "orange" },
};

/**
 * Capability decision + family → card state:
 * ok | limited | stale | partial | not_installed.
 */
export function cardState(family, capability) {
  if (!family || family.availability === "not_installed")
    return { state: "not_installed", label: "Not connected", tone: "" };
  if (family.availability === "declared_not_observed")
    return { state: "partial", label: "Declared, no readings", tone: "orange" };
  const fresh = FRESHNESS[family.freshness?.status] || { label: humanize(family.freshness?.status), tone: "" };
  if (family.freshness?.status !== "fresh") return { state: "stale", ...fresh };
  if (capability && !capability.available) return { state: "limited", label: "Up to date · limited use", tone: "yellow" };
  return { state: "ok", ...fresh };
}

/** Capability reason sentences shown on the card (the "available" codes say what was used). */
function capabilityLines(capability) {
  if (!capability) return [];
  const codes = capability.reason_codes || [];
  const shown = capability.available ? codes : codes.filter((code) => code !== "grid_solar_only_plan");
  const lines = [...new Set(shown.map(reasonText))];
  // An exclusion is the headline; supporting details follow.
  const lead = (text) => (text.startsWith("Battery contribution excluded") ? 0 : 1);
  return lines.sort((a, b) => lead(a) - lead(b));
}

const DECLARED = {
  available: "declared and reporting",
  not_declared: "not provided by this device",
  declared_not_observed: "declared, not reporting",
};

/** Full card model for one family. */
export function familyCard(summary, familyName) {
  const family = summary?.families?.find((item) => item.family === familyName) || null;
  const capability = summary?.capabilities?.find((item) => item.capability === CAPABILITY[familyName]) || null;
  const state = cardState(family, capability);
  const asset =
    family?.assets?.find((item) => item.asset_id === family.selected_source) || family?.assets?.[0] || null;
  const values = (family?.latest || []).map((item) => ({ ...item, text: valueText(familyName, item) }));
  const primary = values[0] || null;
  const lastUpdate = family?.freshness?.last_observed_at || null;
  const measured = values.filter((item) => originKind(item.origin) === "measured");
  const derived = values.filter((item) => originKind(item.origin) !== "measured");
  const assumptions = [];
  for (const [key, value] of Object.entries(family?.declared_capabilities || {}))
    if (value !== "available" && value !== "not_declared") assumptions.push(`${humanize(key.replace(/_available$/, ""))}: ${DECLARED[value] || humanize(value)}`);
  if (asset?.link_basis) assumptions.push(`Link to your site: ${asset.link_basis}.`);
  for (const note of family?.notes || []) assumptions.push(note);
  return {
    family: familyName,
    title: TITLES[familyName],
    ...state,
    device: state.state === "not_installed" ? NONE[familyName] : deviceText(familyName, asset),
    primary,
    secondary: values.slice(1),
    lastUpdate: lastUpdate ? localDateTime(lastUpdate) : null,
    age: ageText(family?.freshness?.age_seconds),
    reasons: capabilityLines(capability),
    capabilityAvailable: capability ? capability.available : null,
    measured,
    derived,
    assumptions,
    declared: Object.entries(family?.declared_capabilities || {}).map(([key, value]) => ({
      name: humanize(key.replace(/_available$/, "")),
      state: DECLARED[value] || humanize(value),
    })),
    technical: {
      asset_id: asset?.asset_id || null,
      profile_id: asset?.profile_id || null,
      boundary: asset?.boundary || null,
      evidence_ids: [...values.map((item) => item.evidence_id), ...(capability?.evidence_ids || [])],
    },
  };
}

/** True when the site has any component equipment (otherwise show the quiet state). */
export function hasEquipment(summary) {
  return Boolean(
    summary &&
      summary.source_mode !== "none" &&
      (summary.families || []).some((family) => family.availability !== "not_installed"),
  );
}

/** "SYNTHETIC replay evidence…" label → short badge text. */
export function evidenceLabel(summary) {
  if (!summary) return "";
  if (summary.source_mode === "synthetic") return "Synthetic equipment data";
  if (summary.source_mode === "replay") return "Recorded replay data";
  return "";
}
