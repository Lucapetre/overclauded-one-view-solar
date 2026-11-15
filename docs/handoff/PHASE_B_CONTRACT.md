# Phase (b) output contract: backend clock, tariff bands, planner, component bridge

Status: **stable** (published by phase b). All data are SYNTHETIC. PCC meters are operational evidence, not billing meters.

## 1. Local commands (Windows: `.venv/Scripts/python`; always set `SOLAR_DATABASE` to a scenario DB)

```
set SOLAR_DATABASE=.local/components.sqlite3    # separate from the compact demo DB
python -m backend import-provider --database build/scraper.sqlite      # registers the 9 provider sites (~25 s)
python -m backend import-components --database build/components/component.sqlite   # ~17 s; duplicate on repeat
python -m backend provision-component-scenario [--sites demo_data/sites.json --assets demo_components/assets.json]
python -m backend scenario start components-2026-07 --at 2026-07-17T07:30:00+03:00
python -m backend scenario advance --by 30m | --to <aware ISO> [--settle]   # forward only; --settle = one offers-worker pass
python -m backend scenario status
```

`replay-clock <ts>` in scenario mode behaves like `advance --to` and refuses a rewind. `scenario start` refuses when a scenario already runs in the DB (restart = new DB), and also when the DB holds offers or plans later than the start. `SOLAR_DEMO_PASSWORD` sets the new account passwords; otherwise they are random. Passwords go only to `<db dir>/demo-credentials.json`.

## 2. Analytical clock (`backend/clock.py`) — USE THIS for all analytical decisions

- `clock_state(connection) -> ClockState(mode 'live'|'scenario', now, scenario_id, run_id, started_at)`.
- `analytical_now(connection) -> datetime` returns the scenario time, or wall time in live mode.
- `scenario_now(connection) -> datetime | None` returns None in live mode. Never read data with an end time after it.
- `age_seconds(connection, moment_or_iso) -> float` gives incident ages and deadlines on the analytical clock.
- `Settings().clock()` (an `AnalyticalClock(database_path)`) gives the same value outside a connection. An explicit `Settings(clock=...)` injection wins (tests).
- Storage: `settings.replay_at` holds the time, `settings.scenario` holds JSON {scenario_id, run_id, start_at}. Tables: `scenario_runs`, `scenario_clock_events`.
- Keep wall time for sessions, auth and `audit.received_at`. Put the analytical time in the audit `detail` (e.g. `analytical_at`).
- `GET /api/v1/clock` → `ClockView {mode, analytical_now, wall_now, scenario_id, run_id, scenario_started_at, synthetic}`.

## 3. Placement of the 9 provider sites (D4) — table `site_placements`

`site_placements(site_id PK, area_id, latitude, longitude, location_label, coordinates_fictional=1, segment home|business, business_type, installed_kwp, module_arrays JSON [{kwp,tilt,az}], scenario_id, provenance, provisioned_at)`.

- Areas: H1 H2 H3 F1 F2 are in `sector-1` (Baneasa/Aviatiei); F3 S1 S2 S3 are in `ilfov` (Otopeni/Tunari). The labels are fictional.
- `sites.area_id` is also set, so the existing `user_areas` staff grants and offer audiences cover them. `register_site` accepts a re-import without an area for placed sites.
- **No `site_profiles` rows were created for provider sites.** Doing so would invent monthly kWh and service fees. Phase (c)'s map/ops queries should LEFT JOIN `site_placements` (lat/lon/segment/kWp) when `site_profiles` is absent, and list sites with neither as "unmapped".
- Accounts (user_id = username):
  - `laundry-owner`: customer, business; site grant F1.
  - `h2-resident`: customer, home; site grant H2.
  - `scenario-supervisor` and `scenario-dispatcher`: area grants sector-1 and ilfov.
  - No crews are created; that is phase (c)'s job (`backend/seed.py::seed_component_scenario` can be extended).
- F1 gets the demo time-of-use contract (version `cv-<F1>-1`, effective 2026-07-01 local, payment compensation, fictional rates):
  - Weekday bands: night 22-07 0.92; morning 07-11 1.52; midday 11-17 1.12; peak 17-22 1.69.
  - Weekend bands: night 0.92; day 07-22 1.15.
  - Export value 0.45 in every band; flat reference rates 1.28/0.45.
