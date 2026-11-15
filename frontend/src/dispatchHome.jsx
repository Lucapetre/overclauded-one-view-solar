// Dispatcher home: everything the dispatcher decides from, in the order they decide it.
//   1. The optimisation panel (Plan teams) with its automation summary and the
//      "Assign by severity" / "Propose plan" controls, baseline comparison included.
//   2. Customer requests that still need triage.
//   3. The ranked incident queue (top cases) with severity badges.
//   4. Crews and their status next to the map.
// All figures come from the same endpoints as the other ops pages; nothing is invented.
import React, { useMemo } from "react";
import { AlertTriangle, ArrowUpRight, Inbox, Users, Video } from "lucide-react";
import { OpsNotice, Pill, usePolled } from "./opsShared";
import { PlanTeamsPanel } from "./opsPlan";
import { OpsStatusMap } from "./opsMapPanel";
import {
  BANDS,
  attentionBadge,
  bandTone,
  progressText,
  telemetryBadge,
  toQueueRows,
  workflowText,
} from "./opsView";
import { crewStatusRows, priorityCounts, topQueue, triageCount, triageItems } from "./dispatchView";
import { scopeLabel } from "./opsData";
import { localDateTime, localTime } from "./planView";

function CountStrip({ queue, counts, rows }) {
  const byBand = priorityCounts(counts, rows);
  return (
    <section className="card dispatch-strip" aria-label="Open cases by priority">
      <div>
        <div className="eyebrow">DISPATCH · RANKED BY SEVERITY</div>
        <p className="muted">
          {queue
            ? `Ranked at ${localDateTime(queue.rank_as_of)} (replay time) · ${queue.policy_label} · updates every few seconds`
            : "Loading the ranked queue…"}
        </p>
      </div>
      <div className="dispatch-counts">
        {byBand.map(({ band, count }) => (
          <span key={band} className={`dispatch-count band-${band}`}>
            <Pill tone={bandTone(band)}>{band}</Pill>
            <b>{count}</b>
          </span>
        ))}
        {queue && (
          <span className="muted">
            Field {queue.field_count} · remote {queue.remote_review_count} · monitoring {queue.monitoring_count}
          </span>
        )}
      </div>
    </section>
  );
}

function TriageCard({ requests, total, error, onRetry, onOpenRequests }) {
  const items = triageItems(requests || []);
  return (
    <section className="card dispatch-triage" aria-labelledby="triage-title">
      <div className="section-head">
        <div>
          <h3 id="triage-title">
            <Inbox size={17} aria-hidden="true" /> Needs triage
          </h3>
          <p className="muted">Customer calls and support requests waiting for a first reply.</p>
        </div>
        <Pill tone={total ? "orange" : "green"}>{total} waiting</Pill>
      </div>
      <OpsNotice error={error} onRetry={onRetry} />
      {!requests && !error && <div className="empty">Loading requests…</div>}
      {requests && items.length === 0 && <div className="empty">Nothing waiting. New requests appear here.</div>}
      <ul className="dispatch-list">
        {items.map((item) => (
          <li key={item.id} className={item.danger ? "is-danger" : ""}>
            <button className="dispatch-row" onClick={() => onOpenRequests(item.id)}>
              <span>
                <b>
                  {item.danger && <AlertTriangle size={14} aria-hidden="true" />} {item.label}
                </b>
                <small>
                  {item.site} · from {item.from} · {localTime(item.at)}
                  {item.hasVideo && (
                    <>
                      {" "}
                      · <Video size={11} aria-hidden="true" /> video
                    </>
                  )}
                </small>
                <small>{item.text}</small>
              </span>
              {item.danger && <Pill tone="orange">Danger</Pill>}
              <ArrowUpRight size={16} aria-hidden="true" />
            </button>
          </li>
        ))}
      </ul>
      {total > items.length && (
        <button className="text-btn" onClick={() => onOpenRequests(null)}>
          See all {total} requests <ArrowUpRight size={14} />
        </button>
      )}
    </section>
  );
}

