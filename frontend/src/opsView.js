// Pure adapters for the phase (c) operations API: ranked queue, status projection,
// map overlays (crews, routes), episode drawer, crew plan and technician agenda.
// No React and no fetch. Every value comes from the backend; nothing here re-ranks,
// re-plans or invents a healthy state. Missing data is "unknown", never green.
import { areaName } from "./opsData.js";
import { durationText, humanize, localDateTime, localTime, ron } from "./planView.js";

export const BANDS = ["P0", "P1", "P2", "P3"];
const bandIndex = (band) => {
  const i = BANDS.indexOf(band);
  return i < 0 ? BANDS.length : i;
};
export const bandTone = (band) =>
  band === "P0" || band === "P1" ? "orange" : band === "P2" ? "yellow" : "";

/* ------------------------------------------------------------------ labels */

/** "Synthetic site F1 (Fronius …)" → "Site F1"; other aliases unchanged. */
export function shortSiteName(alias) {
  const match = /^Synthetic site ([A-Za-z0-9-]+)/.exec(alias || "");
  return match ? `Site ${match[1]}` : alias || "Unknown site";
}

/** Case title without the trailing site alias the backend appends after ": ". */
export function caseTitle(title, siteAlias) {
  const text = String(title || "");
  if (siteAlias && text.endsWith(`: ${siteAlias}`))
    return text.slice(0, -(siteAlias.length + 2));
  const cut = text.indexOf(": Synthetic site ");
  return cut > 0 ? text.slice(0, cut) : text;
}

export const ATTENTION = {
  critical: { label: "Critical attention (P0)", tone: "orange" },
  high: { label: "High attention (P1)", tone: "orange" },
  elevated: { label: "Elevated attention (P2)", tone: "yellow" },
  monitor: { label: "Monitor (P3)", tone: "" },
  data_gap: { label: "Data gap: cannot assess", tone: "grey" },
  unknown: { label: "Unknown: rules not evaluated", tone: "grey" },
  none: { label: "No active issue under evaluated rules", tone: "" },
};
/** Attention badge; anything unrecognised is "unknown", never a healthy state. */
export const attentionBadge = (attention) =>
  ATTENTION[attention] || ATTENTION.unknown;

export const TELEMETRY = {
  fresh: { label: "Telemetry fresh", tone: "green", glyph: "" },
  partial: { label: "Telemetry partial", tone: "yellow", glyph: "½" },
  stale: { label: "Telemetry stale", tone: "orange", glyph: "…" },
  missing: { label: "Telemetry missing", tone: "orange", glyph: "∅" },
  access_error: { label: "Telemetry access error", tone: "orange", glyph: "×" },
};
const TELEMETRY_UNKNOWN = { label: "Telemetry unknown", tone: "grey", glyph: "?" };
export const telemetryBadge = (state) => TELEMETRY[state] || TELEMETRY_UNKNOWN;
/** Worst first; anything else (unknown) sorts before "fresh". */
export const TELEMETRY_SEVERITY = ["access_error", "missing", "stale", "partial", "fresh"];
const telemetryRank = (state) => {
  const i = TELEMETRY_SEVERITY.indexOf(state);
  return i < 0 ? TELEMETRY_SEVERITY.length - 1.5 : i;
};
/** Worst telemetry state of several sites; "unknown" when none is known. */
export function worstTelemetry(states) {
  const known = states.filter(Boolean);
  if (!known.length) return "unknown";
  return [...known].sort((a, b) => telemetryRank(a) - telemetryRank(b))[0];
}

export const CONDITION = {
  observed_active: "Active issue observed",
  suspected: "Issue suspected",
  no_active_issue_under_evaluated_rules: "No active issue under evaluated rules",
  not_evaluated: "Not evaluated (missing inputs)",
};
export const WORKFLOW = {
  needs_review: "Needs review",
  monitoring: "Monitoring",
  remote_triage: "Remote triage",
  field_action_needed: "Field action needed",
  proposed: "Crew proposed (draft plan)",
  assigned: "Crew assigned",
  en_route: "Crew en route",
  on_site: "Crew on site",
  resolved: "Resolved",
  none: "No workflow",
};
export const RESPONSIBILITY = {
  customer_installation_service: "Customer installation service",
  distributor_network_review: "Distributor network review",
  monitoring_provider: "Monitoring provider",
  unknown: "Responsibility unknown",
  not_assessed: "Not assessed (no episode)",
};
export const CONFIDENCE = {
  reported: "Reported by the device",
  corroborated: "Corroborated by independent sources",
  suspected: "Suspected",
  insufficient: "Insufficient evidence",
};
export const ACTION = {
  monitor: "Monitor only",
  remote_review: "Remote review",
  remote_troubleshooting: "Remote troubleshooting",
  field_visit: "Field visit",
  external_review: "External review (proposed, not sent)",
};
export const ACTIVITY = {
  ...ACTION,
  remote_review: "Remote review (desk)",
  remote_troubleshooting: "Remote troubleshooting (desk)",
};
export const PROGRESS = { en_route: "En route", on_site: "On site", done: "Done" };
const label = (table, code) => table[code] || humanize(code);
export const conditionText = (c) => label(CONDITION, c);
export const workflowText = (w) => label(WORKFLOW, w);
export const responsibilityText = (r) => label(RESPONSIBILITY, r);
export const confidenceText = (c) => label(CONFIDENCE, c);
export const actionText = (a) => label(ACTION, a);
export const activityText = (a) => label(ACTIVITY, a);
export const progressText = (p) => label(PROGRESS, p);

