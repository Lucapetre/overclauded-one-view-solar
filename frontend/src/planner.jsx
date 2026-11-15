// Business task planner for the connected customer workspace: task list, task form,
// the recommendation card (also used compactly on Home), acceptance as an immutable
// commitment, explicit review/release and measured progress. Every cost is a backend
// estimate; nothing here schedules or switches equipment.
import React, { useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  BatteryCharging,
  CalendarClock,
  Check,
  CheckCircle2,
  Clock3,
  Gauge,
  Lock,
  Pencil,
  Plus,
  Sun,
  Trash2,
  X,
} from "lucide-react";
import { OfferDialog, newIdempotencyKey, usePoller } from "./offersShared";
import { ContractCard } from "./features";
import { useContract } from "./customer";
import {
  TASK_KINDS,
  bandsUsed,
  compensationText,
  batteryView,
  confidence,
  constraintText,
  costText,
  coverageText,
  differenceText,
  durationText,
  evidenceCounts,
  forecastLines,
  formDuration,
  freshnessRow,
  kindLabel,
  localDateTime,
  localTime,
  nextTask,
  planErrorText,
  planHeadline,
  reasonText,
  ron,
  slotText,
  splitReasons,
  taskBody,
  taskForm,
  taskState,
  versionLabel,
} from "./planView";
import "./planner.css";

const addMinutes = (iso, minutes) => new Date(Date.parse(iso) + minutes * 60000).toISOString();
const clockNudge = (clock) => (clock?.mode === "scenario" ? Date.parse(clock.analytical_now) || 0 : 0);

function Pill({ tone = "", children }) {
  return <span className={`pill ${tone}`}>{children}</span>;
}

