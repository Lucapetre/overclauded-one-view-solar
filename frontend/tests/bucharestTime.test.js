import test from "node:test";
import assert from "node:assert/strict";
import {
  bucharestToUtc,
  bucharestToday,
  meetingLabel,
  meetingWindow,
  slotLabel,
} from "../src/bucharestTime.js";

test("Bucharest local time converts to UTC in winter (EET, UTC+2)", () => {
  assert.equal(
    bucharestToUtc("2026-11-16", "10:00").toISOString(),
    "2026-11-16T08:00:00.000Z",
  );
  assert.equal(
    bucharestToUtc("2026-01-01", "00:30").toISOString(),
    "2025-12-31T22:30:00.000Z",
  );
});

test("Bucharest local time converts to UTC in summer (EEST, UTC+3)", () => {
  assert.equal(
    bucharestToUtc("2026-07-15", "10:00").toISOString(),
    "2026-07-15T07:00:00.000Z",
  );
});

test("clock change days: spring gap refused, autumn repeat resolved", () => {
  // 29 March 2026: 03:00 EET jumps to 04:00 EEST.
  assert.equal(bucharestToUtc("2026-03-29", "03:30"), null);
  assert.equal(
    bucharestToUtc("2026-03-29", "02:30").toISOString(),
    "2026-03-29T00:30:00.000Z",
  );
  assert.equal(
    bucharestToUtc("2026-03-29", "04:30").toISOString(),
    "2026-03-29T01:30:00.000Z",
  );
  // 25 October 2026: 04:00 EEST falls back to 03:00 EET; 03:30 happens twice.
  assert.equal(
    bucharestToUtc("2026-10-25", "03:30").toISOString(),
    "2026-10-25T01:30:00.000Z",
  );
  assert.equal(
    bucharestToUtc("2026-10-25", "12:00").toISOString(),
    "2026-10-25T10:00:00.000Z",
  );
});

test("malformed or impossible inputs are refused", () => {
  assert.equal(bucharestToUtc("2026-02-31", "10:00"), null);
  assert.equal(bucharestToUtc("2026-11-16", "25:00"), null);
  assert.equal(bucharestToUtc("16/11/2026", "10:00"), null);
  assert.equal(bucharestToUtc("", ""), null);
});

test("meeting window: ISO UTC strings, must end later, at most 4 hours", () => {
  assert.deepEqual(meetingWindow("2026-07-15", "10:00", "11:30"), {
    start: "2026-07-15T07:00:00.000Z",
    end: "2026-07-15T08:30:00.000Z",
  });
  assert.deepEqual(meetingWindow("2026-11-16", "09:00", "13:00"), {
    start: "2026-11-16T07:00:00.000Z",
    end: "2026-11-16T11:00:00.000Z",
  });
  assert.match(meetingWindow("2026-11-16", "11:00", "10:00").error, /end after/);
  assert.match(meetingWindow("2026-11-16", "10:00", "10:00").error, /end after/);
  assert.match(meetingWindow("2026-11-16", "09:00", "13:01").error, /4 hours/);
  assert.match(meetingWindow("2026-03-29", "03:15", "05:00").error, /does not exist/);
  assert.match(meetingWindow("", "10:00", "11:00").error, /Choose a date/);
});

test("today in Bucharest, near midnight UTC", () => {
  assert.equal(bucharestToday(new Date("2026-11-15T22:30:00Z")), "2026-11-16");
  assert.equal(bucharestToday(new Date("2026-11-15T21:30:00Z")), "2026-11-15");
  assert.equal(bucharestToday(new Date("2026-07-15T21:30:00Z")), "2026-07-16");
});

test("slot and meeting labels are in Bucharest time", () => {
  assert.equal(
    slotLabel("2026-07-15T07:00:00Z", "2026-07-15T08:30:00Z"),
    "2026-07-15 10:00–11:30",
  );
  assert.equal(slotLabel(null, "2026-07-15T08:30:00Z"), null);
  const label = meetingLabel("2026-11-16T08:00:00Z", "2026-11-16T09:00:00Z");
  assert.match(label, /16 Nov 2026/);
  assert.match(label, /10:00–11:00 \(Bucharest time\)/);
  assert.equal(meetingLabel("x", "y"), "an unknown time");
});
