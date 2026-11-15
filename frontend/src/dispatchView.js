// Pure helpers for the dispatcher home and the manager map: triage list, automation
// summary (what the optimiser did itself, what waits for approval, what needs a person),
// priority counts and crew status lines. No React, no fetch; every figure is the server's.
import {
  BANDS,
  activityText,
  attentionBadge,
  caseTitle,
  conditionText,
  deadlineText,
  progressText,
  reasonLines,
  shortSiteName,
  telemetryBadge,
  verdictText,
  workflowText,
} from "./opsView.js";
import { localTime } from "./planView.js";

/** Customer requests still waiting for a first reply: danger first, then oldest first. */
export function triageItems(requests = [], limit = 5) {
  return requests
    .filter((r) => r.status === "awaiting_review")
    .sort(
      (a, b) =>
        (b.priority === "immediate_danger") - (a.priority === "immediate_danger") ||
        String(a.created_at).localeCompare(String(b.created_at)),
    )
    .slice(0, limit)
    .map((r) => ({
      id: r.request_id,
      danger: r.priority === "immediate_danger",
      label: r.request_label,
      site: shortSiteName(r.site_alias),
      from: r.requested_by,
      at: r.created_at,
      text: r.description.length > 140 ? `${r.description.slice(0, 137)}…` : r.description,
      hasVideo: Boolean(r.media),
      incidentId: r.incident_id,
    }));
}

/** Count of requests awaiting review (all, not just the ones shown). */
export const triageCount = (requests = []) => requests.filter((r) => r.status === "awaiting_review").length;

/**
 * Open cases per priority band: the server's episode counts when the projection has them,
 * otherwise counted from the queue rows. Always returns every band (0 when none).
 */
export function priorityCounts(counts, rows = []) {
  const server = counts?.episodes_by_band;
  return BANDS.map((band) => ({
    band,
    count: server ? Number(server[band] || 0) : rows.filter((r) => r.band === band).length,
  }));
}

/**
 * What the optimiser did and what is left to people, from a CrewPlanView (or null).
 * `autoResult` is the last "Assign by severity" result ({assigned[], skipped[]}) or null.
 */
export function automationSummary(plan, autoResult = null) {
  const automated = [];
  const approval = [];
  const person = [];
  if (autoResult)
    automated.push(
      `Assign by severity: ${autoResult.assigned.length} simple case${autoResult.assigned.length === 1 ? "" : "s"} given to a free qualified crew${autoResult.skipped.length ? `, ${autoResult.skipped.length} left for you` : ""}`,
    );
  if (autoResult?.skipped?.length)
    person.push(`${autoResult.skipped.length} case${autoResult.skipped.length === 1 ? "" : "s"} had no free eligible crew`);
  if (!plan) return { automated, approval, person, verdict: null, empty: true };
  const field = plan.visits?.length || 0;
  const remote = plan.remote_items?.length || 0;
  const monitoring = plan.monitoring?.length || 0;
  const unassigned = plan.unassigned || [];
  if (field || remote)
    automated.push(
      `Ordered ${field} field visit${field === 1 ? "" : "s"} and ${remote} remote job${remote === 1 ? "" : "s"} by severity, skills, shifts and travel time`,
    );
  if (monitoring)
    automated.push(`${monitoring} case${monitoring === 1 ? "" : "s"} kept on monitoring only (never sent to the field)`);
  if (plan.status === "draft" || plan.status === "reviewed")
    approval.push(
      plan.status === "draft"
        ? "Review the plan, then Apply it: nothing is assigned until a dispatcher approves"
        : "Plan reviewed: press Apply to create the assignments",
    );
  if (plan.status === "applied")
    automated.push(`Plan applied by ${plan.approval?.applied_by || "a dispatcher"}: ${plan.applied_assignment_ids?.length ?? 0} assignment(s) created`);
  for (const x of plan.urgent_exceptions || [])
    approval.push(`${x.band} case needs an immediate decision (${String(x.reason).replaceAll("_", " ")})`);
  for (const u of unassigned) {
    const why = reasonLines(u.reasons).general[0] || "see the reasons below";
    person.push(`${u.band} ${caseTitle(u.title)} cannot be assigned: ${why.replace(/^./, (c) => c.toLowerCase())}`);
  }
  return {
    automated,
    approval,
    person,
    verdict: plan.comparison ? verdictText(plan.comparison.verdict) : null,
    empty: false,
  };
}

