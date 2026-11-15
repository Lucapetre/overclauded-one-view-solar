// Pure adapters from the operations API (packages/contracts) to the prop shapes of the
// shared presentational components (map.jsx, ops.jsx), plus menu and wording rules.
// No money is recomputed here: revenue figures are the server's numbers.
import { slotLabel } from "./bucharestTime.js";
import { CLUSTERS, clusterOf } from "./geography.js";

export const TIERS = ["P0", "P1", "P2", "P3"];

/** Menu per role (product owner's decisions). The first page is the landing page. */
export const ROLE_PAGES = {
  customer: ["Home", "Plan", "Offers", "History", "Support", "Learn", "Account"],
  supervisor: [
    "Area Radar",
    "Incidents",
    "Teams",
    "Revenue",
    "Offers",
    "Sites",
    "History",
    "Account",
  ],
  dispatcher: [
    "Area Radar",
    "Incidents",
    "Teams",
    "Requests",
    "Sites",
    "History",
    "Account",
  ],
  technician: ["Agenda", "Incidents", "Requests", "Sites", "History", "Account"],
};
export const pagesFor = (role) => ROLE_PAGES[role] || ["Account"];

/**
 * Bottom navigation on phones: every page when they fit, otherwise the first
 * (max − 1) pages plus a "More" entry that opens the full menu.
 */
export function bottomNav(pages, active, max = 5) {
  if (pages.length <= max) return { items: pages, more: false, moreActive: false };
  const items = pages.slice(0, max - 1);
  return { items, more: true, moreActive: !items.includes(active) };
}

/** Same value → same reference, so polling does not re-render unchanged views. */
export const keepIfSame = (previous, next) =>
  previous !== undefined &&
  previous !== null &&
  JSON.stringify(previous) === JSON.stringify(next)
    ? previous
    : next;

export const tierTone = (tier) =>
  ["P0", "P1"].includes(tier) ? "orange" : tier === "P2" ? "yellow" : "";

/** Readable id: server UUIDs (32 hex) shortened; seeded ids kept. */
export const shortId = (id) =>
  /^[0-9a-f]{32}$/.test(id || "") ? `#${id.slice(0, 8)}` : id || "";

export const areaName = (areaId, aliases = {}) =>
  areaId ? aliases[areaId] || areaId : "No area";

const FRESHNESS = {
  fresh: "recent telemetry",
  stale: "telemetry stale",
  unavailable: "no telemetry received",
  future: "telemetry clock looks wrong",
  unknown_clock: "freshness could not be checked",
};

/** Marker status of a MapSite: open incident first, then recent feed, else stale. */
export function mapStatus(site) {
  if (site.open_incidents > 0)
    return { status: "incident", tier: site.worst_tier || null };
  return {
    status: site.freshness_status === "fresh" ? "ok" : "stale",
    tier: null,
  };
}

/**
 * OpsMap.sites → BucharestMap sites. The area name is the API's `area_alias`
 * (e.g. "Sector 6") or the alias from /areas; the cluster is the API's `cluster`
 * when the server sends it, else the shared fixture's cluster for that site id.
 */
export function toMapSites(sites = [], aliases = {}) {
  return sites.map((site) => {
    const { status, tier } = mapStatus(site);
    const incidents = site.open_incidents
      ? `${site.open_incidents} open synthetic incident${site.open_incidents === 1 ? "" : "s"} (worst ${site.worst_tier})`
      : "No open incident";
    return {
      id: site.site_id,
      name: site.alias,
      latitude: site.latitude,
      longitude: site.longitude,
      zone: site.zone,
      segment: site.segment,
      businessType: site.business_type,
      kwp: site.installed_kwp,
      status,
      tier,
      area: site.area_alias || areaName(site.area_id, aliases),
      cluster: "cluster" in site ? site.cluster || null : clusterOf(site.site_id),
      detail: `${incidents} · ${FRESHNESS[site.freshness_status] || site.freshness_status}`,
    };
  });
}

