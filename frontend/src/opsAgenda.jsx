// Technician agenda (GET /ops/agenda): the signed-in technician's own crews' visits in
// order, with forward-only progress (en route → on site → done). Every update sends the
// item's revision; "done" needs a short note. Other crews' routes are never shown.
import React, { useState } from "react";
import { CalendarClock, CheckCircle2, MapPin, Truck } from "lucide-react";
import { OpsNotice, Pill, usePolled } from "./opsShared";
import { friendlyError } from "./opsData";
import {
  OUTCOMES,
  activityText,
  agendaGroups,
  bandTone,
  caseTitle,
  progressBody,
  progressSteps,
  progressText,
  shortSiteName,
} from "./opsView";
import { localDateTime, localTime } from "./planView";

function AgendaItem({ api, item, onDone, onError }) {
  const [busy, setBusy] = useState(null),
    [error, setError] = useState(null),
    [note, setNote] = useState(""),
    [outcome, setOutcome] = useState("resolved"),
    [ok, setOk] = useState(null);
  const steps = progressSteps(item);
  const remote = String(item.activity || "").startsWith("remote");
  async function send(state) {
    const { body, error: problem } = progressBody(item, state, { note, outcome });
    if (problem) {
      setError(new Error(problem));
      return;
    }
    setBusy(state);
    setError(null);
    setOk(null);
    try {
      await api.updateAssignmentProgress(item.assignment_id, body);
      setOk(`Marked ${progressText(state).toLowerCase()}.`);
      if (state === "done") setNote("");
    } catch (failure) {
      if (!onError(failure)) setError(failure);
    } finally {
      setBusy(null);
      // assignment_changed / progress_not_forward: the refreshed agenda shows the truth.
      onDone();
    }
  }
  const next = steps.find((s) => s.next);
  return (
    <li className="card ops-agenda-item">
      <div className="ops-agenda-time">
        <b>
          {item.scheduled_start ? `${localTime(item.scheduled_start)}–${localTime(item.scheduled_end)}` : "Time not planned"}
        </b>
        <small>{item.scheduled_start ? localDateTime(item.scheduled_start).split(",")[0] : ""}</small>
      </div>
      <div className="ops-agenda-body">
        <div className="detail-meta">
          <Pill tone={bandTone(item.tier)}>{item.tier}</Pill>
          <Pill>{activityText(item.activity || item.kind)}</Pill>
          {item.progress && <Pill tone="yellow">{progressText(item.progress)}</Pill>}
        </div>
        <b>{caseTitle(item.title, item.site_alias)}</b>
        <small>
          <MapPin size={12} aria-hidden="true" /> {shortSiteName(item.site_alias)} · {item.site_alias}
        </small>
        <small>
          {remote
            ? "Remote work: no travel, no field location."
            : item.eta_arrival
              ? `ETA ${localTime(item.eta_arrival)} (estimate) · travel ${item.travel_minutes ?? "?"} min`
              : "ETA not computed"}
        </small>
        <ol className="ops-progress" aria-label="Progress">
          {steps.map((s) => (
            <li key={s.state} className={s.done ? "is-done" : s.next ? "is-next" : ""}>
              {s.done && <CheckCircle2 size={12} aria-hidden="true" />} {s.label}
            </li>
          ))}
        </ol>
        {next && (
          <div className="ops-progress-actions">
            {next.state === "done" && (
              <>
                <label>
                  Outcome
                  <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
                    {OUTCOMES.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="wide">
                  Note (required for done)
                  <input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} placeholder="What was found and done" />
                </label>
              </>
            )}
            <button className="btn yellow" disabled={Boolean(busy)} onClick={() => send(next.state)}>
              {next.state === "en_route" ? <Truck size={15} /> : <CheckCircle2 size={15} />}{" "}
              {busy ? "Saving…" : `Mark ${next.label.toLowerCase()}`}
            </button>
          </div>
        )}
        {error && <p className="error">{friendlyError(error)}</p>}
        {ok && <p className="small-note">{ok}</p>}
      </div>
    </li>
  );
}

export function AgendaPage({ api, onError, reload }) {
  const agenda = usePolled((signal) => api.opsAgenda(signal), `agenda:${reload}`, onError);
  if (agenda.error && !agenda.data) return <OpsNotice error={agenda.error} onRetry={agenda.refresh} />;
  if (!agenda.data) return <section className="card empty">Loading your agenda…</section>;
  const groups = agendaGroups(agenda.data);
  return (
    <>
      <section className="card">
        <div className="section-head">
          <div>
            <h3>Your visits, in order</h3>
            <p className="muted">
              {agenda.data.crews.length
                ? `${agenda.data.crews.join(", ")} · as of ${localDateTime(agenda.data.as_of)} (replay time)`
                : "You are not a member of a crew yet."}
            </p>
          </div>
          <Pill>Synthetic planning inputs</Pill>
        </div>
        <p className="small-note">{agenda.data.eta_label}. Only your own crews' work is shown.</p>
        <OpsNotice error={agenda.error} onRetry={agenda.refresh} />
      </section>
      {groups.length === 0 && (
        <section className="card empty mt">
          <CalendarClock size={28} />
          <p>No active visits for your crews. Applied plans appear here.</p>
        </section>
      )}
      {groups.map((g) => (
        <section key={g.crewId} className="mt">
          <div className="section-head">
            <h3>{g.crewName}</h3>
            <Pill>{g.items.length} visit{g.items.length === 1 ? "" : "s"}</Pill>
          </div>
          <ol className="ops-agenda">
            {g.items.map((item) => (
              <AgendaItem key={item.assignment_id} api={api} item={item} onDone={agenda.refresh} onError={onError} />
            ))}
          </ol>
        </section>
      ))}
      {agenda.data.deferred.length > 0 && (
        <section className="card mt">
          <h3>Planned after a prerequisite</h3>
          <ul className="ops-plan-list">
            {agenda.data.deferred.map((d) => (
              <li key={`${d.plan_id}:${d.incident_id}:${d.activity}`}>
                {activityText(d.activity)} · from {localDateTime(d.start_at)} — {d.reason}
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
