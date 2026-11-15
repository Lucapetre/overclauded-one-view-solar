# Component data dictionary (meters, batteries, weather) — SYNTHETIC DEMONSTRATION

This dictionary covers the component snapshot `build/components/component.sqlite` and its exports. It is
produced by `python scraper.py --component all ...` from `demo_components/`. The provider (inverter) snapshot is
described in `DATA_DICTIONARY.md`. Its schema is unchanged: the extra columns below exist only in component
snapshots.

All values are synthetic. The internal/PCC meters provide operational evidence. They are **not** certified
billing meters.

## 1. Sources and identities

| Profile | Family | Site / asset | Native shape | Cadence (simulated collection) |
|---|---|---|---|---|
| `m1_schneider_iem3255_modbus` | meter | F1 `F1-M1-PCC` (PCC) | captured 16-bit register words: Float32 pairs, Int64 quads, high word first (configured) | 300 s |
| `m2_fronius_smart_meter_solar_api` | meter | F2 `F2-M2-FEEDIN` (feed-in point, location 0) | `GetMeterRealtimeData` `Body.Data.{id}` JSON | 300 s |
| `m3_shelly_pro3em_rpc` | meter | H2 `H2-M3-PCC` (PCC) | separate `EM.GetStatus` and `EMData.GetStatus` JSON | 300 s each |
| `b1_victron_gx_battery_modbus` | battery | F1 `F1-B1-BMS` (CAN-bus BMS, unit id 225) | battery-service register words | 300 s |
| `b2_solaredge_storagedata` | battery | S3 `S3-B2-BAT` = existing battery `BAT-00A1B2C3` | the **existing** `demo_data` storageData file (pinned subset) | existing fixture (15-min telemetries) |
| `w1_imt_si_rs485tc` | weather | F1 `F1-W1-POA` | input register words (0, 7, 8; 9 unsupported) | 60 s |
| `w2_kipp_smp10x_modbus` | weather | S2 `S2-W2-POA` | input register words with a scale-factor register | 60 s |
| `w3_campbell_toa5_station` | weather | area resource `resource\|sector-1\|WX-SECTOR1-CS01`, linked to H1/H2/H3 | TOA5 file with 4 header rows, logger clock UTC+02:00 | 60 s output, hourly collection |
| (B3 Enphase) | battery | — | **excluded**: no accessible response schema | — |

Evidence only (the existing provider profiles are reused unchanged):

- the F2 `GetPowerFlowRealtimeData` `P_Grid`, which mirrors the same physical meter;
- the H1/H2 `getDevRealKpi` realtime poll log of the declared collector `COL-HW-NBI-01`.

**Identity.**

- `site_key = provider|account_id|site_id`. These are the existing provider sites.
- `backend_site_id = "provider-" + sha256(site_key)[:24]`.
- A collector envelope (`collector` or `mock_transport` key) binds each delivery to `binding.asset_id`, which is
  resolved only through `demo_components/assets.json`. An unknown asset is quarantined (`unregistered_source_identity`).
- Identity checks (unit id, serial, `Meter_Location_Current`, station/table name, Kipp device type 635) quarantine
  mismatching records.

## 2. Canonical observation (`component_observations` view)

The original observation columns are kept: provenance, raw `original_value`/`original_unit`, `canonical_value`,
`canonical_text`, `availability_status`, `quality_flags`, `transform_log` and `requirement_class` (the three existing
classes, unchanged). The view adds:

| Column | Meaning |
|---|---|
| `family` | `meter` / `battery` / `weather` (NULL for reused provider evidence) |
| `physical_asset_id` | asset-registry id (B2 keeps the existing battery identity) |
| `profile_version` | pinned document revision of the profile |
| `phase` | L1/L2/L3 for per-phase values |
| `boundary` | e.g. `grid_pcc`, `dc_battery`, `battery`, `sensor_plane`, `back_of_module`, `instrument_body`, `ambient_air` |
| `mounting` | `poa` / `horizontal` / `unknown`. Taken only from the asset registry, never from the device name. |
| `sensor_position` | `back_of_module`, `irradiance_reference_cell`, `instrument_body`, `shielded_ambient`, `battery`, `battery_internal`, ... |
| `aggregation` | see §3 |
| `interval_start_utc` / `interval_end_utc` | for interval values (TOA5 rows: TIMESTAMP = interval end) |
| `exact_value_text` | exact decimal for integer registers (Int64 Wh → kWh is never routed through float) |
| `state_label` | documented enum label (e.g. Victron alarm `2` → `Alarm`). Undocumented labels (SolarEdge `batteryState`) stay raw. |
| `scenario_version` | `components-2026.11.15-1` |
| `source_role` | `production` or `test_only` (the test-only equivalence bench lives only in the side DB) |

**Availability states.**

