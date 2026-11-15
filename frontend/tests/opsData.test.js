import test from "node:test";
import assert from "node:assert/strict";
import {
  ROLE_PAGES,
  ageLabel,
  bottomNav,
  crewChoices,
  friendlyError,
  keepIfSame,
  logAction,
  mapStatus,
  pagesFor,
  scopeLabel,
  shortId,
  skipReason,
  toAssignmentRows,
  toCrewSummaries,
  toForecastAreas,
  toMapClusters,
  toMapSites,
  toRevenueReport,
} from "../src/opsData.js";
import { revenueReport } from "../src/revenue.js";

test("menus follow the product owner's role decisions", () => {
  assert.deepEqual(pagesFor("supervisor"), [
    "Area Radar",
    "Incidents",
    "Teams",
    "Revenue",
    "Offers",
    "Sites",
    "Account",
  ]);
  assert.deepEqual(pagesFor("dispatcher"), [
    "Dispatch",
    "Incidents",
    "Teams",
    "Requests",
    "Sites",
    "Account",
  ]);
  // Technicians get a simple agenda only: no history, no requests inbox, no radar.
  assert.deepEqual(pagesFor("technician"), ["Agenda", "Account"]);
  assert.deepEqual(pagesFor("customer"), [
    "Home",
    "Plan",
    "Offers",
    "History",
    "Support",
    "Learn",
    "Account",
  ]);
  // Only customers keep History; managers have no Requests page; nobody gets Audit.
  for (const role of ["supervisor", "dispatcher", "technician"])
    assert.ok(!pagesFor(role).includes("History"), `${role} has no History`);
  assert.ok(!pagesFor("supervisor").includes("Requests"));
  assert.ok(!pagesFor("technician").includes("Requests"));
  assert.ok(!pagesFor("technician").includes("Area Radar"));
  for (const pages of Object.values(ROLE_PAGES)) assert.ok(!pages.includes("Audit"));
  assert.deepEqual(pagesFor("unknown"), ["Account"]);
});

test("bottom navigation caps long menus with a More entry", () => {
  const short = bottomNav(["Agenda", "Account"], "Agenda");
  assert.deepEqual(short, {
    items: ["Agenda", "Account"],
    more: false,
    moreActive: false,
  });
  const technician = bottomNav(pagesFor("technician"), "Agenda");
  assert.deepEqual(technician.items, ["Agenda", "Account"]);
  assert.equal(technician.more, false);
  const long = bottomNav(pagesFor("supervisor"), "Sites");
  assert.deepEqual(long.items, ["Area Radar", "Incidents", "Teams", "Revenue"]);
  assert.equal(long.more, true);
  assert.equal(long.moreActive, true);
  assert.equal(bottomNav(pagesFor("supervisor"), "Teams").moreActive, false);
  // Customers: Plan and Offers follow Home on phones; the rest goes under More.
  const customer = bottomNav(pagesFor("customer"), "Learn");
  assert.deepEqual(customer.items, ["Home", "Plan", "Offers", "History"]);
  assert.equal(customer.moreActive, true);
});

const mapSite = (extra) => ({
  site_id: "s6-05",
  alias: "Home · Militari 5",
  area_id: "sector-6",
  latitude: 44.4345,
  longitude: 26.018,
  zone: "Militari",
  character: "residential",
  segment: "home",
  business_type: null,
  installed_kwp: 6.5,
  freshness_status: "fresh",
  open_incidents: 0,
  worst_tier: null,
  ...extra,
});

test("map status: open incident first, then a recent feed, else stale", () => {
  assert.deepEqual(mapStatus(mapSite({ open_incidents: 2, worst_tier: "P1", freshness_status: "stale" })), {
    status: "incident",
    tier: "P1",
  });
  assert.deepEqual(mapStatus(mapSite({})), { status: "ok", tier: null });
  for (const freshness of ["stale", "unavailable", "future", "unknown_clock"])
    assert.deepEqual(mapStatus(mapSite({ freshness_status: freshness })), {
      status: "stale",
      tier: null,
    });
});

