# One View Solar

Combined phase 1 provider scraper and phase 2 backend for the customer and PPC Operations applications. Provider payloads become canonical measurements, then authorized FastAPI queries expose those measurements and their quality information to either frontend. The architecture follows pages 5, 12 and 13 of [the build plan](./Challenge1_Build_Plan.pdf).

The [phase 1 walkthrough](./STEP1_README.md), [data dictionary](./DATA_DICTIONARY.md) and [source notes](./SOURCE_NOTES.md) describe the registry-driven scraper, nine fictional Huawei/Fronius/SolarEdge sites, and its generated datasets. All bundled provider data are synthetic. The [React frontend](./frontend/README.md) now connects customer and operations workspaces to this backend using the shared API client and generated types.

## Run the integrated app

After creating an account and importing data as described below, build the frontend and start the backend from the repository root:

```sh
npm --prefix frontend ci
npm --prefix frontend run build
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open [the customer app](http://127.0.0.1:8000/consumer) or [the operations app](http://127.0.0.1:8000/ops). Sign in with a backend username such as `alice` and its actual password. The server supplies the role and authorized scope; customer accounts see their installations, while dispatchers, supervisors and technicians see their permitted operations views. The frontend restores the cookie session after reload and polls site data and area coverage every five seconds. Source labels, replay dates, missing values, boundary distinctions and coverage remain visible. Historical charts and paginated observations use the actual backend records.

For development, keep the backend running and start Vite in another terminal:

```sh
npm --prefix frontend run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). Vite proxies `/api` to `http://127.0.0.1:8000`, preserving same-origin session behavior. Set `SOLAR_BACKEND_URL` when starting Vite to use a different backend port. Built apps are served directly by FastAPI from the same origin; `SOLAR_FRONTEND_DIST` can override the build directory. Build before starting or restarting the backend. API-only use still works without a frontend build.

The frontend branch's complete planning, support, video-review and dispatch simulation remains available at `/demo/`, with a visible browser-only simulation banner. Those workflows retain their fictional accounts and local browser storage. The connected `/consumer` and `/ops` applications use real API sessions and telemetry; they do not silently fall back to mock data or claim that the simulation's mutations were saved to the backend. Planning, incidents, media and dispatch write APIs are separate work beyond phase 2.

Use `npm --prefix frontend test` to run the frontend's domain and telemetry-presentation tests. Backend hosting and authorization tests are included in the Python suite.

## Run the combined pipeline

Install the combined dependencies, import the bundled scraper outputs, create an application account, and explicitly grant that account a site:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m backend import-provider --database build/scraper.sqlite.gz
.venv/bin/python -m backend create-user alice --role customer
.venv/bin/python -m backend grant-site alice provider-ca9967cfc42fcc3e2841efe0
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

The example grant is the fictional Fronius hybrid site `FR-SITE-0003`. Import output lists every backend site ID alongside its original provider/account/site identity. Importing creates no user grants and does not translate manufacturer permissions or the dataset's role labels into application access. Site IDs are stable hashes of the complete original identity; provider and account scopes cannot collide just because native site labels match.

The importer accepts a plain scraper SQLite file or the bundled gzip copy. It saves an immutable local snapshot under the API database directory and imports the 62,880 exported 15-minute frames for all nine source sites. Repeated imports of the same database, site registry and frame file return `duplicate`. A subsequent explicit import of new output switches provider reads to the new snapshot atomically. Plain SQLite input is copied with SQLite backup so committed WAL pages are included. Snapshot files and credentials stay outside Git.

To regenerate and ingest the original native-shaped payloads before importing:

```sh
.venv/bin/python generate_demo.py --seed 42 --sites-per-provider 3 --start 2026-07-15 --days 7 --out demo_data
.venv/bin/python scraper.py --config config/provider_profiles.yaml --input demo_data --out build --as-of 2026-07-22T00:00:00+03:00
.venv/bin/python -m backend import-provider --database build/scraper.sqlite --sites demo_data/sites.json --frames build/site_frames_15min.csv
```

The API uses a read-only canonical snapshot and the actual scraper replay clock. It does not change provider mappings, reconstruct sensor timestamps, reinterpret DC as AC, or infer PV production from a hybrid inverter's net AC output. The Git attributes preserve fixture bytes because manifests contain SHA256 checksums.

### Provider endpoints

| Method and path | Response |
| --- | --- |
| `GET /api/v1/provider/sites` | Accessible imported sites, original identity, declared capabilities, source mode and replay time |
| `GET /api/v1/sites/{site_id}/provider/latest` | Latest frame per endpoint/device/channel/metric, plus source freshness and access health |
| `GET /api/v1/sites/{site_id}/provider/observations?from=…&to=…` | Canonical measurements preserving units, boundaries, channels, origin, quality flags, conflicts and requirement classes |
| `GET /api/v1/sites/{site_id}/provider/frames?from=…&to=…` | Source 15-minute frames preserving aggregation, cadence, coverage and frame status |