- F1 also gets task `f1-laundry-batch-2026-07-17`: 4 kW × 2 h, earliest 08:00, deadline 20:00, window 08:00-20:00 local, usual start 08:00, import limit 17.3 kW (overlay PCC).

Site ids: F1 `provider-e2f35075482123a2267dd143`, F2 `provider-89c51a61990828f2e6027c6f`, H1 `provider-d97b13196637185888be23c1`, H2 `provider-4d119fc90c8c2cf7b55b314c`, H3 `provider-3cf3aeacbce278b4207de1bd`, F3 `provider-ca9967cfc42fcc3e2841efe0`, S1 `provider-65a9712309ce0c5bd8397af2`, S2 `provider-5f758c0e29543b7dcf57a7e6`, S3 `provider-ee134e1a6c0c4c87f7e5a752`.

## 4. Migration 007 tables

`007_planner_tariff_clock.sql`:
- `scenario_runs` and `scenario_clock_events`.
- `contracts`: rebuilt with pricing fixed|time_of_use, plus `export_compensation` and `current_version_id`.
- `contract_versions(version_id, site_id, version_no, pricing, timezone, export_compensation, effective_from, valid_to, created_by, created_at wall, created_as_of analytical)`.
- `contract_bands(version_id, band_id, label, days JSON, start_minute, end_minute, import_rate_ron_kwh, export_value_ron_kwh, valid_from, valid_to)`.
- `planner_tasks`.
- `planner_commitments` (immutable acceptance snapshot; `accepted_at` analytical and `accepted_received_at` wall; `released_*` on review).
- `site_placements`.

`007_x_components.sql`:
- `component_imports(import_id, database_path, imported_at, as_of_utc, scenario_version, synthetic, meta)`.
- `component_sites(site_id PK, site_key, demo_site_key, import_id, updated_at)`: the atomic active switch.
- `component_assets(import_id, asset_id, site_id, source_site_key, family, profile_id, boundary, mounting JSON, shared_resource, link_basis, details JSON public subset)`. Production assets only. The Campbell station appears once per linked site (H1/H2/H3) with `shared_resource=1`.
- `component_capabilities(import_id, site_id, capability, declared, state, reason, assets)`: a copy of `capability_registry`.
- `component_grid_frames(import_id, site_id, metric grid_import|grid_export, frame_start, frame_end, value_kwh NULL=unknown, value_origin measured|estimated, authority_status, selected_asset_id, selected_endpoint_key, selected_basis, selected_coverage, reason, mirrors_excluded)`: a copy of `authority_frames` (grid_pcc), sites F1/F2/H2.

Other component history (battery, irradiance, alarms, limits, evidence) is read read-only from the copied snapshot `component_imports.database_path` (table `component_frames`, indexed by site_key, metric_name, frame_start_ms).

## 5. Reading authoritative component evidence per provider site (`backend/components.py`, `backend/bridge.py`)

Always pass the analytical clock as the upper bound. Helpers:
- `bridge.meter_series(conn, site_id, Metric.grid_import|grid_export, start, end) -> MeterSeries(source 'component_meter'|'compact_telemetry', intervals[MeterInterval kw|None], evidence_ids, boundary)`. Only `measured` frames carry kW; estimated or unknown frames are `None`.
- `components.grid_meter_series(...)` (component only).
- `components._grid_freshness(conn, site_id, now) -> {source,status fresh|stale|missing,last_observed_at,age_seconds}`, or None when the site has no PCC meter.
- `components.source_freshness(conn, site_id, now)`: meter, battery and irradiance freshness rows.
- `bridge.battery_capability(conn, site_id, now) -> BatteryCapability(params|None, reason_codes, evidence_ids, details)`.
  - Reason codes: `battery_limits_unavailable` (S3/B2), `battery_alarm_active_restricted` + `alarm_internal_failure` (F1 from 2026-07-18 06:40Z), `battery_limit_derated_by_bms`, `battery_soc_stale`, `battery_*_missing`, `battery_assisted_planning_available`.