/** OpsMap.clusters → BucharestMap clusters; the shared fixture's list when absent. */
export const toMapClusters = (map) =>
  Array.isArray(map?.clusters) && map.clusters.length
    ? map.clusters.map((c) => ({
        id: c.id ?? c.cluster_id,
        name: c.name,
        area_id: c.area_id,
        kind: c.kind,
      }))
    : CLUSTERS;

/** CapacityView → FleetForecast areas. */
export const toForecastAreas = (capacity) =>
  (capacity?.areas || []).map((area) => ({
    name: area.alias,
    kwp: area.installed_kwp,
    sites: area.sites,
  }));

const round2 = (n) => Math.round(n * 100) / 100;

/** Backend RevenueView → the `report` prop of RevenueView (ops.jsx). */
export function toRevenueReport(view) {
  const totals = (t) => ({
    sites: t.sites,
    energySales: t.energy_sales_ron,
    exportPayments: t.export_payments_ron,
    serviceFees: t.service_fees_ron,
    net: t.net_revenue_ron,
  });
  const aliases = Object.fromEntries(view.by_area.map((a) => [a.area_id, a.alias]));
  const segment = (s) => ({ ...totals(s), share: s.share_of_net });
  const businessAccounts = view.business_accounts.map((b) => ({
    id: b.site_id,
    name: b.alias,
    area: areaName(b.area_id, aliases),
    zone: b.zone,
    businessType: b.business_type,
    kwp: b.installed_kwp,
    importKwh: b.monthly_import_kwh,
    exportKwh: b.monthly_export_kwh,
    energySales: b.energy_sales_ron,
    exportPayments: b.export_payments_ron,
    serviceFees: b.service_fees_ron,
    net: b.net_revenue_ron,
    importPrice: b.import_price_ron_kwh,
    exportPrice: b.export_price_ron_kwh,
    priceSource: b.price_source === "contract" ? "contract" : "default",
  }));
  return {
    totals: totals(view.totals),
    annualNet: view.annualized_net_revenue_ron,
    bySegment: {
      business: segment(view.by_segment.business),
      home: segment(view.by_segment.home),
    },
    byArea: view.by_area.map((a) => ({
      area: a.alias,
      ...totals(a),
      businessSites: a.business_sites,
      businessNet: a.business_net_revenue_ron,
      // Display split only: the server's net minus the server's business part.
      homeNet: round2(a.net_revenue_ron - a.business_net_revenue_ron),
    })),
    businessAccounts,
    sites: [],
    contractSites: businessAccounts.filter((b) => b.priceSource === "contract")
      .length,
    basis: view.basis,
  };
}

/** "Sector 6" or "3 areas · Sector 3, Sector 6, Ilfov". */
export function scopeLabel(aliases) {
  const list = aliases.filter(Boolean);
  if (!list.length) return "Your scope";
  if (list.length === 1) return list[0];
  return `${list.length} areas · ${list.join(", ")}`;
}

export const ASSIGNMENT_STATUS = {
  assigned: "Assigned",
  team_sent: "Team sent",
  meeting_scheduled: "Meeting booked",
  completed: "Completed",
  cancelled: "Cancelled",
};
export const INCIDENT_STATUS = {
  new: "New",
  assigned: "Crew assigned",
  team_sent: "Team sent",
  meeting_scheduled: "Meeting booked",
  resolved: "Resolved",
};
export const LOG_ACTIONS = {
  opened: "Opened",
  assigned: "Crew assigned",
  auto_assigned: "Assigned by severity",
  team_sent: "Team sent",
  meeting_scheduled: "Meeting booked",
  resolved: "Resolved",
  customer_follow_up: "Customer follow-up",
  staff_reply: "Staff reply",
  customer_video: "Customer video attached",
};
const humanize = (code) => {
  const text = String(code || "").replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
};
export const assignmentStatus = (s) => ASSIGNMENT_STATUS[s] || humanize(s);
export const incidentStatus = (s) => INCIDENT_STATUS[s] || humanize(s);
export const logAction = (a) => LOG_ACTIONS[a] || humanize(a);

