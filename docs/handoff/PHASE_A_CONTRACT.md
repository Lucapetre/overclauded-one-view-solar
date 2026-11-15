# Phase (a) output contract — component snapshot (meters, batteries, weather)

Status: **stable** (published by phase a). Any later change is listed in "Changelog" at the bottom.
All data are SYNTHETIC. Internal/PCC meters are operational evidence, not certified billing meters.

## 1. Regenerate and scrape (repo root, Windows: `.venv/Scripts/python`)

```
# (only if demo_data is missing; never needed otherwise — original fixtures are unchanged)
python generate_demo.py --seed 42 --sites-per-provider 3 --start 2026-07-15 --days 7 --out demo_data --truth-out tests

# component fixtures (deterministic; byte-identical on repeat). Reads demo_data read-only.
python generate_components.py --seed 42 --start 2026-07-15 --days 7 --out demo_components \
    --truth-out tests/component_truth --provider-data demo_data

# component snapshot (~2 min). Subsets: --component meter | battery | weather
python scraper.py --component all --config config/component_profiles.yaml --input demo_components \
    --out build/components --as-of 2026-07-22T00:00:00+03:00
```

Outputs (`build/components/`, git-ignored build output):

| File | Content |
|---|---|
| `component.sqlite` | the snapshot (WAL mode; copy with SQLite `backup()` like the provider import) |
| `component_observations.csv.gz` | view `component_observations` |
| `component_frames_15min.csv.gz` | table `component_frames` |
| `authority_frames.csv`, `authority_conflicts.csv` | authoritative grid energy per 15 min + conflicts |
| `capability_registry.csv`, `battery_status.csv`, `state_episodes.csv`, `limit_history.csv`, `collector_outages.csv` | derived tables |
| `assets_capabilities.json` | full asset registry (incl. business overlay) + capabilities + battery status |
| `quality_summary.json`, `quarantine.csv`, `field_rejections.csv`, `quality_issues.csv`, `mapping_notes.json` | quality / provenance |
| `interval_energy.csv`, `source_health.csv`, `data_gaps.csv` | engine tables |
| `side/component_equivalence.sqlite` | TEST-ONLY equivalence bench (never import) |

Inputs: `demo_components/manifest.json` (sha256 of every file, parameters, assumptions), `demo_components/assets.json`
(asset/capability registry). The snapshot also contains `component_meta` (key/value: `snapshot_kind=component_snapshot`,
`scenario_version=components-2026.11.15-1`, `as_of_utc`, `config_hash`, `engine_hash`, `input_manifest_sha256`,
`asset_registry_sha256`, `families`). Suggested component import id:
`sha256(input_manifest_sha256 | asset_registry_sha256 | config_hash)`.

## 2. Identities

* Sites are the 9 EXISTING provider sites. `site_key = "<provider>|<account_id>|<site_id>"` (same as the provider
  snapshot); `backend_site_id = "provider-" + sha256(site_key)[:24]` is precomputed in `site_registry.backend_site_id`
  and `assets.json.sites[].backend_site_id` (F1 = `provider-e2f35075482123a2267dd143`).
* Area resource: the Campbell station `site_key = "resource|sector-1|WX-SECTOR1-CS01"` (`site_registry.kind =
  'area_resource'`, `backend_site_id` NULL). Linked sites (H1, H2, H3) in `site_registry.json -> linked_site_keys`
  and `assets.json.resources[0].linked_site_keys`. It is NOT nine stations and NOT a topology claim.
* Test-only bench `resource|test-bench|TEST-EQUIV-BENCH` exists only in the side DB; assets with
  `source_role='test_only'` must never be imported/bridged.
* Assets (`asset_registry`): `F1-M1-PCC` (meter), `F1-B1-BMS` (battery), `F1-W1-POA` (irradiance), `F2-M2-FEEDIN`
  (meter), `H2-M3-PCC` (meter), `S2-W2-POA` (irradiance), `S3-B2-BAT` (battery = existing S3 battery
  `BAT-00A1B2C3`), `WX-S1-CS01-LOGGER` (station). Columns: asset_id, site_key, demo_site_key, family, profile_id,
  device_id, source_role, boundary, mounting, json (full record).
* Observations also exist for two EXISTING provider endpoints, used only as evidence: F2
  `GetPowerFlowRealtimeData` (mirror of the F2 meter; `physical_asset_id='1'` inverter / site scope) and H1/H2
  `getDevRealKpi` (realtime poll path of collector `COL-HW-NBI-01`). Do not double-import them as new device data.

## 3. Tables