/* ------------------------------------------------------------- map markers */

const BAD_FEED = new Set(["stale", "missing", "access_error"]);

/**
 * Marker look for a SiteStatus. Precedence: an active priority (safety first) wins
 * the colour even when the feed is stale; a broken feed without an active issue is
 * a data gap; missing evaluation is unknown; only evaluated rules with a usable
 * feed and no active issue give the (non-green) "clear" look. The telemetry state
 * is always carried as a second badge when it is not fresh.
 */
export function markerStyle(status) {
  const band = status?.highest_priority || null;
  const tele = status?.telemetry?.state || null;
  const teleBadge = tele === "fresh" ? null : tele || "unknown";
  let tone, glyph;
  if (band) {
    tone = band === "P0" || band === "P1" ? "urgent" : band === "P2" ? "review" : "monitor";
    glyph = band;
  } else if (!tele || BAD_FEED.has(tele)) {
    tone = "gap";
    glyph = "!";
  } else if (
    status?.condition === "no_active_issue_under_evaluated_rules" &&
    status?.attention === "none"
  ) {
    tone = "clear";
    glyph = "–";
  } else {
    tone = "unknown";
    glyph = "?";
  }
  const attention = band
    ? ATTENTION[status.attention] && !["data_gap", "unknown", "none"].includes(status.attention)
      ? status.attention
      : { P0: "critical", P1: "high", P2: "elevated", P3: "monitor" }[band]
    : { gap: "data_gap", unknown: "unknown", clear: "none" }[tone];
  const parts = [
    attentionBadge(attention).label,
    telemetryBadge(tele).label.toLowerCase(),
    workflowText(status?.workflow || "none").toLowerCase(),
  ];
  return { tone, glyph, telemetry: teleBadge, label: parts.join(" · ") };
}

export const MARKER_LEGEND = [
  { tone: "urgent", glyph: "P1", label: "P0/P1 active issue" },
  { tone: "review", glyph: "P2", label: "P2 active issue" },
  { tone: "monitor", glyph: "P3", label: "P3 monitoring" },
  { tone: "gap", glyph: "!", label: "Data gap (feed stale, missing or access error)" },
  { tone: "unknown", glyph: "?", label: "Unknown (rules not evaluated)" },
  { tone: "clear", glyph: "–", label: "No active issue under evaluated rules (not a health certificate)" },
];

/** Legacy status for cluster summaries (map.jsx): incident / stale / ok. */
const legacyStatus = (status) =>
  status.highest_priority
    ? "incident"
    : status.telemetry?.state === "fresh"
      ? "ok"
      : "stale";

/**
 * OpsMap → BucharestMap sites. Uses the status projection (`status_sites`) when the
 * backend sends it, enriched with the compact demo's MapSite fields (zone, cluster,
 * business type); provider-scenario sites are positioned from `status_sites`
 * (site_placements). Sites without a position are not placed (see `unmapped`).
 * Falls back to plain MapSite markers for an older backend.
 */
export function toStatusMapSites(map, aliases = {}, legacy = null) {
  const sites = map?.sites || [];
  const status = map?.status_sites || [];
  const base = new Map(sites.map((s) => [s.site_id, s]));
  if (!status.length) return legacy ? legacy(sites, aliases) : [];
  const covered = new Set(status.map((s) => s.site_id));
  const out = status
    .filter((s) => s.position && Number.isFinite(s.position.latitude) && Number.isFinite(s.position.longitude))
    .map((s) => {
      const b = base.get(s.site_id);
      const marker = markerStyle(s);
      const lines = [
        conditionText(s.condition),
        s.condition_note,
        `${telemetryBadge(s.telemetry?.state).label} · ${workflowText(s.workflow)}`,
        s.crew?.crew_name
          ? `${s.crew.crew_name}${s.crew.progress ? ` · ${progressText(s.crew.progress)}` : ""}${s.crew.eta ? ` · ETA ${localTime(s.crew.eta)} (estimate)` : ""}`
          : null,
        s.episode_ids?.length
          ? `${s.episode_ids.length} active episode${s.episode_ids.length === 1 ? "" : "s"}`
          : null,
        s.position.fictional ? `${s.position.label || "Fictional demo point"} (fictional coordinates)` : s.position.label,
      ].filter(Boolean);
      return {
        id: s.site_id,
        name: b?.alias || shortSiteName(s.alias),
        fullName: s.alias,
        latitude: s.position.latitude,
        longitude: s.position.longitude,
        zone: b?.zone || null,
        segment: (b?.segment || s.segment) === "business" ? "business" : "home",
        businessType: b?.business_type || null,
        kwp: b?.installed_kwp ?? s.installed_kwp ?? null,
        status: legacyStatus(s),
        tier: s.highest_priority || null,
        area: s.area_alias || areaName(s.area_id, aliases),
        cluster: b ? b.cluster || null : null,
        marker,
        lines,
        episodeIds: s.episode_ids || [],
        detail: marker.label,
      };
    });
  // Compact sites the projection did not cover keep their plain marker.
  if (legacy) out.push(...legacy(sites.filter((s) => !covered.has(s.site_id)), aliases));
  return out;
}

