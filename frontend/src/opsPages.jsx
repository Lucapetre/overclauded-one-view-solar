// Connected (API-backed) operations pages: Area Radar map + forecast, Incidents with
// detail and incident log, Teams, Revenue. Data comes from /api/v1/ops/*; the
// presentational parts are the shared components in map.jsx and ops.jsx.
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  ArrowUpRight,
  CalendarDays,
  CheckCircle2,
  MessageSquare,
  Truck,
  Users,
  X,
} from "lucide-react";
import { poll } from "../../packages/contracts/client";
import { BucharestMap, MAP_NOTE } from "./map";
import {
  AssignmentReport,
  CrewSummary,
  FleetForecast,
  RevenueView,
} from "./ops";
import {
  ageLabel,
  areaName,
  assignmentStatus,
  crewChoices,
  friendlyError,
  incidentStatus,
  keepIfSame,
  logAction,
  scopeLabel,
  shortId,
  skipReason,
  tierTone,
  toAssignmentRows,
  toCrewSummaries,
  toForecastAreas,
  toMapSites,
  toRevenueReport,
} from "./opsData";
import { bucharestToday, meetingLabel, meetingWindow } from "./bucharestTime";
import { when } from "./telemetry";

function Pill({ children, tone = "" }) {
  return <span className={`pill ${tone}`}>{children}</span>;
}

/**
 * Polls `load` every 5 s (shared `poll` cadence) while mounted. Unchanged data keeps
 * its reference. `key` restarts polling and clears data (e.g. another filter).
 * 401 goes to `onError` (returns true when handled); poll stops on 401/403/404.
 */
export function usePolled(load, key, onError) {
  const [state, setState] = useState({ key, data: null, error: null });
  const [tick, setTick] = useState(0);
  useEffect(
    () =>
      poll(
        load,
        (value) =>
          setState((previous) => {
            const data =
              previous.key === key ? keepIfSame(previous.data, value) : value;
            return previous.key === key &&
              data === previous.data &&
              !previous.error
              ? previous
              : { key, data, error: null };
          }),
        (error) => {
          if (!onError(error))
            setState((previous) => ({
              key,
              data: previous.key === key ? previous.data : null,
              error,
            }));
        },
      ),
    [key, tick],
  );
  const current = state.key === key ? state : { data: null, error: null };
  return {
    data: current.data,
    error: current.error,
    loading: current.data === null && !current.error,
    refresh: () => setTick((value) => value + 1),
  };
}

