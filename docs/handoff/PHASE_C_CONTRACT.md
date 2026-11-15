# Phase (c) output contract: correlation, ranking, status projection, crew planner

Status: **stable** (published by phase c). All data are SYNTHETIC. Planning inputs are fictional. The policy is a
DEMO policy (`config/dispatch_policy.yaml`). The method is described in `docs/DISPATCH_POLICY.md`.

## 1. Files

| Kind | Files |
|---|---|
| New modules | `backend/correlation.py` (pure rule library + `EvidenceSource` interface + `StaticEvidenceSource`), `backend/ranking.py`, `backend/status.py` (pure projection), `backend/crew_planner.py` (pure heuristic + FIFO baseline), `backend/dispatch.py` (DB adapter `DatabaseEvidenceSource`, correlation runner, queue/detail/projection/map overlay, plans, workflow), `backend/planning_models.py`, `backend/status_models.py` |
| Config / data | `config/dispatch_policy.yaml` (`demo-dispatch-2026.11.15-1`), `demo_components/operations_inputs.json` (synthetic crews/people/shifts/breaks/depots/windows/job templates/travel matrix "approximate demo matrix"; never part of a vendor export) |
| Migration | `backend/migrations/008_correlation_dispatch.sql` |
| Edited | `backend/ops.py` (map overlay, revision bumps, `resolve_incident(detail=, began=)` + episode closure hook, technician scope incl. planned assignments, crew profile on teams), `backend/ops_models.py` (`Battery` family; optional MapSite/OpsMap/Crew/TeamsView fields), `backend/seed.py` (`seed_scenario_operations`), `backend/main.py` (routes appended), `backend/__main__.py` (CLI), `packages/contracts/{openapi.json,index.ts,client.ts}` |
| Phase (d1) gap fixes | `backend/providers.py` (provider latest/history capped at the scenario clock), `backend/planner.py` + `planner_models.py` (commitment `baseline_kind`/`baseline_start`), `backend/components.py` + `component_models.py` (one plane statement `module_plane_match`; `EquipmentAsset.plane_match`) |
| Tests | `tests/test_correlation.py`, `tests/test_ranking.py`, `tests/test_crew_planner.py`, additions to `tests/test_ops_features.py`, plus one targeted test each in `tests/test_provider_integration.py`, `tests/test_planner.py` and `tests/test_components_backend.py` |
| Docs | `docs/DISPATCH_POLICY.md`, this file |

## 2. Migration 008 tables

- **`ops_revisions`** `(id, reason, subject, created_at, created_as_of)`. `MAX(id)` is the single ops revision. Queue, episode detail, map, status and teams all report it.
- **`rule_revisions`** `(rule_id, revision, ruleset_version, rule_hash, definition JSON, first_used_as_of)`.
- **`correlation_runs`** `(run_id, as_of, ruleset_version, source, site_results JSON {site: {evaluated[], not_evaluated[{rule_id, reason_codes}]}}, counts, created_at)`.
- **`episodes`** (PK `incident_id` → `incidents`):
  - identity and rule: `identity`, `sequence`, `rule_id`, `rule_revision`, `state` (active|resolved);
  - assessment: `confidence`, `confidence_basis`, `action`, `responsibility`, `responsibility_basis`, `service_key`, `hypothesis`, `metrics`, `impact`, `reason_codes`;
  - scope and time: `site_ids`, `asset_ids`, `parent_incident_id`, `first_observed_at`/`last_observed_at`, `window_*`, `opened_as_of`/`updated_as_of`/`resolved_as_of`;
  - resolution and review: `resolution_kind` (recovery_rule|authorized_closure), `resolution_detail`, `resolved_by`, `hold_note`, `acknowledged_*`;
  - counters: `repeat_count`, `revision`.
  - A unique partial index allows one active episode per identity.
