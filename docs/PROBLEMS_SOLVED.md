# One View Solar: problems we solved and how

Challenge 1 (AI Bootcamp x LSAC, presented by PPC): *one view of the energy a prosumer produces, consumes and stores.*
All data in the prototype is synthetic. Figures below come from the prototype's replay scenarios and are **estimates or demo values, not field results**.

**Status.** Both connected workspaces are implemented, not planned. The customer side has the Grid / Battery / Solar evidence cards and the Plan page (`frontend/src/equipment.jsx`, `planner.jsx`). The operations side has the ranked incident queue with the episode drawer (`opsQueue.jsx`), the existing map with the common status projection and routes (`opsMapPanel.jsx`), the Plan teams panel with the FIFO comparison and apply (`opsPlan.jsx`) and the technician agenda (`opsAgenda.jsx`). The scripted four-scene replay (`scripts/demo_scenes.py`) exercises these paths through the API with real accounts; its recorded output is [`demo_run_output.txt`](./demo_run_output.txt), and the values quoted below come from it. Test and browser-check results belong in the final handoff, not in this pitch document. The [replay script](./COMPONENT_DEMO.md) separates observed prototype results from what still needs validation with PPC.

## 1. The main problem: data stays inside each piece of equipment

> "The root cause is that the data stays inside each piece of equipment and is never brought together."

**How we solved it**

- **One shared ingestion engine, configured per vendor.** It reads:
  - three inverter brands: Huawei, Fronius, SolarEdge;
  - three grid meters: Schneider iEM3255, Fronius Smart Meter, Shelly Pro 3EM;
  - two battery sources: Victron GX, SolarEdge storage;
  - three irradiance/weather sources: IMT, Kipp & Zonen, a Campbell weather station.

  Each new brand is a configuration profile, not new code. A test enforces that the engine has no vendor-specific branches.
- **One canonical data model.** Every reading keeps its meaning: what was measured (power, energy counter, state of charge, irradiance), where (grid connection, battery, panel plane), when (measurement vs arrival time), with what quality, and from which source.
- **Data quality preserves trust.** The engine handles the kinds of messy data that real devices produce:
  - duplicates and readings arriving out of order;
  - the same meter reported twice through a gateway, which is never double-counted;
  - counter resets, which never create invented energy;
  - gaps, which are shown as "unknown", never as zero;
  - impossible values such as a battery at 108%, which are rejected rather than "fixed".

  In the replay: 7 exact duplicate Shelly records are suppressed, 2 counter-reset intervals start new segments with no energy invented, and F2's mirrored meter is never added to its authoritative stream. An H2 offer window with measured coverage of 0.125 waives its 3.00 RON penalty (`meter_data_incomplete`). Repeating the import and the offers worker leaves every durable total unchanged.
- **Evidence before data.** For every device we checked the vendor documentation to confirm which fields can really be read. We used 8 of 9 candidate sources; Enphase was excluded because no published response format was available. We did not invent fields we could not verify.

## 2. The three pains in the brief

### Pain 1: "Paying more than they need to." The customer doesn't know when to consume

**For the prosumer:**

- **Plan page (business task planner).** It recommends when to run a flexible heavy load. For example, a small laundry's 4 kW × 2 h batch is shown as "run now" vs "best slot". The comparison uses:
  - the customer's own contract, including time-of-use price bands (with overnight bands and daylight-saving days handled);
  - the solar forecast;
  - the battery's reported limits plus the scenario's declared capacity, reserve and efficiencies.

  Demo result on 17 July: the usual 08:00 start 12.16 RON vs recommended 11:00–13:00 at 9.62 RON. That is an estimated 2.54 RON less for one batch. After the accepted run, the connection-point meter measured 9.47 kWh imported with full coverage. The meter sees the whole site, and the measured site cost over that window (10.60 RON) was higher than the plan's whole-site estimate (7.89 RON); one synthetic run neither validates nor refutes the estimate.
