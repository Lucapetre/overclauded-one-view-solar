// Pure presentation helpers for the business task planner, contract time bands and
// the replay indicator. No React, no fetch: every function maps backend values to
// plain-language text. Costs are backend estimates; nothing here computes savings.
import { formatRon } from "./money.js";
import { bucharestParts, bucharestToUtc, TIME_ZONE } from "./bucharestTime.js";

/* ------------------------------------------------------------------ times */

const dateTimeFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: TIME_ZONE,
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});
const dayFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: TIME_ZONE,
  weekday: "short",
  day: "numeric",
  month: "short",
});
const timeFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: TIME_ZONE,
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

const instant = (value) => {
  const ms = value instanceof Date ? value.getTime() : Date.parse(value ?? "");
  return Number.isFinite(ms) ? ms : null;
};

/** "17 Jul 2026, 07:30" in Bucharest time, or "unknown time". */
export function localDateTime(value) {
  const ms = instant(value);
  return ms == null ? "unknown time" : dateTimeFormat.format(ms);
}

/** "07:30" in Bucharest time. */
export function localTime(value) {
  const ms = instant(value);
  return ms == null ? "--:--" : timeFormat.format(ms);
}

/** "Fri 17 Jul, 11:00–13:00", or across midnight "Fri 17 Jul, 23:00 – Sat 18 Jul, 01:00". */
export function slotText(start, end) {
  const a = instant(start),
    b = instant(end);
  if (a == null) return "no time";
  if (b == null) return `${dayFormat.format(a)}, ${timeFormat.format(a)}`;
  const sameDay = bucharestParts(new Date(a)).date === bucharestParts(new Date(b - 1)).date;
  return sameDay
    ? `${dayFormat.format(a)}, ${timeFormat.format(a)}–${timeFormat.format(b)}`
    : `${dayFormat.format(a)}, ${timeFormat.format(a)} – ${dayFormat.format(b)}, ${timeFormat.format(b)}`;
}

/** "2 h", "1 h 30 min", "45 min". */
export function durationText(minutes) {
  if (!Number.isFinite(minutes) || minutes <= 0) return "—";
  const total = Math.round(minutes);
  const h = Math.floor(total / 60),
    m = total % 60;
  if (!h) return `${m} min`;
  return m ? `${h} h ${m} min` : `${h} h`;
}

/** Age in seconds → "just now", "12 min ago", "3 h ago". */
export function ageText(seconds) {
  if (!Number.isFinite(seconds)) return "";
  if (seconds < 90) return "just now";
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} days ago`;
}

/* ------------------------------------------------------------------ replay badge */

/**
 * Text for the replay indicator, or null in live mode (nothing extra is shown).
 * → { text: "Synthetic replay · 17 Jul 2026, 07:30", scenario, detail }
 */
export function replayBadge(clock) {
  if (!clock || clock.mode !== "scenario") return null;
  const time = localDateTime(clock.analytical_now);
  return {
    text: `${clock.synthetic === false ? "Replay" : "Synthetic replay"} · ${time}`,
    scenario: clock.scenario_id || "unnamed scenario",
    detail: `Scenario ${clock.scenario_id || "unnamed"}: all plans, freshness and progress use this replay time (Europe/Bucharest), not today's date.`,
  };
}

/* ------------------------------------------------------------------ money */

/** RON float (backend estimate) → "9.62 RON"; null → null. */
export function ron(value, options) {
  if (value == null || !Number.isFinite(value)) return null;
  return formatRon(Math.round(value * 100), options);
}

/** Cost with the "unknown" wording when the backend could not estimate it. */
export function costText(value, range) {
  const exact = ron(value);
  if (exact) return exact;
  if (range && Number.isFinite(range.low_ron) && Number.isFinite(range.high_ron))
    return `${ron(range.low_ron)} to ${ron(range.high_ron)}`;
  return "unknown";
}

/**
 * Plain sentence for the estimated difference (recommended − baseline).
 * → { text, tone: "good" | "bad" | "neutral" | "unknown" }
 */
export function differenceText(difference, baselineKind) {
  const against =
    baselineKind === "usual_time" ? "your usual time" : baselineKind === "run_now" ? "running now" : "the time it was compared with";
  if (difference == null || !Number.isFinite(difference))
    return {
      text: `Estimated difference versus ${against} is unknown.`,
      tone: "unknown",
    };
  const amount = ron(Math.abs(difference));
  if (Math.abs(difference) < 0.005)
    return { text: `About the same estimated cost as ${against}.`, tone: "neutral" };
  return difference < 0
    ? { text: `Estimated ${amount} less than ${against}`, tone: "good" }
    : { text: `Estimated ${amount} more than ${against}`, tone: "bad" };
}

