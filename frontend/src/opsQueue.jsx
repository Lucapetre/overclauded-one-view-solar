// Ranked incident queue (GET /ops/queue) next to the existing map (GET /ops/map status
// projection), with synchronized filters and selection, and the episode drawer
// (GET /ops/episodes/{id}) with evidence, rank explanation, source health and the
// role's permitted actions. Incidents without an episode keep the original modal.
import React, { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  Eye,
  Info,
  Link2,
  ShieldAlert,
  X,
} from "lucide-react";
import { SolarApiError } from "../../packages/contracts/client";
import { OpsNotice, Modal, Pill, usePolled } from "./opsShared";
import { OpsStatusMap } from "./opsMapPanel";
import { AutoDispatch, CrewBanner, IncidentModal } from "./opsPages";
import { friendlyError, logAction } from "./opsData";
import {
  ASSIGNMENT_FILTER,
  CLOSE_REASONS,
  EMPTY_FILTERS,
  QUEUE_GROUPS,
  RESPONSIBILITY,
  activeFilterCount,
  applyFilters,
  attentionBadge,
  bandTone,
  confidenceText,
  economicsLines,
  episodeActions,
  evidenceRows,
  factorLabel,
  factorRows,
  filterOptions,
  nextActionText,
  responsibilityText,
  rowForSite,
  sameRevision,
  shortSiteName,
  telemetryBadge,
  toQueueRows,
  visibleCounts,
  workflowText,
  progressText,
  conditionText,
  BANDS,
} from "./opsView";
import { FAMILY_ORDER, familyCard, hasEquipment } from "./equipmentView";
import { humanize, localDateTime, localTime } from "./planView";
import { bucharestParts, bucharestToUtc } from "./bucharestTime";

/** Queue + map from the same ops revision; a mismatch is retried, never mixed. */
function useOpsSnapshot(api, status, reload, onError) {
  return usePolled(
    async (signal) => {
      let queue, map;
      for (let attempt = 0; attempt < 3; attempt += 1) {
        [queue, map] = await Promise.all([api.opsQueue(status, signal), api.opsMap(signal)]);
        if (sameRevision(queue, map)) return { queue, map };
      }
      // Keep the last consistent snapshot on screen and retry on the next poll.
      throw new SolarApiError(409, {
        code: "revision_mismatch",
        message: `The queue (revision ${queue.revision}) and the map (revision ${map.revision}) are being reconciled; showing the last consistent view.`,
        request_id: "",
      });
    },
    `snapshot:${status}:${reload}`,
    onError,
  );
}

const FILTER_LABELS = {
  area: "Area",
  band: "Priority",
  family: "Family",
  telemetry: "Telemetry health",
  responsibility: "Responsibility",
  assignment: "Assignment",
};
function optionText(key, value, aliases) {
  if (key === "area") return value === "none" ? "No area" : aliases[value] || value;
  if (key === "telemetry") return telemetryBadge(value).label;
  if (key === "responsibility") return RESPONSIBILITY[value] || humanize(value);
  if (key === "assignment") return ASSIGNMENT_FILTER[value] || humanize(value);
  return value;
}

function Filters({ rows, filters, setFilters, aliases }) {
  const options = useMemo(() => filterOptions(rows), [rows]);
  const active = activeFilterCount(filters);
  return (
    <div className="filters ops-filters ops-queue-filters">
      {Object.keys(FILTER_LABELS).map((key) => (
        <label key={key} className="ops-filter">
          <span>{FILTER_LABELS[key]}</span>
          <select
            value={filters[key]}
            onChange={(event) => setFilters({ ...filters, [key]: event.target.value })}
          >
            <option value="all">All ({rows.length})</option>
            {options[key].map((o) => (
              <option key={o.value} value={o.value}>
                {optionText(key, o.value, aliases)} ({o.count})
              </option>
            ))}
          </select>
        </label>
      ))}
      {active > 0 && (
        <button className="text-btn" onClick={() => setFilters(EMPTY_FILTERS)}>
          Clear {active} filter{active === 1 ? "" : "s"} <X size={13} />
        </button>
      )}
    </div>
  );
}

