# One View Solar

Phase 2 backend for the customer and PPC Operations applications: validate normalized phase 1 telemetry, persist it in SQLite, and expose authorized FastAPI queries. The architecture follows pages 5, 12 and 13 of [the build plan](./Challenge1_Build_Plan.pdf).

The repository does not contain the phase 1 pipeline or either frontend. This implementation supplies a versioned handoff contract, synthetic fixtures, generated TypeScript types and a frontend API client. The phase 1 producer must map its output to that contract; its mandatory/optional policy is registered per site rather than guessed by this service.

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
| `technician` | Assigned sites `north-01` and `north-02` |
| `supervisor` | All three explicitly granted demo areas |

Submit credentials to `POST /api/v1/auth/login` using the documentation's Try it out action. The browser stores the HttpOnly session cookie; subsequent requests use it automatically. `GET /api/v1/me` returns the current account and CSRF token. Logout requires that token in `X-CSRF-Token`.

North includes six recent feeds, one stale feed and one unavailable feed. `north-04` has mandatory-only input, `north-05` has unavailable mandatory PV, `central-01` has battery percentage without battery power, and `central-02` has complete battery flows. Coverage describes reporting freshness; it is not an equipment health diagnosis.

## Phase 1 handoff

Use [the example telemetry record](./backend/fixtures/telemetry.json), [JSON Schema](./packages/contracts/telemetry.schema.json) or [OpenAPI](./packages/contracts/openapi.json). The field names below define the proposed phase 1 to phase 2 interface.

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

All object queries enforce grants on the server. Inaccessible and nonexistent sites return the same 404 envelope. Customer area access returns 403. Operations roles do not receive implicit global access. Area coverage counts only sites visible to that account; financial and incident totals are outside this phase. `incident_status` is explicitly `not_evaluated`.

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

The [tests](./tests) cover quarantine and validation, mandatory/optional behavior, immutable/conflicting records, concurrent retries, site and area isolation, session expiry and CSRF, replay time, missing and stale feeds, AC/DC boundaries, battery capability gates, energy integration, coverage, DST ranges and local provisioning.

Forecasting, incident detection, recommendation scheduling, media handling and dispatch remain separate modules. Phase 2 provides the shared data interface they will consume.
