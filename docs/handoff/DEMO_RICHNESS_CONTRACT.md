# Demo richness contract (backend -> frontend)

All data is SYNTHETIC. Everything here is read-only for the UI except where noted. Times are UTC ISO strings;
display them in Europe/Bucharest. "Analytical clock" = the scenario clock (`GET /api/v1/clock`).

## 1. Customer overview: grid import / grid export / consumption for provider sites

`GET /api/v1/sites/{site_id}/energy/overview` (customer with the site grant, or staff with the site in scope).
Client method: `siteEnergyOverview(siteId)`. Type `EnergyOverview`.

```
EnergyOverview {
  site_id, as_of,                 // analytical clock, never later
  clock: "scenario" | "live",
  source: "component_meters" | "provider_frames" | "compact_telemetry" | "none",
  interval_start, interval_end,   // the latest complete 15-minute frame (null when none)
  pv, grid_import, grid_export, consumption: OverviewMetric,       // kW, latest frame
  today: { production, grid_import, grid_export, consumption: OverviewMetric,   // kWh since local midnight up to as_of
           self_consumption_share: number|null }
}
OverviewMetric { value: number|null, unit: "kW"|"kWh", origin: "measured"|"derived"|null,
                 reason: string|null, basis: string|null }
```
- `value` is `null` (and `origin` null, `reason` set) when an input is missing, e.g. `no_grid_meter`, `grid_frame_unknown`,
  `pv_unknown`. Show `reason` text, never a fake 0.
- `consumption.origin` is always `"derived"`: PV AC + grid import - grid export (+ AC battery where the site has one and it is
  declared). Label it "derived". `basis` has a plain-language formula. F1 and H2 now return grid import/export (measured
  PCC / Shelly meters) and derived consumption. Sites without a meter (H1, H3, F3, S*) return grid/consumption `null` with a reason.
- Use this instead of `providerLatest` for the Home cards (PV / Grid import / Grid export / Home or Business consumption).

## 2. Production / consumption history

`GET /api/v1/sites/{site_id}/energy/periods?period=today|week|month|year` (same access). Client: `siteEnergyPeriods(siteId, period)`.

```
EnergyPeriods {
  site_id, period, as_of, timezone: "Europe/Bucharest", resolution: "hour"|"day"|"month",
  start, end,
  buckets: [{ start, end, label, origin: "measured"|"derived"|"synthetic_profile", complete: boolean,
              production_kwh, consumption_kwh, grid_import_kwh, grid_export_kwh   // number|null
            }],
  totals: { production_kwh, consumption_kwh, grid_import_kwh, grid_export_kwh,
            self_consumption_share: number|null, peak_kw: number|null, peak_kw_origin: string|null },
  origin_summary: { measured: n, derived: n, synthetic_profile: n },
  synthetic: boolean,             // true when any bucket is synthetic
  note: string                    // always show; says what is measured and what is a typical-profile estimate
}
```
- `today`: hourly buckets from local midnight to the analytical clock (last bucket `complete:false`). `week`: 7 daily buckets
  ending on the analytical local day. `month`: 30 daily buckets. `year`: 12 monthly buckets.
- Origins: `measured`/`derived` = real scenario data up to the analytical clock (consumption is always derived from
  PV + import - export; the bucket origin is `derived` when any value is derived). `synthetic_profile` = a deterministic
  SEASONAL PROFILE (installed kWp and segment, winter more consumption, summer more production, home evening peak,
  business weekdays 08-18) used for days outside the measured week and for all of `year`. It is NOT measured: label it
  "typical profile (synthetic)" and style it differently (e.g. hatched).
- `peak_kw` (business sites mostly) is the highest hourly/15-min consumption kW in the period.

## 3. Operations richness (no new endpoints)

- The demo DB now also holds the 60-site city demo (Sectors 1-6 + Ilfov) next to the 9 provider sites. They are separate
  populations (ids `s1-01`...`ilfov-10` vs `provider-...`).
- `GET /api/v1/ops/map`: `crews[]` now has a position for every crew (fictional base depot). More incidents (P0-P3,
  assigned, en route, resolved) in all 7 areas. `status_sites` lists both populations.
- `GET /api/v1/ops/revenue` (supervisor): now includes the provider sites (billing estimates from measured meter energy
  or demo profiles) and the compact business accounts.
- Accounts (usernames; passwords only in `D:\ovs-demo\LOGINS.md`): `elena` supervisor + `andrei` dispatcher have ALL 7 areas;
  new **`victor`** = area manager (supervisor, ONLY `ilfov`); city demo accounts (`customer`, `other-customer`,
  `business-customer`, `dispatcher`, `supervisor`, `area-manager`, `technician`, `technician-s1`..`technician-ilfov`) remain.

## 4. Technician and support requests (rule change)

- A technician has NO request inbox. `GET /api/v1/support/requests` for a technician returns ONLY requests that are
  linked to an assignment of one of their crews (the dispatcher creates the assignment on the request's incident;
  `incident.support_request_id`). Unlinked requests are not returned (empty list, never 403); reply and media
  endpoints return 404 for unlinked requests. Dispatcher and supervisor access is unchanged.
- `GET /api/v1/ops/agenda` items (`AgendaItem`) gain: `zone` (address-like location text), `reason` (why: incident
  evidence), `support_request_id`, `media` (`{media_id, filename, content_type, size_bytes}` when the linked request has a video;
  open with `GET /api/v1/support/media/{media_id}`), `window_label` (e.g. "09:00-10:30"). `AgendaView.history` lists
  recently completed items (same shape, last 48 h) for the "done" section. Hide the Requests page for technicians; show
  the linked video inside the agenda item.
- Technician accounts: `mihai` (several upcoming today + completed yesterday + one item with a support video), `ana`, `radu`;
  `ioana` (remote desk) has remote items.

## 5. Contracts and offers

- Contracts: albert keeps time-of-use; maria has a fixed home contract; city customers have contracts too
  (`GET /sites/{id}/contract`).
- Offers: published consume + export offers in `sector-1` and `ilfov` (expiring after the scenario clock) targeting albert, maria
  and the city customers; each scenario customer also has one accepted and settled offer (savings counter + history).

## 6. Learn

- `GET /api/v1/lessons` `reward_note` now states the reward is a credit on the energy bill, not cash.

## 7. CLI

`python -m backend enrich-demo [--force-live]` (idempotent; refuses unless a scenario clock is active; never run on import).