function QueueCard({ rows, loading, error, onRetry, onOpenIncident, onOpenQueue }) {
  const items = topQueue(rows);
  return (
    <section className="card dispatch-queue" aria-labelledby="queue-title">
      <div className="section-head">
        <div>
          <h3 id="queue-title">Ranked incident queue</h3>
          <p className="muted">Highest priority first. Safety and deadlines come before cost.</p>
        </div>
        <button className="text-btn" onClick={onOpenQueue}>
          Full queue <ArrowUpRight size={14} />
        </button>
      </div>
      <OpsNotice error={error} onRetry={onRetry} />
      {loading && <div className="empty">Loading the ranked queue…</div>}
      {!loading && items.length === 0 && <div className="empty">No open cases in your scope.</div>}
      <ol className="dispatch-list">
        {items.map((row) => {
          const attention = attentionBadge(row.attention);
          const tele = telemetryBadge(row.telemetry);
          return (
            <li key={row.id} className={row.overdue ? "is-overdue" : ""}>
              <button className="dispatch-row" onClick={() => onOpenIncident(row.id)}>
                <span className="dispatch-rank">
                  <small>#{row.position}</small>
                  <Pill tone={bandTone(row.band)}>{row.band}</Pill>
                </span>
                <span>
                  <b>{row.title}</b>
                  <small>
                    {row.siteNames.join(" + ")} · {row.area} · {row.family}
                  </small>
                  <span className="ops-badges">
                    <Pill tone={attention.tone}>{attention.label}</Pill>
                    <Pill tone={tele.tone}>{tele.label}</Pill>
                    <Pill>{workflowText(row.workflow)}</Pill>
                  </span>
                  <small className={row.overdue ? "error" : ""}>
                    {row.deadline}
                    {row.crew
                      ? ` · ${row.crew.name}${row.crew.progress ? ` (${progressText(row.crew.progress).toLowerCase()})` : ""}`
                      : " · no crew yet"}
                  </small>
                </span>
                <ArrowUpRight size={16} aria-hidden="true" />
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function CrewsCard({ teams }) {
  const rows = crewStatusRows(teams);
  return (
    <section className="card dispatch-crews" aria-labelledby="crews-title">
      <div className="section-head">
        <h3 id="crews-title">
          <Users size={17} aria-hidden="true" /> Crews and status
        </h3>
        <Pill>{rows.length}</Pill>
      </div>
      {!teams && <div className="empty">Loading crews…</div>}
      <ul className="dispatch-crew-list">
        {rows.map((crew) => (
          <li key={crew.id}>
            <span>
              <b>{crew.name}</b>
              <small>
                {crew.kind} · shift {crew.shift} · {crew.members.join(", ") || "no members listed"}
              </small>
            </span>
            <span className="dispatch-crew-state">
              <Pill tone={crew.tone}>{crew.state}</Pill>
              <small>{crew.detail}</small>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function DispatchPage({
  api,
  user,
  aliases,
  onOpenIncident,
  onOpenIncidents,
  onOpenRequests,
  onError,
  reload,
}) {
  const queue = usePolled((signal) => api.opsQueue("open", signal), `dispatch-queue:${reload}`, onError);
  const map = usePolled((signal) => api.opsMap(signal), `dispatch-map:${reload}`, onError);
  const teams = usePolled((signal) => api.opsTeams(signal), `dispatch-teams:${reload}`, onError);
  const requests = usePolled((signal) => api.supportRequests(signal), `dispatch-requests:${reload}`, onError);
  const statusSites = useMemo(() => [...(map.data?.status_sites || []), ...(map.data?.unmapped || [])], [map.data]);
  const rows = useMemo(
    () => (queue.data ? toQueueRows(queue.data, statusSites, aliases) : []),
    [queue.data, statusSites, aliases],
  );
  const labels = useMemo(() => Object.fromEntries(rows.map((r) => [r.id, `${r.band} · ${r.title}`])), [rows]);
  const refreshAll = () => {
    queue.refresh();
    map.refresh();
    teams.refresh();
    requests.refresh();
  };
  return (
    <div className="dispatch-page">
      <CountStrip queue={queue.data} counts={map.data?.counts} rows={rows} />
      <PlanTeamsPanel
        api={api}
        user={user}
        crews={teams.data?.crews || []}
        onChanged={refreshAll}
        onError={onError}
        reload={reload}
        variant="dispatch"
        labels={labels}
      />
      <div className="dispatch-two">
        <TriageCard
          requests={requests.data}
          total={triageCount(requests.data || [])}
          error={requests.error}
          onRetry={requests.refresh}
          onOpenRequests={onOpenRequests}
        />
        <QueueCard
          rows={rows}
          loading={queue.loading}
          error={queue.error}
          onRetry={queue.refresh}
          onOpenIncident={onOpenIncident}
          onOpenQueue={() => onOpenIncidents()}
        />
      </div>
      <div className="dispatch-two dispatch-map-row">
        <section className="card ops-map-card" aria-label="Crews and sites on the map">
          <div className="section-head">
            <div>
              <h3>Crews on the map</h3>
              <p className="muted">
                {scopeLabel(Object.values(aliases))} · crew bases (not live GPS), site priority and proposed or applied
                routes.
              </p>
            </div>
            <Pill>Synthetic demo data</Pill>
          </div>
          <OpsNotice error={map.error} onRetry={map.refresh} />
          {map.loading && <div className="empty">Loading the map…</div>}
          {map.data && (
            <OpsStatusMap
              map={map.data}
              aliases={aliases}
              actionLabel="Open its cases"
              onAction={(id) => onOpenIncidents(id)}
              height={380}
              showList={false}
            />
          )}
        </section>
        <CrewsCard teams={teams.data} />
      </div>
    </div>
  );
}