test("map sites adapt to BucharestMap props with area aliases", () => {
  const [site] = toMapSites(
    [mapSite({ open_incidents: 1, worst_tier: "P1", segment: "business", business_type: "Bakery" })],
    { "sector-6": "Sector 6" },
  );
  assert.deepEqual(
    { ...site, detail: undefined },
    {
      id: "s6-05",
      name: "Home · Militari 5",
      latitude: 44.4345,
      longitude: 26.018,
      zone: "Militari",
      segment: "business",
      businessType: "Bakery",
      kwp: 6.5,
      status: "incident",
      tier: "P1",
      area: "Sector 6",
      // No `cluster` from the API yet: the shared fixture's cluster for the site id.
      cluster: "militari-homes",
      detail: undefined,
    },
  );
  assert.match(site.detail, /1 open synthetic incident \(worst P1\)/);
  assert.equal(toMapSites([mapSite({ area_id: "unknown-area" })])[0].area, "unknown-area");
});

test("map sites take the server's area alias and cluster when present", () => {
  const [after] = toMapSites(
    [mapSite({ area_alias: "Sector 6", cluster: "drumul-taberei-homes" })],
    {},
  );
  assert.equal(after.area, "Sector 6");
  assert.equal(after.cluster, "drumul-taberei-homes");
  // An explicit null from the server means a standalone site.
  assert.equal(toMapSites([mapSite({ cluster: null })])[0].cluster, null);
  // Unknown site ids without a server cluster are standalone too.
  assert.equal(toMapSites([mapSite({ site_id: "imported-1" })])[0].cluster, null);
});

test("map clusters come from the server, else from the shared fixture", () => {
  const fallback = toMapClusters({ sites: [] });
  assert.equal(fallback.length, 15);
  assert.ok(fallback.some((c) => c.id === "militari-homes" && c.kind === "residential"));
  assert.deepEqual(
    toMapClusters({
      clusters: [{ id: "x", name: "Old Town (Lipscani)", area_id: "sector-3", kind: "hospitality" }],
    }),
    [{ id: "x", name: "Old Town (Lipscani)", area_id: "sector-3", kind: "hospitality" }],
  );
  assert.equal(toMapClusters(null).length, 15);
});

test("capacity becomes forecast areas", () => {
  assert.deepEqual(
    toForecastAreas({
      areas: [{ area_id: "sector-6", alias: "Sector 6", sites: 8, installed_kwp: 61.5 }],
      total_installed_kwp: 61.5,
    }),
    [{ name: "Sector 6", kwp: 61.5, sites: 8 }],
  );
  assert.deepEqual(toForecastAreas(null), []);
});

const money = (net, extra = {}) => ({
  energy_sales_ron: net + 100,
  export_payments_ron: 150,
  service_fees_ron: 50,
  net_revenue_ron: net,
  sites: 2,
  ...extra,
});
const revenueView = {
  period: "monthly",
  basis: "Estimate from synthetic monthly billing profiles.",
  currency: "RON",
  totals: money(1000, { sites: 3 }),
  by_segment: {
    home: money(400, { sites: 2, share_of_net: 0.4 }),
    business: money(600, { sites: 1, share_of_net: 0.6 }),
  },
  by_area: [
    {
      ...money(1000, { sites: 3 }),
      area_id: "sector-6",
      alias: "Sector 6",
      business_sites: 1,
      business_net_revenue_ron: 600.1,
    },
  ],
  business_accounts: [
    {
      site_id: "s6-13",
      alias: "Demo bakery",
      area_id: "sector-6",
      zone: "Floreasca",
      business_type: "Bakery",
      installed_kwp: 30,
      monthly_import_kwh: 900,
      monthly_export_kwh: 300,
      energy_sales_ron: 1170,
      export_payments_ron: 165,
      service_fees_ron: 40,
      net_revenue_ron: 1045,
      import_price_ron_kwh: 1.3,
      export_price_ron_kwh: 0.55,
      price_source: "default_tariff",
    },
  ],
  annualized_net_revenue_ron: 12000,
};