/* ------------------------------------------------------------------ task states */

const STATES = {
  suggested: { label: "Suggestion", tone: "yellow", detail: "Not accepted yet. Nothing is scheduled." },
  accepted: { label: "Accepted plan", tone: "green", detail: "You committed to this time. It stays fixed until you review it." },
  running: { label: "Running now", tone: "green", detail: "The agreed time has started. Progress uses your grid meter." },
  completed: { label: "Completed", tone: "", detail: "The agreed time has ended. Measured energy is shown below." },
  cancelled: { label: "Cancelled", tone: "", detail: "This task was cancelled." },
};

/** → { label, tone, detail } for a task status. */
export function taskState(status) {
  return STATES[status] || { label: humanize(status || "unknown"), tone: "", detail: "" };
}

/** Pick the task to feature on Home: running, then accepted, then the newest suggestion. */
export function nextTask(tasks) {
  if (!Array.isArray(tasks)) return null;
  const order = ["running", "accepted", "suggested"];
  for (const status of order) {
    const found = tasks
      .filter((task) => task.status === status)
      .sort((a, b) => (instant(a.earliest_start) ?? 0) - (instant(b.earliest_start) ?? 0));
    if (found.length) return found[0];
  }
  return null;
}

/* ------------------------------------------------------------------ reason codes */

export function humanize(code) {
  const text = String(code || "").replaceAll("_", " ").trim();
  return text ? text[0].toUpperCase() + text.slice(1) : "";
}