- **`episode_sites`** `(incident_id, site_id, role primary|affected)`.
- **`episode_evidence`** `(incident_id, evidence_id, kind, source_id, independent_group, mirror_of, observed_from/to, summary, added_revision, added_as_of)`.
- **`episode_links`** `(parent_incident_id, child_incident_id, relation_id, basis, attribution)`.
- **`rank_snapshots`** `(incident_id, ops_revision, context correlation|plan|override, policy_version, band, computed_band, score, digest, explanation JSON, rank_as_of)`.
- **`priority_overrides`** `(override_id, incident_id, band, original_band, reason, created_by, created_at, created_as_of, expires_at, revoked_*)`.
- **Planning inputs (synthetic):**
  - `crew_profiles` (kind field|remote_desk, organisation, authorised_services, qualifications, tools, areas, base_node, location_reported_at, location_basis);
  - `crew_shifts` (per day, breaks JSON);
  - `member_unavailability`;
  - `planning_nodes` (fictional coordinates; site nodes use the backend site id);
  - `travel_times` (minutes, source);
  - `job_templates` (rule → activities);
  - `site_access_windows`;
  - `service_boundaries`;
  - `collector_declarations`;
  - `topology_relations` (empty in the scenario).
- **`crew_plans`** `(plan_id, ops_revision, status draft|reviewed|applied|superseded, created_by/at/as_of, horizon_start/end, scope_digest, input_digest, input_snapshot, travel_source, policy_version, result JSON, reviewed_*, applied_*, apply_idempotency_key, superseded_reason/by)`.
- **`crew_plan_items`** `(plan_id, seq, crew_id, incident_id, job_id, activity, depends_on, depart/arrive/start/finish, travel/service minutes, state proposed|assigned|deferred|cancelled, assignment_id)`.
- **`assignments`** gains `plan_id`, `activity`, `progress` (en_route|on_site|done), `revision`, `eta_arrival`, `travel_minutes`. Every change is recorded in **`assignment_revisions`**.
- **`planner_commitments`** gains `baseline_kind`, `baseline_start` (d1 gap).

## 3. Endpoints

All require a session. Writes need `X-CSRF-Token`. Customers get 403 (`operations_required`). Inaccessible ids return 404.

| Method / path | Who | Request | Response type | client.ts |
|---|---|---|---|---|
| GET `/api/v1/ops/queue?status=open\|all` | ops roles | – | `QueueView {revision, rank_as_of, policy_version, policy_label, items: QueueItem[{incident, episode: EpisodeSummary\|null, workflow, rank: RankExplanation}], remote_review_count, field_count, monitoring_count}` | `opsQueue()` |
| GET `/api/v1/ops/episodes/{incident_id}` | ops roles | – | `EpisodeDetail {revision, incident, episode, hypothesis, metrics, impact, reason_codes, rule, evidence[], rank, rank_history[], overrides[], assignment_history[], workflow, next_actions[], customer_guidance}` | `opsEpisode()` |
| POST `…/episodes/{id}/acknowledge` | ops roles | `{}` | `EpisodeDetail` | `acknowledgeEpisode()` |
| POST `…/episodes/{id}/close` | dispatcher/supervisor, or a technician of the assigned crew | `CloseRequest {reason_code: repaired\|remote_resolved\|no_fault_found_documented\|external_handoff\|duplicate, note}` | `EpisodeDetail` | `closeEpisode()` |
| POST `…/episodes/{id}/priority-override` | dispatcher | `OverrideRequest {band, reason 5..300, expires_at (aware, ≤ 7 d analytical)}` | `EpisodeDetail` (`rank.band` = override, `rank.computed_band` preserved) | `overridePriority()` |
| POST `…/episodes/{id}/priority-override/revoke` | dispatcher | `{}` | `EpisodeDetail` | `revokePriorityOverride()` |
| GET `/api/v1/ops/status` | ops roles | – | `StatusProjection {revision, status_as_of, sites: SiteStatus[], unmapped: SiteStatus[], counts: StatusCounts, note}` | `opsStatus()` |
| GET `/api/v1/ops/unmapped` | ops roles | – | `UnmappedSites {revision, status_as_of, count, sites}` | `opsUnmapped()` |
| GET `/api/v1/ops/map` (extended) | ops roles | – | `OpsMap` (+ `revision, status_as_of, status_sites, unmapped, counts, crews: CrewMarker[], routes: RouteLine[]`). `MapSite` gains `condition, telemetry_state, workflow, highest_priority, episode_ids`. | `opsMap()` |
| GET `/api/v1/ops/teams` (extended) | ops roles | – | `TeamsView` (+ `revision`). `Crew` gains `profile: CrewProfileView` (kind, organisation, qualifications, tools, areas, base position, shift, label). | `opsTeams()` |
| POST `/api/v1/ops/plans` | dispatcher, supervisor | `ProposeRequest {horizon_hours 1..24 (default 12)}` (body optional) | 201 `CrewPlanView` | `proposeCrewPlan()` |
| GET `/api/v1/ops/plans/latest`, `/plans/{plan_id}` | dispatcher, supervisor (others 403) | – | `CrewPlanView` | `latestCrewPlan()`, `crewPlan()` |
| POST `/plans/{plan_id}/review` | dispatcher | `{}` | `CrewPlanView` (status reviewed) | `reviewCrewPlan()` |
| POST `/plans/{plan_id}/apply` | dispatcher (supervisor → 403 `dispatch_capability_required`) | `ApplyRequest {expected_input_digest}` + optional `Idempotency-Key` | `CrewPlanView` (status applied, `applied_assignment_ids`) | `applyCrewPlan()` |
| GET `/api/v1/ops/agenda` | technician (own crews); dispatch/supervisor (visible crews) | – | `AgendaView {as_of, crews, items: AgendaItem[], deferred[], eta_label}` | `opsAgenda()` |
| POST `/api/v1/ops/assignments/{id}/progress` | technician of that crew | `ProgressRequest {state en_route\|on_site\|done, expected_revision, outcome? resolved\|field_visit_needed\|further_evidence_needed, note (required for done)}` | `AgendaView` | `updateAssignmentProgress()` |