test("revenue adapter keeps the server's numbers in RevenueView's shape", () => {
  const report = toRevenueReport(revenueView);
  assert.deepEqual(report.totals, {
    sites: 3,
    energySales: 1100,
    exportPayments: 150,
    serviceFees: 50,
    net: 1000,
  });
  assert.equal(report.annualNet, 12000);
  assert.equal(report.bySegment.business.share, 0.6);
  assert.equal(report.bySegment.home.net, 400);
  assert.deepEqual(report.byArea[0], {
    area: "Sector 6",
    sites: 3,
    energySales: 1100,
    exportPayments: 150,
    serviceFees: 50,
    net: 1000,
    businessSites: 1,
    businessNet: 600.1,
    homeNet: 399.9,
  });
  assert.deepEqual(report.businessAccounts[0], {
    id: "s6-13",
    name: "Demo bakery",
    area: "Sector 6",
    zone: "Floreasca",
    businessType: "Bakery",
    kwp: 30,
    importKwh: 900,
    exportKwh: 300,
    energySales: 1170,
    exportPayments: 165,
    serviceFees: 40,
    net: 1045,
    importPrice: 1.3,
    exportPrice: 0.55,
    priceSource: "default",
  });
  assert.equal(report.basis, revenueView.basis);
  // Same top-level keys as the browser's own revenueReport(), plus basis.
  const browser = revenueReport([], {});
  for (const key of Object.keys(browser)) assert.ok(key in report, key);
});

test("scope labels name the areas in scope", () => {
  assert.equal(scopeLabel(["Sector 6"]), "Sector 6");
  assert.equal(
    scopeLabel(["Sector 3", "Sector 6", "Ilfov"]),
    "3 areas · Sector 3, Sector 6, Ilfov",
  );
  assert.equal(scopeLabel([]), "Your scope");
});

const incident = (id, tier, created_at, extra = {}) => ({
  incident_id: id,
  site_id: `site-${id}`,
  site_alias: `Site ${id}`,
  area_id: "sector-6",
  zone: "Militari",
  segment: "home",
  title: `Title ${id}`,
  family: "Production",
  tier,
  status: "new",
  source: "synthetic_replay",
  evidence: "",
  created_at,
  updated_at: created_at,
  support_request_id: null,
  assignment: null,
  ...extra,
});

test("assignment report rows: assignments plus open unassigned incidents, by severity", () => {
  const incidents = [
    incident("a", "P1", "2026-07-15T10:00:00Z", {
      status: "meeting_scheduled",
      assignment: { assignment_id: "x2", crew_id: "c", crew_name: "Solar Care" },
    }),
    incident("b", "P0", "2026-07-15T11:00:00Z"),
    incident("c", "P3", "2026-07-15T09:00:00Z", { status: "resolved" }),
  ];
  const assignments = [
    {
      assignment_id: "x2",
      incident_id: "a",
      incident_title: "Title a",
      tier: "P1",
      site_alias: "Site a",
      area_id: "sector-6",
      crew_name: "Solar Care",
      kind: "meeting",
      status: "meeting_scheduled",
      created_by: "technician",
      created_at: "2026-07-15T12:30:00Z",
      scheduled_start: "2026-11-16T08:00:00Z",
      scheduled_end: "2026-11-16T09:00:00Z",
      completed_at: null,
    },
    {
      assignment_id: "x1",
      incident_id: "a",
      incident_title: "Title a",
      tier: "P1",
      site_alias: "Site a",
      area_id: "sector-6",
      crew_name: "Solar Care",
      kind: "dispatch",
      status: "completed",
      created_by: "dispatcher",
      created_at: "2026-07-15T12:00:00Z",
      scheduled_start: null,
      scheduled_end: null,
      completed_at: "2026-07-15T12:20:00Z",
    },
  ];
  const rows = toAssignmentRows(assignments, incidents, { "sector-6": "Sector 6" });
  assert.deepEqual(
    rows.map((r) => [r.id, r.status]),
    [
      ["open-b", "Not assigned"],
      ["x1", "Completed"],
      ["x2", "Meeting booked"],
    ],
  );
  assert.equal(rows[2].slot, "2026-11-16 10:00–11:00");
  assert.equal(rows[2].area, "Sector 6");
  assert.equal(rows[2].site, "site-a");
  assert.equal(rows[0].crew, null);
  assert.equal(rows[1].assignedBy, "dispatcher");
  assert.equal(rows[1].slot, null);
});

const crew = (extra) => ({
  crew_id: "solar-care",
  name: "Solar Care",
  area_id: "sector-6",
  area_alias: "Sector 6",
  skills: ["Production", "Telemetry"],
  shift: "08:00-18:00",
  members: ["technician"],
  available: true,
  active_assignment: null,
  report: {
    assigned_total: 2,
    completed_total: 1,
    open_by_tier: { P0: 0, P1: 1, P2: 0, P3: 0 },
    completed_by_tier: { P0: 0, P1: 0, P2: 1, P3: 0 },
  },
  ...extra,
});