- `bridge.irradiance_recent(conn, site_id, start, end) -> History(samples, plane (tilt,az), source 'site_sensor:<asset>'|'area_station:<asset>')`, or None when there is no POA sensor. GHI is never used.
- `components.capability_decisions(conn, site_id, now) -> [CapabilityDecision]` for `grid_energy_verified`, `battery_assisted_planning`, `irradiance_explanation` and `pv_performance_review`.
- `components._assets(conn, site_id, family=None)`, `components._capabilities(conn, site_id)` and `components._frames(conn, site_id, source_site_key, metric, start, end, asset_id=, aggregation=, channel=)` are bounded read-only snapshot reads. Rows are complete at `end`.
- `bridge.pv_history` gives AC PV from provider frames (`pv_ac_kw`/`pv_production_kw`; `inverter_ac_output_kw` only for non-hybrid sites). `bridge.load_history` and `components.derived_load_samples` give load = PCC import − export + AC PV + battery (DC converted to AC with declared efficiencies; labelled derived).
- Evidence ids: `authority:<asset>:<grid_import|grid_export>:<frame_start>`, `frame:<asset>:<metric>[:<channel>]:<frame_start_utc>`, `telemetry:<source>:<record>`, `frame:<endpoint>:<metric>:<start>` (provider frames).

## 6. HTTP endpoints (generated types in `packages/contracts/index.ts`; methods in `client.ts`)

| Method/path | Types | Client |
|---|---|---|
| GET /api/v1/clock | ClockView | clock() |
| GET/POST /api/v1/sites/{site_id}/contract | Contract (+pricing time_of_use, bands: TariffBand[], export_compensation, effective_from) / ContractView (+version: ContractVersionView, version_count; fixed contracts keep the old shape) | contract/saveContract |
| GET /api/v1/sites/{site_id}/tasks | Task[] | tasks() |
| POST /api/v1/sites/{site_id}/tasks | TaskCreate → Task (201, customer, CSRF) | createTask() |
| POST /api/v1/sites/{site_id}/tasks/{task_id} | TaskUpdate (expected_revision) → Task; 409 task_committed | updateTask() |
| POST …/tasks/{task_id}/cancel | Task | cancelTask() |
| GET /api/v1/sites/{site_id}/plan?task= | PlanDecision | plan() |
| POST …/tasks/{task_id}/accept | AcceptTask {recommendation_revision, start?} + Idempotency-Key → Task (201/200); 409 recommendation_changed | acceptTask() |
| POST …/tasks/{task_id}/review | ReviewTask {action:'release', reason} → Task | reviewTask() |
| GET …/tasks/{task_id}/progress | TaskProgress | taskProgress() |
| GET /api/v1/sites/{site_id}/equipment/summary | EquipmentSummary {families[EquipmentFamily], capabilities[CapabilityDecision], label, import_id, clock_mode, source_mode} | equipmentSummary() |
| GET /api/v1/sites/{site_id}/equipment/evidence?from&to&family&metric&limit≤1000&offset | EquipmentEvidence {items[EvidenceItem]} (≤ 7 days) | equipmentEvidence() |

PlanDecision fields:
- Status and costs: `status` (recommended|cost_unknown|no_feasible_start), `recommendation_revision`, `recommended_start`/`recommended_end`, `estimated_cost_ron` (incremental, null = unknown), `baseline_start`/`baseline_kind`/`baseline_cost_ron`, `estimated_difference_ron`, `cost_range`.
- Plan and constraints: `interval_plan[PlanInterval]`, `binding_constraints`, `constraints_applied`.
- Contract: `contract_version_id(s)`, `export_compensation`.
- Inputs: `forecast` (ForecastInfo: issue_time, pv_method, clearness_*, recent_source), `battery` (BatteryContribution), `input_coverage`, `freshness[SourceFreshness]`, `evidence_ids`, `reason_codes`.
- Other: `candidates[PlanCandidate]`, `commitment`, `review_suggested`, `source_mode`.

## 7. Offers

- Provider sites with `grid_energy_measured` are eligible for consume and export offers.
- Settlement and progress read `bridge.meter_series`: consume uses grid_import, export uses grid_export. Only measured frames count; estimated or unknown frames reduce coverage, so the existing `meter_data_incomplete` waiver applies.
- Data are capped at the scenario clock. The financial rules are unchanged.

## 8. Reference end-to-end numbers (real snapshot, scenario 2026-07-17 07:30 local)

- F1 laundry plan: run-now 08:00 local costs 12.16 RON; recommended 11:00-13:00 local costs 9.62 RON (estimated difference −2.54). The battery is available (SoC at the 20 % reserve) and the forecast uses POA clearness.
- After acceptance, at 14:00 local the progress shows the PCC import 9.47 kWh with coverage 1.0.
- At 2026-07-18 10:00 local the battery is restricted (internal_failure alarm, derated 25 A) and the recommendation becomes 13:30 local.
