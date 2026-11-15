# Dispatch policy: correlation, ranking, status and crew planning (demo)

Everything here is a **demonstration policy** on **synthetic** data. The thresholds, weights,
crews, shifts, prices and travel times are illustrative. They are not manufacturer limits,
grid-code settings, contractual service levels, a validated model or a learned model.
A rule that passes its injected scenario is a functional test. It is not evidence of field
diagnostic accuracy.

Source files:
- `config/dispatch_policy.yaml` (versioned policy, `policy_version`)
- `backend/correlation.py` (rule library, `RULESET_VERSION`)
- `backend/ranking.py`
- `backend/status.py`
- `backend/crew_planner.py`
- `backend/dispatch.py` (persistence and API)
- `demo_components/operations_inputs.json` (synthetic planning inputs)

## 1. From observation to work order

| Concept | Where it lives |
|---|---|
| Observation | Component snapshot frames, provider frames and collector delivery events. Every row is read only up to the analytical clock. |
| Condition | A rule result: `matched`, `clear` (an explicit recovery rule is satisfied), `indeterminate`, or `not_evaluated` with reason codes. |
| Hypothesis | The interpretation, its uncertainty, alternative explanations and "what it cannot prove". |
| Episode / work order | One `incidents` row plus one `episodes` row. This is what gets ranked, planned, assigned and tracked. |

Each rule declares:
- required metrics and capability gates;
- a compatible boundary or plane;
- aligned 15-minute frames;
- coverage requirements;
- persistence and hysteresis;
- thresholds;
- explanation text.

When a rule's evidence is missing it returns `not_evaluated` and never invents corroboration.

| Rule (revision 1) | Fires when | Action / band | Cannot prove |
|---|---|---|---|
| `weather_consistent_drop` | The last complete local day has PV down at least 30 % and POA down at least 25 % against the median of up to 5 earlier days, while PR stays at least 0.85 × baseline. Requires a POA sensor in the module plane (±5° tilt, ±10° azimuth). | monitor / P3 | That every equipment issue is ruled out |
| `persistent_underperformance` | At least 8 consecutive valid daylight frames (POA ≥ 200 W/m²) have PR below 0.75 × the median daily PR of earlier days. It clears after 8 frames at or above 0.85 × baseline. | remote review, then field visit / P2 | Which panel or string failed |
| `battery_operational_restriction` | A documented BMS alarm is non-zero, or a limit sits below its declared nominal value, in 2 consecutive frames. It clears after 4 clean frames. | field visit by the battery service / P1; battery flexibility removed | Thermal runaway, failed cells, DSO ownership |
| `pcc_voltage_sustained` | A 15-minute phase mean at a declared PCC meter exceeds 253 V. It clears after 2 frames with every phase max at or below 253 V. | external (distributor/network) review / P2 | Transient compliance, fault location, or that the voltage caused a shutdown |
| `shared_monitoring_path` | At least 2 sites behind one declared collector each have at least 3 failed attempts, overlapping in time. It clears after 2 successful frames per site after the last failure. | one remote troubleshooting episode / P2 | Loss of electricity |
| `common_upstream` | At least 2 sites on an **explicitly supplied** topology relation have overlapping compatible child anomalies. With no relation supplied it is `not_evaluated` (the demo scenario supplies none). | external review / P2; children keep their own evidence and loss | Topology from proximity or area membership |

Confidence is ordinal, not a probability:

- **reported**: the device or collector reports the condition itself.
- **corroborated**: at least 2 independent instruments agree. Mirrors (`mirror_of`) count once.
- **suspected**: a single independent instrument.
- **insufficient**: no episode is opened.

Episode lifecycle and evidence handling:

- **Deduplication.** Each identity (rule + asset/collector/site) has at most one active episode, enforced by a unique index. Repeated firings append only new evidence and increment the revision.
- **Resolution.** An episode resolves only in two ways:
  - an explicit recovery rule (`clear`, provenance `recovery_rule`). While a crew is assigned it is held as "awaiting crew closure" instead.
  - an authorized documented closure (`authorized_closure`: dispatcher, supervisor, assigned crew, or technician progress `done`).
- **Missing data.** `indeterminate` or `not_evaluated` results put the episode on hold, with a log note. A lost feed never resolves anything.
- **Parents and children.** Closing a parent never closes its children. A new firing after a closure opens a new episode with `repeat_count` + 1.
- **Responsibility.** The categories are customer installation service, distributor/network review, monitoring provider, and unknown. They come from the service-boundary registry:
  - `service_boundaries`, provisioned from `operations_inputs.json`;
  - the asset `responsible_service` in `demo_components/assets.json`.

  Responsibility is never derived from brand or geography. It is proposed only; nothing is sent externally.

