# Data dictionary (SYNTHETIC DEMONSTRATION)

## Identity

| Key | Form | Notes |
| --- | --- | --- |
| `site_key` | `provider\|account_id\|site_id` | Never joined across providers/accounts because labels or times match |
| `device_key` | `site_key\|device_id` | A Fronius local id `"1"` is unique only inside its site |
| IDs | strings | Large integers (for example `18000000036112209`) are kept exact and leading zeros (`0071F2A3-9C`) are preserved. Float ids are rejected. |
| `raw_record_id` | sha256(delivery hash, record index) | One per extracted record, including duplicates and quarantined records |

## Canonical observation (`canonical_observations` view / `canonical_measurements.csv.gz`)

Schema: `schemas/canonical_measurement.schema.json`.

| Column | Meaning |
| --- | --- |
| `provider`, `provider_profile_id`, `provider_profile_version`, `mapping_version`, `endpoint_key`, `profile_variant` | The registry entry that interpreted the record |
| `account_id`, `site_id`, `site_key`, `device_id`, `device_key`, `entity_scope`, `channel` | Scoped identity. `channel` holds the phase (L1–L3) or string (PV1/PV2). |
| `raw_record_id`, `payload_hash`, `source_path`, `source_line`, `record_status` | Provenance back to the exact NDJSON line |
| `source_time_raw`, `source_time_role` | The original time value and its declared role (`collect_time`, `local_measurement_time`, `response_time`, `server_current_time`, `capture_time`) |
| `measurement_time_utc` | Set **only** when the source carries a measurement time (null for Fronius `Head.Timestamp`, Huawei real-time, SolarEdge power flow) |
| `response_time_utc`, `capture_time_utc`, `received_at_utc` | Response timestamp, mock capture time, and arrival time |
| `effective_time_utc`, `effective_time_basis` | Ordering/framing anchor and which role it came from |
| `metric_name`, `metric_kind`, `boundary` | Canonical metric, kind and measurement boundary (`ac_inverter_output`, `dc_pv_input`, `dc_mppt_input`, `ac_phase`, `site_grid_connection`, `site_load`, `dc_battery`, `battery_flow`, `site_flow_unspecified`, …) |
| `original_value`, `original_unit` | JSON-encoded original, including **signed** originals and edge descriptions |
| `canonical_value`, `canonical_text`, `canonical_unit` | Normalised value (rounded to 9 decimals) or raw state text |
| `value_origin` | `simulated_observation` (synthetic source), `observation`, `derived` (counter differences), `estimated` (power integration) |
| `availability_status` | See below |
| `quality_flags`, `is_conflicted`, `transform_log`, `assumption_basis`, `requirement_class`, `field_rule_id` | Why and how the value was produced |

### Availability states

| State | Meaning |
| --- | --- |
| `available` | A usable value, which may legitimately be `0` |
| `missing` | Key absent or value null. Flags explain which: `vendor_permitted_null`, `null_value`, `optional_field_absent`, `required_key_missing`, `flow_node_absent` |
| `invalid` | Present but unusable: `invalid_type`, `ambiguous_number`, `out_of_range`, `unit_ambiguity_suspected`, `unexpected_sign`, `direction_unresolved`, `unsupported_unit`. The original is preserved and `canonical_value` is null. |
| `stale` | A real-time response whose response time lags capture by more than `stale_after_s`. The value is kept but excluded from frames. |
| `not_installed`, `unsupported` | Capability states, stored in `capability_states` with record counts, not per row |
| `access_denied` | Endpoint/device denied (HTTP 403). Stored as `delivery_events` windows and shown as frame status. No values or zeros are emitted. |

### Canonical metrics

These metrics are populated only when the source semantics support them:

* `inverter_ac_output_kw`, `pv_dc_kw`, `pv_ac_kw`, `pv_production_kw` (boundary unspecified)
* `grid_import_kw`, `grid_export_kw`, `household_load_kw`, `battery_charge_kw`, `battery_discharge_kw`
  (all nonnegative after profile conversion), `soc_pct`
* `daily_yield_kwh`, `lifetime_yield_kwh`, `yearly_yield_kwh`
* `daily_/lifetime_battery_charge/discharge_kwh`, `interval_*_kwh` (derived only)
* `phase_voltage_v`, `ac_voltage_v`, `ac_current_a`, `grid_frequency_hz`
* `string_dc_voltage_v`, `string_dc_current_a`, `dc_input_voltage_v`, `dc_input_current_a`,
  `battery_busbar_voltage_v`