/** Unmapped sites (no coordinates): never placed at (0,0) or near another site. */
export function unmappedSites(map) {
  return (map?.unmapped || []).map((s) => ({
    id: s.site_id,
    name: shortSiteName(s.alias),
    fullName: s.alias,
    area: s.area_alias || s.area_id || "No area",
    condition: conditionText(s.condition),
    telemetry: telemetryBadge(s.telemetry?.state).label,
    workflow: workflowText(s.workflow),
    priority: s.highest_priority || null,
  }));
}

/** Apply the queue's site selection to every map layer and its list/counts. */
export function filterMapView(map, siteIds) {
  if (!map || !siteIds) return map;
  const keep = (s) => siteIds.has(s.site_id);
  const status_sites = (map.status_sites || []).filter(keep);
  const unmapped = (map.unmapped || []).filter(keep);
  const rows = [...status_sites, ...unmapped];
  const routes = (map.routes || [])
    .map((route) => ({ ...route, stops: route.stops.filter(keep) }))
    .filter((route) => route.stops.length);
  const routedCrews = new Set(routes.map((route) => route.crew_id));
  return {
    ...map,
    sites: (map.sites || []).filter(keep),
    status_sites,
    unmapped,
    routes,
    crews: (map.crews || []).filter((crew) => routedCrews.has(crew.crew_id)),
    counts: {
      ...map.counts,
      sites: rows.length,
      mapped_sites: status_sites.length,
      unmapped_sites: unmapped.length,
      affected_sites: rows.filter((s) => s.episode_ids?.length).length,
      unique_episodes: new Set(rows.flatMap((s) => s.episode_ids || [])).size,
    },
  };
}

/* ------------------------------------------------------------------ routes */

/** Proposed (draft) routes are dashed; applied routes are solid. */
export function routeStyle(state, highlighted = false, dimmed = false) {
  const applied = state === "applied";
  return {
    color: applied ? "#2f4a3c" : "#b8860b",
    weight: highlighted ? 5 : 3,
    opacity: dimmed ? 0.3 : highlighted ? 1 : 0.8,
    dashArray: applied ? null : "8 7",
    label: applied ? "Applied route" : "Proposed route (draft)",
  };
}

const ROUTE_NOTE = "schematic, not road routing";

/**
 * OpsMap crews/routes → map overlays. Crews with a reported base get a marker
 * ("base location — not live GPS"); the remote desk has none. A route starts at
 * its crew's base when known and joins its stops in visit order with straight
 * (schematic) lines. `selected` = the selected incident id (its route is
 * highlighted, the others dimmed).
 */
export function toMapOverlays(map, selected = null) {
  const crews = (map?.crews || [])
    .filter((c) => c.kind !== "remote_desk" && c.position)
    .map((c) => ({
      id: c.crew_id,
      name: c.name,
      latitude: c.position.latitude,
      longitude: c.position.longitude,
      initials: crewInitials(c.name),
      label: `${c.name} · base location — not live GPS${c.location_reported_at ? ` · reported ${localDateTime(c.location_reported_at)}` : ""}`,
    }));
  const base = new Map(crews.map((c) => [c.id, c]));
  const names = new Map((map?.crews || []).map((c) => [c.crew_id, c.name]));
  const anySelected = Boolean(selected);
  const routes = (map?.routes || []).map((r, index) => {
    const stops = [...(r.stops || [])]
      .filter((s) => s.position)
      .sort((a, b) => a.sequence - b.sequence)
      .map((s) => ({
        sequence: s.sequence,
        incidentId: s.incident_id,
        siteId: s.site_id,
        latitude: s.position.latitude,
        longitude: s.position.longitude,
        label: `Visit ${s.sequence} · ${localTime(s.start_at)}–${localTime(s.finish_at)} (estimate)`,
      }));
    const start = base.get(r.crew_id);
    const points = [
      ...(start ? [[start.latitude, start.longitude]] : []),
      ...stops.map((s) => [s.latitude, s.longitude]),
    ];
    const highlighted = anySelected && stops.some((s) => s.incidentId === selected);
    const style = routeStyle(r.state, highlighted, anySelected && !highlighted);
    return {
      id: `${r.plan_id || "active"}:${r.crew_id}:${r.state}:${index}`,
      crewId: r.crew_id,
      crewName: names.get(r.crew_id) || r.crew_id,
      state: r.state,
      stops,
      points,
      highlighted,
      style,
      redacted: r.redacted_stops || 0,
      label: `${names.get(r.crew_id) || r.crew_id} · ${style.label.toLowerCase()} · ${ROUTE_NOTE}`,
      note: r.label,
    };
  });
  return { crews, routes };
}

export function crewInitials(name) {
  const words = String(name || "")
    .replace(/\(.*?\)/g, "")
    .split(/[^A-Za-z0-9]+/)
    .filter((w) => w && !["and", "the", "crew", "desk"].includes(w.toLowerCase()));
  return (words.slice(0, 2).map((w) => w[0].toUpperCase()).join("") || "C").slice(0, 2);
}

/* ------------------------------------------------------------------- queue */

