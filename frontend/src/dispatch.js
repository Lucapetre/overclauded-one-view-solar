// Pure crew assignment, technician actions and the teams report for the workflow demo.
// Every function works on a plain db object (the shape of `seed()`), so the UI can call
// it inside `mutate()` and tests can call it on `seed()`. Actions throw an Error with a
// plain message when they are not allowed; nothing is saved in that case.
import {
  ACTIVE_DISPATCH,
  canSee,
  rank,
  routeRequest,
  sites,
} from "./domain.js";

export const TIERS = ["P0", "P1", "P2", "P3"];
export const CLOSED = ["Resolved", "Closed"];
const nowIso = () => new Date().toISOString();
const siteOf = (siteId) => sites.find((s) => s.id === siteId);
export const isOpen = (incident) => !CLOSED.includes(incident.status);
const kindOf = (a) => a.kind || "dispatch";

/** Appends one entry to an incident's log (its `timeline`). */
export function logIncident(incident, text, actor, time = nowIso()) {
  incident.timeline = incident.timeline || [];
  incident.timeline.push({ text, actor, time });
  incident.revision = (incident.revision || 1) + 1;
}

export function crewByName(db, name) {
  return (db.crews || []).find((c) => c.name === name) || null;
}
/** The area a technician works in: the area of his crew. */
export function technicianArea(db, user) {
  return crewByName(db, user?.crew)?.area || user?.area || null;
}
/** Incidents a user may see. Technicians see every incident in their crew's area. */
export function visibleIncidents(db, user) {
  if (user?.role === "technician") {
    const area = technicianArea(db, user);
    return rank(db.incidents.filter((i) => siteOf(i.site)?.area === area));
  }
  return rank(db.incidents.filter((i) => canSee(user, i.site)));
}
/** The areas a staff user works in. */
export function scopeAreas(db, user) {
  if (!user) return [];
  if (user.role === "ceo") return ["North", "Central", "South"];
  if (user.role === "technician") return [technicianArea(db, user)];
  return [user.area];
}

export function activeDispatch(db, incidentId) {
  return (
    db.assignments.find(
      (a) =>
        a.incident === incidentId &&
        kindOf(a) === "dispatch" &&
        ACTIVE_DISPATCH.includes(a.status),
    ) || null
  );
}
/** The crew's active dispatch assignment, or null when the crew is available. */
export function crewBusy(db, crewName) {
  return (
    db.assignments.find(
      (a) =>
        a.crew === crewName &&
        kindOf(a) === "dispatch" &&
        ACTIVE_DISPATCH.includes(a.status),
    ) || null
  );
}
export const meetingsFor = (db, incidentId) =>
  db.assignments.filter(
    (a) => a.incident === incidentId && kindOf(a) === "meeting",
  );

/**
 * Crews qualified for an incident: same area as the site and the incident family in
 * their skills. Billing is never crew work. With `availableOnly` (default) busy crews
 * are left out; otherwise each entry says whether it is free.
 */
export function eligibleCrews(db, incident, { availableOnly = true } = {}) {
  if (!incident || incident.family === "Billing") return [];
  const area = siteOf(incident.site)?.area;
  return (db.crews || [])
    .filter((c) => c.area === area && c.skills.includes(incident.family))
    .map((crew) => ({ crew, busyWith: crewBusy(db, crew.name) }))
    .filter((item) => !availableOnly || !item.busyWith)
    .map((item) => (availableOnly ? item.crew : item));
}

/** Why an open incident cannot be assigned right now, or null when it can. */
export function skipReason(db, incident) {
  if (incident.family === "Billing")
    return "Billing question: answered by the dispatcher, not a crew";
  if (activeDispatch(db, incident.id)) return "Already has an active crew";
  const all = eligibleCrews(db, incident, { availableOnly: false });
  if (!all.length) {
    const area = siteOf(incident.site)?.area;
    return `No ${area} crew covers ${incident.family}`;
  }
  if (all.every((item) => item.busyWith))
    return `No crew free: ${all
      .map((item) => `${item.crew.name} is on ${item.busyWith.incident}`)
      .join(", ")}`;
  return null;
}