const REASONS = {
  // battery capability
  battery_assisted_planning_available:
    "Battery contribution included: charge level and limits are recent.",
  battery_limits_unavailable:
    "Battery contribution excluded: current charge and discharge limits are unavailable.",
  battery_alarm_active_restricted:
    "Battery contribution excluded: the battery reports an active alarm.",
  battery_limit_derated_by_bms:
    "The battery's own management system has lowered its current limit.",
  battery_soc_stale:
    "Battery contribution excluded: the last charge-level reading is too old.",
  battery_soc_unavailable: "Battery contribution excluded: the charge level is unavailable.",
  no_battery_evidence: "No battery data for this site, so plans use grid and solar only.",
  grid_solar_only_plan: "The plan uses grid and solar only.",
  capacity_from_declared_basis:
    "Battery size comes from its declared rating (an assumption), not a live reading.",
  battery_needs_complete_forecast:
    "Battery contribution excluded: the forecast does not cover the whole planning window.",
  battery_terminal_state_unknown:
    "The battery's charge at the end of the window could not be valued, so it is not counted as a saving.",
  // grid meter
  authoritative_pcc_meter_counter_energy:
    "Grid energy is measured by the meter at your connection point.",
  gateway_mirror_excluded_not_summed:
    "A second copy of the same meter (via a gateway) is kept as evidence and never counted twice.",
  grid_meter_stale: "Grid meter readings are delayed, so recent energy cannot be verified yet.",
  grid_meter_missing: "Grid meter readings are missing, so energy cannot be verified.",
  no_authoritative_grid_meter:
    "No grid meter at your connection point, so grid energy cannot be verified.",
  no_authoritative_grid_meter_data:
    "No grid meter readings cover this window, so energy cannot be verified.",
  meter_coverage_incomplete:
    "Energy verification incomplete: a meter gap covers part of this window.",
  // sunlight
  poa_irradiance_on_registered_plane:
    "Sunlight is measured on the panel plane registered for your solar forecast.",
  site_sensor: "The sunlight sensor is on your site.",
  area_station: "A shared weather station nearby is explicitly linked to your site.",
  no_compatible_irradiance_sensor:
    "No sunlight sensor in the plane of your panels, so the solar forecast is not adjusted.",
  forecast_unchanged: "The solar forecast is used as is.",
  no_recent_valid_poa_irradiance:
    "No recent valid sunlight reading, so the solar forecast is not adjusted.",
  no_poa_irradiance: "No sunlight reading in the panel plane.",
  sensor_plane_differs_from_module_plane:
    "The sunlight sensor faces a different direction than your panels, so production is not compared with it.",
  poa_sensor_plane_vs_module_plane_unknown:
    "It is not known whether the sunlight sensor faces the same direction as your panels, so production is not compared with it.",
  installed_capacity_unknown: "Installed solar size is unknown.",
  no_ac_production_boundary_data: "No measured solar production at the inverter output.",
  insufficient_valid_daylight_coverage: "Not enough valid daylight readings to compare production.",
  inputs_complete_numeric_review_possible:
    "Enough readings to compare production with measured sunlight.",
  // planner
  load_profile_gap_filled_from_adjacent_slots:
    "A few missing usage readings were filled from neighbouring intervals (assumption).",
  load_profile_partial: "Usage history is partial, so the usage forecast is less certain.",
  load_from_typical_shape_assumption: "Usage follows a typical daily shape (assumption).",
  typical_shape_from_profile_assumption: "Usage follows a typical daily shape (assumption).",
  base_load_unknown: "Expected usage is unknown for part of the window.",
  installed_kwp_unknown: "Installed solar size is unknown, so the solar forecast is uncertain.",
  location_assumed_city_level: "Location is assumed at city level for the solar forecast.",
  module_plane_assumed: "Panel direction and tilt are assumed.",
  no_recent_compatible_measurement:
    "No recent compatible sunlight measurement; the forecast is not adjusted.",
  no_recent_production_history: "No recent solar production history.",
  no_measured_ac_pv_history:
    "No measured solar production history; the forecast uses a clear-sky shape.",
  no_measured_site_load_history: "No measured usage history; a typical usage shape is assumed.",
  price_gap_in_run: "Part of this time has no contract price, so its cost is unknown.",
  price_coverage_missing: "Some times have no contract price, so their cost is unknown.",
  import_limit_checked_against_task_power_only:
    "Your connection limit was checked against this task's power only, because other usage is unknown.",
  cost_bounded_by_tariff_unknown_solar_or_load:
    "Solar or usage forecast is missing, so only a cost range from your contract prices is shown.",
  ranked_by_cost_bounds: "Times were compared using cost ranges because some inputs are missing.",
  no_start_satisfies_constraints: "No start time fits all your limits.",
  usual_time_outside_horizon_used_run_now:
    "Your usual time is outside the planning window, so the comparison is with running now.",
  default_tariff_assumed_no_contract:
    "No contract on file: a default price is assumed. Add your contract for real estimates.",
  export_valued_as_contract_credit:
    "Exported energy is valued as contract credit, as your contract states.",
  export_compensation_type_unspecified:
    "Your contract does not say how export is paid; it is valued at the stated export price.",
  other_accepted_tasks_in_base_load: "Your other accepted tasks are included in expected usage.",
  current_recommendation_differs_from_commitment:
    "New evidence gives a different recommendation. Your accepted plan stays as it is until you review it.",
  customer_chose_non_recommended_start:
    "You chose a different start than the recommended one.",
  // progress
  run_not_started: "The agreed time has not started yet.",
  price_or_meter_gap:
    "Part of the window has no price or meter reading, so the measured cost is partial.",
  no_contract_bands_for_measured_cost:
    "No contract price covers this window, so the measured cost is unknown.",
  no_estimate_snapshot_for_chosen_start:
    "You chose a different start than recommended, so there is no saved estimate to compare with.",
};

const CONSTRAINTS = {
  non_interruptible_run: "Runs in one go, without pauses",
  earliest_start: "Not before your earliest start",
  deadline: "Finished by your deadline",
  latest_start: "Starts by your latest start",
  allowed_window: "Inside your allowed hours",
  site_import_limit: "Within your connection import limit",
  battery_reserve: "Keeps the battery reserve",
  battery_power_limits: "Within the battery's power limits",
  battery_terminal_value: "Battery charge used is valued fairly at the end",
};

/** Codes that describe an assumption (shown apart from measurements). */
const ASSUMPTIONS = new Set([
  "load_profile_gap_filled_from_adjacent_slots",
  "load_from_typical_shape_assumption",
  "typical_shape_from_profile_assumption",
  "capacity_from_declared_basis",
  "location_assumed_city_level",
  "module_plane_assumed",
  "default_tariff_assumed_no_contract",
  "export_compensation_type_unspecified",
  "import_limit_checked_against_task_power_only",
  "installed_kwp_unknown",
  "no_measured_ac_pv_history",
  "no_measured_site_load_history",
  "cost_bounded_by_tariff_unknown_solar_or_load",
]);

