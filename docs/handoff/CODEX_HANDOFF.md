# Handoff for Codex: continue the "equipment data, incident intelligence and crew optimization" build

You are taking over a build that a Claude Code architect was running with sequential subagents. Work happened in phases (a) to (e). This file tells you what is done, what may be half-finished, what is left, how to verify, and what "done" means. **Read this whole file before editing anything.**

Repo: `d:\hackhaton innovation labs` (Windows 11), git branch `phase2`, remote `origin` (GitHub `Lucapetre/overclauded-one-view-solar`). The last pushed commit before this work is `b3976f5`. Everything described below is **uncommitted** in the working tree. Do not discard it.

## THE TASK AND THE FINAL OUTPUT

**The task in one sentence.** Extend the existing One View Solar app so that equipment data (grid meters, batteries and irradiance/weather sensors from 8 verified vendor sources) is ingested by one shared, configuration-driven engine. The app then uses that data to:
1. tell a business customer when to run a flexible load (a 4 kW × 2 h laundry batch) at the lowest estimated cost;
2. let operations staff see correlated, safety-first-ranked incidents on the existing map;
3. let operations staff propose and explicitly apply a feasible technician crew schedule.

Everything runs on one replay clock (16–21 July 2026 scenario) and works locally for a hackathon demo. The full requirements are in `docs/handoff/MASTER_SPEC.md`, the product owner's document and the source of truth.

**Why.** A ~12-hour hackathon for PPC (a Romanian electricity distributor). Four teammates will present a working laptop prototype in a **five-minute pitch with four demo scenes**:

| Scene | What the audience must see |
|---|---|
| A: business decision | The laundry owner (`laundry-owner`, provider site F1) sees the three source formats (meter registers, battery data, TOA5 weather file) and their normalised Grid / Battery / Solar cards. Next comes "run now vs recommended slot" with estimated costs from the contract time bands, the solar forecast and battery constraints. They accept, then measured progress appears after the run. |
| B: new evidence changes the decision | On 18 July, clouds plus a battery alarm and derate on F1. The recommendation recalculates; the battery is excluded with a plain-language reason. Accepted commitments are not silently changed. Operations sees evidence; no crew is sent for a cloud. |
| C: data quality preserves trust | Duplicate and mirrored readings and a counter reset are handled. There is no doubled energy and no invented delta. A meter gap means incomplete verification, so the offer penalty is waived. Repeating the import or worker leaves the totals unchanged. |
| D: operations, map and crews | The dispatcher sees a ranked incident queue and the same incidents on the map: F1 battery fault, H2 voltage review, weather-consistent drop, H1+H2 monitoring outage, S2 underperformance. They generate a crew plan with skills, shifts, travel and reasons, one honestly unassigned job, and a comparison with a FIFO/manual baseline. They apply it (the supervisor cannot). A stale plan is rejected, a repeated apply makes no duplicates, and resolving an episode updates the map, counts and ranking. |

**The final output (what must exist when you are done).** From spec §16, with its current status:

1. **Done (a).** Deterministic native-shaped datasets that passed the feasibility gate: 8 of 9 (Enphase excluded), with generation command, manifest, defects and exclusion list.
2. **Done (a).** Component profile config, asset/capability registry and shared engine extensions.
3. **Done (b).** Canonical import, bridge, migrations, scoped API, contracts. **Phase (c)'s APIs: check.**
4. Integrated customer planner and offer checks (**done b+d1**), multi-device incident correlation and ranking, and an updated operations map/status projection (**c backend in progress; d2 UI not started**).
5. Crew assignment and visit-order planning, an authorized propose/review/apply UI, technician agenda updates, and the replay clock (**clock done b; planner c in progress; UI d2 not started**).
6. Focused tests and recorded validation results (**per phase; final run in (e)**).
7. An updated README with real install, generate, ingest, provision, start and replay commands (**partly b; finalise in (e)**).
8. The feasibility evidence matrix, requirement classes, prerequisites and the distinct synthetic operations inputs (**done in research and (a); finalise in (e)**).
9. One compact architecture diagram (**(e)**).
10. A five-minute script for the four scenes with the actual generated values and states (**(e)**).
11. A three-slide presentation outline with screenshot suggestions and no invented percentages (**(e)**).
12. A concise final handoff: changed files, how to run, checks passed or failed, what remains simulated or unverified, essential limitations (**(e)**).
13. Extra, requested by the user: `docs/PROBLEMS_SOLVED.md` (**written; refresh after (d2) and the demo run**).

**Definition of done** (spec §16):
- A reviewer starts the app locally and ingests every included verified format.
- They inspect quality and feasibility handling and log in with scoped roles.
- They see the evidence-based business-load decision and the correlated, ranked incidents on the existing map.
- They generate and explicitly apply a feasible crew schedule, and see the technician and map update.
- They advance the replay time and repeat, with no duplicated measurements, assignments or financial records.