function QueueRow({ row, selected, onSelect, onOpen }) {
  const tele = telemetryBadge(row.telemetry);
  const attention = attentionBadge(row.attention);
  return (
    <li
      className={`ops-queue-row${selected ? " is-selected" : ""}${row.overdue ? " is-overdue" : ""}`}
    >
      <button
        className="ops-queue-main"
        aria-pressed={selected}
        onClick={() => onSelect(row)}
        aria-label={`Rank ${row.position}, ${row.band}, ${row.title}, ${row.siteNames.join(" and ")}. Select to highlight on the map.`}
      >
        <span className="ops-rank">
          <small>#{row.position}</small>
          <Pill tone={bandTone(row.band)}>{row.band}</Pill>
          {row.overridden && (
            <small className="ops-override" title="Manual override; computed band kept">
              computed {row.computedBand}
            </small>
          )}
        </span>
        <span className="ops-queue-body">
          <b>{row.title}</b>
          <small>
            {row.siteNames.join(" + ")} · {row.area} · {row.family}
            {row.shared && " · shared episode (declared relation)"}
          </small>
          <span className="ops-badges">
            <Pill tone={attention.tone}>{attention.label}</Pill>
            <Pill tone={tele.tone}>{tele.label}</Pill>
            <Pill>{workflowText(row.workflow)}</Pill>
            {row.confidence && <Pill>{confidenceText(row.confidence)}</Pill>}
            {row.hasEpisode && <Pill>{responsibilityText(row.responsibility)} (proposed)</Pill>}
            {row.acknowledged && (
              <Pill tone="green">
                <CheckCircle2 size={11} aria-hidden="true" /> Acknowledged
              </Pill>
            )}
          </span>
          {row.conditionNote && <small className="ops-condition-note">{row.conditionNote}</small>}
        </span>
        <span className="ops-queue-time">
          <small className={row.overdue ? "error" : ""}>{row.deadline}</small>
          <small>Age {row.age}</small>
          <small>
            {row.crew
              ? `${row.crew.name}${row.crew.progress ? ` · ${progressText(row.crew.progress)}` : ""}${row.crew.eta ? ` · ETA ${localTime(row.crew.eta)} (estimate)` : ""}`
              : row.assignmentState === "proposed"
                ? "In a draft plan"
                : "No crew"}
          </small>
        </span>
      </button>
      <button
        className="icon-btn"
        aria-label={`Open details: ${row.title}`}
        onClick={() => onOpen(row)}
      >
        <ArrowUpRight size={17} />
      </button>
    </li>
  );
}

/**
 * Ranked queue (server order) in sections — field work, remote work, reviews,
 * monitoring only, other — next to the map. Selecting a row highlights its sites
 * and route; clicking a site selects its top row.
 */
