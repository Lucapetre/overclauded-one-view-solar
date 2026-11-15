# Presentation briefing: One View Solar (Challenge 1, PPC)

Everything you need to present, demo and defend the project. Read sections 1–5 before rehearsing and section 8 (jury Q&A) the night before.

> **Rule for the whole pitch:** all data is **synthetic**, and every money figure is an **estimate** from a replay scenario. Say "estimated" and "in our synthetic scenario". Never claim a validated percentage (for example "20 % fewer visits"). Being honest about this is a strength: the challenge brief says "evidence beats ideas".
>
> The figures below come from development runs. Before presenting, check them against `docs/demo_run_output.txt`, which comes from the final demo run, and use the values there.

---

## 1. The challenge in one breath

**Challenge 1: one view of the energy a prosumer produces, consumes and stores** (presented by PPC).

- **Who hurts:**
  - *Prosumers*: homes and companies with solar panels (PV) and/or batteries (BESS).
  - *PPC's O&M teams*: the people who look after these installations.
- **What happens today:** every device shows its own piece in its own app. The data stays inside each piece of equipment and is never brought together, so nobody sees production, consumption and storage at once.
- **What it costs them:**
  1. *Paying more than they need to.* Customers don't know when to run heavy loads.
  2. *Several apps, no full picture.* Production, battery and consumption sit in separate apps, often from different makers.
  3. *Faults found after the damage.* Underperformance, a poorly used battery or a fault that is just starting is found late, once it has already wasted energy or caused a breakdown.
- **Constraints:**
  - It must work **alongside** existing inverters and energy management systems, not replace them.
  - It must respect **prosumer rules and data protection**.
- **What success looks like:** one view that helps the customer consume more smartly (and pay less) and helps O&M catch abnormal operation early, with a visible reduction in wasted energy or in the time it takes to spot a problem.

**Our one-line answer:** *One View Solar collects data from any brand of inverter, meter, battery and weather sensor. It turns that data into one trustworthy energy picture, then uses it to (1) tell customers when to use energy and what it will cost, and (2) tell PPC's O&M team which problems are real, which matter most, and which crew should go where.*

---

## 2. The framework in three steps

```
STEP 1: COLLECT           STEP 2: NORMALISE & TRUST            STEP 3: DECIDE & ACT
many vendors, many    →   one shared engine, one data model  →  customer decisions + PPC operations
formats, messy data       quality checks, authority, clock      (one view for both users)
```

### STEP 1: Collect data from separate equipment (the "scraper")

**The problem it solves:** "the data stays inside each piece of equipment". Every vendor speaks a different language:

- **Huawei FusionSolar:** nested cloud JSON.
- **Fronius:** a local network JSON API, with different meanings depending on where the meter is installed.
- **SolarEdge:** cloud JSON with local timestamps.
- **Schneider meters:** raw 16-bit Modbus registers.
- **Shelly:** device RPC JSON.
- **Victron:** Modbus registers through a gateway.
- **Campbell weather stations:** a 4-header-row CSV text file (TOA5).

Units differ (W vs kW, Wh vs kWh), signs differ (is negative "import" or "export"?), and times differ (UTC vs local, measurement time vs "when the server answered").

**What we built:**

- **Sources covered:**
  - **3 inverter brands** (Huawei, Fronius, SolarEdge) across **9 fictional installations** (H1–H3, F1–F3, S1–S3), simulated for 7 days (15–21 July 2026, Bucharest time). This is the "phase 1" data.
  - **8 additional equipment sources**, each checked against vendor documentation:

    | Family | Sources | Notes |
    |---|---|---|
    | Grid meters | **Schneider iEM3255** (Modbus registers), **Fronius Smart Meter** (Solar API), **Shelly Pro 3EM** (RPC JSON) | |
    | Batteries | **Victron GX** (Modbus battery service), **SolarEdge storageData** | |
    | Weather / irradiance | **IMT Si-RS485** irradiance sensor (Modbus), **Kipp & Zonen SMP10x** pyranometer (Modbus), **Campbell Scientific** weather station (TOA5 file) | |
    | Excluded | **Enphase** batteries | No published response format available, so we did not invent one |
- **Evidence before data (very important for the jury).** Before generating any data, we checked each vendor's documentation and recorded, for every single field:
  - the register or JSON path;
  - the type and scale;
  - the unit and the sign convention;
  - the document version and page.

  This lives in `docs/COMPONENT_SOURCE_NOTES.md` and `config/component_evidence.yaml`. A test fails if we ever map a field that isn't in that evidence file. What we found:
  - Schneider's Modbus addresses are register number − 1.
  - Victron's charge/discharge limits only exist when a CAN-bus battery management system is connected.
  - Fronius meter signs depend on the meter location.
  - The IMT sensor returns 0 for unsupported channels, which must not be read as a real zero.