**STATUS: ALL PHASES DONE (uncommitted until the user asks to push).** Remaining known issues: the Scene B estimate is lower with the battery excluded (7.69 vs 8.96 RON, explained in `PRESENTATION_BRIEFING.md`); the Home 'Your production forecast' widget uses today's live weather, not the replay clock; `D:\ovs-scratch` is a 2.1 GB scratch folder that can be deleted.

**My last task as architect (historical).** Phases (a), (b), (c) and (d1) are finished. Phase (d2), the operations UI against `docs/handoff/PHASE_C_CONTRACT.md`, is running in a subagent and was partly written when this was updated (see the §1 row). First check whether it finished (tests and build pass, Plan teams panel and technician agenda exist); if not, complete it from the §3 brief. After it comes (e) the demo runner, docs, slides, final verification and the final handoff. Check §1 for the live status and pick up from the first unfinished phase.

## Project primer (you know nothing yet; start here)

**What the product is.** "One View Solar / SolarLenes" is a hackathon prototype for a Romanian electricity distributor (PPC). It brings data from many solar installations into one place for two kinds of users:
- **Customers (prosumers):** households and businesses, using a mobile-first "consumer" workspace.
- **Operations staff:** dispatchers, technicians and managers, using the "ops" workspace.

All data is synthetic. The product owner's latest assignment is `docs/handoff/MASTER_SPEC.md`. In short, it asks you to:
1. add verified equipment data (grid meters, batteries, irradiance/weather sensors) through one shared, configuration-driven ingestion engine;
2. use that data to recommend the cheapest time to run a flexible business load (a laundry batch);
3. correlate incidents across devices and rank them safety-first;
4. propose and apply technician crew schedules on the operations map.

**Stack and layout:**
- **Backend:** Python 3.12, FastAPI, SQLite with versioned SQL migrations.
  - `backend/`: the app; `backend/main.py` holds the routes and `backend/__main__.py` the CLI.
  - `backend/migrations/NNN_*.sql`: applied in order at startup and by `python -m backend migrate`.
  - Tests are in `tests/`; fixtures in `tests/backend_fixtures.py`.
- **Phase-1 data pipeline** (older, independent of the API):
  - `generate_demo.py` generates synthetic native vendor data into `demo_data/`.
  - `scraper.py` and `engine/` form a registry-driven ingestion engine configured by `config/provider_profiles.yaml`. They write `build/scraper.sqlite` (committed gzipped as `build/scraper.sqlite.gz`).
  - The new component extension adds `generate_components.py`, `config/component_profiles.yaml`, `demo_components/` and `build/components/`.
- **API contract:**
  - `scripts/export_contracts.py` generates `packages/contracts/openapi.json` and `index.ts` from the FastAPI app.
  - `packages/contracts/client.ts` is a hand-written typed client. Add a method there for every new endpoint the UI uses.
- **Frontend:** React 19 + Vite in `frontend/`, plain JSX, `lucide-react` icons, hand-written CSS, node:test unit tests in `frontend/tests/`. `npm --prefix frontend run build` writes `frontend/dist`, which the FastAPI app serves at `/consumer`, `/ops` and `/demo/`. The dev server is `npm --prefix frontend run dev` (Vite, which proxies `/api`).
  - **The connected app** (`frontend/src/connected.jsx` plus customer and ops modules) talks to the real backend. **All new work goes here.**
  - **The browser-only demo** at `/demo/` (`frontend/src/demo.jsx`, `domain.js`, `dispatch.js`, `store.js`) keeps its state in localStorage and is not connected to the backend. Do not change it in this assignment.

**Two separate site populations. Never mix them.**
1. **The compact demo:** 60 fictional sites `s1-01` … `s6-NN` and `ilfov-NN`, in areas `sector-1` … `sector-6` and `ilfov`, created by `python -m backend seed-demo`. Coordinates come from `backend/fixtures/site_profiles.json`; real OSM sector boundaries are in `backend/fixtures/bucharest_areas.geojson`. The ops features (incidents, crews, revenue, map, offers) were first built for these sites.
2. **The provider sites:** 9 fictional sites H1, H2, H3 (Huawei), F1, F2, F3 (Fronius), S1, S2, S3 (SolarEdge) from `demo_data/`. They are imported with `python -m backend import-provider`, and their backend ids are `provider-<sha24>`. **This assignment's equipment scenario uses these 9 sites.** Phase (b) placed them in areas `sector-1` and `ilfov` using fictional coordinates in the `site_placements` table. F1 is declared the business demo site (a small laundry).