const tierRank = (tier) => {
  const index = TIERS.indexOf(tier);
  return index < 0 ? TIERS.length : index;
};

/**
 * Assignment report rows: every assignment from TeamsView plus a "Not assigned"
 * row for each open incident without an active assignment, grouped by incident
 * in severity order (tier, then the incident's age), oldest assignment first.
 * `incidents` may include resolved ones (status=all); they only add site ids.
 */
export function toAssignmentRows(assignments = [], incidentList = [], aliases = {}) {
  const incidents = Object.fromEntries(incidentList.map((i) => [i.incident_id, i]));
  const rows = assignments.map((a) => ({
    id: a.assignment_id,
    incident: a.incident_id,
    incidentLabel: shortId(a.incident_id),
    title: a.incident_title,
    tier: a.tier,
    site: incidents[a.incident_id]?.site_id || "",
    siteName: a.site_alias,
    area: areaName(a.area_id, aliases),
    crew: a.crew_name,
    kind: a.kind,
    status: assignmentStatus(a.status),
    assignedBy: a.created_by,
    assignedAt: a.created_at,
    slot: a.kind === "meeting" ? slotLabel(a.scheduled_start, a.scheduled_end) : null,
    opened: incidents[a.incident_id]?.created_at || null,
  }));
  for (const i of incidentList)
    if (!i.assignment && i.status !== "resolved")
      rows.push({
        id: `open-${i.incident_id}`,
        incident: i.incident_id,
        incidentLabel: shortId(i.incident_id),
        title: i.title,
        tier: i.tier,
        site: i.site_id,
        siteName: i.site_alias,
        area: areaName(i.area_id, aliases),
        crew: null,
        kind: null,
        status: "Not assigned",
        assignedBy: null,
        assignedAt: null,
        slot: null,
        opened: i.created_at,
      });
  // Group per incident: an incident's first appearance (by severity) fixes its place.
  const order = new Map();
  for (const r of [...rows].sort(
    (a, b) =>
      tierRank(a.tier) - tierRank(b.tier) ||
      String(a.opened || a.assignedAt || "").localeCompare(
        String(b.opened || b.assignedAt || ""),
      ) ||
      a.incident.localeCompare(b.incident),
  ))
    if (!order.has(r.incident)) order.set(r.incident, order.size);
  return rows
    .sort(
      (a, b) =>
        order.get(a.incident) - order.get(b.incident) ||
        String(a.assignedAt || "~").localeCompare(String(b.assignedAt || "~")),
    )
    .map(({ opened, ...row }) => row);
}

/** TeamsView.crews → CrewSummary crews. Meetings come from the assignment report. */
export function toCrewSummaries(crews = [], assignments = []) {
  return crews.map((c) => {
    const active = c.active_assignment;
    return {
      id: c.crew_id,
      name: c.name,
      area: c.area_alias,
      owner: null,
      shift: c.shift,
      skills: [...c.skills],
      members: [...c.members],
      available: c.available,
      busyWith:
        !c.available && active
          ? {
              incident: `${active.tier} ${active.site_alias}`,
              status: assignmentStatus(active.status),
            }
          : !c.available
            ? { incident: "an on-site dispatch", status: "Busy" }
            : null,
      meetings: assignments.filter(
        (a) =>
          a.crew_name === c.name &&
          a.kind === "meeting" &&
          a.status === "meeting_scheduled",
      ).length,
      open: { ...c.report.open_by_tier },
      completed: { ...c.report.completed_by_tier },
    };
  });
}

/** Crews that may take this incident: same area, family in skills. Busy ones flagged. */
export function crewChoices(crews = [], incident) {
  if (!incident) return [];
  return crews
    .filter(
      (c) => c.area_id === incident.area_id && c.skills.includes(incident.family),
    )
    .map((c) => ({ id: c.crew_id, name: c.name, available: c.available }));
}

