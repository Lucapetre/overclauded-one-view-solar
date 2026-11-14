// Reusable staff (operations) components. They take plain data props and never read
// the demo store, so the connected app can reuse them.
import React, { useEffect, useState } from "react";
import { Building2, CloudSun, Coins, House, MapPin, Users } from "lucide-react";
import "./ops.css";
import { dailyForecast, LOCATION, MODEL, skyLabel, WEATHER_URL } from "./forecast";

const num = (value, digits = 0) =>
  value == null || !Number.isFinite(value)
    ? "—"
    : new Intl.NumberFormat("en-GB", { maximumFractionDigits: digits }).format(
        value,
      );
/** kWh below 1 000, MWh above. Unknown stays a dash, never zero. */
export const energyLabel = (kwh) =>
  kwh == null || !Number.isFinite(kwh)
    ? "—"
    : kwh >= 1000
      ? `${num(kwh / 1000, 2)} MWh`
      : `${num(kwh, kwh < 10 ? 1 : 0)} kWh`;
export const ron = (value) => `${num(value)} RON`;
const pct = (share) => `${num(share * 100, share < 0.1 ? 1 : 0)}%`;
const eet = (iso) =>
  iso
    ? new Date(iso).toLocaleString("en-GB", {
        timeZone: "Europe/Bucharest",
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";
const dayName = (date, index) =>
  ["Today", "Tomorrow"][index] ||
  new Date(`${date}T12:00:00Z`).toLocaleDateString("en-GB", {
    weekday: "long",
  });
const tierTone = (tier) =>
  ["P0", "P1"].includes(tier) ? "orange" : tier === "P2" ? "yellow" : "";

/** Fetches the city weather forecast once per mount (with a retry). */
function useWeather() {
  const [weather, setWeather] = useState(null),
    [failed, setFailed] = useState(false),
    [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setFailed(false);
    fetch(WEATHER_URL, { signal: controller.signal, credentials: "omit" })
      .then((response) => {
        if (!response.ok) throw Error("weather");
        return response.json();
      })
      .then(setWeather)
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [attempt]);
  return { weather, failed, retry: () => setAttempt((n) => n + 1) };
}

/**
 * Fleet production forecast: live city weather × summed installed kWp.
 * areas: [{ name: string, kwp: number, sites: number }]
 */
export function FleetForecast({ areas, title = "Fleet production forecast" }) {
  const { weather, failed, retry } = useWeather();
  const kwp = areas.reduce((sum, a) => sum + (a.kwp || 0), 0);
  const siteCount = areas.reduce((sum, a) => sum + (a.sites || 0), 0);
  const total = dailyForecast(weather, kwp, null).slice(0, 3);
  const rows = areas.map((a) => ({
    ...a,
    days: dailyForecast(weather, a.kwp, null).slice(0, 3),
  }));
  return (
    <section className="card ops-forecast">
      <div className="section-head">
        <div>
          <div className="eyebrow">STAFF · {areas.length > 1 ? "ALL AREAS IN YOUR SCOPE" : `${areas[0]?.name?.toUpperCase() || ""} AREA`}</div>
          <h3>{title}</h3>
          <p>
            {siteCount} sites · {num(kwp, 1)} kWp installed · live weather for{" "}
            {LOCATION.name}
          </p>
        </div>
        <CloudSun size={24} />
      </div>
      {failed ? (
        <div className="empty">
          <p>
            The weather service could not be reached, so there is no fleet
            forecast right now.
          </p>
          <button className="text-btn" onClick={retry}>
            Try again
          </button>
        </div>
      ) : !weather ? (
        <div className="empty">Loading the weather forecast…</div>
      ) : (
        <>
          <div className="forecast-days">
            {total.map((day, index) => (
              <div className="forecast-day" key={day.date}>
                <small>
                  {dayName(day.date, index)} · {day.season}
                </small>
                <strong>
                  {energyLabel(day.kwh)} <span>expected, all sites</span>
                </strong>
                <p>
                  {skyLabel(day.cloud)} · up to {num(day.temperatureMax)} °C ·{" "}
                  {num(day.humidity)}% humidity · {day.daylightHours} h of
                  daylight
                </p>
                <p>
                  Peak about {day.peakKw == null ? "—" : `${num(day.peakKw)} kW`}
                </p>
              </div>
            ))}
          </div>
          <div className="table-wrap">
            <table className="ops-table">
              <thead>
                <tr>
                  <th>Area</th>
                  <th>Sites</th>
                  <th>Installed</th>
                  {total.map((day, index) => (
                    <th key={day.date}>{dayName(day.date, index)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.name}>
                    <td>
                      <b>{row.name}</b>
                    </td>
                    <td>{row.sites}</td>
                    <td>{num(row.kwp, 1)} kWp</td>
                    {row.days.map((day) => (
                      <td key={day.date}>{energyLabel(day.kwh)}</td>
                    ))}
                  </tr>
                ))}
                {rows.length > 1 && (
                  <tr className="ops-total">
                    <td>
                      <b>Total</b>
                    </td>
                    <td>{siteCount}</td>
                    <td>{num(kwp, 1)} kWp</td>
                    {total.map((day) => (
                      <td key={day.date}>
                        <b>{energyLabel(day.kwh)}</b>
                      </td>
                    ))}
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
      <details>
        <summary>How this forecast is calculated</summary>
        <p>
          Hourly output = summed installed capacity of the sites in your scope
          ({num(kwp, 1)} kWp; per area as shown) × forecast sunshine ÷ 1000 W/m²
          × {MODEL.performanceRatio} system efficiency × a temperature factor
          (−{MODEL.temperatureCoefficient * 100}% per °C of panel temperature
          above 25 °C) × a humidity factor (up to −{MODEL.humidityMaxLoss * 100}
          % in very humid air), added up over the day. Season enters through
          day length and sun height, which the sunshine forecast already
          includes.
        </p>
        <p>
          This is an estimate from stated assumptions, not a guarantee or a
          measured value. Every site uses the same city-level weather forecast
          for {LOCATION.name} (from Open-Meteo); roof orientation, shading,
          outages and stale feeds are not modelled. Capacities are synthetic.
        </p>
      </details>
    </section>
  );
}

const SEGMENTS = [
  { key: "business", label: "Business", color: "#2e8a5f", Icon: Building2 },
  { key: "home", label: "Home", color: "#b8920a", Icon: House },
];

/** Two-part share bar with visible labels; hover shows the exact figures. */
function ShareBar({ parts, label }) {
  const [hover, setHover] = useState(null);
  const visible = parts.filter((p) => p.value > 0);
  return (
    <div className="ops-share">
      <div className="ops-share-bar" role="img" aria-label={label}>
        {visible.map((p) => (
          <span
            key={p.key}
            className={"ops-share-seg ops-" + p.key}
            style={{ flexGrow: p.share, background: p.color }}
            onMouseEnter={() => setHover(p)}
            onMouseLeave={() => setHover(null)}
            title={`${p.label}: ${ron(p.value)} · ${pct(p.share)}`}
          />
        ))}
      </div>
      {hover && (
        <span className="ops-tooltip">
          {hover.label}: {ron(hover.value)} per month · {pct(hover.share)} of net
        </span>
      )}
    </div>
  );
}

/**
 * Revenue view for a report from `revenueReport()` in src/revenue.js:
 * { totals, annualNet, bySegment: { business, home }, byArea: [...],
 *   businessAccounts: [...], contractSites, basis? }
 * `basis` (optional) is the server's explanation sentence and replaces the
 * browser's contract-count sentence.
 */
export function RevenueView({ report, scopeLabel = "All areas" }) {
  const { totals, bySegment, byArea, businessAccounts } = report;
  const parts = SEGMENTS.map((s) => ({
    ...s,
    value: bySegment[s.key]?.net || 0,
    share: bySegment[s.key]?.share || 0,
    sites: bySegment[s.key]?.sites || 0,
  }));
  const maxArea = Math.max(1, ...byArea.map((a) => a.net));
  return (
    <>
      <div className="info-box ops-disclaimer">
        <b>Estimate, not invoices.</b>{" "}
        {report.basis ? (
          <>
            {report.basis} Energy sold to the customer + service fees − payments
            for exported solar. No real money or real customers.
          </>
        ) : (
          <>
            Synthetic monthly billing profiles × tariff: energy sold to the
            customer + service fees − payments for exported solar. Saved
            customer contract prices are used where they exist (
            {report.contractSites} of {totals.sites} sites); otherwise the demo
            default tariff. No real money or real customers.
          </>
        )}
      </div>
      <div className="ops-revenue-grid mt">
        <section className="card ops-headline">
          <div className="eyebrow">{scopeLabel.toUpperCase()} · PER MONTH</div>
          <h3>Estimated net revenue</h3>
          <strong>
            {num(totals.net)} <span>RON / month</span>
          </strong>
          <p>
            About {num(report.annualNet)} RON a year at this rate ·{" "}
            {totals.sites} sites
          </p>
          <div className="ops-breakdown">
            <span>
              Energy sales<b>{ron(totals.energySales)}</b>
            </span>
            <span>
              Service fees<b>{ron(totals.serviceFees)}</b>
            </span>
            <span>
              Export payments<b>− {ron(totals.exportPayments)}</b>
            </span>
          </div>
        </section>
        <section className="card">
          <div className="section-head">
            <div>
              <h3>Business vs home</h3>
              <p>Share of estimated monthly net revenue</p>
            </div>
            <Coins size={20} />
          </div>
          <ShareBar
            parts={parts}
            label={parts
              .map((p) => `${p.label} ${pct(p.share)}, ${ron(p.value)}`)
              .join("; ")}
          />
          <div className="ops-share-legend">
            {parts.map(({ key, label, color, Icon, value, share, sites }) => (
              <div key={key}>
                <i style={{ background: color }} aria-hidden="true">
                  <Icon size={12} />
                </i>
                <span>
                  <b>
                    {label} · {pct(share)}
                  </b>
                  <small>
                    {ron(value)} / month · {sites} sites
                  </small>
                </span>
              </div>
            ))}
          </div>
        </section>
      </div>
      <section className="card mt">
        <div className="section-head">
          <div>
            <h3>Revenue by area</h3>
            <p>Estimated monthly net revenue, RON · business and home parts</p>
          </div>
          <MapPin size={18} />
        </div>
        <div className="chart-legend">
          {SEGMENTS.map((s) => (
            <span key={s.key}>
              <i style={{ background: s.color }} />
              {s.label}
            </span>
          ))}
        </div>
        <div className="ops-area-bars">
          {byArea.map((a) => (
            <div className="ops-area-row" key={a.area}>
              <span className="ops-area-name">{a.area}</span>
              <div
                className="ops-area-track"
                role="img"
                aria-label={`${a.area}: ${ron(a.net)}; business ${ron(a.businessNet)}, home ${ron(a.homeNet)}`}
              >
                <span
                  style={{
                    width: `${(100 * Math.max(0, a.businessNet)) / maxArea}%`,
                    background: SEGMENTS[0].color,
                  }}
                  title={`${a.area} business: ${ron(a.businessNet)}`}
                />
                <span
                  style={{
                    width: `${(100 * Math.max(0, a.homeNet)) / maxArea}%`,
                    background: SEGMENTS[1].color,
                  }}
                  title={`${a.area} home: ${ron(a.homeNet)}`}
                />
              </div>
              <span className="ops-area-value">
                <b>{ron(a.net)}</b>
                <small>
                  business {ron(a.businessNet)} · home {ron(a.homeNet)}
                </small>
              </span>
            </div>
          ))}
        </div>
      </section>
      <section className="card mt">
        <div className="section-head">
          <div>
            <h3>Business accounts, ranked by net revenue</h3>
            <p>Per month · synthetic billing profiles</p>
          </div>
          <span className="pill">{businessAccounts.length} accounts</span>
        </div>
        <div className="table-wrap">
          <table className="ops-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Account</th>
                <th>Zone</th>
                <th>Type</th>
                <th>Installed</th>
                <th>Import</th>
                <th>Export</th>
                <th>Net</th>
                <th>Prices</th>
              </tr>
            </thead>
            <tbody>
              {businessAccounts.map((b, index) => (
                <tr key={b.id}>
                  <td>{index + 1}</td>
                  <td>
                    <b>{b.name}</b>
                    <small>
                      {b.id} · {b.area}
                    </small>
                  </td>
                  <td>{b.zone}</td>
                  <td>{b.businessType || "—"}</td>
                  <td>{num(b.kwp)} kWp</td>
                  <td>{num(b.importKwh)} kWh</td>
                  <td>{num(b.exportKwh)} kWh</td>
                  <td>
                    <b>{ron(b.net)}</b>
                  </td>
                  <td>
                    <span className={"pill " + (b.priceSource === "contract" ? "green" : "")}>
                      {b.priceSource === "contract" ? "Contract" : "Default tariff"}
                    </span>
                    <small>
                      {b.importPrice.toFixed(2)} / {b.exportPrice.toFixed(2)} RON/kWh
                    </small>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!businessAccounts.length && (
          <div className="empty">No business accounts in this scope.</div>
        )}
      </section>
    </>
  );
}

/**
 * Assignment report by incident.
 * rows: [{ id, incident, incidentLabel?, title, tier, site, siteName, area, crew|null,
 *          kind: "dispatch"|"meeting"|null, status, assignedBy|null,
 *          assignedAt (ISO)|null, slot ("YYYY-MM-DD HH:MM–HH:MM")|null }]
 * onOpen(incidentId) is optional.
 */
export function AssignmentReport({ rows, onOpen }) {
  if (!rows.length)
    return <div className="empty">No incidents or assignments in this scope.</div>;
  return (
    <div className="table-wrap">
      <table className="ops-table ops-report">
        <thead>
          <tr>
            <th>Incident</th>
            <th>Site</th>
            <th>Area</th>
            <th>Crew</th>
            <th>Kind</th>
            <th>Status</th>
            <th>Assigned by</th>
            <th>When (EET)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.id}
              onClick={onOpen ? () => onOpen(r.incident) : undefined}
              className={onOpen ? "clickable" : ""}
            >
              <td>
                <div className="case-cell">
                  <span className={"pill " + tierTone(r.tier)}>{r.tier}</span>
                  <div>
                    <b>{r.incidentLabel || r.incident}</b>
                    <small>{r.title}</small>
                  </div>
                </div>
              </td>
              <td>
                {r.siteName}
                <small>{r.site}</small>
              </td>
              <td>{r.area}</td>
              <td>{r.crew || "—"}</td>
              <td>
                {r.kind === "meeting"
                  ? "Meeting"
                  : r.kind === "dispatch"
                    ? "Dispatch"
                    : "—"}
              </td>
              <td>
                <span
                  className={
                    "pill " +
                    (r.status === "Not assigned"
                      ? "orange"
                      : ["Completed"].includes(r.status)
                        ? "green"
                        : r.status === "Cancelled"
                          ? ""
                          : "yellow")
                  }
                >
                  {r.status}
                </span>
              </td>
              <td>{r.assignedBy || "—"}</td>
              <td>
                {r.slot ? (
                  <>
                    {r.slot}
                    <small>booked {eet(r.assignedAt)}</small>
                  </>
                ) : (
                  eet(r.assignedAt)
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Per-crew summary cards.
 * crews: [{ name, area, owner (optional), shift, skills: [], members: [], available,
 *           busyWith: { incident, status }|null, meetings: number,
 *           open: { P0, P1, P2, P3 }, completed: { P0, P1, P2, P3 } }]
 */
export function CrewSummary({ crews }) {
  const tiers = ["P0", "P1", "P2", "P3"];
  return (
    <div className="ops-crews">
      {crews.map((c) => (
        <section className="card crew-card" key={c.name}>
          <div className="section-head">
            <span className="crew-icon">
              <Users size={24} />
            </span>
            <span className={"pill " + (c.available ? "green" : "orange")}>
              {c.available
                ? "✓ Available"
                : `● Busy · ${c.busyWith.status} · ${c.busyWith.incident}`}
            </span>
          </div>
          <h2>{c.name}</h2>
          <p>
            {c.area} area{c.owner ? ` · ${c.owner}` : ""} · {c.shift} EET
          </p>
          <div className="ops-members">
            {c.members.map((m) => (
              <span key={m}>{m}</span>
            ))}
          </div>
          <table className="ops-tier-table">
            <thead>
              <tr>
                <th />
                {tiers.map((t) => (
                  <th key={t}>{t}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Open</td>
                {tiers.map((t) => (
                  <td key={t}>{c.open[t]}</td>
                ))}
              </tr>
              <tr>
                <td>Completed</td>
                {tiers.map((t) => (
                  <td key={t}>{c.completed[t]}</td>
                ))}
              </tr>
            </tbody>
          </table>
          <small className="ops-crew-foot">
            {c.meetings} customer meeting{c.meetings === 1 ? "" : "s"} booked ·
            covers {c.skills.join(", ")}
          </small>
        </section>
      ))}
    </div>
  );
}