`CrewPlanView` fields:
- identity and timing: `plan_id`, `status`, `ops_revision`, `current_revision`, `created_at`, `created_as_of`, `horizon_start`, `horizon_end`;
- method: `label` ("feasible heuristic proposal …"), `method`, `travel_source`, `policy_version`, `input_digest`, `input_completeness`;
- plan content: `visits`, `remote_items` (both `PlanVisit`: crew_id/name, job_id, incident_id, site_id, title, activity, sequence, band, rank_position, depart_at/arrive_at/start_at/finish_at, travel_minutes, service_minutes, deadline_at, deadline_met, constraints_checked, reason), `unassigned` (`PlanUnassigned` with `reasons[]`), `urgent_exceptions`, `monitoring`;
- comparison: `baseline {visits, remote_items, unassigned}`, `comparison {baseline_definition, heuristic, baseline, findings[], verdict}`;
- approval and lifecycle: `approval {created_by, reviewed_by, reviewed_at, applied_by, applied_at, applied_as_of}`, `superseded_reason`, `superseded_by`, `redacted_items`, `applied_assignment_ids`.

Error codes for the UI:
- `plan_stale` (409). A new draft was computed; reload `latestCrewPlan()`, review and apply again.
- `plan_already_applied`, `plan_superseded`, `plan_not_reviewed`, `plan_changed` (digest mismatch), `crew_double_booked` (all 409).
- `assignment_changed`, `progress_not_forward`, `assignment_closed` (409); `note_required` (422).
- `invalid_expiry` (422).

## 4. CLI

These run against the scenario DB (set `SOLAR_DATABASE`). Phase b's steps come first:

```
python -m backend import-provider --database build/scraper.sqlite
python -m backend import-components --database build/components/component.sqlite
python -m backend provision-component-scenario
```

Then:

```
python -m backend provision-scenario-operations [--inputs demo_components/operations_inputs.json --sites demo_data/sites.json --assets demo_components/assets.json]
python -m backend scenario start components-2026-07 --at 2026-07-19T11:30:00+03:00
python -m backend correlate                     # run the rules at the analytical time (idempotent)
python -m backend scenario advance --to ... --correlate [--settle]
```

