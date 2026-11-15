import test from "node:test";
import assert from "node:assert/strict";
import { agendaCard, nextStep, pastJobs, linkedMedia } from "../src/agendaView.js";
import {
  bandAt,
  businessHeader,
  chartBuckets,
  estimateDayCost,
  metricCard,
  overviewCards,
  profileNote,
  solarCoverage,
} from "../src/customerView.js";
import {
  automationSummary,
  priorityCounts,
  siteListRows,
  ticketsBySite,
  triageItems,
  visibleSiteSet,
} from "../src/dispatchView.js";
import { isAreaManager, roleLabel } from "../src/opsData.js";

test("agenda card: one next step per item, remote work has a single step", () => {
  assert.equal(nextStep({ activity: "field_visit", progress: null }), "en_route");
  assert.equal(nextStep({ activity: "field_visit", progress: "en_route" }), "on_site");
  assert.equal(nextStep({ activity: "field_visit", progress: "on_site" }), "done");
  assert.equal(nextStep({ activity: "field_visit", progress: "done" }), null);
  assert.equal(nextStep({ activity: "remote_review", progress: null }), "done");
  const card = agendaCard({
    assignment_id: "a1",
    title: "Battery alarm: Synthetic site F1 (x)",
    site_alias: "Synthetic site F1 (x)",
    zone: "Aviatiei, Bucharest",
    reason: "Battery restricted by its BMS",
    window_label: "09:00-10:30",
    activity: "field_visit",
    tier: "P1",
    progress: null,
    media: { media_id: "m1", filename: "clip.mp4" },
  });
  assert.equal(card.time, "09:00–10:30");
  assert.equal(card.where, "Site F1");
  assert.equal(card.whereDetail, "Aviatiei, Bucharest");
  assert.equal(card.why, "Battery restricted by its BMS");
  assert.deepEqual(card.media, { id: "m1", filename: "clip.mp4", size: null });
  assert.equal(linkedMedia({}), null);
});

test("past jobs come from the agenda history, newest first", () => {
  const list = pastJobs({
    history: [
      { assignment_id: "a", title: "A", site_alias: "Synthetic site F1 (x)", scheduled_end: "2026-07-16T10:00:00Z" },
      { assignment_id: "b", title: "B", site_alias: "Synthetic site H2 (x)", scheduled_end: "2026-07-16T12:00:00Z" },
    ],
  });
  assert.deepEqual(list.map((j) => j.id), ["b", "a"]);
  assert.deepEqual(pastJobs({}), []);
});

test("overview cards never turn a missing value into zero; consumption is derived", () => {
  const cards = overviewCards(
    {
      pv: { value: 3.2, unit: "kW", origin: "measured" },
      consumption: { value: 1.5, unit: "kW", origin: "derived", basis: "pv + import - export" },
      grid_import: { value: null, unit: "kW", origin: null, reason: "no_grid_meter" },
      grid_export: { value: 0, unit: "kW", origin: "measured" },
    },
    "business",
  );
  assert.equal(cards[1].name, "Business consumption");
  assert.equal(cards[1].origin, "derived");
  assert.equal(cards[2].value, null);
  assert.equal(cards[2].reason, "This site has no grid meter");
  assert.equal(cards[3].value, "0");
  assert.equal(metricCard("x", null).value, null);
});

test("periods: synthetic profile buckets are flagged and noted", () => {
  const chart = chartBuckets({
    synthetic: true,
    note: "n",
    buckets: [
      { label: "Jan", origin: "synthetic_profile", production_kwh: 1, consumption_kwh: 2 },
      { label: "Feb", origin: "measured", production_kwh: 3, consumption_kwh: null },
    ],
  });
  assert.equal(chart.syntheticCount, 1);
  assert.equal(chart.buckets[1].consumption, null);
  assert.match(profileNote(chart), /1 of 2 periods use a typical seasonal profile/);
  assert.equal(profileNote({ syntheticCount: 0, buckets: [] }), null);
});

test("business header: cost from contract bands, peak and coverage from totals", () => {
  const bands = [
    { band_id: "day", days: [1, 2, 3, 4, 5, 6, 7], start_minute: 0, end_minute: 1440, import_rate_ron_kwh: 1, export_value_ron_kwh: 0.4 },
  ];
  assert.equal(bandAt(bands, "2026-07-17T08:00:00Z").band_id, "day");
  const periods = {
    buckets: [
      { start: "2026-07-17T05:00:00Z", origin: "measured", grid_import_kwh: 4, grid_export_kwh: 1 },
      { start: "2026-07-17T06:00:00Z", origin: "synthetic_profile", grid_import_kwh: 99, grid_export_kwh: 0 },
    ],
    totals: { production_kwh: 10, consumption_kwh: 20, grid_export_kwh: 1, self_consumption_share: 0.9, peak_kw: 6.5 },
  };
  const cost = estimateDayCost(periods, { import_price_ron_kwh: 1.2, export_price_ron_kwh: 0.3 }, bands);
  assert.equal(Math.round(cost.ron * 100) / 100, 3.6);
  assert.equal(estimateDayCost(periods, null, bands), null);
  assert.equal(solarCoverage(periods.totals), 0.45);
  const header = businessHeader(periods, null, { import_price_ron_kwh: 1.2, export_price_ron_kwh: 0.3 }, bands);
  assert.equal(header.tiles.find((t) => t.key === "peak").value, "6.5 kW");
  assert.equal(header.tiles.find((t) => t.key === "self").value, "90 %");
  assert.equal(businessHeader(null, null, null, []).tiles[0].value, null);
});

