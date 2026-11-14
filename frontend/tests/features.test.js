import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { friendlyEnergy, words } from "../src/friendly.js";
import { dailyForecast, hourlyPower, season, skyLabel } from "../src/forecast.js";
import {
  bucketEnergy,
  demoBuckets,
  localMidnight,
  periodRange,
  total,
} from "../src/periods.js";
import { recommend, requestTypes, routeRequest, users, sites } from "../src/domain.js";

test("export energy becomes a plain sentence; unknown energy does not become zero", () => {
  const home = friendlyEnergy(3.2, "home");
  assert.equal(home.headline.text, "run a big-screen TV for 32 hours");
  assert.equal(home.others.length, 2);
  assert.match(friendlyEnergy(6, "business").headline.text, /display fridge cold for 12 hours/);
  assert.equal(friendlyEnergy(null), null);
  assert.equal(friendlyEnergy(Number.NaN), null);
  assert.equal(words("business").consumption, "Business consumption");
});

test("forecast responds to sunshine, temperature and humidity and never exceeds capacity", () => {
  const base = { radiation: 800, temperature: 15, humidity: 50 };
  const cool = hourlyPower(base, 5);
  assert.ok(cool > 3 && cool <= 5);
  assert.ok(hourlyPower({ ...base, temperature: 35 }, 5) < cool);
  assert.ok(hourlyPower({ ...base, humidity: 95 }, 5) < cool);
  assert.ok(hourlyPower({ ...base, radiation: 400 }, 5) < cool);
  assert.equal(hourlyPower({ ...base, radiation: 0 }, 5), 0);
  assert.ok(hourlyPower({ ...base, radiation: 1400, temperature: -20 }, 5) <= 5);
  assert.equal(hourlyPower({ ...base, humidity: undefined }, 5), null);
  assert.equal(season("2026-11-14"), "Autumn");
  assert.equal(season("2026-07-01"), "Summer");
  assert.equal(skyLabel(10), "Mostly sunny");
});

function weather(days, radiation = (hour) => (hour >= 8 && hour < 16 ? 500 : 0)) {
  const hourly = {
    time: [],
    shortwave_radiation: [],
    temperature_2m: [],
    relative_humidity_2m: [],
    cloud_cover: [],
  };
  for (let day = 0; day < days; day++)
    for (let hour = 0; hour < 24; hour++) {
      hourly.time.push(`2026-11-${14 + day}T${String(hour).padStart(2, "0")}:00`);
      hourly.shortwave_radiation.push(radiation(hour));
      hourly.temperature_2m.push(10);
      hourly.relative_humidity_2m.push(55);
      hourly.cloud_cover.push(30);
    }
  return { hourly };
}

test("daily forecast uses contract prices only when a contract exists", () => {
  const prices = { importPrice: 1.3, exportPrice: 0.55 };
  const [day, next] = dailyForecast(weather(2), 6, prices);
  const hour = hourlyPower({ radiation: 500, temperature: 10, humidity: 55 }, 6);
  assert.ok(Math.abs(day.kwh - hour * 8) < 1e-9);
  assert.equal(day.daylightHours, 8);
  assert.ok(Math.abs(day.value.low - day.kwh * 0.55) < 1e-9);
  assert.ok(Math.abs(day.value.high - day.kwh * 1.3) < 1e-9);
  assert.equal(next.date, "2026-11-15");
  assert.equal(dailyForecast(weather(1), 6, null)[0].value, null);
  assert.deepEqual(dailyForecast(null, 6, prices), []);
  const gaps = weather(1);
  gaps.hourly.temperature_2m[12] = null;
  assert.equal(dailyForecast(gaps, 6, prices)[0].kwh, null);
});

test("period buckets add energy by local hour, day and month and keep gaps empty", () => {
  const series = {
    production: [
      { time: "2026-07-15T09:00:00Z", kwh: 1 },
      { time: "2026-07-15T09:15:00Z", kwh: 2 },
      { time: "2026-07-15T10:00:00Z", kwh: null },
      { time: "2026-07-15T21:30:00Z", kwh: 4 },
    ],
    consumption: [{ time: "2026-07-15T09:00:00Z", kwh: 0.5 }],
  };
  const hours = bucketEnergy(series, "hour");
  assert.deepEqual(
    hours.map((row) => [row.label, row.production, row.consumption]),
    [
      ["12:00", 3, 0.5],
      ["13:00", null, null],
      ["00:00", 4, null],
    ],
  );
  // 21:30 UTC is already the next local day in Bucharest.
  assert.deepEqual(
    bucketEnergy(series, "day").map((row) => [row.label, row.production]),
    [
      ["15 Jul", 3],
      ["16 Jul", 4],
    ],
  );
  assert.equal(bucketEnergy(series, "month")[0].production, 7);
  assert.equal(total(series.production), 7);
  assert.equal(total([{ kwh: null }]), null);
});

