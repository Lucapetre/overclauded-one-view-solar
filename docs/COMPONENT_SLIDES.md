# Three-slide pitch outline

Five minutes, four presenters, one laptop. Keep **Synthetic replay · July 2026** visible on every slide. The [demo script](./COMPONENT_DEMO.md) gives the commands and the second-by-second pacing (30 / 60 / 45 / 30 / 105 / 30 s); the [architecture](./COMPONENT_ARCHITECTURE.md) is the technical backup. Every number below is a value from `docs/demo_run_output.txt` (one deterministic replay of fictional data). None of it is a field result, a bill, a measured accuracy or a visit-reduction figure.

| Slide | Time on screen | Live demo behind it |
| --- | --- | --- |
| 1. Fragmented data, late and misrouted response | 0:00–0:30 | none; native source crops |
| 2. A decision the customer can follow, and a plan the dispatcher can apply | 0:30–4:30 | Scenes A, B, C, D |
| 3. Evidence, prototype comparisons and next validation | 4:30–5:00 | none |

## Slide 1: Fragmented evidence makes decisions late or misrouted

**Main line:** "The data stays inside each device. A customer cannot decide, and a dispatcher cannot route, without bringing it together."

Show two short user questions side by side:

- Laundry owner: "When should I run this batch, and why?"
- Dispatcher: "Is this monitoring, remote review, a network review, or a job for a qualified crew?"

Below them, three small native-format snippets feeding one canonical record: meter register words, Victron battery-service register words in the collector's JSON envelope, and the configured Campbell TOA5 four-row header. Caption: **3 meter paths + 2 battery paths + 3 weather paths: 8 of 9 candidates delivered. Enphase excluded (no accessible response schema).**

Speaker notes (0:00–0:30): "The values are simulated, but the fields and interfaces were checked before we simulated anything. One configuration-driven engine keeps identity, units, measurement boundary, time, quality and source. A field we cannot verify is excluded, not invented." Do not imply the Campbell station is installed at F1: F1's irradiance evidence is from its own IMT POA sensor; the station is an area resource shared by H1/H2/H3.

**Screenshot suggestions:** crop the native snippets from `demo_components/meters/F1_schneider_iem3255_registers.ndjson`, `demo_components/batteries/F1_victron_gx_battery_registers.ndjson` and `demo_components/weather/WX_SECTOR1_CS01_OneMin.dat`; then `laundry-owner` Home with the Grid / Battery / Solar cards at 17 July 07:30, keeping the replay badge, source names and last-update times. No credentials, internal paths or real identities.

## Slide 2: Explain the decision, then propose feasible work

Customer screenshot on the left; operations queue and map, plus a small plan comparison, on the right.

**Customer, 17 July (Scene A):**

> 4 kW × 2 h batch, fictional contract: **12.16 RON** at the usual 08:00 start → **9.62 RON** at 11:00–13:00.
> **Estimated 2.54 RON less for one batch.**

Caption: incremental site-cost estimate from contract bands, the forecast available at 07:30 and the battery's reported limits; battery included at the 07:30 decision. After the run, the connection-point meter measured **9.47 kWh** imported with full coverage. It measures the whole site: the measured site cost over the window was **10.60 RON** against the plan's whole-site estimate of **7.89 RON**, and one run cannot show what the other start would have cost. Say this plainly; it is the prototype's honesty point, not a saving.

**Changing evidence, 18 July (Scene B):** a day-18 plan is accepted for 13:30–15:30 at an estimated 8.96 RON (usual-time baseline 9.20 RON). At 10:00 clouds arrive and the Victron service reports an internal-failure alarm with discharge derated 100 → 25 A: the battery is excluded with plain reasons, the estimate for the same slot recalculates to 7.69 RON, a review is suggested, and the accepted commitment stays unchanged.

**Data quality, 17–18 July (Scene C):** 7 exact duplicate Shelly records suppressed, 2 counter-reset intervals recorded as new segments with no energy invented, F2's mirrored meter never added to its authoritative stream. The H2 offer across the meter gap had **coverage 0.125**, so its 3.00 RON (300 bani) penalty is waived as `meter_data_incomplete`. Repeating the import and the offers worker leaves every durable total unchanged.