## 2. Ranking (one service for queue, drawer, map and planner)

Bands come first.

| Band | Meaning | Response window | Mandatory |
|---|---|---|---|
| P0 | Safety or emergency | 60 min | yes |
| P1 | Urgent: reported fault with lost function | 240 min | yes |
| P2 | Service impact or review | 1440 min | no |
| P3 | Monitoring | none | no |

Rules for bands:
- An active P0 stays urgent with incomplete evidence (`urgent_review_incomplete_evidence`).
- Unknown economics never move a job across bands. The factor contributes 0 and is listed in `unknowns`.

Within a band, the score is the sum of normalized factor values (each 0..1) times demo weights:

| Factor | Weight | Basis |
|---|---|---|
| `deadline_pressure` | 0.30 | Elapsed share of the response window. 1 means due or overdue. |
| `evidenced_impact` | 0.20 | Affected installations (cap 5) and lost function. |
| `recoverable_impact` | 0.15 | Expected recoverable kWh/day (cap 30). Unknown counts as 0. |
| `confidence_persistence` | 0.15 | Ordinal score (reported 1, corroborated 0.8, suspected 0.5, insufficient 0.3) and persistence (cap 4 h). |
| `age` | 0.08 | Analytical age (cap 24 h). |
| `repeat_dependency` | 0.05 | Repeats (cap 3), child of a shared parent. |
| `commitments` | 0.04 | An active assignment already exists. |
| `remote_resolvable` | 0.03 | Remote work scores 1; field work scores 0.5. |

The sort order is `(band, -score, created_at, incident_id)`, which is deterministic.

Each output carries:
- `band`, `computed_band`, `score`;
- `factors` (value, normalized, weight, contribution, basis);
- `unknowns`, `reason_codes`;
- `dominant` (`priority_band` plus the top 2 factors);
- `policy_version`, `evidence_ids`, `rank_as_of` (the analytical clock floored to 5 minutes, so every view in one slot gets the same rank);
- `deadline_at`, `overdue_minutes`;
- `economics`, `override`.

**Economics** never mixes stakeholders. Unknown values are null with a reason.
- **Expected lost energy per day.** Only from a valid baseline: the underperformance rule's median baseline day × (1 − PR_obs/PR_base). Battery, voltage and monitoring episodes report unknown with a reason. Weather drops are not recoverable.
- **Value per day.** Stakeholder "site customer". The range runs from the export value to the avoided import price of the saved contract, or the default demo tariff. It is never "PPC revenue loss".
- **Repair estimate.** From the manual demo catalog in `job_templates` (currency, range, source, as-of), or unknown.
- **Parent episodes.** Physical loss stays on the children. The parent reports their sum once and is never added to the totals.

**Overrides.** A dispatcher may override with a reason and an expiry of at most 7 days on the analytical clock. Each override is audited and logged and produces a rank snapshot. The computed band is preserved in `computed_band`. Overrides can be revoked.

## 3. Site-status projection

Each site has independent dimensions:

- **condition**: `observed_active`, `suspected`, `no_active_issue_under_evaluated_rules` (labelled "does not certify a healthy installation"), or `not_evaluated`.
- **telemetry**: `fresh`, `partial`, `stale`, `missing` or `access_error`. Access errors are collector failures in the last 30 min. Telemetry also carries coverage and unsupported capabilities.
- **workflow**: `needs_review`, `monitoring`, `remote_triage`, `field_action_needed`, `proposed`, `assigned`, `en_route`, `on_site`, `resolved` or `none`.
- **priority and context**: highest priority, parent episodes, affected assets, evaluated and not-evaluated rules, and crew/ETA for authorized roles.

Projection rules:
- **Counts** separate `affected_sites` from `unique_episodes`.
- **Unknown coordinates.** Sites without coordinates go into the `unmapped` list.
- **Scope.** Sites, episodes, routes and crews are filtered server-side. A shared parent never reveals other customers' sites.
- **Revision.** The projection carries the same `revision` (`ops_revisions`) as the queue, the drawer and teams.

## 4. Crew planner: a feasible heuristic proposal

The proposal is not a guaranteed optimum. It runs in these steps:

1. Filter each job by:
   - responsible service vs the crew's `authorised_services`;
   - area permission, qualifications, tools and parts readiness;
   - crew size, and member availability across crews;
   - a known location, service duration and access window, otherwise the job is unplannable with a reason (no zero durations, no fake ETAs);
   - a remote desk for remote activities.

   Monitoring-only episodes and children of active parents are listed, not planned.