- **Realistic, physically consistent synthetic data.** The new equipment data is generated from the **same simulation** as the inverter data, so the numbers agree:
  - solar production matches the irradiance measured on the panel plane;
  - grid import + PV + battery discharge = consumption + export + battery charge + losses;
  - meter counters are the integral of the flows;
  - battery state of charge respects capacity, efficiency and limits.

  Generation is **deterministic** (seed 42) with SHA-256 manifests: run it twice and you get identical files.
- **Real-world defects deliberately injected** (18 cases), so we can prove we handle them:
  - duplicates and readings arriving out of order;
  - the same meter reported twice through a gateway;
  - a counter reset;
  - an unexplained backwards counter step;
  - data gaps and access errors (HTTP 403, timeouts);
  - an impossible battery SoC of 108 %;
  - a wrong Modbus word order;
  - negative temperatures;
  - cloud-driven production drops;
  - a battery alarm with power derating;
  - a shared data collector outage;
  - small negative night readings from a pyranometer (normal, not a fault).

  The "correct answers" live in a separate evaluation folder that the runtime code is **forbidden** to read; a test enforces this.
- **Collection is read-only.** We read documented APIs, registers and export files, and send **no** commands to devices. This answers the constraint "work alongside existing inverters and EMS".

**Key message:** *"Adding a new brand is a configuration file, not new code."* There are no vendor-specific branches in the business logic, and a test enforces it.

### STEP 2: Normalise, check and make the data usable

**The problem it solves:** raw data is not trustworthy. Mixing units, double-counting a mirrored meter, reading a gap as "zero production" or inventing energy across a counter reset all lead to wrong decisions and wrong bills.

**What we built:**

- **One shared ingestion engine** (`scraper.py` + `engine/`). Readers for nested JSON, register snapshots and TOA5 files feed one pipeline driven by **declarative profiles** (`config/provider_profiles.yaml`, `config/component_profiles.yaml`). Transforms come from a fixed safe list: no `eval`, no arbitrary code, and safe YAML loading.
- **One canonical data model.** Every observation keeps:
  - **identity**: provider, account, site, device, physical asset, endpoint, channel;
  - **what it is**: metric, unit, sign convention, aggregation (instantaneous, interval average, min/max, interval energy, cumulative counter);
  - **where it was measured**: grid connection point, AC or DC side, battery, panel plane vs horizontal;
  - **when**: source time vs received time vs response time, stored in UTC and shown in Bucharest time; daylight-saving days are handled;
  - **how trustworthy it is**: availability, quality flags, freshness, coverage;
  - **provenance**: the original record hash, the mapping version, and any conversion or derivation.
- **Data quality rules:**

  | Situation | How we handle it |
  |---|---|
  | Duplicates | Stored once and marked as duplicates |
  | Out-of-order records | Sorted by source time; arrival time kept |
  | Mirrored meter (the same physical meter via inverter and directly) | One **authoritative** source chosen, the other kept as evidence, **never summed** |
  | Counter reset (only on resettable counters, documented) | New segment starts; no energy invented across the reset |
  | Backwards step on a non-resettable counter | Flagged; no fake reset and no negative energy |
  | Gaps | Shown as **unknown with coverage %**, never as 0 |
  | Impossible values (SoC 108 %) | Rejected; never "clamped to 100" |
  | Wrong unit or word order | Flagged as a configuration problem; we never "repair" it by guessing |
  | Bad single field | Rejected individually; the rest of the record is kept |
  | Unknown device | Quarantined; we never guess which customer it belongs to |
- **Authority and no double counting.** For each site, physical boundary, metric and time interval there is exactly one primary source with a quality-aware fallback.
- **Capability flags.** The system knows what each site can and cannot prove: for example "grid energy verified", "battery-assisted planning available", "irradiance explanation available". It explains in plain language why something is unavailable, for example "battery limits unavailable" for the SolarEdge battery.
- **Immutable imports.** Each snapshot is imported once (by content hash), switched atomically, and a repeated import is a no-op. Importing data **never grants anyone access**.
- **One analytical (replay) clock.** The whole scenario (freshness, planning, offers, incidents, crew plans) runs on one clock that only moves forward. Security functions such as sessions and audit receipts use real time. This means the demo can "advance time" without rewinding money or creating duplicates.

### STEP 3: Final output: the problems we solve (customer and PPC)

See section 3. The detailed feature map is in section 4.