**Operations, 19 July 11:30 (Scene D):**

- **7 episodes on 4 affected sites** (P1: 1, P2: 3, P3: 3), the same ids and operations revision in the queue and on the map.
- F1 battery alarm → qualified Battery Service Crew, 12:30–14:00. S2 underperformance → remote review 11:30–12:00, then a PV crew visit 13:30–15:30. H1+H2 shared-collector outage → one remote-desk job, 13:00–13:45. Three weather-consistent drops → monitoring only. H2 sustained voltage → **deliberately unassigned**: no crew is authorized for the responsible network service.
- **Heuristic vs a feasible FIFO baseline under the same constraints: `no_improvement`** (4 jobs served, 30 travel minutes and 2.192 kWh estimated delay loss in both). Say so; do not invent a gain.
- Dispatcher applies; supervisor receives 403 `dispatch_capability_required`; a priority override on H2 makes the old plan return 409 `plan_stale`; repeating apply returns the same assignments; closing the collector episode at 12:30 takes **7 → 6** open episodes while the F1, H2, S2 and S3 issues stay visible.

**Screenshot suggestions** (capture each before advancing the forward-only clock):

1. Customer Plan at 07:30 with the "run now vs recommended" card and **Why this recommendation?** open.
2. The restricted-battery explanation and the unchanged accepted commitment on 18 July.
3. H2's offer history showing `meter_data_incomplete` and the waived penalty.
4. Dispatcher Incidents at 11:30 with F1 selected: queue row, map marker and drawer.
5. Teams → Plan teams showing the verdict `no_improvement` and H2's unassigned reason.
6. `tech-battery-1` Agenda after apply, and the map with dashed (proposed) turning solid (applied) lines. Label them **schematic estimates**, never road routing; crew markers are reported bases, not GPS.

## Slide 3: A reproducible prototype, with explicit limits and next validation

**Feasibility evidence:** a field-by-field matrix ([source notes](./COMPONENT_SOURCE_NOTES.md)) with include / narrow / exclude rows and the prerequisites for each path; 8 of 9 sources delivered, Enphase excluded; the operations inputs (crews, shifts, travel, prices) are labelled synthetic and kept out of vendor payloads.

**Actual prototype comparisons (all on fictional inputs):**

- Planner: 12.16 → 9.62 RON estimated for one batch; measured whole-site cost 10.60 vs plan estimate 7.89 RON for the window.
- Crew plan vs FIFO baseline: no difference on jobs served, timeliness, travel or estimated delay loss.
- Meter gap: penalty waived rather than punishing missing evidence; repeated import, worker and apply paths add no duplicates.

**What this establishes:** a feasible, explainable schedule and an honest baseline comparison on fictional inputs. It does **not** establish diagnostic accuracy, real bill savings, faster real repairs or any percentage reduction in visits.

**Limits to keep on the slide:**

- Enphase excluded: no accessible response schema established.
- Fronius units inferred; Victron uses the 16-bit power register only; SolarEdge battery state raw, no verified limits.
- No live hardware or crew GPS, no device control, no inferred feeder topology, no legal-compliance claim.
- OSM tiles and the live city-weather widget need internet; the local replay and the coordinate/list fallback do not.

**Next PPC validation:** authorized installation samples and availability checks; ownership and access review; real tariffs and appliance-level measurements; an O&M review of responsibility, skills, deadlines and travel; comparison with documented current workflows.

Speaker notes (4:30–5:00): "We can reproduce this path on a laptop from a clean setup. The next evidence has to come from authorized samples and the people who run the service. The mentor's 20% unnecessary-visits figure is a hypothesis we have not measured."

**Screenshot suggestion:** a compact crop of the feasibility matrix rows (include / narrow / exclude) beside the runner's printed "actual values" lines. Put test counts only on a technical backup slide after checking the final validation record; do not imply a suite was rerun when an earlier green result was retained.