export function OpsNotice({ error, onRetry }) {
  if (!error) return null;
  return (
    <div role="alert" className="connected-error">
      <AlertTriangle size={19} />
      <div>
        <b>{friendlyError(error)}</b>
        {error.detail?.request_id && (
          <small>Request {error.detail.request_id}</small>
        )}
      </div>
      {onRetry && (
        <button className="text-btn" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

function Modal({ title, children, onClose }) {
  useEffect(() => {
    const previous = document.activeElement;
    const handler = (event) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    document.querySelector(".modal .icon-btn")?.focus();
    return () => {
      document.removeEventListener("keydown", handler);
      previous?.focus?.();
    };
  }, []);
  return (
    <div className="overlay" onClick={onClose}>
      <section
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="modal wide ops-modal"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="section-head">
          <h2>{title}</h2>
          <button
            className="icon-btn"
            aria-label="Close dialog"
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}

/* ----------------------------- Area Radar ----------------------------- */

/** Map and fleet forecast shown above the coverage cards on Area Radar. */
export function RadarOps({
  api,
  aliases,
  scopeSites,
  onOpenSite,
  onOpenIncidents,
  onError,
  reload,
}) {
  const map = usePolled((signal) => api.opsMap(signal), `map:${reload}`, onError);
  const capacity = usePolled(
    (signal) => api.opsCapacity(signal),
    `capacity:${reload}`,
    onError,
  );
  const sites = useMemo(
    () => (map.data ? toMapSites(map.data.sites, aliases) : []),
    [map.data, aliases],
  );
  const forecastAreas = useMemo(
    () => toForecastAreas(capacity.data),
    [capacity.data],
  );
  const [focus, setFocus] = useState(null);
  const missing = Math.max(0, scopeSites - sites.length);
  const areaList = [...new Set(sites.map((site) => site.area))];
  const openSites = sites.filter((site) => site.status === "incident").length;
  return (
    <>
      <section className="card ops-map-card">
        <div className="section-head">
          <div>
            <h3>Installation map · Bucharest</h3>
            <p className="muted">
              {map.data
                ? `${sites.length} synthetic sites · ${areaList.length === 1 ? `${areaList[0]} area` : `${areaList.length} areas`} · ${openSites} with open incidents · zoom and pan the street map`
                : "Loading the map of your scope…"}
            </p>
          </div>
          <Pill>Synthetic demo data</Pill>
        </div>
        <OpsNotice error={map.error} onRetry={map.refresh} />
        <BucharestMap
          sites={sites}
          selectedId={focus}
          actionLabel="Open incidents or installation"
          onSelect={(id) => {
            setFocus(id);
            const site = map.data?.sites.find((item) => item.site_id === id);
            if (site?.open_incidents > 0) onOpenIncidents(id, site.alias);
            else onOpenSite(id);
          }}
          note={map.data?.note || MAP_NOTE}
        />
        {map.data && missing > 0 && (
          <p className="small-note">
            {missing} installation{missing === 1 ? "" : "s"} in your scope{" "}
            {missing === 1 ? "has" : "have"} no map profile (for example
            imported provider sites) and {missing === 1 ? "is" : "are"} not
            shown on the map.
          </p>
        )}
        <p className="small-note">
          A coverage map, not a network model. A site with an open incident
          opens the Incidents page filtered to that site; other sites open the
          installation detail. A recent feed is not an equipment health check.
        </p>
      </section>
      {capacity.error ? (
        <OpsNotice error={capacity.error} onRetry={capacity.refresh} />
      ) : capacity.loading ? (
        <section className="card empty mt">Loading installed capacity…</section>
      ) : forecastAreas.length ? (
        <div className="mt">
          <FleetForecast areas={forecastAreas} />
        </div>
      ) : (
        <section className="card empty mt">
          No installations with a capacity profile in your scope, so there is
          no fleet forecast.
        </section>
      )}
    </>
  );
}

/* ------------------------------ Incidents ----------------------------- */

function AutoDispatch({ api, labels, onDone, onError }) {
  const [busy, setBusy] = useState(false),
    [result, setResult] = useState(null),
    [error, setError] = useState(null);
  async function run() {
    setBusy(true);
    setError(null);
    try {
      const value = await api.autoDispatch();
      setResult(value);
      onDone?.();
    } catch (failure) {
      if (!onError(failure)) setError(failure);
    } finally {
      setBusy(false);
    }
  }
  const label = (id, tier) => labels[id] || `${tier} · ${shortId(id)}`;
  return (
    <div className="ops-auto">
      <button className="btn yellow" onClick={run} disabled={busy}>
        {busy ? "Assigning…" : "Assign by severity"} <ArrowRight size={16} />
      </button>
      {error && <p className="error">{friendlyError(error)}</p>}
      {result && (
        <div className="info-box ops-result" role="status">
          <b>
            Assigned {result.assigned.length} · skipped {result.skipped.length}
          </b>
          {result.assigned.length > 0 && (
            <ul>
              {result.assigned.map((a) => (
                <li key={a.incident_id}>
                  ✓ {label(a.incident_id, a.tier)} → <b>{a.crew_name}</b>
                </li>
              ))}
            </ul>
          )}
          {result.skipped.length > 0 && (
            <ul>
              {result.skipped.map((s) => (
                <li key={s.incident_id}>
                  – Not assigned: {label(s.incident_id, s.tier)}, because{" "}
                  {skipReason(s.reason)}.
                </li>
              ))}
            </ul>
          )}
          {!result.assigned.length && !result.skipped.length && (
            <p>Every open incident in your scope already has a crew.</p>
          )}
          <p className="small-note">
            Demo only: no real team was contacted.
          </p>
        </div>
      )}
    </div>
  );
}

const incidentLabels = (list) =>
  Object.fromEntries(
    (list || []).map((i) => [
      i.incident_id,
      `${i.tier} · ${i.title} · ${i.site_alias}`,
    ]),
  );

function CrewBanner({ teams, onOpen }) {
  if (!teams) return null;
  if (!teams.crews.length)
    return (
      <section className="card ops-crew-banner">
        <Users size={18} />
        <span>
          You are not a member of a crew yet, so you can view incidents but not
          send a team or book meetings.
        </span>
      </section>
    );
  return teams.crews.map((crew) => {
    const meetings = teams.assignments.filter(
      (a) => a.crew_name === crew.name && a.status === "meeting_scheduled",
    );
    const active = crew.active_assignment;
    return (
      <section className="card ops-crew-banner" key={crew.crew_id}>
        <span className="crew-icon">
          <Users size={20} />
        </span>
        <span>
          <b>{crew.name}</b> · {crew.area_alias} area · {crew.members.length}{" "}
          member{crew.members.length === 1 ? "" : "s"} · {crew.shift} EET
        </span>
        <Pill tone={crew.available ? "green" : "orange"}>
          {crew.available
            ? "✓ Available"
            : `● ${active ? assignmentStatus(active.status) : "Busy"}${active ? ` · ${active.site_alias}` : ""}`}
        </Pill>
        {active && (
          <button
            className="text-btn"
            onClick={() => onOpen(active.incident_id)}
          >
            Open {active.tier} {active.site_alias} <ArrowUpRight size={14} />
          </button>
        )}
        <span className="muted">
          {meetings.length
            ? `Meetings: ${meetings.map((m) => `${m.site_alias} ${meetingLabel(m.scheduled_start, m.scheduled_end)}`).join(" · ")}`
            : "No customer meetings booked"}
        </span>
      </section>
    );
  });
}

/**
 * Incidents list (severity order from the server) with filters and the detail modal.
 * siteFilter: { id, alias } | null — set from the map.
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
  onError,
  reload,
}) {
  const role = user.role;
  const [status, setStatus] = useState("open"),
    [tier, setTier] = useState("All"),
    [selected, setSelected] = useState(null);
  const list = usePolled(
    (signal) => api.opsIncidents(status, signal),
    `incidents:${status}:${reload}`,
    onError,
  );
  const teams = usePolled(
    (signal) =>
      role === "supervisor" ? Promise.resolve(null) : api.opsTeams(signal),
    `teams:${role}:${reload}`,
    onError,
  );
  useEffect(() => {
    if (focusIncident) {
      setSelected(focusIncident);
      onFocusHandled?.();
    }
  }, [focusIncident]);
  const rows = (list.data || []).filter(
    (i) =>
      (tier === "All" || i.tier === tier) &&
      (!siteFilter || i.site_id === siteFilter.id),
  );
  const labels = useMemo(() => incidentLabels(list.data), [list.data]);
  const refreshAll = () => {
    list.refresh();
    teams.refresh();
  };
  return (
    <>
      {role === "technician" && (
        <CrewBanner teams={teams.data} onOpen={setSelected} />
      )}
      <section className="card">
        <div className="section-head ops-incidents-head">
          <div>
            <h3>Every case in your scope, in the right order</h3>
            <p className="muted">
              Safety tier first, then age. Synthetic demo incidents from replay
              policy rules and customer requests; not an equipment diagnosis.
            </p>
          </div>
          {role === "dispatcher" && (
            <AutoDispatch
              api={api}
              labels={labels}
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
            <option value="open">Open incidents</option>
            <option value="all">All incidents, including resolved</option>
          </select>
          <select
            aria-label="Safety tier"
            value={tier}
            onChange={(event) => setTier(event.target.value)}
          >
            <option value="All">All safety tiers</option>
            {["P0", "P1", "P2", "P3"].map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
          {siteFilter && (
            <span className="ops-chip">
              Site: <b>{siteFilter.alias}</b>
              <button
                className="text-btn"
                onClick={onClearSite}
                aria-label="Show incidents for every site"
              >
                Show all sites <X size={13} />
              </button>
            </span>
          )}
          <Pill>
            {list.data ? `${rows.length} case${rows.length === 1 ? "" : "s"}` : "Loading…"}
          </Pill>
        </div>
        <OpsNotice error={list.error} onRetry={list.refresh} />
        {list.data && rows.length > 0 && (
          <div className="table-scroll">
            <table className="ops-incident-table">
              <thead>
                <tr>
                  <th>Priority / case</th>
                  <th>Installation</th>
                  <th>Status</th>
                  <th>Crew / meeting</th>
                  <th>Age</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((i) => (
                  <tr
                    key={i.incident_id}
                    className="clickable"
                    onClick={() => setSelected(i.incident_id)}
                  >
                    <td>
                      <div className="case-cell">
                        <Pill tone={tierTone(i.tier)}>{i.tier}</Pill>
                        <div>
                          <b>{i.title}</b>
                          <small>
                            {shortId(i.incident_id)} · {i.family} ·{" "}
                            {i.source === "customer_request"
                              ? "Customer request"
                              : "Synthetic replay"}
                          </small>
                        </div>
                      </div>
                    </td>
                    <td>
                      {i.site_alias}
                      <small>
                        {[i.zone, `${areaName(i.area_id, aliases)} area`]
                          .filter(Boolean)
                          .join(" · ")}
                      </small>
                    </td>
                    <td>
                      <Pill tone={i.status === "resolved" ? "green" : ""}>
                        {incidentStatus(i.status)}
                      </Pill>
                    </td>
                    <td>
                      {i.assignment ? (
                        <>
                          {i.assignment.crew_name}
                          <small>
                            {i.assignment.kind === "meeting"
                              ? `Meeting ${meetingLabel(i.assignment.scheduled_start, i.assignment.scheduled_end)}`
                              : assignmentStatus(i.assignment.status)}
                          </small>
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      {ageLabel(i.created_at)}
                      <small>{when(i.created_at)}</small>
                    </td>
                    <td>
                      <button
                        className="icon-btn"
                        aria-label={`Open ${i.title} at ${i.site_alias}`}
                        onClick={(event) => {
                          event.stopPropagation();
                          setSelected(i.incident_id);
                        }}
                      >
                        <ArrowUpRight size={17} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {list.loading && <div className="empty">Loading incidents…</div>}
        {list.data && !rows.length && (
          <div className="empty">
            <CheckCircle2 size={28} />
            <p>
              {status === "open"
                ? "No open incidents match these filters in your scope."
                : "No incidents match these filters in your scope."}
            </p>
          </div>
        )}
      </section>
      {selected && (
        <IncidentModal
          api={api}
          user={user}
          incidentId={selected}
          crews={teams.data?.crews || []}
          aliases={aliases}
          onClose={() => setSelected(null)}
          onChanged={refreshAll}
          onOpenRequest={onOpenRequest}
          onError={onError}
          reload={reload}
        />
      )}
    </>
  );
}


/** Incident detail: evidence, source, assignment, incident log and role actions. */
export function IncidentModal({
  api,
  user,
  incidentId,
  crews,
  aliases,
  onClose,
  onChanged,
  onOpenRequest,
  onError,
  reload,
}) {
  const role = user.role;
  const detail = usePolled(
    (signal) => api.opsIncident(incidentId, signal),
    `incident:${incidentId}:${reload}`,
    onError,
  );
  const [busy, setBusy] = useState(null),
    [error, setError] = useState(null),
    [ok, setOk] = useState(null),
    [crew, setCrew] = useState(""),
    [meeting, setMeeting] = useState(() => ({
      date: bucharestToday(),
      start: "10:00",
      end: "11:00",
    }));
  const i = detail.data;
  async function run(name, action, success) {
    setBusy(name);
    setError(null);
    setOk(null);
    try {
      const result = await action();
      setOk(typeof success === "function" ? success(result) : success);
      return true;
    } catch (failure) {
      if (!onError(failure)) setError(failure);
      return false;
    } finally {
      // Refresh either way: a conflict (e.g. already_assigned) means the view is stale.
      setBusy(null);
      detail.refresh();
      onChanged?.();
    }
  }
  const title = i
    ? `${i.tier} · ${i.title}`
    : detail.error
      ? "Incident"
      : "Loading incident…";
  if (!i)
    return (
      <Modal title={title} onClose={onClose}>
        <OpsNotice error={detail.error} onRetry={detail.refresh} />
        {!detail.error && <div className="empty">Loading incident…</div>}
      </Modal>
    );
  const open = i.status !== "resolved";
  const a = i.assignment;
  const myCrews = role === "technician" ? crews : [];
  const mine = Boolean(a && myCrews.some((c) => c.crew_id === a.crew_id));
  const myEligible = myCrews.filter(
    (c) => c.area_id === i.area_id && c.skills.includes(i.family),
  );
  const choices = crewChoices(crews, i);
  const billing = i.family === "Billing";
  const sortedLog = [...i.log];
  return (
    <Modal title={title} onClose={onClose}>
      <div className="detail-meta">
        <Pill tone={tierTone(i.tier)}>{i.tier}</Pill>
        <Pill tone={open ? "" : "green"}>{incidentStatus(i.status)}</Pill>
        <span>
          {i.site_alias} ·{" "}
          {[i.zone, `${areaName(i.area_id, aliases)} area`]
            .filter(Boolean)
            .join(" · ")}{" "}
          · {shortId(i.incident_id)}
        </span>
        {a && (
          <Pill tone="yellow">
            <Truck size={12} /> {a.crew_name} · {assignmentStatus(a.status)}
          </Pill>
        )}
      </div>
      {["P0", "P1"].includes(i.tier) && open && (
        <div className="danger-box">
          <b>
            {i.tier === "P0"
              ? "Immediate danger reported or flagged"
              : "Urgent technical review"}
          </b>
          <p>
            If there is smoke, fire, or immediate danger, people must move away
            and contact emergency services (112). No equipment operating
            instructions are given here.
          </p>
        </div>
      )}
      <h3>What the evidence says</h3>
      <p>{i.evidence}</p>
      <div className="info-box">
        Source:{" "}
        {i.source === "customer_request"
          ? "a customer support request (the customer's own words)"
          : "synthetic replay policy rule on demo data"}
        <br />
        Type: {i.family} · Opened {when(i.created_at)} · Last change{" "}
        {when(i.updated_at)}
        <br />
        This is a demo flag for human review, not an equipment diagnosis.
      </div>
      {i.support_request_id && role !== "supervisor" && (
        <button
          className="text-btn mt"
          onClick={() => onOpenRequest(i.support_request_id)}
        >
          <MessageSquare size={15} /> Open the customer request{" "}
          <ArrowUpRight size={14} />
        </button>
      )}
      {a?.kind === "meeting" && (
        <div className="meeting-note">
          <CalendarDays size={14} /> Customer meeting · {a.crew_name}:{" "}
          <b>{meetingLabel(a.scheduled_start, a.scheduled_end)}</b> (demo
          booking)
        </div>
      )}
      <div className="two-col compact">
        <div>
          <h3>Assignment</h3>
          {a ? (
            <p>
              <b>{a.crew_name}</b> ·{" "}
              {a.kind === "meeting" ? "Customer meeting" : "On-site dispatch"} ·{" "}
              {assignmentStatus(a.status)}
            </p>
          ) : (
            <p>{open ? "No crew assigned yet." : "Closed without an active assignment."}</p>
          )}
          {billing && (
            <p className="small-note">
              Billing questions have no crew: the dispatcher answers the
              customer through the request replies and resolves the incident.
            </p>
          )}
        </div>
        <div>
          <h3>Incident log</h3>
          <div className="timeline ops-log">
            {sortedLog.map((entry, index) => (
              <div key={index}>
                <b>{logAction(entry.action)}</b>
                <span>{entry.detail}</span>
                <small>
                  {entry.actor} · {when(entry.created_at)}
                </small>
              </div>
            ))}
            {!sortedLog.length && <p className="muted">No entries yet.</p>}
          </div>
        </div>
      </div>
      <div className="ops-actions" aria-live="polite">
        {error && <p className="error">{friendlyError(error)}</p>}
        {ok && <div className="info-box">{ok}</div>}
        {role === "dispatcher" && open && (
          <>
            <h3>Assign a crew</h3>
            {a ? (
              <p className="small-note">
                {a.crew_name} already has this incident. Resolve it to free the
                crew.
              </p>
            ) : billing ? (
              <div className="info-box">
                Billing questions are never given to a crew. Answer the
                customer in Requests, then mark the incident resolved.
              </div>
            ) : (
              <>
                <div className="ops-assign-form">
                  <label>
                    Crew
                    <select
                      value={crew}
                      onChange={(event) => setCrew(event.target.value)}
                    >
                      <option value="">
                        {choices.some((c) => c.available)
                          ? "Choose an available crew"
                          : choices.length
                            ? "Every eligible crew is busy"
                            : "No crew covers this incident"}
                      </option>
                      {choices.map((c) => (
                        <option key={c.id} value={c.id} disabled={!c.available}>
                          {c.name}
                          {c.available ? "" : " — busy on a dispatch"}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    className="btn secondary"
                    disabled={!crew || Boolean(busy)}
                    onClick={async () => {
                      const name = choices.find((c) => c.id === crew)?.name;
                      if (
                        await run(
                          "assign",
                          () => api.assignIncident(i.incident_id, crew),
                          `${name} assigned. Demo only: no team was contacted.`,
                        )
                      )
                        setCrew("");
                    }}
                  >
                    {busy === "assign" ? "Assigning…" : "Assign crew"}
                  </button>
                  <button
                    className="btn secondary"
                    disabled={Boolean(busy)}
                    onClick={() =>
                      run(
                        "auto",
                        () => api.assignIncident(i.incident_id),
                        (result) =>
                          `${result.assignment?.crew_name || "A crew"} assigned automatically. Demo only: no team was contacted.`,
                      )
                    }
                  >
                    {busy === "auto" ? "Assigning…" : "Assign automatically"}
                  </button>
                </div>
                <p className="small-note">
                  Eligible: same area as the site, the incident type in the
                  crew's skills, and no active on-site dispatch.
                </p>
              </>
            )}
          </>
        )}
        {role === "technician" && open && (
          <>
            <h3>
              Your crew
              {myCrews.length ? ` · ${myCrews.map((c) => c.name).join(", ")}` : ""}
            </h3>
            {a && !mine ? (
              <div className="info-box">
                Crew {a.crew_name} is assigned to this incident; only that crew
                can act on it.
              </div>
            ) : billing ? (
              <div className="info-box">
                Billing questions are answered by the PPC dispatcher; no crew
                visit is needed.
              </div>
            ) : !mine && !myEligible.length ? (
              <div className="info-box">
                None of your crews covers this incident's area and type.
              </div>
            ) : (
              <>
                <p className="small-note">
                  Demo actions only: no real team, customer or calendar is
                  contacted.
                </p>
                <div className="button-row">
                  <button
                    className="btn yellow"
                    disabled={Boolean(busy) || a?.status === "team_sent"}
                    onClick={() =>
                      run(
                        "send",
                        () => api.sendTeam(i.incident_id),
                        "Team marked as on the way. Your crew is now unavailable for other dispatches.",
                      )
                    }
                  >
                    <Truck size={16} />{" "}
                    {a?.status === "team_sent"
                      ? "Team on its way"
                      : busy === "send"
                        ? "Sending…"
                        : "Send the team"}
                  </button>
                </div>
                <form
                  className="ops-meeting-form mt"
                  onSubmit={(event) => {
                    event.preventDefault();
                    const slot = meetingWindow(
                      meeting.date,
                      meeting.start,
                      meeting.end,
                    );
                    if (slot.error) {
                      setOk(null);
                      setError(new Error(slot.error));
                      return;
                    }
                    run(
                      "meeting",
                      () =>
                        api.scheduleMeeting(
                          i.incident_id,
                          slot.start,
                          slot.end,
                        ),
                      `Meeting booked for ${meetingLabel(slot.start, slot.end)}. The customer sees it on their request.`,
                    );
                  }}
                >
                  <label>
                    Meeting date
                    <input
                      type="date"
                      required
                      value={meeting.date}
                      onChange={(event) =>
                        setMeeting({ ...meeting, date: event.target.value })
                      }
                    />
                  </label>
                  <label>
                    Start (Bucharest)
                    <input
                      type="time"
                      required
                      value={meeting.start}
                      onChange={(event) =>
                        setMeeting({ ...meeting, start: event.target.value })
                      }
                    />
                  </label>
                  <label>
                    End (Bucharest)
                    <input
                      type="time"
                      required
                      value={meeting.end}
                      onChange={(event) =>
                        setMeeting({ ...meeting, end: event.target.value })
                      }
                    />
                  </label>
                  <button className="btn secondary" disabled={Boolean(busy)}>
                    <CalendarDays size={16} />{" "}
                    {busy === "meeting" ? "Booking…" : "Allocate meeting"}
                  </button>
                </form>
                <p className="small-note">
                  Times are Europe/Bucharest local time; at most 4 hours. Your
                  crew's meetings may not overlap.
                </p>
              </>
            )}
          </>
        )}
        {role === "supervisor" && (
          <p className="small-note">
            Managers read this incident; only the PPC dispatcher assigns crews.
          </p>
        )}
        {open &&
          (role !== "technician" || mine) && (
            <div className="mt">
              <button
                className="btn dark"
                disabled={Boolean(busy)}
                onClick={() =>
                  run(
                    "resolve",
                    () => api.resolveIncident(i.incident_id),
                    a
                      ? `Marked resolved. ${a.crew_name} is available again.`
                      : "Marked resolved.",
                  )
                }
              >
                <CheckCircle2 size={16} />{" "}
                {busy === "resolve" ? "Resolving…" : "Mark resolved"}
              </button>
            </div>
          )}
        {!open && <p className="small-note">This incident is resolved.</p>}
      </div>
    </Modal>
  );
}

/* -------------------------------- Teams -------------------------------- */

export function TeamsPage({ api, user, aliases, onOpenRequest, onError, reload }) {
  const dispatcher = user.role === "dispatcher";
  const teams = usePolled((signal) => api.opsTeams(signal), `teams:${reload}`, onError);
  const incidents = usePolled(
    (signal) => api.opsIncidents("all", signal),
    `teams-incidents:${reload}`,
    onError,
  );
  const [selected, setSelected] = useState(null);
  const rows = useMemo(
    () =>
      teams.data
        ? toAssignmentRows(teams.data.assignments, incidents.data || [], aliases)
        : [],
    [teams.data, incidents.data, aliases],
  );
  const crews = useMemo(
    () =>
      teams.data
        ? toCrewSummaries(teams.data.crews, teams.data.assignments)
        : [],
    [teams.data],
  );
  const labels = useMemo(() => incidentLabels(incidents.data), [incidents.data]);
  const areaAliases = Object.values(aliases);
  const refreshAll = () => {
    teams.refresh();
    incidents.refresh();
  };
  if (teams.error && !teams.data)
    return <OpsNotice error={teams.error} onRetry={teams.refresh} />;
  if (!teams.data)
    return <section className="card empty">Loading crews and assignments…</section>;
  return (
    <>
      <section className="card">
        <div className="section-head">
          <div>
            <h3>Assignment report by incident</h3>
            <p className="muted">
              {scopeLabel(areaAliases)} · safety tier first, then age ·
              synthetic incidents and crews
            </p>
          </div>
          <Pill>{rows.length} rows</Pill>
        </div>
        <OpsNotice error={incidents.error} onRetry={incidents.refresh} />
        {!dispatcher && (
          <div className="info-box">
            Read-only report. Only the PPC dispatcher assigns crews; technicians
            send their team, book customer meetings and resolve their cases.
          </div>
        )}
        <AssignmentReport rows={rows} onOpen={setSelected} />
      </section>
      <section className="mt">
        <div className="section-head">
          <h3>Crews</h3>
          <Pill>{crews.length}</Pill>
        </div>
        {crews.length ? (
          <CrewSummary crews={crews} />
        ) : (
          <div className="card empty">No crews work in your areas.</div>
        )}
      </section>
      {dispatcher && (
        <section className="card mt ops-tools">
          <div className="section-head">
            <div>
              <div className="eyebrow">DISPATCHER TOOLS</div>
              <h3>Assign available crews</h3>
              <p className="muted">
                {teams.data.unassigned_incidents} open incident
                {teams.data.unassigned_incidents === 1 ? "" : "s"} without a
                crew. Assign by severity gives each one, P0 first, to the first
                eligible free crew until crews run out. Billing questions are
                never given to a crew.
              </p>
            </div>
          </div>
          <AutoDispatch
            api={api}
            labels={labels}
            onDone={refreshAll}
            onError={onError}
          />
        </section>
      )}
      {selected && (
        <IncidentModal
          api={api}
          user={user}
          incidentId={selected}
          crews={teams.data.crews}
          aliases={aliases}
          onClose={() => setSelected(null)}
          onChanged={refreshAll}
          onOpenRequest={onOpenRequest}
          onError={onError}
          reload={reload}
        />
      )}
    </>
  );
}

/* ------------------------------- Revenue ------------------------------- */

export function RevenuePage({ api, onError, reload }) {
  const revenue = usePolled(
    (signal) => api.opsRevenue(signal),
    `revenue:${reload}`,
    onError,
  );
  const report = useMemo(
    () => (revenue.data ? toRevenueReport(revenue.data) : null),
    [revenue.data],
  );
  if (revenue.error && !report)
    return <OpsNotice error={revenue.error} onRetry={revenue.refresh} />;
  if (!report)
    return <section className="card empty">Loading the revenue estimate…</section>;
  return (
    <>
      <OpsNotice error={revenue.error} onRetry={revenue.refresh} />
      <RevenueView
        report={report}
        scopeLabel={scopeLabel(revenue.data.by_area.map((a) => a.alias))}
      />
    </>
  );
}