export function IncidentsPage({
  api,
  user,
  aliases,
  siteFilter,
  onClearSite,
  focusIncident,
  onFocusHandled,
  onOpenRequest,
  onOpenPlan,
  onError,
  reload,
}) {
  const role = user.role;
  const [status, setStatus] = useState("open"),
    [filters, setFilters] = useState(EMPTY_FILTERS),
    [selected, setSelected] = useState(null),
    [opened, setOpened] = useState(null);
  const snapshot = useOpsSnapshot(api, status, reload, onError);
  const teams = usePolled(
    (signal) => (role === "supervisor" ? Promise.resolve(null) : api.opsTeams(signal)),
    `teams:${role}:${reload}`,
    onError,
  );
  const queue = snapshot.data?.queue,
    map = snapshot.data?.map;
  const statusSites = useMemo(
    () => [...(map?.status_sites || []), ...(map?.unmapped || [])],
    [map],
  );
  const allRows = useMemo(
    () => (queue ? toQueueRows(queue, statusSites, aliases) : []),
    [queue, statusSites, aliases],
  );
  const rows = useMemo(
    () =>
      applyFilters(allRows, filters).filter(
        (row) => !siteFilter || row.siteIds.includes(siteFilter.id),
      ),
    [allRows, filters, siteFilter],
  );
  const counts = visibleCounts(rows);
  const filtered = activeFilterCount(filters) > 0 || Boolean(siteFilter);
  const visibleSiteIds = useMemo(
    () => (filtered ? new Set(rows.flatMap((r) => r.siteIds)) : null),
    [filtered, rows],
  );
  useEffect(() => {
    if (!focusIncident) return;
    const row = allRows.find((r) => r.id === focusIncident);
    if (queue && !row && status === "open") {
      setStatus("all");
      return;
    }
    if (row || queue) {
      setSelected(focusIncident);
      setOpened(focusIncident);
      onFocusHandled?.();
    }
  }, [focusIncident, allRows, queue, status]);
  const selectedRow = allRows.find((r) => r.id === selected) || null;
  const openedRow = allRows.find((r) => r.id === opened) || null;
  const myCrewIds = role === "technician" ? (teams.data?.crews || []).map((c) => c.crew_id) : [];
  const legacy = allRows.some((r) => !r.hasEpisode);
  function selectSite(siteId) {
    const row = rowForSite(rows, siteId) || rowForSite(allRows, siteId);
    if (row) setSelected(row.id);
  }
  const refreshAll = () => {
    snapshot.refresh();
    teams.refresh();
  };
  return (
    <>
      {role === "technician" && <CrewBanner teams={teams.data} onOpen={setOpened} />}
      <section className="card">
        <div className="section-head ops-incidents-head">
          <div>
            <h3>Ranked incident queue</h3>
            <p className="muted">
              {queue
                ? `${queue.policy_label} · version ${queue.policy_version} (demo policy) · ranked at ${localDateTime(queue.rank_as_of)} · revision ${queue.revision}`
                : "Safety and deadlines first, then the demo policy's factors."}
            </p>
          </div>
          {role === "dispatcher" && legacy && (
            <AutoDispatch
              api={api}
              labels={Object.fromEntries(allRows.map((r) => [r.id, `${r.band} · ${r.title}`]))}
              onDone={refreshAll}
              onError={onError}
            />
          )}
        </div>
        <div className="filters ops-filters">
          <select
            aria-label="Incident status"
            value={status}
            onChange={(event) => setStatus(event.target.value)}
          >
            <option value="open">Open cases</option>
            <option value="all">All cases, including resolved</option>
          </select>
          {siteFilter && (
            <span className="ops-chip">
              Site: <b>{shortSiteName(siteFilter.alias)}</b>
              <button
                className="text-btn"
                onClick={onClearSite}
                aria-label="Show cases for every site"
              >
                Show all sites <X size={13} />
              </button>
            </span>
          )}
        </div>
        {queue && <Filters rows={allRows} filters={filters} setFilters={setFilters} aliases={aliases} />}
        {queue && (
          <div className="ops-count-strip" role="status" aria-live="polite">
            <span>
              <b>{counts.cases}</b> case{counts.cases === 1 ? "" : "s"}
            </span>
            <span>
              <b>{counts.episodes}</b> unique episode{counts.episodes === 1 ? "" : "s"}
            </span>
            <span>
              <b>{counts.sites}</b> unique site{counts.sites === 1 ? "" : "s"}
            </span>
            {BANDS.filter((b) => counts.byBand[b]).map((b) => (
              <span key={b}>
                <Pill tone={bandTone(b)}>{b}</Pill> {counts.byBand[b]}
              </span>
            ))}
            <span className="muted">
              Field {queue.field_count} · remote {queue.remote_review_count} · monitoring{" "}
              {queue.monitoring_count} (server totals)
            </span>
          </div>
        )}
        <OpsNotice error={snapshot.error} onRetry={snapshot.refresh} />
        {snapshot.loading && <div className="empty">Loading the ranked queue and the map…</div>}
      </section>
      {queue && (
        <div className="ops-queue-layout mt">
          <section className="card ops-queue-card" aria-label="Ranked queue">
            {rows.length === 0 && (
              <div className="empty">
                <CheckCircle2 size={28} />
                <p>
                  {status === "open"
                    ? "No open cases match these filters in your scope."
                    : "No cases match these filters in your scope."}
                </p>
              </div>
            )}
            {QUEUE_GROUPS.map((group) => {
              const list = rows.filter((r) => r.group === group.key);
              if (!list.length) return null;
              return (
                <div key={group.key} className={`ops-queue-group group-${group.key}`}>
                  <div className="ops-group-head">
                    <h4>
                      {group.title} <span className="muted">({list.length})</span>
                    </h4>
                    <small>{group.note}</small>
                  </div>
                  <ol className="ops-queue-list">
                    {list.map((row) => (
                      <QueueRow
                        key={row.id}
                        row={row}
                        selected={row.id === selected}
                        onSelect={(r) => setSelected(r.id === selected ? null : r.id)}
                        onOpen={(r) => {
                          setSelected(r.id);
                          setOpened(r.id);
                        }}
                      />
                    ))}
                  </ol>
                </div>
              );
            })}
          </section>
          <section className="card ops-map-card ops-queue-map" aria-label="Map of the same cases">
            <div className="section-head">
              <div>
                <h3>Same cases on the map</h3>
                <p className="muted">
                  {selectedRow
                    ? `Selected: #${selectedRow.position} ${selectedRow.band} · ${selectedRow.siteNames.join(" + ")}`
                    : "Click a site to select its top case; select a case to highlight its sites and route."}
                </p>
              </div>
              {selectedRow && (
                <button className="btn secondary" onClick={() => setOpened(selectedRow.id)}>
                  Open details <ArrowUpRight size={15} />
                </button>
              )}
            </div>
            <OpsStatusMap
              map={map}
              aliases={aliases}
              selectedSiteId={selectedRow?.siteId || null}
              relatedIds={selectedRow?.siteIds || null}
              selectedIncident={selectedRow?.id || null}
              onSiteClick={selectSite}
              onAction={(siteId) => {
                const row = rowForSite(rows, siteId) || rowForSite(allRows, siteId);
                if (row) {
                  setSelected(row.id);
                  setOpened(row.id);
                }
              }}
              actionLabel="Open its top case"
              visibleSiteIds={visibleSiteIds}
              height={460}
            />
          </section>
        </div>
      )}
      {openedRow?.hasEpisode && (
        <EpisodeDrawer
          api={api}
          user={user}
          incidentId={openedRow.id}
          statusSites={statusSites}
          myCrewIds={myCrewIds}
          analyticalNow={queue?.rank_as_of}
          snapshotRevision={queue?.revision}
          onClose={() => setOpened(null)}
          onChanged={refreshAll}
          onOpenPlan={onOpenPlan}
          onError={onError}
          reload={reload}
        />
      )}
      {opened && (!openedRow || !openedRow.hasEpisode) && (
        <IncidentModal
          api={api}
          user={user}
          incidentId={opened}
          crews={teams.data?.crews || []}
          aliases={aliases}
          onClose={() => setOpened(null)}
          onChanged={refreshAll}
          onOpenRequest={onOpenRequest}
          onError={onError}
          reload={reload}
        />
      )}
    </>
  );
}

