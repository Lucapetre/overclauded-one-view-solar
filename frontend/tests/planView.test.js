import test from "node:test";
import assert from "node:assert/strict";
import {
  bandId,
  bandTime,
  bandsUsed,
  batteryView,
  checkBands,
  confidence,
  costText,
  daysText,
  differenceText,
  durationText,
  evidenceCounts,
  freshnessRow,
  localDateTime,
  minuteText,
  nextTask,
  parseMinute,
  planErrorText,
  reasonText,
  replayBadge,
  ron,
  slotText,
  sortBands,
  splitReasons,
  taskBody,
  taskForm,
  taskState,
  validityText,
  versionLabel,
} from "../src/planView.js";

const scenarioClock = {
  mode: "scenario",
  analytical_now: "2026-07-17T04:30:00Z",
  wall_now: "2026-11-15T03:31:38Z",
  scenario_id: "components-2026-07",
  run_id: "r1",
  scenario_started_at: "2026-07-17T04:30:00Z",
  synthetic: true,
};

test("replay badge shows the scenario time in Bucharest, nothing in live mode", () => {
  const badge = replayBadge(scenarioClock);
  assert.equal(badge.text, "Synthetic replay · 17 Jul 2026, 07:30");
  assert.equal(badge.scenario, "components-2026-07");
  assert.match(badge.detail, /Europe\/Bucharest/);
  assert.equal(replayBadge({ ...scenarioClock, mode: "live" }), null);
  assert.equal(replayBadge(null), null);
});

test("times are Bucharest local, including slots across midnight", () => {
  assert.equal(localDateTime("2026-07-17T08:00:00Z"), "17 Jul 2026, 11:00");
  assert.equal(slotText("2026-07-17T08:00:00Z", "2026-07-17T10:00:00Z"), "Fri 17 Jul, 11:00–13:00");
  assert.equal(
    slotText("2026-07-17T20:00:00Z", "2026-07-17T22:00:00Z"),
    "Fri 17 Jul, 23:00 – Sat 18 Jul, 01:00",
  );
  // A run ending exactly at local midnight stays on the same day.
  assert.equal(slotText("2026-07-17T19:00:00Z", "2026-07-17T21:00:00Z"), "Fri 17 Jul, 22:00–00:00");
  assert.equal(localDateTime("nope"), "unknown time");
  assert.equal(durationText(120), "2 h");
  assert.equal(durationText(90), "1 h 30 min");
  assert.equal(durationText(45), "45 min");
});

test("costs use the RON format; unknown stays unknown", () => {
  assert.equal(ron(9.618), "9.62 RON");
  assert.equal(ron(null), null);
  assert.equal(costText(12.16), "12.16 RON");
  assert.equal(costText(null, { low_ron: 1.2, high_ron: 3.4, basis: "x" }), "1.20 RON to 3.40 RON");
  assert.equal(costText(null, null), "unknown");
  assert.deepEqual(differenceText(-2.542, "usual_time"), {
    text: "Estimated 2.54 RON less than your usual time",
    tone: "good",
  });
  assert.equal(differenceText(0.5, "run_now").tone, "bad");
  assert.match(differenceText(0.5, "run_now").text, /more than running now/);
  assert.equal(differenceText(null, "run_now").tone, "unknown");
  assert.equal(differenceText(-1, null).text, "Estimated 1.00 RON less than the time it was compared with");
  assert.match(differenceText(null, "run_now").text, /unknown/);
  assert.equal(differenceText(0.001, "run_now").tone, "neutral");
});

test("task states are distinct and labelled", () => {
  const labels = ["suggested", "accepted", "running", "completed"].map((s) => taskState(s).label);
  assert.deepEqual(labels, ["Suggestion", "Accepted plan", "Running now", "Completed"]);
  assert.equal(new Set(labels).size, 4);
  assert.equal(taskState("weird_state").label, "Weird state");
});

