import test from "node:test";
import assert from "node:assert/strict";
import {
  chartSegments,
  matchesSeries,
  number,
  primaryReadings,
  providerStatus,
  readings,
} from "../src/telemetry.js";

const frame = (metric_name, value, extra = {}) => ({
  metric_name,
  value,
  endpoint_key: "power",
  device_id: null,
  channel: null,
  frame_end_utc: "2026-07-15T12:15:00Z",
  unit: "kW",
  frame_status: "ok",
  aggregation: "mean",
  coverage_ratio: 1,
  original_cadence_s: 60,
  value_origin: "simulated_observation",
  ...extra,
});

test("zero readings remain zero while missing values stay unavailable", () => {
  assert.equal(number(0), "0");
  assert.equal(number(null), "Unavailable");
  assert.equal(number(NaN), "Unavailable");
  const result = readings(
    { frames: [frame("grid_import_kw", 0), frame("grid_export_kw", null)] },
    true,
  );
  assert.equal(result[0].value, 0);
  assert.equal(result[1].value, null);
});
test("hybrid DC production is never relabeled AC or inferred from net inverter output", () => {
  const result = primaryReadings(
    { frames: [frame("pv_dc_kw", 3.3), frame("inverter_ac_output_kw", 3.95)] },
    true,
  );
  assert.equal(result[0].name, "Solar production · DC");
  assert.equal(result[0].value, 3.3);
  assert.equal(result[1].value, null);
});
test("inverter-only output stays explicitly inverter output", () => {
  assert.equal(
    primaryReadings({ frames: [frame("inverter_ac_output_kw", 4.2)] }, true)[0]
      .name,
    "Inverter AC output",
  );
});
test("source health is distinct from equipment health and partial coverage remains visible", () => {
  assert.equal(
    providerStatus({ source_health: [{ freshness_status: "stale" }] }),
    "stale",
  );
  assert.equal(
    providerStatus({
      source_health: [{ freshness_status: "capability_unsupported" }],
    }),
    "unavailable",
  );
  const result = readings(
    { frames: [frame("pv_dc_kw", 3, { coverage_ratio: 0.5 })] },
    true,
  )[0];
  assert.match(result.detail, /50% coverage/);
});
test("device, endpoint and channel identities cannot be merged into one chart", () => {
  const selected = frame("phase_voltage_v", 230, {
    channel: "L1",
    device_id: "001",
  });
  assert.equal(
    matchesSeries(
      frame("phase_voltage_v", 235, { channel: "L2", device_id: "001" }),
      selected,
    ),
    false,
  );
  assert.equal(
    matchesSeries(
      frame("phase_voltage_v", 230, { channel: "L1", device_id: "1" }),
      selected,
    ),
    false,
  );
  assert.equal(matchesSeries(selected, selected), true);
});
test("missing data breaks a chart line", () => {
  assert.deepEqual(
    chartSegments([{ value: 1 }, { value: null }, { value: 0 }, { value: 2 }]),
    [[{ value: 1 }], [{ value: 0 }, { value: 2 }]],
  );
});