/** One reason code → a plain sentence (unknown codes are humanized, never hidden). */
export function reasonText(code) {
  if (REASONS[code]) return REASONS[code];
  let match = /^alarm_(.+)$/.exec(code || "");
  if (match) return `The battery reports an active “${humanize(match[1]).toLowerCase()}” alarm. Contact your technician through Support; do not open the equipment.`;
  match = /^battery_(.+)_missing$/.exec(code || "");
  if (match) {
    const name = match[1].replaceAll("_", " ");
    const current = /limit/.test(name) ? `current ${name}` : name;
    return `Battery contribution excluded: ${current} is unavailable.`;
  }
  match = /^baseline_violates_(.+)$/.exec(code || "");
  if (match)
    return `Your usual time breaks a limit: ${match[1]
      .split("_and_")
      .map((part) => (CONSTRAINTS[part] || humanize(part)).toLowerCase())
      .join("; ")}.`;
  return `${humanize(code)}.`;
}

export const isAssumption = (code) => ASSUMPTIONS.has(code);

/** Unique reason sentences, split into assumptions and everything else. */
export function splitReasons(codes) {
  const seen = new Set();
  const facts = [],
    assumptions = [];
  for (const code of codes || []) {
    const text = reasonText(code);
    if (seen.has(text)) continue;
    seen.add(text);
    (isAssumption(code) ? assumptions : facts).push({ code, text });
  }
  return { facts, assumptions };
}

export const constraintText = (code) => CONSTRAINTS[code] || humanize(code);

/* ------------------------------------------------------------------ evidence ids */

/**
 * Evidence id → { kind: measured | derived | other, text }. Ids stay visible only in
 * technical details; this gives each a plain label.
 */
export function evidenceKind(id) {
  const value = String(id || "");
  if (value.startsWith("authority:") || value.startsWith("frame:") || value.startsWith("telemetry:"))
    return "measured";
  if (value.startsWith("derived:")) return "derived";
  return "other";
}

/** Counts per kind, e.g. { measured: 9, derived: 4, other: 0 }. */
export function evidenceCounts(ids) {
  const counts = { measured: 0, derived: 0, other: 0 };
  for (const id of ids || []) counts[evidenceKind(id)] += 1;
  return counts;
}

/* ------------------------------------------------------------------ inputs */

const SOURCES = {
  component_pcc_meter: "Grid meter",
  component_battery: "Battery",
  component_irradiance: "Sunlight sensor",
  inverter_frames: "Inverter",
  compact_telemetry: "Site telemetry",
  component_meter: "Grid meter at your connection point",
};

export const sourceName = (source) => SOURCES[source] || humanize(source);

const FRESH = {
  fresh: { label: "up to date", tone: "green" },
  stale: { label: "delayed", tone: "orange" },
  missing: { label: "no readings", tone: "orange" },
  not_applicable: { label: "not used", tone: "" },
};

/** Freshness row → { name, label, tone, time } in plain words. */
export function freshnessRow(row) {
  const state = FRESH[row?.status] || { label: humanize(row?.status), tone: "" };
  return {
    name: sourceName(row?.source),
    label: state.label,
    tone: state.tone,
    time: row?.last_observed_at ? localDateTime(row.last_observed_at) : null,
    age: ageText(row?.age_seconds),
  };
}

const pct = (value) => (Number.isFinite(value) ? `${Math.round(value * 100)} %` : "unknown");

/** Input coverage → "Solar forecast 100 % · Usage 100 % · Prices 100 %". */
export function coverageText(coverage) {
  if (!coverage) return "Input coverage unknown";
  return `Solar forecast ${pct(coverage.pv_forecast)} · Usage ${pct(coverage.base_load)} · Prices ${pct(coverage.prices)}`;
}

/** Overall confidence label from coverage and freshness. */
export function confidence(decision) {
  const coverage = decision?.input_coverage;
  const values = coverage ? [coverage.pv_forecast, coverage.base_load, coverage.prices] : [];
  const weakest = values.length ? Math.min(...values.map((v) => (Number.isFinite(v) ? v : 0))) : 0;
  const stale = (decision?.freshness || []).some((row) => row.status === "stale" || row.status === "missing");
  if (!coverage || weakest < 0.5) return { label: "Low confidence", tone: "orange" };
  if (weakest < 1 || stale) return { label: "Partial inputs", tone: "yellow" };
  return { label: "Complete inputs", tone: "green" };
}

const PV_METHODS = {
  clear_sky_scaled_with_near_term_adjustment:
    "Clear-sky solar shape scaled by recent days, with a short adjustment from measured sunlight",
  clear_sky_scaled_by_recent_days: "Clear-sky solar shape scaled by your recent days",
  clear_sky_envelope_unadjusted: "Clear-sky solar shape, not adjusted (no recent production data)",
};
const LOAD_METHODS = {
  measured_same_time_of_day_mean_3d: "Usage from the same times on your last 3 days (measured)",
  typical_shape_from_profile_assumption: "Usage from a typical daily shape (assumption)",
  load_from_typical_shape_assumption: "Usage from a typical daily shape (assumption)",
};
const RECENT_SOURCES = {
  poa_irradiance: "measured sunlight in your panel plane",
  measured_ac_pv: "your measured solar production",
};