test("crew summaries: availability, busy work, meetings and tier counts", () => {
  const busy = crew({
    available: false,
    active_assignment: {
      assignment_id: "x",
      incident_id: "i",
      incident_title: "T",
      tier: "P1",
      site_id: "s6-05",
      site_alias: "Home · Militari 5",
      kind: "dispatch",
      status: "team_sent",
      scheduled_start: null,
      scheduled_end: null,
    },
  });
  const [summary] = toCrewSummaries([busy], [
    { crew_name: "Solar Care", kind: "meeting", status: "meeting_scheduled" },
    { crew_name: "Solar Care", kind: "meeting", status: "completed" },
    { crew_name: "Other", kind: "meeting", status: "meeting_scheduled" },
  ]);
  assert.equal(summary.name, "Solar Care");
  assert.equal(summary.area, "Sector 6");
  assert.equal(summary.owner, null);
  assert.equal(summary.available, false);
  assert.deepEqual(summary.busyWith, {
    incident: "P1 Home · Militari 5",
    status: "Team sent",
  });
  assert.equal(summary.meetings, 1);
  assert.deepEqual(summary.open, { P0: 0, P1: 1, P2: 0, P3: 0 });
  assert.deepEqual(summary.completed, { P0: 0, P1: 0, P2: 1, P3: 0 });
  assert.equal(toCrewSummaries([crew({})])[0].busyWith, null);
});

test("crew choices: same area and family, busy crews kept but flagged", () => {
  const crews = [
    crew({}),
    crew({ crew_id: "busy", name: "Busy", available: false }),
    crew({ crew_id: "ilfov", name: "Ilfov Field Service", area_id: "ilfov" }),
    crew({ crew_id: "volt", name: "Volt", skills: ["Voltage"] }),
  ];
  assert.deepEqual(crewChoices(crews, incident("a", "P1", "")), [
    { id: "solar-care", name: "Solar Care", available: true },
    { id: "busy", name: "Busy", available: false },
  ]);
  assert.deepEqual(crewChoices(crews, null), []);
});

test("friendly error text for known codes, server message otherwise", () => {
  const error = (code, message = "terse") => ({ status: 409, detail: { code, message } });
  assert.match(friendlyError(error("meeting_overlap")), /already has a meeting/);
  assert.match(friendlyError(error("crew_unavailable")), /on-site dispatch/);
  assert.match(friendlyError(error("dispatcher_required")), /dispatcher/);
  assert.match(friendlyError(error("media_not_allowed")), /danger reports/);
  assert.match(friendlyError(error("episode_workflow_required")), /^Use Plan teams for this incident/);
  assert.equal(friendlyError(error("something_new", "Server says")), "Server says.");
  assert.equal(friendlyError(error("something_new", "Done!")), "Done!");
  assert.equal(friendlyError(new Error("Local check.")), "Local check.");
  assert.match(friendlyError(new TypeError("Failed to fetch")), /^Unable to reach the service/);
  assert.match(friendlyError(null), /Unable to reach/);
  assert.match(skipReason("no_eligible_crew"), /no crew in this area covers/);
  assert.match(skipReason("no_available_crew"), /already on an on-site dispatch/);
});

test("small labels: ids, log actions, ages and stable references", () => {
  assert.equal(shortId("0123456789abcdef0123456789abcdef"), "#01234567");
  assert.equal(shortId("demo-inc-s6-05-production"), "demo-inc-s6-05-production");
  assert.equal(logAction("auto_assigned"), "Assigned by severity");
  assert.equal(logAction("brand_new_action"), "Brand new action");
  const now = Date.parse("2026-07-15T12:00:00Z");
  assert.equal(ageLabel("2026-07-15T11:15:00Z", now), "45 min");
  assert.equal(ageLabel("2026-07-15T02:00:00Z", now), "10 h");
  assert.equal(ageLabel("2026-07-10T12:00:00Z", now), "5 days");
  assert.equal(ageLabel("not a date", now), "—");
  const previous = { a: [1, 2] };
  assert.equal(keepIfSame(previous, { a: [1, 2] }), previous);
  const next = { a: [1, 3] };
  assert.equal(keepIfSame(previous, next), next);
  assert.equal(keepIfSame(null, next), next);
});