test("next task prefers running, then accepted, then the earliest suggestion", () => {
  const tasks = [
    { task_id: "a", status: "suggested", earliest_start: "2026-07-18T05:00:00Z" },
    { task_id: "b", status: "suggested", earliest_start: "2026-07-17T05:00:00Z" },
    { task_id: "c", status: "completed", earliest_start: "2026-07-16T05:00:00Z" },
  ];
  assert.equal(nextTask(tasks).task_id, "b");
  assert.equal(nextTask([...tasks, { task_id: "d", status: "accepted", earliest_start: "2026-07-19T05:00:00Z" }]).task_id, "d");
  assert.equal(nextTask([...tasks, { task_id: "e", status: "running" }]).task_id, "e");
  assert.equal(nextTask([{ status: "cancelled" }]), null);
  assert.equal(nextTask(undefined), null);
});

test("reason codes map to plain text, including prefixed families", () => {
  assert.equal(
    reasonText("battery_discharge_limit_missing"),
    "Battery contribution excluded: current discharge limit is unavailable.",
  );
  assert.equal(
    reasonText("battery_limits_unavailable"),
    "Battery contribution excluded: current charge and discharge limits are unavailable.",
  );
  assert.match(reasonText("battery_alarm_active_restricted"), /active alarm/);
  assert.match(reasonText("alarm_internal_failure"), /“internal failure” alarm/);
  assert.match(reasonText("alarm_internal_failure"), /do not open the equipment/);
  assert.match(reasonText("meter_coverage_incomplete"), /Energy verification incomplete/);
  assert.match(reasonText("baseline_violates_allowed_window_and_deadline"), /inside your allowed hours; finished by your deadline/);
  assert.equal(reasonText("something_new"), "Something new.");
  const split = splitReasons([
    "battery_assisted_planning_available",
    "load_profile_gap_filled_from_adjacent_slots",
    "load_profile_gap_filled_from_adjacent_slots",
  ]);
  assert.equal(split.facts.length, 1);
  assert.equal(split.assumptions.length, 1);
  assert.match(split.assumptions[0].text, /assumption/);
});

test("battery contribution says included or excluded with the reason", () => {
  const used = batteryView({
    available: true,
    used: true,
    reason_codes: ["battery_assisted_planning_available"],
    soc_pct: 20,
    soc_as_of: "2026-07-17T04:25:01Z",
    reserve_pct: 20,
    discharge_limit_kw: 3,
    charge_limit_kw: 3,
    usable_capacity_kwh: 10.24,
  });
  assert.equal(used.included, true);
  assert.equal(used.title, "Battery contribution included.");
  assert.ok(used.lines.some((line) => /Charge level 20 % at 07:25; reserve kept at 20 %/.test(line)));
  const excluded = batteryView({
    available: false,
    used: false,
    reason_codes: ["battery_limit_derated_by_bms", "battery_alarm_active_restricted", "alarm_internal_failure", "grid_solar_only_plan"],
  });
  assert.equal(excluded.included, false);
  assert.equal(excluded.title, "Battery contribution excluded: the battery reports an active alarm.");
  assert.ok(excluded.lines.some((line) => /lowered its current limit/.test(line)));
  assert.ok(excluded.lines.some((line) => /internal failure/.test(line)));
  const none = batteryView({ available: false, used: false, reason_codes: ["no_battery_evidence", "grid_solar_only_plan"] });
  assert.match(none.title, /No battery data/);
  assert.equal(batteryView({ available: true, used: false, reason_codes: [] }).included, false);
});

test("confidence and freshness are plain", () => {
  assert.equal(confidence({ input_coverage: { pv_forecast: 1, base_load: 1, prices: 1 }, freshness: [] }).label, "Complete inputs");
  assert.equal(
    confidence({ input_coverage: { pv_forecast: 1, base_load: 1, prices: 1 }, freshness: [{ status: "stale" }] }).label,
    "Partial inputs",
  );
  assert.equal(confidence({ input_coverage: { pv_forecast: 0.2, base_load: 1, prices: 1 } }).label, "Low confidence");
  const row = freshnessRow({ source: "component_battery", status: "fresh", last_observed_at: "2026-07-17T04:25:01Z", age_seconds: 298 });
  assert.equal(row.name, "Battery");
  assert.equal(row.label, "up to date");
  assert.equal(row.age, "5 min ago");
  assert.deepEqual(evidenceCounts(["frame:a", "authority:b", "derived:load:x", "zzz"]), { measured: 2, derived: 1, other: 1 });
  assert.equal(versionLabel("cv-provider-e2f35075482123a2267dd143-1"), "version 1");
  assert.equal(versionLabel(null), "no contract version");
});