/** Which section of the queue an item belongs to (field work stays apart). */
export function queueGroup(item) {
  const action = item?.episode?.action;
  if (!item?.episode) return "other";
  if (action === "field_visit") return "field";
  if (action === "remote_review" || action === "remote_troubleshooting") return "remote";
  if (action === "monitor") return "monitoring";
  return "review";
}
export const QUEUE_GROUPS = [
  { key: "field", title: "Field work", note: "Needs a qualified crew on site." },
  { key: "remote", title: "Remote review and troubleshooting", note: "Handled from the remote desk; not sent straight to a field crew." },
  { key: "review", title: "Reviews needing a decision", note: "Proposed for review by the responsible party; nothing is sent automatically." },
  { key: "monitoring", title: "Monitoring only", note: "No field visit or remote job; kept visible until a recovery rule clears it." },
  { key: "other", title: "Other cases", note: "Incidents without a correlated episode (compact demo or customer requests)." },
];

/** Assignment state of a queue row for filtering: unassigned / proposed / assigned / resolved. */
export function assignmentState(workflow, incident) {
  if (incident?.status === "resolved" || workflow === "resolved") return "resolved";
  if (["assigned", "en_route", "on_site"].includes(workflow) || incident?.assignment) return "assigned";
  if (workflow === "proposed") return "proposed";
  return "unassigned";
}
export const ASSIGNMENT_FILTER = {
  unassigned: "No crew",
  proposed: "In a draft plan",
  assigned: "Crew assigned",
  resolved: "Resolved",
};

/** "Overdue by 45 min" / "Due 15:30 (in 4 h)" / "No response deadline". */
export function deadlineText(rank, now) {
  if (!rank?.deadline_at) return { text: "No response deadline", overdue: false };
  const overdue = Number(rank.overdue_minutes) > 0;
  if (overdue)
    return {
      text: `Overdue by ${durationText(rank.overdue_minutes)} (due ${localTime(rank.deadline_at)})`,
      overdue: true,
    };
  const left = (Date.parse(rank.deadline_at) - Date.parse(now)) / 60000;
  return {
    text: `Due ${localDateTime(rank.deadline_at)}${Number.isFinite(left) && left > 0 ? ` (in ${durationText(left)})` : ""}${rank.deadline_mandatory ? " · mandatory" : ""}`,
    overdue: false,
  };
}