/** One compact line per crew for the dispatcher's crew status list. */
export function crewStatusRows(teams) {
  return (teams?.crews || []).map((crew) => {
    const a = crew.active_assignment;
    const remote = crew.profile?.kind === "remote_desk";
    let state = "Available",
      tone = "green",
      detail = remote ? "Remote desk: no travel" : "Free for the next job";
    if (!crew.available) {
      tone = "orange";
      state = a ? (a.status === "team_sent" ? "On the way" : "Busy") : "Busy";
      detail = a ? `${a.tier} · ${shortSiteName(a.site_alias)}` : "On an on-site dispatch";
    }
    return {
      id: crew.crew_id,
      name: crew.name,
      kind: remote ? "Remote desk" : "Field crew",
      shift: crew.shift,
      members: crew.members,
      state,
      tone,
      detail,
    };
  });
}

/** Queue rows for the compact home list, in server order, active work first. */
export function topQueue(rows = [], limit = 6) {
  return rows.slice(0, limit);
}

/**
 * Open tickets per site from a QueueView: { siteId: [{ id, band, title, workflow, deadline,
 * updatedAt, crew }] } in the server's rank order. A shared episode lists on each of its sites.
 */
export function ticketsBySite(queue) {
  const out = {};
  for (const item of queue?.items || []) {
    const i = item.incident;
    const ids = item.episode?.site_ids?.length ? item.episode.site_ids : [i.site_id];
    const ticket = {
      id: i.incident_id,
      band: item.rank.band,
      title: caseTitle(i.title, i.site_alias),
      workflow: item.workflow,
      deadline: deadlineText(item.rank, queue.rank_as_of).text,
      updatedAt: i.updated_at,
      crew: i.assignment?.crew_name || null,
    };
    for (const id of ids) (out[id] ||= []).push(ticket);
  }
  return out;
}

const bandOrder = (band) => {
  const i = BANDS.indexOf(band);
  return i < 0 ? BANDS.length : i;
};
const latest = (...values) => values.filter(Boolean).sort().at(-1) || null;

/** Complete list of sites in scope (mapped and unmapped) for the live list view. */
export function siteListRows(map, tickets = {}) {
  const sites = [...(map?.status_sites || []), ...(map?.unmapped || [])];
  return sites
    .map((s) => {
      const list = tickets[s.site_id] || [];
      const lastData = latest(...(s.telemetry?.sources || []).map((x) => x.last_observed_at));
      const crew = s.crew?.crew_name
        ? `${s.crew.crew_name}${s.crew.progress ? ` · ${progressText(s.crew.progress)}` : ""}${s.crew.eta ? ` · ETA ${localTime(s.crew.eta)} (estimate)` : ""}`
        : list.find((t) => t.crew)?.crew || null;
      return {
        id: s.site_id,
        name: shortSiteName(s.alias),
        fullName: s.alias,
        area: s.area_alias || s.area_id || "No area",
        areaId: s.area_id || "none",
        segment: s.segment,
        mapped: Boolean(s.position),
        priority: s.highest_priority || null,
        condition: conditionText(s.condition),
        conditionNote: s.condition_note || null,
        attention: attentionBadge(s.attention),
        telemetry: telemetryBadge(s.telemetry?.state),
        workflow: workflowText(s.workflow),
        tickets: list,
        crew,
        lastData,
        lastCase: latest(...list.map((t) => t.updatedAt)),
      };
    })
    .sort(
      (a, b) =>
        bandOrder(a.priority) - bandOrder(b.priority) ||
        b.tickets.length - a.tickets.length ||
        a.name.localeCompare(b.name, "en", { numeric: true }),
    );
}

/** Site ids to show given the chosen bands, area and "only sites with open cases". */
export function visibleSiteSet(rows, { bands = [], area = "all", onlyIssues = false } = {}) {
  if (!bands.length && area === "all" && !onlyIssues) return null;
  return new Set(
    rows
      .filter(
        (r) =>
          (!bands.length || bands.includes(r.priority || "none")) &&
          (area === "all" || r.areaId === area) &&
          (!onlyIssues || r.priority),
      )
      .map((r) => r.id),
  );
}

export { activityText, progressText, localTime };