test("triage list: danger first, then oldest; only requests awaiting review", () => {
  const items = triageItems([
    { request_id: "1", status: "awaiting_review", priority: "standard", created_at: "2026-07-17T05:00:00Z", description: "a", site_alias: "S", requested_by: "x", request_label: "L" },
    { request_id: "2", status: "awaiting_review", priority: "immediate_danger", created_at: "2026-07-17T06:00:00Z", description: "b", site_alias: "S", requested_by: "x", request_label: "L" },
    { request_id: "3", status: "answered", priority: "standard", created_at: "2026-07-17T04:00:00Z", description: "c", site_alias: "S", requested_by: "x", request_label: "L" },
  ]);
  assert.deepEqual(items.map((i) => i.id), ["2", "1"]);
});

test("automation summary separates automated work, approvals and what needs a person", () => {
  const plan = {
    status: "draft",
    visits: [{}, {}],
    remote_items: [{}],
    monitoring: [{}],
    unassigned: [{ band: "P2", title: "Voltage: Synthetic site H2 (x)", reasons: ["crew_not_authorised_for_responsible_service"] }],
    urgent_exceptions: [],
    comparison: { verdict: "no_improvement" },
  };
  const summary = automationSummary(plan, { assigned: [{}], skipped: [] });
  assert.equal(summary.automated.length, 3);
  assert.match(summary.approval[0], /Apply/);
  assert.equal(summary.person.length, 1);
  assert.equal(automationSummary(null).empty, true);
});

test("priority counts, tickets per site and map filters", () => {
  assert.deepEqual(priorityCounts({ episodes_by_band: { P1: 2, P3: 1 } }), [
    { band: "P0", count: 0 },
    { band: "P1", count: 2 },
    { band: "P2", count: 0 },
    { band: "P3", count: 1 },
  ]);
  const queue = {
    rank_as_of: "2026-07-17T05:00:00Z",
    items: [
      {
        incident: { incident_id: "i1", site_id: "s1", site_alias: "Synthetic site F1 (x)", title: "Battery: Synthetic site F1 (x)", updated_at: "2026-07-17T04:00:00Z", assignment: null },
        episode: null,
        workflow: "needs_review",
        rank: { band: "P1", deadline_at: null },
      },
    ],
  };
  const tickets = ticketsBySite(queue);
  assert.equal(tickets.s1[0].title, "Battery");
  const map = {
    status_sites: [
      { site_id: "s1", alias: "Synthetic site F1 (x)", area_id: "ilfov", area_alias: "Ilfov", position: { latitude: 1, longitude: 2 }, highest_priority: "P1", condition: "observed_active", attention: "high", telemetry: { state: "fresh", sources: [{ last_observed_at: "2026-07-17T04:30:00Z" }] }, workflow: "needs_review", crew: null },
      { site_id: "s2", alias: "Synthetic site H1 (x)", area_id: "sector-1", area_alias: "Sector 1", position: null, highest_priority: null, condition: "not_evaluated", attention: "unknown", telemetry: { state: "missing", sources: [] }, workflow: "none", crew: null },
    ],
    unmapped: [],
  };
  const rows = siteListRows(map, tickets);
  assert.equal(rows[0].id, "s1");
  assert.equal(rows[0].tickets.length, 1);
  assert.equal(visibleSiteSet(rows, {}), null);
  assert.deepEqual([...visibleSiteSet(rows, { bands: ["P1"] })], ["s1"]);
  assert.deepEqual([...visibleSiteSet(rows, { bands: ["none"] })], ["s2"]);
  assert.deepEqual([...visibleSiteSet(rows, { area: "sector-1" })], ["s2"]);
});

test("an area manager is a supervisor limited to one area", () => {
  const user = { role: "supervisor" };
  assert.equal(isAreaManager(user, ["Ilfov"]), true);
  assert.equal(isAreaManager(user, ["Ilfov", "Sector 1"]), false);
  assert.equal(roleLabel(user, ["Ilfov"]), "Area manager · Ilfov");
  assert.equal(roleLabel(user, ["Ilfov", "Sector 1"]), "PPC manager");
  assert.equal(roleLabel({ role: "technician" }, []), "Field technician");
});
