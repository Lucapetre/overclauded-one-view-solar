import test from "node:test";
import assert from "node:assert/strict";
import {
  markerStyle, toQueueRows, visibleCounts, applyFilters, filterOptions,
  filterMapView, rowForSite, sameRevision, toMapOverlays, evidenceRows,
  planActions, comparisonRows, verdictText, progressSteps, progressBody, visitCells,
  episodeActions, economicsLines,
} from "../src/opsView.js";

const status = (id, episodes, extra = {}) => ({
  site_id: id, alias: `Synthetic site ${id} (demo)`, area_id: "sector-1",
  condition: "observed_active", attention: "high", highest_priority: "P1",
  telemetry: { state: "fresh" }, workflow: "assigned", episode_ids: episodes,
  position: { latitude: 44.5, longitude: 26.1, fictional: true }, ...extra,
});
const item = (id, siteIds, band = "P2", action = "remote_troubleshooting") => ({
  incident: { incident_id: id, site_id: siteIds[0], site_alias: `Synthetic site ${siteIds[0]} (demo)`,
    title: `Review: Synthetic site ${siteIds[0]} (demo)`, family: "Data", area_id: "sector-1", status: "open" },
  episode: { site_ids: siteIds, responsibility: "monitoring_provider", action },
  workflow: "needs_review", rank: { band, computed_band: band, position: 1 },
});

test("safety attention survives loss of telemetry; unknown never becomes clear", () => {
  const alarm = markerStyle(status("F1", ["battery"], { telemetry: { state: "missing" } }));
  assert.equal(alarm.tone, "urgent");
  assert.equal(alarm.telemetry, "missing");
  assert.match(alarm.label, /High attention.*missing/);
  for (const state of [null, "missing", "stale", "access_error"]) {
    assert.notEqual(markerStyle({ telemetry: { state } }).tone, "clear");
  }
  assert.equal(markerStyle({}).glyph, "!");
});

test("queue retains server order, shared ids, unknown feeds and unique counts", () => {
  const queue = { rank_as_of: "2026-07-19T08:30:00Z", items: [
    item("battery", ["F1"], "P1", "field_visit"),
    item("collector", ["H1", "H2"]), item("voltage", ["H2"]),
  ] };
  const rows = toQueueRows(queue, [status("F1", ["battery"]), status("H1", ["collector"])]);
  assert.deepEqual(rows.map((r) => r.id), ["battery", "collector", "voltage"]);
  assert.equal(rows[1].telemetry, "unknown");
  assert.equal(rows[1].shared, true);
  assert.equal(visibleCounts(rows).sites, 3);
  assert.equal(visibleCounts(rows).episodes, 3);
  assert.equal(rowForSite(rows, "H2").id, "collector");
});

test("filters combine without reranking and report matching option counts", () => {
  const rows = toQueueRows({ items: [item("a", ["F1"], "P1", "field_visit"), item("b", ["H2"])] });
  const selected = applyFilters(rows, { band: "P2", responsibility: "monitoring_provider", assignment: "unassigned" });
  assert.deepEqual(selected.map((r) => r.id), ["b"]);
  assert.deepEqual(filterOptions(rows).band, [{ value: "P1", count: 1 }, { value: "P2", count: 1 }]);
  assert.equal(applyFilters(rows, { telemetry: "fresh" }).length, 0);
});

test("map filters synchronize unmapped list, counts, crews and route stops", () => {
  const map = { revision: 4, status_sites: [status("H1", ["shared"]), status("H2", ["shared", "voltage"])],
    unmapped: [status("S3", [], { position: null })],
    routes: [{ crew_id: "desk", stops: [{ site_id: "H1" }, { site_id: "H2" }] },
      { crew_id: "battery", stops: [{ site_id: "F1" }] }],
    crews: [{ crew_id: "desk" }, { crew_id: "battery" }], counts: {} };
  const view = filterMapView(map, new Set(["H2", "S3"]));
  assert.equal(view.counts.sites, 2);
  assert.equal(view.counts.unique_episodes, 2);
  assert.equal(view.counts.affected_sites, 1);
  assert.equal(view.unmapped.length, 1);
  assert.deepEqual(view.routes[0].stops, [{ site_id: "H2" }]);
  assert.deepEqual(view.crews, [{ crew_id: "desk" }]);
  assert.equal(map.routes[0].stops.length, 2);
  assert.equal(filterMapView(map, new Set()).counts.sites, 0);
});