---

## 3. Every problem and how we solve it

### 3.1 For the customer (prosumer: homes and businesses)

| # | Customer problem | Our solution | Where in the app |
|---|---|---|---|
| C1 | "I see my energy in pieces, one app per device." | One Home view: solar production, consumption, grid import/export and battery, whatever the brand. Plus **Grid / Battery / Solar evidence cards**, each showing the source device, latest value, freshness and plain-language limits. | `/consumer` Home |
| C2 | "I don't know when to run heavy loads." | **Plan page:** for a flexible task (demo: a laundry batch, 4 kW for 2 h), it compares **"run now"** with the **cheapest feasible slot** before the deadline. It uses the customer's own contract (including time-of-use bands), the solar forecast and the real battery limits and reserve. | `/consumer` Plan; "Next task" card on Home |
| C3 | "Is solar really free? What does it cost me?" | Honest economics. The planner computes *site cost with the task minus site cost without the task*, including the **export revenue you give up** when you use solar yourself. Battery energy is **never free**: it must be refilled and left in a fair state at the end. Unknown prices are shown as **unknown**, never as 0. | Plan, under "Why this recommendation?" |
| C4 | "Kilowatt-hours mean nothing to me." | Plain-language energy, for example *"Today's export would run a big-screen TV for N hours"*. Business accounts get business examples (display fridge, oven, dishwasher). | Home |
| C5 | "What will tomorrow look like?" | A **Daily Forecast** card (production, consumption and estimated profit for today or tomorrow, from live weather and the contract) and a **3-day production forecast** that shows its formula. | Home |
| C6 | "Is my battery helping, or am I misusing it?" | Battery-aware planning. The battery is used **only** when fresh state of charge, capacity, reserve, battery-management limits and efficiency are known **and** there is no active alarm. Otherwise the planner excludes it with a plain reason, for example *"Battery contribution excluded: the battery reports an active alarm"*. | Plan, Battery card |
| C7 | "What is my contract really costing me?" | Contract page with fixed or **time-of-use bands** (night or midnight-crossing bands, daylight-saving days, validity dates). Prices flow into every estimate. | Plan / Contract |
| C8 | "I want to earn more from my installation." | **Power Block Offers** from PPC, e.g. *"Use 10 kWh at 0.55 RON/kWh within 2 h"* or *"Feed in 10 kWh at 0.70 RON/kWh within 2 h"*:<br>• penalty rules always visible in plain language before accepting, behind an unticked confirmation box;<br>• live countdown and progress;<br>• fair settlement from **measured** meter energy;<br>• an animated **savings counter** ("You've saved/earned X RON", which can be negative and is never hidden). | `/consumer` Offers |
| C9 | "Something seems wrong with my system." | **Support requests** in 13 categories, with an optional short **video**. The danger option says "move away, call 112", and video is disabled for danger reports. The request goes to the right team, a booked technician visit appears in the history, and conversations continue there. | `/consumer` Support |
| C10 | "I don't understand energy." | **Interactive lessons** (cards plus a mini test) with a small simulated reward credit, checked on the server. | `/consumer` Learn |
| C11 | "I'm a business, not a home." | **Business accounts**: business wording, business consumption shapes (restaurant, office, factory), business examples. A full roadmap is in `docs/BUSINESS_ACCOUNT_PLAN.md`. | Account type |
| C12 | "Can I trust these numbers?" | Every value shows its source, time and freshness. Estimates are labelled "estimated", missing data is never shown as zero, and a conspicuous **"Synthetic replay"** badge shows the demo time. | Everywhere |

### 3.2 For the distributor (PPC: operations, O&M, dispatch, management)