function requireDispatcher(user, incident) {
  if (user?.role !== "dispatcher")
    throw Error("Only the PPC dispatcher can assign crews.");
  if (incident && siteOf(incident.site)?.area !== user.area)
    throw Error("This incident is outside your area.");
}
function findIncident(db, id) {
  const incident = db.incidents.find((i) => i.id === id);
  if (!incident) throw Error("Incident not found.");
  return incident;
}

/** Dispatcher assigns an eligible, available crew to one incident. */
export function assignCrew(db, user, incidentId, crewName, now = nowIso(), how = "manual") {
  const incident = findIncident(db, incidentId);
  requireDispatcher(user, incident);
  if (!isOpen(incident)) throw Error("This incident is already resolved.");
  if (incident.family === "Billing")
    throw Error("Billing questions are answered by the dispatcher, not a crew.");
  if (activeDispatch(db, incidentId))
    throw Error("This incident already has an active crew.");
  const crew = eligibleCrews(db, incident).find((c) => c.name === crewName);
  if (!crew) throw Error(`${crewName} is not eligible or not available.`);
  const assignment = {
    id: `A-${incidentId}-${db.assignments.length + 1}`,
    kind: "dispatch",
    incident: incidentId,
    site: incident.site,
    area: crew.area,
    crew: crew.name,
    status: "Assigned",
    assignedBy: user.name,
    assignedAt: now,
    how,
  };
  db.assignments.push(assignment);
  incident.status = "Crew assigned";
  logIncident(
    incident,
    `${how === "auto" ? "Assigned by severity" : "Crew assigned"}: ${crew.name}`,
    user.name,
    now,
  );
  return assignment;
}

/**
 * Walks open, unassigned incidents in the dispatcher's area in severity order
 * (P0, P1, P2, P3; oldest first within a tier) and gives each one an eligible free
 * crew until none are free. Returns what was assigned and what was skipped, and why.
 */
export function autoAssign(db, user, now = nowIso()) {
  requireDispatcher(user);
  const queue = rank(
    db.incidents.filter(
      (i) =>
        isOpen(i) &&
        siteOf(i.site)?.area === user.area &&
        !activeDispatch(db, i.id),
    ),
  );
  const assigned = [],
    skipped = [];
  for (const incident of queue) {
    const reason = skipReason(db, incident);
    if (reason) {
      skipped.push({ incident: incident.id, tier: incident.tier, reason });
      continue;
    }
    const [crew] = eligibleCrews(db, incident);
    assigned.push(assignCrew(db, user, incident.id, crew.name, now, "auto"));
  }
  return { assigned, skipped };
}

function requireTechnician(db, user, incident) {
  if (user?.role !== "technician" || !crewByName(db, user.crew))
    throw Error("Only a crew technician can do this.");
  if (siteOf(incident.site)?.area !== technicianArea(db, user))
    throw Error("This incident is outside your crew's area.");
  return crewByName(db, user.crew);
}