- `provision-scenario-operations` is idempotent. It upserts the input tables, never grants dispatch, and is never run by an import.
- It creates the technicians `tech-battery-1`, `tech-battery-2`, `tech-pv-1` and `desk-operator` (password `SOLAR_DEMO_PASSWORD`, else random, stored in `<db dir>/demo-credentials.json`).
- It creates the crews `scn-battery-service` (battery qualified, depot Aviatiei, 08:00-16:00, break 12:00-12:30), `scn-pv-om` (PV string inspection, depot Otopeni, 09:00-17:00, break 13:00-13:30; `tech-battery-1` is a shared member) and `scn-remote-desk` (remote triage desk, not a field crew).
- The dispatch manager is `scenario-dispatcher` (dispatcher). The supervisor without apply rights is `scenario-supervisor`. Both have sector-1 and ilfov grants from phase b.

## 5. Scene D (verified on the real snapshot)

The run starts the scenario at **2026-07-19 11:30 local** (08:30Z) and calls `correlate` there. Correlating earlier, for example at 07-18 23:00, is also valid. In that case the F1 episode opens at night, its P1 4-hour window is overdue by the morning, and the plan lists it as an urgent exception `response_deadline_already_overdue`.

| # | Case | Site (backend id) | Episode after correlate | Plan (propose → review → apply) |
|---|---|---|---|---|
| 1 | F1 battery BMS alarm + derating | F1 `provider-e2f35075482123a2267dd143` | P1, reported, field_visit, responsibility customer_installation_service via battery_service_partner; flexibility removed | Battery Service Crew; arrive ~11:40, start 12:30 (after the 12:00-12:30 break) → 14:00 local; deadline met; map workflow assigned → en_route after technician progress |
| 2 | H2 PCC voltage (Shelly mean > 253 V from 11:15) | H2 `provider-4d119fc90c8c2cf7b55b314c` | P2, corroborated (PCC meter + inverter voltage), external_review, distributor_network_review; no shutdown claim | **Blocked/unassigned with an honest reason**: `crew_not_authorised_for_responsible_service` (distributor review is proposed, never auto-sent) |
| 3 | Weather-consistent drop (07-18 overcast) | F1, S2, H1 `provider-d97b13196637185888be23c1` | 3 × P3 monitor (PR normal, POA down); H2/H3 not evaluated (station plane differs); F2/F3/S1/S3 not evaluated (no POA) | Listed under `monitoring`, never sent to the field |
| 4 | H1+H2 shared collector outage 09:15-11:45 | H1 + H2 (ONE episode) | P2, reported, remote_troubleshooting, monitoring_provider; "missing feeds ≠ loss of supply"; telemetry `access_error` on both sites | Remote desk 13:00-13:45 local (remote item, no travel) |
| 5 | S2 persistent underperformance (PR ≈ 0.40 vs baseline 0.81) | S2 `provider-5f758c0e29543b7dcf57a7e6` | P2, corroborated (inverter + POA sensor), expected loss ≈ 26 kWh/day, value range for the site customer | Remote review on the desk 11:30-12:00 → deferred field visit by PV O&M Crew 13:30-15:30 local (created when the desk marks `done` with `field_visit_needed`) |

Totals: 7 unique episodes on 4 affected sites. S3 shows telemetry `access_error`/`partial` (storageData 403) with no episode.

The FIFO baseline gives the same result, verdict **`no_improvement`**. The comparison reports this honestly.

**Supervisor.** `scenario-supervisor` can propose and view plans (200) but gets 403 on review and apply.

**Stale plan.**
1. Propose and review a second plan.
2. Override the H2 band to P1.
3. Apply the old plan → 409 `plan_stale`. A new draft is computed and the old plan is marked `superseded`.

A repeat apply with the same Idempotency-Key returns the same assignments.

**Resolution.** Advance the clock to 12:30 local and run `correlate`:
- The monitoring-path condition clears by its recovery rule. It is assigned, so it is held as "awaiting crew closure".
- `desk-operator` then posts progress `done` with outcome `resolved` → `authorized_closure`.
- Counts update: 6 open episodes. H1 workflow moves to `monitoring` (its weather episode remains) and H1/H2 telemetry returns to `fresh`.

What stays visible afterwards:
- the F1 alarm (en_route);
- the H2 voltage review;
- S2 (field visit assigned to `tech-pv-1`);
- the S3 stale/partial battery feed.