History endpoints accept optional `metric`, `endpoint`, `device` and `channel` filters, plus `limit` (1–1000, default 100) and `offset`. Time ranges must be offset-aware and span at most 31 elapsed days. Observation ranges are half-open; frames are included when their interval overlaps the range. Results include `total`, `limit` and `offset` for pagination. Internal database paths, raw records and source file paths are not returned.

Use these provider endpoints for the scraper dataset. They retain `integration_required`, `vendor_response_required` and `optional` exactly, and keep the separate native AC/DC/phase/unspecified boundaries. Missing measurements remain null, conflicted observations remain visibly conflicted, and access-denied/stale frames are not fabricated zero readings. Regulatory reference information remains distinct from telemetry requirements. Frames retain their original aggregation: for example temperature maxima are not relabeled as temperature means.

The older `/energy` endpoints below continue to serve the compact, normalized interval contract and its separate 24-site demo. They do not flatten imported provider observations into that narrower schema. Imported sites have unknown topology and receive no inferred area grouping.

Frontend example after login:

```ts
const sites = await api.providerSites();
const snapshot = await api.providerLatest(sites[0].site_id);
const page = await api.providerObservations(sites[0].site_id, {
  from: "2026-07-15T00:00:00+03:00",
  to: "2026-07-16T00:00:00+03:00",
  metric: "pv_dc_kw",
});
```

## Run locally