/** Forecast info → plain lines. */
export function forecastLines(forecast) {
  if (!forecast) return [];
  const lines = [`Forecast issued ${localDateTime(forecast.issue_time)} (estimated).`];
  lines.push(`${PV_METHODS[forecast.pv_method] || humanize(forecast.pv_method)}.`);
  if (forecast.recent_source)
    lines.push(`Near-term check uses ${RECENT_SOURCES[forecast.recent_source] || humanize(forecast.recent_source)}.`);
  lines.push(`${LOAD_METHODS[forecast.load_method] || humanize(forecast.load_method)}.`);
  if (forecast.location_basis && forecast.location_basis !== "site")
    lines.push(`Location basis: ${humanize(forecast.location_basis).toLowerCase()} (assumption).`);
  if (forecast.plane_basis && forecast.plane_basis !== "registered")
    lines.push(`Panel plane: ${humanize(forecast.plane_basis).toLowerCase()} (assumption).`);
  return lines;
}

const num = (value, digits = 1) =>
  Number.isFinite(value)
    ? new Intl.NumberFormat("en-GB", { maximumFractionDigits: digits }).format(value)
    : "unknown";

/**
 * Battery contribution → { included, title, lines[] }.
 * `included` is true only when the backend used it in the plan.
 */
export function batteryView(battery) {
  if (!battery) return { included: false, title: "Battery contribution unknown.", lines: [] };
  const reasons = (battery.reason_codes || []).filter((code) => code !== "grid_solar_only_plan");
  const others = reasons.filter((code) => code !== "battery_assisted_planning_available");
  // Lead with the reason that excludes the battery, then the supporting details.
  const exclusion =
    others.find((code) => reasonText(code).startsWith("Battery contribution excluded")) ||
    others.find((code) => code === "no_battery_evidence") ||
    others[0];
  if (!battery.available) {
    return {
      included: false,
      title: exclusion ? reasonText(exclusion) : "Battery contribution excluded.",
      lines: reasons.filter((code) => code !== exclusion).map(reasonText),
    };
  }
  const lines = [];
  if (battery.soc_pct != null)
    lines.push(
      `Charge level ${num(battery.soc_pct, 0)} %${battery.soc_as_of ? ` at ${localTime(battery.soc_as_of)}` : ""}; reserve kept at ${num(battery.reserve_pct, 0)} %.`,
    );
  if (battery.discharge_limit_kw != null || battery.charge_limit_kw != null)
    lines.push(
      `Limits used: discharge ${num(battery.discharge_limit_kw)} kW, charge ${num(battery.charge_limit_kw)} kW (lowest applicable).`,
    );
  if (battery.usable_capacity_kwh != null)
    lines.push(`Usable capacity ${num(battery.usable_capacity_kwh)} kWh.`);
  for (const code of reasons) if (code !== "battery_assisted_planning_available") lines.push(reasonText(code));
  return {
    included: Boolean(battery.used),
    title: battery.used
      ? "Battery contribution included."
      : "Battery available, but this plan does not need it.",
    lines,
  };
}

/** "cv-<site>-3" → "version 3"; anything else stays as given. */
export function versionLabel(id) {
  if (!id) return "no contract version";
  const match = /-(\d+)$/.exec(id);
  return match ? `version ${match[1]}` : id;
}

/**
 * Group interval rows by band → [{ band_id, label, from, to, rate, exportValue }].
 * `bands` is the contract's band list (for labels); unknown ids keep their id.
 */
export function bandsUsed(intervals, bands = []) {
  const names = Object.fromEntries((bands || []).map((band) => [band.band_id, band.label || band.band_id]));
  const groups = [];
  for (const row of intervals || []) {
    const last = groups.at(-1);
    if (last && last.band_id === row.band_id && last.rate === row.import_rate_ron_kwh && last.to === row.start) {
      last.to = row.end;
      continue;
    }
    groups.push({
      band_id: row.band_id,
      label: row.band_id ? names[row.band_id] || humanize(row.band_id) : "No contract price",
      from: row.start,
      to: row.end,
      rate: row.import_rate_ron_kwh,
      exportValue: row.export_value_ron_kwh,
      gap: row.price_gap_reason || null,
    });
  }
  return groups;
}

