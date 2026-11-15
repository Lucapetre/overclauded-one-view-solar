# Component extension: implementation inventory (phase 1)

Inventory of reusable modules and real file paths for the master spec ("feasible equipment data, incident intelligence and technician optimization"). It was taken from branch `phase2` at `b3976f5` by reading the code. Where the spec's "Known baseline" disagrees with the code, the code wins, and section 0 lists the differences. Nothing here has been implemented yet.

## 0. Spec baseline vs. actual code

| Spec claim | Actual state |
| --- | --- |
| React/Vite/**TypeScript** frontend | React 19 + Vite 6 in **JSX/JS** (`frontend/src/*.jsx`, `*.js`). Only the contract package is TS: `packages/contracts/index.ts` is generated, `packages/contracts/client.ts` is hand-written, and JSX imports it through the Vite alias in `frontend/vite.config.js`. `frontend/src/contracts.d.ts` is a shim. There is no `tsc` step in `package.json`. |
| "Personal task planner exists" | **Browser-only.** It lives in `frontend/src/demo.jsx` (`Plan`, line ~1060) and `frontend/src/domain.js` (`recommend()`, line 550), served at `/demo/` on localStorage. It uses a hard-coded PV shape (3 kW 12–16 h, 1.5 kW 10–17 h), half-hour steps, a fixed 6 kW per-area cap and `defaultPrices` 1.30/0.55. There is **no backend planner, task table or route**, and the connected `/consumer` app has no Plan page (`opsData.js` `ROLE_PAGES.customer` = Home, Offers, History, Support, Learn, Account). |
| "Contract-defined tariff time bands" | **Absent.** `contracts` (migration 003) has `pricing TEXT CHECK (pricing IN ('fixed'))` with one `import_price_ron_kwh` and one `export_price_ron_kwh`. The fallback is `site_profiles.json.default_tariff` (1.30/0.55). There are no bands, calendars or a DST-aware evaluator. |
| "Business loads" | `users.account_type` is `home`/`business` (migration 003). `site_profiles.segment`/`business_type` exist for compact sites only. Business consumption *shapes* are browser-side heuristics (`frontend/src/dailyForecast.js` `consumptionShape()`). There is no flexible-load model. |
| "Offer suitability checks" | These exist as **offer acceptance/preview gates**, not planner suitability. In `backend/offers.py`: `accept_offer()` checks meter/import/export capability (`meter_required`, `import_meter_required`, `export_meter_required`), and `_preview()` warns about prices vs. tariff, penalty vs. value, windows under 30 min and sites that can't measure the flow. |
| Compact demo is "24-site" | It now has **60 sites** (`backend/fixtures/site_profiles.json`): Sectors 1–6 plus Ilfov (s6 14, s1 10, ilfov 10, s3 9, s4 8, s2 5, s5 4), 35 home and 25 business. The old `north/central/south` areas survive only as `seed.LEGACY_AREAS`, and `_refuse_legacy_geography` uses them to refuse old databases. |
| Provider observations "preserve … provenance" | True in the scraper DB. The API reads observations **directly from the immutable snapshot file** and copies only frames into the API DB (see §1.3). |
| Python 3.11+ | `pyproject.toml` requires `>=3.11`, but STEP1 notes the scraper was tested on 3.10. `.venv` exists (`.venv/Scripts/python.exe`, Windows). |
| Roles customer/technician/dispatcher/supervisor | Correct (`users.role` CHECK, migration 001). Junior/senior/maintenance exist only as **labels** in `demo_data/sites.json` `platform_access.role_scopes` and are never used for access. |

## 1. Provider (phase-1) pipeline and the nine provider sites

### 1.1 Generation → scrape → build

1. **`generate_demo.py`** (1531 lines, `GENERATOR_VERSION="1.0.0"`).
   - `main()` takes args `--seed 42 --sites-per-provider 3 --start 2026-07-15 --days 7 --out demo_data --truth-out tests`.
   - Simulation: one-minute latent model. `make_weather()` uses a shared regional `DAY_PLAN` (7 days, one `LOCATION` 44.43/26.10 for all sites). `simulate_site()` covers POA per array, strings, inverter efficiency/clipping, battery dispatch with reserve/η/p_max, AR(1) load with EV, inverter temperature and phase voltage. It asserts the AC balance every minute.
   - Native builders: `build_huawei`, `build_fronius`, `build_solaredge`. `DeliveryFactory` wraps payloads in a `mock_transport` envelope. `Injector.run()` adds defects.
   - Outputs: `demo_data/<provider>/{delivery,clean_reference}/*.ndjson` plus manifests with sha256, `demo_data/sites.json` (`site_registry()`), `demo_data/regulatory_metadata.json`, `golden_cases/` and `dst_cases/`.
   - Evaluation-only outputs: `tests/ground_truth/{latent_15min.csv,daily_totals.json}` and `tests/injection_manifest.json`.
   - Extension point: `SITE_SPECS` (per-site dicts with `battery`, `meter`, `load`, `fault`, `grid.event`) and the `sims[key]` arrays, which are the latent trajectories new families must reuse (`pv_used`, `load`, `volts`, `inv_temp`, battery `soc`/`e_bat`, grid import/export).
2. **`scraper.py`** has one entry point, `ingest()` + `main()`.
   - Flags: `--config` (repeatable, later files add profiles), `--input`, `--out`, `--as-of` (replay clock with offset), `--dataset delivery`, `--side-datasets golden_equivalence,dst_edge_cases`, `--db`, `--http`, `--no-report`.
   - Steps: `Registry` → `SiteRegistry(sites.json)` → `discover()` (manifest files, checksum verified) → `Ingestor.process_file` → `finalize` → `derive.recompute` → `health.compute(as_of)` → `review.evaluate` → `runs` row. Reports come from `derive.build_frames`, `report.export_tables/export_canonical/quality_report/demo_report`.
3. **`build/`** contains:
   - `scraper.sqlite`: 353 MB, git-ignored. A gz copy (35 MB) is committed.
   - `site_frames_15min.csv`: 62,880 frame rows.
   - `canonical_measurements.csv.gz`, `interval_energy.csv`, `quality_report.json`, `source_health.csv`, `data_gaps.csv`, `quality_issues.csv`, `audit_actions.csv`, `review_candidates.json`, `demo_report.html`, and `side/*.sqlite`.
   - Scraper tables are in `engine/storage.py`: `runs, input_files, raw_deliveries, raw_records, observations, capability_states, delivery_events, quality_issues, audit_actions, routine_transform_counts, interval_energy, source_health, data_gaps, review_candidates`, plus the view `canonical_observations`.

### 1.2 The nine provider site identities (`demo_data/sites.json`)

`backend_site_id = "provider-" + sha256("provider|account_id|site_id")[:24]` (`backend/providers.py` `backend_site_id`).

| Key | Backend site_id | provider / account / native site | Variant | kWp | Battery | Meter capability | Devices |
| --- | --- | --- | --- | --- | --- | --- | --- |
| H1 | provider-d97b13196637185888be23c1 | huawei / hw-nbi-demo-01 / NE=33554791 | residential_inverter_dt38 | 6.2 | not_installed | unsupported | inv 1000000035350464 |
| H2 | provider-4d119fc90c8c2cf7b55b314c | huawei / hw-nbi-demo-01 / NE=33554792 | dt38 (3-phase, weak feeder) | 8.1 | not_installed | unsupported | inv 1000000035351021 |
| H3 | provider-3cf3aeacbce278b4207de1bd | huawei / hw-nbi-demo-02 / NE=33554850 | dt38 + dt39 battery | 9.6 | **10 kWh, 5 kW** | unsupported | inv 18000000036112209, bat 18000000036112210 |
| F1 | provider-e2f35075482123a2267dd143 | fronius / fr-lan-gw-0001 / FR-SITE-0001 | snapinverter | 5.5 | not_installed | not_installed | inv "1" |
| F2 | provider-89c51a61990828f2e6027c6f | fronius / fr-lan-gw-0002 / FR-SITE-0002 | snapinverter (+EV) | 7.8 | not_installed | **installed** | inv "1" |
| F3 | provider-ca9967cfc42fcc3e2841efe0 | fronius / fr-lan-gw-0003 / FR-SITE-0003 | gen24_hybrid | 8.8 | **11 kWh, 4.5 kW** (no battery device id) | **installed** | inv "1" |
| S1 | provider-65a9712309ce0c5bd8397af2 | solaredge / se-acct-demo-01 / 2718281 | inverter_only_no_meter | 5.9 | not_installed | not_installed (power flow unsupported) | inv 7E0412A3-6B |
| S2 | provider-5f758c0e29543b7dcf57a7e6 | solaredge / se-acct-demo-01 / 3141592 | inverter_with_meter (+EV, string loss from day 4) | 9.2 | not_installed | **installed** | inv 0071F2A3-9C |
| S3 | provider-ee134e1a6c0c4c87f7e5a752 | solaredge / se-acct-demo-02 / 1618033 | storedge_hybrid | 7.4 | **9.7 kWh, 5 kW** | **installed** | inv 7F11C0DE-21, bat BAT-00A1B2C3 |

- **All nine are residential.** None is a business. Their loads are household plus EV, and `platform_access.customer_account_id` runs CUST-0001…0009. The spec's "at least one business site" therefore needs a **new declared business role for one existing identity**, via the asset registry/overlay, without changing `sites.json` bytes.
- Every site shares one location (44.43, 26.10) and one weather plan. `ppc_region` is the label `PPC-SYNTH-NORTH/SOUTH`, which no code uses.
- Endpoints in `config/provider_profiles.yaml`:
  - Huawei: `getDevHistoryKpi` (dt38/dt39) and `getDevRealKpi`.
  - Fronius: `GetPowerFlowRealtimeData` ×2 variants and `GetInverterRealtimeData.CommonInverterData` ×2.
  - SolarEdge: `equipment_data`, `currentPowerFlow`, `storageData`. The existing SolarEdge `storageData` endpoint is the spec's B2 in embryo: it maps power, SoC, internalTemp and lifetime Wh, and S3 has a 403 day and an unexpected lifetime-counter reset.

### 1.3 `python -m backend import-provider` (`backend/providers.py::import_provider_snapshot`)

- Args `--database` (plain SQLite or `.gz`), `--sites demo_data/sites.json`, `--frames build/site_frames_15min.csv`.
- It copies the source into `<api db dir>/provider-snapshots/<tmp>.partial` (gunzip, or SQLite `backup()` so WAL pages are included). Then `import_id = sha256(sha(snapshot)|sha(sites.json)|sha(frames.csv))`, and a repeat returns `status: duplicate`.
- It reads the last completed `runs.as_of_utc`. The site keys must exactly equal those in `canonical_observations ∪ source_health`.
- For each site it builds a `ProviderSite` identity and a compact `SiteRegistration`:
  - `area_id=None`, `topology_mode='unknown'`, interval 900 s, stale 2700 s.
  - capabilities mapped through `CAPABILITIES` (for example `grid_import_kw→grid_import`, `soc_pct→soc`, `inverter_temperature_c→temperature`).
  - device `stream-<site_id>`, source `phase1-scraper`.
- It validates each CSV frame with `ProviderFrame`.
- `register_site()` inserts rows into `sites`, `devices` and **`energy_streams`**. Note that every provider site therefore "has a meter" for offer gating.
- Then it runs `os.replace` to `<import_id>.sqlite`, and in one transaction it does `INSERT provider_imports`, inserts all `provider_frames`, upserts `provider_sites.import_id` (**the atomic active-snapshot switch, per site row**) and writes audit `provider.snapshot.imported`. It never grants access.
- **What is stored:** the API DB holds only frames (`provider_frames.payload` = ProviderFrame JSON) plus identity. Observations, source_health and quality remain in the **snapshot file** and are queried read-only (`readonly()` with `mode=ro`, `query_only`) through `provider_imports.database_path`. Old imports and snapshot files are kept, so they are immutable.
- **How provider sites relate to app `sites`:**
  - They are rows in `sites` with `area_id NULL`.
  - They have **no `site_profiles` row**, so no coordinates, segment or kWp.
  - They have no `telemetry` rows and no contract unless one is saved.
- What that breaks:
  - `ops_map()` uses `JOIN site_profiles`, so they are **excluded from the map**.
  - `capacity()` also joins profiles and areas.
  - Crew eligibility (`ops._eligible`: `crew.area_id == incident.area_id`) **can never match**, so incidents could be opened but never assigned.
  - Offer `audience()` filters `s.area_id=?`, so they are **never targeted**.
  - Offer metering uses `energy.records_between()` → `telemetry`, so it **cannot meter them**.
  - Compact `snapshot()` freshness → `unavailable`.
  - Area-wide staff grants (`user_areas`) never cover them; only `grant-site` does.
- **Access:** `python -m backend grant-site <user> provider-…` (`provisioning.grant_access`). Customers can only get site grants; staff can get `grant-area` grants, but those are useless here without an `area_id`.
- **Connected app:**
  - `connected.jsx` polls `api.sites()` + `api.providerSites()` + `api.areas()`. For provider sites it polls `api.providerLatest()` (latest frame per endpoint/device/channel/metric plus `source_health`); otherwise it polls `api.latest()`.
  - History: `connected.jsx:~1375` and `customer.jsx` `providerSeries()` page through `providerFrames`/`providerObservations` with a limit of 1000.
  - `asOf()` uses `site.as_of_utc`, which is the fixed scrape clock 2026-07-22T00:00+03:00, **not** `settings.replay_at`.
  - Provider `source_health.freshness_status` is computed once at scrape time against `--as-of`.

## 2. Where each spec-assumed capability actually lives

| Capability | Location / state |
| --- | --- |
| Task planner | Demo-only: `frontend/src/demo.jsx` `Plan` and `frontend/src/domain.js` `recommend()`, `defaultPrices`. Nothing in the backend. A backend planner is **new work**. "Do not build a second planner" means porting `recommend()` semantics (window, deadline, normal start, power/energy, accepted-plan state) to a backend service and replacing its constants. |
| Tariff time bands | None. Contract API: `backend/customer.py` `get_contract`/`save_contract`, models `backend/customer_models.py`, `GET/POST /api/v1/sites/{id}/contract`, `ContractCard` in `features.jsx`. Needs a forward migration (for example `contract_bands` table, or widening the `pricing` CHECK) plus an evaluator. |
| Business loads | Only `account_type` and `site_profiles.segment/business_type`. No load/task model. |
| Offer suitability | `backend/offers.py`: `accept_offer` (~1416), `_preview` (~1067), `audience` (235), `reference_price` (265, contract or default tariff). Pure math lives in `backend/offers_math.py` (`attribute()` FIFO, penalties, settlement). |
| Offer settlement metering | `offers.allocate()` → `energy.records_between()` → **compact `telemetry` table only**, `Metric.grid_import`/`grid_export` kW × overlapped hours, with `coverage_ratio` from the intervals. Provider frames are never read. `simulate-offer-meter` (`offers_worker.py` ~315) injects wall-time synthetic telemetry through `ingest()`; this is the "wall-time meter readings into July" hack the spec says to remove. |
| Incident engine / ranking | **There is no rule engine.** Incidents come only from `seed.INCIDENTS` (11 fixed rows) and support requests (`customer.create_request` → `ops.open_incident`, P0 if immediate danger, else P2). Ranking is `ops.SEVERITY_ORDER = ORDER BY i.tier, i.created_at, i.incident_id`, with tiers P0–P3 (`ops_models.TIERS`) and families as listed in the README. There are no episodes, parent/child links, evidence IDs, revisions or rank reasons. `engine/review.py` produces `review_candidates` (temperature, phase voltage, peer underproduction) in the scraper DB, but **nothing imports them into the incidents table**. |
| Crews / assignments | Tables `crews(area_id, skills JSON = incident families, shift TEXT "08:00-18:00")`, `crew_members`, `assignments(kind dispatch\|meeting, status, scheduled_start/end)` with one active assignment per incident (unique partial index). `ops.assign_incident` picks the first eligible non-busy crew by name. `ops.auto_dispatch` (`POST /ops/dispatch/auto`) is greedy by severity, one dispatch per crew. There is no location, travel, member-level availability, plan, revision or optimistic lock. Only `dispatcher` can assign (`require_role`); supervisors read. Technicians use `send_team`/`schedule_meeting`/`resolve_incident`. |
| Map / status aggregation | `ops.ops_map()` → `OpsMap` (`MapSite`: position, area, cluster, segment, kWp, `freshness_status` from the compact snapshot, `open_incidents`, `worst_tier`). Frontend: `map.jsx` `BucharestMap`, `markerStatus`, `opsData.js` `mapStatus`/`toMapSites`, page `opsPages.jsx` `RadarOps`. There is no unified status projection, revision or unmapped list. Tiles come from **online** `tile.openstreetmap.org` (`map.jsx` `TILE_URL`), which breaks the offline fallback. Area outlines `backend/fixtures/bucharest_areas.geojson` and `frontend/src/areaBoundaries.js` work offline. |
| Polling | `packages/contracts/client.ts` `poll()` runs every 5 s with backoff to 30 s and stops on 401/403/404. It is used by `connected.jsx` and `opsPages.jsx` `usePolled`. Offers use 15 s (`offersManager.jsx`, `offersClient.jsx` `useNow(15000)`); notifications use 30 s (`notifications.jsx`). |
| Notifications | `notifications` table (migration 005, `kind` CHECK limited to offer kinds: new, accepted, reminder_30, reminder_10, settled), `offers.notify()`, routes `/api/v1/notifications*`, `NotificationBell`. New kinds need a table-rebuild migration, because SQLite can't alter a CHECK. |
| Replay clock | `settings.replay_at` is set by `seed-demo` (2026-07-15T12:15Z) and the CLI `replay-clock`. **Only** `energy.snapshot()` reads it, for compact freshness of non-live records. `Settings.clock` (`backend/config.py`, default `utc_now`) feeds offer routes in `main.py` (~784–994) and `offers_worker.settle_due`/`run_worker`, so it is **wall time** unless injected in tests. `replay-clock` does not change it. |
| Customer evidence / forecast UI | `features.jsx` `ForecastCard` + `useWeather()` fetch **live Open-Meteo** (`forecast.js` `WEATHER_URL`, Bucharest 44.43/26.1, 30-min cache) using wall-clock today/tomorrow. `DailyForecast` + `dailyForecast.js` `estimateDay` hold the shape heuristics; `forecast.js` `dailyForecast`/`hourlyPower` hold the model. `customer.jsx` has `HomeEnergyChart`, `CareCard`, `ContractAndForecast`. `ops.jsx` `FleetForecast` uses `/ops/capacity`. None of these is replay-aware or backend-computed. |

## 3. Engine extensibility for new component families

Profile schema, validated in `engine/registry.py::Registry._validate/_validate_endpoint`:

- Top-level keys: `registry_version`, `requirements_registry`, `review_policies`, `rule_versions`, `defaults`, `units` (`dimension`/`canonical`/`factor`), `canonical_metrics` (`unit`, `kind`, `bounds{min,max | max_ref,max_factor,on_exceed}`, `derived_only`) and `profiles`.
- Multiple `--config` files merge. Duplicate profile ids fail, and conflicting unit/metric redefinitions fail. A new `config/component_profiles.yaml` can therefore **add** metrics and units without touching `provider_profiles.yaml`.
- A profile has `provider`, `profile_version`, `endpoints[]`, plus optional `numeric{allow_numeric_strings, decimal_separator, thousands_separator}`, `transport.http_status_classes`, `failure_detection[]`, `value_object_keys`, `evidence` and `provenance`.
- An endpoint has `endpoint_key`, `variant`, `route[]` (conditions on envelope/payload/site), `mapping_version`, `mapping_versions[]`, `cadence_s`, `expected_delay_s`, `realtime`/`stale_after_s`, `continuous_feed`, `request_window`, `empty_response` and `records`:
  - `records` contains `iterate[]` list/map, `device_id.path`, `times[]{role,path,format ∈ epoch_ms|epoch_s|iso_offset|local_naive}`, `effective_time_roles`, `entity_scope` and `known_keys`.
  - `entities[].fields[]` have `{id, source, metric, unit|unit_from+allowed_units, transform, presence, requirement, channel, boundary, requires_capability, applies_if, expect_sign, status_map, model_behaviour, assumption_basis}`.
  - `derive[]` entries are `counter_difference` (`counter: lifetime|daily`, `max_gap_s`, `max_rate_ref`, `resolution`, `priority`) or `power_integration`.
- **Transforms allowlist** (`engine/transforms.py`): `TRANSFORMS = {numeric, value_object, sign_split, negate, edge_flow, state}` and `DERIVE_METHODS = {counter_difference, power_integration}`. Selectors (`engine/selectors.py`) are dot paths with no expressions, and conditions use `eq ne gt gte lt lte in present absent`.
- **Readers that exist:** one only. It reads NDJSON lines, each a `mock_transport` envelope with `payload` (JSON) or `payload_text` (JSON string), in `Ingestor.process_file/process_line/_envelope`. Routing requires `provider_profile_id` + `endpoint_key` + `binding{account_id,site_id}` registered in `sites.json`. Nested JSON (Shelly `EM.GetStatus`/`EMData.GetStatus`, Fronius `GetMeterRealtimeData` `Body.Data.{n}`, SolarEdge `storageData.batteries[].telemetries[]`) **already fits** via `iterate` (map/list) with no engine change, so only YAML and fixtures are needed.
- **Missing readers:**
  - (a) CSV/TOA5: there is no text-table reader.
  - (b) Register words: there is no decoding of UINT16/INT16/Int32/Int64/Float32, word order, scale, or zero-based address vs. register number.
  - (c) Invalid sentinels such as `0xFFFF` or NaN Float32. Only `parse_number` exists, and it rejects NaN/inf.
- **Cleanest extension points, all without vendor branches:**
  1. **Register decode as a new closed transform** `register_words` in `TRANSFORMS`. Field config: `{register, address_base: 0|1, type: uint16|int16|uint32|int32|int64|float32, word_order: big|little, scale, offset, invalid_sentinels[]}`. Words come from a JSON envelope payload such as `{"unit_id":…, "start_address":…, "words":[…]}`, so the existing NDJSON reader and selectors work unchanged. Decode Int64 with Python ints, and store the exact value in `original_value` (TEXT) plus a canonical REAL. **Caveat:** `observations.canonical_value` is REAL (float64), exact only up to 2^53 Wh, which is fine for realistic kWh counters, but the delta precision claim must cite `original_value`. `registry._validate_endpoint` must learn the new transform's required keys.
  2. **TOA5 reader** as a *payload decoder* chosen by envelope or endpoint config (for example endpoint `records.format: toa5` with `payload_text` carrying the file text). It parses the 4 header rows and yields a list of row dicts with keys = column names, plus `units`/`processing` maps in context (`toa5.header`). Then the existing `iterate`/`fields`/`times(local_naive + site tz)` apply. A `missing_tokens` list (for example `"NAN"`) goes into profile `numeric`. Keep the reader in a new `engine/readers.py` dispatched by a format name from YAML, not by vendor.
  3. **Counter segments / resettable counters:** `derive.counter_intervals` treats every decrease as `unknown_counter_reset`. Add an optional rule key (for example `reset_evidence_path` or `known_reset_events` from a capability or registry field) to label a *documented* reset as `segment_start`, and keep `unknown_counter_reset` otherwise. Rollover only applies with an explicit `rollover_bits`.
  4. **Aggregation semantics:** `derive.AGG_BY_KIND` has power→mean, percent→mean, temperature→max, AC-phase voltage→max, energy→sum. Add explicit per-field `aggregation` (instantaneous / interval_average / min / max / interval_energy / cumulative) for TOA5 Avg/Min/Max/Smp and Enphase interval energy, and SoC last-valid. Canonical metrics for meters (`grid_net_kw`, directional `grid_import/export_kwh` counters), battery (`battery_net_kw`, pack V/A, state enum) and weather (`poa_irradiance_wm2`, `ghi_wm2`, `module_temperature_c`, `ambient_temperature_c`, `sensor_body_temperature_c`) are YAML additions with new units `W/m2`, `kW` (exists) and `Wh` (exists).
  5. **Identity / asset registry:** `engine/sites.py::SiteRegistry` reads one `sites.json` with `devices[]`. New devices (meters, gateways, a shared Campbell station) need either a second registry file (for example `demo_components/assets.json`) merged by `SiteRegistry`, or a separate input root with its own `sites.json` carrying the **same provider/account/site identities**. Do **not** rewrite `demo_data/sites.json`: it is checksummed in `demo_data/manifest.json`, and import hashes depend on it. A shared station needs an "area resource" concept that `sites.json` lacks.
  6. **Health / quarantine:** `engine/health.py::compute` (freshness vs `--as-of`, gaps, `continuous_feed`), quarantine codes in `pipeline.py`, and `bounds.on_exceed` (`out_of_range`, `implausible_magnitude`) are reusable as they are. Invalid SoC 108 % is already handled by `soc_pct` bounds (not clamped). A mirrored stream or authority selection does **not** exist. Conflicts only cover same identity_key versions, so authority needs new derive/report logic or a backend bridge rule.
- **Architecture guard:** `tests/test_architecture.py`:
  - `VENDOR_WORDS = huawei|fronius|solaredge|fusionsolar|gen24|snapinverter|storedge` must be **extended** with schneider, shelly, victron, enphase, kipp, campbell and imt.
  - `test_fourth_provider_is_config_only` hashes `engine/*.py` + `scraper.py` before and after adding a provider in the same test (not against a stored hash), so engine edits are allowed but must stay vendor-neutral.

## 4. Tests and tooling

| Suite | Tests | Covers |
| --- | --- | --- |
| `tests/conftest.py` (session) | — | Regenerates the full dataset plus full ingestion into tmp (`generate_demo.main`, `scraper.main`); `mini` fixture for small crafted payloads |
| `test_outcomes.py` | 24 | Full 9-site replay vs hidden truth/injection manifest (slow) |
| `test_semantics.py` | 13 | Signs, units, availability, time roles on crafted payloads |
| `test_architecture.py` | 7 | No vendor branches/eval, guard, config-only 4th provider, no secrets |
| `test_time.py` | 5 | Time roles, DST |
| `test_http_replay.py` | 3 | Loopback retry/backoff |
| `test_provider_integration.py` | 10 | import-provider idempotency/no grants, preserved semantics, cross-customer denial, frames/latest, pagination, read-only snapshot + WAL, id hashing |
| `test_api.py` | 23 | Auth/session/CSRF, scope, compact energy, freshness/replay |
| `test_ingestion.py` | 9 | Compact ingest, quarantine, duplicates, concurrency |
| `test_cli.py` | 10 | CLI provisioning/import/replay-clock |
| `test_provisioning.py` | 4 | register-site/grants |
| `test_customer_features.py` | 4 | Contracts, support, lessons |
| `test_ops_features.py` | 9 | Ops scope, incidents/log, crews, assign/auto-dispatch, revenue, video |
| `test_offers.py` / `test_offers_math.py` | 17 / 10 | Offers scope/accept/metering/settlement/counters; pure math |
| `test_geography.py` | 5 | 60 sites inside OSM polygons |
| `test_frontend_host.py` | 2 | FastAPI static hosting |
| `tests/backend_fixtures.py` | — | API fixtures (plugin) |

- **Runtime:** STEP1 quotes about 4–5 min for the scraper suites on Windows because of the session regeneration (~35 s generation plus ~3 min ingestion). The backend suites are fast. Budget **5–8 min** for a full `pytest -q`, and use `-k` or file selection while iterating.
- **Lint:** `ruff` 0.17.5 with rules `E,F,I,UP,B` (`E501` ignored), target py311. **Excluded**: `engine`, `generate_demo.py`, `mock_server.py`, `scraper.py`, and the scraper tests (`conftest.py`, `test_architecture/http_replay/outcomes/semantics/time.py`). README commands: `ruff check backend scripts tests` and `ruff format --check backend scripts tests`. The spec asks to bring modified root modules into lint coverage, but that would reformat 1.5k-line files, so new engine modules should be lint-clean individually.
- **Contracts:** `scripts/export_contracts.py` writes `packages/contracts/{openapi.json,index.ts,telemetry.schema.json,site-registration.schema.json}` from the FastAPI/pydantic models, and `--check` detects drift. `client.ts` is hand-maintained, so new routes need manual methods there.
- **Frontend:** `npm --prefix frontend test` = `node --test tests/*.test.js` (10 files: bucharestTime, dispatch, domain, features, geography, offers, opsData, revenue, telemetry, video), which tests pure JS modules only. `npm --prefix frontend run build` uses Vite. No type check, no ESLint and no browser tests. `frontend/dist` is checked out locally and FastAPI serves `/consumer`, `/ops` and `/demo`.
- **CI:** none (no `.github/`).
- **Fixture bytes:** `.gitattributes` preserves fixture bytes.

## 5. Risks and gaps the phase plan must cover

1. **Two populations, no bridge.**
   - The provider sites (`provider-…`, area NULL, no profile) and the 60 compact sites (`s1-01`…, area plus profile) share the `sites` table and nothing else.
   - The ops features (map, crews, auto-dispatch, offers audience, capacity, revenue) only work for sites with `area_id` and `site_profiles`.
   - Scene D needs the nine provider identities on the map with crews. Options:
     - **(a)** A migration adding a separate `provider_site_placement`/asset-registry table with explicitly fictional coordinates and an explicit, provisioned area/zone membership. Every ops query then uses a LEFT JOIN plus an "unmapped" list. The spec forbids reusing coordinates and requires unknown sites to be shown as unmapped.
     - **(b)** Inserting `site_profiles` rows and setting `sites.area_id` for provider sites via a local provisioning command.
   - Never alias a provider site to an `s*-NN` identity. Option (b) conflicts with `register_site`'s immutable contract check (`area_id` is part of the registration), because a re-import would compare `area_id=None`. **This must be decided in phase (b).**
2. **Offer metering reads only `telemetry`.** Settling from imported meter evidence needs a bridge in `offers.allocate`, either (i) materializing bridged 15-min grid import/export into `telemetry` with provenance, or (ii) a new metering source. Option (i) reuses `ingest()` contract checks but must not use wall-time `received_at` or overlap existing intervals (409). Accepted terms and the settlement ledger stay unchanged.
3. **Wall time in analytical decisions:**
   - `Settings.clock`: offer accept/expiry/progress/settle and the worker.
   - `ops.*` uses `stamp()` (wall) for incident `created_at`/`updated_at`/assignment times. Seeded incidents use `REPLAY_AT − minutes`, so ages mix replay and wall time.
   - `seed_offers` expiry = wall now + 7 d.
   - `simulate-offer-meter` uses wall now.
   - Frontend `ageLabel(Date.now())`, `useWeather` (live Open-Meteo today) and `useNow`.
   - Provider `as_of_utc` is frozen at scrape time.
   - Only `energy.snapshot` uses `replay_at`.
   - The fix is one analytical clock provider (for example `backend/clock.py` reading `settings.replay_at` when a scenario is in replay mode), wired into `Settings.clock`, the worker, ops and the planner. Security/session/audit stay on `datetime.now`/`time.time` (`security.py`).
   - Forward-only advancement means `replay-clock` (which currently allows rewinding) needs a guard for scenario mode.
4. **North/south:**
   - Compact areas are now `sector-1..6`/`ilfov`. Old `north/central/south` DBs are refused (`legacy_demo_geography`).
   - `PPC-SYNTH-NORTH/SOUTH` in `sites.json` is a dead label; don't map it to areas.
   - The browser `/demo` (`domain.js` `AREAS`) has its own geography.
5. **No incident rule engine:** correlation, episodes, rank policy, rank explanations and a status projection are all new. They need migrations, for example `incident_evidence`, `incident_episode_links(parent, child)`, `rank_snapshots`, columns `incidents.episode_key/revision/priority_band/responsibility/rank_policy_version`, and `crew_plans`/`crew_plan_items`/`crew_availability`/`crew_locations` (fictional, labelled). `incidents.status`, `source` and `tier` have CHECK constraints (`source IN ('synthetic_replay','customer_request')`), so new values require a table rebuild in SQLite. Prefer **new tables** over altering CHECKs.
6. **Crew skills are incident *families*,** not qualifications, and the shift is a single text field. Battery-service qualification and the responsible-organization filter need new crew attributes, either a new table or nullable columns.
7. **Dispatch permission is role-based** (`require_role(user,"dispatcher")`). The spec requires "explicitly granted dispatch capability" for planners. Options: map the dispatcher role to that capability, or add a capability grant table. Supervisors must stay read-only (README: "Managers only read").
8. **Notifications CHECK** covers offer kinds only, so planner notifications need a migration.
9. **Snapshot size:** `scraper.sqlite` is 353 MB. Component imports should use a **separate scraper DB/snapshot and import pathway** (or the same `provider_imports` with a `family`/`scenario_version` column) and must never regenerate or overwrite `build/scraper.sqlite(.gz)` or `demo_data/`.
10. **Import immutability:** `import_provider_snapshot` requires `set(sites) == known`. An overlay snapshot covering only some sites or devices would fail, so the component importer needs its own function, reusing `readonly`, `digest_file` and the atomic-switch pattern.
11. **Offline demo:** OSM tiles and Open-Meteo are online-only. The scenario needs a tile-less fallback (polygons are already local) and a replayed forecast.
12. **Float counters:** see §3.1. Keep Int64 evidence as text.

## 6. Recommended file ownership for sequential phases

Phases run in order (a)→(e). Each phase owns its files exclusively; later phases may only *call* earlier ones. Files marked "append" are shared append-only and touched in one phase only.

**(a) Data, profiles, generator, engine**
- New: `config/component_profiles.yaml`, `demo_components/**` (fixtures, `manifest.json`, `assets.json` asset/capability registry incl. the business-role overlay for one existing identity, `operations_inputs.json` if produced here), `tests/component_truth/**` (eval-only), `engine/readers.py` (TOA5, payload decoders).
- Edited: `engine/transforms.py` (register_words), `engine/registry.py` (validation of new keys), `engine/derive.py` (segments, aggregation), `engine/sites.py` (asset registry merge), `engine/pipeline.py` (reader dispatch only), `engine/report.py`/`engine/storage.py` (export/quarantine/authority tables), `scraper.py` (`--component` wrapper).
- Generator: a new `generate_components.py` that imports `generate_demo` latent functions, leaving `generate_demo.py` itself unchanged so the original bytes reproduce.
- Tests: `tests/test_components_engine.py`, `tests/test_architecture.py` (VENDOR_WORDS only).
- Never touch `demo_data/**`, `build/scraper.sqlite*`, `config/provider_profiles.yaml` (except possibly shared units, which go in the new file instead), or `tests/ground_truth/**`.

**(b) Backend bridge, planner, tariff bands, replay clock**
- New: `backend/migrations/007_*.sql` (component imports, equipment/evidence tables, contract bands, tasks, scenario clock), `backend/components.py` (+`component_models.py`) for import/summary/evidence APIs, `backend/bridge.py` (equipment→decision), `backend/planner.py` (+`planner_models.py`, port of `recommend()`), `backend/tariff.py` (band evaluator), `backend/clock.py`.
- Edited: `backend/config.py` (clock wiring), `backend/offers_worker.py` + `backend/offers.py` (metering source and clock only, no financial-rule edits), `backend/customer.py`/`customer_models.py` (contract bands), `backend/energy.py` (clock), `backend/__main__.py` (append commands: `import-components`, `scenario`/forward-only replay), `backend/main.py` (append routes for equipment/planner), `backend/provisioning.py` (placement/grants).
- Tests: `tests/test_components_backend.py`, `tests/test_planner.py`, `tests/test_tariff.py`, `tests/test_replay_clock.py`.

**(c) Incident correlation, ranking, status projection, crew planner**
- New: `backend/migrations/008_*.sql`, `backend/correlation.py`, `backend/ranking.py` (+ `config/dispatch_policy.yaml`), `backend/status.py` (site-status projection), `backend/crew_planner.py` (+models), and `demo_components/operations_inputs.json` if not produced in (a).
- Edited: `backend/ops.py` (map/incidents/teams consume ranking and status; apply via existing dispatch controls), `backend/ops_models.py`, `backend/seed.py` (only the provider-scenario provisioning function), `backend/main.py` (append ops routes: plan/propose/review/apply, episode detail), `backend/__main__.py` (append).
- Tests: `tests/test_correlation.py`, `tests/test_ranking.py`, `tests/test_crew_planner.py`, plus additions to `tests/test_ops_features.py`.
- Ends with `python -m scripts.export_contracts` regenerating `packages/contracts/{openapi.json,index.ts}`.

**(d) Frontend customer and ops UI**
- Owns `packages/contracts/client.ts` (new methods) and `frontend/src/**` except demo-only files: `connected.jsx`, `customer.jsx`, `features.jsx` (evidence cards, ForecastCard replay), new `frontend/src/equipment.jsx` and `frontend/src/planner.jsx` (connected Plan page; add "Plan" to `opsData.js` `ROLE_PAGES.customer`), `opsPages.jsx` (queue, Plan teams panel), `map.jsx` (episode/route layers, unmapped list, offline tile fallback), `opsData.js`, `notifications.jsx`, and CSS (`connected.css`, `ops.css`, `features.css`).
- Tests: `frontend/tests/*.test.js` (new pure-module tests).
- Must not edit backend files. Contract mismatches go back to (b)/(c).

**(e) Demo, docs, tests**
- Docs: `README.md`, `STEP1_README.md` (append section), `DATA_DICTIONARY.md`/`SOURCE_NOTES.md` (append pointers), new `docs/COMPONENT_DATA_DICTIONARY.md`, `docs/COMPONENT_SOURCE_NOTES.md` (feasibility gate plus evidence matrix, which (a) drafts and (e) finalizes), `docs/COMPONENT_DEMO.md` (four scenes, script, slides), `docs/DISPATCH_POLICY.md`, and this inventory.
- New: `scripts/demo_scenes.py` (runner) and cross-cutting acceptance tests `tests/test_component_scenes.py`.
- Leave `frontend/src/demo.jsx`/`domain.js`/`dispatch.js` alone unless (d) explicitly hands them over. They are the browser-only demo, and their tests exist.