| # | PPC problem | Our solution | Where in the app |
|---|---|---|---|
| P1 | "Data from many brands never comes together." | Step 1 and Step 2: one engine, one canonical model, one authoritative source per measurement, quality and provenance on everything. | Backend; equipment evidence in drawers |
| P2 | "We learn about problems only after they cost money." | **Multi-device incident correlation.** It compares inverter, meter, battery and weather evidence and raises **explained episodes** (see the table below). | `/ops` Incidents queue and drawer |
| P3 | "We send trucks for things that aren't faults." | Weather-consistent drops are **monitoring only** (no truck). A **shared collector outage** becomes **one remote troubleshooting job**, not a visit per site. Remote review comes before a field visit for underperformance. | Queue: remote vs field |
| P4 | "Which problem first?" | **Safety-first ranking.** Priority bands (P0–P3) come first: safety and deadlines always win, and missing economic data never demotes a hazard. Within a band, deterministic factors: deadline, impact, recoverable loss, evidence confidence, remote vs field. Every rank has **reason codes, a factor table, unknowns and a policy version**. Overrides need a reason, are audited and expire. | Queue, drawer |
| P5 | "Who is responsible: the customer's installer, the distributor, the monitoring provider?" | Responsibility comes from the asset/service registry, never guessed from brand or location. Example: H2 voltage → distributor review; F1 battery fault → battery service. | Drawer |
| P6 | "Which crew goes where, in what order?" | **Crew planner.** A deterministic heuristic proposes the qualified crew, visit order and ETAs. It respects qualifications, scope, shifts and breaks, customer access windows, travel times, locked jobs, dependencies and member availability across crews. Impossible jobs are listed as **unassigned with an honest reason**. | `/ops` Plan teams |
| P7 | "Is the plan actually better?" | Compared with a **first-come-first-served baseline** under the same constraints: travel minutes, deadlines met by priority, jobs served. In our scenario the verdict is **"no improvement", and we show that honestly**. | Plan teams |
| P8 | "Two managers assign the same crew twice." | **Apply** is dispatcher-only and transactional, with a revision check (a stale plan returns 409 and is recomputed) and an idempotency key (a repeated click creates no duplicates). Supervisors can see the plan but cannot apply it. | Plan teams |
| P9 | "Technicians need a clear day plan." | **Technician agenda**: own crew's ordered visits with ETAs and reasons; progress steps en route → on site → done (note required). Closing happens through authorised actions, never because a feed went silent. | `/ops` Agenda |
| P10 | "We can't see the whole area at once." | **Operations map of Bucharest Sectors 1–6 and Ilfov** with real OSM boundaries and site clusters.<br>• Markers show equipment condition, data freshness, workflow and priority **as separate badges**; "no data" is never shown as green.<br>• Crew bases are shown (no fake live GPS).<br>• Proposed routes are dashed, applied routes solid, both labelled schematic.<br>• Sites without coordinates go in an **unmapped** list.<br>• Map, queue and drawer share the **same revision**, so they never disagree. | `/ops` Area Radar / map |
| P11 | "Area managers should only see their area." | Server-side scoping everywhere: sites, incidents, map, routes, crew positions, counts, revenue. | All ops pages |
| P12 | "We want to shift load or get export when the grid needs it." | **Offer management for managers.** Create, preview the audience (with warnings when a price is worse than the tariff), publish, cancel and edit (only until someone accepts). Targeting: all clients in an area, consumers or prosumers, minimum installed kWp, hand-picked clients, or the zone of a grid incident. Limits on takers and total kWh. Dashboard of uptake, delivery, penalties, charges and payouts. **Full audit log.** | `/ops` Offers |
| P13 | "What is our revenue by area, and from businesses?" | A **Revenue** view (estimate from synthetic billing profiles × tariff), split by business vs home and by sector, with a ranked list of business accounts. | `/ops` Revenue |
| P14 | "We need an audit trail." | Incident logs record every assignment, team dispatch, meeting, reply and closure. Offer audit records every edit and publish. Plan and assignment revisions are kept. | Drawers / logs |

**Correlation rules (what O&M sees and why):**

| Evidence | Interpretation | Action | What it *cannot* prove (we say so) |
|---|---|---|---|
| PV drop **and** measured irradiance drop on the panel plane | Weather-consistent | Monitor, no truck | That no hardware issue exists |
| PV deficit vs measured sunlight, persistent | Unexplained underperformance | Remote review, then a field visit | Which panel or string failed |
| Battery reports an alarm or a reduced power limit | Battery operational restriction | Battery service; battery planning switched off for the customer | Thermal runaway or failed cells |
| Sustained high phase voltage at the grid connection | Voltage review | Distributor network review | Fault location or transient compliance |
| Several sites silent through the same collector | Monitoring-path problem | **One** remote job | A power outage |
| Several sites with anomalies **and** a declared common feeder | Possible upstream episode | Parent with child sites, loss counted once | Topology from map proximity (we never infer it) |

---

## 4. The demo: four scenes (5 minutes)

Suggested pacing: 30 s sources and feasibility → 60 s Scene A → 45 s Scene B → 30 s Scene C → 105 s Scene D → 30 s limitations and next steps.

**Scene A: a useful business decision.** Log in as the laundry owner (`laundry-owner`, site F1). Replay time: 17 July 2026, 07:30.