/** Plain headline for a decision. */
export function planHeadline(decision) {
  if (!decision) return "";
  if (decision.status === "no_feasible_start") return "No start time fits all your limits";
  if (!decision.recommended_start) return "No recommendation yet";
  return `Best time: ${slotText(decision.recommended_start, decision.recommended_end)}`;
}

/* ------------------------------------------------------------------ contract bands */

const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** Minutes after local midnight → "07:00"; 1440 → "24:00". */
export function minuteText(minute) {
  if (!Number.isFinite(minute)) return "--:--";
  const h = Math.floor(minute / 60),
    m = minute % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

/** "HH:MM" → minutes; "24:00" → 1440; invalid → null. */
export function parseMinute(text) {
  const match = /^(\d{2}):(\d{2})$/.exec(text || "");
  if (!match) return null;
  const h = +match[1],
    m = +match[2];
  if (h === 24 && m === 0) return 1440;
  if (h > 23 || m > 59) return null;
  return h * 60 + m;
}

export const crossesMidnight = (band) => band.end_minute <= band.start_minute;

/** "22:00–07:00 (next day)", "00:00–24:00 (all day)". */
export function bandTime(band) {
  if (band.start_minute === 0 && band.end_minute === 1440) return "00:00–24:00 (all day)";
  const text = `${minuteText(band.start_minute)}–${minuteText(band.end_minute)}`;
  return crossesMidnight(band) ? `${text} (next day)` : text;
}

/** ISO weekdays → "Mon–Fri", "Sat–Sun", "Every day", "Mon, Wed, Fri". */
export function daysText(days) {
  const list = [...new Set(days || [])].filter((d) => d >= 1 && d <= 7).sort((a, b) => a - b);
  if (!list.length) return "No days";
  if (list.length === 7) return "Every day";
  const contiguous = list.every((d, i) => i === 0 || d === list[i - 1] + 1);
  if (contiguous && list.length > 2) return `${DAY_NAMES[list[0] - 1]}–${DAY_NAMES[list.at(-1) - 1]}`;
  if (contiguous && list.length === 2) return `${DAY_NAMES[list[0] - 1]}–${DAY_NAMES[list[1] - 1]}`;
  return list.map((d) => DAY_NAMES[d - 1]).join(", ");
}

/** Bands sorted for display: weekday groups first, then by start time. */
export function sortBands(bands) {
  return [...(bands || [])].sort(
    (a, b) =>
      Math.min(...a.days) - Math.min(...b.days) ||
      a.days.length - b.days.length ||
      a.start_minute - b.start_minute,
  );
}

/** "Valid from 1 Jul 2026", "1 Jul 2026 – 31 Dec 2026" for band date limits. */
export function validityText(from, to) {
  const fmt = (value) =>
    value ? new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(Date.parse(`${value}T00:00:00Z`)) : null;
  const a = fmt(from),
    b = fmt(to);
  if (!a && !b) return "No end date";
  if (a && b) return `${a} – before ${b}`;
  return a ? `From ${a}` : `Until before ${b}`;
}

const COMPENSATION = {
  payment: "Export is paid to you",
  credit: "Export is credited to your bill",
  unspecified: "Export compensation not stated",
};
export const compensationText = (value) => COMPENSATION[value] || humanize(value || "unspecified");

/** Minutes of one band on a week grid (a midnight-crossing band spills into the next day). */
function weekMinutes(band) {
  const minutes = new Set();
  const week = 7 * 1440;
  const span = crossesMidnight(band)
    ? 1440 - band.start_minute + band.end_minute
    : band.end_minute - band.start_minute;
  for (const day of band.days) {
    const base = (day - 1) * 1440;
    for (let offset = 0; offset < span; offset += 1) minutes.add((base + band.start_minute + offset) % week);
  }
  return minutes;
}

/**
 * Local checks before saving (the server validates again).
 * → { errors: string[], uncoveredMinutes }
 */
export function checkBands(bands) {
  const errors = [];
  const sets = [];
  const ids = new Set();
  (bands || []).forEach((band, index) => {
    const name = band.label || `Band ${index + 1}`;
    if (!band.days?.length) errors.push(`${name}: choose at least one day.`);
    if (!Number.isFinite(band.start_minute) || !Number.isFinite(band.end_minute))
      errors.push(`${name}: enter a start and an end time.`);
    if (!(band.import_rate_ron_kwh > 0 && band.import_rate_ron_kwh <= 10))
      errors.push(`${name}: the import price must be above 0 and at most 10 RON/kWh.`);
    if (!(band.export_value_ron_kwh >= 0 && band.export_value_ron_kwh <= 10))
      errors.push(`${name}: the export value must be between 0 and 10 RON/kWh.`);
    if (ids.has(band.band_id)) errors.push(`${name}: duplicate band name.`);
    ids.add(band.band_id);
    sets.push(band.days?.length && Number.isFinite(band.start_minute) && Number.isFinite(band.end_minute) ? weekMinutes(band) : new Set());
  });
  for (let i = 0; i < sets.length; i += 1)
    for (let j = i + 1; j < sets.length; j += 1) {
      const both = [...sets[i]].some((minute) => sets[j].has(minute));
      if (both && sameValidity(bands[i], bands[j]))
        errors.push(`${bands[i].label || `Band ${i + 1}`} and ${bands[j].label || `Band ${j + 1}`} overlap.`);
    }
  const covered = new Set();
  for (const set of sets) for (const minute of set) covered.add(minute);
  return { errors, uncoveredMinutes: 7 * 1440 - covered.size };
}

const sameValidity = (a, b) => {
  const start = (x) => x.valid_from || "0000-01-01";
  const end = (x) => x.valid_to || "9999-12-31";
  return start(a) < end(b) && start(b) < end(a);
};

/** A readable unique band id from a label ("Evening peak" → "evening-peak"). */
export function bandId(label, taken = new Set()) {
  const base =
    String(label || "band")
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 32) || "band";
  let id = /^[a-z0-9]/.test(base) ? base : `b-${base}`;
  let n = 2;
  while (taken.has(id)) id = `${base.slice(0, 30)}-${n++}`;
  return id;
}

