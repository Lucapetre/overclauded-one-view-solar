# Five-minute equipment and operations demo

This is a local **synthetic replay**, not a hardware trial. All times below are Europe/Bucharest in July 2026. The replay has nine provider sites; it does not use the compact demo's 60 sites or the browser-only `/demo/` application. Every value marked "recorded" comes from [`demo_run_output.txt`](./demo_run_output.txt), the output of `scripts/demo_scenes.py` on a clean scratch workspace (recorded 15 November 2026, scenario `component-four-scenes-v1`, fixtures seed 42). Costs are labelled **estimated** and use a fictional contract.

## Prepare and reproduce

Follow the [component demo quick start](../README.md#run-the-component-demo). Install dependencies and build the frontend before disconnecting from the internet. Keep the scenario database outside the repo and serve the built app on port 8016 or above. Use a drive with at least 2 GB free for the copied snapshots. Never use the user's `.local/` or port 8000.

The deterministic runner supports checkpoints (`$demo` is a new, empty directory outside the repository):

```powershell
$demo = 'D:\one-view-demos\rehearsal-1'
.\.venv\Scripts\python.exe -m scripts.demo_scenes --workspace $demo setup
.\.venv\Scripts\python.exe -m scripts.demo_scenes --workspace $demo A
.\.venv\Scripts\python.exe -m scripts.demo_scenes --workspace $demo B
.\.venv\Scripts\python.exe -m scripts.demo_scenes --workspace $demo C
.\.venv\Scripts\python.exe -m scripts.demo_scenes --workspace $demo D
```

Run each stage in order, pausing to inspect its UI and report before continuing. `setup` stops at 17 July 07:30; A accepts the batch and stops after measured progress at 14:00; B stops at 18 July 10:00; C checks the earlier gap's settlement and repeats the import and worker; D exercises operations and closes the monitoring episode at 19 July 12:30. The runner's `demo-report.json` stores the actual responses and checks, with no passwords. `all` runs the same sequence without presentation pauses. A repeat is not a rewind: restart from a new empty external directory when rehearsing the complete story.

Use the local passwords in `<demo>\demo-credentials.json` (never on slides or screenshots). Customer tabs use `laundry-owner` and `h2-resident`; operations tabs use `scenario-dispatcher`, `scenario-supervisor`, `tech-battery-1`, `tech-pv-1` or `desk-operator`. A separate browser profile or private context per role avoids cookie-session switching. The runner uses its own API sessions.

For the automated rehearsal, inspect the suggested plan after `setup`, then let A accept it and advance. Accepting manually under a different idempotency key can conflict with the runner's acceptance. For a live UI walkthrough, use a separate manual setup with CLI advances and the UI controls below instead of also running checkpoint mutations; do not mix two controllers on one rehearsal database. The runner is the reproducibility and acceptance path; the live pitch can use prepared screenshots for slow transitions.

## Pacing and presenter handoffs

Spec pacing: 30 s sources and feasibility, 60 s customer decision, 45 s changing evidence, 30 s data-quality trust, 105 s ranking, map and team plan, 30 s limits and next validation (300 s in total).

| Pitch time | Length | Presenter | Screen and line |
| --- | --- | --- | --- |
| 0:00–0:30 | 30 s | 1 | Sources and feasibility: eight supported component paths, Enphase excluded (slide 1) |
| 0:30–1:30 | 60 s | 2 | Scene A: cost comparison, evidence, acceptance and measured progress |
| 1:30–2:15 | 45 s | 3 | Scene B: battery alarm changes advice, accepted commitment stays intact |
| 2:15–2:45 | 30 s | 3 | Scene C: quality, meter-gap waiver, repeat leaves totals unchanged |
| 2:45–4:30 | 105 s | 4 | Scene D: queue and map, crew proposal, honest FIFO comparison, apply and closure |
| 4:30–5:00 | 30 s | 1 | Limits and next PPC validation (slide 3) |

## 0:00–0:30: establish the evidence boundary

Show three native shapes briefly, then return to the normalized cards:

- `demo_components/meters/F1_schneider_iem3255_registers.ndjson`: raw 16-bit register words in our collector's JSON envelope, including directional energy counters.
- `demo_components/batteries/F1_victron_gx_battery_registers.ndjson`: another register map and sign/scale convention; only verified battery-service fields are selected.
- `demo_components/weather/WX_SECTOR1_CS01_OneMin.dat`: configured Campbell TOA5 four-row header with units and processing descriptors. This is the shared H1/H2/H3 area station. **F1's Solar card uses its own IMT POA sensor, not that station.**

Say: "The values are simulated, but the readable fields and formats were checked. One configuration-driven engine preserves units, boundaries, time, quality and source. We deliver three meter paths, two battery paths and three weather paths. We excluded Enphase because we could not establish an accessible schema."

## 0:30–1:30: Scene A, the laundry owner's decision

At **17 July 07:30**, sign in as `laundry-owner`, site F1 (`provider-e2f35075482123a2267dd143`). Show the replay badge, the Grid / Battery / Solar cards and **Plan**. The task is a non-interruptible **4 kW × 2 h = 8 kWh** batch with an 08:00–20:00 window and an import limit. Expand **Why this recommendation?** to show the contract bands, forecast issue time (07:30), input freshness, battery reserve and limits, and export opportunity cost.

Recorded comparison (estimated, incremental site cost under the fictional contract):

| | Start | Estimated cost |
| --- | --- | --- |
| Usual time (baseline) | 08:00 | **12.16 RON** |
| Recommended | **11:00–13:00** | **9.62 RON** (9.618) |
| Difference | | **−2.54 RON** (−2.542) for this one batch |

Battery-assisted planning is included in this decision (`battery_assisted_planning_available`; recorded inputs: SoC 20 % when the forecast was issued, reserve 20 %, 3 kW charge and discharge limits, 95 % efficiencies). The battery is not priced as a free source. This is incremental site-cost modelling under a fictional contract, not a bill or a monthly savings promise.

Accept explicitly (a repeat with the same Idempotency-Key returns the same commitment). For a manual walkthrough advance to 14:00:

```powershell
.\.venv\Scripts\python.exe -m backend scenario advance --to 2026-07-17T14:00:00+03:00
```

Recorded progress: at 12:00 the task is `running`; at 14:00 it is `completed` with **9.467 kWh** measured at the connection point, import coverage **1.0**. The whole-site measured cost over the window was **10.60 RON** against the plan's whole-site estimate of **7.89 RON** (both priced from the same contract bands).

Say: "This meter measures the whole laundry site, not the individual appliance. It verifies connection-point energy coverage; it does not prove the appliance's actual savings, and one run cannot show what the other start time would have cost. Here the measured site cost came out above the plan's estimate, and we show that rather than hide it."

The runner also prepares a separate H2 grid-import offer at 14:00 for Scene C. It does not claim that the solar-oriented laundry task necessarily fulfils a grid-import offer.

## 1:30–2:15: Scene B, new evidence changes advice

The runner creates and accepts a second-day batch before the alarm, then advances to **18 July 10:00**. In a manual walkthrough create the day-18 task before the alarm; an already completed day-17 task cannot demonstrate an accepted plan changing.

Show the equipment and recommendation explanations: F1's Victron service reports the internal-failure alarm and its maximum discharge current is derated **100 → 25 A from 09:40**. Battery contribution is excluded; the recorded reason codes are `battery_limit_derated_by_bms`, `battery_alarm_active_restricted`, `alarm_internal_failure` and `grid_solar_only_plan`, shown to the customer as plain-language reasons. Show the newly computed slot beside the original acceptance snapshot.

Recorded values:

| Time | Recommendation | Baseline (10:00) | Battery |
| --- | --- | --- | --- |
| 18 July 07:30, before new evidence | 13:30–15:30 at **8.96 RON** (8.9589), −0.24 RON | 9.20 RON | included |
| 18 July 10:00, after clouds and the alarm | 13:30–15:30 at **7.69 RON** (7.6946), −1.51 RON | 9.20 RON | **excluded** |

`review_suggested` is **true**, and the accepted commitment is **unchanged** (start 13:30, estimate 8.96 RON, contract version retained) until the customer reviews it. This scenario changes the evidence and the estimate; it does **not** show a moved start time, so do not claim one.

Say: "New evidence changes what we recommend. It does not silently rewrite what the customer accepted. Clouds affect solar advice; this alarm creates a separate service concern. Weather-consistent production variation alone stays monitoring-only."

For the reference Scene D deadline comparison, do not run correlation at this earlier checkpoint. Equipment and planner checks use the analytical clock independently. Opening the urgent episode earlier starts its response window earlier and can legitimately make it overdue by the next morning.

## 2:15–2:45: Scene C, preserve trust in messy data

Show `build/components/quality_summary.json`, the selected authority and the H2 offer history.

| Check | Recorded result |
| --- | --- |
| H2 Shelly exact duplicate records | **7** suppressed (`exact_duplicate_suppressed`: 7), retained as evidence without multiplying energy |
| Counter reset at 17 July 11:02:30 | **2** intervals `segment_start_known_reset` (`known_counter_reset_new_segment`: 2): energy withheld (none), 0 allocatable; no delta invented across the reset |
| F2 Smart Meter and inverter-gateway copy | One physical meter: authority `F2-M2-FEEDIN`, origin `measured`; the mirror is evidence and is never summed (the 14:00–16:00 window shows 7 frames and 0.0 kWh of import, so the proof is the single selected authority, not a total) |
| H2 offer across the 14:00–15:30 meter gap | 10 kWh consume offer, window 14:00–16:00, measured coverage **0.125**; penalty before waiver **300 bani (3.00 RON)**; penalty charged **0 bani**; reason **`meter_data_incomplete`**; status `expired_unfulfilled` |
| Repeated `import-components` | `duplicate`, same import id |
| Offers worker, first pass | expired 1, settled 1, reminders 0 |
| Offers worker, repeated pass | expired 0, progressed 0, settled 0, reminders 0 |
| Durable totals before and after | **unchanged**: component imports 1, grid frames 4032, user offers 1, settlements 1, notifications 4, assignments 0, savings counter unchanged |

Say: "A gap reduces what we can verify. We waive the penalty rather than make up energy or punish the customer for missing evidence. Repeating the import and the worker changes nothing."

## 2:45–4:30: Scene D, one queue, map and feasible team plan

For a manual live demonstration, advance once to **19 July 11:30** and correlate:

```powershell
.\.venv\Scripts\python.exe -m backend scenario advance --to 2026-07-19T11:30:00+03:00 --correlate
```

Sign in as `scenario-dispatcher`. Recorded: queue revision 3 equals map revision 3; **7 unique open episodes on 4 affected sites**, by band **P0: 0, P1: 1, P2: 3, P3: 3**. Click the F1 battery row and then its map marker; both use the same episode id and operations revision. Expand its drawer to show the reported alarm, affected asset, proposed responsibility, ordinal confidence, priority reason and unknowns. Change a filter once to show synchronized map and list counts.

| Evidence case | Queue and planning outcome at this checkpoint (recorded) |
| --- | --- |
| F1 battery alarm and derating | P1, confidence reported, field visit; qualified Battery Service Crew, service **12:30–14:00** (after its 12:00–12:30 break), deadline met |
| H2 sustained PCC voltage | P2 network review, corroborated; **unassigned on purpose**: `no_eligible_crew`, `crew_not_authorised_for_responsible_service` (no crew is authorized for the responsible service), `crew_location_unknown`, `remote_desk_no_field`; no shutdown diagnosis |
| Weather-consistent drops on S2, F1 and H1 | Three P3 episodes, corroborated; monitoring-only, no field dispatch |
| H1 + H2 declared collector outage | One P2 remote-troubleshooting episode, reported; Remote Triage Desk **13:00–13:45**; missing data is not proof of a power cut |
| S2 persistent underperformance | P2, corroborated; remote review **11:30–12:00**, then a deferred PV O&M crew visit **13:30–15:30** (deadline met), contingent on the desk's outcome |

S3's partial battery feed (storage data refused) is shown as telemetry `partial` without inventing an incident; after the closure below the telemetry counts are 8 fresh and 1 partial. There is **no declared common feeder relation**, so separate physical issues remain separate; the shared grouping is a documented collector relationship, not inferred topology.

In **Teams → Plan teams**, propose a 12-hour plan. Show qualifications, shifts and breaks, member sharing, approximate travel, service windows, remote items and unassigned reasons. The result is labelled a **feasible heuristic proposal**. The feasible FIFO/manual baseline uses identical constraints, and the recorded verdict is **`no_improvement`**: jobs served 4 of 5 in both plans (the unserved job is H2's voltage review), P1 1 of 1 served and timely, P2 3 of 4 served and timely, travel 30 minutes and estimated delay loss 2.192 kWh, each with no difference. Say that plainly; do not claim a route-saving percentage.

Review, then explicitly **Apply** as the dispatcher. Dashed proposed lines become solid applied lines; they are schematic estimates, not road routing. Crew markers are reported bases, not live GPS. Open `tech-battery-1`'s **Agenda** and mark en route; the queue and map workflow follow the authorized update (recorded: the F1 agenda item is `en_route`; the S2 PV item has no progress yet). The shared technician is not double-booked between crews.

Use the runner's recorded checks or prepared screenshots for the error cases:

1. `scenario-supervisor` can view and propose but receives **403 `dispatch_capability_required`** on both review and apply; its buttons explain why.
2. Overriding H2 to P1 (the computed band **P2** stays recorded separately) makes the older reviewed plan return **409 `plan_stale`**; a replacement plan is computed with status **`draft`**.
3. Repeating the same apply key returns the **same assignments**, with no duplicates.
4. The legacy single-incident assign route on a correlated incident returns **`episode_workflow_required`**: correlated work goes through the reviewed plan, progress or a documented closure.

Advance to 12:30 and correlate, then have `desk-operator` document the recovered monitoring path as done:

```powershell
.\.venv\Scripts\python.exe -m backend scenario advance --to 2026-07-19T12:30:00+03:00 --correlate
```

Recorded after closure: the collector incident is `resolved` (resolution `authorized_closure`); open episodes fall **7 → 6**; affected sites stay **4 → 4** (H1 and H2 still have open weather and voltage items); workflow counts are en_route 1, assigned 1, needs_review 1, monitoring 1, none 5; telemetry counts are fresh 8, partial 1, missing 0, stale 0, access_error 0. H1's workflow remains monitoring because its weather episode is still open. The F1 alarm, H2 voltage review, S2 follow-up and the S3 partial feed all remain visible. Closing one episode never certifies the whole site healthy or closes unrelated work.

## 4:30–5:00: limits and next validation

Say: "This demonstrates a reproducible decision and an authorized service workflow. It does not measure field accuracy, real savings or fewer visits. Enphase is excluded; Fronius units are inferred; Victron uses the 16-bit power register; SolarEdge battery states stay raw and lack verified limits. Hardware access and legal applicability remain unverified. Our next step is authorized PPC samples, installation and access checks, real customer tariffs and an O&M review of responsibilities, deadlines and feasible schedules. The mentor's 20 % unnecessary-visits figure is a hypothesis; we have not measured it."

For offline rehearsal, keep local snapshots, built assets, this script and screenshot backups. If OSM tiles fail, use the coordinate/list fallback; the replay planner does not need the live weather widget. Never describe synthetic coordinates, approximate travel or manual catalog prices as live operational data.