The weather episodes recover at the next complete normal day: correlate on or after 2026-07-20 00:00 local.

## 6. Notes for phase (d2) ops UI

- **One source of truth.** Use `opsQueue` for the ranked list, `opsEpisode` for the drawer and `opsMap().status_sites/unmapped/counts/crews/routes` for the map. They share `revision` and `rank_as_of`. Reconcile on a revision change rather than showing mixed states. Existing polling (5 s) is fine.
- **Badges.** Show both `attention` (critical/high/elevated/monitor/data_gap/unknown/none) and telemetry. Missing data is not green. `condition_note` must be shown for `no_active_issue_under_evaluated_rules`.
- **Unmapped sites.** `position` null means the site goes into an unmapped list. All coordinates are labelled fictional. Route lines are schematic (`RouteLine.label`). Styling: `state: proposed` dashed, `applied` solid. Crew markers are depots ("last reported base, not live GPS"); the remote desk has no position.
- **Rank explanation.** Show `band_label`, `dominant`, the `factors` table (value / normalized / weight / contribution / basis), `unknowns` and `policy_version` ("demo policy"). Show `economics.value_per_day.stakeholder`, and show `repair_estimate.source` as a manual demo catalog. Show `computed_band` next to any override.
- **Plan panel.**
  - Show `visits` (crew, order, depart/arrive/start/finish, travel/service, deadline_met, reason, constraints_checked), `remote_items`, `unassigned` with reasons, `urgent_exceptions` and `monitoring`.
  - Show the comparison `findings` and `verdict`, and the `label` "feasible heuristic proposal".
  - Apply needs `input_digest` plus an Idempotency-Key per click.
  - On 409 `plan_stale`, reload `latestCrewPlan()`.
  - Supervisors: hide or disable review/apply (the backend returns 403 anyway).
- **Technician.** `opsAgenda` plus `updateAssignmentProgress` with `expected_revision` = `item.revision`. A note is required for `done`. Deferred items are listed in `deferred`.
- **New reason codes** (d1's `planView.js` labels may lack them):
  - irradiance capability: `sensor_plane_differs_from_module_plane` (already labelled), `poa_sensor_plane_vs_module_plane_unknown`;
  - `EquipmentAsset.plane_match` (module_plane | differs_from_module_plane | unknown) is the single mounting statement to display.
- **Customer copy.** Customers never see crews or routes. `EpisodeDetail.customer_guidance` is the approved customer wording.

## 7. Phase (d1) gap fixes

1. **Provider data at the scenario clock.** `GET /sites/{id}/provider/latest` returns `site.as_of_utc` = min(scrape as-of, scenario clock) and only frames with `frame_end` ≤ clock. Source health is re-judged at the clock (`notes` say so). Provider frame and observation history is capped at the clock.
2. **Commitment baseline.** `Commitment.baseline_kind` ("usual_time" | "run_now") and `baseline_start` are stored on acceptance and returned with the task.
3. **One plane statement.** `components.module_plane_match()` is the single check. On H2 the irradiance capability now reports `sensor_plane_differs_from_module_plane`, consistent with the PV performance review. F1 keeps `poa_irradiance_on_registered_plane`.

## 8. Verification

Results (final run 2026-11-15): 119 passed across the 11 suites below; ruff check + format clean; export_contracts --check OK; strict tsc OK. Commands:

```
.venv/Scripts/python -m pytest -q tests/test_correlation.py tests/test_ranking.py tests/test_crew_planner.py tests/test_ops_features.py tests/test_components_backend.py tests/test_provider_integration.py tests/test_planner.py tests/test_customer_features.py tests/test_api.py tests/test_cli.py tests/test_replay_clock.py
.venv/Scripts/ruff check backend scripts tests ; .venv/Scripts/ruff format --check backend scripts tests
.venv/Scripts/python -m scripts.export_contracts --check
cd frontend && npx --yes --package typescript tsc --noEmit --strict --target ES2020 --module ESNext --moduleResolution bundler --lib ES2020,DOM ../packages/contracts/index.ts ../packages/contracts/client.ts
```