test("bands format local times, days and midnight crossing", () => {
  assert.equal(minuteText(420), "07:00");
  assert.equal(minuteText(1440), "24:00");
  assert.equal(parseMinute("24:00"), 1440);
  assert.equal(parseMinute("07:30"), 450);
  assert.equal(parseMinute("25:00"), null);
  assert.equal(bandTime({ start_minute: 1320, end_minute: 420 }), "22:00–07:00 (next day)");
  assert.equal(bandTime({ start_minute: 660, end_minute: 1020 }), "11:00–17:00");
  assert.equal(bandTime({ start_minute: 0, end_minute: 1440 }), "00:00–24:00 (all day)");
  assert.equal(daysText([1, 2, 3, 4, 5]), "Mon–Fri");
  assert.equal(daysText([6, 7]), "Sat–Sun");
  assert.equal(daysText([7, 1, 2, 3, 4, 5, 6]), "Every day");
  assert.equal(daysText([1, 3, 5]), "Mon, Wed, Fri");
  assert.equal(validityText(null, null), "No end date");
  assert.equal(validityText("2026-07-01", null), "From 1 Jul 2026");
  const sorted = sortBands([
    { band_id: "we", days: [6, 7], start_minute: 420 },
    { band_id: "night", days: [1, 2, 3, 4, 5], start_minute: 1320 },
    { band_id: "morning", days: [1, 2, 3, 4, 5], start_minute: 420 },
  ]);
  assert.deepEqual(sorted.map((b) => b.band_id), ["morning", "night", "we"]);
});

const f1Bands = [
  { band_id: "weekday-night", label: "Night", days: [1, 2, 3, 4, 5], start_minute: 1320, end_minute: 420, import_rate_ron_kwh: 0.92, export_value_ron_kwh: 0.45 },
  { band_id: "weekday-morning", label: "Morning", days: [1, 2, 3, 4, 5], start_minute: 420, end_minute: 660, import_rate_ron_kwh: 1.52, export_value_ron_kwh: 0.45 },
  { band_id: "weekday-midday", label: "Midday", days: [1, 2, 3, 4, 5], start_minute: 660, end_minute: 1020, import_rate_ron_kwh: 1.12, export_value_ron_kwh: 0.45 },
  { band_id: "weekday-peak", label: "Evening peak", days: [1, 2, 3, 4, 5], start_minute: 1020, end_minute: 1320, import_rate_ron_kwh: 1.69, export_value_ron_kwh: 0.45 },
  { band_id: "weekend-day", label: "Weekend day", days: [6, 7], start_minute: 420, end_minute: 1320, import_rate_ron_kwh: 1.15, export_value_ron_kwh: 0.45 },
  { band_id: "weekend-night", label: "Weekend night", days: [6, 7], start_minute: 1320, end_minute: 420, import_rate_ron_kwh: 0.92, export_value_ron_kwh: 0.45 },
];

test("band checks find overlaps (also across midnight) and uncovered time", () => {
  assert.deepEqual(checkBands(f1Bands), { errors: [], uncoveredMinutes: 0 });
  const overlap = checkBands([
    f1Bands[0],
    { ...f1Bands[1], band_id: "early", label: "Early", start_minute: 360 },
  ]);
  assert.ok(overlap.errors.some((e) => /Night and Early overlap/.test(e)));
  // Friday night spills into Saturday morning; a Saturday 06:00 band overlaps it.
  const spill = checkBands([f1Bands[0], { ...f1Bands[4], band_id: "sat", label: "Sat", days: [6], start_minute: 360, end_minute: 480 }]);
  assert.ok(spill.errors.some((e) => /overlap/.test(e)));
  const gap = checkBands([f1Bands[1]]);
  assert.equal(gap.errors.length, 0);
  assert.equal(gap.uncoveredMinutes, 7 * 1440 - 5 * 240);
  assert.ok(checkBands([{ ...f1Bands[1], import_rate_ron_kwh: 0 }]).errors.length);
  // Different validity periods do not overlap.
  const seasonal = checkBands([
    { ...f1Bands[1], valid_to: "2026-10-01" },
    { ...f1Bands[1], band_id: "winter", label: "Winter", valid_from: "2026-10-01" },
  ]);
  assert.deepEqual(seasonal.errors, []);
  assert.equal(bandId("Evening peak"), "evening-peak");
  assert.equal(bandId("Evening peak", new Set(["evening-peak"])), "evening-peak-2");
  assert.equal(bandId("!!!"), "band");
});

