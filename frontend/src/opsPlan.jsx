// "Plan teams": propose → review → apply a crew plan (feasible heuristic proposal) with
// its FIFO/manual baseline comparison. Dispatchers review and apply; supervisors may
// propose and view, and see review/apply disabled. Apply sends the plan's input digest
// and one Idempotency-Key per click (reused only when retrying that same click).
import React, { useEffect, useRef, useState } from "react";
import { ArrowRight, Bot, CheckCircle2, ClipboardCheck, Info, RefreshCw, Route, UserCheck, Users } from "lucide-react";
import { SolarApiError } from "../../packages/contracts/client";
import { OpsNotice, Pill, newIdempotencyKey, usePolled } from "./opsShared";
import { friendlyError } from "./opsData";
import { AutoDispatch } from "./opsAuto";
import { automationSummary } from "./dispatchView";
import {
  activityText,
  bandTone,
  comparisonRows,
  completenessLines,
  crewProfileLines,
  crewRoutes,
  planActions,
  planJobs,
  planLifecycle,
  reasonLines,
  shortSiteName,
  verdictText,
  visitCells,
  caseTitle,
} from "./opsView";
import { localDateTime } from "./planView";

const HORIZONS = [4, 8, 12, 24];

/** Errors worth retrying with the same Idempotency-Key (the click may have landed). */
const retryable = (error) =>
  !(error instanceof SolarApiError) || error.status >= 500;

function Lifecycle({ status }) {
  return (
    <ol className="ops-lifecycle" aria-label={`Plan status: ${status}`}>
      {planLifecycle(status).map((step, index, all) => (
        <li key={step.key} className={`is-${step.state}`}>
          {step.state === "done" && <CheckCircle2 size={12} aria-hidden="true" />} {step.label}
          {index < all.length - 1 && <ArrowRight size={12} aria-hidden="true" />}
        </li>
      ))}
    </ol>
  );
}

function CrewCards({ crews }) {
  return (
    <div className="ops-plan-crews">
      {crews.map((crew) => {
        const p = crewProfileLines(crew);
        return (
          <div key={crew.crew_id} className="ops-plan-crew">
            <b>
              <Users size={14} aria-hidden="true" /> {crew.name}
            </b>
            <small>
              {p.kind === "remote_desk" ? "Remote triage desk (not a field crew)" : "Field crew"}
              {p.organisation ? ` · ${p.organisation}` : ""}
            </small>
            <span>Shift {p.shift}</span>
            <span>Members: {p.members.join(", ") || "none listed"}</span>
            <span>Qualifications: {p.qualifications.join(", ").toLowerCase() || "none listed"}</span>
            {p.tools?.length > 0 && <span>Tools: {p.tools.join(", ").toLowerCase()}</span>}
            <small>{p.base}</small>
          </div>
        );
      })}
    </div>
  );
}