/** Technician sends his crew to the site now: the dispatch becomes "Team sent". */
export function sendTeam(db, user, incidentId, now = nowIso()) {
  const incident = findIncident(db, incidentId);
  const crew = requireTechnician(db, user, incident);
  if (!isOpen(incident)) throw Error("This incident is already resolved.");
  if (incident.family === "Billing")
    throw Error("Billing questions do not need a crew visit.");
  const busy = crewBusy(db, crew.name);
  if (busy && busy.incident !== incidentId)
    throw Error(`${crew.name} is already on ${busy.incident}. Resolve it first.`);
  let assignment = activeDispatch(db, incidentId);
  if (assignment && assignment.crew !== crew.name)
    throw Error(`${assignment.crew} is already assigned to this incident.`);
  if (assignment?.status === "Team sent")
    throw Error("Your team is already on the way.");
  if (!assignment) {
    if (!crew.skills.includes(incident.family))
      throw Error(`${crew.name} does not cover ${incident.family}.`);
    assignment = {
      id: `A-${incidentId}-${db.assignments.length + 1}`,
      kind: "dispatch",
      incident: incidentId,
      site: incident.site,
      area: crew.area,
      crew: crew.name,
      status: "Team sent",
      assignedBy: user.name,
      assignedAt: now,
      how: "technician",
    };
    db.assignments.push(assignment);
  }
  assignment.status = "Team sent";
  assignment.sentAt = now;
  incident.status = "Team sent";
  logIncident(incident, `Team sent on site: ${crew.name}`, user.name, now);
  return assignment;
}

const minutes = (hhmm) => {
  const m = /^(\d{2}):(\d{2})$/.exec(hhmm || "");
  return m ? Number(m[1]) * 60 + Number(m[2]) : NaN;
};

/** Books a customer meeting for an incident; overlapping meetings for the crew are rejected. */
export function scheduleMeeting(db, user, incidentId, { date, start, end }, now = nowIso()) {
  const incident = findIncident(db, incidentId);
  const crew = requireTechnician(db, user, incident);
  if (!isOpen(incident)) throw Error("This incident is already resolved.");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date || "")) throw Error("Choose a date.");
  const from = minutes(start),
    to = minutes(end);
  if (!Number.isFinite(from) || !Number.isFinite(to))
    throw Error("Choose a start and end time.");
  if (to <= from) throw Error("The meeting must end after it starts.");
  const clash = db.assignments.find(
    (a) =>
      kindOf(a) === "meeting" &&
      a.crew === crew.name &&
      a.status !== "Cancelled" &&
      a.date === date &&
      minutes(a.start) < to &&
      from < minutes(a.end),
  );
  if (clash)
    throw Error(
      `${crew.name} already has a meeting ${clash.date} ${clash.start}–${clash.end} (${clash.incident}).`,
    );
  const meeting = {
    id: `M-${incidentId}-${db.assignments.length + 1}`,
    kind: "meeting",
    incident: incidentId,
    site: incident.site,
    area: crew.area,
    crew: crew.name,
    status: "Scheduled",
    date,
    start,
    end,
    assignedBy: user.name,
    assignedAt: now,
  };
  db.assignments.push(meeting);
  if (!activeDispatch(db, incidentId)) incident.status = "Meeting booked";
  logIncident(
    incident,
    `Meeting booked with the customer: ${date} ${start}–${end} · ${crew.name}`,
    user.name,
    now,
  );
  for (const visit of db.visits || [])
    if (visit.incident === incidentId) visit.status = "Meeting booked";
  return meeting;
}

/** Technician marks his crew's incident resolved; the crew becomes available again. */
export function resolveIncident(db, user, incidentId, note = "", now = nowIso()) {
  const incident = findIncident(db, incidentId);
  const crew = requireTechnician(db, user, incident);
  const assignment = activeDispatch(db, incidentId);
  if (!assignment || assignment.crew !== crew.name)
    throw Error("Only the crew working on this incident can resolve it.");
  assignment.status = "Completed";
  assignment.completedAt = now;
  incident.status = "Resolved";
  logIncident(
    incident,
    `Resolved by ${crew.name}${note.trim() ? ": " + note.trim() : ""}`,
    user.name,
    now,
  );
  return assignment;
}