export const SKIP_REASONS = {
  no_eligible_crew:
    "no crew in this area covers this type of incident, so a person has to handle it",
  no_available_crew:
    "every crew that could take it is already on an on-site dispatch; try again when one finishes",
};
export const skipReason = (reason) => SKIP_REASONS[reason] || humanize(reason);

/** Plain words for the API's error codes; falls back to the server's message. */
export const FRIENDLY_ERRORS = {
  operations_required: "This page is for operations staff.",
  dispatcher_required: "Only a PPC dispatcher can assign crews.",
  technician_required: "Only a technician can do this.",
  supervisor_required: "Revenue is available to managers only.",
  manager_required: "Offers are managed by distributor managers only.",
  customer_required: "Offers can be accepted by customer accounts only.",
  crew_member_required:
    "Only a member of the assigned crew can mark this incident resolved.",
  already_assigned:
    "This incident already has a crew. The list has been refreshed.",
  crew_unavailable:
    "That crew is already on an on-site dispatch. Choose another crew or wait until it is free.",
  no_available_crew:
    "No eligible crew is free right now. Try again when a crew finishes its dispatch.",
  crew_not_eligible:
    "This crew does not work in the incident's area or does not cover this type of incident.",
  incident_resolved: "This incident is already resolved.",
  already_resolved: "This incident is already resolved.",
  assigned_to_other_crew: "Another crew is already assigned to this incident.",
  team_already_sent: "The team is already on its way.",
  invalid_meeting:
    "A meeting must end after it starts and last at most 4 hours.",
  meeting_overlap:
    "Your crew already has a meeting at that time. Choose another slot.",
  media_too_large: "The video is larger than 30 MB.",
  unsupported_media_type: "Use an MP4 or WebM video.",
  invalid_media: "The file is not a valid MP4 or WebM video.",
  media_not_allowed:
    "Videos cannot be attached to danger reports. Keep away from the equipment.",
  media_exists: "This request already has a video.",
  not_found: "This item is not in your scope or no longer exists.",
  // Phase (c) episodes, crew plans and agenda.
  episode_workflow_required:
    "Use Plan teams for this incident: correlated cases are assigned through a reviewed crew plan and closed from the case drawer.",
  plan_stale: "The situation changed — a new draft was computed. Review it, then apply again.",
  plan_already_applied: "This plan is already applied. Nothing was duplicated.",
  plan_superseded: "This plan was replaced by a newer draft. Open the latest plan.",
  plan_not_reviewed: "Review the plan before applying it.",
  plan_changed: "The plan's inputs no longer match. The latest plan has been loaded.",
  crew_double_booked:
    "A crew in this plan is already booked at that time. Propose a new plan.",
  dispatch_capability_required: "Applying needs dispatch capability.",
  planning_access_required:
    "Crew plans are visible to dispatch and supervisory accounts only.",
  assignment_changed:
    "This visit changed since you loaded it. The agenda has been refreshed; try again.",
  progress_not_forward: "Progress only moves forward: en route, on site, then done.",
  assignment_closed: "This visit is no longer active.",
  note_required: "Write a short note describing the outcome before marking it done.",
  invalid_expiry:
    "Choose an override expiry after the current replay time and at most 7 days ahead.",
  invalid_request: "Some fields are missing or out of range. Check the form and try again.",
};
const OFFLINE = "Unable to reach the service. Please try again.";
/** Always a full sentence ending in punctuation, so it can be embedded in text. */
export function friendlyError(error) {
  const code = error?.detail?.code;
  // A failed fetch (offline, server down) is a TypeError without an API envelope.
  const text =
    FRIENDLY_ERRORS[code] ||
    error?.detail?.message ||
    (error instanceof TypeError ? OFFLINE : error?.message) ||
    OFFLINE;
  return /[.!?…]$/.test(text.trim()) ? text : `${text.trim()}.`;
}

/** "12 min", "5 h", "3 days" since an ISO time. */
export function ageLabel(iso, now = Date.now()) {
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) return "—";
  const minutes = Math.max(0, Math.round((now - then) / 60000));
  if (minutes < 90) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h`;
  return `${Math.round(hours / 24)} days`;
}