function VisitTable({ visits, remote = false }) {
  return (
    <div className="table-scroll">
      <table className="ops-table ops-visit-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Case</th>
            <th>Priority</th>
            {!remote && <th>Depart</th>}
            {!remote && <th>Arrive</th>}
            <th>Start–finish</th>
            <th>Travel</th>
            <th>Service</th>
            <th>Deadline</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {visits.map((v) => {
            const c = visitCells(v);
            return (
              <tr key={v.job_id}>
                <td>{c.order}</td>
                <td>
                  <b>{caseTitle(v.title)}</b>
                  <small>
                    {shortSiteName(v.title.split(": ").slice(1).join(": ") || v.site_id)} ·{" "}
                    {activityText(v.activity)}
                  </small>
                </td>
                <td>
                  <Pill tone={bandTone(v.band)}>{v.band}</Pill>
                  <small>rank #{v.rank_position}</small>
                </td>
                {!remote && <td>{c.depart}</td>}
                {!remote && <td>{c.arrive}</td>}
                <td>{c.window}</td>
                <td>{c.travel}</td>
                <td>{c.service}</td>
                <td className={v.deadline_met ? "" : "error"}>{c.deadline}</td>
                <td>
                  <small>{v.reason}</small>
                  <details>
                    <summary>{c.constraints.length} constraints checked</summary>
                    <small>{c.constraints.join(", ")}</small>
                  </details>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Three plain columns: what was automated, what waits for approval, what needs a person. */
function AutomationSummary({ summary }) {
  const columns = [
    { key: "automated", title: "Done automatically", Icon: Bot, tone: "green", lines: summary.automated, empty: "Nothing yet. Press Propose a plan or Assign by severity." },
    { key: "approval", title: "Needs your approval", Icon: ClipboardCheck, tone: "yellow", lines: summary.approval, empty: "Nothing waiting for approval." },
    { key: "person", title: "Needs a person", Icon: UserCheck, tone: "orange", lines: summary.person, empty: "Every ranked case has an owner in this plan." },
  ];
  return (
    <div className="ops-automation" aria-label="What was automated and what needs approval">
      {columns.map(({ key, title, Icon, tone, lines, empty }) => (
        <section key={key} className={`ops-auto-col tone-${tone}`}>
          <h4>
            <Icon size={16} aria-hidden="true" /> {title} <span className="muted">({lines.length})</span>
          </h4>
          {lines.length ? (
            <ul>
              {lines.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          ) : (
            <p className="muted">{empty}</p>
          )}
        </section>
      ))}
      {summary.verdict && (
        <p className="ops-auto-verdict">
          <Pill tone={summary.verdict.tone}>{summary.verdict.text}</Pill> against the FIFO/manual baseline, same constraints.
        </p>
      )}
    </div>
  );
}

export function PlanTeamsPanel({ api, user, crews = [], onChanged, onError, reload, variant = "page", labels = {} }) {
  const role = user.role;
  const [horizon, setHorizon] = useState(12),
    [busy, setBusy] = useState(null),
    [error, setError] = useState(null),
    [notice, setNotice] = useState(null),
    [fresh, setFresh] = useState(null);
  // One key per Apply click; kept only while that click may be retried.
  const applyKey = useRef(null);
  const latest = usePolled(
    (signal) => api.latestCrewPlan(signal),
    `plan-latest:${reload}`,
    (failure) => {
      // "No plan yet" is a normal empty state, not an error.
      if (failure instanceof SolarApiError && failure.status === 404) return false;
      return onError(failure);
    },
  );
  const noPlan = latest.error instanceof SolarApiError && latest.error.status === 404;
  // An action's response is shown at once; the next poll result replaces it.
  useEffect(() => setFresh(null), [latest.data]);
  const plan = fresh || latest.data;
  const actions = planActions(role, plan);
  const crewNames = Object.fromEntries(crews.map((c) => [c.crew_id, c.name]));

  async function run(name, action, success) {
    setBusy(name);
    setError(null);
    setNotice(null);
    try {
      const result = await action();
      if (result) setFresh(result);
      setNotice(success);
      return true;
    } catch (failure) {
      if (onError(failure)) return false;
      const code = failure?.detail?.code;
      if (code === "plan_stale" || code === "plan_changed" || code === "plan_superseded") {
        // The backend computed a new draft (or superseded this one): load the latest.
        setFresh(null);
        setNotice(null);
        setError(failure);
        latest.refresh();
      } else setError(failure);
      return false;
    } finally {
      setBusy(null);
      latest.refresh();
      onChanged?.();
    }
  }

  function apply() {
    if (!applyKey.current) applyKey.current = newIdempotencyKey();
    const key = applyKey.current;
    setBusy("apply");
    setError(null);
    setNotice(null);
    api
      .applyCrewPlan(plan.plan_id, plan.input_digest, key)
      .then((result) => {
        applyKey.current = null;
        setFresh(result);
        setNotice(
          `Applied: ${result.applied_assignment_ids.length} assignment${result.applied_assignment_ids.length === 1 ? "" : "s"}. Crews and technicians now see them; repeating apply creates no duplicates.`,
        );
      })
      .catch((failure) => {
        if (onError(failure)) return;
        if (!retryable(failure)) applyKey.current = null;
        const code = failure?.detail?.code;
        if (["plan_stale", "plan_changed", "plan_superseded"].includes(code)) setFresh(null);
        setError(failure);
      })
      .finally(() => {
        setBusy(null);
        latest.refresh();
        onChanged?.();
      });
  }

  const routes = plan ? crewRoutes(plan.visits) : [];
  const verdict = plan ? verdictText(plan.comparison.verdict) : null;
  const completeness = plan ? completenessLines(plan.input_completeness) : null;
  const jobs = planJobs(plan);
  const staleCode = error?.detail?.code;
  const [autoResult, setAutoResult] = useState(null);
  const dispatch = variant === "dispatch";
  const summary = dispatch ? automationSummary(plan, autoResult) : null;
  return (
    <section className={`card ops-plan${dispatch ? " ops-plan-hero" : ""}`} aria-labelledby="plan-teams-title">
      <div className="section-head">
        <div>
          <div className="eyebrow">{dispatch ? "PLAN TEAMS · OPTIMISATION" : "PLAN TEAMS"}</div>
          <h3 id="plan-teams-title">Crew plan: who goes where, in what order</h3>
          <p className="muted">
            A feasible heuristic proposal from synthetic planning inputs (fictional crews,
            shifts, depots and an approximate travel matrix). Nothing changes until a
            dispatcher applies it.
          </p>
        </div>
        <Pill>Synthetic planning inputs</Pill>
      </div>

      {dispatch && <AutomationSummary summary={summary} />}

      <div className="ops-plan-controls">
        {dispatch && (
          <AutoDispatch
            api={api}
            labels={labels}
            onResult={setAutoResult}
            onDone={() => {
              latest.refresh();
              onChanged?.();
            }}
            onError={onError}
            compact
          />
        )}
        <label>
          Horizon
          <select value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}>
            {HORIZONS.map((h) => (
              <option key={h} value={h}>
                Next {h} hours
              </option>
            ))}
          </select>
        </label>
        <button
          className="btn yellow"
          disabled={!actions.canPropose || Boolean(busy)}
          onClick={() =>
            run("propose", () => api.proposeCrewPlan({ horizon_hours: horizon }), "A new draft plan was computed. Review it before applying.")
          }
        >
          <Route size={16} /> {busy === "propose" ? "Computing…" : plan ? "Propose a new plan" : "Propose a plan"}
        </button>
        <button
          className="btn secondary"
          disabled={!actions.review.enabled || Boolean(busy)}
          title={actions.review.reason || undefined}
          onClick={() => run("review", () => api.reviewCrewPlan(plan.plan_id), "Plan marked as reviewed. Apply it to create the assignments.")}
        >
          <ClipboardCheck size={16} /> {busy === "review" ? "Saving…" : "Review"}
        </button>
        <button
          className="btn dark"
          disabled={!actions.apply.enabled || Boolean(busy)}
          title={actions.apply.reason || undefined}
          onClick={apply}
        >
          <CheckCircle2 size={16} /> {busy === "apply" ? "Applying…" : applyKey.current ? "Retry apply" : "Apply"}
        </button>
        <button className="icon-btn" aria-label="Reload the latest plan" onClick={latest.refresh}>
          <RefreshCw size={16} />
        </button>
      </div>
      {(!actions.review.enabled || !actions.apply.enabled) && plan && role !== "dispatcher" && (
        <p className="small-note">
          <Info size={13} aria-hidden="true" /> {actions.apply.reason}. You can propose and view
          plans; a dispatcher reviews and applies them.
        </p>
      )}
      <div aria-live="polite">
        {error && (
          <div role="alert" className="connected-error">
            <Info size={19} />
            <div>
              <b>{friendlyError(error)}</b>
              {staleCode === "plan_stale" && <small>The previous plan is now superseded; the latest draft is shown below.</small>}
            </div>
          </div>
        )}
        {notice && <div className="info-box">{notice}</div>}
      </div>
      {latest.error && !noPlan && <OpsNotice error={latest.error} onRetry={latest.refresh} />}

      <h4>Available crews</h4>
      {crews.length ? <CrewCards crews={crews} /> : <p className="muted">No crews in your scope.</p>}

      {!plan && latest.loading && <div className="empty">Loading the latest plan…</div>}
      {!plan && noPlan && (
        <div className="empty">
          <Route size={26} />
          <p>No crew plan yet. Propose one to see visits, remote work and what cannot be assigned.</p>
        </div>
      )}
      {plan && (
        <>
          <div className="ops-plan-head">
            <Lifecycle status={plan.status} />
            <span className="muted">
              {plan.label} · horizon {localDateTime(plan.horizon_start)} – {localDateTime(plan.horizon_end)} ·
              created by {plan.approval.created_by} at replay time {localDateTime(plan.created_as_of)}
              {plan.approval.reviewed_by && ` · reviewed by ${plan.approval.reviewed_by}`}
              {plan.approval.applied_by && ` · applied by ${plan.approval.applied_by} at ${localDateTime(plan.approval.applied_as_of)}`}
            </span>
          </div>
          {actions.stale && plan.status !== "applied" && plan.status !== "superseded" && (
            <div className="info-box">
              The situation changed since this plan (revision {plan.ops_revision} → {plan.current_revision}). Applying
              it will be rejected and a new draft computed.
            </div>
          )}
          {plan.superseded_reason && (
            <div className="info-box">Superseded: {plan.superseded_reason}{plan.superseded_by ? ` (by ${plan.superseded_by})` : ""}.</div>
          )}
          {plan.redacted_items > 0 && (
            <p className="small-note">{plan.redacted_items} item(s) outside your scope are hidden.</p>
          )}

          <h4>Comparison with the FIFO/manual baseline</h4>
          <p>
            <Pill tone={verdict.tone}>{verdict.text}</Pill>
          </p>
          <div className="table-scroll">
            <table className="ops-table ops-compare-table">
              <thead>
                <tr>
                  <th>Measure</th>
                  <th>Heuristic proposal</th>
                  <th>FIFO baseline</th>
                </tr>
              </thead>
              <tbody>
                {comparisonRows(plan.comparison).map((row) => (
                  <tr key={row.metric}>
                    <td>{row.metric}</td>
                    <td>{row.heuristic}</td>
                    <td>
                      {row.baseline}
                      {row.same && <small>same</small>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small-note">
            {plan.comparison.baseline_definition} Findings: {plan.comparison.findings.join("; ")}.
          </p>

          <h4>Field visits per crew</h4>
          {routes.length ? (
            routes.map((r) => (
              <div key={r.crewId} className="ops-plan-route">
                <b>
                  {r.crewName} · {r.visits.length} visit{r.visits.length === 1 ? "" : "s"}
                </b>
                <VisitTable visits={r.visits} />
              </div>
            ))
          ) : (
            <p className="muted">No field visits in this plan.</p>
          )}

          <h4>Remote review and troubleshooting</h4>
          {plan.remote_items.length ? (
            crewRoutes(plan.remote_items).map((r) => (
              <div key={r.crewId} className="ops-plan-route">
                <b>{r.crewName} (no travel, no field location)</b>
                <VisitTable visits={r.visits} remote />
              </div>
            ))
          ) : (
            <p className="muted">No remote work in this plan.</p>
          )}

          <h4>Unassigned or blocked</h4>
          {plan.unassigned.length ? (
            <ul className="ops-plan-list">
              {plan.unassigned.map((u) => {
                const reasons = reasonLines(u.reasons, crewNames);
                return (
                  <li key={u.job_id}>
                    <Pill tone={bandTone(u.band)}>{u.band}</Pill> <b>{caseTitle(u.title)}</b> ·{" "}
                    {activityText(u.activity)}
                    <ul>
                      {reasons.general.map((t) => (
                        <li key={t}>{t}</li>
                      ))}
                    </ul>
                    {reasons.perCrew.length > 0 && (
                      <details>
                        <summary>Per crew</summary>
                        <ul>
                          {reasons.perCrew.map((t) => (
                            <li key={t}>{t}</li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="muted">Every eligible job has a crew in this plan.</p>
          )}

          {plan.urgent_exceptions.length > 0 && (
            <>
              <h4>Urgent exceptions</h4>
              <div className="danger-box">
                <ul>
                  {plan.urgent_exceptions.map((x) => (
                    <li key={x.job_id}>
                      {x.band} · {x.incident_id}: {reasonLines([x.reason]).general.join("")}
                    </li>
                  ))}
                </ul>
                <p>Escalate these under the local emergency policy; the plan does not replace it.</p>
              </div>
            </>
          )}

          {plan.monitoring.length > 0 && (
            <>
              <h4>Monitoring only (never sent to the field)</h4>
              <ul className="ops-plan-list">
                {plan.monitoring.map((m) => (
                  <li key={m.incident_id}>
                    <Pill tone={bandTone(m.band)}>{m.band}</Pill> {caseTitle(m.title)} ·{" "}
                    {shortSiteName(m.title.split(": ").slice(1).join(": "))} — {m.reason}
                  </li>
                ))}
              </ul>
            </>
          )}

          <details className="ops-plan-jobs">
            <summary>Ranked jobs considered ({jobs.length})</summary>
            <ol>
              {jobs.map((j) => (
                <li key={j.job_id}>
                  <Pill tone={bandTone(j.band)}>{j.band}</Pill> {caseTitle(j.title)} · {activityText(j.activity)} —{" "}
                  {j.text}
                </li>
              ))}
            </ol>
          </details>

          <h4>Inputs</h4>
          <ul className="ops-plan-list">
            <li>
              <Pill tone={completeness.complete ? "" : "orange"}>
                {completeness.complete ? "Inputs complete" : "Inputs incomplete"}
              </Pill>{" "}
              {completeness.lines.join(" · ")}
            </li>
            <li>Travel: {plan.travel_source}</li>
            <li>Policy {plan.policy_version} (demo policy) · method {plan.method.replaceAll("_", " ")}</li>
            <li className="muted">Input digest {plan.input_digest.slice(0, 12)}… · plan {plan.plan_id}</li>
          </ul>
        </>
      )}
    </section>
  );
}
