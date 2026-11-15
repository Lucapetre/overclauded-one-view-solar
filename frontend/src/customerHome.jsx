// Customer Home and History for the connected app, home and business accounts.
// Values come from GET /sites/{id}/energy/overview and /energy/periods (never a fake zero:
// a missing value shows its reason). Consumption is always labelled "derived"; typical
// seasonal profile periods are labelled "synthetic". Business accounts get their own header.
import React, { Suspense, lazy, useMemo, useState } from "react";
import {
  Activity,
  ArrowRight,
  BarChart3,
  BatteryCharging,
  Briefcase,
  Database,
  Gauge,
  House,
  Plug,
  Sun,
  Tag,
  Zap,
} from "lucide-react";
import { SolarApiError } from "../../packages/contracts/client";
import { usePoller } from "./offersShared";
import { EnergyBars, FriendlyEnergy } from "./features";
import { CareCard, ContractAndForecast, useContract } from "./customer";
import { EquipmentCards } from "./equipment";
import { SavingsCounter } from "./offersSavings";
import { errorMessage, sourceInfo, when } from "./telemetry";
import { words } from "./friendly";
import {
  PERIOD_CHOICES,
  businessHeader,
  chartBuckets,
  detailRows,
  fmtNumber,
  newOffer,
  overviewCards,
  profileNote,
} from "./customerView";
import { formatRon } from "./money";

const NextTaskCard = lazy(() => import("./planner").then((m) => ({ default: m.NextTaskCard })));
const clockNudge = (clock) => (clock?.mode === "scenario" ? Date.parse(clock.analytical_now) || 0 : 0);

/** Same request on the client when the typed method is not generated yet. */
const getJson = (api, path, signal) =>
  api.request ? api.request(path, { signal }) : Promise.reject(new Error("request unavailable"));
export const loadOverview = (api, siteId, signal) =>
  api.siteEnergyOverview
    ? api.siteEnergyOverview(siteId, signal)
    : getJson(api, `/api/v1/sites/${encodeURIComponent(siteId)}/energy/overview`, signal);
export const loadPeriods = (api, siteId, period, signal) =>
  api.siteEnergyPeriods
    ? api.siteEnergyPeriods(siteId, period, signal)
    : getJson(api, `/api/v1/sites/${encodeURIComponent(siteId)}/energy/periods?period=${period}`, signal);

export function useOverview(api, siteId, nudge, onError) {
  return usePoller((signal) => loadOverview(api, siteId, signal), { key: `overview:${siteId}`, interval: 15000, nudge, onError });
}
export function usePeriods(api, siteId, period, nudge, onError) {
  return usePoller((signal) => loadPeriods(api, siteId, period, signal), {
    key: `periods:${siteId}:${period}`,
    interval: 60000,
    nudge,
    onError,
  });
}

function Pill({ children, tone = "" }) {
  return <span className={`pill ${tone}`}>{children}</span>;
}

/* ------------------------------------------------------------ metric cards */

const ICONS = [Sun, House, Plug, Zap];
function MetricCards({ overview, accountType, error }) {
  const cards = overviewCards(overview, accountType);
  return (
    <div className="connected-metrics customer-metrics">
      {cards.map((card, index) => {
        const Icon = index === 1 && accountType === "business" ? Briefcase : ICONS[index];
        return (
          <section className="card metric-card" key={card.name}>
            <div className="section-head">
              <Icon size={20} aria-hidden="true" />
              {card.origin && <Pill>{card.origin === "derived" ? "derived" : "measured"}</Pill>}
            </div>
            <h3>{card.name}</h3>
            <div className={`metric-value ${card.value == null ? "missing-value" : ""}`}>
              {card.value == null ? "Unavailable" : card.value} <small>{card.value != null && card.unit}</small>
            </div>
            {card.reason && <small>{error && !overview ? "Could not load this value." : card.reason}</small>}
            {card.value != null && card.basis && card.origin === "derived" && <small>{card.basis}</small>}
          </section>
        );
      })}
    </div>
  );
}

/* ---------------------------------------------------------- business header */

export function BusinessHeader({ api, site, overview, clock, onError, contract, bands }) {
  const today = usePeriods(api, site.site_id, "today", clockNudge(clock), onError);
  const header = useMemo(
    () => businessHeader(today.data, overview, contract, bands),
    [today.data, overview, contract, bands],
  );
  return (
    <section className="card business-header" aria-labelledby="business-header-title">
      <div className="section-head">
        <div>
          <div className="eyebrow">YOUR BUSINESS TODAY · OPENING HOURS</div>
          <h2 id="business-header-title">{site.alias}</h2>
        </div>
        <Pill tone="dark">Business account</Pill>
      </div>
      <div className="business-tiles">
        {header.tiles.map((tile) => (
          <div key={tile.key} className="business-tile">
            <span>{tile.label}</span>
            <b className={tile.value == null ? "missing-value" : ""}>{tile.value ?? "Unavailable"}</b>
            <small>{tile.note}</small>
          </div>
        ))}
      </div>
      <p className="small-note">
        Estimates from measured grid energy and your contract, plus a derived consumption (solar + grid import − grid
        export). {today.error && !today.data ? "Today's figures could not be loaded." : ""}
      </p>
    </section>
  );
}