**Roles** (`users.role`): `customer`, `dispatcher`, `technician`, `supervisor`. Access always comes from explicit server-side grants (`user_sites`, `user_areas`); importing data never grants anything.
- A supervisor granted all areas acts as the overall manager; one granted a single area is an area manager.
- Customers have `account_type` home or business.
- State-changing requests are POST with an `X-CSRF-Token` (the client handles this).
- Sessions are cookies.
- Inaccessible objects return 404.

**Existing features you will see:**
- **Power Block Offers:** managers publish offers, customers accept them, and an idempotent settlement worker settles them in integer bani with a savings counter.
- **Support requests** with video upload.
- **Rewarded lessons.**
- **Incidents, crews, assignments and revenue** for the compact demo.
- **In-app notifications.**
- **A Leaflet map** with OSM tiles, sector boundaries and site clusters.

**How to build a scratch environment from zero.** Never use `.local/` or port 8000; those belong to the user. Run everything from the repo root with these environment variables set:
- `SOLAR_DATABASE=<scratch>/api.sqlite3`
- `SOLAR_MEDIA_DIR=<scratch>/media`
- `SOLAR_OFFER_WORKER=false` (the in-app worker is off; run passes by hand)

Steps:
1. `.venv/Scripts/python -m backend migrate`
2. Optional, for the compact demo: `.venv/Scripts/python -m backend seed-demo` (writes passwords to `<scratch>/demo-credentials.json`).
3. Provider sites: `.venv/Scripts/python -m backend import-provider --database <path to build/scraper.sqlite or .gz> --sites demo_data/sites.json --frames build/site_frames_15min.csv`. Check `--help` and the README for the exact arguments.
4. Component data:
   - If `build/components/component.sqlite` is missing (it is git-ignored), run `.venv/Scripts/python scraper.py --component all --config config/component_profiles.yaml --input demo_components --out build/components --as-of 2026-07-22T00:00:00+03:00` (about 2 min).
   - Then run `.venv/Scripts/python -m backend import-components --database build/components/component.sqlite`.
5. `.venv/Scripts/python -m backend provision-component-scenario` (creates `laundry-owner`, `h2-resident`, `scenario-supervisor` and `scenario-dispatcher`, with passwords in the scratch credentials file), plus the operations provisioning command that phase (c) adds.
6. `.venv/Scripts/python -m backend scenario start demo --at 2026-07-17T07:30:00+03:00`. Later use `scenario advance --to … [--settle]`. Time only moves forward; to restart, use a new scratch database.
7. `npm --prefix frontend run build`, then `.venv/Scripts/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8016`. Open `http://localhost:8016/consumer` or `/ops` and sign in with a username and the password from the scratch credentials file.

**How to find out where things really stand.** Work was done by agents that may have stopped mid-edit, so check:
1. `git status --short` and `git diff --stat`. Everything since commit `b3976f5` is uncommitted.
2. `docs/handoff/PHASE_A_CONTRACT.md` and `PHASE_B_CONTRACT.md`. If a `PHASE_C_CONTRACT.md` exists, phase (c) finished and that file describes its API.
3. Run the targeted tests in the §1 table for any phase marked in progress. If they fail or are missing, that phase is your first job.
4. `.venv/Scripts/python -m backend --help` lists the CLI commands that exist.
5. `GET /openapi.json` on your scratch server (or `packages/contracts/openapi.json`) lists the endpoints that exist.

## 0. Ground rules (read first)

- **End goal.** The "Definition of done" in `docs/handoff/MASTER_SPEC.md` §16:
  - a reviewer can start the app locally and ingest every included verified format;
  - inspect quality and feasibility handling;
  - log in with scoped roles;
  - see an evidence-based business-load decision;
  - inspect correlated, ranked incidents on the existing map;
  - generate and explicitly apply a feasible crew schedule;
  - observe authorized technician and map updates;
  - advance replay time and repeat without duplicated measurements, assignments or financial records.

  Plus the docs and demo deliverables in §16 items 6–12.
- **Binding documents** (copies are in `docs/handoff/`):
  - `MASTER_SPEC.md`: the product owner's full spec.
  - `EQUIPMENT_REFERENCE_SHEET.md`: a transcribed reference PDF. It is a reference, not proof.
  - `ARCHITECTURE_DECISIONS.md`: binding decisions D1–D7, covering which site has which device, scenario days, placement and guards.
  - `PHASE_A_CONTRACT.md`: component snapshot schema.
  - `PHASE_B_CONTRACT.md`: backend clock, planner, tariff, import and API.
- **Context documents:**
  - `docs/COMPONENT_IMPLEMENTATION_INVENTORY.md`: what existed before; §6 gives file ownership per phase.
  - `docs/COMPONENT_SOURCE_NOTES.md` and `config/component_evidence.yaml`: the feasibility gate. Only fields listed there may be generated or mapped.
