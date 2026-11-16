# One View Solar

One shared ingestion engine, an authorized FastAPI/SQLite backend and connected customer and PPC Operations workspaces. Provider payloads become canonical measurements with provenance, quality and capability gates, then serve customer decisions and operations review. The original architecture context is on pages 5, 12 and 13 of [the build plan](./Challenge1_Build_Plan.pdf).

The [phase 1 walkthrough](./STEP1_README.md), [data dictionary](./DATA_DICTIONARY.md) and [source notes](./SOURCE_NOTES.md) describe the registry-driven scraper, nine fictional Huawei/Fronius/SolarEdge sites, and its generated datasets. All bundled provider data are synthetic. The [React frontend](./frontend/README.md) now connects customer and operations workspaces to this backend using the shared API client and generated types.

## Equipment, customer planning and operations replay

The connected app now includes Grid / Battery / Solar evidence cards, the business-load planner, correlated and ranked incidents on the existing map, and crew proposal → review → apply with a technician agenda. **Eight of nine candidate component profiles are delivered: three meters, two battery paths and three weather sources. Enphase is excluded because an accessible response schema was not established.** All readings, tariffs, coordinates, crews and travel estimates are synthetic. Read the [feasibility matrix](./docs/COMPONENT_SOURCE_NOTES.md), [architecture](./docs/COMPONENT_ARCHITECTURE.md), [five-minute demo script](./docs/COMPONENT_DEMO.md), [three-slide outline](./docs/COMPONENT_SLIDES.md), [dispatch policy](./docs/DISPATCH_POLICY.md) and [problems solved](./docs/PROBLEMS_SOLVED.md). [`docs/demo_run_output.txt`](./docs/demo_run_output.txt) is the recorded output of the runner on a clean scratch workspace.

Three data populations exist. They never share identities, and none of them is real:

