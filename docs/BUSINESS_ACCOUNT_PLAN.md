# Business accounts: plan

Status: proposal for the team. Nothing here is built yet unless marked **(exists)**.

## 1. Where we are today

A business customer is a normal customer with `account_type = "business"`. The differences are cosmetic:

- wording ("Business consumption", "Looking after your business") **(exists)**
- appliance equivalents (display fridge, oven, dishwasher) instead of TV and laundry **(exists)**
- a daytime or industrial consumption shape in the Daily Forecast (demo) **(exists)**
- managers see business revenue separately and rank business accounts **(exists)**

Everything else is the same: one site per login, a home-style tariff, the same alerts, the same support, the same offers. A restaurant owner, a factory energy manager and a family see the same product.

## 2. Who we are designing for

| Persona | Example sites | What they care about |
| --- | --- | --- |
| Hospitality owner | Restaurant, café, bar, small hotel | Monthly bill, opening hours, kitchen and refrigeration load, quick help when something fails during service |
| Retail and office manager | Shop, supermarket, office park | Daytime load matching solar, HVAC, peak demand, several sites |
| Industrial / logistics energy manager | Factory, warehouse, cold storage, data centre | Peak kW and capacity charges, night baseload, shift patterns, flexibility revenue, reports for finance and ESG |
| Chain or portfolio owner | Several restaurants or warehouses | One view across sites, comparison between sites, who in the company may see or change what |

## 3. The changes, by theme

### 3.1 Organisation and team (foundation)

- **Organisation** record: name, fictional fiscal code (CUI), billing address, business type, size band.
- **Several sites per organisation**, with a portfolio view and a site switcher.
- **Several users per organisation** with roles:
  - owner (everything, billing, users)
  - energy manager (offers, planning, alerts)
  - site manager (one or more sites)
  - accountant (invoices and reports, read-only)
  - viewer
- Invitations by link or code, plus an access log ("who accepted this offer").
- Server-side scoping as today: a user sees only the organisation's sites they are granted.

### 3.2 Tariffs and contracts that look like a business bill

- **Multi-rate tariffs**: day/night or peak/off-peak bands, prices without VAT, and VAT shown separately.
- **Contracted power (kW) and demand charges**: track monthly peak kW against the contracted level and warn before it is exceeded.
- **Reactive energy / power factor** line for larger sites (flag only, if the meter provides it).
- **Prosumer regime** per site (compensation vs sale of surplus). The rules depend on installed power, so they need checking with a regulatory source before any claims.
- One contract per site, with history (valid from/to) so past savings keep the prices that applied then.

### 3.3 Business energy insights

- **Load profile by hour and weekday**, compared with opening hours or shifts that the user enters.
- **Night and weekend baseload**: "Your Old Town Bistro uses 3.1 kW at 03:00. Refrigeration usually explains about 1.5 kW."
- **Peak demand tracker**: today's and this month's peak kW, when it happened, and distance to the contracted limit.
- **Self-consumption and coverage**: how much of the business's use solar covered, by day and month.
- **Benchmarks**: kWh per m², per seat/cover (hospitality) or per shift (industry), compared with the organisation's own sites (no external benchmark claims).
- **Portfolio comparison**: sites ranked by cost, self-consumption and anomalies.

### 3.4 Money: cost, savings and reports

- Monthly **cost breakdown**: energy, demand, fees and VAT, with solar savings and offer earnings (from the existing settlement ledger).
- **Installation ROI**: investment, savings to date, estimated payback date (an estimate with stated assumptions).
- **CO₂ report** for ESG: avoided emissions from solar using a stated grid emission factor.
- **Exports** for accounting: CSV and PDF monthly statement per site and per organisation.

### 3.5 Power Block Offers for businesses

This builds on the shipped offers feature.

- **Scheduled windows**: accept now for a future slot (for example 13:00–15:00 tomorrow) instead of "starting now". Businesses plan around service hours and shifts.
- **Larger blocks and tiered prices** sized to the site: offers targeted by business type and installed kWp (targeting by kWp exists).
- **Flexible assets** registered per site: oven pre-heat, refrigeration pre-cool, HVAC, EV fleet, battery. The planner suggests which asset can deliver a block.
- **Auto-accept rules** (opt-in, editable, always visible): "accept consume offers ≤ 0.50 RON/kWh between 11:00 and 16:00, up to 50 kWh/day". Penalty terms stay explicit, and every automatic acceptance is notified and logged.
- **Portfolio offers**: one offer delivered across several sites of the same organisation, attributed per site.
- Settlement lines on the monthly statement instead of separate small amounts.

### 3.6 Planning for business tasks

- Business task library: dishwasher cycles, pre-cooling cold rooms, kiln or oven pre-heat, compressor runs, EV fleet charging.
- Weekly schedule aware of opening hours, shifts and the Daily Forecast; suggestions to move flexible load into solar hours.
- Respect hard constraints such as minimum and maximum temperature for refrigeration. The app gives advice and never controls devices (no device write interface, as now).

### 3.7 Alerts that matter to a business

- Inverter offline or production drop **during opening hours**, with higher priority than for a home.
- Approaching contracted power or a new monthly peak.
- Unusual baseload (for example a cold room door left open overnight shows as a load step).
- Offer deadlines (reminders exist) and daily summary emails for owners. Email needs a provider; in-app notifications exist.