test("period ranges start at local midnight", () => {
  const asOf = new Date("2026-07-15T12:15:00Z");
  assert.equal(localMidnight(asOf).toISOString(), "2026-07-14T21:00:00.000Z");
  assert.equal(periodRange("Today", asOf).from.toISOString(), "2026-07-14T21:00:00.000Z");
  assert.equal(periodRange("Weekly", asOf).from.toISOString(), "2026-07-08T21:00:00.000Z");
  assert.equal(demoBuckets("Weekly").length, 7);
  assert.equal(demoBuckets("Monthly").length, 30);
  assert.equal(demoBuckets("Yearly").length, 12);
});

test("saved contract prices drive the task saving", () => {
  const task = { energy: 6, power: 3, from: 12, to: 18, deadline: 18, normal: 19 };
  assert.equal(recommend(task)[0].saving, 4.5);
  const custom = recommend(task, [], "S01", { importPrice: 1, exportPrice: 0.5 })[0];
  assert.equal(custom.saving, 3);
  assert.equal(custom.baseline - custom.cost, custom.saving);
  assert.deepEqual(recommend(task, [], "S01", { importPrice: 0.5, exportPrice: 0.5 }), []);
});

test("request types are extended and the business account is separate", () => {
  assert.equal(requestTypes.length, 13);
  assert.equal(routeRequest("battery").routeTo, "Solar Care");
  assert.equal(routeRequest("unknown").id, "other");
  const business = users.filter((user) => user.business);
  assert.deepEqual(business.map((user) => user.sites), [["S04"]]);
  assert.ok(sites.find((site) => site.id === "S04").business);
  // Seven business sites from the shared fixture; only Bistro Soare has a demo login.
  assert.equal(sites.filter((site) => site.business).length, 7);
});

test("backend and demo request types and lessons stay aligned", () => {
  const backend = readFileSync(new URL("../../backend/customer.py", import.meta.url), "utf8");
  for (const type of requestTypes) {
    assert.ok(backend.includes(`"${type.id}"`) && backend.includes(`"${type.label}"`), type.id);
  }
  const lessons = JSON.parse(
    readFileSync(new URL("../../backend/fixtures/lessons.json", import.meta.url), "utf8"),
  ).lessons;
  assert.equal(lessons.length, 4);
  for (const lesson of lessons) {
    assert.ok(lesson.steps.length >= 3 && lesson.reward_ron > 0);
    for (const question of lesson.questions)
      assert.ok(question.answer >= 0 && question.answer < question.options.length);
  }
});

import {
  consumptionShape,
  estimateDay,
  typicalDailyConsumption,
} from "../src/dailyForecast.js";

test("daily forecast estimates production, consumption and profit from hourly data", () => {
  const hours = Array.from({ length: 24 }, (_, h) => ({
    time: `2026-11-15T${String(h).padStart(2, "0")}:00`,
    kw: h >= 10 && h < 14 ? 2 : 0,
  }));
  const flat = Array(24).fill(1);
  const day = estimateDay(hours, 24, flat, { importPrice: 1.3, exportPrice: 0.55 });
  assert.equal(day.production, 8);
  assert.equal(day.consumption, 24);
  assert.equal(day.selfUse, 4); // 1 kWh used per sunny hour
  assert.equal(day.exported, 4);
  assert.equal(day.imported, 20);
  assert.ok(Math.abs(day.profit - (4 * 1.3 + 4 * 0.55)) < 1e-9);
  assert.ok(Math.abs(day.selfShare - 4 / 24) < 1e-9);
  const gap = hours.map((hour, i) => (i === 12 ? { ...hour, kw: null } : hour));
  assert.equal(estimateDay(gap, 24, flat, { importPrice: 1.3, exportPrice: 0.55 }), null);
  assert.equal(estimateDay(hours, null, flat, { importPrice: 1.3, exportPrice: 0.55 }), null);
});

test("consumption shapes and typical consumption follow the kind of site", () => {
  assert.equal(consumptionShape("home").length, 24);
  assert.notDeepEqual(consumptionShape("business", "Restaurant"), consumptionShape("home"));
  assert.deepEqual(consumptionShape("business", "Factory"), consumptionShape("business", "Warehouse"));
  assert.ok(Math.abs(typicalDailyConsumption({ monthly_import_kwh: 195 }) - 10) < 1e-9);
  assert.equal(typicalDailyConsumption({}), null);
});