/* ------------------------------------------------------------------ task form */

const KINDS = {
  laundry_batch: "Laundry batch",
  dishwasher: "Dishwasher",
  ev_charging: "EV charging",
  water_heating: "Water heating",
  pool_pump: "Pool pump",
  other: "Other",
};
export const TASK_KINDS = Object.entries(KINDS).map(([value, label]) => ({ value, label }));
export const kindLabel = (kind) => KINDS[kind] || humanize(kind);

const parts = (value) =>
  bucharestParts(typeof value === "number" ? new Date(value) : value) || { date: "", time: "" };
const ceilQuarter = (ms) => Math.ceil(ms / 900000) * 900000;

/** Form state for a new task (`now` = analytical time) or an existing one. */
export function taskForm(task, now) {
  if (task) {
    const e = parts(task.earliest_start),
      d = parts(task.deadline),
      l = task.latest_start ? parts(task.latest_start) : { date: "", time: "" },
      u = task.usual_start ? parts(task.usual_start) : { date: "", time: "" };
    return {
      label: task.label,
      kind: task.kind,
      power_kw: String(task.power_kw),
      energy_kwh: String(task.energy_kwh),
      earliest_date: e.date,
      earliest_time: e.time,
      deadline_date: d.date,
      deadline_time: d.time,
      latest_date: l.date,
      latest_time: l.time,
      usual_date: u.date,
      usual_time: u.time,
      window_from: task.allowed_start_minute == null ? "" : minuteText(task.allowed_start_minute),
      window_to: task.allowed_end_minute == null ? "" : minuteText(task.allowed_end_minute % 1440),
      import_limit_kw: task.site_import_limit_kw == null ? "" : String(task.site_import_limit_kw),
      assumption_note: task.assumption_note || "",
    };
  }
  const base = ceilQuarter(instant(now) ?? Date.now());
  const e = parts(base),
    d = parts(base + 12 * 3600000);
  return {
    label: "",
    kind: "other",
    power_kw: "2",
    energy_kwh: "2",
    earliest_date: e.date,
    earliest_time: e.time,
    deadline_date: d.date,
    deadline_time: d.time,
    latest_date: "",
    latest_time: "",
    usual_date: "",
    usual_time: "",
    window_from: "",
    window_to: "",
    import_limit_kw: "",
    assumption_note: "",
  };
}

const positive = (text) => {
  const value = Number(String(text).replace(",", "."));
  return String(text).trim() !== "" && Number.isFinite(value) ? value : null;
};

/** Duration in minutes from the form (energy / power), or null. */
export function formDuration(form) {
  const power = positive(form.power_kw),
    energy = positive(form.energy_kwh);
  return power > 0 && energy > 0 ? (energy / power) * 60 : null;
}

/**
 * Form → { body } ready for createTask/updateTask, or { errors: string[] }.
 * Mirrors the backend rules so a rejected request is rare (the server still decides).
 */