test("bands used in a plan are grouped with their labels", () => {
  const rows = [
    { start: "2026-07-17T08:00:00Z", end: "2026-07-17T08:15:00Z", band_id: "weekday-midday", import_rate_ron_kwh: 1.12, export_value_ron_kwh: 0.45 },
    { start: "2026-07-17T08:15:00Z", end: "2026-07-17T08:30:00Z", band_id: "weekday-midday", import_rate_ron_kwh: 1.12, export_value_ron_kwh: 0.45 },
    { start: "2026-07-17T08:30:00Z", end: "2026-07-17T08:45:00Z", band_id: null, import_rate_ron_kwh: null, export_value_ron_kwh: null, price_gap_reason: "no_band_coverage" },
  ];
  const groups = bandsUsed(rows, f1Bands);
  assert.equal(groups.length, 2);
  assert.equal(groups[0].label, "Midday");
  assert.equal(groups[0].to, "2026-07-17T08:30:00Z");
  assert.equal(groups[1].label, "No contract price");
});

test("task form round-trips Bucharest local times and mirrors server rules", () => {
  const task = {
    label: "Laundry batch",
    kind: "laundry_batch",
    power_kw: 4,
    energy_kwh: 8,
    earliest_start: "2026-07-17T05:00:00Z",
    deadline: "2026-07-17T17:00:00Z",
    latest_start: null,
    allowed_start_minute: 480,
    allowed_end_minute: 1200,
    usual_start: "2026-07-17T05:00:00Z",
    site_import_limit_kw: 17.3,
    assumption_note: "Demo values",
  };
  const form = taskForm(task);
  assert.equal(form.earliest_time, "08:00");
  assert.equal(form.deadline_time, "20:00");
  assert.equal(form.window_from, "08:00");
  assert.equal(form.window_to, "20:00");
  const { body } = taskBody(form);
  assert.equal(body.earliest_start, "2026-07-17T05:00:00.000Z");
  assert.equal(body.deadline, "2026-07-17T17:00:00.000Z");
  assert.equal(body.allowed_start_minute, 480);
  assert.equal(body.allowed_end_minute, 1200);
  assert.equal(body.site_import_limit_kw, 17.3);
  assert.equal(body.latest_start, null);
  // Allowed hours ending at midnight are sent as 1440.
  assert.equal(taskBody({ ...form, window_from: "18:00", window_to: "00:00" }).body.allowed_end_minute, 1440);
  assert.ok(taskBody({ ...form, deadline_time: "09:00" }).errors.some((e) => /does not fit/.test(e)));
  assert.ok(taskBody({ ...form, deadline_date: "2026-07-20" }).errors.some((e) => /48 hours/.test(e)));
  assert.ok(taskBody({ ...form, power_kw: "0" }).errors.length);
  assert.ok(taskBody({ ...form, window_to: "" }).errors.some((e) => /both/.test(e)));
  assert.ok(taskBody({ ...form, label: " " }).errors.some((e) => /name/.test(e)));
  const fresh = taskForm(null, "2026-07-17T04:31:00Z");
  assert.equal(fresh.earliest_time, "07:45");
  assert.equal(fresh.deadline_time, "19:45");
});

test("planner errors become plain text", () => {
  assert.match(planErrorText({ detail: { code: "recommendation_changed" } }), /changed since you opened it/);
  assert.match(planErrorText({ status: 404, detail: { code: "not_found" } }), /not available/);
  assert.equal(planErrorText({ detail: { code: "other", message: "Server says" } }), "Server says");
});