/** Dispatcher cancels an active assignment or a scheduled meeting. */
export function cancelAssignment(db, user, assignmentId, now = nowIso()) {
  const assignment = db.assignments.find((a) => a.id === assignmentId);
  if (!assignment) throw Error("Assignment not found.");
  const incident = findIncident(db, assignment.incident);
  requireDispatcher(user, incident);
  if (["Completed", "Cancelled"].includes(assignment.status))
    throw Error("This assignment is already closed.");
  assignment.status = "Cancelled";
  if (kindOf(assignment) === "dispatch" && isOpen(incident))
    incident.status = "Reviewing";
  logIncident(
    incident,
    `${kindOf(assignment) === "meeting" ? "Meeting" : "Assignment"} cancelled: ${assignment.crew}`,
    user.name,
    now,
  );
  return assignment;
}

/** Request types that name a crew go to the crew of the customer's area. */
export function routeVisit(requestTypeId, siteId, crewList) {
  const type = routeRequest(requestTypeId);
  if (type.routeTo === "PPC Triage") return "PPC Triage";
  const area = siteOf(siteId)?.area;
  return (
    crewList.find((c) => c.area === area && c.skills.includes(type.family))
      ?.name || "PPC Triage"
  );
}

const tierCounts = () => Object.fromEntries(TIERS.map((t) => [t, 0]));

/**
 * Report for the Teams page. Managers, dispatchers and technicians see exactly the
 * overall manager's rows and crews, filtered to their area: one source, `db`.
 * rows: [{ id, incident, title, tier, site, siteName, area, crew, kind, status,
 *          assignedBy, assignedAt, slot }]
 * crews: [{ name, area, owner, shift, skills, members, available, busyWith,
 *           open: {P0..P3}, completed: {P0..P3} }]
 */
export function teamsReport(db, user) {
  const areas = scopeAreas(db, user);
  const inScope = (siteId) => areas.includes(siteOf(siteId)?.area);
  const incidents = rank(db.incidents.filter((i) => inScope(i.site)));
  const rows = [];
  for (const incident of incidents) {
    const site = siteOf(incident.site);
    const base = {
      incident: incident.id,
      title: incident.title,
      tier: incident.tier,
      family: incident.family,
      site: incident.site,
      siteName: site?.name || incident.site,
      area: site?.area || "",
      incidentStatus: incident.status,
    };
    const list = db.assignments
      .filter((a) => a.incident === incident.id)
      .sort((a, b) => String(a.assignedAt).localeCompare(String(b.assignedAt)));
    if (!list.length && isOpen(incident))
      rows.push({
        ...base,
        id: `open-${incident.id}`,
        crew: null,
        kind: null,
        status: "Not assigned",
        assignedBy: null,
        assignedAt: null,
        slot: null,
      });
    for (const a of list)
      rows.push({
        ...base,
        id: a.id,
        crew: a.crew,
        kind: kindOf(a),
        status: a.status,
        assignedBy: a.assignedBy || null,
        assignedAt: a.assignedAt || null,
        slot: kindOf(a) === "meeting" ? `${a.date} ${a.start}–${a.end}` : null,
      });
  }
  const crews = (db.crews || [])
    .filter((c) => areas.includes(c.area))
    .map((c) => {
      const open = tierCounts(),
        completed = tierCounts();
      for (const a of db.assignments) {
        if (a.crew !== c.name || kindOf(a) !== "dispatch") continue;
        const tier = db.incidents.find((i) => i.id === a.incident)?.tier;
        if (!tier) continue;
        if (ACTIVE_DISPATCH.includes(a.status)) open[tier]++;
        if (a.status === "Completed") completed[tier]++;
      }
      const busy = crewBusy(db, c.name);
      return {
        name: c.name,
        area: c.area,
        owner: c.owner,
        shift: c.shift,
        skills: [...c.skills],
        members: [...c.members],
        available: !busy,
        busyWith: busy ? { incident: busy.incident, status: busy.status } : null,
        meetings: db.assignments.filter(
          (a) =>
            a.crew === c.name && kindOf(a) === "meeting" && a.status === "Scheduled",
        ).length,
        open,
        completed,
      };
    });
  return { areas, rows, crews };
}