- **The data is synthetic.** Never invent native vendor fields, registers, legal claims, savings, accuracy figures or visit-reduction percentages. The "20 % unnecessary visits" figure is a hypothesis, not a result.
- **Do not break existing behaviour.**
  - The compact 60-site demo (`s1-01`…, Sectors 1–6 and Ilfov) and the 9 provider sites (`provider-<sha24>`, H1…S3) are separate populations. Never mix their identities.
  - The original fixtures (`demo_data/**`, `build/scraper.sqlite.gz`, `tests/ground_truth/**`) must keep their exact bytes.
- **Do not touch:**
  - `.local/`: the user's local database and credentials.
  - The app the user runs on `http://127.0.0.1:8000`; never stop it.
  - The user's existing browser tabs.

  For your own checks, use a scratch database outside the repo and another port (8016+), and browse it at `localhost:<port>`.
- **Credit and time discipline (product owner's instruction).**
  - Never re-run a test suite that already passed if you did not change the code it covers.
  - Run targeted tests for what you change.
  - Do one final run of the affected suites at the end.
- **Git.** Do not commit or push unless the user asks. When asked:
  - Commit on `phase2`.
  - Never commit `.local/`, `build/components/` (≈470 MB snapshot, already in `.gitignore`), scratch databases or vendor PDFs.
  - End commit messages with a `Co-Authored-By` line naming your tool.
- **Windows and tooling gotchas:**
  - Python is `.venv/Scripts/python` (3.12). Do not use the system Python 3.10.
  - `python -m scripts.export_contracts` writes CRLF on Windows. Convert `packages/contracts/{openapi.json,index.ts}` back to LF afterwards, then run `python -m scripts.export_contracts --check`.
  - Strict type check of the contract package:

    ```
    cd frontend && npx --yes --package typescript tsc --noEmit --strict --target ES2020 --module ESNext --moduleResolution bundler --lib ES2020,DOM ../packages/contracts/index.ts ../packages/contracts/client.ts
    ```
  - Never use PowerShell `Set-Content`, because it adds a BOM. Edit with your editor tools or Python.
  - Backend tests: each login costs about 5 s (scrypt).
  - Do not run the slow phase-1 suites (`tests/test_architecture.py` is fine) unless you changed `engine/**`, `generate_demo.py` or `scraper.py`. Those suites are `test_semantics`, `test_time`, `test_outcomes` and `test_http_replay`.
  - Lint: `.venv/Scripts/python -m ruff check backend tests/<files you changed>` and `ruff format --check` on the same paths. `engine/**` is excluded from ruff.
  - Frontend: `npm --prefix frontend test` (node:test) and `npm --prefix frontend run build`. The frontend is plain JSX. Only `packages/contracts` is TypeScript.
- **Accessibility and design.**
  - Reuse the existing design language (cards, `.pill`, `.list-row`, `.section-head`, `.eyebrow`, yellow accent cards).
  - Mobile customer view must work at 360–390 px without horizontal scrolling.
  - Show text or icons alongside colour; times in Europe/Bucharest; money via `frontend/src/money.js`.
  - Explicit loading, empty, partial, error and unauthorized states; no mock fallbacks.

## 1. Current status by phase

How to check what really exists: `git status --short`, then the targeted tests listed per phase. Phases (c) and (d1) may have been **interrupted mid-edit** by a usage limit. Treat their files as work in progress until their tests pass.

| Phase | Status when this file was written | Owner files | Verify with |
|---|---|---|---|
| 1. Research | **Done.** 8 of 9 sources verified; B3 Enphase excluded (no accessible schema). M2 Fronius, B1 Victron and B2 SolarEdge are narrowed to verified fields. | `docs/COMPONENT_SOURCE_NOTES.md`, `config/component_evidence.yaml`, `docs/COMPONENT_IMPLEMENTATION_INVENTORY.md` | Read them |
| (a) Data, profiles, generator, engine | **Done.** 45 tests passed. | `generate_components.py`, `config/component_profiles.yaml`, `demo_components/**`, `tests/component_truth/**`, `engine/readers.py`, edits in `engine/*.py`, `scraper.py` (`--component`), `tests/test_components_engine.py`, `tests/test_components_dataset.py`, `docs/COMPONENT_DATA_DICTIONARY.md` | `.venv/Scripts/python -m pytest -q tests/test_components_engine.py tests/test_components_dataset.py tests/test_architecture.py` (~4 min; only if you change those files) |
| (b) Backend clock, tariff bands, planner, component import, bridge, offers metering | **Done.** The final backend run gave 229 passed. | `backend/clock.py`, `tariff.py`, `solar_forecast.py`, `planner.py`, `planner_models.py`, `bridge.py`, `components.py`, `component_models.py`, migrations `007_planner_tariff_clock.sql` and `007_x_components.sql`; edits in `config.py`, `energy.py`, `customer*.py`, `offers.py`, `offers_worker.py`, `provisioning.py`, `seed.py`, `main.py`, `__main__.py`; contracts; `tests/test_tariff.py`, `test_planner.py`, `test_replay_clock.py`, `test_components_backend.py` | Already green; re-run only what you change |
| (c) Incident correlation, ranking, status projection, crew planner | **Done.** Final run: 119 passed across 11 suites; ruff, contract check and tsc are clean; Scene D was run end to end on a real scenario database. The full API, CLI and Scene D case list are in `docs/handoff/PHASE_C_CONTRACT.md`. It also fixed d1 gaps 1–3 from §2a. | `backend/correlation.py`, `ranking.py`, `status.py`, `crew_planner.py`, `dispatch.py`, `planning_models.py`, `status_models.py`, migration 008, `config/dispatch_policy.yaml`, `demo_components/operations_inputs.json`, `docs/DISPATCH_POLICY.md`, tests | `pytest -q tests/test_correlation.py tests/test_ranking.py tests/test_crew_planner.py tests/test_ops_features.py` (already green) |
| (d1) Customer UI | **Done.** `npm test`: 124 passed; build passes; checked in headless Chrome against a scratch server. New files: `frontend/src/planView.js`, `equipmentView.js`, `equipment.jsx` + `.css`, `planner.jsx` + `.css`, and tests `planView.test.js` and `equipmentView.test.js`. Edited: `connected.jsx`, `opsData.js` (customer menu Home, Plan, Offers, History, More), `customer.jsx`, `features.jsx`/`.css` (contract band editor). Open gaps are listed in §2a. | Customer-side `frontend/src/**`, but **not** `demo.jsx`, `domain.js`, `dispatch.js`, `store.js`, `opsPages.jsx`, `ops.jsx`, `ops.css` or `map.jsx` | `npm --prefix frontend test` and `npm --prefix frontend run build` |
| (d2) Operations UI | **Done.** Queue, drawer, map layers, Plan teams, technician agenda. The dispatch bypass is closed: correlated incidents get 409 `episode_workflow_required` on the legacy assign actions. Frontend tests: 135 passed; build passes; headless browser check of Scenes A, B and D. | ops frontend files | already green |
| (e) Demo runner, docs, slides | **Done.** `scripts/demo_scenes.py` runs end to end; actual output in `docs/demo_run_output.txt`. README quick start, `COMPONENT_DEMO.md`, `COMPONENT_SLIDES.md`, `COMPONENT_ARCHITECTURE.md`, `PROBLEMS_SOLVED.md` and `PRESENTATION_BRIEFING.md` are written with the real values. Targeted backend run: 36 passed; ruff and contract check clean. | docs + runner | already green |

If phase (c) or (d1) is incomplete, finish it first, following the brief in §2. Do not start (d2) before (c)'s endpoints exist, because (d2) depends on them.

## 2. Briefs for the phases that may be unfinished

### Phase (c): finish if needed
Implement spec §9.5–9.9 as described in `docs/handoff/MASTER_SPEC.md`, using the files listed above.

1. **Correlation** (Observation → Condition → Incident hypothesis → Operational episode). Each rule is active only when its evidence exists; otherwise it reports "not evaluated". Rules:
   - **Weather-consistent drop:** PV plus measured irradiance on a compatible plane.
   - **S2 persistent underperformance:** against Kipp POA irradiance.
   - **F1 battery restriction:** from the Victron alarm and limit fields (internal-failure alarm = 2 and max discharge 100 → 25 A from 2026-07-18 09:40 local). Routed to the responsible battery service.
   - **H2 sustained PCC phase-voltage anomaly:** Shelly. Never report "overvoltage caused shutdown".
   - **H1+H2 shared collector outage:** 2026-07-19 09:15–11:45 local. One remote troubleshooting episode; missing feeds are not loss of power.
   - **Common upstream episode:** only with an explicitly declared topology relation. The scenario declares none, so demonstrate separate episodes and test the parent path with a fixture.

   Further rules:
   - Mirrored copies are not independent corroboration.
   - Confidence is ordinal: reported / corroborated / suspected / insufficient.
   - Deduplicate episodes. Losing a feed never resolves an episode.
   - Parent and child impact is counted once.
   - Responsibility comes from `demo_components/assets.json`, never from brand or geography.
   - Correlation runs on the analytical clock and only on past data.
   - Never read `tests/component_truth/**` or fault labels; add a guard test.
2. **Ranking** (`config/dispatch_policy.yaml`, a versioned demo policy). One service feeds the queue, detail, map and planner.
   - Bands come first, with safety and deadlines on top; a hazard is never demoted for unknown economics.
   - Within a band, deterministic factors.
   - Outputs: reason codes, factor values, unknowns, policy version, evidence ids, `rank_as_of`.
   - Overrides require a reason, are audited and expire; the original rank is preserved.
3. **Status projection.**
   - Per site: `status_as_of` and revision, with independent dimensions for condition, telemetry, workflow, priority, parent and crew/ETA.
   - Counts distinguish unique sites from unique episodes.
   - Unknown coordinates go to an "unmapped" list.
   - Scope is filtered and redacted server-side.
   - The nine provider sites have no `site_profiles` rows. Their coordinates, segment and kWp are in `site_placements` (phase b). Map, capacity and crew queries need a LEFT JOIN on it.
4. **Crew planner.**
   - A deterministic, bounded insertion heuristic, called a "feasible heuristic proposal".
   - Hard constraints: qualification, scope, shifts and breaks, access windows, travel, locks, dependencies, member-level availability.
   - Infeasible jobs are listed as unassigned with a reason; there are no fabricated ETAs.
   - A feasible manual/FIFO baseline is compared under identical constraints, with honest results.
   - Lifecycle: draft → reviewed → applied/superseded.
   - **Apply:** dispatcher only (supervisor gets 403). It is transactional, uses an optimistic revision check and an idempotency key; a stale proposal returns 409 and must be recomputed. No double booking.
   - **Technicians:** see their own agenda and update progress (en route / on site / done).
   - Synthetic planning inputs live in `demo_components/operations_inputs.json` and are clearly labelled fictional. They never appear in vendor exports.
5. **Provider-scenario operations provisioning.**
   - At least two crews with different qualifications, including a battery-qualified one, plus a remote-triage desk.
   - Technician accounts; the dispatcher (`scenario-dispatcher` exists from phase b); a supervisor without apply rights (`scenario-supervisor`).
   - Explicit and idempotent; never done through import.
6. **APIs, appended to `main.py`:**
   - ranked queue;
   - episode detail with evidence, log, rank explanation and responsibility;
   - status projection, which the map consumes;
   - priority override;
   - plan propose, review and apply;
   - technician agenda and progress;
   - unmapped sites.

   Regenerate contracts, add the `client.ts` methods, and run the `--check` and tsc checks.
7. **Tests:** as listed in spec §14 (Correlation, Ranking, Crew feasibility, Planning/apply, Map). Keep `tests/test_ops_features.py` green.
8. **`docs/DISPATCH_POLICY.md`.**

### Phase (d1): finish if needed
The customer connected app, spec §11.

- **Replay badge:** from `api.clock()`, shown when a scenario is running, with the scenario name and the analytical time in Bucharest.
- **Grid / Battery / Solar evidence cards** on Home, fed by `GET /api/v1/sites/{id}/equipment/summary`.
  - Show the source, value, last update, availability, and capability reason codes in plain language.
  - A "Why?" expander lists the evidence; assumptions are shown separately from measurements.
- **Plan page** in the customer menu (`opsData.js` `ROLE_PAGES.customer`).
  - Tasks list and create/edit.
  - A recommendation card comparing run now with the proposed slot, with estimated costs. Null costs show "unknown" with the reason.
  - Also on the card: deadline, binding constraints, confidence/freshness, forecast issue time, contract version, whether the battery is included or excluded and why.
  - "Why this recommendation?" expander.
  - States: suggestion → accepted → running → completed.
  - Accept sends `{recommendation_revision}` with an Idempotency-Key.
  - Release via review, with a reason.
  - Progress shows measured connection-point energy and coverage, with the note that the meter covers the whole site, not the appliance.
- **"Next task" card** on Home.
- **Contract bands** shown in the contract UI. Fixed contracts have no `bands` key; the effective bands are in `version.bands`.
- **Pure-module tests** in `frontend/tests/`.

## 2a. Known gaps found by phase (d1). Gaps 1–3 were fixed in phase (c); 4–5 are optional in (e).
1. `GET /api/v1/sites/{id}/provider/latest` returns `as_of_utc` from the frozen scrape time (22 Jul 00:00) instead of the replay clock. The customer Home source banner therefore shows the wrong replay time. It should respect the analytical clock and never expose data after it.
2. The accepted planner commitment record does not store which baseline it was compared with ("run now" or the usual time). Add a field, so the card can say what the saving was measured against.
3. On H2, the equipment summary contradicts itself: the irradiance capability says the station is in the panel plane, but the PV performance check says the planes differ. The shared Campbell station is an area resource; its mounting needs one consistent statement.
4. A rejected task form returns only "Request does not match the API contract". Field-level validation messages would help; the frontend currently duplicates the rules.
5. There is no notification for "the recommendation now differs from your accepted plan". It only shows on the card. Add one, deduplicated, only if it is cheap.

## 3. Phase (d2): operations UI (in progress; finish whatever is missing)
Spec §9.8, §11 (operations workspace) and §13 Scene D. You own `frontend/src/opsPages.jsx`, `ops.jsx`, `ops.css`, `map.jsx` and `opsData.js` (ops parts), plus new ops modules and tests. The browser-only demo files are off limits.

- **Revised incident queue and the existing map:** both use the common status projection with the same ids and revisions. Clicking a queue item highlights its site and route; clicking a site selects its queue item.
- **Synchronised filters:** area, priority, family, telemetry health, responsibility and assignment, with counts.
- **Site and episode drawer:**
  - affected devices, correlated evidence, confidence basis, last update, responsibility;
  - rank explanation (dominant criteria), permitted next action, equipment source health.
- **Map layers:**
  - Site markers show condition, priority, freshness and workflow. Missing data is shown as unknown, never green. A safety colour takes precedence but both badges are shown.
  - Crew markers at the last reported location (no live GPS).
  - Proposed routes as dashed, schematic straight lines with visit order, labelled "estimate". Applied routes use a different style.
  - Shared-episode grouping only where a relation is declared.
  - An "unmapped" list.
  - **Offline fallback.** Tiles come from tile.openstreetmap.org and need internet. If tiles fail, keep the markers on a plain background; this already works and must stay working.
- **"Plan teams" panel**, for dispatchers and supervisors:
  - horizon, available crews, ranked eligible jobs, proposed visit order and times, reasons, remote-review items, blocked and unassigned work;
  - comparison against the manual/FIFO baseline (travel minutes, deadline compliance by band, jobs served, optional delay loss);
  - review, permitted lock or override, and an explicit **Apply** (dispatcher only; supervisors see it disabled with a reason);
  - clear messages for stale plans and conflicts (409).
- **Technician view:** own agenda and progress actions only.
- Polling uses the existing cadence; updates arrive without a full reload.
- Laptop width (1280–1440 px) and 390 px both work.
- Pure-module tests for the adapters.

### 3a. How to finish (d2) if it stopped midway
1. Read the existing new modules (`opsQueue.jsx`, `opsMapPanel.jsx`, `opsShared.jsx`, `opsView.js`) and `opsPages.jsx` to see what is wired. Do not rewrite working parts.
2. Check that each item in §3 exists and works:
   - ranked queue with filters and counts;
   - episode drawer with rank explanation, evidence, actions by role;
   - map layers: status badges, unmapped list, crew bases, dashed proposed / solid applied routes;
   - the **Plan teams** panel: propose, review, apply (dispatcher only), baseline comparison, `plan_stale` handling;
   - the **technician agenda** with progress actions;
   - the `planView.js` labels for `poa_sensor_plane_vs_module_plane_unknown` and `sensor_plane_differs_from_module_plane`.
3. The API reference is `docs/handoff/PHASE_C_CONTRACT.md`. Its "Scene D" table gives the expected states at the scenario time `2026-07-19T11:30:00+03:00`:
   - F1 battery: P1, battery crew 12:30–14:00.
   - H2 voltage: P2, **unassigned on purpose**, because no crew is authorised for distributor work.
   - Weather drops: P3, monitoring only.
   - H1+H2 outage: one remote-desk job, 13:00–13:45.
   - S2 underperformance: P2, remote review, then a PV crew visit 13:30–15:30.
   - Baseline verdict: `no_improvement`.
   - Supervisor: 403 on review and apply.
   - Stale plan: a priority override on H2, after which the old plan returns 409 `plan_stale`.
   - At 12:30, `scenario advance --to 2026-07-19T12:30:00+03:00 --correlate`, then `desk-operator` marks the job done: open episodes go from 7 to 6.
4. Accounts for Scene D (created by `provision-component-scenario` and `provision-scenario-operations`; passwords in the scratch credentials file): `scenario-dispatcher` (apply), `scenario-supervisor` (view only), `tech-battery-1`, `tech-battery-2`, `tech-pv-1`, `desk-operator`.

### 3b. Extra deliverable already written: `docs/PROBLEMS_SOLVED.md`
A pitch and Q&A document for the challenge brief. It covers the main problem, the three pains for prosumer and O&M, the constraints, the four "questions worth investigating" and "what success looks like". It currently says the operations interface is being finished. When (d2) is done, update that status line and replace any example figures with values from your final demo run.

## 4. Phase (e): demo runner, docs, slides, final verification (not started)
1. **`scripts/demo_scenes.py`** (or the equivalent). It prints and runs the exact commands for the four scenes from a clean local setup using a separate scenario database. Time only moves forward. The setup sequence (see `PHASE_B_CONTRACT.md` for the exact arguments):
   - `python -m backend migrate`
   - `import-provider` (provider snapshot; it may be `build/scraper.sqlite.gz`, see README)
   - `python generate_components.py --seed 42 --start 2026-07-15 --days 7 --out demo_components --truth-out tests/component_truth --provider-data demo_data` (deterministic; already generated)
   - `python scraper.py --component all --config config/component_profiles.yaml --input demo_components --out build/components --as-of 2026-07-22T00:00:00+03:00` (about 2 min; output is git-ignored, so regenerate it on a fresh clone)
   - `python -m backend import-components --database build/components/component.sqlite`
   - `python -m backend provision-component-scenario`
   - phase (c)'s operations provisioning
   - `python -m backend scenario start <name> --at 2026-07-17T07:30:00+03:00`
   - `scenario advance --to …`

   The scenes:
   - **Scene A, F1 laundry decision on 2026-07-17.** Phase (b) observed: run now 12.16 RON, recommended start 11:00–13:00 at 9.62 RON, an estimated −2.54 RON; progress after the run showed 9.47 kWh imported at the connection point. Use the actual values from your run, not these.
   - **Scene B, 2026-07-18 ~10:00.** Clouds plus the Victron alarm and derate; the battery is excluded and the recommendation moves.
   - **Scene C.**
     - H2 Shelly duplicates, out-of-order records and the EMData counter reset.
     - The F2 mirrored meter is never summed.
     - The Shelly 14:00–15:30 gap leads to an incomplete-coverage waiver in the offer workflow.
     - A repeated import or worker pass leaves the totals unchanged.
   - **Scene D, operations.** The ranked queue and the map; propose, compare with the baseline, apply as `scenario-dispatcher`; the supervisor cannot apply; a stale-proposal rejection; repeated apply makes no duplicates; resolving an episode updates the map, counts and rank while unrelated issues stay visible.
2. **Docs.**
   - Update `README.md`: install, generate, ingest, provision, start, replay commands, and the account list. Passwords live in the credentials file next to the database; never print them in docs.
   - `docs/COMPONENT_DEMO.md`: a five-minute script with actual values and states from your run, plus the pacing from spec §13.
   - A three-slide presentation outline with screenshot suggestions and no invented percentages.
   - One compact architecture diagram (Mermaid).
   - Finalise `docs/COMPONENT_SOURCE_NOTES.md` (feasibility matrix and exclusion list).
   - Make sure `docs/COMPONENT_DATA_DICTIONARY.md` and `docs/DISPATCH_POLICY.md` are consistent with the code.
3. **Acceptance tests** (`tests/test_component_scenes.py`) covering the cross-cutting spec §14 rows that are not yet covered. Keep them targeted.
4. **Final verification.** Run each suite once, only where code changed since its last green run, and report the actual commands and results:
   - backend suites: `test_api`, `test_cli`, `test_provisioning`, `test_customer_features`, `test_ops_features`, `test_provider_integration`, `test_frontend_host`, `test_ingestion`, `test_offers`, `test_offers_math`, `test_geography`, `test_tariff`, `test_planner`, `test_replay_clock`, `test_components_backend`, plus phase (c)'s tests;
   - `tests/test_components_*` and `tests/test_architecture.py` if `engine/` or the generator changed;
   - ruff, the contract check and tsc;
   - frontend test and build.

   Then do a browser smoke check of the four scenes on a scratch server. Never write "all tests passed" unless you ran them.
5. **Final handoff to the user.** Changed files, how to run, checks passed or failed, what remains simulated or unverified, and the essential limitations:
   - Enphase is excluded.
   - Fronius units are inferred.
   - Victron uses the 16-bit power register only.
   - SolarEdge battery state has no labels.
   - Map tiles and the weather API need internet; there is an offline fallback.
   - The legal claims are marked unverified.

## 5. Accounts and identities you will meet
- **Compact demo** (`seed-demo`): `customer`, `other-customer`, `business-customer`, `dispatcher`, `technician`, `technician-s1`…`technician-s5`, `technician-ilfov`, `area-manager`, `supervisor`. Passwords are in the credentials file next to the database (`.local/demo-credentials.json` for the user's database; do not read or print the user's file).
- **Provider component scenario** (`provision-component-scenario`): `laundry-owner` (business, F1), `h2-resident` (home, H2), `scenario-supervisor`, `scenario-dispatcher`, plus the technicians phase (c) adds.
- **Provider site ids:** see the table in `docs/COMPONENT_IMPLEMENTATION_INVENTORY.md` §1. For example, F1 = `provider-e2f35075482123a2267dd143`.
- **Browser-only `/demo/`** has its own fictional accounts, using the public password shown in its login window. Leave it unchanged.

## 6. If something is unclear
Prefer the spec's conservative option: abstain or mark as unknown rather than invent. Write the assumption into the relevant doc, and list it in your final handoff.
