import test from "node:test";
import assert from "node:assert/strict";
import { seed, users, sites } from "../src/domain.js";
import {
  autoAssign,
  assignCrew,
  cancelAssignment,
  crewBusy,
  eligibleCrews,
  resolveIncident,
  routeVisit,
  scheduleMeeting,
  sendTeam,
  skipReason,
  teamsReport,
  visibleIncidents,
} from "../src/dispatch.js";

const byId = (id) => users.find((u) => u.id === id);
const ceo = byId("u5"),
  manager = byId("u6"),
  dispatcher = byId("u7"),
  dispatcherCentral = byId("u14"),
  ioana = byId("u8"),
  mihai = byId("u9");
const NOW = "2026-11-14T11:30:00Z";
const incident = (id, site, family, tier, age, status = "New") => ({
  id,
  site,
  title: `${family} case`,
  family,
  tier,
  owner: "Solar O&M",
  status,
  confirmedOwner: "",
  revision: 1,
  age,
  timeline: [],
});

test("auto-assign walks severity order, oldest first within a tier, until no crew is free", () => {
  const db = seed();
  db.incidents = [
    incident("A", "S01", "Production", "P2", 300),
    incident("B", "S02", "Temperature", "P1", 10),
    incident("C", "S03", "Telemetry", "P1", 90),
    incident("D", "S05", "Local issue", "P0", 1),
  ];
  // A second North crew so that two assignments can happen.
  db.crews.push({ ...db.crews[0], id: "C9", name: "Solar Care B", members: ["Demo"] });
  const result = autoAssign(db, dispatcher, NOW);
  assert.deepEqual(
    result.assigned.map((a) => [a.incident, a.crew]),
    [
      ["D", "Solar Care"],
      ["C", "Solar Care B"],
    ],
  );
  assert.deepEqual(
    result.skipped.map((s) => s.incident),
    ["B", "A"],
  );
  assert.match(result.skipped[0].reason, /No crew free/);
  assert.equal(db.incidents.find((i) => i.id === "D").status, "Crew assigned");
  assert.ok(
    db.incidents
      .find((i) => i.id === "D")
      .timeline.some((t) => t.text === "Assigned by severity: Solar Care" && t.actor === dispatcher.name),
  );
  for (const a of result.assigned) {
    assert.equal(a.kind, "dispatch");
    assert.equal(a.assignedBy, dispatcher.name);
    assert.equal(a.assignedAt, NOW);
    assert.equal(a.area, "North");
  }
});

test("auto-assign on the seed gives the North crew the P1 incident and explains every skip", () => {
  const db = seed();
  const { assigned, skipped } = autoAssign(db, dispatcher, NOW);
  assert.deepEqual(assigned.map((a) => a.incident), ["I102"]);
  // Only North incidents are considered by the North dispatcher.
  for (const s of skipped)
    assert.equal(sites.find((x) => x.id === db.incidents.find((i) => i.id === s.incident).site).area, "North");
  assert.ok(skipped.every((s) => s.reason));
  // Central dispatcher: I104 and I105 are both P1; the older one (I105) wins.
  const central = autoAssign(db, dispatcherCentral, NOW);
  assert.deepEqual(central.assigned.map((a) => a.incident), ["I105"]);
});

test("billing questions and unknown families are never given to a crew", () => {
  const db = seed();
  db.incidents = [
    incident("BILL", "S01", "Billing", "P0", 500),
    incident("WX", "S02", "Weather", "P1", 400),
    incident("OK", "S03", "Production", "P3", 1),
  ];
  const { assigned, skipped } = autoAssign(db, dispatcher, NOW);
  assert.deepEqual(assigned.map((a) => a.incident), ["OK"]);
  assert.match(skipped.find((s) => s.incident === "BILL").reason, /Billing/);
  assert.match(skipped.find((s) => s.incident === "WX").reason, /No North crew covers Weather/);
  assert.throws(() => assignCrew(db, dispatcher, "BILL", "Solar Care"), /Billing/);
});