2. Reserve locked or started assignments and break blocks.
3. Order jobs by band, then mandatory deadlines, then deadline, then rank position. Dependencies come first (S2's remote review precedes its field visit).
4. Evaluate every insertion position in every eligible crew route. After each insertion, re-simulate the complete affected routes: travel, breaks, access windows, shift end (no overtime), dependencies, locked commitments and member-level occupancy.
5. Choose by lexicographic goals:
   1. hard constraints;
   2. the timely count of placed higher bands never drops, and P0/P1 take the earliest start;
   3. expected delay loss;
   4. added travel, then workload, then crew id and position.
6. Run a bounded local improvement: relocate P2/P3 jobs only when total travel strictly falls and no band's timely count drops.

Edge cases:
- **Already-overdue mandatory deadline.** The job is scheduled as early as feasible and listed as an urgent exception.
- **P0.** Always listed as `emergency_escalation_required`.
- **Infeasible P1.** Listed as `urgent_job_unserved`.

**Baseline.** A feasible FIFO run under identical hard constraints:
- arrival order (dependencies first);
- the first eligible crew by name;
- append only, with no insertion search and no improvement.

The comparison reports jobs served, timely jobs per band, travel minutes and delay loss. The verdict is `heuristic_improves`, `mixed` or `no_improvement`, reported honestly. In the Scene D data both runs give the same result, so the verdict is `no_improvement`.

**Lifecycle.** `draft` → `reviewed` → `applied` or `superseded`. The stored plan includes:
- the input snapshot (member ids hashed), the input digest and the scope digest;
- the horizon and travel source;
- constraints, visits with ETAs, remote items, unassigned reasons and exceptions;
- the baseline comparison and approval state.

**Apply** takes the dispatch capability (the `dispatcher` role). Supervisors can propose and view, but get 403 on review and apply. Apply checks, in order:
- `BEGIN IMMEDIATE`, then that the plan is reviewed and the expected digest matches;
- the plan is re-derived at its own planning time. If incidents, crew availability, locks, assignments or scope changed, or the clock moved more than 30 min, the result is 409 `plan_stale` and a new draft is stored.

On success:
- The first activity per incident is assigned. Field jobs become a `dispatch` / `assigned` assignment; remote jobs become `meeting` / `meeting_scheduled` with `activity` set.
- Later activities are `deferred` and created when the earlier one is done with `field_visit_needed`.
- An `Idempotency-Key` repeat returns the applied plan. A different key gets 409 `plan_already_applied`.
- Other drafts are superseded, so concurrent proposals cannot double-book a crew. The unique active-assignment index is a further guard.
- Assignment revisions and audit entries record counts only.

**Technician progress** moves forward only: `en_route`, `on_site`, then `done` (a note is required).
- `done` + `resolved` is a technician closure.
- `field_visit_needed` creates the deferred field assignment.
- `further_evidence_needed` reopens the incident to `new`.

**Travel.** "Approximate demo matrix": straight line × 1.4 / 30 km/h + 5 min, rounded up to 5 min. It is not road routing. Map lines are schematic.

## 5. Connected review and replay

The connected **Incidents** page loads queue and map only at a matching operations revision. Six filters
(area, priority, family, telemetry, responsibility and assignment) control the visible queue, site/list
layers and counts. Selecting a queue row or site preserves the underlying episode identity. The drawer
shows evidence independence, confidence basis, responsibility, rank factors, unknowns and source health.
The existing five-second poll delivers changes; a mixed revision retains the last consistent snapshot
and retries rather than presenting conflicting states together.

**Teams → Plan teams** shows a proposed horizon, crew qualifications/shifts, visits and remote work,
unassigned reasons and the feasible baseline. Review and apply are dispatcher-only; supervisory users
receive disabled controls with an explanation. Started/existing work is reserved by backend constraints;
this panel does not provide arbitrary drag-and-drop rescheduling. Priority overrides are available in the
episode drawer, with reason and expiry.

Correlated episodes use the reviewed crew-plan/progress workflow. Legacy manual assignment and closure
shortcuts cannot bypass it. Compact-demo incidents without an episode keep their original workflow.
The **Agenda** page gives technicians only their permitted crews' work, with forward progress and an
outcome note on completion. Customer summaries never include crew routes.

Reproduce the scenario with [the staged runner](./COMPONENT_DEMO.md). Start correlation at 19 July 11:30
for the documented Scene D deadline comparison; opening an urgent episode earlier starts its response
window earlier. The scenario declares no common feeder topology, so the collector grouping must not be
presented as an upstream network diagnosis. OSM tile failures leave the map markers/boundaries/list on a
plain background; travel and routes remain approximate demo estimates.
