// Shared customer features used by both the connected app and the workflow demo.
import "./features.css";
import React, { useEffect, useState } from "react";
import {
  ArrowRight,
  BookOpen,
  Check,
  CheckCircle2,
  CloudSun,
  Coins,
  FileText,
  Lightbulb,
  Sun,
  X,
} from "lucide-react";
import { friendlyEnergy } from "./friendly";
import { dailyForecast, LOCATION, MODEL, skyLabel, WEATHER_URL } from "./forecast";

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
  { key: "production", label: "Solar production", color: "#c9a30f" },
  { key: "consumption", label: "Consumption", color: "#7d70b8" },
];

/** Grouped bars on one kWh axis. Missing buckets draw no bar. */
export function EnergyBars({ buckets, consumptionLabel = "Consumption" }) {
  const [hover, setHover] = useState(null);
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
    H = 195,
    left = 44,
    bottom = 158,
    plotH = 138;
  const slot = (W - left - 12) / buckets.length;
  const barW = Math.max(2, Math.min(14, (slot - 4) / series.length - 2));
  const every = Math.ceil(buckets.length / 8);
  const name = (item) =>
    item.key === "consumption" ? consumptionLabel : item.label;
  return (
    <>
      <div className="chart-legend">
        {series.map((item) => (
          <span key={item.key}>
            <i style={{ background: item.color }} />
            {name(item)}
          </span>
        ))}
        <span className="forecast-label">kWh per bar</span>
      </div>
      <div className="chart-wrap">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label={`Energy in kWh for ${buckets.length} periods`}
        >
          {[0, 0.5, 1].map((f) => (
            <g key={f}>
              <line
                x1={left}
                x2={W - 8}
                y1={bottom - f * plotH}
                y2={bottom - f * plotH}
                stroke="#eceeeb"
                strokeDasharray={f ? "3 4" : undefined}
              />
              <text x="0" y={bottom + 4 - f * plotH}>
                {fmt(top * f, top < 10 ? 1 : 0)}
              </text>
            </g>
          ))}
          {buckets.map((bucket, i) => {
            const x0 =
              left + i * slot + (slot - series.length * (barW + 2) + 2) / 2;
            return (
              <g key={bucket.label + i}>
                {series.map((item, j) => {
                  const value = bucket[item.key];
                  if (value == null) return null;
                  const h = Math.max(1, (value / top) * plotH);
                  const r = Math.min(4, barW / 2, h);
                  const x = x0 + j * (barW + 2),
                    y = bottom - h;
                  return (
                    <path
                      key={item.key}
                      fill={item.color}
                      d={`M${x} ${bottom}V${y + r}Q${x} ${y} ${x + r} ${y}H${x + barW - r}Q${x + barW} ${y} ${x + barW} ${y + r}V${bottom}Z`}
                    />
                  );
                })}
                {i % every === 0 && (
                  <text x={left + i * slot + slot / 2} y="180" textAnchor="middle">
                    {bucket.label}
                  </text>
                )}
                <rect
                  x={left + i * slot}
                  y="10"
                  width={slot}
                  height={bottom - 10}
                  fill="transparent"
                  onMouseEnter={() => setHover(bucket)}
                  onMouseLeave={() => setHover(null)}
                />
              </g>
            );
          })}
        </svg>
        {hover && (
          <span className="chart-tooltip">
            {hover.label}
            {series.map((item) => (
              <React.Fragment key={item.key}>
                {" · "}
                {name(item)}{" "}
                {hover[item.key] == null
                  ? "unavailable"
                  : `${fmt(hover[item.key])} kWh`}
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
  const [weather, setWeather] = useState(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
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
          <button className="text-btn" onClick={() => setAttempt(attempt + 1)}>
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

/** Contract details that drive the money figures. `onSave` resolves or throws. */
export function ContractCard({ contract, onSave, readOnly, defaultKwp }) {
  const blank = {
    supplier: "",
    import_price_ron_kwh: "",
    export_price_ron_kwh: "",
    installed_kwp: defaultKwp ?? "",
  };
  const [form, setForm] = useState(contract || blank);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!editing) setForm(contract || blank);
  }, [contract]);
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await onSave({
        supplier: form.supplier.trim(),
        pricing: "fixed",
        import_price_ron_kwh: Number(form.import_price_ron_kwh),
        export_price_ron_kwh: Number(form.export_price_ron_kwh),
        installed_kwp:
          form.installed_kwp === "" || form.installed_kwp == null
            ? null
            : Number(form.installed_kwp),
      });
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
              <div className="list-row">
                <b>You pay (import)</b>
                <span>{money(contract.import_price_ron_kwh)} RON/kWh · fixed</span>
              </div>
              <div className="list-row">
                <b>You receive (export)</b>
                <span>{money(contract.export_price_ron_kwh)} RON/kWh</span>
              </div>
              <div className="list-row">
                <b>Installed solar</b>
                <span>
                  {contract.installed_kwp
                    ? `${fmt(contract.installed_kwp)} kWp`
                    : "Not provided"}
                </span>
              </div>
            </>
          ) : (
            <p className="muted">
              No contract added yet. Add your fixed prices from your supplier
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
            {field("import_price_ron_kwh", "Price you pay (RON/kWh)", {
              required: true,
              type: "number",
              min: "0.01",
              max: "10",
              step: "0.01",
            })}
            {field("export_price_ron_kwh", "Price you receive (RON/kWh)", {
              required: true,
              type: "number",
              min: "0",
              max: "10",
              step: "0.01",
            })}
          </div>
          <p className="small-note">
            Fixed-price contracts only for now. Prices are per kWh, taxes
            included, as on your bill.
          </p>
          {error && <p className="error">{error}</p>}
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
