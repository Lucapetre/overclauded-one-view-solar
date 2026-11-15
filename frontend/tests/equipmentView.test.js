import test from "node:test";
import assert from "node:assert/strict";
import {
  cardState,
  deviceText,
  evidenceLabel,
  familyCard,
  hasEquipment,
  originKind,
  unitText,
  valueText,
} from "../src/equipmentView.js";

const fresh = { status: "fresh", last_observed_at: "2026-07-17T04:30:00Z", age_seconds: 0, stale_after_seconds: 2700 };
const value = (metric, v, unit, extra = {}) => ({
  metric,
  channel: null,
  value: v,
  unit,
  observed_at: null,
  frame_start: "2026-07-17T04:15:00Z",
  frame_end: "2026-07-17T04:30:00Z",
  aggregation: "mean",
  origin: "simulated_observation",
  coverage_ratio: 1,
  evidence_id: `frame:X:${metric}:2026-07-17T04:15:00.000Z`,
  ...extra,
});

const f1 = {
  site_id: "F1",
  source_mode: "synthetic",
  families: [
    {
      family: "meter",
      availability: "available",
      selected_source: "F1-M1-PCC",
      assets: [{ asset_id: "F1-M1-PCC", profile_id: "m1", role: "authoritative_pcc_meter", boundary: "grid_pcc", mounting: null, shared_resource: false, link_basis: null }],
      latest: [value("grid_net_kw", 0.439, "kW")],
      freshness: fresh,
      declared_capabilities: { grid_energy_measured: "available" },
      notes: ["Authoritative grid energy comes from one selected meter per interval."],
    },
    {
      family: "battery",
      availability: "available",
      selected_source: "F1-B1-BMS",
      assets: [{ asset_id: "F1-B1-BMS", profile_id: "b1", role: "battery_monitoring", boundary: "dc_battery", mounting: null, shared_resource: false, link_basis: null }],
      latest: [value("soc_pct", 20, "pct"), value("battery_net_kw", -1.2, "kW"), value("battery_max_discharge_current_a", 25, "A")],
      freshness: fresh,
      declared_capabilities: { battery_limits_available: "available" },
      notes: [],
    },
    {
      family: "weather",
      availability: "available",
      selected_source: "WX",
      assets: [{ asset_id: "WX", profile_id: "w3", role: "irradiance_sensor", boundary: "station", mounting: "poa", shared_resource: true, link_basis: "explicitly linked area resource; not electrical topology" }],
      latest: [value("irradiance_wm2", 81.24, "W/m2"), value("module_temperature_c", 23.68, "degC")],
      freshness: { ...fresh, status: "stale", age_seconds: 4000 },
      declared_capabilities: { irradiance_ghi_available: "not_declared" },
      notes: [],
    },
  ],
  capabilities: [
    { capability: "grid_energy_verified", available: true, reason_codes: ["authoritative_pcc_meter_counter_energy"], evidence_ids: [] },
    {
      capability: "battery_assisted_planning",
      available: false,
      reason_codes: ["battery_limit_derated_by_bms", "battery_alarm_active_restricted", "alarm_internal_failure", "grid_solar_only_plan"],
      evidence_ids: ["frame:F1-B1-BMS:battery_alarm_raw:internal_failure:2026-07-18T04:00:00.000Z"],
    },
    { capability: "irradiance_explanation", available: true, reason_codes: ["poa_irradiance_on_registered_plane", "area_station"], evidence_ids: [] },
  ],
};

test("grid card: plain device, import direction, verified energy", () => {
  const card = familyCard(f1, "meter");
  assert.equal(card.title, "Grid");
  assert.equal(card.device, "Grid meter at your connection point");
  assert.equal(card.state, "ok");
  assert.equal(card.primary.text.sentence, "Taking 0.44 kW from the grid");
  assert.equal(card.lastUpdate, "17 Jul 2026, 07:30");
  assert.ok(card.reasons.some((r) => /measured by the meter at your connection point/.test(r)));
  assert.equal(card.measured.length, 1);
  assert.ok(card.assumptions.some((a) => /one selected meter/.test(a)));
  assert.equal(valueText("meter", value("grid_net_kw", -0.31, "kW")).sentence, "Sending 0.31 kW to the grid");
  assert.equal(valueText("meter", value("grid_net_kw", 0.01, "kW")).sentence, "Almost no grid exchange");
});

test("battery card: limited state with plain exclusion reasons", () => {
  const card = familyCard(f1, "battery");
  assert.equal(card.state, "limited");
  assert.equal(card.capabilityAvailable, false);
  assert.equal(card.primary.text.sentence, "Charge level 20 %");
  assert.equal(card.secondary[0].text.sentence, "Charging 1.2 kW");
  assert.match(card.reasons[0], /^Battery contribution excluded: the battery reports an active alarm/);
  assert.ok(card.reasons.some((r) => /lowered its current limit/.test(r)));
  assert.ok(!card.reasons.some((r) => /grid and solar only/.test(r)));
  assert.ok(card.technical.evidence_ids.some((id) => id.includes("internal_failure")));
});

test("solar card: shared station, stale freshness, linked-resource assumption", () => {
  const card = familyCard(f1, "weather");
  assert.equal(card.state, "stale");
  assert.equal(card.label, "Delayed");
  assert.equal(card.device, "Shared weather station nearby, tilted sunlight sensor");
  assert.equal(card.primary.text.sentence, "Sunlight 81 W/m²");
  assert.ok(card.assumptions.some((a) => /not electrical topology/.test(a)));
});

test("not installed and declared-only states are explicit", () => {
  const none = { ...f1, families: [{ family: "battery", availability: "not_installed", selected_source: null, assets: [], latest: [], freshness: { status: "missing" }, declared_capabilities: {}, notes: [] }] };
  const card = familyCard(none, "battery");
  assert.equal(card.state, "not_installed");
  assert.equal(card.device, "No battery is connected to this site.");
  assert.equal(card.primary, null);
  assert.equal(cardState({ availability: "declared_not_observed" }).state, "partial");
  assert.equal(cardState(null).state, "not_installed");
});

test("sites without component equipment are recognised", () => {
  assert.equal(hasEquipment(f1), true);
  assert.equal(hasEquipment({ source_mode: "none", families: [{ availability: "not_installed" }] }), false);
  assert.equal(hasEquipment(null), false);
  assert.equal(evidenceLabel(f1), "Synthetic equipment data");
});

test("units, origins and device wording", () => {
  assert.equal(unitText("pct"), "%");
  assert.equal(unitText("degC"), "°C");
  assert.equal(unitText("W/m2"), "W/m²");
  assert.equal(originKind("simulated_observation"), "measured");
  assert.equal(originKind("estimated"), "derived");
  assert.equal(originKind("declared_rating"), "assumed");
  assert.equal(deviceText("weather", { mounting: "poa", shared_resource: false }), "Sunlight sensor on your site, in the plane of your panels");
});