| Population | Created by | Contents |
| --- | --- | --- |
| **Component scenario** (this section) | `import-provider`, `import-components`, `provision-component-scenario`, `provision-scenario-operations` | Nine provider sites H1 H2 H3 (Huawei-like), F1 F2 F3 (Fronius-like), S1 S2 S3 (SolarEdge-like), backend ids `provider-<hash>`, placed in `sector-1` and `ilfov` at fictional coordinates |
| Compact demo | `python -m backend seed-demo` (see [Run locally](#run-locally)) | 60 fictional sites `s1-01` … `s6-NN`, `ilfov-NN` in Bucharest Sectors 1–6 and Ilfov |
| Browser-only workflow demo | Nothing to run; open `/demo/` | Local simulation in `localStorage`; no API access |

Do not run `seed-demo` against a component-scenario database.

### Run the component demo

**Easiest on Windows: double-click `start.bat`.** On first run it creates `.venv` if needed, generates the demo database in an `ovs-demo` folder next to the repo (a few minutes, ~2 GB), builds the frontend, starts the server for laptop and phones, and opens `http://127.0.0.1:8020/demo/`. Later runs start in seconds. The database is generated from fixed seeds and fixtures, so every machine gets the same sites, accounts, incidents, offers and numbers; only internal random IDs, creation timestamps and password salts differ. When `DEMO_DATA_VERSION` in `scripts/setup_demo.py` changes, `start.bat` offers to rebuild an older workspace.

**Same demo as presented, one command** (new empty workspace outside the repo, ~2 GB free):

```
python -m scripts.setup_demo --workspace D:/ovs-demo
```

It builds the scenario, renames accounts to albert, maria, elena, andrei, mihai, ana, radu and ioana, runs `enrich-demo` (adding the city demo, incidents, crews, offers, revenue, the agenda and victor), builds the frontend and writes `LOGINS.md` in the workspace. Every synthetic demo account gets the same public demo password, `SolarDemo2026!` (synthetic local data only; change it with `--password`), so every machine has identical logins. Then start the server with `SOLAR_DEMO_LOGIN=true` and open `/demo/` for one-click sign-in. For phones on the same Wi-Fi, add `SOLAR_DEMO_LAN=true` and `--host 0.0.0.0`, then open `http://<laptop Wi-Fi IP>:8020/demo/`. These switches are for local demos only and are off by default. The database itself is not committed; each machine generates it.

> **Disk space:** the demo workspace needs about 2 GB, and pytest and SQLite also write temporary files (to `%TEMP%` on Windows). If your system drive is nearly full, put both on another drive before running anything, for example in PowerShell: `$env:TEMP='D:\ovs-tmp'; $env:TMP='D:\ovs-tmp'`, and use a workspace such as `D:\ovs-demo`.

Quick start on Windows PowerShell, from the repository root.

Needs Python 3.12 and Node/npm. The existing workspace already has `.venv\Scripts\python.exe`; create it only on a fresh checkout.

```powershell
# 1. One-time install and frontend build
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build

# 2. Create a scenario in a NEW, EMPTY directory outside the repository (at least 2 GB free)
$demo = 'D:\one-view-demos\rehearsal-1'
.\.venv\Scripts\python.exe -m scripts.demo_scenes --workspace $demo setup

# 3. Serve the built app on port 8016 (never port 8000 or the repository's .local/), in a second terminal
#    (set $demo to the same directory there)
$env:SOLAR_DATABASE = Join-Path $demo 'api.sqlite3'
$env:SOLAR_MEDIA_DIR = Join-Path $demo 'media'
$env:SOLAR_OFFER_WORKER = 'false'
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8016
```

Open <http://localhost:8016/consumer> or <http://localhost:8016/ops>, using the same hostname throughout, and sign in with an account below. Passwords are random and saved only in `<demo>\demo-credentials.json` (a JSON object keyed by username). Read them locally; never copy them into documentation or screenshots.

`setup` runs, in order, and prints each command: `generate_components.py` only when the checked-in fixtures are missing (otherwise it prints the regeneration command), `scraper.py --component all …` only when `build/components/component.sqlite` is absent (about 2 minutes, about 467 MB, git-ignored), `backend migrate`, `import-provider`, `import-components`, `provision-component-scenario`, `provision-scenario-operations` and `scenario start component-four-scenes-v1 --at 2026-07-17T07:30:00+03:00`. The workspace must be empty because snapshots are immutable and time never rewinds; for another rehearsal use another directory. `--rebuild-components` forces regeneration of the fixtures and snapshot.

Then run each scene in order, inspecting the UI between stages, or run everything in one go:

```powershell
.\.venv\Scripts\python.exe -m scripts.demo_scenes --workspace $demo A     # accepts the laundry batch, advances to 17 Jul 14:00
.\.venv\Scripts\python.exe -m scripts.demo_scenes --workspace $demo B     # 18 Jul 10:00: clouds plus battery alarm and derate
.\.venv\Scripts\python.exe -m scripts.demo_scenes --workspace $demo C     # data quality, meter-gap waiver, repeated import/worker
.\.venv\Scripts\python.exe -m scripts.demo_scenes --workspace $demo D     # 19 Jul 11:30 correlation, crew plan, apply, closure at 12:30
.\.venv\Scripts\python.exe -m scripts.demo_scenes --workspace $demo all   # setup and every unfinished scene
```

Each stage prints its actual values and writes them to `<demo>\demo-report.json` (no passwords or cookies). Repeating a finished stage only prints its recorded result. The runner uses its own API sessions, so do not also accept the same tasks manually in the UI on that database; follow the [demo script](./docs/COMPONENT_DEMO.md) for the live walkthrough. Choose the stages you want visible before advancing, because the clock only moves forward.

### Accounts in the component scenario

Passwords are in `<demo>\demo-credentials.json`.

| Account | Role and access |
| --- | --- |
| `laundry-owner` | Business customer, site F1 only; Plan, evidence cards, offers |
| `h2-resident` | Home customer, site H2 only; the meter-gap offer demonstration |
| `scenario-dispatcher` | Dispatcher, `sector-1` and `ilfov`; propose, review and apply crew plans; audited priority overrides |
| `scenario-supervisor` | Supervisor, `sector-1` and `ilfov`; view and propose, cannot review or apply |
| `tech-battery-1`, `tech-battery-2` | Technicians of the fictional Battery Service Crew; `tech-battery-1` is also a shared member of the PV O&M crew |
| `tech-pv-1` | Technician of the fictional PV O&M crew |
| `desk-operator` | Fictional remote-triage desk (technician role) agenda |

The other populations use their own accounts: `seed-demo` writes its credentials to `.local/demo-credentials.json` (accounts are listed under [Run locally](#run-locally)), and `/demo/` uses the public development accounts listed in the [frontend README](./frontend/README.md).

### Manual setup (what the runner does)

Use these commands to build the same scenario by hand. Set the three environment variables before the first backend command, in the same shell that runs them:

```powershell
$demo = 'D:\one-view-demos\manual-1'
New-Item -ItemType Directory -Path $demo -Force | Out-Null
$env:SOLAR_DATABASE = Join-Path $demo 'api.sqlite3'
$env:SOLAR_MEDIA_DIR = Join-Path $demo 'media'
$env:SOLAR_OFFER_WORKER = 'false'
.\.venv\Scripts\python.exe -m backend migrate
.\.venv\Scripts\python.exe -m backend import-provider --database build/scraper.sqlite.gz --sites demo_data/sites.json --frames build/site_frames_15min.csv
.\.venv\Scripts\python.exe scraper.py --component all --config config/component_profiles.yaml --input demo_components --out build/components --as-of 2026-07-22T00:00:00+03:00
.\.venv\Scripts\python.exe -m backend import-components --database build/components/component.sqlite
.\.venv\Scripts\python.exe -m backend provision-component-scenario
.\.venv\Scripts\python.exe -m backend provision-scenario-operations
.\.venv\Scripts\python.exe -m backend scenario start component-four-scenes-v1 --at 2026-07-17T07:30:00+03:00
```

Skip the `scraper.py` line when `build/components/component.sqlite` already exists for the unchanged fixtures; importing the same snapshot again reports `duplicate`. Provider and component imports grant no access; the two `provision-…` commands create the explicit grants and write new passwords to `<demo>\demo-credentials.json`.

The checked-in component fixtures are already generated. To reproduce them explicitly (deterministic), use the generator below. Do not run the original `generate_demo.py` unless you intend to rewrite the tracked `demo_data/` population and its truth files:

```powershell
.\.venv\Scripts\python.exe generate_components.py --seed 42 --start 2026-07-15 --days 7 --out demo_components --truth-out tests/component_truth --provider-data demo_data
```

Advance time forward only; each command prints the new analytical time:

```powershell
.\.venv\Scripts\python.exe -m backend scenario advance --to 2026-07-17T14:00:00+03:00
.\.venv\Scripts\python.exe -m backend scenario advance --to 2026-07-18T10:00:00+03:00
.\.venv\Scripts\python.exe -m backend scenario advance --to 2026-07-19T11:30:00+03:00 --correlate
.\.venv\Scripts\python.exe -m backend offers-worker --once
.\.venv\Scripts\python.exe -m backend scenario status
```

`scenario advance` also accepts `--by 30m`, and `--settle` runs one offers-worker pass at the new time; `python -m backend correlate` runs the incident rules at the current analytical time. For the documented Scene D deadlines, run correlation first at 19 July 11:30. Correlating the battery alarm the evening before opens its four-hour response window earlier and changes the next day's deadline result. The customer equipment and planning screens do not require an earlier correlation pass.

`build/components/component.sqlite` is git-ignored; run the scraper once on a fresh clone. Do not run `seed-demo` for this nine-provider-site scenario.

### Offline use and limits

The replay works without internet after dependencies, fixtures, snapshots and the frontend are prepared. OSM map tiles and the older live city-weather widget need internet: map markers, boundaries and the list remain available on a plain background, and the component planner uses local replay evidence. Routes are schematic estimates from an approximate demo matrix; crew markers show reported bases, never live GPS. Fronius meter units remain inferred, Victron uses only the 16-bit power register, SolarEdge battery-state numbers have no invented labels, and legal applicability remains unverified.

## Run the integrated app

This and the following sections use macOS/Linux paths (`.venv/bin/python`). On Windows use `.\.venv\Scripts\python.exe` and `npm.cmd` instead. They target the default database `.local/solar.sqlite3` on port 8000; the component demo above uses its own database and port 8016.

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

The original browser-only simulation remains available at `/demo/`, with a visible simulation banner and separate fictional accounts/local storage. The connected `/consumer` and `/ops` applications use API sessions, telemetry and the planner, support, incident, offer and dispatch write APIs. They never silently fall back to browser-only data.

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

The older `/energy` endpoints below continue to serve the compact, normalized interval contract and its separate 60-site demo. They do not flatten imported provider observations into that narrower schema. Imported sites have unknown topology. Component-scenario provisioning adds explicitly fictional area placements separately from import; area membership does not imply electrical topology.

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

Requires Python 3.11 or later; this component build uses Python 3.12 in `.venv/Scripts/python.exe`.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m backend seed-demo
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open [interactive API documentation](http://127.0.0.1:8000/docs). Startup applies pending migrations; seeding is a separate, explicit action. The demo creates 60 fictional sites in the seven real administrative areas of Bucharest Sector 1 to Sector 6 and Ilfov County (area ids `sector-1` … `sector-6`, `ilfov`; topology `simulated`) and 59 synthetic telemetry records for 15 July 2026. Its analytical clock starts at 12:15 UTC on that date. These are demonstration values, not PPC measurements.

Sites are listed in `backend/fixtures/site_profiles.json`: ids `s1-01` … `s6-NN` for the sectors and `ilfov-NN` for Ilfov, a fictional display name, the real neighbourhood or locality (`zone`), and an optional `cluster` of nearby installations drawn as one map highlight (for example 8 homes in Militari, 4 hospitality venues in the Old Town, logistics on the A1 at Chiajna). About 35 are homes in residential clusters, 10 are restaurants, cafés, bars, a hotel and a supermarket in the centre, and 15 are factories, warehouses, cold storage, a data centre and office parks, mostly in Ilfov and on the city's industrial platforms. Every name, coordinate, capacity and billing figure is invented; no real customer, business or address is represented. The area outlines in `backend/fixtures/bucharest_areas.geojson` are simplified OpenStreetMap administrative boundaries, © OpenStreetMap contributors, available under the [Open Database License 1.0](https://www.openstreetmap.org/copyright). `tests/test_geography.py` checks that every site lies inside its area polygon.

**Databases seeded by an earlier release.** An earlier release seeded a different, smaller geography. `seed-demo` refuses to mix the two: on such a database it stops with `legacy_demo_geography` and names the file. The content is synthetic demo data, so stop the server, delete the database file (by default `.local/solar.sqlite3` with its `-wal` and `-shm` files) and run `seed-demo` again; there is no data migration.

The seed command generates passwords and writes them to the ignored, mode-0600 file `.local/demo-credentials.json`. Repeating the command does not reset passwords or duplicate readings. The accounts are:

| Username | Access |
| --- | --- |
| `customer` | Own home `s6-01` (Home · Militari 1, Militari cluster, Sector 6) |
| `other-customer` | Own home `s4-01` (Home · Berceni 1, Sector 4) |
| `business-customer` | Own business site `s3-06` (Old Town Bistro, Sector 3) |
| `dispatcher` | The 14 Sector 6 sites and the `sector-6` area summary |
| `technician` | Assigned sites `s6-01` and `s6-02`; member of crew Sector 6 Solar Care (Sector 6 incidents) |
| `technician-s1` … `technician-s5`, `technician-ilfov` | Member of that area's crew (Sector 1 Solar Care … Sector 5 Solar Care, Ilfov Field Service) |
| `area-manager` | Supervisor role with only `sector-6` granted |
| `supervisor` | All seven explicitly granted demo areas (overall manager) |

The seed also loads the synthetic site profiles (map position, zone, cluster, segment, installed kWp and a monthly billing profile), seven crews (one per area, each covering every incident family except `Billing`) and eleven synthetic incidents across the areas, from a `P0` area event in Titan to `P3` reminders, described as demo policy rules, never as equipment diagnoses.

Submit credentials to `POST /api/v1/auth/login` using the documentation's Try it out action. The browser stores the HttpOnly session cookie; subsequent requests use it automatically. `GET /api/v1/me` returns the current account and CSRF token. Logout requires that token in `X-CSRF-Token`.

Sector 6 includes twelve recent feeds, one stale feed (`s6-02`) and one registered site without telemetry (`s6-03`, with a `P3` telemetry incident). `s6-04` has mandatory-only input, `s6-09` has unavailable mandatory PV, `s3-01` has battery percentage without battery power, and `s3-02` has complete battery flows. Coverage describes reporting freshness; it is not an equipment health diagnosis.

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
.venv/bin/python -m backend create-crew "Night Crew" --area sector-6 --skills "Production,Telemetry,Local issue" --shift 18:00-23:00
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

Lesson rewards are a simulated bill credit, not money. Create a business customer with `python -m backend create-user bistro --role customer --account-type business`, or switch an existing customer with `python -m backend set-account-type <username> business`. `seed-demo` adds the `business-customer` account on `s3-06` (Old Town Bistro).

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
| `GET /api/v1/ops/map` | staff | Profiled sites in scope with position, area alias, zone, cluster, segment, kWp, freshness, open incident count and worst tier; `clusters` (`id`, `name`, `area_id`, `kind`) that have a site in scope |
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

The attributed energy then reaches about `fraction × energy_kwh` (re-running tops up; existing intervals are never rewritten). `--coverage 0.5` reports the metric as missing in half of the new intervals to demonstrate the incomplete-data waiver. These readings are newer than the replay clock, so the site's freshness may show `future`. `seed-demo` adds, idempotently and without acceptances, two published offers by `supervisor` in area `sector-6` (`demo-offer-s6-consume`: 10 kWh at 0.55 RON/kWh within 2 hours, 0.30 RON per kWh not used; `demo-offer-s6-export`: 10 kWh at 0.70 RON/kWh within 2 hours, 20% of the undelivered value) expiring 7 days after seeding, and the draft `demo-offer-s6-draft`. Delete the local database and seed again for fresh expiries.

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
  signal => api.latest("s6-01", signal),
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

Set analytical time without changing actual session expiry or ingestion audit timestamps. In a running scenario, this command accepts forward-only movement; restart with a new scenario database:

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

On Windows use `.\.venv\Scripts\python.exe` and `.\.venv\Scripts\ruff.exe`; `export_contracts` writes CRLF there, so convert `packages/contracts/openapi.json` and `index.ts` back to LF before `--check`. The component and operations suites are `tests/test_components_*`, `test_tariff`, `test_planner`, `test_replay_clock`, `test_correlation`, `test_ranking`, `test_crew_planner` and `test_ops_features`, plus `test_component_scenes` for the cross-cutting scenario checks. The frontend has `npm --prefix frontend test` and `npm --prefix frontend run build`.

The exporter writes OpenAPI, standalone telemetry/registration schemas and TypeScript types from the backend models. Commit regenerated outputs whenever the contract changes. Run `--check` in CI to detect drift.

Type-check the frontend contracts with TypeScript installed in the consuming frontend, or:

```sh
npm exec --yes --package typescript -- tsc --noEmit --strict --target ES2020 --module ESNext --moduleResolution bundler --lib ES2020,DOM packages/contracts/index.ts packages/contracts/client.ts
```

The [tests](./tests) cover both original pipelines plus the handoff: synthetic generation and provider mapping, quarantine and validation, requirement classes, immutable/conflicting records, concurrent retries, site and area isolation, session expiry and CSRF, replay time, missing and stale feeds, AC/DC boundaries, battery capability gates, energy integration, coverage, DST ranges, local provisioning, read-only snapshots, WAL updates and authorized canonical queries. The original scraper fixtures and phase 2 fixtures are loaded together without replacing one another.

The component scenario adds the planner, bridge, correlation, ranking, status projection and crew planner as separate modules (`backend/planner.py`, `bridge.py`, `correlation.py`, `ranking.py`, `status.py`, `crew_planner.py`, `dispatch.py`) on top of this data interface; media handling stays in `backend/media.py`.

## Component scenario backend: clock, tariff bands, planner, equipment bridge

All component data are SYNTHETIC. Internal/PCC meters are operational evidence, not certified billing meters.

### Local setup (separate scenario database)

Use the [component demo quick start above](#run-the-component-demo) for install, generation, import, both provisioning commands, external scenario storage and port 8016. The [staged demo runner](./docs/COMPONENT_DEMO.md) records actual values from the four scenes.

- `import-components` copies the snapshot with SQLite `backup()` (WAL pages included) to `<db dir>/component-snapshots/<import_id>.sqlite`. The import id comes from the snapshot's input manifest, asset registry, config and engine hashes. A repeat is `duplicate`, and every covered site switches in one transaction. The provider sites must already be imported. Importing never grants access.
- `provision-component-scenario` places H1 H2 H3 F1 F2 in `sector-1` and F3 S1 S2 S3 in `ilfov` at labelled fictional coordinates (`site_placements`). It creates `laundry-owner` (business, F1), `h2-resident` (home, H2), `scenario-supervisor` and `scenario-dispatcher` (both granted sector-1 and ilfov), a demo time-of-use contract for F1 and the illustrative 4 kW x 2 h laundry task. New passwords go only to `<db dir>/demo-credentials.json`, as with `seed-demo`. It is idempotent and does not touch the compact demo.

### Analytical clock

- With no scenario, analytical time is wall time. In a scenario run, it is the forward-only clock stored in the database (`settings.replay_at` plus `settings.scenario`, with `scenario_runs` and `scenario_clock_events`).
- Analytical time drives planning, forecast issue time, telemetry freshness, offer acceptance, expiry, reminders, progress and settlement. Component data after it are never read.
- Sessions, login and `audit.received_at` keep real wall time. Audit details carry the analytical event time.
- Rewinds are refused. To restart a scenario, create a new local database.
- `replay-clock` advances the scenario clock in scenario mode and keeps its old behaviour otherwise. `simulate-offer-meter` is only needed in live mode.
- `GET /api/v1/clock` reports the mode and both times. It is read-only.

### Contract time bands (`backend/tariff.py`)

- `POST /api/v1/sites/{id}/contract` accepts `pricing: "time_of_use"` with `bands[]`, where each band has `days` (ISO weekdays), `start_minute`, `end_minute`, import rate, export value and optional local validity dates. When end ≤ start, the band crosses midnight.
- It also accepts `export_compensation` (`payment`, `credit` or `unspecified`) and an optional future `effective_from`.
- Every save creates an immutable version. Existing fixed contracts became version 1 with one all-day band.
- Intervals are split at every band and version boundary in Europe/Bucharest time, so DST days have 23 or 25 hours.
- Missing coverage is an explicit gap (null plus a reason), never zero.
- Power Block Offers still use the flat reference rates, so the offer rule is unchanged.

### Business task planner (`backend/planner.py`)

The planner is a backend port of the demo's `recommend()`. Each task is non-interruptible and has power, energy, earliest start, deadline, an optional latest start, an optional local daily window, an optional usual start and an optional site import limit.

For every 15-minute start, the incremental cost is `site_cost(with task) - site_cost(without task)` over one common horizon, where `site_cost = Σ import kWh × band rate − export kWh × band value − terminal stored energy × η_d × terminal import rate`.

- Self-consumed solar costs the export value it displaces.
- A battery is used only when the bridge reports fresh SoC, capacity, reserve, BMS limits, efficiencies and the conversion boundary, and no active alarm. Its AC limits are the minimum of the converted BMS limits and the battery inverter rating.
- Unknown inputs give `null` costs with reasons, or tariff bounds (`cost_range`). Ties go to the earliest start.
- The forecast uses only data known at decision time: clear-sky PV for the registered arrays, scaled by recent measured clearness. POA irradiance on the same plane is preferred, else measured AC PV, with a bounded three-hour adjustment. Base load is the measured three-day profile, or the typical-shape assumption.

Routes (customer writes need CSRF):

- `GET`/`POST /api/v1/sites/{id}/tasks`
- `POST …/tasks/{task_id}` (edit, `expected_revision`; refused once accepted)
- `POST …/tasks/{task_id}/cancel`
- `GET /api/v1/sites/{id}/plan?task=`
- `POST …/tasks/{task_id}/accept` (`recommendation_revision`, Idempotency-Key)
- `POST …/tasks/{task_id}/review` (`release`)
- `GET …/tasks/{task_id}/progress` (measured whole-site PCC energy and coverage, with the attribution note and an estimated comparison)

### Equipment bridge and API (`backend/bridge.py`, `backend/components.py`)

- Offers and progress read the authoritative PCC meter per 15 minutes: consume offers use `grid_import` and export offers use `grid_export`.
- Only *measured* counter energy settles. Estimated or unknown frames reduce coverage, so the existing `meter_data_incomplete` waiver applies.
- Gateway mirrors are never added. Hybrid inverter output is never PV, and DC battery power is never grid energy. Compact sites keep the `telemetry` path.
- `GET /api/v1/sites/{id}/equipment/summary` returns, per family, the selected source, recent values, freshness and declared capabilities. It also returns these decisions: `grid_energy_verified`, `battery_assisted_planning`, `irradiance_explanation` and `pv_performance_review`.
- `GET /api/v1/sites/{id}/equipment/evidence?family=&metric=&from=&to=&limit=&offset=` covers at most 7 days and at most 1000 rows, with no raw payloads or paths.
- Both routes are scoped like other site routes: out-of-scope sites return 404.

### Correlation, ranking, status projection and crew planning (`backend/correlation.py`, `ranking.py`, `status.py`, `crew_planner.py`, `dispatch.py`)

These run only on the analytical clock and read only data that exist at that time. The demonstration policy is in `config/dispatch_policy.yaml` and described in [`docs/DISPATCH_POLICY.md`](./docs/DISPATCH_POLICY.md); the synthetic crews, shifts, access windows, reported bases and approximate travel matrix are in `demo_components/operations_inputs.json` and never appear in vendor payloads.

- `provision-scenario-operations` creates the fictional technicians, crews and planning inputs; `correlate` (or `scenario advance --correlate`) runs the rules once and is idempotent. A rule without its evidence reports `not_evaluated`; mirrored evidence is not independent corroboration; a lost feed never resolves an episode.
- Operations routes (non-customer session; writes need `X-CSRF-Token`): `GET /api/v1/ops/queue`, `GET /api/v1/ops/episodes/{id}` (plus `acknowledge`, `close`, `priority-override` and its `revoke`), `GET /api/v1/ops/status`, `GET /api/v1/ops/unmapped`, the extended `GET /api/v1/ops/map` and `GET /api/v1/ops/teams`, `POST /api/v1/ops/plans`, `GET /api/v1/ops/plans/latest` and `/plans/{id}`, `POST …/plans/{id}/review` and `…/apply`, `GET /api/v1/ops/agenda` and `POST /api/v1/ops/assignments/{id}/progress`. Queue, map, status and teams report one operations `revision`.
- A plan is a bounded, deterministic **feasible heuristic proposal** (draft → reviewed → applied or superseded) compared with a feasible FIFO baseline under identical constraints; the verdict may be `no_improvement`. Only a dispatcher may review and apply (the supervisor receives 403 `dispatch_capability_required`); a stale proposal returns 409 `plan_stale` and a new draft; a repeated apply with the same idempotency key returns the same assignments.
- The full request and response shapes are in `packages/contracts/openapi.json` and `packages/contracts/client.ts`.