/* ------------------------------------------------------------ period chart */

export function PeriodChart({ api, site, accountType, clock, onError, title = "Production and consumption", compactTable = false }) {
  const [period, setPeriod] = useState("today");
  const periods = usePeriods(api, site.site_id, period, clockNudge(clock), onError);
  const w = words(accountType);
  const chart = useMemo(() => chartBuckets(periods.data), [periods.data]);
  const spec = PERIOD_CHOICES.find((p) => p.key === period);
  const rows = useMemo(() => detailRows(periods.data), [periods.data]);
  const note = profileNote(chart);
  return (
    <section className="card chart-card">
      <div className="section-head">
        <div>
          <h3>{title}</h3>
          <p>Energy in kWh, {spec.title}.</p>
        </div>
        <div className="period-tabs" role="group" aria-label="Chart period">
          {PERIOD_CHOICES.map((choice) => (
            <button
              key={choice.key}
              className={choice.key === period ? "is-on" : ""}
              aria-pressed={choice.key === period}
              onClick={() => setPeriod(choice.key)}
            >
              {choice.label}
            </button>
          ))}
        </div>
      </div>
      {periods.error && !periods.data ? (
        <div className="empty">
          <p>{errorMessage(periods.error)}</p>
          <button className="text-btn" onClick={periods.refresh}>
            Retry
          </button>
        </div>
      ) : periods.loading ? (
        <div className="empty">Adding up your energy…</div>
      ) : (
        <EnergyBars buckets={chart.buckets} consumptionLabel={`${w.consumption} (derived)`} />
      )}
      <div className="chart-foot">
        <span>
          Solar produced{" "}
          <b>{chart.totals?.production_kwh == null ? "unavailable" : `${fmtNumber(chart.totals.production_kwh)} kWh`}</b>
          {" · "}Used{" "}
          <b>{chart.totals?.consumption_kwh == null ? "unavailable" : `${fmtNumber(chart.totals.consumption_kwh)} kWh`}</b>
        </span>
        {periods.data && <span>Up to {when(periods.data.as_of)}</span>}
      </div>
      {note && (
        <p className="profile-note" role="note">
          <Tag size={13} aria-hidden="true" /> {note}
        </p>
      )}
      {periods.data?.note && <p className="small-note">{periods.data.note}</p>}
      {compactTable && rows.length > 0 && (
        <details className="history-details">
          <summary>Show details</summary>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Period</th>
                  <th>Produced (kWh)</th>
                  <th>Used (kWh)</th>
                  <th>From grid (kWh)</th>
                  <th>Sent to grid (kWh)</th>
                  <th>Data</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.key}>
                    <td>{row.label}{row.partial ? " (so far)" : ""}</td>
                    <td>{fmtNumber(row.production)}</td>
                    <td>{fmtNumber(row.consumption)}</td>
                    <td>{fmtNumber(row.gridImport)}</td>
                    <td>{fmtNumber(row.gridExport)}</td>
                    <td>{row.origin}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </section>
  );
}

/* --------------------------------------------------------------- new offer */

function NewOfferCard({ api, onOpenOffers, onError }) {
  const offers = usePoller((signal) => api.offers(signal), { key: "home-offers", interval: 60000, onError });
  const offer = newOffer(offers.data || []);
  if (!offer) return null;
  const price = Number(offer.offer_price_ron_per_kwh);
  return (
    <section className="card new-offer" aria-label="New offer">
      <Tag size={22} aria-hidden="true" />
      <div>
        <div className="eyebrow">NEW OFFER</div>
        <b>{offer.title || (offer.type === "export" ? "Export offer" : "Consumption offer")}</b>
        <small>
          {offer.energy_kwh} kWh at {Number.isFinite(price) ? `${price.toFixed(2)} RON/kWh` : "a set price"}
          {offer.block_value_bani != null ? ` · block value ${formatRon(offer.block_value_bani)}` : ""}
        </small>
      </div>
      <button className="btn secondary" onClick={onOpenOffers}>
        View offer <ArrowRight size={15} />
      </button>
    </section>
  );
}

/* -------------------------------------------------------------------- home */

function Status({ value }) {
  const names = { fresh: "Recent telemetry", stale: "Stale telemetry", unavailable: "Unavailable" };
  return <Pill tone={value === "fresh" ? "green" : value === "stale" ? "orange" : ""}>{names[value] || String(value).replaceAll("_", " ")}</Pill>;
}

export function CustomerHome({
  api,
  site,
  record,
  accountType,
  clock,
  navigate,
  onError,
  userId,
  showOffers,
  retry,
  scene,
}) {
  const w = words(accountType);
  const business = accountType === "business";
  const nudge = clockNudge(clock);
  const overview = useOverview(api, site.site_id, nudge, onError);
  const todayPeriods = usePeriods(api, site.site_id, "today", nudge, onError);
  const [contractView] = useContract(api, site.site_id, onError);
  const contract = contractView?.contract || null;
  const bands = contractView?.version?.bands || contract?.bands || [];
  const info = sourceInfo(record);
  const cards = overviewCards(overview.data, accountType);
  const [pv, consumption, , exporting] = cards;
  const solarKwh = todayPeriods.data?.totals?.production_kwh ?? null;
  const task = (
    <Suspense fallback={null}>
      <NextTaskCard
        key={site.site_id}
        api={api}
        site={site}
        clock={clock}
        onError={onError}
        onOpenPlan={() => navigate("Plan")}
      />
    </Suspense>
  );
  return (
    <>
      <div className="source-banner">
        <div>
          <Database size={17} />
          <b>
            {info.mode === "synthetic"
              ? "Synthetic replay"
              : info.mode === "replay"
                ? "Recorded replay"
                : info.mode === "live"
                  ? "Live source"
                  : "Connecting source"}
          </b>
          <span>{when(overview.data?.as_of || info.time)}</span>
        </div>
        <Status value={info.status} />
      </div>
      {showOffers && (
        <SavingsCounter api={api} userId={userId} onError={onError} compact onOpenOffers={() => navigate("Offers")} />
      )}
      {business && (
        <BusinessHeader
          api={api}
          site={site}
          overview={overview.data}
          clock={clock}
          onError={onError}
          contract={contract}
          bands={bands}
        />
      )}
      {business && task}
      {showOffers && <NewOfferCard api={api} onOpenOffers={() => navigate("Offers")} onError={onError} />}
      <div className="home-grid">
        <section className="energy-hero">
          <div className="section-head">
            <div>
              <div className="eyebrow">{w.eyebrow}</div>
              <h2>{site.alias}</h2>
            </div>
            <Pill tone="dark">{record?.provider ? record.data?.site.provider || "Provider source" : "Normalized telemetry"}</Pill>
          </div>
          <div className="energy-scene">
            <div className="scene-grid" />
            <div className="scene-sun">
              <Sun size={30} />
              <span>
                Solar production
                <b>
                  {pv.value == null ? "Unavailable" : pv.value} <small>{pv.value != null && pv.unit}</small>
                </b>
              </span>
            </div>
            <div className="flow-track solar-track">
              <i />
              <i />
              <i />
            </div>
            {scene}
            <div className="scene-home">
              {business ? <Briefcase size={22} /> : <House size={22} />}
              <span>
                {w.consumption}
                <b>
                  {consumption.value == null ? "Unavailable" : consumption.value}{" "}
                  <small>{consumption.value != null && `${consumption.unit} · derived`}</small>
                </b>
              </span>
            </div>
            <div className="scene-grid-export">
              <Plug size={23} />
              <span>
                Grid export
                <b>
                  {exporting.value == null ? "Unavailable" : exporting.value}{" "}
                  <small>{exporting.value != null && exporting.unit}</small>
                </b>
              </span>
            </div>
          </div>
          <div className="hero-foot">
            <span>
              {overview.error && !overview.data
                ? "Readings could not be refreshed"
                : overview.data?.source === "none"
                  ? "No meter data yet"
                  : "Latest 15-minute readings; consumption is derived from solar and the grid meter"}
            </span>
            <span>
              <Activity size={14} />
              Refreshes automatically
            </span>
          </div>
        </section>
        <section className="solar-opportunity connected-opportunity">
          <span className="opportunity-icon">
            <BarChart3 size={25} />
          </span>
          <div className="eyebrow">TODAY, IN PLAIN WORDS</div>
          <FriendlyEnergy kwh={solarKwh} subject="Today’s solar energy" accountType={accountType} loading={todayPeriods.loading} />
          <button className="btn dark" onClick={() => navigate("History")}>
            See history <ArrowRight size={17} />
          </button>
          <p className="small-note">Missing data stays unavailable; it is never shown as zero.</p>
        </section>
      </div>
      <MetricCards overview={overview.data} accountType={accountType} error={overview.error} />
      {!business && task}
      <EquipmentCards key={site.site_id} api={api} siteId={site.site_id} onError={onError} nudge={nudge} />
      <div className="lower-grid">
        <PeriodChart api={api} site={site} accountType={accountType} clock={clock} onError={onError} />
        <CareCard
          record={record}
          accountType={accountType}
          onLearn={() => navigate("Learn")}
          onSupport={() => navigate("Support")}
        />
      </div>
      <ContractAndForecast api={api} site={site} accountType={accountType} onError={onError} replay={clock?.mode === "scenario"} />
    </>
  );
}

/* ----------------------------------------------------------------- history */

/** One chart (production vs consumption) and a short table behind "Show details". */
export function SimpleHistory({ api, site, accountType, clock, onError, children }) {
  return (
    <>
      <PeriodChart
        api={api}
        site={site}
        accountType={accountType}
        clock={clock}
        onError={onError}
        title={accountType === "business" ? "How your business used energy" : "How your home used energy"}
        compactTable
      />
      {children}
    </>
  );
}