### 3.8 Support and service level

- **Priority SLA** by business tier: response targets shown to the customer and tracked by dispatch.
- **Technician appointments outside opening hours** (meeting booking exists; add opening-hours awareness).
- **Named account manager** for larger sites, and requests that can affect several sites.
- Business request types: "production loss during service", "contracted power exceeded", "invoice dispute", "add a site".

### 3.9 Distributor-side (managers)

- **Key accounts view**: business sites by revenue, flexibility delivered, open incidents and SLA status (revenue by business segment exists).
- Offer targeting by business type, opening hours and registered flexible assets.
- Flexibility capacity map: kW that business sites can shift, by sector, for grid events (fits the incident-linked offers and the sector map).

### 3.10 Business UI

- **Business Home**: portfolio header (sites, today's cost, peak kW, self-consumption, CO₂), a site switcher, the Daily Forecast with business consumption, and today's offers and planned tasks.
- Pages: **Home · Sites · Energy · Costs & Reports · Offers · Planning · Team · Support · Learn**. Homes keep today's simpler menu.
- Business lessons: demand charges, power factor, shifting refrigeration, reading a business bill.

## 4. Data model and API (backend)

New tables (one migration):

- `organisations(org_id, name, fiscal_code, business_type, size_band, created_at)`
- `org_members(org_id, user_id, role)`
- `org_sites(org_id, site_id)`
- `invitations(code_hash, org_id, role, site_scope, expires_at, used_at)`
- `site_business_profile(site_id, opening_hours_json, shifts_json, contracted_power_kw, floor_area_m2, seats, business_type)`
- `tariff_bands(contract_id, band, price_ron_kwh, from_minute, to_minute, days)`
- `contracts`: add `valid_from`, `valid_to`, `vat_rate`, `prices_include_vat`, `demand_charge_ron_kw`, `contracted_power_kw`, `prosumer_regime`
- `flex_assets(asset_id, site_id, kind, max_kw, min_minutes, constraints_json)`
- `auto_accept_rules(rule_id, org_id, site_id, offer_type, max_price, window_json, daily_kwh_cap, enabled, created_by)`
- `peaks(site_id, month, peak_kw, at)` (or computed from telemetry)

API (all scoped by organisation membership and role):

- `GET /api/v1/org`
- `GET/POST /api/v1/org/members`
- `POST /api/v1/org/invitations`
- `GET /api/v1/org/sites`
- `GET /api/v1/org/portfolio?period=`
- `GET /api/v1/sites/{id}/load-profile?from&to`
- `GET /api/v1/sites/{id}/peaks`
- `GET /api/v1/org/statements?month=`, with CSV and PDF export
- `GET/POST /api/v1/sites/{id}/business-profile`
- `GET/POST /api/v1/sites/{id}/flex-assets`
- `GET/POST /api/v1/org/auto-accept-rules`
- Offers: `scheduled_start` on accept, and portfolio acceptance

Authorisation: replace the single `account_type` check with organisation roles. Keep `account_type` as the switch between the home and business experience.

## 5. Phasing

| Phase | Scope | Size |
| --- | --- | --- |
| **A. Demo-ready business (hackathon)** | Business Home with portfolio header (cost today, peak kW, self-consumption, CO₂); opening hours on the business profile; load-profile chart with baseload callout; peak tracker vs contracted power; business request types; seed two organisations: a restaurant chain with 3 Old Town and Dorobanți sites, and a logistics company with 2 Ilfov warehouses | M |
| **B. Business money** | Multi-rate and VAT contracts with history; monthly statement with CSV export; ROI and CO₂ report | M |
| **C. Team and portfolio** | Organisations, roles, invitations, site switcher, portfolio comparison | L |
| **D. Business flexibility** | Scheduled offer windows, flexible assets, auto-accept rules (opt-in, visible, logged), portfolio offers, flexibility map for managers | L |
| **E. Service level** | SLA tiers, opening-hours-aware appointments, account manager, multi-site requests | M |

Recommended for the hackathon: **Phase A** plus scheduled offer windows from Phase D. Those make the business account visibly different in a demo without the full organisation model.

## 6. Tests to add

- Organisation scoping: a member never sees another organisation's sites, and roles limit actions (accountant cannot accept offers).
- Tariff bands and VAT: statement totals with known inputs; history keeps old prices.
- Peak tracking and contracted-power warnings with crafted telemetry.
- Auto-accept: rule limits respected, penalties shown, every automatic acceptance logged and notified, rule edits audited.
- Scheduled offer windows: settlement attributes only the scheduled slot.

## 7. Open questions

1. Should a business login see several sites from day one, or is one site per login enough for the hackathon?
2. Which business types matter most for the demo: hospitality (Old Town), industrial and logistics (Ilfov), or both?
3. Are demand charges and power factor in scope? They make the product feel professional but need realistic synthetic meter data (peak kW, reactive energy).
4. Auto-accept rules are powerful but risky for trust. Do we show them, or keep acceptance always manual?
5. Do statements need PDF, or is CSV enough for now?
6. Prosumer regime rules (compensation vs sale, power thresholds) need a source we can cite before showing anything regulatory.