test("eligibility needs the same area and skill; availability needs no active dispatch", () => {
  const db = seed();
  const i101 = db.incidents.find((i) => i.id === "I101");
  assert.deepEqual(eligibleCrews(db, i101).map((c) => c.name), ["Solar Care"]);
  const i104 = db.incidents.find((i) => i.id === "I104");
  assert.deepEqual(eligibleCrews(db, i104).map((c) => c.name), ["Grid Response"]);
  assignCrew(db, dispatcher, "I101", "Solar Care", NOW);
  assert.equal(crewBusy(db, "Solar Care").incident, "I101");
  const i102 = db.incidents.find((i) => i.id === "I102");
  assert.deepEqual(eligibleCrews(db, i102), []);
  assert.equal(eligibleCrews(db, i102, { availableOnly: false })[0].busyWith.incident, "I101");
  assert.match(skipReason(db, i102), /Solar Care is on I101/);
  assert.throws(() => assignCrew(db, dispatcher, "I102", "Solar Care"), /not available/);
  // Wrong area and wrong role are refused.
  assert.throws(() => assignCrew(db, dispatcher, "I104", "Grid Response"), /outside your area/);
  assert.throws(() => assignCrew(db, manager, "I102", "Solar Care"), /Only the PPC dispatcher/);
  assert.throws(() => assignCrew(db, ceo, "I102", "Solar Care"), /Only the PPC dispatcher/);
  assert.throws(() => autoAssign(db, manager), /Only the PPC dispatcher/);
  // Cancelling frees the crew again.
  const active = crewBusy(db, "Solar Care");
  cancelAssignment(db, dispatcher, active.id, NOW);
  assert.equal(crewBusy(db, "Solar Care"), null);
});