1. Show briefly that three very different raw formats feed the same Grid, Battery and Solar cards: Modbus registers, battery data and a TOA5 weather file.
2. On the Plan page, the 4 kW × 2 h laundry batch: **run now ≈ 12.16 RON vs recommended 11:00–13:00 ≈ 9.62 RON**, an **estimated ≈ 2.54 RON less** for one batch. The recommendation is based on contract bands, the solar forecast from the panel-plane irradiance sensor, and the battery (at reserve).
3. Accept the plan. It becomes locked; nothing is switched on automatically.
4. Advance the replay to 13:30. Measured progress: **9.467 kWh imported at the connection point, 100 % coverage**, with the honest note that the connection-point meter measures the whole site, not the appliance alone.
5. **Be ready for this:** the measured whole-site cost in that window was **10.60 RON**, while the plan estimated **7.89 RON**. The whole site, not just the laundry, used more grid energy than forecast. We show this openly: the estimate is a forecast-based comparison, and one measured day cannot prove what would have happened otherwise. If asked, this is a strength: we don't hide forecast error.

**Scene B: new evidence changes the decision.** Advance to 18 July, 10:00.

1. Clouds, and the battery reports an internal-failure alarm with its discharge limit derated from 100 A to 25 A.
2. The recommendation recalculates. The battery is **excluded, with the reasons shown**: BMS derate, active alarm, internal-failure alarm, so the plan is grid and solar only. Recorded values: at 07:30 the 13:30–15:30 slot was estimated at 8.96 RON vs a 9.20 RON baseline; at 10:00 the same slot is re-estimated at 7.69 RON with the battery excluded.
3. An already accepted plan is **not silently changed**. The app flags "review suggested", and the customer decides.
4. **Speaker note:** focus on the *reasons* changing, not the number. The 10:00 estimate (7.69 RON) is lower than the 07:30 one (8.96 RON) even though the battery is now excluded. The two estimates are made at different times with different inputs: a new forecast, a new baseline, and the battery's stored energy no longer being drawn down and charged for. If a juror asks, answer: "the estimate is recomputed from the evidence available at that moment; what matters is that the battery is no longer promised once it reports a fault."
4. Operations sees the battery episode; **no crew is sent for the clouds**.

**Scene C: data quality builds trust.**

1. A duplicate reading, a mirrored meter (F2) and a Shelly counter reset (H2).
2. The quality summary shows **7 exact duplicates suppressed**, **2 counter-reset intervals with no energy invented**, and one selected authoritative grid source for F2. The mirror is kept as evidence and never summed. The proof is the single selected authority, not a visible total, because F2 imported ~0 kWh in that window.
3. A data gap means incomplete verification, so the offer penalty is **waived**. On H2, coverage was 12.5 %, the penalty before waiver was 3.00 RON, and the charge was **0** (`meter_data_incomplete`). We never penalise a customer for our missing data.
4. Repeating the import or worker leaves **identical totals** (idempotent).

**Scene D: operations, map and crews.** Replay: 19 July, 11:30; log in as `scenario-dispatcher`.

1. The queue and map show 5 cases:
   - **F1** battery fault: P1, needs the battery-qualified crew;
   - **H2** voltage review: P2;
   - weather-consistent drops: P3, monitoring only;
   - **H1+H2** collector outage: one remote job;
   - **S2** underperformance: P2, remote review, then a field visit.
2. Propose a plan:
   - battery crew to F1, about 12:30–14:00;
   - remote desk to the H1+H2 outage, about 13:00–13:45;
   - PV crew to S2, about 13:30–15:30;
   - **H2 deliberately unassigned**, because no crew is authorised for distributor network work. That is honest, not hidden.
3. Baseline comparison: **"no improvement" vs first-come-first-served, shown honestly**. Both serve 4 of 5 jobs with 30 travel minutes and 2.192 kWh estimated delay loss. The queue and map show the same revision, with 7 episodes on 4 sites (P1: 1, P2: 3, P3: 3).
4. Apply as dispatcher. `scenario-supervisor` can see the plan but **cannot apply it**.
5. A priority override makes the old plan **stale (409)**, and a new draft is computed. A repeated apply creates no duplicates.
6. Advance to 12:30. The collector recovers and the desk operator marks the job done, so **open episodes drop from 7 to 6** and H1/H2 data is fresh again. The other issues **stay visible**.

**Setup and fallback:**

- Commands are in `README.md`, and `scripts/demo_scenes.py` prints them and the expected states.
- Keep a **built frontend and a seeded local database ready**.
- Map tiles and live weather need internet. If the network fails, markers still show on a plain background, but say so.

---

## 5. Architecture in one picture (say it in 20 seconds)