/* --------------------------------------------------------------- drawer */

/** Grid / Battery / Solar source health from the d1 equipment adapter (read-only). */
function SourceHealth({ api, siteId, onError, reload }) {
  const summary = usePolled(
    (signal) => api.equipmentSummary(siteId, signal),
    `equipment:${siteId}:${reload}`,
    onError,
  );
  if (summary.loading) return <p className="muted">Loading equipment source health…</p>;
  if (summary.error && !summary.data) {
    const denied = summary.error instanceof SolarApiError && [403, 404].includes(summary.error.status);
    return (
      <p className="small-note">
        {denied
          ? "Equipment source health for this site is not available to your account."
          : `Equipment source health could not be loaded: ${friendlyError(summary.error)}`}
      </p>
    );
  }
  if (!hasEquipment(summary.data))
    return <p className="small-note">No connected meter, battery or weather equipment for this site.</p>;
  const cards = FAMILY_ORDER.map((family) => familyCard(summary.data, family));
  return (
    <div className="table-scroll">
      <table className="ops-table ops-source-table">
        <thead>
          <tr>
            <th>Source</th>
            <th>Device</th>
            <th>State</th>
            <th>Last update</th>
            <th>Latest value</th>
          </tr>
        </thead>
        <tbody>
          {cards.map((card) => (
            <tr key={card.family}>
              <td>{card.title}</td>
              <td>
                {card.device}
                {card.reasons.length > 0 && <small>{card.reasons.join(" ")}</small>}
              </td>
              <td>
                <Pill tone={card.tone}>{card.label}</Pill>
              </td>
              <td>
                {card.lastUpdate || "—"}
                {card.age && <small>{card.age}</small>}
              </td>
              <td>{card.primary ? card.primary.text.sentence : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FeedHealth({ status }) {
  if (!status) return <p className="small-note">No status projection for this site.</p>;
  const t = status.telemetry || {};
  return (
    <ul className="ops-feed-list">
      <li>
        <Pill tone={telemetryBadge(t.state).tone}>{telemetryBadge(t.state).label}</Pill>{" "}
        coverage {t.coverage == null ? "unknown" : `${Math.round(t.coverage * 100)}%`} · {conditionText(status.condition)}
        {status.condition_note && <small> — {status.condition_note}</small>}
      </li>
      {(t.sources || []).map((s) => (
        <li key={s.source}>
          {humanize(s.source)}: {humanize(s.status).toLowerCase()} · last {localDateTime(s.last_observed_at)}
        </li>
      ))}
      {(t.access_errors || []).map((e) => (
        <li key={`${e.source}:${e.failure_class}`} className="error">
          {humanize(e.source)}: {humanize(e.failure_class).toLowerCase()} ({e.count}×, last{" "}
          {localDateTime(e.last_at)})
        </li>
      ))}
      {t.unsupported_capabilities?.length > 0 && (
        <li className="muted">
          Not provided by this site's devices: {t.unsupported_capabilities.map(humanize).join(", ").toLowerCase()}
        </li>
      )}
      {status.not_evaluated_rules?.length > 0 && (
        <li className="muted">
          Not evaluated:{" "}
          {status.not_evaluated_rules
            .map((r) => `${humanize(r.rule_id)} (${r.reason_codes.map(humanize).join(", ").toLowerCase()})`)
            .join("; ")}
        </li>
      )}
    </ul>
  );
}

const plusHours = (iso, hours) => {
  const ms = Date.parse(iso);
  return Number.isFinite(ms) ? new Date(ms + hours * 3600000).toISOString() : null;
};

function OverrideForm({ detail, analyticalNow, busy, onSubmit }) {
  const start = bucharestParts(plusHours(analyticalNow || new Date().toISOString(), 24));
  const [form, setForm] = useState({
    band: detail.rank.band === "P0" ? "P0" : BANDS[Math.max(0, BANDS.indexOf(detail.rank.band) - 1)],
    reason: "",
    date: start?.date || "",
    time: start?.time || "",
  });
  const [problem, setProblem] = useState(null);
  return (
    <form
      className="ops-override-form"
      onSubmit={(event) => {
        event.preventDefault();
        const reason = form.reason.trim();
        if (reason.length < 5 || reason.length > 300)
          return setProblem("Give a reason of 5 to 300 characters.");
        const expires = bucharestToUtc(form.date, form.time);
        if (!expires) return setProblem("Choose a valid expiry date and time (Bucharest).");
        setProblem(null);
        onSubmit({ band: form.band, reason, expires_at: expires.toISOString() });
      }}
    >
      <label>
        New band
        <select value={form.band} onChange={(e) => setForm({ ...form, band: e.target.value })}>
          {BANDS.map((b) => (
            <option key={b}>{b}</option>
          ))}
        </select>
      </label>
      <label className="wide">
        Reason (audited)
        <input
          value={form.reason}
          maxLength={300}
          required
          onChange={(e) => setForm({ ...form, reason: e.target.value })}
          placeholder="Why the computed band should not apply"
        />
      </label>
      <label>
        Expires (date)
        <input type="date" required value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} />
      </label>
      <label>
        Expires (Bucharest time)
        <input type="time" required value={form.time} onChange={(e) => setForm({ ...form, time: e.target.value })} />
      </label>
      <button className="btn secondary" disabled={busy}>
        {busy ? "Saving…" : "Override priority"}
      </button>
      {problem && <p className="error">{problem}</p>}
      <p className="small-note wide">
        At most 7 days after the current replay time. The computed rank is kept and shown
        next to the override; active assignments are not changed automatically.
      </p>
    </form>
  );
}

function CloseForm({ busy, onSubmit }) {
  const [reason, setReason] = useState("remote_resolved"),
    [note, setNote] = useState(""),
    [problem, setProblem] = useState(null);
  return (
    <form
      className="ops-override-form"
      onSubmit={(event) => {
        event.preventDefault();
        const text = note.trim();
        if (text.length < 3) return setProblem("Document the closure with a short note (at least 3 characters).");
        setProblem(null);
        onSubmit({ reason_code: reason, note: text });
      }}
    >
      <label>
        Closure reason
        <select value={reason} onChange={(e) => setReason(e.target.value)}>
          {CLOSE_REASONS.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>
      </label>
      <label className="wide">
        Note (required, audited)
        <input value={note} maxLength={500} required onChange={(e) => setNote(e.target.value)} />
      </label>
      <button className="btn dark" disabled={busy}>
        <CheckCircle2 size={16} /> {busy ? "Closing…" : "Close episode"}
      </button>
      {problem && <p className="error">{problem}</p>}
      <p className="small-note wide">
        A documented, authorized closure. Missing telemetry never closes an episode; a
        parent's closure does not close unrelated child faults.
      </p>
    </form>
  );
}

export function EpisodeDrawer({
  api,
  user,
  incidentId,
  statusSites,
  myCrewIds,
  analyticalNow,
  snapshotRevision,
  onClose,
  onChanged,
  onOpenPlan,
  onError,
  reload,
}) {
  const role = user.role;
  const detail = usePolled(
    (signal) => api.opsEpisode(incidentId, signal),
    `episode:${incidentId}:${reload}`,
    onError,
  );
  const [busy, setBusy] = useState(null),
    [error, setError] = useState(null),
    [ok, setOk] = useState(null),
    [form, setForm] = useState(null);
  const d = detail.data;
  async function run(name, action, success) {
    setBusy(name);
    setError(null);
    setOk(null);
    try {
      await action();
      setOk(success);
      setForm(null);
    } catch (failure) {
      if (!onError(failure)) setError(failure);
    } finally {
      setBusy(null);
      detail.refresh();
      onChanged?.();
    }
  }
  if (!d)
    return (
      <Modal title={detail.error ? "Episode" : "Loading episode…"} onClose={onClose}>
        <OpsNotice error={detail.error} onRetry={detail.refresh} />
        {!detail.error && <div className="empty">Loading episode…</div>}
      </Modal>
    );
  if (snapshotRevision != null && d.revision !== snapshotRevision)
    return (
      <Modal title="Updating episode evidence…" onClose={onClose}>
        <p role="status">Reconciling the episode with the queue and map revision. Updates arrive within the five-second polling cycle.</p>
        <OpsNotice error={detail.error} onRetry={detail.refresh} />
      </Modal>
    );
  const i = d.incident,
    e = d.episode,
    rank = d.rank;
  const sites = new Map(statusSites.map((s) => [s.site_id, s]));
  const siteIds = e?.site_ids?.length ? e.site_ids : [i.site_id];
  const evidence = evidenceRows(d.evidence);
  const factors = factorRows(rank);
  const actions = episodeActions(role, d, myCrewIds);
  const open = i.status !== "resolved" && e?.state !== "resolved";
  const cannotProve = d.hypothesis?.cannot_prove || d.rule?.cannot_prove;
  return (
    <Modal title={`${rank.band} · ${i.title}`} onClose={onClose} className="ops-drawer">
      <div className="detail-meta">
        <Pill tone={bandTone(rank.band)}>
          {rank.band} · rank #{rank.position}
        </Pill>
        {rank.override && (
          <Pill tone="yellow" title={rank.override.reason}>
            Override until {localDateTime(rank.override.expires_at)} · computed {rank.computed_band}
          </Pill>
        )}
        <Pill>{workflowText(d.workflow)}</Pill>
        {e && <Pill>{confidenceText(e.confidence)}</Pill>}
        {e && <Pill tone={e.state === "active" ? "orange" : "green"}>{e.state === "active" ? "Active" : "Resolved"}</Pill>}
        {e?.acknowledged && <Pill tone="green">Acknowledged</Pill>}
        <span className="muted">
          Revision {d.revision} · ranked {localDateTime(rank.rank_as_of)}
        </span>
      </div>
      {["P0", "P1"].includes(rank.band) && open && (
        <div className="danger-box">
          <b>{rank.band === "P0" ? "Immediate danger reported or flagged" : "Urgent technical review"}</b>
          <p>
            If there is smoke, fire, or immediate danger, people must move away and contact
            emergency services (112). No equipment operating instructions are given here.
          </p>
        </div>
      )}
      {e?.hold_note && <div className="info-box">{e.hold_note}</div>}
      {e?.resolution_kind && (
        <div className="info-box">
          Resolved by {e.resolution_kind === "recovery_rule" ? "an explicit recovery rule" : "an authorized documented closure"}
          {e.resolution_detail ? `: ${e.resolution_detail}` : "."}
        </div>
      )}

      <h3>Affected sites and devices</h3>
      <ul className="ops-feed-list">
        {siteIds.map((id) => (
          <li key={id}>
            <b>{shortSiteName(sites.get(id)?.alias || (id === i.site_id ? i.site_alias : id))}</b>
            {sites.get(id)?.alias && <small> · {sites.get(id).alias}</small>}
          </li>
        ))}
        {e?.asset_ids?.length > 0 && <li>Devices: {e.asset_ids.join(", ")}</li>}
        {siteIds.length > 1 && (
          <li className="muted">
            <Link2 size={13} aria-hidden="true" /> One episode across {siteIds.length} sites (a declared
            relation); counted once as an episode.
          </li>
        )}
        {e?.parent_incident_id && <li>Child of the shared parent episode {e.parent_incident_id}.</li>}
        {e?.child_incident_ids?.length > 0 && <li>Parent of {e.child_incident_ids.length} child episode(s).</li>}
      </ul>

      {d.hypothesis && (
        <>
          <h3>Hypothesis</h3>
          <p>{d.hypothesis.interpretation}</p>
          <p className="small-note">Uncertainty: {d.hypothesis.uncertainty}</p>
          {d.hypothesis.alternatives?.length > 0 && (
            <p className="small-note">Alternative explanations: {d.hypothesis.alternatives.join("; ")}.</p>
          )}
        </>
      )}
      {cannotProve && (
        <div className="info-box ops-cannot">
          <ShieldAlert size={15} aria-hidden="true" /> <b>What this cannot prove:</b> {cannotProve}
        </div>
      )}

      <h3>Correlated evidence</h3>
      <p className="small-note">
        {e ? `Confidence: ${confidenceText(e.confidence)} — ${e.confidence_basis}. ` : ""}
        {evidence.independentSources} independent source group
        {evidence.independentSources === 1 ? "" : "s"}; mirrored copies are not counted as
        corroboration.
      </p>
      {evidence.rows.length ? (
        <div className="table-scroll">
          <table className="ops-table">
            <thead>
              <tr>
                <th>Evidence</th>
                <th>Source</th>
                <th>Time (Bucharest)</th>
                <th>Quality / independence</th>
              </tr>
            </thead>
            <tbody>
              {evidence.rows.map((row) => (
                <tr key={row.id} className={row.mirrored ? "is-mirrored" : ""}>
                  <td>
                    <b>{row.kind}</b>
                    <small>{row.summary}</small>
                  </td>
                  <td>{row.source}</td>
                  <td>{row.window}</td>
                  <td>{row.independence}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">No evidence rows recorded.</p>
      )}

      {e && (
        <>
          <h3>Responsibility (proposed, for review)</h3>
          <p>
            <b>{responsibilityText(e.responsibility)}</b> — {e.responsibility_basis}. Nothing is sent
            to an external party automatically.
          </p>
        </>
      )}

      <h3>Why this rank</h3>
      <p>
        <b>{rank.band_label}</b> · position #{rank.position} · policy {rank.policy_version}{" "}
        <Pill>demo policy</Pill>
        {rank.override && (
          <>
            {" "}
            · manual override to {rank.band} by {rank.override.created_by}: “{rank.override.reason}” (computed
            band {rank.computed_band} kept)
          </>
        )}
      </p>
      <p className="small-note">
        Dominant: {rank.dominant.map(factorLabel).join(", ")}.{" "}
        {rank.deadline_at
          ? `Response deadline ${localDateTime(rank.deadline_at)}${rank.deadline_mandatory ? " (mandatory)" : ""}${rank.overdue_minutes > 0 ? `, overdue by ${Math.round(rank.overdue_minutes)} min` : ""}.`
          : "No response deadline."}
      </p>
      <div className="table-scroll">
        <table className="ops-table ops-factor-table">
          <thead>
            <tr>
              <th>Factor</th>
              <th>Value</th>
              <th>Normalized</th>
              <th>Weight</th>
              <th>Contribution</th>
              <th>Basis</th>
            </tr>
          </thead>
          <tbody>
            {factors.map((f) => (
              <tr key={f.key} className={f.dominant ? "is-dominant" : ""}>
                <td>
                  {f.label}
                  {f.dominant && <small>dominant</small>}
                </td>
                <td>{f.value}</td>
                <td>{f.normalized}</td>
                <td>{f.weight}</td>
                <td>{f.contribution}</td>
                <td>
                  <small>{f.basis}</small>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rank.unknowns.length > 0 && (
        <p className="small-note">
          Unknown (never used to demote): {rank.unknowns.map(humanize).join(", ").toLowerCase()}.
        </p>
      )}
      <ul className="ops-feed-list">
        {economicsLines(rank.economics).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      {d.rank_history.length > 1 && (
        <p className="small-note">
          Rank history:{" "}
          {d.rank_history
            .map((h) => `rev ${h.ops_revision} ${h.band} (${h.context}, ${localTime(h.rank_as_of)})`)
            .join(" → ")}
        </p>
      )}

      <h3>Equipment and feed health</h3>
      {siteIds.map((id) => (
        <div key={id} className="ops-source-site">
          <h4>{shortSiteName(sites.get(id)?.alias || id)}</h4>
          <FeedHealth status={sites.get(id)} />
          <SourceHealth api={api} siteId={id} onError={onError} reload={reload} />
        </div>
      ))}

      {d.rule && (
        <details className="ops-rule">
          <summary>Rule {humanize(d.rule.title || e?.rule_id)} (revision {d.rule.revision})</summary>
          <ul className="ops-feed-list">
            {d.rule.required_metrics && <li>Required metrics: {d.rule.required_metrics.join(", ")}</li>}
            {d.rule.capability_gates && <li>Capability gates: {d.rule.capability_gates.join(", ")}</li>}
            {d.rule.boundary && <li>Boundary: {d.rule.boundary}</li>}
            {d.rule.window && <li>Window: {d.rule.window}</li>}
            {d.rule.persistence && <li>Persistence: {d.rule.persistence}</li>}
            {d.rule.explanation && <li>{d.rule.explanation}</li>}
          </ul>
        </details>
      )}

      <div className="two-col compact">
        <div>
          <h3>Log</h3>
          <div className="timeline ops-log">
            {i.log.map((entry, index) => (
              <div key={index}>
                <b>{logAction(entry.action)}</b>
                <span>{entry.detail}</span>
                <small>
                  {entry.actor} · {localDateTime(entry.created_at)}
                </small>
              </div>
            ))}
            {!i.log.length && <p className="muted">No entries yet.</p>}
          </div>
        </div>
        <div>
          <h3>Assignment history</h3>
          {d.assignment_history.length ? (
            <div className="timeline ops-log">
              {d.assignment_history.map((h) => (
                <div key={`${h.assignment_id}:${h.revision}`}>
                  <b>
                    Revision {h.revision} · {h.progress ? progressText(h.progress) : humanize(h.status)}
                  </b>
                  <span>{h.reason}</span>
                  <small>
                    {localDateTime(h.changed_as_of)}
                    {h.scheduled_start && ` · planned ${localTime(h.scheduled_start)}–${localTime(h.scheduled_end)}`}
                  </small>
                </div>
              ))}
            </div>
          ) : (
            <p className="muted">No assignment yet.</p>
          )}
          {d.overrides.length > 0 && (
            <>
              <h3>Overrides</h3>
              <ul className="ops-feed-list">
                {d.overrides.map((o) => (
                  <li key={o.override_id}>
                    {o.original_band} → {o.band} · “{o.reason}” · until {localDateTime(o.expires_at)}
                    {o.revoked ? " · revoked" : ""}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>

      <details className="ops-guidance">
        <summary>Approved customer wording</summary>
        <p>{d.customer_guidance}</p>
      </details>

      <div className="ops-actions" aria-live="polite">
        <h3>Next actions</h3>
        {d.next_actions.length > 0 ? (
          <p className="small-note">Suggested: {d.next_actions.map(nextActionText).join(" · ")}.</p>
        ) : (
          <p className="small-note">No further actions: this episode is resolved.</p>
        )}
        {error && <p className="error">{friendlyError(error)}</p>}
        {ok && <div className="info-box">{ok}</div>}
        <div className="button-row">
          {actions.acknowledge.allowed && (
            <button
              className="btn secondary"
              disabled={Boolean(busy)}
              onClick={() => run("ack", () => api.acknowledgeEpisode(incidentId), "Acknowledged. The log records who and when.")}
            >
              <Eye size={16} /> {busy === "ack" ? "Saving…" : "Acknowledge"}
            </button>
          )}
          {actions.close.allowed && (
            <button className="btn secondary" disabled={Boolean(busy)} onClick={() => setForm(form === "close" ? null : "close")}>
              <CheckCircle2 size={16} /> Close with reason…
            </button>
          )}
          {actions.override.allowed && (
            <button className="btn secondary" disabled={Boolean(busy)} onClick={() => setForm(form === "override" ? null : "override")}>
              <AlertTriangle size={16} /> Override priority…
            </button>
          )}
          {actions.revoke.allowed && (
            <button
              className="btn secondary"
              disabled={Boolean(busy)}
              onClick={() => run("revoke", () => api.revokePriorityOverride(incidentId), "Override revoked; the computed rank applies again.")}
            >
              {busy === "revoke" ? "Revoking…" : "Revoke override"}
            </button>
          )}
          {open && onOpenPlan && ["dispatcher", "supervisor"].includes(role) &&
            d.next_actions.some((a) => a.startsWith("propose_crew") || a.startsWith("plan_")) && (
              <button className="btn yellow" onClick={() => onOpenPlan()}>
                Open Plan teams <ArrowUpRight size={15} />
              </button>
            )}
        </div>
        {form === "close" && (
          <CloseForm
            busy={busy === "close"}
            onSubmit={(body) => run("close", () => api.closeEpisode(incidentId, body), "Episode closed with a documented reason.")}
          />
        )}
        {form === "override" && (
          <OverrideForm
            detail={d}
            analyticalNow={analyticalNow}
            busy={busy === "override"}
            onSubmit={(body) =>
              run("override", () => api.overridePriority(incidentId, body), `Priority set to ${body.band} until ${localDateTime(body.expires_at)}. Draft plans made before this change will be recomputed.`)
            }
          />
        )}
        {open && (
          <ul className="ops-denied">
            {["close", "override", "revoke"]
              .filter((k) => !actions[k].allowed && actions[k].reason && !(k === "revoke" && actions[k].reason === "No active override."))
              .map((k) => (
                <li key={k}>
                  <Info size={13} aria-hidden="true" /> {actions[k].reason}
                </li>
              ))}
          </ul>
        )}
      </div>
    </Modal>
  );
}