Requires Python 3.11 or later. Validation in this workspace used Python 3.14.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m backend seed-demo
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open [interactive API documentation](http://127.0.0.1:8000/docs). Startup applies pending migrations; seeding is a separate, explicit action. The demo creates 24 sites across three simulated areas and 23 synthetic telemetry records for 15 July 2026. Its analytical clock starts at 12:15 UTC on that date. These are demonstration values, not PPC measurements.

The seed command generates passwords and writes them to the ignored, mode-0600 file `.local/demo-credentials.json`. Repeating the command does not reset passwords or duplicate readings. The accounts are:

| Username | Access |
| --- | --- |
| `customer` | Own site `north-01` |
| `other-customer` | Own site `south-01` |
| `dispatcher` | Eight north-area sites and the north area summary |
| `technician` | Assigned sites `north-01` and `north-02`; member of crew Solar Care (north incidents) |
| `supervisor` | All three explicitly granted demo areas (overall manager) |
| `business-customer` | Own business site `central-03` |
| `technician-central` | Member of crew Grid Response (central incidents) |
| `technician-south` | Member of crew Field Service (south incidents) |
| `area-manager` | Supervisor role with only the north area granted |

The seed also loads the synthetic site profiles in `backend/fixtures/site_profiles.json` (map position, segment, installed kWp and a monthly billing profile), three crews and eight synthetic incidents described as demo policy rules, never as equipment diagnoses.

Submit credentials to `POST /api/v1/auth/login` using the documentation's Try it out action. The browser stores the HttpOnly session cookie; subsequent requests use it automatically. `GET /api/v1/me` returns the current account and CSRF token. Logout requires that token in `X-CSRF-Token`.

North includes six recent feeds, one stale feed and one unavailable feed. `north-04` has mandatory-only input, `north-05` has unavailable mandatory PV, `central-01` has battery percentage without battery power, and `central-02` has complete battery flows. Coverage describes reporting freshness; it is not an equipment health diagnosis.

## Phase 1 handoff

For a producer that already supplies compatible interval records, use [the compact telemetry example](./backend/fixtures/telemetry.json), [JSON Schema](./packages/contracts/telemetry.schema.json) or [OpenAPI](./packages/contracts/openapi.json). For the merged scraper, use `import-provider` and the canonical endpoints above so its richer semantics are preserved.

Every record carries schema version `1.0`, stable record/site/device/source identifiers, timezone-aware interval start/end and receipt timestamps, source mode (`live`, `replay` or `synthetic`), a private raw-record reference, and a measurements object. Unknown vendor codes and quality flags are preserved. IDs contain letters, digits, dots, underscores, colons or hyphens and are at most 96 characters. Record IDs must be unique within a source.

Each supplied measurement has `value`, `unit`, `requirement` (`mandatory` or `optional`) and `boundary` (`ac`, `dc` or `not_applicable`). `availability` defaults to `available`, `origin` to `measured`, and `quality_flags` to an empty list.

| Metric | Standard unit | Meaning |
| --- | --- | --- |
| `pv_power` | `kW` | Average production over the interval |
| `home_load` | `kW` | Average household load |
| `grid_import`, `grid_export` | `kW` | Separate nonnegative average directional grid flows |
| `battery_charge`, `battery_discharge` | `kW` | Separate nonnegative average battery flows |
| `battery_soc` | `%` | Battery percentage at the interval endpoint |
| `voltage` | `V` | Interval-average voltage at the supplied site boundary |
| `temperature` | `degC` | Interval-average temperature at the supplied device sensor |

Phase 1 must resolve multiple phases, meters and sensor meanings into the registered site stream. The service does not silently combine device records. An average interval may contain import and export at different moments; both values are preserved with a bidirectional-interval quality flag.

Power flows must be nonnegative JSON numbers. Numeric strings, booleans and nonfinite values are rejected. SoC is bounded to 0–100%; voltage to 0–1000 V; temperature to −80–200 °C. Voltage/temperature bounds are broad demo input checks, not operating limits or alarm thresholds. Intervals must be positive, at most 48 elapsed hours, and receipt must not precede interval end. This permits 25-hour local-day samples. An absent power sample is never converted to zero.

Requirement, capability and availability have different meanings:

- **Requirement** comes from the site's phase 1 contract. A producer cannot downgrade a registered mandatory metric to optional.
- **Capability** identifies which measurements the site can provide. Unsupported sensors remain explicit in read responses.
- **Availability** is `available`, `missing`, `unsupported` or `invalid`. Only `available` readings have numeric values; all other states require `null`.

Missing optional readings are accepted. Missing mandatory readings are also retained as degraded telemetry, with `mandatory_unavailable:<metric>` flags, so other usable measurements remain visible. Missing required envelope fields, invalid timestamps/units/ranges, inconsistent classifications and unregistered streams are quarantined and return 422. Conflicting record reuse or overlapping site intervals return 409 and are quarantined. Raw references and quarantine contents are backend-only.

Exact retries return `duplicate`, including under concurrent delivery. Preserve the original receipt timestamp across retries. Corrections never overwrite earlier records silently; replacing a stream or correcting history requires an explicit migration policy.

### Register a pipeline site and account

Copy [the registration example](./backend/fixtures/site-registration.json), set real identifiers and the actual mandatory/optional policy, and register it before ingestion. Every declared capability needs a classification. An optional `area` object can register an area; leave topology unknown unless its membership is authorized or explicitly simulated.

```sh
.venv/bin/python -m backend register-site backend/fixtures/site-registration.json
.venv/bin/python -m backend create-user alice --role customer
.venv/bin/python -m backend grant-site alice phase1-home-01
```

Account creation prompts for a password of 12–256 characters and grants no data access. For noninteractive local provisioning, set `SOLAR_ACCOUNT_PASSWORD`. Staff accounts may receive an explicit area grant with `grant-area <username> <area_id>`. Customers cannot receive area-wide grants. These commands require local filesystem access and have no public administration endpoint. Existing site configuration cannot be changed by rerunning registration with a different contract.

Run `create-user` once for each username. If `alice` already exists, sign in with her current password and skip account creation. To choose a different password, use the local administrator command below; it prompts for a new password of 12–256 characters and revokes existing sessions while preserving access grants:

```sh
.venv/bin/python -m backend set-password alice
```

Field crews work in one area and cover a list of incident families (`Production`, `Temperature`, `Telemetry`, `Voltage`, `Area event`, `Local issue`, `Billing`, `Other`). Only technician accounts can join a crew; a technician's operations zone is the area of each crew he belongs to:

```sh
.venv/bin/python -m backend create-crew "Night Crew" --area north --skills "Production,Telemetry,Local issue" --shift 18:00-23:00
.venv/bin/python -m backend add-crew-member "Night Crew" alice-tech
```

Repeating `grant-site` is safe. CLI account errors report the database path so commands using different `SOLAR_DATABASE` settings or working directories can be distinguished.

### Deliver records

For a worker in the same process, call [the ingestion function](./backend/ingestion.py). It is the same implementation used by HTTP and local imports:

```python
from backend.config import Settings
from backend.db import Database
from backend.ingestion import ingest

database = Database(Settings().database_path)
database.migrate()
result = ingest(database, standardized_record)
```

For file delivery, import one JSON object or an array. Each record commits separately, rejected records go to quarantine, and the command exits nonzero if any fail:

```sh
.venv/bin/python -m backend import phase1-output.json
```

For a separate phase 1 process, set a secret `SOLAR_INGEST_KEY` in the backend environment and send records to `POST /internal/v1/telemetry` with `X-Ingest-Key`. HTTP ingestion is disabled when the key is unset. Customer and operations sessions never grant pipeline-write access. Keep the key out of frontend code and use HTTPS for remote traffic.

## Customer features API

Migration `003_customer_features.sql` adds a customer account type, supply contracts, support requests and lesson rewards. All routes need a session; state changes are `POST` with `X-CSRF-Token`, and every site is checked against the caller's scope.

| Method/path | Behavior |
| --- | --- |
| `GET /api/v1/me` | `user.account_type` is `home` or `business` |
| `GET` / `POST /api/v1/sites/{site_id}/contract` | Read the site's fixed-price contract; customers with access may save it |
| `GET /api/v1/support/request-types` | The 13 request types and the team each is sent to |
| `GET` / `POST /api/v1/support/requests` | Customers see and create their own requests; staff see requests for sites in scope |
| `POST /api/v1/support/requests/{id}/replies` | Customer follow-up or staff reply |
| `GET /api/v1/lessons` | Lessons without the answer key, with completion and total reward |
| `POST /api/v1/lessons/{id}/complete` | Checks the answers on the server; rewards once per account and lesson |

Lesson rewards are a simulated bill credit, not money. Create a business customer with `python -m backend create-user bistro --role customer --account-type business`, or switch an existing customer with `python -m backend set-account-type <username> business`. `seed-demo` adds the `business-customer` account on `central-03`.

Each support request also opens a linked operations incident (`P0` for immediate danger, otherwise `P2`). The response carries `incident_id`, any scheduled `meeting` (`start`, `end`, `crew_name`) and an attached `media` video. Meter and billing questions are routed to the `Dispatch desk`.

### Support videos

| Method/path | Behavior |
| --- | --- |
| `POST /api/v1/support/requests/{id}/media?filename=…` | Owning customer only, with `X-CSRF-Token`. The body is the raw file (not multipart) with `Content-Type: video/mp4` or `video/webm`. Returns the updated request (201) |
| `GET /api/v1/support/media/{media_id}` | Streams the video inline to the owning customer or to staff who can see the request; otherwise 404. Supports HTTP Range |

One video per request (409 `media_exists`), at most 30 MB (413 `media_too_large`; only this route has the larger body limit). Other types return 415; content whose magic bytes do not match the declared type (`ftyp` at offset 4 for MP4, `1A 45 DF A3` for WebM) returns 422 `invalid_media`. Immediate-danger requests refuse videos (422 `media_not_allowed`): people must not film danger. Files are stored under `SOLAR_MEDIA_DIR` (default `.local/media`, never inside the frontend build) with random server-generated names; the client file name is only shown, after sanitizing to a basename of at most 120 characters. The 60-second duration limit is checked only in the browser. There is no virus scanning or transcoding.

## Operations API

Migration `004_operations.sql` adds synthetic site profiles, crews, incidents with an append-only incident log, assignments and support media. All routes need a non-customer session (customers get 403 `operations_required`); state changes are `POST` with `X-CSRF-Token`. Objects outside the caller's scope return 404.

| Method/path | Roles | Behavior |
| --- | --- | --- |
| `GET /api/v1/ops/map` | staff | Profiled sites in scope with position, zone, segment, kWp, freshness, open incident count and worst tier |
| `GET /api/v1/ops/incidents?status=open\|all` | staff | Ordered by tier (`P0` first), then oldest first, with the active assignment |
| `GET /api/v1/ops/incidents/{id}` | staff | The incident and its full log, oldest first |
| `POST /api/v1/ops/incidents/{id}/assign` | dispatcher | Body `{crew_id?}`; without a crew, the first eligible available crew by name |
| `POST /api/v1/ops/dispatch/auto` | dispatcher | Assigns open unassigned incidents in severity order until crews run out; returns `assigned` and `skipped` |
| `POST /api/v1/ops/incidents/{id}/send-team` | technician | Sends the technician's crew on site |
| `POST /api/v1/ops/incidents/{id}/meeting` | technician | Body `{start, end}`, timezone-aware, at most 4 hours; shown to the customer on the linked request |
| `POST /api/v1/ops/incidents/{id}/resolve` | dispatcher, supervisor, technician of the assigned crew | Completes the assignment and frees the crew |
| `GET /api/v1/ops/teams` | staff | Crews with members, availability, active assignment and per-tier report; `unassigned_incidents`; the assignment report by incident |
| `GET /api/v1/ops/revenue` | supervisor | Monthly synthetic revenue estimate for the granted areas |
| `GET /api/v1/ops/capacity` | staff | Installed kWp per area in scope, for the browser's weather-based forecast |

Scope: supervisors and dispatchers see their granted areas and sites. A technician sees the areas of his crews plus explicit grants; telemetry access (`/api/v1/sites`) is unchanged. A supervisor with every area is the overall manager; one with a single area is an area manager. Both read the same tables, so they see identical crew data for a shared area. Managers only read the assignment report; only dispatchers assign.

Assignments: a crew is eligible when it works in the incident's area and its skills include the incident's family. An incident has at most one active assignment. A crew with an active on-site dispatch is unavailable; meetings do not block a crew, but a crew's meetings may not overlap (409 `meeting_overlap`). Other conflicts return 409 `already_assigned`, `crew_unavailable`, `no_available_crew` or `assigned_to_other_crew`; an ineligible crew returns 422 `crew_not_eligible`. `Billing` incidents have no crew: the dispatcher answers them through the request replies and resolves them.

Incident log: every state change appends an entry with the actor, action and detail: `opened`, `assigned`, `auto_assigned`, `team_sent`, `meeting_scheduled`, `resolved`, `customer_follow_up`, `staff_reply` and `customer_video`. This log replaces a separate audit view.

Revenue is an estimate, not invoices: per site and month, `energy_sales = monthly_import_kwh × import_price`, `export_payments = monthly_export_kwh × export_price` (paid to the prosumer), `service_fees = service_fee_ron` and `net_revenue = energy_sales + service_fees − export_payments`. Prices come from the site's saved contract, otherwise the fixture's default tariff (1.30 / 0.55 RON/kWh). The response splits totals by segment (with `share_of_net`) and area, lists business accounts by net revenue and gives an annualized net figure. Money is rounded to 2 decimals.

## Power Block Offers

Time-limited commitments to **consume** ("use 10 kWh at 0.55 RON/kWh within 2 hours of accepting") or **export** ("feed 10 kWh into the grid at 0.70 RON/kWh within 2 hours") a fixed block of energy at an agreed price, with a penalty on the unfulfilled part, a Savings/Earnings Counter for clients and an offer management area for managers. Migration `005_power_offers.sql` adds the tables below and a nullable `audit.detail` column (JSON). All demo prices, tariffs and settlements are synthetic.

| Table | Contents |
| --- | --- |
| `offers` | Terms (`type`, `title`, `energy_kwh`, `offer_price_ron_per_kwh`, `window_minutes`, `penalty_type`, `penalty_value`, `offer_expires_at`), one `area_id`, targeting (`target_mode`, `target_segment`, `target_min_kwp`, `linked_incident_id`, `target_zone`), limits (`max_takers`, `max_total_kwh`), `status` `draft` / `available` / `cancelled` / `expired` and timestamps |
| `offer_targets` | Hand-picked clients for `target_mode=clients` |
| `user_offers` | One acceptance per client and offer (`UNIQUE(offer_id,user_id)`) for one site, with a copy of the terms, the reference-price snapshot, the window, live progress, reminder marks and the `Idempotency-Key` |
| `offer_settlements` | The ledger: one row per user offer (`UNIQUE(user_offer_id)`) with every input (metered, fulfilled, unfulfilled, excess kWh, coverage, prices, penalty terms, waiver reason) and result in bani |
| `savings_totals` | Per-client counter (`lifetime_bani`, `consume_bani`, `export_bani`, `penalties_bani`, `settled_count`), updated in the settlement transaction |
| `notifications` | In-app notifications: `offer_new`, `offer_accepted`, `offer_reminder_30`, `offer_reminder_10`, `offer_settled` |

**Roles.** There is no new role. A client is a `customer`; its areas are the areas of its sites. A manager is a `supervisor` scoped to `user_areas`; a supervisor granted every area is the admin (same code, wider scope). Other roles get 403 `manager_required` on manager routes; non-customers get 403 `customer_required` on client routes. Managers never see, create or target offers or clients outside their areas: offers elsewhere are 404, an out-of-scope `area_id` is 422 `area_out_of_scope`, hand-picked clients without a site in the offer's area are 422 `client_out_of_scope`, and a linked incident outside the offer's area is 422 `incident_out_of_scope`.

| Method/path | Who | Behavior |
| --- | --- | --- |
| `GET /api/v1/manager/offers?status=` | manager | `ManagerOffer[]`: terms, `penalty_rule_text`, `terms_text`, `max_penalty_bani`, `block_value_bani`, `audience_size`, `locked` and `stats` |
| `POST /api/v1/manager/offers` | manager | Create a draft from `OfferDraft` (201) |
| `POST /api/v1/manager/offers/preview` | manager | Validate an `OfferDraft` without saving: `audience_size`, `sites`, `sample_clients` (≤ 10), `warnings`, `errors`, `summary` |
| `GET /api/v1/manager/offers/{id}` | manager | `ManagerOfferDetail`: the offer plus `takers` with live progress and settlement amounts |
| `POST /api/v1/manager/offers/{id}` | manager | Replace the terms (full `OfferDraft`) of a draft or available offer; 409 `offer_locked` after any acceptance, 409 `offer_closed` when cancelled or expired |
| `GET /api/v1/manager/offers/{id}/preview` | manager | Preview of the saved offer |
| `POST /api/v1/manager/offers/{id}/publish` | manager | Draft to `available`; re-validates terms, 422 `expiry_in_past`, 422 `empty_audience`; notifies the audience |
| `POST /api/v1/manager/offers/{id}/cancel` | manager | Draft or available to `cancelled` (409 `offer_not_cancellable` otherwise) |
| `GET /api/v1/manager/offers/{id}/audit` | manager | Audit entries for the offer: created, updated (with changed fields), published, accepted, settled, cancelled |
| `GET /api/v1/manager/clients?area_id=` | manager | Clients with sites in scope, each site's zone, `segment`, `installed_kwp`, PV, export capability and meter |
| `GET /api/v1/offers` | client | Open offers targeted at the caller and not yet accepted, with `terms_text`, `penalty_rule_text`, `max_penalty_bani`, `eligible_sites` (reference price preview and source) and `remaining_capacity` |
| `POST /api/v1/offers/{id}/accept` | client | Body `{site_id?}`, optional `Idempotency-Key` header. Returns `UserOffer` (201; 200 for an idempotent repeat) |
| `GET /api/v1/offers/mine?status=active\|history\|all` | client | `UserOffer[]` with live progress and the `settlement` once settled |
| `GET /api/v1/offers/savings` | client | Savings/Earnings Counter: `lifetime_bani`, `this_month_bani` (Europe/Bucharest month), `penalties_paid_bani`, `consume_bani`, `export_bani`, `settled_count`, `last_settled_at`, `recent` (10) |
| `GET /api/v1/notifications?unread=` | any | The caller's 50 newest notifications and `unread_count` |
| `POST /api/v1/notifications/{id}/read`, `POST /api/v1/notifications/read-all` | any | Mark read; another user's notification is 404 |

**Validation.** `energy_kwh` in (0, 10000] with at most 3 decimals; prices in [0, 10] RON/kWh with at most 4; `window_minutes` 15–1440; `penalty_value` ≥ 0: at most 10 RON/kWh (4 decimals), 100 percent or 1000 RON flat (2 decimals); `max_total_kwh` ≥ `energy_kwh`; `target_segment` only with `segment`, `target_user_ids` only with `clients`, `target_zone` only with a `linked_incident_id` and equal to that incident site's zone. Failures are 422 `invalid_offer_terms` listing every problem; drafts may have a past expiry, publishing may not. Previews warn when a consume price is above the default import tariff, an export price is below the default export tariff, any targeted site would be worse off than with its own contract, the maximum penalty exceeds the block's value, the window is shorter than 30 minutes, or targeted sites cannot measure the needed flow.

**Targeting.** The audience is the set of (client, site) pairs in the offer's area that match. `all`: every client site in the area. `segment=prosumers`: sites with `pv_power` capability and a site profile with `installed_kwp` > 0 (or no profile); `segment=consumers`: sites without PV capability. `clients`: only the hand-picked clients. `target_min_kwp` keeps sites whose `site_profiles.installed_kwp` is at least the value (sites without a profile are excluded). `target_zone` keeps sites in that profile zone. Each acceptance is for one eligible site; `site_id` may be omitted when the client has exactly one.

**Acceptance** runs in one `BEGIN IMMEDIATE` transaction. The offer must be `available` and unexpired (409 `offer_unavailable`); untargeted callers and drafts get 404. The site must be eligible (422 `site_required` / `site_not_eligible`), have a linked meter (422 `meter_required`) and measure `grid_export` for export offers (422 `export_meter_required`) or `grid_import` for consume offers (422 `import_meter_required`). A client may run at most `offer_max_active_per_client` (default 3) offers at once (409 `too_many_active_offers`); `max_takers` and `max_total_kwh` cap the offer (409 `offer_full`). A second acceptance by the same client is 409 `already_accepted`, but repeating the same `Idempotency-Key` returns the original acceptance (a key reused for another offer is 409 `idempotency_key_reused`). The reference price is snapshotted: the site's saved contract import price (consume) or export price (export), otherwise the default tariff from `backend/fixtures/site_profiles.json` (1.30 / 0.55 RON/kWh), with `reference_price_source` `contract` or `default_tariff`. The window starts at acceptance and lasts `window_minutes`. Terms are copied onto the acceptance, and offers cannot be edited once accepted.

**Metering.** Consume offers measure `grid_import`, export offers `grid_export`, from the site's stored telemetry (the designated energy stream). Energy is kW × the overlapped hours of each interval with the window (uniform power within an interval); only `available` readings count. When several offers of the same type overlap on one site, every time slice goes FIFO to the earliest-accepted (`accepted_at`, then id) unfilled offer covering it; energy left once every covering offer is full is `excess` on the earliest covering offer. Excess is settled at the normal tariff outside this feature and is never charged here. `coverage_ratio` is the share of the window covered by intervals that report the metric. Progress is computed on every read with the same attribution, and `status` becomes `active` once any energy is attributed.

**Settlement** is idempotent. A user offer settles when its block is fully delivered, or once `window_end + offer_settlement_grace_minutes` (default 60) has passed so late meter data still counts. One transaction guarded by `status IN ('accepted','active')` and `UNIQUE(user_offer_id)` writes the ledger row, the counter and the notification, so retries, restarts and concurrent workers settle once. Settled offers keep their credited energy when overlapping offers are re-attributed later. Outcomes: `completed` (fulfilled = energy), `partial`, `expired_unfulfilled` (nothing delivered) or `cancelled`.

- `fulfilled = min(metered, energy_kwh)`, `unfulfilled = energy_kwh − fulfilled`, metered rounded half-up to 3 decimals first.
- Penalty: `per_unfulfilled_kwh` = unfulfilled × value; `percent_of_unfulfilled_value` = unfulfilled × offer price × value / 100; `flat` = value if anything is unfulfilled.
- The penalty is waived (`penalty_waived_reason`) when `coverage_ratio < 0.8` (`meter_data_incomplete`: a missing or offline meter is never the client's fault) or when the manager cancels the offer during the window (`cancelled_by_distributor`; the window closes at cancellation and the energy delivered so far settles immediately). `penalty_before_waiver_bani` keeps the waived amount.
- Consume: `amount = fulfilled × offer price + penalty`, charged (`direction=charge`); `savings = fulfilled × (reference − offer price) − penalty`.
- Export: `amount = fulfilled × offer price − penalty`, credited (`direction=credit`, may be negative); `gain = fulfilled × (offer price − reference) − penalty`, stored as `savings_bani`.
- Savings and gains may be negative and are never clamped.

**Money and time.** Calculations use `decimal.Decimal`. Prices and kWh are stored and returned as decimal strings ("0.55", "10"); money is integer bani (1 RON = 100 bani) in `*_bani` fields, rounded half-up (away from zero) once per stored amount, so `amount_bani` can differ by 1 ban from `energy_value_bani ± penalty_bani`. All timestamps are UTC ISO 8601; the frontend displays Europe/Bucharest, and "this month" uses the Bucharest calendar month of `settled_at`. Every offer the client sees carries its penalty terms both as fields and as plain-language `penalty_rule_text`/`terms_text`, including the maximum penalty.

**Worker.** Each pass marks offers past `offer_expires_at` as `expired`, updates progress, sends the 30- and 10-minute reminders once each (the 30-minute one only for windows longer than 30 minutes) and settles what is due. It runs inside the app as a background thread every `offer_worker_interval_seconds` (30) unless `SOLAR_OFFER_WORKER=false`, and from the command line. All state lives in the database, so restarting mid-window is safe.

```sh
.venv/bin/python -m backend offers-worker            # loop; --once for one pass, --interval 30
.venv/bin/python -m backend settle-offers --now 2026-11-20T12:00:00Z
.venv/bin/python -m backend reconcile-savings        # recompute counters from the ledger; --check reports only
```

**Demo meter data.** The seeded telemetry is on the fixed July 2026 replay clock, so no meter data arrives during a live demo. After a client accepts, ingest SYNTHETIC 15-minute readings for the elapsed part of the window through the normal `ingest()` path (`received_at` = now, only ended intervals):

```sh
.venv/bin/python -m backend simulate-offer-meter <user_offer_id> --fraction 0.8 --coverage 1.0
```

The attributed energy then reaches about `fraction × energy_kwh` (re-running tops up; existing intervals are never rewritten). `--coverage 0.5` reports the metric as missing in half of the new intervals to demonstrate the incomplete-data waiver. These readings are newer than the replay clock, so the site's freshness may show `future`. `seed-demo` adds, idempotently and without acceptances, two published offers by `supervisor` in area `north` (`demo-offer-north-consume`: 10 kWh at 0.55 RON/kWh within 2 hours, 0.30 RON per kWh not used; `demo-offer-north-export`: 10 kWh at 0.70 RON/kWh within 2 hours, 20% of the undelivered value) expiring 7 days after seeding, and the draft `demo-offer-north-draft`. Delete the local database and seed again for fresh expiries.

## Frontend API

| Method and path | Response |
| --- | --- |
| `POST /api/v1/auth/login` | Session and CSRF token; sets cookie |
| `POST /api/v1/auth/logout` | Revokes session; requires CSRF token |
| `GET /api/v1/me` | Signed-in account, CSRF token and expiry |
| `GET /api/v1/sites` | Only accessible sites and their capability contracts |
| `GET /api/v1/sites/{site_id}` | Authorized site metadata |
| `GET /api/v1/sites/{site_id}/energy/latest` | Latest interval, all metric states, freshness and provenance |
| `GET /api/v1/sites/{site_id}/energy?from=…&to=…&resolution=…` | Bounded, coverage-aware history |
| `GET /api/v1/areas` | Explicitly authorized operations areas |
| `GET /api/v1/areas/{area_id}/summary` | Scoped site snapshots and reporting coverage denominator |
| `GET /health` | Database readiness |

All object queries enforce grants on the server. Inaccessible and nonexistent sites return the same 404 envelope. Customer area access returns 403. Operations roles do not receive implicit global access. Area coverage counts only sites visible to that account; area summaries carry no financial or incident totals (see the Operations API for those). `incident_status` is explicitly `not_evaluated`.

Latest responses include every known metric. Missing supported metrics have `value: null` and `availability: missing`; unsupported metrics use `unsupported`. Stale readings retain their values and timestamps. Freshness is evaluated against wall time for live input and the configured replay clock for replay/synthetic input. An unset replay clock returns `unknown_clock`; future data returns `future`. Neither state is counted as recent.

Household load may be derived from compatible AC PV, import and export flows. Sites with any battery capability also require charge and discharge power; percentage alone is insufficient. Derived load is labeled `derived_assuming_zero_losses`; an impossible negative result is invalid, never clamped to zero. This is a conditional estimate, not an independent energy-accounting validation. No appliance-level load or equipment diagnosis is inferred.

History requires timezone-aware `from` and `to`, accepts at most 31 elapsed days and 10,000 source records, and supports `raw`, `15m`, `1h` or `1d`. Its interval rules are:

- Power, voltage and temperature use duration-weighted averages over available coverage; SoC uses the last available endpoint in the bucket.
- Power energy is the integral over actual covered elapsed hours. Partial energy totals describe the covered portion and are never scaled to a whole bucket.
- Per-metric coverage exposes missing periods. Buckets without readings contain null values, not zeroes.
- Buckets use UTC boundaries; `1d` means a UTC 24-hour bucket. Query a local calendar day using its actual offset-aware boundaries to represent 23-hour or 25-hour days correctly.
- Splitting an hourly average across smaller buckets preserves its integral and adds `interval_average_distributed`. `source_interval_seconds` exposes original granularity; finer display buckets do not add information.
- Different AC/DC boundaries cannot become one metric average. Source modes and quality flags remain visible.

Errors use `{code, message, request_id}`; the same ID appears in `X-Request-ID`. API responses are marked `no-store`.

### TypeScript integration

Import [the generated types](./packages/contracts/index.ts) and [the API client](./packages/contracts/client.ts) directly into either frontend:

```ts
import { SolarClient, poll } from "../../packages/contracts/client";

const api = new SolarClient("http://localhost:8000");
await api.login(username, password);
const stop = poll(
  signal => api.latest("north-01", signal),
  data => renderEnergy(data),
  error => showRefreshError(error),
);
// Call stop() when the view unmounts or the user signs out.
```

The client includes session credentials, restores CSRF via `me()`, polls every five seconds after successful requests, applies bounded retry delays, and cancels in-flight requests on cleanup. Authentication and scope failures stop polling. Display refresh failures separately from backend telemetry freshness. Always inspect `availability`, `freshness`, `origin`, source mode and coverage before presenting a value.

Use a matching hostname for browser and API (`localhost` with `localhost`, or `127.0.0.1` with `127.0.0.1`) so SameSite cookies work during development. Use separate browser profiles for the customer and operations accounts.

## Configuration and local tools

| Environment variable | Default |
| --- | --- |
| `SOLAR_DATABASE` | `.local/solar.sqlite3` |
| `SOLAR_INGEST_KEY` | Unset; disables HTTP ingestion |
| `SOLAR_COOKIE_SECURE` | `false`, permitted only for loopback HTTP development |
| `SOLAR_ALLOWED_ORIGINS` | Explicit localhost/127.0.0.1 frontend origins on ports 5173 and 5174 |
| `SOLAR_DEMO_PASSWORD` | Unset; seed generates random account passwords |
| `SOLAR_ACCOUNT_PASSWORD` | Unset; account creation prompts locally |
| `SOLAR_OFFER_WORKER` | `true`; runs the Power Block Offers worker inside the app (set `false` when running `offers-worker` separately) |

Set secure cookies and HTTPS before non-loopback session use. Allowed origins are comma-separated exact origins, not a wildcard. Passwords use salted scrypt, session tokens are stored hashed, login attempts are rate-limited, and state changes require CSRF protection. Requests are bounded to 256 KiB. Accepted/rejected ingestion, login/logout and local provisioning produce audit entries without passwords or session secrets.

Advance or rewind analytical time without changing actual session expiry or ingestion audit timestamps:

```sh
.venv/bin/python -m backend replay-clock 2026-07-15T13:00:00Z
```

SQLite uses WAL mode, foreign keys, transactional writes and versioned [migrations](./backend/migrations). Pending migrations apply at startup or via `python -m backend migrate`. The API does not expose arbitrary SQL, raw payloads, device-control commands or public reset endpoints.

## Verify and regenerate contracts

```sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check backend scripts tests
.venv/bin/ruff format --check backend scripts tests
.venv/bin/python -m scripts.export_contracts
.venv/bin/python -m scripts.export_contracts --check
```

The exporter writes OpenAPI, standalone telemetry/registration schemas and TypeScript types from the backend models. Commit regenerated outputs whenever the contract changes. Run `--check` in CI to detect drift.

Type-check the frontend contracts with TypeScript installed in the consuming frontend, or:

```sh
npm exec --yes --package typescript -- tsc --noEmit --strict --target ES2020 --module ESNext --moduleResolution bundler --lib ES2020,DOM packages/contracts/index.ts packages/contracts/client.ts
```

The [tests](./tests) cover both original pipelines plus the handoff: synthetic generation and provider mapping, quarantine and validation, requirement classes, immutable/conflicting records, concurrent retries, site and area isolation, session expiry and CSRF, replay time, missing and stale feeds, AC/DC boundaries, battery capability gates, energy integration, coverage, DST ranges, local provisioning, read-only snapshots, WAL updates and authorized canonical queries. The original scraper fixtures and phase 2 fixtures are loaded together without replacing one another.

Forecasting, incident detection, recommendation scheduling, media handling and dispatch remain separate modules. Phase 2 provides the shared data interface they will consume.