- **Honest economics.** The planner counts the export revenue lost when solar is used on site, and it never treats battery energy as free. The battery must be left in a fair state at the end of the period. Unknown prices are shown as "unknown", never as 0.
- **Daily Forecast widget.** Shows today's expected production, consumption and estimated profit from live weather and the customer's contract.
- **Power Block Offers.** The distributor offers time-limited deals, for example "use 10 kWh at 0.55 RON/kWh in the next 2 hours". Penalty terms are always visible before accepting. A savings counter shows what the customer saved or earned.
- **Plain-language energy.** The interface translates measured energy into everyday equivalents, with different wording for homes and businesses. These comparisons are illustrative, not appliance submetering.

**For the distributor (PPC):**

- Offers can move consumption into solar-surplus hours or ask for export at peak times. Every offer is targeted and capped by area, and the manager dashboard shows uptake, delivery and penalties.

### Pain 2: "Several apps, no full picture"

**For the prosumer:**

- **Home dashboard.** It shows energy flows (solar, home or business consumption, grid), history (today, week, month, year), a production forecast and the contract in one place, whatever brand the equipment is.
- **Grid, Battery and Solar evidence cards.** Each shows which device the data comes from, the latest value, how fresh it is, and in plain words what can't be verified. For example: "Battery contribution excluded: the battery reports an active alarm."
- **Home and business accounts.** Business accounts use business wording and examples.

**For O&M:**

- **One existing operations map.** It uses real Bucharest/Ilfov boundaries and fictional site coordinates. The equipment replay has nine provider sites in Sector 1 and Ilfov; the older compact demo has 60 separate identities across Sectors 1–6 and Ilfov. Area membership is never treated as electrical topology.
- **Per-site status.** The status keeps separate four things that are often confused:
  - the equipment condition;
  - whether data is arriving (fresh, stale, missing, access error);
  - the workflow stage;
  - the priority.

  "No data" is never shown as "healthy".

### Pain 3: "Faults found after the damage." O&M learns about problems too late

**For O&M:**

- **Multi-device incident correlation.** The system compares inverter, meter, battery and weather data. It tells apart:

  | Situation | What it means | What happens |
  |---|---|---|
  | Production fell together with measured sunlight on a compatible plane | Weather-consistent variation; other issues are not ruled out | Monitoring only, no truck sent for this evidence |
  | Production fell while sunlight was normal | Unexplained underperformance | Remote review, then a site visit |
  | Battery reports an alarm or a reduced power limit | Battery-related restriction | Qualified battery-service work is proposed; only a dispatcher applies it; battery support is excluded from planning |
  | Sustained high voltage at the grid connection | Needs network review | Responsibility is proposed for review, not sent externally; no "it caused a shutdown" claim |
  | Several sites go silent through the same declared data collector | Monitoring-path evidence; loss of electricity is not established | One remote troubleshooting job; no automatic field visit |
- **Safety-first ranking.** Safety issues and deadlines always come first. Every rank has a written explanation, and an override needs a reason and expires.
- **Crew planning.**
  - Proposes which qualified crew handles each job, in what order and roughly when, respecting shifts and customer access windows.
  - Compares the proposal honestly with a first-come-first-served plan. In the demo it is no better, and it says so: verdict `no_improvement`, with identical jobs served (4), travel (30 minutes) and estimated delay loss (2.192 kWh).
  - Only the dispatcher can apply it; the system blocks stale plans and double booking.
  - Technicians see their own agenda.
- **Incident log** on every incident, plus the support-request link.

**In the replay at 19 July 11:30:** 7 unique episodes on 4 affected sites (1 P1, 3 P2, 3 P3). The F1 battery alarm is proposed to the Battery Service Crew at 12:30–14:00; S2 underperformance gets a remote review (11:30–12:00) before a PV crew visit (13:30–15:30); the H1 + H2 collector outage is one remote-desk job (13:00–13:45); three weather-consistent drops stay monitoring-only; and H2's sustained voltage review is deliberately left unassigned because no crew is authorized for the responsible network service. The supervisor's apply attempt returns 403, a priority override makes the earlier plan return 409 `plan_stale`, and closing the collector episode takes the open episodes from 7 to 6 while the other issues remain visible. All crews, shifts and travel times are fictional planning inputs.