/** Analytical age: "12 min", "5 h", "3 days" (from the replay clock, not wall time). */
export function ageAt(iso, now) {
  const then = Date.parse(iso),
    at = Date.parse(now);
  if (!Number.isFinite(then) || !Number.isFinite(at)) return "—";
  const minutes = Math.max(0, Math.round((at - then) / 60000));
  if (minutes < 90) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours} h` : `${Math.round(hours / 24)} days`;
}

/**
 * QueueView (+ status sites by id) → queue rows, in the server's rank order.
 * Telemetry of a row is the worst state among the episode's sites; it is
 * "unknown" when the projection does not cover a site.
 */
export function toQueueRows(queue, statusSites = [], aliases = {}) {
  const status = new Map(statusSites.map((s) => [s.site_id, s]));
  const now = queue?.rank_as_of;
  return (queue?.items || []).map((item) => {
    const i = item.incident,
      e = item.episode,
      r = item.rank;
    const siteIds = e?.site_ids?.length ? [...e.site_ids] : [i.site_id];
    const sites = siteIds.map((id) => status.get(id)).filter(Boolean);
    const telemetry = sites.length === siteIds.length ? worstTelemetry(sites.map((s) => s.telemetry?.state)) : "unknown";
    const primary = status.get(i.site_id);
    const crew = sites.find((s) => s.crew)?.crew || null;
    const deadline = deadlineText(r, now);
    return {
      id: i.incident_id,
      position: r.position,
      band: r.band,
      computedBand: r.computed_band,
      overridden: Boolean(r.override) && r.band !== r.computed_band,
      bandLabel: r.band_label,
      title: caseTitle(i.title, i.site_alias),
      fullTitle: i.title,
      family: i.family,
      siteId: i.site_id,
      siteIds,
      siteNames: siteIds.map((id) => shortSiteName(status.get(id)?.alias || (id === i.site_id ? i.site_alias : id))),
      areaId: i.area_id,
      area: areaName(i.area_id, aliases),
      condition: primary?.condition || null,
      conditionNote: primary?.condition_note || null,
      telemetry,
      attention: primary?.attention || null,
      workflow: item.workflow,
      responsibility: e?.responsibility || "not_assessed",
      responsibilityBasis: e?.responsibility_basis || null,
      confidence: e?.confidence || null,
      confidenceBasis: e?.confidence_basis || null,
      action: e?.action || null,
      group: queueGroup(item),
      hasEpisode: Boolean(e),
      shared: siteIds.length > 1,
      parent: e?.parent_incident_id || null,
      acknowledged: Boolean(e?.acknowledged),
      status: i.status,
      assignmentState: assignmentState(item.workflow, i),
      crew: crew
        ? { name: crew.crew_name, progress: crew.progress, eta: crew.eta, label: crew.eta_label }
        : i.assignment
          ? { name: i.assignment.crew_name, progress: null, eta: null, label: null }
          : null,
      deadline: deadline.text,
      overdue: deadline.overdue,
      age: ageAt(i.created_at, now),
      createdAt: i.created_at,
      dominant: r.dominant || [],
      unknowns: r.unknowns || [],
    };
  });
}

export const FILTER_KEYS = ["area", "band", "family", "telemetry", "responsibility", "assignment"];
export const EMPTY_FILTERS = Object.fromEntries(FILTER_KEYS.map((k) => [k, "all"]));

const rowValue = (row, key) =>
  key === "area" ? row.areaId || "none" : key === "assignment" ? row.assignmentState : row[key];

/** Distinct options per filter with their (unfiltered) row counts, sorted. */
export function filterOptions(rows) {
  const out = {};
  for (const key of FILTER_KEYS) {
    const counts = new Map();
    for (const row of rows) {
      const v = rowValue(row, key) ?? "unknown";
      counts.set(v, (counts.get(v) || 0) + 1);
    }
    const order =
      key === "band"
        ? (a, b) => bandIndex(a) - bandIndex(b)
        : key === "telemetry"
          ? (a, b) => telemetryRank(a) - telemetryRank(b)
          : (a, b) => String(a).localeCompare(String(b));
    out[key] = [...counts.entries()].sort((a, b) => order(a[0], b[0])).map(([value, count]) => ({ value, count }));
  }
  return out;
}

export function applyFilters(rows, filters = EMPTY_FILTERS) {
  return rows.filter((row) =>
    FILTER_KEYS.every((key) => !filters[key] || filters[key] === "all" || (rowValue(row, key) ?? "unknown") === filters[key]),
  );
}
export const activeFilterCount = (filters = {}) =>
  FILTER_KEYS.filter((k) => filters[k] && filters[k] !== "all").length;

/**
 * Visible counts for a list of rows: cases, unique episodes, unique affected sites
 * (a shared episode counts once as an episode and once per site), and per band and
 * section. A site with several episodes counts once.
 */
export function visibleCounts(rows) {
  const sites = new Set(),
    episodes = new Set(),
    byBand = Object.fromEntries(BANDS.map((b) => [b, 0])),
    byGroup = {};
  for (const row of rows) {
    if (row.hasEpisode) episodes.add(row.id);
    for (const id of row.siteIds) sites.add(id);
    byBand[row.band] = (byBand[row.band] || 0) + 1;
    byGroup[row.group] = (byGroup[row.group] || 0) + 1;
  }
  return { cases: rows.length, episodes: episodes.size, sites: sites.size, byBand, byGroup };
}

/** The queue row to select when a site is clicked: its top-ranked visible row. */
export function rowForSite(rows, siteId) {
  return rows.find((row) => row.siteIds.includes(siteId)) || null;
}

/** Queue and map must come from the same ops revision before they are shown together. */
export const sameRevision = (queue, map) =>
  Boolean(queue && map) && (map.revision === undefined || queue.revision === map.revision);

/* ----------------------------------------------------------- episode drawer */

/**
 * Evidence rows. A mirrored copy (inverter/gateway copy of the same measurement)
 * is labelled as not independent; `independentSources` counts distinct groups.
 */
export function evidenceRows(evidence = []) {
  const groups = new Set();
  const rows = evidence.map((e) => {
    if (!e.mirror_of) groups.add(e.independent_group || e.source_id);
    return {
      id: e.evidence_id,
      kind: humanize(e.kind),
      source: e.source_id,
      group: e.independent_group,
      summary: e.summary,
      window:
        e.observed_from || e.observed_to
          ? `${localDateTime(e.observed_from)} – ${localTime(e.observed_to)}`
          : "time not reported",
      mirrored: Boolean(e.mirror_of),
      independence: e.mirror_of
        ? `Mirrored copy of ${e.mirror_of}: not independent corroboration`
        : `Independent source group ${e.independent_group || e.source_id}`,
      addedAt: e.added_as_of,
    };
  });
  return { rows, independentSources: groups.size };
}

const FACTOR_LABELS = {
  priority_band: "Priority band (safety and deadlines first)",
  deadline_pressure: "Response deadline pressure",
  evidenced_impact: "Evidenced service impact",
  recoverable_impact: "Recoverable impact while waiting",
  confidence_persistence: "Evidence confidence and persistence",
  age: "Age",
  repeat_dependency: "Repeats and shared parent",
  commitments: "Existing commitments",
  remote_resolvable: "Remote-resolvable vs field",
};
export const factorLabel = (key) => FACTOR_LABELS[key] || humanize(key);

export function factorValue(value) {
  if (value === null || value === undefined) return "unknown";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number") return String(Math.round(value * 1000) / 1000);
  if (typeof value === "object")
    return Object.entries(value)
      .map(([k, v]) => `${humanize(k).toLowerCase()}: ${v === null ? "unknown" : typeof v === "object" ? JSON.stringify(v) : String(v).replaceAll("_", " ")}`)
      .join(", ");
  return String(value).replaceAll("_", " ");
}

/** Rank factor table, largest contribution first; dominant factors flagged. */
export function factorRows(rank) {
  const dominant = new Set(rank?.dominant || []);
  return Object.entries(rank?.factors || {})
    .map(([key, f]) => ({
      key,
      label: factorLabel(key),
      value: factorValue(f.value),
      normalized: f.normalized,
      weight: f.weight,
      contribution: f.contribution,
      basis: f.basis,
      dominant: dominant.has(key),
    }))
    .sort((a, b) => b.contribution - a.contribution || a.key.localeCompare(b.key));
}

/** Plain lines for the economics block; unknowns stay unknown with their reason. */
export function economicsLines(economics) {
  if (!economics) return ["Economic impact unknown."];
  const lines = [];
  lines.push(
    economics.expected_lost_kwh_per_day == null
      ? `Expected lost energy: unknown (${humanize(economics.lost_kwh_reason || "no estimate").toLowerCase()})`
      : `Expected lost energy: about ${factorValue(economics.expected_lost_kwh_per_day)} kWh/day`,
  );
  const v = economics.value_per_day;
  lines.push(
    v
      ? `Value per day for ${humanize(v.stakeholder).toLowerCase()}: ${ron(Number(v.low_ron))} to ${ron(Number(v.high_ron))} (${v.basis})`
      : `Value per day: unknown (${humanize(economics.value_reason || "no valuation").toLowerCase()})`,
  );
  const r = economics.repair_estimate;
  lines.push(
    r
      ? `Repair estimate: ${r.currency === "RON" ? `${ron(Number(r.low))} to ${ron(Number(r.high))}` : `${r.low}–${r.high} ${r.currency}`} · ${r.source} (manual demo catalog, as of ${r.as_of})`
      : `Repair estimate: unknown (${humanize(economics.repair_reason || "no catalog entry").toLowerCase()})`,
  );
  if (economics.parent_attribution) lines.push(`Parent attribution: ${economics.parent_attribution}`);
  return lines;
}

export const CLOSE_REASONS = [
  { value: "repaired", label: "Repaired" },
  { value: "remote_resolved", label: "Resolved remotely" },
  { value: "no_fault_found_documented", label: "No fault found (documented)" },
  { value: "external_handoff", label: "Handed over to the responsible party" },
  { value: "duplicate", label: "Duplicate" },
];

/**
 * Which drawer actions a role may take. The backend enforces the same rules;
 * this only decides what to offer and how to explain a disabled action.
 * myCrewIds: crews the signed-in technician belongs to.
 */
export function episodeActions(role, detail, myCrewIds = []) {
  const open = detail?.incident?.status !== "resolved" && detail?.episode?.state !== "resolved";
  const ops = ["dispatcher", "supervisor", "technician"].includes(role);
  const dispatcher = role === "dispatcher";
  const assignedCrew = detail?.incident?.assignment?.crew_id || null;
  const myCrew = Boolean(assignedCrew && myCrewIds.includes(assignedCrew));
  const hasOverride = Boolean(detail?.rank?.override);
  const no = (reason) => ({ allowed: false, reason });
  const yes = { allowed: true, reason: null };
  if (!ops) {
    const denied = no("Operations staff only.");
    return { acknowledge: denied, close: denied, override: denied, revoke: denied };
  }
  if (!open) {
    const closed = no("This episode is resolved.");
    return { acknowledge: closed, close: closed, override: closed, revoke: closed };
  }
  return {
    acknowledge: detail?.episode?.acknowledged ? no("Already acknowledged.") : yes,
    close:
      role === "technician" && !myCrew
        ? no("Only the dispatcher, a supervisor or the assigned crew can close this episode.")
        : yes,
    override: dispatcher ? yes : no("Priority overrides need dispatch capability."),
    revoke: !dispatcher
      ? no("Revoking an override needs dispatch capability.")
      : hasOverride
        ? yes
        : no("No active override."),
  };
}

export const NEXT_ACTIONS = {
  acknowledge: "Acknowledge",
  keep_monitoring: "Keep monitoring",
  plan_remote_review: "Plan a remote review (Plan teams)",
  plan_remote_troubleshooting: "Plan remote troubleshooting (Plan teams)",
  close_documented: "Close with a documented reason",
  propose_crew_plan: "Propose a crew plan (Plan teams)",
  propose_external_review_not_auto_sent: "Propose an external review (not sent automatically)",
  assign: "Assign a crew",
  resolve: "Resolve",
};
export const nextActionText = (a) => NEXT_ACTIONS[a] || humanize(a);

/* ---------------------------------------------------------------- crew plan */

export const PLAN_STEPS = ["draft", "reviewed", "applied"];
/** Lifecycle chips draft → reviewed → applied, or → superseded. */
export function planLifecycle(status) {
  if (status === "superseded")
    return [
      { key: "draft", label: "Draft", state: "done" },
      { key: "reviewed", label: "Reviewed", state: "skipped" },
      { key: "superseded", label: "Superseded", state: "current" },
    ];
  const at = PLAN_STEPS.indexOf(status);
  return PLAN_STEPS.map((key, i) => ({
    key,
    label: humanize(key),
    state: i < at ? "done" : i === at ? "current" : "todo",
  }));
}

const DISPATCH_ONLY = "Applying needs dispatch capability";
/** Plan buttons per role and plan state. Supervisors see review/apply disabled. */
export function planActions(role, plan) {
  const planner = role === "dispatcher" || role === "supervisor";
  const dispatcher = role === "dispatcher";
  const status = plan?.status;
  const stale = Boolean(plan) && plan.current_revision !== plan.ops_revision;
  return {
    canView: planner,
    canPropose: planner,
    review: !plan
      ? { enabled: false, reason: "Propose a plan first." }
      : !dispatcher
        ? { enabled: false, reason: "Reviewing needs dispatch capability" }
        : status !== "draft"
          ? { enabled: false, reason: status === "reviewed" ? "Already reviewed." : `This plan is ${status}.` }
          : { enabled: true, reason: null },
    apply: !plan
      ? { enabled: false, reason: "Propose a plan first." }
      : !dispatcher
        ? { enabled: false, reason: DISPATCH_ONLY }
        : status === "draft"
          ? { enabled: false, reason: "Review the plan before applying it." }
          : status !== "reviewed"
            ? { enabled: false, reason: status === "applied" ? "Already applied." : `This plan is ${status}.` }
            : { enabled: true, reason: null },
    stale,
  };
}

export const VERDICT = {
  heuristic_improves: { text: "The heuristic improves on the FIFO baseline on these inputs", tone: "green" },
  mixed: { text: "Mixed: better on some measures, worse on others", tone: "yellow" },
  no_improvement: { text: "No improvement over the FIFO baseline on these inputs", tone: "" },
};
export const verdictText = (v) => VERDICT[v] || { text: humanize(v), tone: "" };

const num = (v, unit = "") => (v === null || v === undefined ? "—" : `${Math.round(Number(v) * 1000) / 1000}${unit}`);

/**
 * Comparison table rows (heuristic vs feasible FIFO/manual baseline), straight
 * from the backend's metrics. `same` marks equal values so nothing is spun.
 */
export function comparisonRows(comparison) {
  const h = comparison?.heuristic || {},
    b = comparison?.baseline || {};
  const rows = [
    { metric: "Jobs served", heuristic: `${num(h.jobs_served)} of ${num(h.jobs_total)}`, baseline: `${num(b.jobs_served)} of ${num(b.jobs_total)}`, same: h.jobs_served === b.jobs_served },
    { metric: "Travel", heuristic: num(h.travel_minutes, " min"), baseline: num(b.travel_minutes, " min"), same: h.travel_minutes === b.travel_minutes },
  ];
  for (const band of BANDS) {
    const hb = h.by_band?.[band],
      bb = b.by_band?.[band];
    if (!hb?.jobs && !bb?.jobs) continue;
    rows.push({
      metric: `${band} on time (deadline met)`,
      heuristic: `${hb?.timely ?? 0} of ${hb?.jobs ?? 0}`,
      baseline: `${bb?.timely ?? 0} of ${bb?.jobs ?? 0}`,
      same: hb?.timely === bb?.timely && hb?.jobs === bb?.jobs,
    });
    const hm = h.mean_response_minutes?.[band],
      bm = b.mean_response_minutes?.[band];
    if (hm != null || bm != null)
      rows.push({ metric: `${band} mean response`, heuristic: num(hm, " min"), baseline: num(bm, " min"), same: hm === bm });
  }
  if (h.delay_loss_kwh != null || b.delay_loss_kwh != null)
    rows.push({ metric: "Estimated delay loss (optional)", heuristic: num(h.delay_loss_kwh, " kWh"), baseline: num(b.delay_loss_kwh, " kWh"), same: h.delay_loss_kwh === b.delay_loss_kwh });
  if (h.overtime_minutes != null || b.overtime_minutes != null)
    rows.push({ metric: "Overtime", heuristic: num(h.overtime_minutes, " min"), baseline: num(b.overtime_minutes, " min"), same: h.overtime_minutes === b.overtime_minutes });
  return rows;
}

/** Visits grouped per crew in visit order (field visits and remote items apart). */
export function crewRoutes(visits = []) {
  const crews = new Map();
  for (const v of visits) {
    if (!crews.has(v.crew_id)) crews.set(v.crew_id, { crewId: v.crew_id, crewName: v.crew_name, visits: [] });
    crews.get(v.crew_id).visits.push(v);
  }
  for (const c of crews.values()) c.visits.sort((a, b) => a.sequence - b.sequence || a.start_at.localeCompare(b.start_at));
  return [...crews.values()].sort((a, b) => a.crewName.localeCompare(b.crewName));
}

/** One visit → display cells in Bucharest time. */
export function visitCells(v) {
  return {
    order: v.sequence,
    depart: localTime(v.depart_at),
    arrive: localTime(v.arrive_at),
    start: localTime(v.start_at),
    finish: localTime(v.finish_at),
    window: `${localTime(v.start_at)}–${localTime(v.finish_at)}`,
    travel: v.travel_minutes == null ? "unknown" : String(v.activity || "").startsWith("remote") ? "none (remote)" : `${v.travel_minutes} min`,
    service: `${v.service_minutes} min`,
    deadline: v.deadline_at ? `${v.deadline_met ? "Met" : "Missed"} · due ${localDateTime(v.deadline_at)}` : "No deadline",
    constraints: (v.constraints_checked || []).map((c) => humanize(c)),
  };
}

const UNASSIGNED_REASONS = {
  no_eligible_crew: "No eligible crew in this plan",
  crew_not_authorised_for_responsible_service:
    "No crew is authorised for the responsible service; the review is proposed for that party, never sent automatically",
  crew_location_unknown: "Crew location unknown, so no ETA is fabricated",
  remote_desk_no_field: "The remote desk does not do field work",
  no_qualified_crew: "No crew has the required qualification",
  outside_shift: "No crew shift covers the job",
  access_window_closed: "The customer access window cannot be met",
  dependency_not_met: "A prerequisite job is not planned",
  location_unknown: "Job location unknown",
  service_duration_unknown: "Service duration unknown",
  response_deadline_already_overdue: "The response deadline is already overdue",
  no_feasible_insertion: "No feasible slot within shifts and travel",
};
/**
 * Unassigned reasons → plain text. Codes "crew-id:code" become "Crew name: text";
 * general reasons come first.
 */
export function reasonLines(reasons = [], crewNames = {}) {
  const general = [],
    perCrew = [];
  for (const code of reasons) {
    const cut = code.indexOf(":");
    if (cut > 0) {
      const crew = code.slice(0, cut),
        rest = code.slice(cut + 1);
      perCrew.push(`${crewNames[crew] || crew}: ${(UNASSIGNED_REASONS[rest] || humanize(rest)).replace(/^./, (c) => c.toLowerCase())}`);
    } else general.push(UNASSIGNED_REASONS[code] || humanize(code));
  }
  return { general, perCrew };
}
export const reasonCodeText = (code) => UNASSIGNED_REASONS[code] || humanize(code);

/** Input completeness → { complete, lines }. */
export function completenessLines(ic) {
  if (!ic) return { complete: false, lines: ["Input completeness not reported."] };
  const lines = [];
  if (ic.travel_pairs_needed != null)
    lines.push(`Travel times known for ${ic.travel_pairs_known} of ${ic.travel_pairs_needed} trips`);
  const missing = (obj, what) =>
    Object.entries(obj || {}).map(([id, v]) => `${what} ${id}: missing ${Array.isArray(v) ? v.map(humanize).join(", ").toLowerCase() : String(v)}`);
  lines.push(...missing(ic.crews_missing, "Crew"), ...missing(ic.jobs_missing, "Job"));
  return { complete: ic.status === "complete", lines };
}

/** Jobs the planner considered, in rank order, with their outcome in this plan. */
export function planJobs(plan) {
  if (!plan) return [];
  const jobs = [
    ...(plan.visits || []).map((v) => ({ ...v, outcome: "field", text: `${v.crew_name}, visit ${v.sequence}, ${localTime(v.start_at)}–${localTime(v.finish_at)}` })),
    ...(plan.remote_items || []).map((v) => ({ ...v, outcome: "remote", text: `${v.crew_name} (remote), ${localTime(v.start_at)}–${localTime(v.finish_at)}` })),
    ...(plan.unassigned || []).map((u) => ({ ...u, rank_position: Number.POSITIVE_INFINITY, outcome: "unassigned", text: "Not assigned (see reasons)" })),
  ];
  return jobs.sort(
    (a, b) => bandIndex(a.band) - bandIndex(b.band) || a.rank_position - b.rank_position || a.job_id.localeCompare(b.job_id),
  );
}

/** Crew planning profile for the panel (synthetic planning inputs). */
export function crewProfileLines(crew) {
  const p = crew?.profile;
  if (!p)
    return {
      kind: "field",
      qualifications: crew?.skills || [],
      shift: crew?.shift ? `${crew.shift} (Bucharest)` : "Shift unknown",
      base: "Base location unknown",
      members: crew?.members || [],
      label: null,
    };
  return {
    kind: p.kind,
    organisation: humanize(p.organisation),
    qualifications: p.qualifications.map(humanize),
    tools: p.tools.map(humanize),
    shift: p.shift_start && p.shift_end ? `${localTime(p.shift_start)}–${localTime(p.shift_end)} (Bucharest)` : crew.shift ? `${crew.shift} (Bucharest)` : "Shift unknown",
    base: p.kind === "remote_desk" ? "Remote desk: no field location" : p.base ? `${p.base.label || "Base"} · base location — not live GPS` : "Base location unknown",
    members: crew.members || [],
    label: p.label,
  };
}

/* ------------------------------------------------------------------- agenda */

const PROGRESS_ORDER = ["en_route", "on_site", "done"];
/** Progress steps for an agenda item; only forward moves are offered. */
export function progressSteps(item) {
  const at = item?.progress ? PROGRESS_ORDER.indexOf(item.progress) : -1;
  const remote = String(item?.activity || "").startsWith("remote");
  return PROGRESS_ORDER.filter((s) => !(remote && (s === "en_route" || s === "on_site")))
    .map((state) => ({
      state,
      label: progressText(state),
      done: PROGRESS_ORDER.indexOf(state) <= at,
      next: false,
    }))
    .map((step, i, all) => ({ ...step, next: !step.done && all.slice(0, i).every((s) => s.done) }));
}

export const OUTCOMES = [
  { value: "resolved", label: "Resolved" },
  { value: "field_visit_needed", label: "Field visit needed" },
  { value: "further_evidence_needed", label: "Further evidence needed" },
];

/** Agenda items grouped by crew in time order. */
export function agendaGroups(agenda) {
  const groups = new Map();
  for (const item of agenda?.items || []) {
    if (!groups.has(item.crew_id)) groups.set(item.crew_id, { crewId: item.crew_id, crewName: item.crew_name, items: [] });
    groups.get(item.crew_id).items.push(item);
  }
  for (const g of groups.values())
    g.items.sort((a, b) => String(a.scheduled_start || "~").localeCompare(String(b.scheduled_start || "~")));
  return [...groups.values()];
}

/** Request body for a progress update; done needs a note (server checks too). */
export function progressBody(item, state, { note = "", outcome = null } = {}) {
  const text = note.trim();
  if (state === "done" && !text) return { error: "Write a short note describing the outcome before marking it done." };
  const body = { state, expected_revision: item.revision };
  if (text) body.note = text;
  if (state === "done" && outcome) body.outcome = outcome;
  return { body };
}