```
Vendor sources (Huawei, Fronius, SolarEdge, Schneider, Shelly, Victron, IMT, Kipp & Zonen, Campbell)
   │  documented APIs / Modbus registers / TOA5 files (read-only)
   ▼
STEP 1  profiles (YAML) + readers ──► shared engine (no vendor branches)
STEP 2  validation, quality, authority, quarantine ──► canonical observations + 15-min frames
        immutable snapshot import (hash, atomic switch) ──► FastAPI + SQLite (one analytical clock)
STEP 3  ├─ customer: equipment cards, planner (tariff bands, forecast, battery), offers, savings, support, lessons
        └─ PPC: correlation → safety-first ranking → site status → crew planner → map / queue / agenda / offers / revenue
```

**Tech:**
- Python 3.12, FastAPI and SQLite (WAL, versioned migrations); React 19 + Vite; Leaflet with OpenStreetMap; a generated TypeScript API contract.
- Runs on a laptop with no paid services.
- Tests cover the engine, data defects, planner, tariffs, clock, offers, correlation, ranking, crew planner, permissions and the scenes, about 300+ automated tests in total. Use the exact numbers from the final run.

---

## 6. What is real, and what is simulated (be ready to say this clearly)

**Real and working:**
- the code: engine, backend and both apps;
- the security model;
- the planning, correlation, ranking and crew algorithms;
- the data-quality handling;
- the vendor documentation research;
- the OSM boundaries;
- the live weather API.

**Simulated:**
- all device data and installations (fictional sites and accounts);
- crews, shifts, travel times and repair estimates (labelled "synthetic planning inputs");
- tariffs (a fictional time-of-use contract);
- money figures (estimates);
- the replay dates (July 2026 scenario).

**Not built, and we say so:**
- no live connection to real devices or vendor clouds (we need customer authorisation and API plans);
- no reading of PPC's billing meters (DLMS/COSEM through PPC's own systems);
- no device control;
- no ML failure prediction;
- no Enphase support;
- no validated savings or detection-time percentages.

**Narrowed by evidence:**
- Fronius meter units are inferred from documentation context.
- Victron uses the 16-bit power register only (the 32-bit word order is undocumented).
- SolarEdge battery state has no documented labels, so it is shown as a raw number.
- EU Batteries Regulation and Data Act points are marked "to verify", not claimed.

---

## 7. The "questions worth investigating" from the brief: our answers

| Question | Our answer |
|---|---|
| **Which user feels the pain more sharply today: the prosumer or the O&M technician?** | The same data serves both. The prosumer's pain is money per decision (the planner quantifies it), and O&M's pain is time and wasted visits (correlation and planning address it). Who feels it *more sharply* is our riskiest assumption; we would test it with PPC mentors through interviews and raw quotes. Our hypothesis: O&M, because one missed fault costs energy for days and can mean a truck roll, while a customer loses a few RON per decision. |
| **How do customers decide when to run heavy loads now, and how much do they lose?** | Mostly habit (for example "after work", "first thing in the morning"). The planner shows the loss per decision: ≈ 2.54 RON per laundry batch in our scenario; the browser demo shows 4.50 RON for a 6 kWh EV charge moved into solar hours. Turning that into monthly figures needs real habits and tariffs from PPC. |
| **How does O&M find out about a fault today, and how late is "late"?** | Typically from customer calls, vendor app alarms or periodic checks, often after days of lost production. In our replay, an evidence-based episode is raised as soon as a rule's persistence window is met, and the start time is recorded. Measuring "before vs after" needs PPC's real detection history. |
| **What data can realistically be pulled from common inverters and EMS?** | See our evidence matrix: 3 inverter brands, 3 meters, 2 battery paths and 3 weather sources, with exact fields, interfaces and prerequisites. Enphase is excluded (schema not published). PPC's billing meter is read by PPC through its own systems, not through the inverter makers' cloud apps (from the reference sheet we were given). |

---

## 8. Jury questions and strong answers

### Data and integration
**Q: Is any of this real data?**
A: No, it's synthetic by design. But the *formats* are real: we checked each vendor's documentation field by field, and the generator produces native-shaped payloads, such as real Modbus words and a real TOA5 file. Swapping in real data means pointing the same profiles at authorised real exports; the engine doesn't change.

