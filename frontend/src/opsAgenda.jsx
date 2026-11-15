// Technician agenda (GET /ops/agenda): today's assignments as simple cards. Each card says
// where to go, when, what to do and why, with at most one primary progress button
// (Start trip -> I have arrived -> Finish job with a short note). A "Customer video"
// button appears only when the dispatcher linked one. Past jobs are listed below.
// Progress is forward-only and every update sends the item's revision.
import React, { useState } from "react";
import {
  CalendarClock,
  CheckCircle2,
  Clock3,
  MapPin,
  MessageSquare,
  Truck,
  Video,
  Wrench,
} from "lucide-react";
import { OpsNotice, Pill, usePolled } from "./opsShared";
import { friendlyError } from "./opsData";
import { OUTCOMES, bandTone, progressBody, progressText } from "./opsView";
import { PRIMARY_LABEL, SECONDARY_NOTE, agendaCard, agendaList, pastJobs } from "./agendaView";
import { localDateTime } from "./planView";

function CustomerVideo({ api, media }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="agenda-video">
      <button className="btn secondary" aria-expanded={open} onClick={() => setOpen(!open)}>
        <Video size={15} /> {open ? "Hide customer video" : "Customer video"}
      </button>
      {open && (
        <figure className="support-video">
          <video
            controls
            preload="metadata"
            className="video-preview"
            src={api.supportMediaUrl(media.id)}
            aria-label="Video recorded by the customer"
          />
          <figcaption>
            <Video size={13} /> {media.filename} · shared by the customer with the dispatcher
          </figcaption>
        </figure>
      )}
    </div>
  );
}