export function taskBody(form) {
  const errors = [];
  const label = form.label.trim();
  if (!label) errors.push("Give the task a name.");
  if (label.length > 80) errors.push("Keep the name under 80 characters.");
  const power = positive(form.power_kw),
    energy = positive(form.energy_kwh);
  if (!(power > 0 && power <= 50)) errors.push("Power must be above 0 and at most 50 kW.");
  if (!(energy > 0 && energy <= 200)) errors.push("Energy must be above 0 and at most 200 kWh.");
  const at = (date, time, name, required) => {
    if (!date && !time && !required) return null;
    const value = bucharestToUtc(date, time);
    if (!value) errors.push(`${name}: choose a valid date and time (Bucharest time).`);
    return value;
  };
  const earliest = at(form.earliest_date, form.earliest_time, "Earliest start", true);
  const deadline = at(form.deadline_date, form.deadline_time, "Finish by", true);
  const latest = at(form.latest_date, form.latest_time, "Latest start", false);
  const usual = at(form.usual_date, form.usual_time, "Usual start", false);
  const minutes = power > 0 && energy > 0 ? (energy / power) * 60 : null;
  if (minutes != null && minutes > 24 * 60) errors.push("A task may run for at most 24 hours.");
  if (minutes != null && minutes < 1) errors.push("A task must run for at least one minute.");
  if (earliest && deadline) {
    if (deadline - earliest > 48 * 3600000) errors.push("Plan within at most 48 hours from the earliest start.");
    if (minutes != null && earliest.getTime() + minutes * 60000 > deadline.getTime())
      errors.push("The run does not fit between the earliest start and the finish-by time.");
  }
  if (latest && earliest && deadline && !(earliest <= latest && latest <= deadline))
    errors.push("The latest start must lie between the earliest start and the finish-by time.");
  const from = form.window_from ? parseMinute(form.window_from) : null;
  const to = form.window_to ? parseMinute(form.window_to) : null;
  if (Boolean(form.window_from) !== Boolean(form.window_to))
    errors.push("Allowed hours need both a from and a to time.");
  const limit = form.import_limit_kw === "" ? null : positive(form.import_limit_kw);
  if (form.import_limit_kw !== "" && !(limit > 0 && limit <= 1000))
    errors.push("The import limit must be above 0 and at most 1000 kW.");
  const note = form.assumption_note.trim();
  if (note.length > 200) errors.push("Keep the note under 200 characters.");
  if (errors.length) return { errors };
  return {
    body: {
      label,
      kind: form.kind,
      power_kw: power,
      energy_kwh: energy,
      earliest_start: earliest.toISOString(),
      deadline: deadline.toISOString(),
      latest_start: latest ? latest.toISOString() : null,
      allowed_start_minute: from == null ? null : from % 1440,
      allowed_end_minute: to == null ? null : to === 0 ? 1440 : to,
      usual_start: usual ? usual.toISOString() : null,
      site_import_limit_kw: limit,
      assumption_note: note || null,
    },
  };
}

/* ------------------------------------------------------------------ errors */

const PLAN_ERRORS = {
  recommendation_changed:
    "The recommendation changed since you opened it. Review the new one before accepting.",
  already_accepted: "This task already has an accepted plan.",
  start_passed: "That start time has already passed. Choose another time.",
  start_not_feasible: "That start no longer fits your limits. Choose one of the offered times.",
  no_recommendation: "There is no feasible start to accept.",
  task_committed: "This task has an accepted plan. Review (release) it before editing.",
  task_started: "A plan that has started cannot be released.",
  task_cancelled: "This task was cancelled.",
  stale_revision: "The task changed in the meantime. It was reloaded; try again.",
  not_committed: "This task has no accepted plan.",
  too_many_tasks: "You have many open tasks. Cancel or finish older ones first.",
  deadline_passed: "The deadline has already passed.",
  idempotency_key_reused: "This confirmation was already used for another task. Close it and try again.",
  invalid_request: "Some values were not accepted. Check the form and try again.",
  invalid_tariff_bands: null,
  retroactive_tariff: "A contract version cannot start in the past.",
};

/** Error → plain text (planner codes first, then the server's own message). */
export function planErrorText(error) {
  const code = error?.detail?.code;
  if (code && PLAN_ERRORS[code]) return PLAN_ERRORS[code];
  if (error?.status === 403 || error?.status === 404)
    return "This installation is not available to your account.";
  return error?.detail?.message || error?.message || "Unable to reach the service. Please try again.";
}