### observations / view `component_observations`
Original engine columns plus: `family` (meter|battery|weather|NULL for provider evidence), `physical_asset_id`,
`phase` (L1..L3), `mounting` (poa|horizontal|unknown), `sensor_position` (back_of_module, instrument_body,
irradiance_reference_cell, shielded_ambient, battery, battery_internal, ...), `aggregation` (instantaneous |
interval_average | interval_min | interval_max | cumulative_counter_lifetime | cumulative_counter_resettable |
last_valid_instantaneous | state), `interval_start_ms/interval_end_ms` (TOA5 rows: [end-60 s, end]),
`scenario_version`, `source_role`, `exact_value_text` (exact decimal for integer registers, e.g. Int64 Wh -> kWh),
`state_label` (documented enum label, e.g. "Alarm"). View adds ISO `*_utc` times and `record_status`.
`availability_status`: available | missing | invalid | stale | withheld (source quality gate, e.g. Fronius
Visible=0). Use only `available` and `is_conflicted=0` for decisions. `original_value` = raw evidence (keep internal).

### component_frames (15-min, UTC-aligned, Europe/Bucharest local label)
site_key, demo_site_key, endpoint_key, provider_profile_id, family, physical_asset_id, device_key, metric_name,
channel, phase, boundary, mounting, sensor_position, source_aggregation, frame_aggregation (mean|min|max|last_valid|
last|sum), rule_id, basis (measured_counter_delta|estimated_power_integration for sum rows), frame_start_utc,
frame_end_utc, frame_start_local, frame_start_ms, value, value_time_utc (for last_valid: the observation's own time),
unit, n_obs, original_cadence_s, coverage_ratio, value_origin, frame_status (ok|partial|no_data|only_<avail>|
...+unallocated_<status>), scenario_version. Energy (`sum`) rows exist per derive rule — prefer `authority_frames`.

### authority_frames — THE grid energy contract
PK (site_key, boundary, metric_name, frame_start_ms). Sites with a declared PCC meter: F1, F2, H2; boundary
`grid_pcc`; metric `interval_grid_import_kwh` | `interval_grid_export_kwh` (separate, non-negative kWh).
Columns: value_kwh (NULL when unknown), selected_rank, selected_role (primary|fallback|mirror_fallback),
selected_basis, selected_asset_id, selected_endpoint_key, selected_rule_id, selected_coverage, value_origin
(measured|estimated), authority_status (selected_primary | selected_fallback | selected_mirror_fallback |
no_complete_source), reason, mirrors_excluded (JSON), candidates_json (every candidate's value/coverage/status),
policy_version.

**Authoritative import/export for site S, interval [t, t+15 min)**:
`SELECT value_kwh, value_origin, authority_status FROM authority_frames WHERE site_key=? AND boundary='grid_pcc' AND
metric_name IN ('interval_grid_import_kwh','interval_grid_export_kwh') AND frame_start_ms=?`.
`value_origin='measured'` = counter delta of the authoritative meter (settlement-eligible as operational evidence);
`estimated` = bounded-hold power integration (label as estimated; do NOT use for offer settlement unless the
existing measured-energy contract accepts it). NULL = unknown (never 0). Mirrors are never summed.
`authority_conflicts`: frames where another comparable complete candidate disagrees (> max(0.05 kWh, 15 %)).

### capability_registry
PK (site_key, capability). declared (0/1: an asset's profile maps it), declared_basis (asset |
linked_area_resource:<key>), assets (JSON), observed_valid (count), first/last_valid_utc, state (available |
declared_not_observed | not_declared), reason. Capabilities: grid_power_measured, grid_energy_measured,
pcc_phase_voltage, battery_soc_available, battery_limits_available, battery_alarms_available,
battery_energy_throughput, irradiance_poa_available, irradiance_ghi_available, module_temperature_available,
ambient_temperature_available. Rows exist only for sites with component assets or linked resources (F1, F2, H1, H2,
H3, S2, S3, station). Absent row = not declared.
Key facts: S3 `battery_limits_available` = not_declared (B2 has no limits) -> no battery-assisted planning from S3;
F1 all battery capabilities available.

### battery_status (one row per production battery asset at the scrape as-of)
soc_pct + soc_time_utc + soc_obs_id + soc_age_s (LAST VALID observation, never averaged), limits_available,
max_charge_current_a, max_discharge_current_a, max_charge_voltage_v, min_discharge_voltage_v, limits_time_utc
(BMS-reported registers 305-308), active_alarms (JSON [{alarm, value, label, since_utc}]), battery_state_raw (B2 raw
integer, labels NOT established), capacity_ah, declared_json (asset registry declaration: nominal V, Ah, capacity
basis kWh (derived), reserve, eta), capability_json. For a replay clock earlier than the scrape as-of, recompute from
observations (`soc_pct` last valid <= clock; limits from `limit_history`; alarms from `state_episodes`).

### limit_history / state_episodes
limit_history: constant-value runs of each BMS limit metric with start/last_seen, declared_nominal,
below_declared_nominal (1 = derated). state_episodes: runs of documented non-normal state values (battery alarms
!= 0, meter/sensor status != 0) with start/last_seen and active_at_as_of.

### collector_outages
collector_id, start/end (first..last failed attempt), affected_site_keys (JSON), endpoints, failed_attempts,
failure_classes, evidence_delivery_hashes, detail. Contains COL-HW-NBI-01: H1+H2 on 2026-07-19 09:15-11:45 local.

### site_registry / asset_registry / component_meta
See §2. `assets.json` additionally carries `collectors`, `authority` (declarations), `business_overlays`,
`maintenance_log`, `excluded_profiles`.

## 4. Canonical metrics and units
grid_net_kw (kW, + import / - export, PCC only), phase_active_power_kw, phase_voltage_v (V), ac_current_a (A;
M2 magnitude only), grid_frequency_hz, lifetime_grid_import_kwh / lifetime_grid_export_kwh (non-resettable),
resettable_grid_import_kwh / resettable_grid_export_kwh (Shelly), meter_status_raw, interval_grid_import_kwh /
interval_grid_export_kwh (derived), battery_net_kw (+ discharge / - charge, DC battery boundary), battery_voltage_v,
battery_current_a (+ discharge), soc_pct (%), battery_temperature_c, battery_capacity_ah, battery_max_charge_current_a,
battery_max_discharge_current_a, battery_max_charge_voltage_v, battery_min_discharge_voltage_v, battery_alarm_raw
(channel = alarm name; 0 no alarm, 2 alarm), battery_state_raw, interval_battery_charge_kwh /
interval_battery_discharge_kwh (DC; B1 estimated, B2 counter), irradiance_wm2 (W/m2; plane = `mounting`),
reference_cell_temperature_c, module_temperature_c, ambient_temperature_c, sensor_body_temperature_c,
sensor_status_raw. Units: kW, kWh, V, A, Hz, degC, W/m2, pct, Ah.

Irradiance: POA = `metric_name='irradiance_wm2' AND mounting='poa'` (F1-W1-POA instantaneous 1-min, S2-W2-POA
instantaneous 1-min, station interval_average/min/max 1-min, channels avg/max/min). GHI exists only on the test
bench. Use `component_frames` `frame_aggregation='mean'` + `coverage_ratio` for 15-min. Station plane: tilt 30,
az 180 (H1 plane-compatible; H2/H3 differ — compare like-for-like only).

## 5. F1 business overlay (`assets.json.business_overlays[0]`, overlay_id `F1-BUSINESS-OVERLAY-1`)
segment business, "small self-service laundry (fictional)", opening 07:00-22:00, PCC asset F1-M1-PCC (3-phase,
contracted 17.3 kW, fictional), PV = existing F1 inverter (5.5 kWp). Flexible task `F1-TASK-LAUNDRY-BATCH`:
"commercial laundry batch", 4.0 kW x 120 min = 8.0 kWh, noninterruptible, allowed window 08:00-20:00 local,
deadline 20:00 (demonstration assumption). Battery F1-B1-BMS: AC-coupled (battery inverter 3.0 kW on L2), capacity
basis 10.24 kWh (51.2 V x 200 Ah, derived), reserve 20 %, eta_charge 0.95 / eta_discharge 0.95 (AC<->storage),
storage rule E_next = E + eta_c*P_ch*dt - P_dis*dt/eta_d; BMS nominal limits 70 A charge / 100 A discharge.
Measured history contains a daily batch (09:00-11:00 local; 11:00-13:00 on 2026-07-17) — the executed-run log is
evaluation-only (tests/component_truth), the planner must not read it.

## 6. Scenario timeline (local, Europe/Bucharest)
07-16 cumulus 13-17 (brief cloud dips), M1 timeouts 03:00-03:40, B1 SoC 108 % at 14:05 (invalid), M2 Visible=0
18:10-18:20 (withheld). 07-17 Scene A day (partly cloudy); H2 Shelly duplicates 09:00-09:30, logged reset 11:02:30
(new segment), gap 14:00-15:30, EM out-of-order 16:00-17:00; station module temp NAN 11:00-16:00. 07-18 overcast
(cloud event); F1 BMS InternalFailure alarm + MaxDischargeCurrent 100 -> 25 A from 09:40 (persists to end).
07-19 S2 string loss (existing) with normal POA; H2 PCC voltage event (existing latent, visible in Shelly V);
H1+H2 collector outage 09:10-11:59; M2 export counter backwards step 12:40; B2 HTTP 403 all day (existing).
07-20 M1 word-order fault 14:00-14:25 (invalid, flagged). 07-21 morning clouds.

## 7. Guarantees
* Deterministic: generator output byte-identical for the same args (tested). Original `demo_data` manifest
  reproduces unchanged; `demo_data`/`build/scraper.sqlite*`/`tests/ground_truth` untouched.
* Idempotent: re-running the scrape into the same DB adds 0 deliveries/observations; derived tables (frames,
  authority, capability, battery_status, episodes, outages) are recomputed deterministically.
* Runtime never reads `tests/component_truth/**` (guarded).
* The snapshot covers the whole 7-day window; replay consumers must exclude rows with `effective_time_ms` later than
  their analytical clock.

## Changelog
* 2026-11-15 v1 published.