function Notice({ error, text, onRetry, tone = "error" }) {
  if (!error && !text) return null;
  return (
    <div role={tone === "error" ? "alert" : "status"} className={`connected-error plan-notice ${tone}`}>
      <AlertTriangle size={18} aria-hidden="true" />
      <div>
        <b>{text || planErrorText(error)}</b>
        {error?.detail?.request_id && <small>Request {error.detail.request_id}</small>}
      </div>
      {onRetry && (
        <button className="text-btn" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

function usePlan(api, siteId, task, nudge, onError) {
  const active = task && task.status !== "cancelled";
  return usePoller(
    (signal) => (active ? api.plan(siteId, task.task_id, signal) : Promise.resolve(null)),
    { key: `${siteId}:${task?.task_id}:${task?.revision}:${task?.status}`, interval: 60000, nudge, onError },
  );
}

/* ------------------------------------------------------------------ dialogs */

function AcceptDialog({ api, siteId, task, decision, onClose, onAccepted, onChanged }) {
  // One key per opened confirmation; a retry from this dialog reuses it.
  const [key] = useState(newIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const options = [];
  if (decision.recommended_start)
    options.push({
      id: "recommended",
      start: decision.recommended_start,
      end: decision.recommended_end,
      cost: decision.estimated_cost_ron,
      range: decision.cost_range,
      label: "Recommended time",
    });
  const baseline = decision.candidates?.find(
    (c) => c.start === decision.baseline_start && c.start !== decision.recommended_start,
  );
  if (baseline && Date.parse(baseline.start) >= Date.parse(decision.decided_at))
    options.push({
      id: "baseline",
      start: baseline.start,
      end: baseline.end,
      cost: baseline.estimated_cost_ron,
      range: baseline.cost_range,
      label: decision.baseline_kind === "usual_time" ? "My usual time" : "Run now",
    });
  const [choice, setChoice] = useState(options[0]?.id);
  const chosen = options.find((option) => option.id === choice);
  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const body = { recommendation_revision: decision.recommendation_revision };
      if (chosen.id !== "recommended") body.start = chosen.start;
      const result = await api.acceptTask(siteId, task.task_id, body, key);
      onAccepted(result);
    } catch (failure) {
      if (failure?.detail?.code === "recommendation_changed") {
        onChanged(failure);
        return;
      }
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  return (
    <OfferDialog title="Accept this plan?" onClose={onClose} busy={busy}>
      <p className="plan-dialog-lead">
        <b>{task.label}</b> · {task.power_kw} kW for {durationText(task.duration_minutes)} in one go.
      </p>
      <fieldset className="plan-options">
        <legend>Choose the time you commit to</legend>
        {options.map((option) => (
          <label key={option.id} className={`plan-option ${choice === option.id ? "selected" : ""}`}>
            <input
              type="radio"
              name="plan-start"
              value={option.id}
              checked={choice === option.id}
              onChange={() => setChoice(option.id)}
            />
            <span>
              <b>{option.label}</b>
              <span>{slotText(option.start, option.end)}</span>
              <small>Estimated cost of this run: {costText(option.cost, option.range)}</small>
            </span>
          </label>
        ))}
      </fieldset>
      <ul className="plan-dialog-notes">
        <li>Accepting records your commitment with today's estimate. It does not switch anything on: start the task yourself at the agreed time.</li>
        <li>The accepted time and estimate stay fixed. If new evidence changes the recommendation, we show it and you decide.</li>
        <li>Costs are estimates from your contract bands and the solar forecast, not a bill.</li>
      </ul>
      <Notice error={error} />
      <div className="button-row">
        <button className="btn yellow" onClick={submit} disabled={busy || !chosen}>
          {busy ? "Accepting…" : error ? "Try again" : "Accept this time"} <Check size={16} />
        </button>
        <button className="text-btn" onClick={onClose} disabled={busy}>
          Not now
        </button>
      </div>
    </OfferDialog>
  );
}

function ReleaseDialog({ api, siteId, task, onClose, onReleased }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onReleased(await api.reviewTask(siteId, task.task_id, { action: "release", reason: reason.trim() }));
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  return (
    <OfferDialog title="Review and release this plan?" onClose={onClose} busy={busy}>
      <form onSubmit={submit}>
        <p className="plan-dialog-lead">
          Releasing ends your commitment for {slotText(task.commitment.start, task.commitment.end)}. The task goes back to a
          suggestion and gets a fresh recommendation. The original acceptance stays on record.
        </p>
        <label>
          Why are you releasing it?
          <textarea
            required
            maxLength={200}
            rows={3}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="e.g. Battery limited today; I prefer the new time"
          />
        </label>
        <Notice error={error} />
        <div className="button-row">
          <button className="btn dark" disabled={busy || !reason.trim()}>
            {busy ? "Releasing…" : "Release plan"}
          </button>
          <button type="button" className="text-btn" onClick={onClose} disabled={busy}>
            Keep my plan
          </button>
        </div>
      </form>
    </OfferDialog>
  );
}

function CancelDialog({ api, siteId, task, onClose, onCancelled }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  async function submit() {
    setBusy(true);
    setError(null);
    try {
      onCancelled(await api.cancelTask(siteId, task.task_id));
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  return (
    <OfferDialog title="Cancel this task?" onClose={onClose} busy={busy}>
      <p className="plan-dialog-lead">“{task.label}” will no longer get recommendations.</p>
      <Notice error={error} />
      <div className="button-row">
        <button className="btn dark" onClick={submit} disabled={busy}>
          {busy ? "Cancelling…" : "Cancel task"}
        </button>
        <button className="text-btn" onClick={onClose} disabled={busy}>
          Keep it
        </button>
      </div>
    </OfferDialog>
  );
}

/* ------------------------------------------------------------------ recommendation */

function Compare({ decision, task }) {
  const baselineEnd = addMinutes(decision.baseline_start, task.duration_minutes);
  const sameSlot = decision.recommended_start === decision.baseline_start;
  return (
    <div className="plan-compare">
      <div className="plan-tile">
        <span>{decision.baseline_kind === "usual_time" ? "Your usual time" : "Run now"}</span>
        <b>{slotText(decision.baseline_start, baselineEnd)}</b>
        <strong>{costText(decision.baseline_cost_ron)}</strong>
        <small>estimated</small>
      </div>
      <ArrowRight size={18} aria-hidden="true" className="plan-compare-arrow" />
      <div className="plan-tile recommended">
        <span>{sameSlot ? "Recommended (same time)" : "Recommended"}</span>
        <b>{decision.recommended_start ? slotText(decision.recommended_start, decision.recommended_end) : "No feasible time"}</b>
        <strong>{costText(decision.estimated_cost_ron, decision.cost_range)}</strong>
        <small>estimated{decision.cost_range && decision.estimated_cost_ron == null ? " range" : ""}</small>
      </div>
    </div>
  );
}

function unknownReason(decision) {
  const codes = decision.reason_codes || [];
  const code =
    codes.find((c) => ["cost_bounded_by_tariff_unknown_solar_or_load", "price_coverage_missing", "price_gap_in_run"].includes(c)) ||
    codes.find((c) => /unknown|missing|gap/.test(c));
  return code ? reasonText(code) : "Some inputs needed for the estimate are missing.";
}

/** What can no longer be verified, from stale or missing inputs. */
function degraded(decision) {
  return (decision.freshness || [])
    .filter((row) => row.status === "stale" || row.status === "missing")
    .map((row) => {
      const view = freshnessRow(row);
      return `${view.name}: ${view.label}${view.time ? ` since ${view.time}` : ""}. Estimates that use it are less certain and cannot be verified yet.`;
    });
}

function WhyDetails({ decision, bands, task, children }) {
  const used = bandsUsed(decision.interval_plan, bands);
  const battery = batteryView(decision.battery);
  const { facts, assumptions } = splitReasons(decision.reason_codes);
  const counts = evidenceCounts(decision.evidence_ids);
  return (
    <details className="plan-why">
      <summary>Why?</summary>
      {children}
      {used.length > 0 && (
        <>
          <h4>Contract bands used</h4>
          <ul>
            {used.map((group) => (
              <li key={`${group.from}-${group.band_id}`}>
                {localTime(group.from)}–{localTime(group.to)}: <b>{group.label}</b>{" "}
                {group.rate == null ? "· no contract price (unknown cost)" : `· you pay ${ron(group.rate)}/kWh, export valued ${ron(group.exportValue)}/kWh`}
              </li>
            ))}
          </ul>
        </>
      )}
      <h4>Forecast basis (estimated)</h4>
      <ul>
        {forecastLines(decision.forecast).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      <h4>Battery</h4>
      <ul>
        <li>
          <b>{battery.title}</b>
        </li>
        {battery.lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      <h4>Input freshness</h4>
      <ul>
        {(decision.freshness || []).map((row) => {
          const view = freshnessRow(row);
          return (
            <li key={row.source}>
              {view.name}: {view.label}
              {view.time ? ` (last ${view.time}${view.age ? `, ${view.age}` : ""})` : ""}
            </li>
          );
        })}
        <li>{coverageText(decision.input_coverage)}</li>
      </ul>
      {facts.length > 0 && (
        <>
          <h4>What we found</h4>
          <ul>
            {facts.map((item) => (
              <li key={item.code}>{item.text}</li>
            ))}
          </ul>
        </>
      )}
      <h4>Assumptions</h4>
      <ul>
        {assumptions.map((item) => (
          <li key={item.code}>{item.text}</li>
        ))}
        {task.assumption_note && <li>Task note: {task.assumption_note}</li>}
        <li>The task's power and duration are the values you entered, not a measurement.</li>
      </ul>
      <p className="small-note">
        Evidence: {counts.measured} measured readings, {counts.derived} derived values
        {counts.other ? `, ${counts.other} other` : ""}. A recommendation cannot prove what would have happened at another time.
      </p>
      <details className="technical-details">
        <summary>Technical details</summary>
        <dl>
          <dt>Recommendation</dt>
          <dd>
            <code>{decision.recommendation_revision}</code> at {localDateTime(decision.decided_at)}
          </dd>
          <dt>Contract</dt>
          <dd>
            <code>{(decision.contract_version_ids || []).join(", ") || "none"}</code>
          </dd>
          <dt>Planning window</dt>
          <dd>
            {localDateTime(decision.horizon_start)} – {localDateTime(decision.horizon_end)}
          </dd>
          <dt>Evidence ids</dt>
          <dd>
            <ul className="evidence-ids">
              {(decision.evidence_ids || []).map((id) => (
                <li key={id}>
                  <code>{id}</code>
                </li>
              ))}
            </ul>
          </dd>
        </dl>
      </details>
    </details>
  );
}

function CommitmentBlock({ task, decision }) {
  const c = task.commitment;
  // The commitment snapshot does not name its comparison kind; the current decision's may differ.
  const difference = differenceText(c.estimated_difference_ron, null);
  return (
    <div className="plan-commitment">
      <div className="plan-commitment-head">
        <Lock size={16} aria-hidden="true" />
        <b>Accepted commitment</b>
        <span className="muted-inline">fixed, not changed by new forecasts</span>
      </div>
      <p className="plan-commitment-slot">{slotText(c.start, c.end)}</p>
      <dl className="plan-facts">
        <dt>Estimate at acceptance</dt>
        <dd>
          {costText(c.estimated_cost_ron)} <small>estimated</small>
        </dd>
        <dt>Compared with</dt>
        <dd>
          {costText(c.baseline_cost_ron)} · {difference.text}
        </dd>
        <dt>Accepted</dt>
        <dd>
          {localDateTime(c.accepted_at)} <small>(scenario time; recorded {localDateTime(c.accepted_received_at)})</small>
        </dd>
        <dt>Contract</dt>
        <dd>{versionLabel(c.contract_version_id)}</dd>
      </dl>
    </div>
  );
}

/**
 * The recommendation card. `compact` (Home) shows the headline, comparison and the
 * primary action; the full card adds facts and the "Why?" evidence.
 */
export function RecommendationCard({ api, siteId, task, plan, bands, compact = false, onTaskChanged, onOpenPlan, onEdit, onCancel }) {
  const { data: decision, error, loading, refresh } = plan;
  const [dialog, setDialog] = useState(null);
  const [notice, setNotice] = useState(null);
  const state = taskState(task.status);
  const committed = Boolean(task.commitment);
  const confidenceView = decision ? confidence(decision) : null;
  const battery = decision ? batteryView(decision.battery) : null;
  const difference = decision ? differenceText(decision.estimated_difference_ron, decision.baseline_kind) : null;
  const canAccept = decision && task.status === "suggested" && decision.recommended_start && decision.status !== "no_feasible_start";
  const lost = decision ? degraded(decision) : [];
  const factsBlock = decision && !committed && !compact ? (
    <dl className="plan-facts">
              <dt>Deadline</dt>
              <dd>Finished by {localDateTime(task.deadline)}</dd>
              <dt>Limits respected</dt>
              <dd>{(decision.constraints_applied || []).map(constraintText).join(" · ")}</dd>
              {decision.binding_constraints?.length > 0 && (
                <>
                  <dt>Limits that ruled out a cheaper time</dt>
                  <dd>{decision.binding_constraints.map(constraintText).join(" · ")}</dd>
                </>
              )}
              <dt>Inputs</dt>
              <dd>
                {confidenceView.label} · {coverageText(decision.input_coverage)}
              </dd>
              <dt>Forecast issued</dt>
              <dd>{localDateTime(decision.forecast?.issue_time)}</dd>
              <dt>Contract</dt>
              <dd>
                {versionLabel(decision.contract_version_id)}
                {decision.export_compensation ? ` · ${compensationText(decision.export_compensation).toLowerCase()}` : ""}
              </dd>
              <dt>Battery</dt>
              <dd className={battery.included ? "" : "plan-battery-excluded"}>
                <BatteryCharging size={13} aria-hidden="true" /> {battery.title}
              </dd>
            </dl>
  ) : null;
  return (
    <section className={`card plan-card ${compact ? "compact" : ""}`} aria-labelledby={`plan-${task.task_id}`}>
      <div className="plan-card-head">
        <div>
          <div className="eyebrow">{compact ? "NEXT TASK · ESTIMATED" : "RECOMMENDATION · ESTIMATED"}</div>
          <h3 id={`plan-${task.task_id}`}>{task.label}</h3>
        </div>
        <div className="plan-pills">
          <Pill tone={state.tone}>
            {task.status === "completed" ? <CheckCircle2 size={11} /> : committed ? <Lock size={11} /> : <Clock3 size={11} />}
            {state.label}
          </Pill>
          {confidenceView && !committed && <Pill tone={confidenceView.tone}>{confidenceView.label}</Pill>}
        </div>
      </div>
      <p className="plan-state-detail">{state.detail}</p>
      {notice && <Notice text={notice} tone="info" />}
      {committed && <CommitmentBlock task={task} decision={decision} />}
      {loading && <p className="muted">Calculating the recommendation…</p>}
      {error && !decision && (
        <Notice
          error={error}
          text={`The recommendation could not be loaded: ${planErrorText(error)} Your task is unchanged.`}
          onRetry={refresh}
        />
      )}
      {error && decision && (
        <Notice
          tone="info"
          text={`Could not refresh the recommendation. Showing the one from ${localDateTime(decision.decided_at)}; it may be outdated.`}
          onRetry={refresh}
        />
      )}
      {decision && committed && decision.review_suggested && (
        <div className="plan-review" role="status">
          <AlertTriangle size={16} aria-hidden="true" />
          <div>
            <b>New evidence suggests reviewing this plan.</b>
            <p>
              Current recommendation: {decision.recommended_start ? slotText(decision.recommended_start, decision.recommended_end) : "no feasible time"}
              {" "}({costText(decision.estimated_cost_ron, decision.cost_range)} estimated). {battery.included ? "" : battery.title} Your accepted plan stays
              as it is unless you release it.
            </p>
          </div>
        </div>
      )}
      {decision && !committed && (
        <>
          <p className="plan-headline">{planHeadline(decision)}</p>
          {decision.status !== "no_feasible_start" && <Compare decision={decision} task={task} />}
          <p className={`plan-reason tone-${difference.tone}`}>
            {decision.status === "no_feasible_start"
              ? (decision.reason_codes || []).map(reasonText).join(" ") || "No start time fits all your limits. Edit the task to widen its window."
              : difference.tone === "unknown"
                ? `${difference.text} ${unknownReason(decision)}`
                : `${difference.text}; based on your contract and the solar forecast${battery.included ? ", with your battery" : ""}.`}
          </p>
          {compact && (
            <p className="plan-compact-facts">
              <span>Deadline {localTime(task.deadline)}</span>
              <span>
                <BatteryCharging size={12} aria-hidden="true" /> {battery.title}
              </span>
            </p>
          )}
        </>
      )}
      {decision && lost.length > 0 && (
        <div className="plan-degraded" role="status">
          <b>What can no longer be verified</b>
          <ul>
            {lost.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}
      {decision && !compact && !["running", "completed"].includes(task.status) && (
        <WhyDetails decision={decision} bands={bands} task={task}>
          {factsBlock}
        </WhyDetails>
      )}
      <div className="button-row plan-actions">
        {canAccept && (
          <button className="btn yellow" onClick={() => { setNotice(null); setDialog("accept"); }}>
            Accept <Check size={16} />
          </button>
        )}
        {task.status === "accepted" && !compact && (
          <button className="btn secondary" onClick={() => setDialog("release")}>
            Review / release plan
          </button>
        )}
        {compact && onOpenPlan && (
          <button className="btn secondary" onClick={onOpenPlan}>
            {committed ? "See progress" : "Details"} <ArrowRight size={16} />
          </button>
        )}
        {!compact && task.status === "suggested" && onEdit && (
          <button className="text-btn" onClick={onEdit}>
            <Pencil size={14} /> Edit task
          </button>
        )}
        {!compact && task.status === "suggested" && onCancel && (
          <button className="text-btn" onClick={() => setDialog("cancel")}>
            <Trash2 size={14} /> Cancel task
          </button>
        )}
      </div>
      {dialog === "accept" && decision && (
        <AcceptDialog
          api={api}
          siteId={siteId}
          task={task}
          decision={decision}
          onClose={() => setDialog(null)}
          onAccepted={(next) => {
            setDialog(null);
            setNotice("Plan accepted. Start the task yourself at the agreed time; progress appears here once it runs.");
            onTaskChanged(next);
          }}
          onChanged={() => {
            setDialog(null);
            setNotice("The recommendation changed since you opened it. Review the new one below before accepting.");
            refresh();
          }}
        />
      )}
      {dialog === "release" && (
        <ReleaseDialog
          api={api}
          siteId={siteId}
          task={task}
          onClose={() => setDialog(null)}
          onReleased={(next) => {
            setDialog(null);
            setNotice("Plan released. A fresh recommendation is shown below.");
            onTaskChanged(next);
          }}
        />
      )}
      {dialog === "cancel" && (
        <CancelDialog
          api={api}
          siteId={siteId}
          task={task}
          onClose={() => setDialog(null)}
          onCancelled={(next) => {
            setDialog(null);
            onTaskChanged(next);
            onCancel?.(next);
          }}
        />
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ progress */

function ProgressCard({ api, siteId, task, nudge, onError }) {
  const { data, error, loading, refresh } = usePoller((signal) => api.taskProgress(siteId, task.task_id, signal), {
    key: `${siteId}:${task.task_id}:${task.commitment?.commitment_id}`,
    interval: 30000,
    nudge,
    onError,
  });
  const coverage = data ? Math.round((data.measured.import_coverage ?? 0) * 100) : null;
  const { facts } = splitReasons(data?.reason_codes);
  const notStarted = Boolean(data?.reason_codes?.includes("run_not_started"));
  return (
    <section className="card plan-progress" aria-labelledby={`progress-${task.task_id}`}>
      <div className="plan-card-head">
        <div>
          <div className="eyebrow">MEASURED AT YOUR CONNECTION POINT</div>
          <h3 id={`progress-${task.task_id}`}>Progress</h3>
        </div>
        <Gauge size={20} aria-hidden="true" />
      </div>
      {loading && <p className="muted">Loading measured energy…</p>}
      {error && <Notice error={error} text={`Progress could not be loaded: ${planErrorText(error)}`} onRetry={refresh} />}
      {data && notStarted && (
        <p className="plan-state-detail">
          Measurement starts at {localTime(data.window_start)} ({slotText(data.window_start, data.window_end)}). The grid meter at your
          connection point will show the energy taken during the agreed time.
        </p>
      )}
      {data && !notStarted && (
        <>
          <p className="plan-state-detail">
            Window {slotText(data.window_start, data.window_end)} · as of {localDateTime(data.as_of)}
            {data.status === "running" ? " · still running, figures grow until the window ends" : ""}
          </p>
          <div className="plan-compare progress">
            <div className="plan-tile">
              <span>Grid energy taken (measured)</span>
              <strong>{data.measured.grid_import_kwh == null ? "unknown" : `${data.measured.grid_import_kwh.toFixed(2)} kWh`}</strong>
              <small>coverage {coverage} %</small>
            </div>
            <div className="plan-tile">
              <span>Grid energy sent (measured)</span>
              <strong>{data.measured.grid_export_kwh == null ? "unknown" : `${data.measured.grid_export_kwh.toFixed(2)} kWh`}</strong>
              <small>coverage {Math.round((data.measured.export_coverage ?? 0) * 100)} %</small>
            </div>
          </div>
          <dl className="plan-facts">
            <dt>Whole-site grid cost in the window</dt>
            <dd>
              {costText(data.measured_site_cost_ron)} <small>from measured energy and your contract bands</small>
            </dd>
            <dt>Planned whole-site cost</dt>
            <dd>
              {costText(data.estimated_site_cost_ron)} <small>{data.comparison_label || "estimated"}</small>
            </dd>
            <dt>Source</dt>
            <dd>{data.measured.source === "component_meter" ? "Grid meter at your connection point" : data.measured.source}</dd>
          </dl>
          {coverage < 100 && data.status !== "accepted" && (
            <p className="plan-reason tone-bad">Energy verification incomplete: a meter gap covers part of this window.</p>
          )}
          {facts.length > 0 && (
            <ul className="plan-progress-reasons">
              {facts.map((item) => (
                <li key={item.code}>{item.text}</li>
              ))}
            </ul>
          )}
          <p className="small-note">
            {data.attribution_note ||
              "The connection-point meter measures the whole site, not the appliance alone. The planned cost is an estimate; one measured run cannot prove what another time would have cost."}
          </p>
        </>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ task form */

function DateTime({ label, prefix, form, set, required, hint }) {
  return (
    <fieldset className="plan-datetime">
      <legend>
        {label}
        {!required && <small> (optional)</small>}
      </legend>
      <input
        type="date"
        aria-label={`${label} date`}
        required={required}
        value={form[`${prefix}_date`]}
        onChange={(event) => set(`${prefix}_date`, event.target.value)}
      />
      <input
        type="time"
        step="900"
        aria-label={`${label} time`}
        required={required}
        value={form[`${prefix}_time`]}
        onChange={(event) => set(`${prefix}_time`, event.target.value)}
      />
      {hint && <small>{hint}</small>}
    </fieldset>
  );
}

function TaskForm({ api, siteId, task, now, onSaved, onClose }) {
  const [form, setForm] = useState(() => taskForm(task, now));
  const [errors, setErrors] = useState([]);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (key, value) => setForm((previous) => ({ ...previous, [key]: value }));
  const minutes = formDuration(form);
  async function submit(event) {
    event.preventDefault();
    const result = taskBody(form);
    setErrors(result.errors || []);
    setError(null);
    if (result.errors) return;
    setBusy(true);
    try {
      const saved = task
        ? await api.updateTask(siteId, task.task_id, { ...result.body, expected_revision: task.revision })
        : await api.createTask(siteId, result.body);
      onSaved(saved);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="card plan-form" aria-labelledby="plan-form-title">
      <div className="section-head">
        <h3 id="plan-form-title">{task ? "Edit task" : "Add a task"}</h3>
        <button className="icon-btn" aria-label="Close form" onClick={onClose}>
          <X size={18} />
        </button>
      </div>
      <form onSubmit={submit} noValidate>
        <div className="form-grid">
          <label>
            Name
            <input required maxLength={80} value={form.label} onChange={(event) => set("label", event.target.value)} placeholder="e.g. Laundry batch" />
          </label>
          <label>
            Power while running (kW)
            <input type="number" inputMode="decimal" min="0.1" max="50" step="0.1" value={form.power_kw} onChange={(event) => set("power_kw", event.target.value)} />
          </label>
          <label>
            Energy needed (kWh)
            <input type="number" inputMode="decimal" min="0.1" max="200" step="0.1" value={form.energy_kwh} onChange={(event) => set("energy_kwh", event.target.value)} />
          </label>
        </div>
        <p className="small-note">
          Runs in one go for {minutes ? durationText(minutes) : "—"} (energy ÷ power). These are your values, not a measurement of the appliance.
        </p>
        <div className="form-grid">
          <DateTime label="Finish by" prefix="deadline" form={form} set={set} required />
        </div>
        <details className="plan-advanced">
          <summary>Advanced options</summary>
        <div className="form-grid">
          <label>
            Kind
            <select value={form.kind} onChange={(event) => set("kind", event.target.value)}>
              {TASK_KINDS.map((kind) => (
                <option key={kind.value} value={kind.value}>
                  {kind.label}
                </option>
              ))}
            </select>
          </label>
          <DateTime label="Earliest start" prefix="earliest" form={form} set={set} required />
          <DateTime label="Latest start" prefix="latest" form={form} set={set} />
          <DateTime label="Your usual start" prefix="usual" form={form} set={set} hint="Used as the comparison; otherwise “run now”." />
          <fieldset className="plan-datetime">
            <legend>
              Allowed hours each day <small>(optional)</small>
            </legend>
            <input type="time" step="900" aria-label="Allowed from" value={form.window_from} onChange={(event) => set("window_from", event.target.value)} />
            <input type="time" step="900" aria-label="Allowed until" value={form.window_to} onChange={(event) => set("window_to", event.target.value)} />
            <small>An end before the start crosses midnight.</small>
          </fieldset>
          <label>
            Connection import limit (kW, optional)
            <input type="number" inputMode="decimal" min="0.1" max="1000" step="0.1" value={form.import_limit_kw} onChange={(event) => set("import_limit_kw", event.target.value)} />
          </label>
        </div>
        <label>
          Note (optional)
          <input maxLength={200} value={form.assumption_note} onChange={(event) => set("assumption_note", event.target.value)} placeholder="e.g. Illustrative values" />
        </label>
        </details>
        <p className="small-note">All times are Europe/Bucharest.</p>
        {errors.length > 0 && (
          <ul className="error" role="alert">
            {errors.map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
        )}
        <Notice error={error} />
        <div className="button-row">
          <button className="btn yellow" disabled={busy}>
            {busy ? "Saving…" : task ? "Save changes" : "Create task"} <Check size={16} />
          </button>
          <button type="button" className="text-btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}

/* ------------------------------------------------------------------ pages */

function useTasks(api, siteId, nudge, onError) {
  return usePoller((signal) => api.tasks(siteId, signal), { key: siteId, interval: 30000, nudge, onError });
}

function TaskWithPlan({ api, siteId, task, bands, nudge, onError, onTaskChanged, onEdit, onCancel }) {
  const plan = usePlan(api, siteId, task, nudge, onError);
  return (
    <>
      <RecommendationCard
        api={api}
        siteId={siteId}
        task={task}
        plan={plan}
        bands={bands}
        onTaskChanged={(next) => {
          onTaskChanged(next);
          plan.refresh();
        }}
        onEdit={onEdit}
        onCancel={onCancel}
      />
      {task.commitment && <ProgressCard api={api} siteId={siteId} task={task} nudge={nudge} onError={onError} />}
    </>
  );
}

export function PlanPage({ api, site, clock, onError }) {
  const nudge = clockNudge(clock);
  const [localNudge, setLocalNudge] = useState(0);
  const tasks = useTasks(api, site.site_id, nudge + localNudge, onError);
  const [contractView, saveContract] = useContract(api, site.site_id, onError);
  const [selected, setSelected] = useState(null);
  const [editing, setEditing] = useState(null); // null | "new" | task
  const [showCancelled, setShowCancelled] = useState(false);
  const list = tasks.data || [];
  const visible = list.filter((task) => showCancelled || task.status !== "cancelled");
  const current = list.find((task) => task.task_id === selected) || nextTask(list) || visible[0] || null;
  const bands = contractView?.version?.bands || contractView?.contract?.bands || [];
  const changed = (next) => {
    if (next?.task_id) setSelected(next.task_id);
    setLocalNudge((value) => value + 1);
  };
  return (
    <div className="plan-page">
      <p className="plan-intro">
        <Sun size={16} aria-hidden="true" /> A recommended time for your flexible work. Estimates only: you decide, and
        SolarLens never switches equipment on or off.
      </p>
      <div className="plan-layout">
        <section className="card plan-list" aria-labelledby="plan-list-title">
          <div className="section-head">
            <h3 id="plan-list-title">Your tasks</h3>
            <button className="btn secondary" onClick={() => setEditing("new")}>
              <Plus size={15} /> Add task
            </button>
          </div>
          {tasks.loading && <p className="muted">Loading tasks…</p>}
          {tasks.error && <Notice error={tasks.error} onRetry={tasks.refresh} />}
          {tasks.data && !visible.length && (
            <div className="empty">
              <CalendarClock size={30} />
              <p>No tasks yet. Add a flexible task (for example a laundry batch) to get a recommended time.</p>
            </div>
          )}
          <ul className="plan-task-list">
            {visible.map((task) => {
              const state = taskState(task.status);
              const active = current?.task_id === task.task_id;
              return (
                <li key={task.task_id}>
                  <button className={`plan-task ${active ? "active" : ""}`} aria-pressed={active} onClick={() => setSelected(task.task_id)}>
                    <span>
                      <b>{task.label}</b>
                      <small>
                        {kindLabel(task.kind)} · {task.power_kw} kW × {durationText(task.duration_minutes)} ·{" "}
                        {task.commitment ? slotText(task.commitment.start, task.commitment.end) : `by ${localDateTime(task.deadline)}`}
                      </small>
                    </span>
                    <Pill tone={state.tone}>{state.label}</Pill>
                  </button>
                </li>
              );
            })}
          </ul>
          {list.some((task) => task.status === "cancelled") && (
            <button className="text-btn" onClick={() => setShowCancelled(!showCancelled)}>
              {showCancelled ? "Hide cancelled tasks" : "Show cancelled tasks"}
            </button>
          )}
        </section>
        <div className="plan-main">
          {editing && (
            <TaskForm
              key={editing === "new" ? "new" : `${editing.task_id}:${editing.revision}`}
              api={api}
              siteId={site.site_id}
              task={editing === "new" ? null : editing}
              now={clock?.analytical_now}
              onClose={() => setEditing(null)}
              onSaved={(saved) => {
                setEditing(null);
                changed(saved);
              }}
            />
          )}
          {current && (
            <TaskWithPlan
              key={current.task_id}
              api={api}
              siteId={site.site_id}
              task={current}
              bands={bands}
              nudge={nudge + localNudge}
              onError={onError}
              onTaskChanged={changed}
              onEdit={() => setEditing(current)}
              onCancel={() => setSelected(null)}
            />
          )}
        </div>
      </div>
      <details className="plan-contract-details">
        <summary>Your contract prices (advanced)</summary>
        {contractView ? (
          <div className="plan-contract">
            <ContractCard key={site.site_id} contract={contractView.contract} version={contractView.version} onSave={saveContract} />
          </div>
        ) : (
          <section className="card empty">Loading your contract…</section>
        )}
      </details>
    </div>
  );
}

/** Compact "Next task" card for Home; renders nothing when the site has no open task. */
export function NextTaskCard({ api, site, clock, onError, onOpenPlan }) {
  const nudge = clockNudge(clock);
  const [localNudge, setLocalNudge] = useState(0);
  const tasks = useTasks(api, site.site_id, nudge + localNudge, onError);
  const task = nextTask(tasks.data);
  const plan = usePlan(api, site.site_id, task, nudge + localNudge, onError);
  if (tasks.error && !tasks.data) return <Notice error={tasks.error} text={`Tasks could not be loaded: ${planErrorText(tasks.error)}`} onRetry={tasks.refresh} />;
  if (!task) return null;
  return (
    <div className="next-task">
      <RecommendationCard
        api={api}
        siteId={site.site_id}
        task={task}
        plan={plan}
        compact
        onTaskChanged={() => setLocalNudge((value) => value + 1)}
        onOpenPlan={onOpenPlan}
      />
    </div>
  );
}