* `inverter_temperature_c` and `battery_temperature_c` (never merged)
* `inverter_state_raw`, `battery_state_raw`, `battery_mode_raw`

## Interval energy (`interval_energy`)

| Status | Meaning | Allocatable to frames |
| --- | --- | --- |
| `valid` | Counter difference within `max_gap_s` and the rate bound | yes |
| `daily_segment_start` | Legitimate local-midnight reset. Energy since midnight equals the first reading. | yes |
| `unknown_pre_midnight_remainder` | The last part of the previous local day (final reading unknown) | no (energy null) |
| `gap_span_total` | A known counter total over a span longer than `max_gap_s` | no (total only) |
| `unknown_counter_reset` | An unexpected counter drop. The crossing energy is unknown and a new baseline starts. | no (energy null) |
| `implausible_counter_jump` | Difference exceeds rated power × duration × factor | no (energy null) |
| `estimated_from_power` | Left Riemann sum of power snapshots (`value_origin = estimated`) | yes, but not billing-grade |

Each row carries `formula`, `dependencies` (observation ids), `rule_id`, `rule_version` and `priority`. The
lifetime counter has priority over the daily counter.

## 15-minute frames (`site_frames_15min.csv`)

| Column | Meaning |
| --- | --- |
| `aggregation` | `mean` (power, %), `max` (temperature, AC phase voltage), `sum` (interval energy) |
| `n_obs`, `original_cadence_s`, `coverage_ratio` | Number of real samples, the source cadence (no upsampling), and the covered share of the actual frame duration |
| `frame_status` | `ok`, `partial`, `no_data`, `stale_only`, `access_denied`, or `…unallocated_<interval status>` |

Local days have 92/96/100 frames around DST (`engine.timeparse.local_day_frames`).

## Quality issues and audit (`quality_issues`, `audit_actions`)

Every issue row identifies the raw record/delivery, source line, rule id + version, mapping version, original
value, output or unresolved state, reason and affected metric. Every issue has at least one audit action.

| Category | Examples (issue_code) |
| --- | --- |
| `defect_repaired` | `exact_duplicate_suppressed` |
| `quarantined` | `unparseable_transport_line`, `truncated_or_invalid_json`, `missing_required_identifier`, `unregistered_device`, `unregistered_binding`, `unusable_time_missing`, `unusable_time_ambiguous_local_time`, `unusable_time_nonexistent_local_time`, `manifest_checksum_mismatch` |
| `unresolved` | `implausible_magnitude_unit_ambiguity`, `ambiguous_number`, `invalid_field_type`, `value_out_of_range`, `conflicting_versions`, `stale_response`, `stale_repeated_response`, `flow_direction_unresolved`, `lifetime_counter_reset` (derive stage) |
| `schema_damage` / `schema_review` | `required_key_missing` / `unknown_field`, `unrouted_endpoint` |
| `access`, `transport`, `provider_failure` | `http_access_denied`, `http_rate_limited`, `http_request_validation_error`, `provider_failure_rate_limited` |
| `data_gap` | `gap_trailing_gap_feed_stale`, `gap_stale_feed_repeated_response`, `gap_access_denied`, `gap_data_gap` |
| `informational` | `optional_field_absent`, `conflict_without_metric_difference` |

Deterministic, non-defect actions are listed in `audit_actions` with category `deterministic_transformation`:
`numeric_string_parsed`, `declared_unit_change_converted` and `registered_mapping_version_applied`. Routine unit and
sign handling is counted in `routine_transform_counts`.

## Source health (`source_health`)

`freshness_status` is computed against `--as-of` (the replay clock). The possible values are:

* `fresh`
* `fresh_documented_unavailable` (the device reported a documented unavailable state, such as asleep)
* `stale`
* `not_continuously_polled`
* `capability_unsupported`
* `access_denied`

`late_arrivals` and `historical_gaps` describe historical validity separately. Old rows are never "stale" merely
for being old.

## Review candidates (`review_candidates`)

Demo policies from `config/review_policies.yaml` are `demo_high_inverter_temperature`, `demo_phase_voltage_high`
and `demo_sustained_underproduction_peer`. Each candidate holds evidence observation ids or day statistics and the
status `open_for_review`. Candidates never modify values.