test("send the team marks the crew busy and writes the incident log", () => {
  const db = seed();
  const a = sendTeam(db, ioana, "I101", NOW);
  assert.equal(a.status, "Team sent");
  assert.equal(a.crew, "Solar Care");
  const i101 = db.incidents.find((i) => i.id === "I101");
  assert.equal(i101.status, "Team sent");
  assert.equal(i101.timeline.at(-1).text, "Team sent on site: Solar Care");
  assert.equal(i101.timeline.at(-1).actor, ioana.name);
  assert.equal(crewBusy(db, "Solar Care").id, a.id);
  // Busy on I101: cannot be sent elsewhere until resolved.
  assert.throws(() => sendTeam(db, ioana, "I102", NOW), /already on I101/);
  // An assigned dispatch advances instead of a duplicate being created.
  const db2 = seed();
  const assigned = assignCrew(db2, dispatcher, "I102", "Solar Care", NOW);
  sendTeam(db2, ioana, "I102", NOW);
  assert.equal(db2.assignments.length, 1);
  assert.equal(assigned.status, "Team sent");
  // Outside the crew area.
  assert.throws(() => sendTeam(db, ioana, "I104", NOW), /outside your crew's area/);
  assert.throws(() => sendTeam(db, dispatcher, "I101", NOW), /crew technician/);
});

test("meetings are booked for the crew and overlapping meetings are rejected", () => {
  const db = seed();
  db.visits.push({ id: "V1", incident: "I101", site: "S01", status: "Awaiting review", replies: [] });
  const m = scheduleMeeting(db, ioana, "I101", { date: "2026-11-16", start: "10:00", end: "11:00" }, NOW);
  assert.equal(m.kind, "meeting");
  assert.equal(m.status, "Scheduled");
  assert.equal(db.visits[0].status, "Meeting booked");
  const i101 = db.incidents.find((i) => i.id === "I101");
  assert.match(i101.timeline.at(-1).text, /Meeting booked with the customer: 2026-11-16 10:00–11:00/);
  assert.throws(
    () => scheduleMeeting(db, ioana, "I102", { date: "2026-11-16", start: "10:30", end: "11:30" }, NOW),
    /already has a meeting/,
  );
  // Back-to-back and other days are fine; meetings do not block dispatch availability.
  scheduleMeeting(db, ioana, "I102", { date: "2026-11-16", start: "11:00", end: "12:00" }, NOW);
  scheduleMeeting(db, ioana, "I102", { date: "2026-11-17", start: "10:30", end: "11:30" }, NOW);
  assert.equal(crewBusy(db, "Solar Care"), null);
  // Another crew may meet at the same time.
  scheduleMeeting(db, mihai, "I104", { date: "2026-11-16", start: "10:00", end: "11:00" }, NOW);
  assert.throws(
    () => scheduleMeeting(db, ioana, "I101", { date: "2026-11-18", start: "12:00", end: "11:00" }, NOW),
    /end after it starts/,
  );
  assert.throws(() => scheduleMeeting(db, ioana, "I101", { date: "", start: "10:00", end: "11:00" }, NOW), /date/);
});

test("resolving frees the crew and only the working crew can resolve", () => {
  const db = seed();
  assert.throws(() => resolveIncident(db, ioana, "I101", "", NOW), /Only the crew working/);
  sendTeam(db, ioana, "I101", NOW);
  const done = resolveIncident(db, ioana, "I101", "Panels cleaned (synthetic)", NOW);
  assert.equal(done.status, "Completed");
  assert.equal(db.incidents.find((i) => i.id === "I101").status, "Resolved");
  assert.equal(crewBusy(db, "Solar Care"), null);
  assert.match(db.incidents.find((i) => i.id === "I101").timeline.at(-1).text, /Resolved by Solar Care: Panels cleaned/);
  // The freed crew can be sent to the next case.
  sendTeam(db, ioana, "I102", NOW);
  const report = teamsReport(db, ceo).crews.find((c) => c.name === "Solar Care");
  assert.equal(report.completed.P2, 1);
  assert.equal(report.open.P1, 1);
  assert.equal(report.available, false);
});

test("technicians see every incident in their crew's area", () => {
  const db = seed();
  const ids = visibleIncidents(db, ioana).map((i) => i.id).sort();
  assert.deepEqual(ids, ["I101", "I102", "I103", "I108"]);
  assert.deepEqual(visibleIncidents(db, mihai).map((i) => i.id).sort(), ["I104", "I105"]);
  // Safety order is kept.
  assert.equal(visibleIncidents(db, ioana)[0].tier, "P1");
});

test("area manager sees only his area and the same team data as the overall manager", () => {
  const db = seed();
  assignCrew(db, dispatcher, "I102", "Solar Care", NOW);
  assignCrew(db, dispatcherCentral, "I104", "Grid Response", NOW);
  scheduleMeeting(db, ioana, "I101", { date: "2026-11-16", start: "09:00", end: "10:00" }, NOW);
  const all = teamsReport(db, ceo),
    north = teamsReport(db, manager);
  assert.deepEqual(north.areas, ["North"]);
  assert.deepEqual(
    north.rows,
    all.rows.filter((r) => r.area === "North"),
  );
  assert.deepEqual(
    north.crews,
    all.crews.filter((c) => c.area === "North"),
  );
  assert.equal(north.crews.length, 1);
  assert.deepEqual(north.crews[0].members, db.crews[0].members);
  assert.ok(north.rows.some((r) => r.kind === "meeting" && r.slot === "2026-11-16 09:00–10:00"));
  assert.ok(north.rows.some((r) => r.status === "Not assigned"));
  assert.ok(!north.rows.some((r) => r.area !== "North"));
  assert.deepEqual(
    visibleIncidents(db, manager).map((i) => i.id).sort(),
    ["I101", "I102", "I103", "I108"],
  );
});

test("request types that name a crew go to the crew of the customer's area", () => {
  const db = seed();
  assert.equal(routeVisit("solar", "S01", db.crews), "Solar Care");
  assert.equal(routeVisit("solar", "S17", db.crews), "Field Service");
  assert.equal(routeVisit("grid", "S09", db.crews), "Grid Response");
  assert.equal(routeVisit("billing", "S04", db.crews), "PPC Triage");
  assert.equal(routeVisit("other", "S04", db.crews), "PPC Triage");
});
