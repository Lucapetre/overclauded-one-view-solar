// Shared customer features used by both the connected app and the workflow demo.
import "./features.css";
import React, { useEffect, useId, useState } from "react";
import {
  ArrowRight,
  BookOpen,
  Check,
  CheckCircle2,
  CloudSun,
  Coins,
  FileText,
  House,
  Lightbulb,
  Sun,
  X,
} from "lucide-react";
import { friendlyEnergy } from "./friendly";
import { dailyForecast, LOCATION, MODEL, skyLabel, WEATHER_URL } from "./forecast";
import { estimateDay } from "./dailyForecast";
import {
  bandId,
  bandTime,
  checkBands,
  compensationText,
  daysText,
  localDateTime,
  minuteText,
  parseMinute,
  sortBands,
  validityText,
} from "./planView";

const fmt = (value, digits = 1) =>
  value == null || !Number.isFinite(value)
    ? "—"
    : new Intl.NumberFormat("en-GB", { maximumFractionDigits: digits }).format(
        value,
      );
const money = (value) =>
  value == null || !Number.isFinite(value)
    ? "—"
    : new Intl.NumberFormat("en-GB", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(value);
const SERIES = [
  { key: "production", label: "Solar production", color: "#d6b32d" },
  { key: "consumption", label: "Consumption", color: "#a49bc5" },
];

// Split a series into runs of known values so missing periods break the line.
function runs(points) {
  const out = [];
  let current = [];
  for (const point of points) {
    if (point.value == null || !Number.isFinite(point.value)) {
      if (current.length) out.push(current);
      current = [];
    } else current.push(point);
  }
  if (current.length) out.push(current);
  return out;
}

/**
 * Period energy totals drawn like the "Today" chart: a filled production line and a
 * consumption line on one kWh axis. Missing periods leave a gap, never a zero.
 */
export function EnergyBars({ buckets, consumptionLabel = "Consumption" }) {
  const [hover, setHover] = useState(null);
  const gradient = "energyFill" + useId().replace(/[^A-Za-z0-9_-]/g, "");
  const series = SERIES.filter((item) =>
    buckets.some((bucket) => bucket[item.key] != null),
  );
  if (!series.length)
    return (
      <div className="empty">
        <p>No energy totals are available for this period.</p>
      </div>
    );
  const max = Math.max(
    ...buckets.flatMap((bucket) => series.map((item) => bucket[item.key] ?? 0)),
    0.001,
  );
  const step = 10 ** Math.floor(Math.log10(max));
  const top = Math.ceil(max / step) * step;
  const W = 660,
    left = 45,
    right = 640,
    bottom = 155,
    plotH = 120;
  const n = buckets.length;
  const x = (i) => (n === 1 ? (left + right) / 2 : left + (i * (right - left)) / (n - 1));
  const y = (value) => bottom - (value / top) * plotH;
  const slot = n === 1 ? right - left : (right - left) / (n - 1);
  const every = Math.ceil(n / 7);
  const name = (item) =>
    item.key === "consumption" ? consumptionLabel : item.label;
  const lines = series.map((item) => ({
    item,
    runs: runs(buckets.map((bucket, i) => ({ i, value: bucket[item.key] }))),
  }));
  const pts = (run) => run.map((p) => `${x(p.i)},${y(p.value)}`).join(" ");
  return (
    <>
      <div className="chart-legend">
        {series.map((item) => (
          <span key={item.key}>
            <i style={{ background: item.color }} />
            {name(item)}
          </span>
        ))}
        <span className="forecast-label">Energy in kWh</span>
      </div>
      <div className="chart-wrap">
        <svg
          viewBox={`0 0 ${W} 195`}
          role="img"
          aria-label={`Energy in kWh over ${n} periods, production and consumption`}
          onMouseLeave={() => setHover(null)}
        >
          <defs>
            <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#e8c848" stopOpacity=".25" />
              <stop offset="100%" stopColor="#e8c848" stopOpacity=".01" />
            </linearGradient>
          </defs>
          {[0, 1, 2, 3].map((i) => (
            <g key={i}>
              <line
                x1="40"
                x2={right}
                y1={bottom - (i * plotH) / 3}
                y2={bottom - (i * plotH) / 3}
                stroke="#eceeeb"
                strokeDasharray="3 4"
              />
              <text x="0" y={bottom + 4 - (i * plotH) / 3}>
                {fmt((top * i) / 3, top < 10 ? 1 : 0)}
              </text>
            </g>
          ))}
          {lines.map(({ item, runs: parts }) =>
            parts.map((run, k) => (
              <g key={`${item.key}${k}`}>
                {item.key === "production" && run.length > 1 && (
                  <polygon
                    points={`${x(run[0].i)},${bottom} ${pts(run)} ${x(run.at(-1).i)},${bottom}`}
                    fill={`url(#${gradient})`}
                  />
                )}
                {run.length > 1 ? (
                  <polyline
                    points={pts(run)}
                    fill="none"
                    stroke={item.color}
                    strokeWidth={item.key === "production" ? 2.5 : 2.4}
                    strokeLinejoin="round"
                    strokeLinecap="round"
                  />
                ) : (
                  <circle
                    cx={x(run[0].i)}
                    cy={y(run[0].value)}
                    r="4"
                    fill={item.color}
                  />
                )}
              </g>
            )),
          )}
          {buckets.map((bucket, i) =>
            i === n - 1 || (i % every === 0 && n - 1 - i >= every / 2) ? (
              <text
                key={`label${i}`}
                x={x(i)}
                y="185"
                textAnchor={
                  n > 1 && i === 0 ? "start" : n > 1 && i === n - 1 ? "end" : "middle"
                }
              >
                {bucket.label}
              </text>
            ) : null,
          )}
          {hover != null && (
            <g pointerEvents="none">
              <line
                x1={x(hover)}
                x2={x(hover)}
                y1={bottom - plotH}
                y2={bottom}
                stroke="#c8cdc2"
              />
              {series.map((item) =>
                buckets[hover][item.key] == null ? null : (
                  <circle
                    key={item.key}
                    cx={x(hover)}
                    cy={y(buckets[hover][item.key])}
                    r="4.5"
                    fill={item.color}
                    stroke="#fff"
                    strokeWidth="2"
                  />
                ),
              )}
            </g>
          )}
          {buckets.map((bucket, i) => (
            <rect
              key={`hit${i}`}
              x={x(i) - slot / 2}
              y={bottom - plotH - 10}
              width={slot}
              height={plotH + 10}
              fill="transparent"
              onMouseEnter={() => setHover(i)}
            />
          ))}
        </svg>
        {hover != null && (
          <span className="chart-tooltip">
            {buckets[hover].label}
            {series.map((item) => (
              <React.Fragment key={item.key}>
                {" · "}
                {name(item)}{" "}
                {buckets[hover][item.key] == null
                  ? "unavailable"
                  : `${fmt(buckets[hover][item.key])} kWh`}
              </React.Fragment>
            ))}
          </span>
        )}
      </div>
      <details className="chart-table">
        <summary>Show as table</summary>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Period</th>
                {series.map((item) => (
                  <th key={item.key}>{name(item)} (kWh)</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {buckets.map((bucket, i) => (
                <tr key={bucket.label + i}>
                  <td>{bucket.label}</td>
                  {series.map((item) => (
                    <td key={item.key}>
                      {bucket[item.key] == null
                        ? "Unavailable"
                        : fmt(bucket[item.key])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </>
  );
}

// One shared live-weather request for every forecast card on the page (refreshed after 30 min).
let weatherCache = null;
export function useWeather() {
  const [state, setState] = useState(() =>
    weatherCache?.data ? { weather: weatherCache.data } : {},
  );
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let alive = true;
    if (!weatherCache || Date.now() - weatherCache.at > 30 * 60000) {
      const entry = { at: Date.now() };
      entry.promise = fetch(WEATHER_URL, { credentials: "omit" })
        .then((response) => {
          if (!response.ok) throw Error("weather");
          return response.json();
        })
        .then((data) => {
          entry.data = data;
          return data;
        });
      weatherCache = entry;
    }
    const entry = weatherCache;
    entry.promise
      .then((data) => alive && setState({ weather: data }))
      .catch(() => {
        if (weatherCache === entry) weatherCache = null;
        if (alive) setState({ failed: true });
      });
    return () => {
      alive = false;
    };
  }, [attempt]);
  return {
    ...state,
    retry: () => {
      setState({});
      setAttempt((value) => value + 1);
    },
  };
}

/**
 * Home widget: today's (or tomorrow's) estimated production, consumption and profit.
 * prices = { importPrice, exportPrice } in RON/kWh; shape = 24 hourly consumption weights.
 */
export function DailyForecast({
  kwp,
  dailyConsumption,
  shape,
  prices,
  pricesFromContract,
  consumptionLabel = "Consumption",
  onPlan,
}) {
  const { weather, failed, retry } = useWeather();
  const [index, setIndex] = useState(0);
  const days = dailyForecast(weather, kwp, null);
  const day = days[index];
  const estimate = day
    ? estimateDay(day.hours, dailyConsumption, shape, prices)
    : null;
  const share = estimate ? Math.round(estimate.selfShare * 100) : 0;
  return (
    <section className="solar-opportunity daily-forecast">
      <div className="section-head">
        <span className="opportunity-icon">
          <CloudSun size={21} />
        </span>
        <span className="tiny-label">DAILY FORECAST</span>
        <div className="df-toggle" role="group" aria-label="Forecast day">
          {["Today", "Tomorrow"].map((label, i) => (
            <button
              key={label}
              className={i === index ? "active" : ""}
              aria-pressed={i === index}
              onClick={() => setIndex(i)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      {failed ? (
        <div className="df-state">
          <p>The weather forecast could not be loaded, so there is no estimate right now.</p>
          <button className="text-btn" onClick={retry}>
            Try again
          </button>
        </div>
      ) : !weather ? (
        <div className="df-state">
          <p>Loading today’s weather forecast…</p>
        </div>
      ) : !day || !estimate ? (
        <div className="df-state">
          <p>Not enough forecast data for this day yet.</p>
        </div>
      ) : (
        <>
          <h2>
            {skyLabel(day.cloud)}
            <span>
              {" "}
              · up to {fmt(day.temperatureMax, 0)} °C
            </span>
          </h2>
          <p className="df-meta">
            {day.season} · {day.daylightHours} h of daylight ·{" "}
            {fmt(day.humidity, 0)}% humidity
          </p>
          <div className="df-metrics">
            <div>
              <small>
                <Sun size={14} /> Production
              </small>
              <b>
                {fmt(estimate.production)} <span>kWh</span>
              </b>
            </div>
            <div>
              <small>
                <House size={14} /> {consumptionLabel}
              </small>
              <b>
                {fmt(estimate.consumption)} <span>kWh</span>
              </b>
            </div>
          </div>
          <div
            className="df-cover"
            role="img"
            aria-label={`Solar covers about ${share}% of the day's use`}
          >
            <i style={{ width: `${share}%` }} />
          </div>
          <small className="df-cover-label">
            Solar covers about <b>{share}%</b> of the day’s use ·{" "}
            {fmt(estimate.exported)} kWh exported
          </small>
          <div className="saving">
            <b>{money(estimate.profit)}</b>
            <span>
              RON
              <br />
              estimated profit
            </span>
          </div>
          <p className="df-breakdown">
            {money(estimate.savings)} RON saved on your bill +{" "}
            {money(estimate.exportEarnings)} RON from export
          </p>
          {onPlan && (
            <button className="btn dark full" onClick={onPlan}>
              Plan my energy <ArrowRight size={17} />
            </button>
          )}
          <small>
            {pricesFromContract
              ? "Your contract prices"
              : "Assumed prices · add your contract in Plan"}{" "}
            · Live weather · Estimate
          </small>
        </>
      )}
    </section>
  );
}

/** "Today's export would run a big-screen TV for N hours." */
export function FriendlyEnergy({ kwh, subject, accountType, loading }) {
  const friendly = friendlyEnergy(kwh, accountType);
  return (
    <div className="friendly-energy">
      <span className="friendly-icon">
        <Lightbulb size={20} />
      </span>
      {friendly ? (
        <div>
          <b>
            {subject} would {friendly.headline.text}.
          </b>
          <p>
            That is {fmt(friendly.kwh)} kWh. It could also{" "}
            {friendly.others.map((item) => item.text).join(", or ")}.
          </p>
          <small>
            Rounded, typical appliance figures ({friendly.headline.basis}) for
            illustration.
          </small>
        </div>
      ) : (
        <div>
          <b>
            {loading
              ? "Adding up today's energy…"
              : `${subject} is not available yet.`}
          </b>
          {!loading && (
            <p>We only translate energy we have actually measured.</p>
          )}
        </div>
      )}
    </div>
  );
}

/** Production outlook from live weather: sky, season, humidity and temperature. */
export function ForecastCard({ kwp, kwpAssumed, contract, accountType }) {
  const { weather, failed, retry } = useWeather();
  const prices = contract
    ? {
        importPrice: contract.import_price_ron_kwh,
        exportPrice: contract.export_price_ron_kwh,
      }
    : null;
  const days = dailyForecast(weather, kwp, prices);
  const names = ["Today", "Tomorrow"];
  return (
    <section className="card forecast-card">
      <div className="section-head">
        <div>
          <h3>Your production forecast</h3>
          <p className="muted">
            From the live weather forecast for {LOCATION.name}: sunshine, season,
            temperature and humidity.
          </p>
        </div>
        <CloudSun size={24} />
      </div>
      {failed ? (
        <div className="empty">
          <p>
            The weather service could not be reached, so there is no forecast
            right now.
          </p>
          <button className="text-btn" onClick={retry}>
            Try again
          </button>
        </div>
      ) : !weather ? (
        <div className="empty">Loading the weather forecast…</div>
      ) : (
        <div className="forecast-days">
          {days.map((day, index) => {
            const friendly = friendlyEnergy(day.kwh, accountType);
            return (
              <div className="forecast-day" key={day.date}>
                <small>
                  {names[index] ||
                    new Date(`${day.date}T12:00:00Z`).toLocaleDateString(
                      "en-GB",
                      { weekday: "long" },
                    )}{" "}
                  · {day.season}
                </small>
                <strong>
                  {fmt(day.kwh)} <span>kWh expected</span>
                </strong>
                <p>
                  {skyLabel(day.cloud)} · up to {fmt(day.temperatureMax, 0)} °C ·{" "}
                  {fmt(day.humidity, 0)}% humidity · {day.daylightHours} h of
                  daylight
                </p>
                {friendly && <p>Enough to {friendly.headline.text}.</p>}
                {day.value ? (
                  <p className="forecast-value">
                    Worth about <b>{money(day.value.low)}</b>–
                    <b>{money(day.value.high)} RON</b> on your contract
                  </p>
                ) : (
                  <p className="forecast-value muted">
                    Add your contract to see what this is worth.
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}
      <details>
        <summary>How this forecast is calculated</summary>
        <p>
          Hourly output = installed capacity ({fmt(kwp)} kWp
          {kwpAssumed ? ", assumed until you add yours" : ""}) × forecast
          sunshine ÷ 1000 W/m² × {MODEL.performanceRatio} system efficiency ×
          a temperature factor (−{MODEL.temperatureCoefficient * 100}% per °C of
          panel temperature above 25 °C) × a humidity factor (up to −
          {MODEL.humidityMaxLoss * 100}% in very humid air). Season enters
          through day length and sun height, which the sunshine forecast already
          includes. The money range runs from exporting everything to using
          everything on site.
        </p>
        <p>
          This is an estimate from stated assumptions, not a guarantee. The
          weather forecast is for {LOCATION.name}, not your exact address, and
          is provided by Open-Meteo.
        </p>
      </details>
    </section>
  );
}

const PRICING_LABEL = { fixed: "fixed", time_of_use: "time of use" };
const DAY_LETTERS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** Read-only list of contract time bands (local Europe/Bucharest times). */
export function BandTable({ bands }) {
  const rows = sortBands(bands);
  if (!rows.length) return <p className="muted">No time bands on this contract.</p>;
  return (
    <ul className="band-list" aria-label="Contract time bands">
      {rows.map((band) => (
        <li key={band.band_id}>
          <div>
            <b>{band.label || band.band_id}</b>
            <small>
              {daysText(band.days)} · {bandTime(band)}
              {(band.valid_from || band.valid_to) && ` · ${validityText(band.valid_from, band.valid_to)}`}
            </small>
          </div>
          <span>
            You pay <b>{money(band.import_rate_ron_kwh)}</b> RON/kWh
            <small>export valued {money(band.export_value_ron_kwh)} RON/kWh</small>
          </span>
        </li>
      ))}
    </ul>
  );
}

const bandRow = (band) => ({
  band_id: band.band_id,
  label: band.label || "",
  days: [...band.days],
  start: minuteText(band.start_minute),
  end: minuteText(band.end_minute % 1440),
  import_rate_ron_kwh: String(band.import_rate_ron_kwh),
  export_value_ron_kwh: String(band.export_value_ron_kwh),
  valid_from: band.valid_from || null,
  valid_to: band.valid_to || null,
});
const rowBand = (row) => {
  const start = parseMinute(row.start);
  const endRaw = parseMinute(row.end);
  return {
    band_id: row.band_id,
    label: row.label.trim() || null,
    days: [...row.days].sort((a, b) => a - b),
    start_minute: start == null ? NaN : start % 1440,
    end_minute: endRaw == null ? NaN : endRaw === 0 ? 1440 : endRaw,
    import_rate_ron_kwh: Number(row.import_rate_ron_kwh),
    export_value_ron_kwh: Number(row.export_value_ron_kwh),
    valid_from: row.valid_from,
    valid_to: row.valid_to,
  };
};

function BandEditor({ rows, onChange }) {
  const update = (index, patch) => onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  return (
    <div className="band-editor">
      {rows.map((row, index) => (
        <fieldset key={row.band_id} className="band-row">
          <legend>{row.label || `Band ${index + 1}`}</legend>
          <label>
            Name
            <input value={row.label} maxLength={60} onChange={(event) => update(index, { label: event.target.value })} placeholder="e.g. Night" />
          </label>
          <div className="band-days" role="group" aria-label="Days this band starts">
            {DAY_LETTERS.map((name, i) => {
              const day = i + 1;
              const on = row.days.includes(day);
              return (
                <button
                  type="button"
                  key={name}
                  aria-pressed={on}
                  className={on ? "on" : ""}
                  onClick={() => update(index, { days: on ? row.days.filter((d) => d !== day) : [...row.days, day] })}
                >
                  {name}
                </button>
              );
            })}
          </div>
          <div className="band-fields">
            <label>
              From
              <input type="time" step="900" value={row.start} onChange={(event) => update(index, { start: event.target.value })} />
            </label>
            <label>
              Until
              <input type="time" step="900" value={row.end} onChange={(event) => update(index, { end: event.target.value })} />
            </label>
            <label>
              You pay (RON/kWh)
              <input type="number" min="0.01" max="10" step="0.01" value={row.import_rate_ron_kwh} onChange={(event) => update(index, { import_rate_ron_kwh: event.target.value })} />
            </label>
            <label>
              Export value (RON/kWh)
              <input type="number" min="0" max="10" step="0.01" value={row.export_value_ron_kwh} onChange={(event) => update(index, { export_value_ron_kwh: event.target.value })} />
            </label>
          </div>
          <small className="band-hint">
            {row.end === "00:00"
              ? "Ends at midnight."
              : row.end && row.start && row.end <= row.start
                ? "Ends the next day (crosses midnight)."
                : ""}
          </small>
          <button type="button" className="text-btn" onClick={() => onChange(rows.filter((_, i) => i !== index))} disabled={rows.length === 1}>
            Remove band
          </button>
        </fieldset>
      ))}
      <button
        type="button"
        className="btn secondary"
        onClick={() =>
          onChange([
            ...rows,
            {
              band_id: bandId(`band-${rows.length + 1}`, new Set(rows.map((r) => r.band_id))),
              label: "",
              days: [1, 2, 3, 4, 5],
              start: "",
              end: "",
              import_rate_ron_kwh: "",
              export_value_ron_kwh: "0",
              valid_from: null,
              valid_to: null,
            },
          ])
        }
      >
        Add a band
      </button>
    </div>
  );
}

/**
 * Contract details that drive the money figures. `onSave` resolves or throws.
 * `version` (optional) is the contract version in force, with its effective bands.
 */
export function ContractCard({ contract, version, onSave, readOnly, defaultKwp }) {
  const blank = {
    supplier: "",
    pricing: "fixed",
    import_price_ron_kwh: "",
    export_price_ron_kwh: "",
    installed_kwp: defaultKwp ?? "",
    export_compensation: "unspecified",
    rows: [],
  };
  const toForm = (value) =>
    value
      ? {
          ...blank,
          ...value,
          pricing: value.pricing || "fixed",
          export_compensation: value.export_compensation || "unspecified",
          rows: (value.bands || []).map(bandRow),
        }
      : blank;
  const [form, setForm] = useState(() => toForm(contract));
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!editing) setForm(toForm(contract));
  }, [contract]);
  const timeOfUse = contract?.pricing === "time_of_use";
  const bands = contract?.bands || version?.bands || [];
  async function submit(event) {
    event.preventDefault();
    setError("");
    const body = {
      supplier: form.supplier.trim(),
      pricing: form.pricing,
      import_price_ron_kwh: Number(form.import_price_ron_kwh),
      export_price_ron_kwh: Number(form.export_price_ron_kwh),
      installed_kwp:
        form.installed_kwp === "" || form.installed_kwp == null
          ? null
          : Number(form.installed_kwp),
    };
    // Keep the stated compensation; an older fixed contract keeps its original shape.
    if (contract?.export_compensation || form.export_compensation !== "unspecified")
      body.export_compensation = form.export_compensation;
    if (form.pricing === "time_of_use") {
      const taken = new Set();
      body.bands = form.rows.map((row) => {
        const band = rowBand(row);
        // Existing ids stay stable across versions; new or clashing ones come from the name.
        band.band_id =
          /^[a-z0-9][a-z0-9_-]{0,39}$/.test(row.band_id) && !taken.has(row.band_id)
            ? row.band_id
            : bandId(band.label || row.band_id, taken);
        taken.add(band.band_id);
        return band;
      });
      const check = checkBands(body.bands);
      if (!body.bands.length) check.errors.push("Add at least one band.");
      if (check.errors.length) {
        setError(check.errors.slice(0, 4).join(" "));
        return;
      }
    }
    setBusy(true);
    try {
      await onSave(body);
      setEditing(false);
    } catch (failure) {
      setError(
        failure?.detail?.message || failure?.message || "Could not save.",
      );
    } finally {
      setBusy(false);
    }
  }
  const field = (key, label, props) => (
    <label>
      {label}
      <input
        value={form[key] ?? ""}
        onChange={(event) => setForm({ ...form, [key]: event.target.value })}
        {...props}
      />
    </label>
  );
  const uncovered = form.pricing === "time_of_use" ? checkBands(form.rows.map(rowBand)).uncoveredMinutes : 0;
  return (
    <section className="card contract-card">
      <div className="section-head">
        <div>
          <h3>Your energy contract</h3>
          <p className="muted">
            Your real prices replace assumptions in every estimate.
          </p>
        </div>
        <FileText size={22} />
      </div>
      {!editing ? (
        <>
          {contract ? (
            <>
              <div className="list-row">
                <b>Supplier</b>
                <span>{contract.supplier}</span>
              </div>
              {timeOfUse ? (
                <>
                  <div className="list-row">
                    <b>Pricing</b>
                    <span>Time of use: prices change by time of day (Bucharest time)</span>
                  </div>
                  <BandTable bands={bands} />
                  <div className="list-row">
                    <b>Reference rates</b>
                    <span>
                      {money(contract.import_price_ron_kwh)} / {money(contract.export_price_ron_kwh)} RON/kWh
                      <small>used by Power Block Offers</small>
                    </span>
                  </div>
                </>
              ) : (
                <>
                  <div className="list-row">
                    <b>You pay (import)</b>
                    <span>{money(contract.import_price_ron_kwh)} RON/kWh · fixed</span>
                  </div>
                  <div className="list-row">
                    <b>You receive (export)</b>
                    <span>{money(contract.export_price_ron_kwh)} RON/kWh</span>
                  </div>
                </>
              )}
              {contract.export_compensation && (
                <div className="list-row">
                  <b>Export compensation</b>
                  <span>{compensationText(contract.export_compensation)}</span>
                </div>
              )}
              <div className="list-row">
                <b>Installed solar</b>
                <span>
                  {contract.installed_kwp
                    ? `${fmt(contract.installed_kwp)} kWp`
                    : "Not provided"}
                </span>
              </div>
              {version && (
                <div className="list-row">
                  <b>Version in force</b>
                  <span>
                    Version {version.version_no} ({PRICING_LABEL[version.pricing] || version.pricing}) · from{" "}
                    {localDateTime(version.effective_from)}
                    {version.valid_to ? ` until ${localDateTime(version.valid_to)}` : ""}
                    {version.uncovered_week_minutes > 0 && (
                      <small>
                        {Math.round(version.uncovered_week_minutes / 60)} h a week have no price; estimates there show “unknown”.
                      </small>
                    )}
                  </span>
                </div>
              )}
            </>
          ) : (
            <p className="muted">
              No contract added yet. Add your prices from your supplier
              contract or latest bill.
            </p>
          )}
          {!readOnly && (
            <button className="btn secondary" onClick={() => setEditing(true)}>
              {contract ? "Edit contract" : "Add my contract"}
              <ArrowRight size={16} />
            </button>
          )}
        </>
      ) : (
        <form onSubmit={submit}>
          <div className="form-grid">
            {field("supplier", "Supplier", { required: true, maxLength: 80 })}
            {field("installed_kwp", "Installed solar (kWp)", {
              type: "number",
              min: "0.1",
              max: "1000",
              step: "0.1",
              placeholder: "e.g. 6",
            })}
            <label>
              Pricing
              <select
                value={form.pricing}
                onChange={(event) =>
                  setForm({
                    ...form,
                    pricing: event.target.value,
                    rows:
                      event.target.value === "time_of_use" && !form.rows.length
                        ? [
                            bandRow({
                              band_id: "all-day",
                              label: "All day",
                              days: [1, 2, 3, 4, 5, 6, 7],
                              start_minute: 0,
                              end_minute: 1440,
                              import_rate_ron_kwh: form.import_price_ron_kwh || "",
                              export_value_ron_kwh: form.export_price_ron_kwh || "0",
                            }),
                          ]
                        : form.rows,
                  })
                }
              >
                <option value="fixed">Fixed price</option>
                <option value="time_of_use">Time of use (bands)</option>
              </select>
            </label>
            <label>
              Export compensation
              <select value={form.export_compensation} onChange={(event) => setForm({ ...form, export_compensation: event.target.value })}>
                <option value="unspecified">Not stated</option>
                <option value="payment">Paid to me</option>
                <option value="credit">Credited to my bill</option>
              </select>
            </label>
            {field("import_price_ron_kwh", form.pricing === "fixed" ? "Price you pay (RON/kWh)" : "Reference price you pay (RON/kWh)", {
              required: true,
              type: "number",
              min: "0.01",
              max: "10",
              step: "0.01",
            })}
            {field("export_price_ron_kwh", form.pricing === "fixed" ? "Price you receive (RON/kWh)" : "Reference export price (RON/kWh)", {
              required: true,
              type: "number",
              min: "0",
              max: "10",
              step: "0.01",
            })}
          </div>
          {form.pricing === "time_of_use" && (
            <>
              <p className="small-note">
                Bands use Bucharest local time. An “until” time before the “from” time crosses midnight. Days are the days a band starts.
              </p>
              <BandEditor rows={form.rows} onChange={(rows) => setForm({ ...form, rows })} />
              {uncovered > 0 && (
                <p className="small-note">
                  {Math.round(uncovered / 60)} h a week have no band; estimates for those times will show “unknown”.
                </p>
              )}
            </>
          )}
          <p className="small-note">
            Prices are per kWh, taxes included, as on your bill. Saving creates a new contract version from now on; accepted plans keep the version they used.
          </p>
          {error && <p className="error" role="alert">{error}</p>}
          <div className="button-row">
            <button className="btn yellow" disabled={busy}>
              {busy ? "Saving…" : "Save contract"} <Check size={16} />
            </button>
            <button
              type="button"
              className="text-btn"
              onClick={() => setEditing(false)}
            >
              Cancel
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

/**
 * Short interactive lessons with a mini test and a small reward.
 * `onComplete(lessonId, answers)` resolves to
 * { passed, correct, total, reward_ron, already_completed, total_reward_ron }.
 */
export function LessonDeck({ catalog, onComplete }) {
  const [open, setOpen] = useState(null);
  const lesson = catalog.lessons.find((item) => item.id === open);
  const done = catalog.lessons.filter((item) => item.completed).length;
  return (
    <>
      <div className="learn-intro lesson-wallet">
        <Coins size={30} />
        <span>
          {money(catalog.total_reward_ron)} RON earned
          <small>
            {done} of {catalog.lessons.length} lessons complete · Pass the mini
            test at the end of a lesson to earn its reward. {catalog.reward_note}
          </small>
        </span>
      </div>
      {lesson ? (
        <LessonPlayer
          key={lesson.id}
          lesson={lesson}
          onClose={() => setOpen(null)}
          onComplete={onComplete}
        />
      ) : (
        <div className="learn-grid lesson-deck">
          {catalog.lessons.map((item, index) => (
            <section className="card lesson" key={item.id}>
              <div className={"lesson-art art-" + (index % 3)}>
                {item.completed ? <CheckCircle2 size={64} /> : <Sun size={64} />}
                <span>{String(index + 1).padStart(2, "0")}</span>
              </div>
              <div className="eyebrow">
                {item.minutes} MIN · {item.steps.length} CARDS ·{" "}
                {item.questions.length} QUESTIONS
              </div>
              <h2>{item.title}</h2>
              <p>{item.summary}</p>
              <div className="lesson-reward">
                <Coins size={15} />
                {item.completed
                  ? `${money(item.reward_ron)} RON earned`
                  : `Earn ${money(item.reward_ron)} RON`}
              </div>
              <button
                className={`btn full ${item.completed ? "secondary" : "yellow"}`}
                onClick={() => setOpen(item.id)}
              >
                {item.completed ? "Review lesson" : "Start lesson"}
                <ArrowRight size={17} />
              </button>
            </section>
          ))}
        </div>
      )}
    </>
  );
}

function LessonPlayer({ lesson, onClose, onComplete }) {
  const cards = lesson.steps.length;
  const last = cards + lesson.questions.length;
  const [position, setPosition] = useState(0);
  const [answers, setAnswers] = useState([]);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const question = lesson.questions[position - cards];
  async function finish(all) {
    setBusy(true);
    setError("");
    try {
      setResult(await onComplete(lesson.id, all));
      setPosition(last);
    } catch (failure) {
      setError(
        failure?.detail?.message || failure?.message || "Could not check.",
      );
    } finally {
      setBusy(false);
    }
  }
  function choose(index) {
    const all = [...answers.slice(0, position - cards), index];
    setAnswers(all);
    if (all.length === lesson.questions.length) finish(all);
    else setPosition(position + 1);
  }
  return (
    <section className="card lesson-player">
      <div className="section-head">
        <div className="eyebrow">
          <BookOpen size={14} /> {lesson.title}
        </div>
        <button className="icon-btn" aria-label="Close lesson" onClick={onClose}>
          <X size={18} />
        </button>
      </div>
      <div className="lesson-progress" aria-hidden="true">
        {Array.from({ length: last }, (_, i) => (
          <i key={i} className={i < position || result ? "done" : i === position ? "now" : ""} />
        ))}
      </div>
      {result ? (
        <div className="lesson-result">
          {result.passed ? (
            <>
              <CheckCircle2 size={46} />
              <h2>
                {result.reward_ron > 0
                  ? `+${money(result.reward_ron)} RON earned`
                  : "All correct"}
              </h2>
              <p>
                {result.already_completed
                  ? "You had already earned this lesson's reward."
                  : "Well done. Your reward was added to your learning credit."}{" "}
                Total: {money(result.total_reward_ron)} RON.
              </p>
              <button className="btn yellow" onClick={onClose}>
                Back to lessons <ArrowRight size={16} />
              </button>
            </>
          ) : (
            <>
              <h2>
                {result.correct} of {result.total} correct
              </h2>
              <p>Almost. Read the cards again and retake the mini test.</p>
              <button
                className="btn yellow"
                onClick={() => {
                  setResult(null);
                  setAnswers([]);
                  setPosition(0);
                }}
              >
                Try again <ArrowRight size={16} />
              </button>
            </>
          )}
        </div>
      ) : position < cards ? (
        <div className="lesson-step">
          <small>
            Card {position + 1} of {cards}
          </small>
          <h2>{lesson.steps[position].title}</h2>
          <p>{lesson.steps[position].text}</p>
          {position === cards - 1 && (
            <div className="info-box">{lesson.example}</div>
          )}
          <div className="button-row">
            {position > 0 && (
              <button
                className="btn secondary"
                onClick={() => setPosition(position - 1)}
              >
                Back
              </button>
            )}
            <button
              className="btn yellow"
              onClick={() => setPosition(position + 1)}
            >
              {position === cards - 1 ? "Take the mini test" : "Next"}
              <ArrowRight size={16} />
            </button>
          </div>
        </div>
      ) : (
        <div className="lesson-step">
          <small>
            Question {position - cards + 1} of {lesson.questions.length}
          </small>
          <h2>{question.text}</h2>
          <div className="lesson-options">
            {question.options.map((option, index) => (
              <button
                key={option}
                className="btn secondary full"
                disabled={busy}
                onClick={() => choose(index)}
              >
                {option}
              </button>
            ))}
          </div>
          {busy && <p className="muted">Checking your answers…</p>}
          {error && (
            <p className="error">
              {error}{" "}
              <button className="text-btn" onClick={() => finish(answers)}>
                Retry
              </button>
            </p>
          )}
        </div>
      )}
    </section>
  );
}