function AgendaCard({ api, item, first, onDone, onError }) {
  const card = agendaCard(item);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(null),
    [note, setNote] = useState(""),
    [outcome, setOutcome] = useState("resolved"),
    [finishing, setFinishing] = useState(false),
    [ok, setOk] = useState(null);
  async function send(state) {
    const { body, error: problem } = progressBody(item, state, { note, outcome });
    if (problem) {
      setError(new Error(problem));
      return;
    }
    setBusy(true);
    setError(null);
    setOk(null);
    try {
      await api.updateAssignmentProgress(item.assignment_id, body);
      setOk(state === "done" ? "Job marked done. Thank you." : `Saved: ${progressText(state).toLowerCase()}.`);
      if (state === "done") setNote("");
      setFinishing(false);
    } catch (failure) {
      if (!onError(failure)) setError(failure);
    } finally {
      setBusy(false);
      // assignment_changed / progress_not_forward: the refreshed agenda shows the truth.
      onDone();
    }
  }
  const primary = () => {
    if (card.next === "done" && !finishing) setFinishing(true);
    else if (card.next) send(card.next);
  };
  return (
    <li className={`card agenda-card${first ? " is-next" : ""}`}>
      <div className="agenda-when">
        <Clock3 size={16} aria-hidden="true" />
        <b>{card.time}</b>
        {card.day && <small>{card.day}</small>}
        {first && <Pill tone="yellow">Next job</Pill>}
        {card.progress && <Pill tone="green">{card.progress}</Pill>}
      </div>
      <dl className="agenda-facts">
        <div>
          <dt>
            <MapPin size={14} aria-hidden="true" /> Where
          </dt>
          <dd>
            <b>{card.where}</b>
            {card.whereDetail && <small>{card.whereDetail}</small>}
            {card.eta && <small>{card.eta}</small>}
          </dd>
        </div>
        <div>
          <dt>
            <Wrench size={14} aria-hidden="true" /> What to do
          </dt>
          <dd>
            <b>{card.what}</b>
          </dd>
        </div>
        <div>
          <dt>Why</dt>
          <dd>
            {card.tier && <Pill tone={bandTone(card.tier)}>{card.tier}</Pill>} {card.why}
          </dd>
        </div>
        {card.contact && (
          <div>
            <dt>
              <MessageSquare size={14} aria-hidden="true" /> Customer
            </dt>
            <dd>{card.contact}</dd>
          </div>
        )}
      </dl>
      {card.media && <CustomerVideo api={api} media={card.media} />}
      {card.next && (
        <div className="agenda-action">
          {finishing && card.next === "done" && (
            <div className="agenda-done-form">
              <label className="wide">
                Short note (required)
                <input
                  autoFocus
                  value={note}
                  maxLength={500}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder="What was found and done"
                />
              </label>
              <label>
                Result
                <select value={outcome} onChange={(event) => setOutcome(event.target.value)}>
                  {OUTCOMES.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}
          <button className="btn yellow full" disabled={busy} onClick={primary}>
            {card.next === "en_route" ? <Truck size={17} /> : <CheckCircle2 size={17} />}{" "}
            {busy ? "Saving…" : finishing && card.next === "done" ? "Mark done" : PRIMARY_LABEL[card.next]}
          </button>
          {!finishing && <small className="muted">{SECONDARY_NOTE[card.next]}</small>}
          {finishing && (
            <button className="text-btn" disabled={busy} onClick={() => setFinishing(false)}>
              Not yet
            </button>
          )}
        </div>
      )}
      <div aria-live="polite">
        {error && <p className="error">{friendlyError(error)}</p>}
        {ok && <p className="small-note">{ok}</p>}
      </div>
    </li>
  );
}

export function AgendaPage({ api, onError, reload }) {
  const agenda = usePolled((signal) => api.opsAgenda(signal), `agenda:${reload}`, onError);
  if (agenda.error && !agenda.data) return <OpsNotice error={agenda.error} onRetry={agenda.refresh} />;
  if (!agenda.data) return <section className="card empty">Loading your day…</section>;
  const items = agendaList(agenda.data);
  const past = pastJobs(agenda.data);
  return (
    <div className="agenda-page">
      <section className="agenda-head">
        <div>
          <h2>Today's jobs</h2>
          <p className="muted">
            {agenda.data.crews.length
              ? `${agenda.data.crews.join(", ")} · as of ${localDateTime(agenda.data.as_of)}`
              : "You are not a member of a crew yet."}
          </p>
        </div>
        <Pill>Synthetic planning</Pill>
      </section>
      <OpsNotice error={agenda.error} onRetry={agenda.refresh} />
      {items.length === 0 && (
        <section className="card empty">
          <CalendarClock size={28} />
          <p>No jobs for you right now. New jobs appear here when your dispatcher applies a plan.</p>
        </section>
      )}
      <ol className="agenda-list">
        {items.map((item, index) => (
          <AgendaCard
            key={item.assignment_id}
            api={api}
            item={item}
            first={index === 0}
            onDone={agenda.refresh}
            onError={onError}
          />
        ))}
      </ol>
      {agenda.data.deferred.length > 0 && (
        <section className="card">
          <h3>Coming up after another step</h3>
          <ul className="ops-plan-list">
            {agenda.data.deferred.map((d) => (
              <li key={`${d.plan_id}:${d.incident_id}:${d.activity}`}>
                {d.reason} · from {localDateTime(d.start_at)}
              </li>
            ))}
          </ul>
        </section>
      )}
      <section className="card agenda-past">
        <div className="section-head">
          <h3>Past jobs</h3>
          <Pill>{past.length}</Pill>
        </div>
        {past.length === 0 ? (
          <p className="muted">Finished jobs will be listed here.</p>
        ) : (
          <ul className="agenda-past-list">
            {past.map((job) => (
              <li key={job.id}>
                <CheckCircle2 size={15} aria-hidden="true" />
                <span>
                  <b>{job.title}</b>
                  <small>
                    {job.site}{job.zone ? ` · ${job.zone}` : ""} · {job.activity}
                    {job.finished ? ` · ${localDateTime(job.finished)}` : ""}
                  </small>
                  {job.note && <small>{job.note}</small>}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <p className="small-note">{agenda.data.eta_label}. Only your own crews' work is shown.</p>
    </div>
  );
}