| State | Meaning |
|---|---|
| `available` | valid value |
| `missing` | key absent, null, or a configured missing token (`NAN`) |
| `invalid` | out of bounds, decode error, status bit set, sign configuration missing, decode-configuration suspect |
| `stale` | value is old |
| `withheld` | new: the source itself marks the value unusable (Fronius `Visible = 0` / `Enable = 0`). The value is kept as evidence and excluded from counters and frames. |

## 3. Aggregation semantics

| `aggregation` | Used for | 15-min frame aggregation |
|---|---|---|
| `instantaneous` | snapshot power, voltage, current, frequency, irradiance and temperatures | `mean` of snapshots. Voltage also gets `min`/`max`; temperature also gets `max`. Coverage = n × cadence / 900 s. |
| `interval_average` / `interval_max` / `interval_min` | TOA5 Avg/Max/Min columns | mean / max / min. Coverage = sum of covered interval seconds. |
| `last_valid_instantaneous` | SoC | `last_valid`: the last valid observation and its own timestamp (`value_time_utc`). Never averaged. |
| `state` | alarms, status words, limits, capacity | `last` / `last_valid` (limits and capacity) |
| `cumulative_counter_lifetime` / `cumulative_counter_resettable` | energy counters | not framed directly. They go through interval energy (§4). |

## 4. Counters and interval energy (`interval_energy`)

- **`counter: lifetime_nonresettable`** (Schneider 3204/3208, Fronius Consumed/Produced, SolarEdge lifetime):
  - a decrease is recorded as `counter_discontinuity` with the issue `unexplained_counter_decrease`;
  - the interval energy is unknown, and is never negative;
  - no reset is invented, and the new reading becomes the baseline.
- **`counter: resettable`** (Shelly `total_act` / `total_act_ret`):
  - a decrease starts a new segment;
  - the status is `segment_start_known_reset` if `assets.json.maintenance_log` records a reset in the crossing
    interval, otherwise `segment_start_unlogged_decrease`;
  - the delta across the reset is withheld, and later deltas are valid.
- **Bounded gaps.** A delta over a span longer than `max_gap_s` gets the status `gap_span_total`. It is the total for
  that span and is not allocated to frames.
- **Rate bound.** A delta greater than capacity × duration × 1.3 gets the status `implausible_counter_jump`.
- **`power_integration`** with `component: positive|negative` and `hold: previous_sample`:
  - this is a bounded left-hold of snapshots (`max_gap_s` 600). Its status is `estimated_from_power` and its origin
    is `estimated`;
  - it is used only as a labelled fallback;
  - B1 battery energy is estimated this way, because the history registers are not supported by CAN-bus BMS.
- **Frame allocation.** An interval is allocated to a 15-min frame when both its ends are within ±10 s of that frame
  (snapshot timing tolerance). Spanning intervals are not split.

## 5. Authority (`authority_frames`, `authority_conflicts`)

Authority is declared in `assets.json.authority`, per site × `grid_pcc` × `interval_grid_import_kwh` /
`interval_grid_export_kwh`.

Candidates, in rank order:

1. the meter's counter delta (`primary`, `measured_counter_delta`);
2. the same meter's power-integration estimate (`fallback`);
3. for F2 only, the mirrored inverter-gateway `P_Grid` estimate (`mirror_fallback`).

For each frame, the first **complete** candidate (`frame_status ok`, coverage ≥ 0.995) is selected. If no candidate
is complete, the frame gets `value_kwh = NULL` and `authority_status = no_complete_source`.

- `value_origin` is `measured` for counter deltas and `estimated` otherwise.
- Candidates are never summed. `mirrors_excluded` lists the mirror copies.
- `candidates_json` keeps every candidate's value, coverage and status.
- `authority_conflicts` records frames where a comparable complete candidate (same basis, or a mirror) disagrees by
  more than max(0.05 kWh, 15 %). The selection is unchanged.

## 6. Capability flags (`capability_registry`)

A **declaration** and an **observation** are kept separate:

- `declared` = 1 when an asset at the site (or an explicitly linked area resource) has a profile that maps the
  metric(s), with matching boundary/mounting;
- `observed_valid` counts valid observations, with first/last times;
- `state` is `available`, `declared_not_observed` or `not_declared`.

Capabilities:

- `grid_power_measured`, `grid_energy_measured`, `pcc_phase_voltage`;
- `battery_soc_available`, `battery_limits_available`, `battery_alarms_available`, `battery_energy_throughput`;
- `irradiance_poa_available`, `irradiance_ghi_available`;
- `module_temperature_available`, `ambient_temperature_available`.

Key degradation: on S3, `battery_limits_available = not_declared`. B2 exposes no limits, so S3 has no
battery-assisted planning. `capability_states` additionally records documented model gaps, e.g. IMT registers 3 and
9 `unsupported`, which are never treated as measured zeros.

## 7. Battery and state tables

- **`battery_status`** (one row per production battery asset, at the scrape `as_of`):
  - last valid SoC with its time, observation id and age;
  - `limits_available`;
  - the BMS-reported limits 305–308 and their time;
  - `active_alarms` (JSON);
  - raw `battery_state_raw`;
  - `capacity_ah`;
  - the registry declaration (nominal V, Ah, a **derived** capacity basis in kWh, reserve, efficiencies). This is a
    declaration, not a BMS value.
