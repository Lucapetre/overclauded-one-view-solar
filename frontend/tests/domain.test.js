import test from "node:test";
import assert from "node:assert/strict";
import {
  users,
  seed,
  sites,
  crews,
  canSee,
  canDispatch,
  canReview,
  rank,
  recommend,
  eligible,
  timeLabel,
} from "../src/domain.js";
const task = {
  energy: 6,
  power: 3,
  from: 12,
  to: 18,
  deadline: 18,
  normal: 19,
};
test("six kWh shift yields 4.50 RON, half solar yields 2.25", () => {
  const r = recommend(task)[0];
  assert.equal(r.saving, 4.5);
  assert.equal(r.low, 2.25);
  assert.equal(r.start, 13);
  assert.equal(r.baseline - r.cost, r.saving);
});
test("all offered windows obey deadline and duration", () => {
  for (const r of recommend({ ...task, deadline: 15 })) {
    assert.ok(r.start >= task.from);
    assert.ok(r.start + r.duration <= 15);
    assert.equal(r.duration, 2);
  }
});
test("invalid and no benefit tasks have no offer", () => {
  assert.deepEqual(recommend({ ...task, energy: -1 }), []);
  assert.deepEqual(recommend({ ...task, deadline: 12 }), []);
  assert.deepEqual(recommend({ ...task, from: 19, to: 23, deadline: 23 }), []);
  assert.deepEqual(recommend({ ...task, normal: 13 }), []);
});
test("two 3kW tasks fill each slot; third moves later", () => {
  let plans = [
    { ...recommend(task)[0], site: "S01", status: "Accepted" },
    { ...recommend(task)[0], site: "S02", status: "Accepted" },
  ];
  const third = recommend(task, plans, "S03")[0];
  assert.ok(third.start >= 15);
  assert.equal(third.saving, 3.375);
  assert.deepEqual(recommend(task, plans, "S01"), []);
  plans[1].status = "Cancelled";
  assert.equal(recommend(task, plans, "S03")[0].start, 13);
});
test("site access is role and assignment scoped", () => {
  assert.equal(sites.filter((s) => canSee(users[0], s.id)).length, 1);
  assert.equal(sites.filter((s) => canSee(users[4], s.id)).length, 24);
  assert.equal(sites.filter((s) => canSee(users[5], s.id)).length, 8);
  assert.equal(canSee(users[7], "S17"), false);
  assert.equal(canDispatch(users[7]), false);
  assert.equal(canReview(users[7]), true);
  assert.equal(canReview(users[10]), false);
});
test("safety precedes money and missing data stays unknown", () => {
  const db = seed(),
    r = rank(db.incidents);
  assert.equal(r[0].tier, "P1");
  const missing = db.incidents.find((i) => i.family === "Telemetry");
  assert.equal(missing.value, null);
  assert.equal(missing.tier, "P3");
});
test("qualified crews cannot receive overlapping confirmed work", () => {
  const i = seed().incidents[0];
  assert.equal(eligible(crews[0], i, []), true);
  assert.equal(eligible(crews[1], i, []), false);
  assert.equal(
    eligible(crews[0], i, [{ crew: "Solar Care", status: "Confirmed" }]),
    false,
  );
});
test("time formatting supports fractional duration", () => {
  assert.equal(timeLabel(13.25), "13:15");
});