**For the prosumer:**

- **Equipment problems surface early.** The customer sees them on their cards and in "Looking after your home/business", with safe guidance: contact the technician, never open the equipment.
- **Support requests with an optional short video.** A request goes to the right team, and a booked technician visit shows in the customer's history.

## 3. Constraints in the brief

| Constraint | How we respect it |
|---|---|
| Must work **alongside** existing inverters and energy management systems, not replace them | We only read vendor data (documented APIs, Modbus registers, exports). There are no device commands and no remote switching; recommendations are advice and the customer starts the appliance. |
| Must respect **prosumer rules and data protection** | Every endpoint enforces access; customers see only their own sites and staff only their areas, and importing data grants nothing. Security measures include hashed passwords, CSRF protection, session expiry and no raw device payloads in the interface. Video uploads require consent and are not allowed for danger reports. Crew locations and shifts are visible only to authorised staff. We make no legal-compliance claims; regulatory points are marked "to verify with PPC". |

## 4. "Questions worth investigating": what the prototype shows, and what still needs the mentors

| Question | What the prototype answers | What we still need from PPC mentors |
|---|---|---|
| **Which user feels the pain more sharply today: the prosumer or the O&M technician?** | We built for both, and the same data serves both. The prosumer gets cost decisions; O&M gets early, explained incidents and crew plans. The data shows where each one loses money or time, but not who feels it more. | Interviews: frequency and cost of each pain, and raw quotes. This is the brief's "riskiest assumption" to test. |
| **How do customers decide when to run heavy loads now, and how much do they actually lose?** | The planner compares estimated incremental cost per decision against the customer's saved contract. Example: 2.54 RON estimated less for the laundry batch on 17 July in this replay. Whole-site measured progress does not prove appliance-specific savings. | Real habits, appliance measurements and real tariffs; then validate realized costs rather than extrapolating a single synthetic batch. |
| **How does O&M currently find out about a fault, and how late is "late"?** | In the replay, the system raises evidence-based episodes as soon as a rule's persistence window is met. Examples: the battery alarm on 18 July, the H1+H2 data outage within its time window, S2 underperformance as a persistent deficit against measured sunlight. It also records when each condition started. | Today's real detection path (customer calls? daily checks?) and typical delays, so we can compare "time to spot a problem" before and after. |
| **What data can realistically be pulled from common inverters and EMS?** | A field-by-field [evidence matrix](./COMPONENT_SOURCE_NOTES.md), alongside the existing inverter notes. It records acquisition paths, prerequisites and limits for 3 meters, 2 battery paths and 3 weather sources. Enphase's response schema was not accessible in the review, so it is excluded. The selected Victron limits require a supported CAN-bus BMS/Lynx NG path; SolarEdge lacks verified limits. Operational PCC meters are not automatically certified billing feeds. | Authorized samples and installation details, to confirm field availability, permissions and refresh rates. |

## 5. "What success looks like"

> "A single view of energy produced, consumed and stored that helps the customer consume more smartly (and pay less) and helps O&M catch abnormal operations early. The result should show a visible reduction in wasted energy or in the time it takes to spot a problem."

- **A single view:** yes. One customer workspace and one operations workspace over all brands and device types.
- **Pay less:** shown per decision, with transparent maths (with vs without the task, against the customer's contract), always labelled "estimated".
- **Catch abnormal operations early:** shown in the replay, with correlated episodes, explanations and crew proposals.
- **Visible reduction:** the prototype gives the mechanism and per-case numbers, not a validated percentage. We deliberately do not claim figures such as "20% fewer unnecessary visits". The next step is to measure before and after on PPC sample data with the O&M team.

The Scene D comparison is a functional result under fictional skills, shifts and travel: the heuristic and feasible FIFO baseline tie. It supports a reviewable, authorized schedule, not a claim of operational optimization gains. Fronius units remain inferred, Victron power uses the 16-bit register only, SolarEdge raw battery-state codes have no inferred labels, and legal applicability remains unverified.