- **`limit_history`**: constant-value runs per limit metric, with `below_declared_nominal` (derating).
- **`state_episodes`**: runs of documented non-normal states (`defaults.normal_state_values`), with
  `active_at_as_of`. These are evidence pointers, not diagnoses.
- **`collector_outages`**: windows where at least 2 sources served by one declared collector failed at
  overlapping times. They do not establish loss of supply.

## 8. Quality flags and issue codes (component additions)

- **Flags**: `decode_configuration_suspect`, `register_not_captured`, `nonfinite_float`, `invalid_sentinel`,
  `source_status_invalid`, `scale_factor_invalid`, `sign_configuration_missing`, `source_marked_incomplete`,
  `source_disabled`, `source_missing_token`, `late_arrival`, `out_of_range`.
- **Issue codes**: `register_decode_configuration_suspect`, `unexplained_counter_decrease`,
  `known_counter_reset_new_segment`, `resettable_counter_decrease_unlogged`, `source_missing_token`,
  `source_marked_incomplete`, `unregistered_source_identity`, `asset_profile_mismatch`, `unit_id_mismatch`,
  `meter_location_boundary_mismatch`, `model_identity_mismatch`, `profile_override_not_accepted`.

## 9. Exports (`build/components/`)

| File | Content |
|---|---|
| `component_observations.csv.gz` | the canonical observations |
| `component_frames_15min.csv.gz` | the 15-min frames |
| `authority_frames.csv`, `authority_conflicts.csv` | authority selection and conflicts |
| `capability_registry.csv` | capability flags |
| `assets_capabilities.json` | the asset registry + capabilities + battery status |
| `battery_status.csv`, `state_episodes.csv`, `limit_history.csv`, `collector_outages.csv` | battery and state tables |
| `quality_summary.json`, `quality_issues.csv` | quality summary and issues |
| `quarantine.csv` | quarantined deliveries/records and duplicates |
| `field_rejections.csv` | invalid/withheld fields |
| `mapping_notes.json` | every mapped field with its native ref, unit, scale, sign, boundary, aggregation, evidence status |
| `interval_energy.csv`, `source_health.csv`, `data_gaps.csv` | engine tables |
| `side/component_equivalence.sqlite` | test-only |

## 10. API bridge and replay semantics

The API imports immutable component snapshots and atomically selects the active import per existing
provider site. `component_grid_frames` keeps the selected PCC authority, origin, coverage and excluded
mirrors. Other component history is read from the copied snapshot. Every query is bounded by the
analytical clock; an end-of-scrape summary is not used as future evidence in an earlier replay.

`GET /api/v1/sites/{site_id}/equipment/summary` groups evidence into meter, battery and weather families.
Its capabilities are feature decisions (`grid_energy_verified`, `battery_assisted_planning`,
`irradiance_explanation`, `pv_performance_review`), distinct from the engine's declared/observed capability
registry. `EquipmentAsset.plane_match` is `module_plane`, `differs_from_module_plane` or `unknown`; the same
check is used by irradiance and performance decisions. A Campbell area-resource link alone is not proof
of a matching plane.

Offers and task progress read `backend.bridge.meter_series`. Only measured directional PCC energy counts
for settlement. Power estimates or mirror fallbacks remain evidence and reduce measured coverage; they
cannot fill a meter gap for a financial penalty. Task progress is whole-site connection-point energy,
not appliance-specific consumption or proof that the appliance ran.

The [phase B API contract](./handoff/PHASE_B_CONTRACT.md) describes the bridge and task endpoints. The
[source notes](./COMPONENT_SOURCE_NOTES.md) record field support and unresolved inferences.

## 11. Operational inputs and derived outputs

`demo_components/operations_inputs.json` is a separate synthetic planning dataset, not a ninth native
equipment source. It contains crew/service eligibility, qualifications/tools, members and availability,
shifts/breaks, depots, access windows, estimated service durations, travel matrix, collector declarations
and explicit topology relations (none in this scenario). Provisioning imports these records explicitly;
telemetry import grants no access.

The operational episode preserves evidence ids, physical assets, hypothesis, ordinal confidence,
responsibility and resolution provenance. `revision` and `status_as_of` accompany the common site-status
projection: condition, telemetry, workflow, highest priority, episode ids and authorized crew/ETA remain
independent. Counts distinguish unique affected sites from episodes. Unknown coordinates stay unmapped.

Crew visits carry estimated departure/arrival/start/finish, travel/service minutes, deadline result,
constraint checks and assignment reasons. Routes are schematic straight lines from an approximate demo
matrix; crew positions are reported bases, not live GPS. See the [phase C contract](./handoff/PHASE_C_CONTRACT.md)
and [dispatch policy](./DISPATCH_POLICY.md) for the full schema and lifecycle.