test("mixed revisions cannot be presented together", () => {
  assert.equal(sameRevision({ revision: 1 }, { revision: 2 }), false);
  assert.equal(sameRevision({ revision: 2 }, { revision: 2 }), true);
  assert.equal(sameRevision(null, { revision: 2 }), false);
});

test("routes distinguish proposed/applied, remote desks have no GPS marker", () => {
  const map = { crews: [{ crew_id: "c", name: "Battery Crew", kind: "field", position: { latitude: 44, longitude: 26 } },
    { crew_id: "d", name: "Desk", kind: "remote_desk", position: { latitude: 44, longitude: 26 } }],
    routes: ["proposed", "applied"].map((state) => ({ crew_id: "c", state, stops: [{ sequence: 1,
      incident_id: "alarm", site_id: "F1", position: { latitude: 45, longitude: 27 } }] })) };
  const overlays = toMapOverlays(map, "alarm");
  assert.equal(overlays.crews.length, 1);
  assert.match(overlays.crews[0].label, /not live GPS/);
  assert.ok(overlays.routes[0].style.dashArray);
  assert.equal(overlays.routes[1].style.dashArray, null);
  assert.equal(overlays.routes[0].highlighted, true);
  assert.match(overlays.routes[0].label, /schematic/);
});

test("mirrored evidence never counts as independent corroboration", () => {
  const evidence = evidenceRows([
    { evidence_id: "1", source_id: "meter", independent_group: "physical-meter" },
    { evidence_id: "2", source_id: "gateway", independent_group: "gateway", mirror_of: "meter" },
    { evidence_id: "3", source_id: "meter", independent_group: "physical-meter" },
  ]);
  assert.equal(evidence.independentSources, 1);
  assert.match(evidence.rows[1].independence, /not independent/);
});

test("plan lifecycle requires dispatcher review; supervisors cannot apply", () => {
  const draft = { status: "draft", current_revision: 7, ops_revision: 7 };
  assert.equal(planActions("dispatcher", draft).apply.enabled, false);
  assert.equal(planActions("dispatcher", { ...draft, status: "reviewed" }).apply.enabled, true);
  const supervisor = planActions("supervisor", { ...draft, status: "reviewed" });
  assert.equal(supervisor.canPropose, true);
  assert.equal(supervisor.review.enabled, false);
  assert.equal(supervisor.apply.enabled, false);
  assert.match(supervisor.apply.reason, /dispatch capability/);
  assert.equal(planActions("dispatcher", { ...draft, current_revision: 8 }).stale, true);
  assert.equal(planActions("technician", draft).canView, false);
  assert.equal(episodeActions("technician", { incident: { status: "open" } }).close.allowed, false);
});

test("equal FIFO results are reported without claiming an improvement", () => {
  const metrics = { jobs_served: 4, jobs_total: 5, travel_minutes: 25, by_band: { P1: { jobs: 1, timely: 1 } } };
  assert.ok(comparisonRows({ heuristic: metrics, baseline: metrics }).every((r) => r.same));
  assert.match(verdictText("no_improvement").text, /^No improvement/);
});

test("economic estimates preserve the stakeholder, unknowns and common money format", () => {
  const lines = economicsLines({ value_per_day: { stakeholder: "site_customer", low_ron: 1.2, high_ron: 2.5, basis: "demo tariff" } });
  assert.match(lines[0], /unknown/);
  assert.match(lines[1], /site customer: 1.20 RON to 2.50 RON/);
  assert.match(lines[2], /unknown/);
});

test("agenda only offers forward progress and submits the observed revision", () => {
  const visit = { revision: 3, progress: "en_route", activity: "field_visit" };
  assert.equal(progressSteps(visit).find((s) => s.next).state, "on_site");
  assert.ok(progressBody(visit, "done").error);
  assert.deepEqual(progressBody(visit, "done", { note: "  Repaired  ", outcome: "resolved" }).body,
    { state: "done", expected_revision: 3, note: "Repaired", outcome: "resolved" });
  assert.deepEqual(progressSteps({ activity: "remote_review" }).map((s) => s.state), ["done"]);
  assert.equal(visitCells({ activity: "field_visit", travel_minutes: 0 }).travel, "0 min");
});