**Q: How would you connect to real installations?**
A: Three paths, all read-only:
1. **Vendor cloud APIs** (Huawei, SolarEdge, Fronius), with the customer's authorisation and an API key or plan.
2. **Local gateways** (Modbus TCP or Fronius Solar API on the customer's network) via a small collector.
3. **Logger exports** (CSV/TOA5).

Each needs consent; we never bypass access controls.

**Q: What if a vendor changes its format?**
A: Profiles are versioned. A new mapping version is detected by rules, and unknown fields go to "schema review" instead of being silently ignored.

**Q: Why not just use each vendor's app or Home Assistant?**
A: Vendor apps only show their own device, and the brief says the customer sees energy in pieces. Home Assistant is a DIY tool for hobbyists; it doesn't give PPC an operations view, correlation across many customers, crew planning or offer settlement.

**Q: Why did you exclude Enphase?**
A: We couldn't find a published response format for its battery telemetry. Inventing one would mean faking data, so we documented the exclusion instead. That is the "evidence beats ideas" rule.

**Q: How do you avoid double-counting energy?**
A: One authoritative source per site, boundary, metric and interval. Mirrored copies are kept as evidence but never summed. Offer allocation is first-in-first-out, so the same kWh never pays twice. A test covers it.

**Q: What happens when data is missing?**
A: It shows as unknown with a coverage percentage, never as zero. Planning becomes conservative (for example no battery promise), and offer penalties are waived when coverage is incomplete. Losing a feed never "resolves" a fault.

### The customer decision
**Q: Isn't "run at noon when the sun shines" obvious?**
A: Not always. Using solar yourself means giving up export revenue, time-of-use bands change prices during the day, the battery may need that solar for the evening peak, and clouds move the best slot. In Scene B, the battery alarm plus clouds moved the best slot to 13:30. Our planner computes the difference instead of guessing.

**Q: How accurate are the savings?**
A: They are estimates from a forecast and the customer's contract, labelled as such. In our own demo the plan estimated 7.89 RON for the window and the measured whole-site cost was 10.60 RON. We show that gap openly instead of hiding it. After the run we show *measured* grid energy, but one observed day can't prove what would have happened otherwise. Validating savings needs before-and-after data from real customers.

**Q: Does it control the appliance or battery?**
A: No. It only gives advice: the customer starts the appliance, and we send no device commands. That is deliberate (safety, warranty, and the "work alongside" constraint).

**Q: What's the forecast based on?**
A: In the scenario: installed kWp, sun position, and recent measured panel-plane irradiance, using only data available at decision time. On Home we also use a live public weather forecast. Both are shown with their issue time.

### Operations
**Q: Is your incident detection machine learning?**
A: No, and that is intentional. These are explainable rules with documented thresholds, persistence and evidence requirements. With synthetic data, claiming ML accuracy would be dishonest. A learned model could come later, trained on PPC's real labelled history.

**Q: How do you avoid false alarms?**
A: Cross-device evidence. A production drop with matching low sunlight is weather, so no truck. Missing data from several sites through one collector is one monitoring issue, not several outages. A mirrored meter doesn't count as independent confirmation.

**Q: How does ranking work?**
A: Priority bands first (safety and deadlines win), then deterministic factors within a band. Every rank has reasons, factor values, unknowns and a policy version, and the weights are explicitly a demo policy. A hazard is never demoted because its cost is unknown.

**Q: Is your crew planner optimal?**
A: It's a "feasible heuristic proposal", not a guaranteed optimum. We compare it honestly with a first-come-first-served baseline under the same constraints; in our scenario it matched the baseline, and we show that. With more jobs and crews the difference grows. An optimisation solver such as OR-Tools could replace the heuristic later.

**Q: What stops two dispatchers from double-booking a crew?**
A: Apply is transactional with revision checks and an idempotency key. A stale plan is rejected (409) and recomputed.

**Q: Where do crew shifts and travel times come from?**
A: In the demo they are labelled synthetic planning inputs. In production they would come from PPC's workforce and work-order systems, never from device telemetry.

### Business and value
**Q: What's in it for PPC?**
A:
- customer retention and engagement (one app for all brands);
- fewer unnecessary truck rolls (weather vs fault, remote first);
- earlier detection (less lost energy, fewer breakdowns);
- grid flexibility through Power Block Offers (shift load to solar surplus, buy export at peak);
- business-account revenue insight;
- a data foundation for PPC's green and efficiency direction.

**Q: How much will it save?**
A: We don't claim a percentage. The prototype shows the mechanism and per-case estimates (e.g. ≈ 2.54 RON per laundry batch). The mentors' "20 % unnecessary visits" is a hypothesis we would measure with PPC data.

**Q: Business model?**
A: Free for PPC customers, as a retention and flexibility tool. Value comes to PPC through O&M efficiency and offers (load shifting and peak export at agreed prices), with a premium business tier (multi-site, demand charges, reports) as in `docs/BUSINESS_ACCOUNT_PLAN.md`.

**Q: How is this different for businesses?**
A: Business accounts get business consumption profiles and examples today. The roadmap adds:
- organisations with team roles and multiple sites;
- demand and peak-power tracking;
- business tariffs with VAT;
- scheduled offers, flexible assets and statements.

### Security, privacy and regulation
**Q: Data protection?**
A:
- Every endpoint checks access server-side: customers see only their own sites, staff only their areas.
- Importing data grants nothing.
- Hashed passwords, CSRF protection, session expiry and login rate limiting.
- No raw device payloads or internal paths in the interface.
- Crew locations and shifts are visible only to authorised staff.
- Support videos are private, checked and need consent.

We don't claim full GDPR compliance from these measures alone; that needs a legal review.

**Q: Prosumer rules?**
A: Contract prices and export compensation follow the customer's own contract settings; we don't invent regulated compensation. Regulatory references (EU Batteries Regulation Art. 14, the Data Act, the Romanian connection norm) are documented as *to verify*, not claimed. PPC's mentors offered guidance on prosumer rules; that's our next validation step.

**Q: Your meters vs PPC's official meter?**
A: Our meters are the customer's *internal operational* meters at the connection point, used as operational evidence. PPC's billing meter is read by PPC through its own systems (DLMS/COSEM). We don't claim our data is billing-grade.

### Technical
**Q: Does it scale?**
A: The engine is streaming and idempotent, imports are immutable snapshots, and queries are bounded and indexed. For real scale we would move from SQLite to a managed database and run collectors per site. The architecture already separates collection, normalisation and decisions.

**Q: Why SQLite?**
A: It's a hackathon prototype on a laptop, with zero infrastructure, WAL mode, migrations and transactions. The design moves to Postgres without changing the API.

**Q: What if the internet fails during the demo?**
A: The app and data run locally. Only map tiles and live weather need internet; the map falls back to markers on a plain background.

**Q: How do you test it?**
A: About 300+ automated tests (use the final count). They cover:
- parsing every source format;
- equivalence across vendors (the same data encoded three ways gives the same values);
- physical consistency;
- every injected defect;
- authority and no double counting;
- daylight-saving and midnight tariff bands;
- planner constraints;
- offer settlement idempotency;
- correlation, ranking, crew-plan feasibility and stale-plan rejection;
- permissions.

### Team and process
**Q: What's your riskiest assumption?**
A: That customers will change *when* they run loads for a few RON, and that O&M's biggest time loss is unnecessary or misrouted visits. We'd test both with PPC mentors and sample data first.

**Q: What would you do next week?**
A:
1. Get PPC sample data from real installations and run it through the same profiles.
2. Interview 5 prosumers and 3 O&M technicians (raw quotes).
3. Measure today's detection delay and visit outcomes as a baseline.
4. Pilot the planner and offers with a few business customers.
5. Legal review of data access and prosumer rules.

---

## 9. Key phrases to remember
- "**Evidence before data**: every field we read is checked against vendor documentation."
- "**Adding a brand is a config file, not new code.**"
- "**Missing data is unknown, never zero.**"
- "**One authoritative source per measurement; mirrors are never summed.**"
- "**Weather is not a fault: no truck for a cloud.**"
- "**Safety first, then deadlines, then money, with every rank explained.**"
- "**Feasible plan, honestly compared, dispatcher applies, no double booking.**"
- "**We advise; we never switch your devices.**"
- "**Estimates are labelled, and we don't claim percentages we haven't measured.**"

## 9a. Known quirks (so nothing surprises you)
- The Home card "Your production forecast" uses **today's live weather**, not the July replay clock. The Daily Forecast and the Plan page use the replay. If asked: "that card is the live public weather forecast; the replay scenario has its own forecast."
- Scene C's F2 mirror check covers a window with ~0 kWh of import, so the "no doubling" proof is the single selected authority (`F2-M2-FEEDIN`), not a visible total.
- Correlated incidents can't be assigned through the old buttons (the app says "Use Plan teams for this incident"). This is deliberate: every correlated job goes through the crew constraints.

## 10. Checklist before going on stage
- [ ] The local database is seeded with the scenario; the frontend is built; the app is running; you've logged in once with each demo account (`laundry-owner`, `scenario-dispatcher`, `scenario-supervisor`, `desk-operator`).
- [ ] The replay clock is set to the Scene A start (17 July 07:30). Rehearse the `scenario advance` commands for Scenes B–D; time only moves forward, so use a fresh database for each rehearsal.
- [ ] All figures in the script are updated from `docs/demo_run_output.txt`.
- [ ] Internet is checked; you know the map fallback.
- [ ] Screenshots of each scene, in case the live demo fails.
- [ ] One person drives the demo and one presents; practise the 5-minute pacing.
