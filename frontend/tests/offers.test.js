import test from "node:test";
import assert from "node:assert/strict";
import {
  addDecimals,
  baniToDecimal,
  compareDecimals,
  decimalToBani,
  formatKwh,
  formatPercent,
  formatPrice,
  formatRon,
  multiplyDecimals,
  normalizeDecimal,
  ratio,
  subtractDecimals,
} from "../src/money.js";
import { messages, t, tn } from "../src/offersText.js";
import {
  auditLines,
  capacityText,
  countdown,
  defaultForm,
  durationText,
  expectedOutcome,
  formFromOffer,
  formToDraft,
  meterDelayed,
  notificationTarget,
  offerTitle,
  offerTotals,
  penaltyPreviewText,
  referenceText,
  relativeUntil,
  savingsView,
  settledMore,
  siteBlocker,
  windowPhase,
} from "../src/offersLogic.js";
import { bucharestParts } from "../src/bucharestTime.js";

const MINUS = "−";

/* ------------------------------------------------------------- money */

test("formatRon shows integer bani in the app's '7.50 RON' style", () => {
  assert.equal(formatRon(750), "7.50 RON");
  assert.equal(formatRon(5), "0.05 RON");
  assert.equal(formatRon(0), "0.00 RON");
  assert.equal(formatRon(123456789), "1,234,567.89 RON");
  assert.equal(formatRon(100000), "1,000.00 RON");
});

test("formatRon uses a real minus sign for negatives and never clamps", () => {
  assert.equal(formatRon(-320), `${MINUS}3.20 RON`);
  assert.equal(formatRon(-1), `${MINUS}0.01 RON`);
  assert.equal(formatRon(-123456), `${MINUS}1,234.56 RON`);
  assert.equal(formatRon(-5, { signed: true }), `${MINUS}0.05 RON`);
  assert.equal(formatRon(5, { signed: true }), "+0.05 RON");
  assert.equal(formatRon(0, { signed: true }), "0.00 RON");
});

test("formatRon refuses non-integer money instead of rounding floats", () => {
  assert.equal(formatRon(7.5), "—");
  assert.equal(formatRon(null), "—");
  assert.equal(formatRon(undefined), "—");
  assert.equal(formatRon("750"), "—");
  // Exact even beyond float-safe cents arithmetic.
  assert.equal(formatRon(900719925474099), "9,007,199,254,740.99 RON");
  assert.equal(baniToDecimal(-105), "-1.05");
});

test("formatKwh and formatPrice format decimal strings exactly", () => {
  assert.equal(formatKwh("10"), "10 kWh");
  assert.equal(formatKwh("2.500"), "2.5 kWh");
  assert.equal(formatKwh("0"), "0 kWh");
  assert.equal(formatKwh("1234.567"), "1,234.567 kWh");
  assert.equal(formatKwh("6.001", { unit: false }), "6.001");
  assert.equal(formatKwh("abc"), "—");
  assert.equal(formatKwh(6), "—", "numbers are not accepted: send strings");
  assert.equal(formatPrice("0.55"), "0.55 RON/kWh");
  assert.equal(formatPrice("1.3"), "1.30 RON/kWh");
  assert.equal(formatPrice("0.5525"), "0.5525 RON/kWh");
  assert.equal(formatPercent(0.6), "60%");
});

test("decimal helpers never go through binary floating point", () => {
  assert.equal(addDecimals("0.1", "0.2"), "0.3");
  assert.equal(addDecimals("10", "2.505", "0.005"), "12.51");
  assert.equal(subtractDecimals("10", "6.001"), "3.999");
  assert.equal(multiplyDecimals("0.70", "20"), "14");
  assert.equal(compareDecimals("10.0", "10"), 0);
  assert.equal(compareDecimals("9.999", "10"), -1);
  assert.equal(normalizeDecimal("0010.500"), "10.5");
  assert.equal(normalizeDecimal("1e3"), null);
  // Half-up away from zero, like the server's single rounding step.
  assert.equal(decimalToBani("0.305"), 31);
  assert.equal(decimalToBani("0.304"), 30);
  assert.equal(decimalToBani("5"), 500);
  assert.equal(ratio("6", "10"), 0.6);
  assert.equal(ratio("12", "10"), 1);
  assert.equal(ratio("1", "0"), 0);
});

/* ------------------------------------------------------------ messages */

test("t() fills placeholders and falls back to the id", () => {
  assert.equal(t("offer.maxPenalty", { amount: "3.00 RON" }), "Maximum penalty: 3.00 RON");
  assert.equal(t("no.such.message"), "no.such.message");
  assert.equal(t("offer.maxPenalty"), "Maximum penalty: {amount}", "missing vars stay visible");
  assert.equal(t("offer.maxPenalty", { amount: 0 }), "Maximum penalty: 0");
});

test("tn() picks the plural form with Intl.PluralRules", () => {
  assert.equal(tn("offer.capacity.takers", 1), "1 place left");
  assert.equal(tn("offer.capacity.takers", 3), "3 places left");
  assert.equal(tn("offer.capacity.takers", 0), "0 places left");
  assert.equal(tn("duration.hours", 2), "2 hours");
});

test("every message is a non-empty string and every placeholder is a word", () => {
  for (const [id, text] of Object.entries(messages)) {
    assert.equal(typeof text, "string", id);
    assert.ok(text.length > 0, id);
    for (const match of text.matchAll(/\{([^}]*)\}/g)) assert.match(match[1], /^\w+$/, id);
  }
});

/* ------------------------------------------------- penalty rule preview */

const baseForm = { ...defaultForm("north", Date.parse("2026-11-15T10:20:00Z")) };

test("builder penalty preview mirrors the server text for each penalty type", () => {
  // Expected strings produced by backend/offers_math.penalty_rule_text.
  assert.equal(
    penaltyPreviewText({ ...baseForm, penaltyValue: "0.3" }),
    "If you use less than 10 kWh within 2 hours, you pay 0.30 RON for each kWh not used.",
  );
  assert.equal(
    penaltyPreviewText({
      ...baseForm,
      type: "export",
      price: "0.70",
      penaltyType: "percent_of_unfulfilled_value",
      penaltyValue: "20",
    }),
    "If you feed less than 10 kWh into the grid within 2 hours, you pay 20% of the offer value of the energy not delivered (0.14 RON per kWh).",
  );
  assert.equal(
    penaltyPreviewText({
      ...baseForm,
      energy: "10",
      windowChoice: "60",
      price: "0.5555",
      penaltyType: "percent_of_unfulfilled_value",
      penaltyValue: "33.33",
    }),
    "If you use less than 10 kWh within 1 hour, you pay 33.33% of the offer value of the energy not used.",
  );
  assert.equal(
    penaltyPreviewText({
      ...baseForm,
      energy: "2.5",
      windowChoice: "custom",
      windowCustom: "90",
      penaltyType: "flat",
      penaltyValue: "5",
    }),
    "If you use less than 2.5 kWh within 1 hour 30 minutes, you pay a flat 5.00 RON.",
  );
  assert.equal(
    penaltyPreviewText({
      ...baseForm,
      type: "export",
      windowChoice: "custom",
      windowCustom: "45",
      penaltyValue: "0",
    }),
    "There is no penalty: if you feed less than 10 kWh into the grid within 45 minutes, you are paid only for what you deliver.",
  );
  assert.equal(
    penaltyPreviewText({
      ...baseForm,
      windowChoice: "custom",
      windowCustom: "61",
      penaltyValue: "0.1234",
    }),
    "If you use less than 10 kWh within 1 hour 1 minute, you pay 0.1234 RON for each kWh not used.",
  );
  assert.equal(penaltyPreviewText({ ...baseForm, energy: "" }), null);
});

test("durationText matches the server's window wording", () => {
  assert.equal(durationText(120), "2 hours");
  assert.equal(durationText(60), "1 hour");
  assert.equal(durationText(90), "1 hour 30 minutes");
  assert.equal(durationText(45), "45 minutes");
  assert.equal(durationText(1440), "24 hours");
});

/* ------------------------------------------------------------- countdown */

test("countdown ticks in hours, minutes and seconds, rounding up", () => {
  const end = "2026-11-15T12:00:00Z";
  assert.deepEqual(countdown(end, Date.parse("2026-11-15T10:54:50.500Z")), {
    ended: false,
    secondsLeft: 3910,
    text: "1 h 05 min 10 s",
  });
  assert.equal(countdown(end, Date.parse("2026-11-15T11:55:51Z")).text, "4 min 09 s");
  assert.equal(countdown(end, Date.parse("2026-11-15T11:59:59.900Z")).text, "1 s");
});

test("countdown never goes negative once the window has ended", () => {
  const end = "2026-11-15T12:00:00Z";
  for (const now of ["2026-11-15T12:00:00Z", "2026-11-15T12:30:00Z", "2026-11-16T00:00:00Z"]) {
    const value = countdown(end, Date.parse(now));
    assert.equal(value.ended, true);
    assert.equal(value.secondsLeft, 0);
    assert.doesNotMatch(value.text, /-|−/);
  }
  assert.equal(countdown("not a time").text, "—");
});

test("relativeUntil describes an offer's closing time", () => {
  const now = Date.parse("2026-11-15T10:00:00Z");
  assert.equal(relativeUntil("2026-11-17T14:30:00Z", now), "in 2 d 4 h");
  assert.equal(relativeUntil("2026-11-15T13:20:00Z", now), "in 3 h 20 min");
  assert.equal(relativeUntil("2026-11-15T10:12:30Z", now), "in 12 min");
  assert.equal(relativeUntil("2026-11-15T10:00:30Z", now), "in less than a minute");
  assert.equal(relativeUntil("2026-11-15T09:00:00Z", now), "ended");
});

test("window phase: running, then waiting for meter data, then settled", () => {
  const offer = { window_end: "2026-11-15T12:00:00Z", settlement: null };
  assert.equal(windowPhase(offer, Date.parse("2026-11-15T11:00:00Z")), "running");
  assert.equal(windowPhase(offer, Date.parse("2026-11-15T12:20:00Z")), "settling");
  assert.equal(windowPhase({ ...offer, settlement: {} }, Date.parse("2026-11-15T11:00:00Z")), "settled");
});

test("meter delay warning only after more than 30 uncovered minutes", () => {
  const offer = {
    window_start: "2026-11-15T10:00:00Z",
    window_end: "2026-11-15T12:00:00Z",
    coverage_ratio: 0,
    settlement: null,
  };
  const at = (iso) => Date.parse(iso);
  assert.equal(meterDelayed(offer, at("2026-11-15T10:25:00Z")), false, "too early to tell");
  assert.equal(meterDelayed(offer, at("2026-11-15T10:45:00Z")), true);
  // 60 minutes elapsed, 45 covered (0.375 of 120): normal reporting lag.
  assert.equal(meterDelayed({ ...offer, coverage_ratio: 0.375 }, at("2026-11-15T11:00:00Z")), false);
  assert.equal(meterDelayed({ ...offer, coverage_ratio: 0.25 }, at("2026-11-15T11:40:00Z")), true);
  assert.equal(
    meterDelayed({ ...offer, settlement: { penalty_waived_reason: "meter_data_incomplete" } }),
    true,
  );
  assert.equal(meterDelayed({ ...offer, settlement: { penalty_waived_reason: null } }), false);
});

/* -------------------------------------------------------- client wording */

test("acceptance wording is honest about negative outcomes", () => {
  assert.equal(expectedOutcome("consume", 750), "You save 7.50 RON compared with your normal price.");
  assert.equal(expectedOutcome("export", 150), "You earn 1.50 RON more than your normal export price.");
  assert.match(expectedOutcome("consume", -200), /costs you 2\.00 RON more/);
  assert.match(expectedOutcome("export", -200), /earn 2\.00 RON less/);
  assert.equal(expectedOutcome("consume", 0), "The same as your normal price.");
  assert.equal(
    referenceText({ reference_price_ron_per_kwh: "1.3", reference_price_source: "default_tariff" }),
    "1.30 RON/kWh — the default tariff (no contract saved)",
  );
  assert.equal(
    referenceText({ reference_price_ron_per_kwh: "0.9", reference_price_source: "contract" }),
    "0.90 RON/kWh — your contract price",
  );
  assert.equal(siteBlocker("export", { has_meter: true, export_capable: false }) !== null, true);
  assert.equal(siteBlocker("consume", { has_meter: true, export_capable: false }), null);
  assert.equal(siteBlocker("consume", { has_meter: false }) !== null, true);
  assert.equal(offerTitle({ type: "export", energy_kwh: "10", offer_price_ron_per_kwh: "0.7" }), "Feed in 10 kWh at 0.70 RON/kWh");
  assert.equal(offerTitle({ title: "Sunny surplus", type: "export" }), "Sunny surplus");
  assert.equal(capacityText(null), "No limit");
  assert.equal(capacityText({ full: true, takers_left: 0, kwh_left: "0" }), "Full — no places left");
  assert.equal(capacityText({ full: false, takers_left: 1, kwh_left: "25.5" }), "1 place left · 25.5 kWh left in total");
});

/* ---------------------------------------------------------- savings */

const summary = (patch) => ({
  lifetime_bani: 0,
  this_month_bani: 0,
  penalties_paid_bani: 0,
  consume_bani: 0,
  export_bani: 0,
  settled_count: 1,
  ...patch,
});

test("savings counter wording for positive, negative, zero and empty", () => {
  assert.equal(savingsView(null).state, "loading");
  const empty = savingsView(summary({ settled_count: 0 }));
  assert.equal(empty.state, "empty");
  assert.match(empty.body, /^Accept an offer to start earning/);
  assert.equal(
    savingsView(summary({ lifetime_bani: 750, consume_bani: 750 })).headline,
    "You've saved 7.50 RON with offers",
  );
  assert.equal(
    savingsView(summary({ lifetime_bani: 300, export_bani: 300 })).headline,
    "You've earned 3.00 RON with offers",
  );
  assert.equal(
    savingsView(summary({ lifetime_bani: 400, consume_bani: 100, export_bani: 300 })).headline,
    "You've saved and earned 4.00 RON with offers",
  );
  const negative = savingsView(summary({ lifetime_bani: -320, consume_bani: -320 }));
  assert.equal(negative.state, "negative");
  assert.equal(negative.headline, "Your offers cost you 3.20 RON so far");
  assert.equal(savingsView(summary({ lifetime_bani: 0 })).state, "zero");
});

test("the counter animates only when more offers settled", () => {
  assert.equal(settledMore(null, summary({})), false, "first load never animates");
  assert.equal(settledMore(summary({ settled_count: 1 }), summary({ settled_count: 2 })), true);
  assert.equal(settledMore(summary({ settled_count: 2 }), summary({ settled_count: 2 })), false);
});

/* ------------------------------------------------------ notifications */

test("notification links route to the Offers page per role", () => {
  assert.deepEqual(notificationTarget("offers/mine/abc123", "customer"), {
    page: "Offers",
    focus: { kind: "userOffer", id: "abc123" },
  });
  assert.deepEqual(notificationTarget("offers/demo-offer-north-consume", "customer"), {
    page: "Offers",
    focus: { kind: "offer", id: "demo-offer-north-consume" },
  });
  assert.deepEqual(notificationTarget("offers/xyz", "supervisor"), {
    page: "Offers",
    focus: { kind: "managerOffer", id: "xyz" },
  });
  assert.equal(notificationTarget("offers/xyz", "technician"), null);
  assert.equal(notificationTarget(null, "customer"), null);
  assert.equal(notificationTarget("https://example.com", "customer"), null);
  assert.equal(notificationTarget("offers/../admin", "customer"), null);
});

/* -------------------------------------------------- draft serialisation */

test("draft from form: decimal strings, Bucharest local expiry to UTC", () => {
  const { draft, errors } = formToDraft({
    ...baseForm,
    energy: " 12,5 ",
    price: "0.550",
    penaltyValue: "0.30",
    expiryDate: "2026-11-20",
    expiryTime: "18:00",
  });
  assert.deepEqual(errors, []);
  assert.equal(draft.energy_kwh, "12.5");
  assert.equal(draft.offer_price_ron_per_kwh, "0.55");
  assert.equal(draft.penalty_value, "0.3");
  assert.equal(typeof draft.window_minutes, "number");
  assert.equal(draft.window_minutes, 120);
  assert.equal(draft.offer_expires_at, "2026-11-20T16:00:00.000Z", "winter: UTC+2");
  const summer = formToDraft({ ...baseForm, expiryDate: "2026-07-15", expiryTime: "10:00" });
  assert.equal(summer.draft.offer_expires_at, "2026-07-15T07:00:00.000Z", "summer: UTC+3");
  for (const key of ["energy_kwh", "offer_price_ron_per_kwh", "penalty_value"])
    assert.equal(typeof draft[key], "string");
});

test("draft targeting fields are sent only for their mode", () => {
  const all = formToDraft({ ...baseForm, segment: "prosumers", userIds: ["x"], minKwp: "3" }).draft;
  assert.equal(all.target_mode, "all");
  assert.equal(all.target_segment, null);
  assert.equal(all.target_min_kwp, null);
  assert.deepEqual(all.target_user_ids, []);

  const segment = formToDraft({ ...baseForm, targetMode: "segment", segment: "prosumers", minKwp: "3.5" });
  assert.deepEqual(segment.errors, []);
  assert.equal(segment.draft.target_segment, "prosumers");
  assert.equal(segment.draft.target_min_kwp, "3.5");

  const clients = formToDraft({ ...baseForm, targetMode: "clients", userIds: ["a", "b", "a"] });
  assert.deepEqual(clients.draft.target_user_ids, ["a", "b"]);
  assert.equal(clients.draft.target_segment, null);
  assert.deepEqual(
    formToDraft({ ...baseForm, targetMode: "clients", userIds: [] }).errors.map((e) => e.field),
    ["userIds"],
  );

  const zone = formToDraft({ ...baseForm, incidentId: "inc-1", incidentZone: "Pipera", zoneOnly: true }).draft;
  assert.equal(zone.linked_incident_id, "inc-1");
  assert.equal(zone.target_zone, "Pipera");
  const noZone = formToDraft({ ...baseForm, incidentId: "", incidentZone: "Pipera", zoneOnly: true }).draft;
  assert.equal(noZone.target_zone, null, "a zone needs a linked incident");
  const limits = formToDraft({ ...baseForm, maxTakers: "5", maxTotalKwh: "50" }).draft;
  assert.equal(limits.max_takers, 5);
  assert.equal(limits.max_total_kwh, "50");
});

test("local validation catches what the server's format check would reject", () => {
  const fields = (patch) => formToDraft({ ...baseForm, ...patch }).errors.map((e) => e.field);
  assert.deepEqual(fields({ energy: "0" }), ["energy"]);
  assert.deepEqual(fields({ energy: "1.2345" }), ["energy"]);
  assert.deepEqual(fields({ energy: "-1" }), ["energy"]);
  assert.deepEqual(fields({ price: "11" }), ["price"]);
  assert.deepEqual(fields({ windowChoice: "custom", windowCustom: "10" }), ["window"]);
  assert.deepEqual(fields({ penaltyType: "flat", penaltyValue: "5.555" }), ["penaltyValue"]);
  assert.deepEqual(fields({ penaltyType: "percent_of_unfulfilled_value", penaltyValue: "101" }), ["penaltyValue"]);
  assert.deepEqual(fields({ expiryDate: "2026-03-29", expiryTime: "03:30" }), ["expiry"], "spring gap");
  assert.deepEqual(fields({ maxTotalKwh: "5" }), ["maxTotalKwh"], "below the block size");
  assert.deepEqual(fields({ maxTakers: "0" }), ["maxTakers"]);
  assert.deepEqual(fields({ areaId: "" }), ["areaId"]);
});

test("a saved offer round-trips through the builder form", () => {
  const offer = {
    type: "export",
    title: "Surplus",
    energy_kwh: "10",
    offer_price_ron_per_kwh: "0.7",
    window_minutes: 75,
    penalty_type: "percent_of_unfulfilled_value",
    penalty_value: "20",
    offer_expires_at: "2026-11-22T10:00:00Z",
    area_id: "north",
    target_mode: "segment",
    target_segment: "prosumers",
    target_min_kwp: "3",
    target_zone: null,
    target_user_ids: [],
    max_takers: 4,
    max_total_kwh: null,
    linked_incident_id: null,
  };
  const form = formFromOffer(offer);
  assert.equal(form.windowChoice, "custom");
  assert.equal(form.windowCustom, "75");
  assert.equal(form.expiryDate, "2026-11-22");
  assert.equal(form.expiryTime, "12:00");
  const { draft, errors } = formToDraft(form);
  assert.deepEqual(errors, []);
  assert.equal(draft.offer_expires_at, "2026-11-22T10:00:00.000Z");
  assert.equal(draft.window_minutes, 75);
  assert.equal(draft.max_takers, 4);
  assert.deepEqual(bucharestParts("2026-07-15T07:00:00Z"), { date: "2026-07-15", time: "10:00" });
  assert.equal(bucharestParts("nope"), null);
});

/* ------------------------------------------------------------ manager */

test("offer totals add counts, exact kWh and bani", () => {
  const stats = (patch) => ({
    targeted: 2,
    accepted: 1,
    fulfilled: 1,
    partial: 0,
    failed: 0,
    total_kwh_committed: "10",
    total_kwh_delivered: "6.001",
    total_penalties_bani: 120,
    charges_bani: 300,
    payouts_bani: 0,
    client_savings_bani: -50,
    ...patch,
  });
  const totals = offerTotals([
    { audience_size: 3, stats: stats({}) },
    { audience_size: 1, stats: stats({ total_kwh_delivered: "0.999", payouts_bani: 700, client_savings_bani: 20 }) },
  ]);
  assert.equal(totals.count, 2);
  assert.equal(totals.audience, 4);
  assert.equal(totals.committed, "20");
  assert.equal(totals.delivered, "7");
  assert.equal(totals.penalties, 240);
  assert.equal(totals.payouts, 700);
  assert.equal(totals.savings, -30);
  assert.equal(offerTotals([]).committed, "0");
});

test("audit lines show changed fields from detail.changed", () => {
  const lines = auditLines(
    {
      action: "offer.updated",
      detail: { changed: { offer_price_ron_per_kwh: ["0.55", "0.6"], target_user_ids: [[], ["a"]] } },
    },
    (iso) => `T(${iso})`,
  );
  assert.deepEqual(lines, ["Price (RON/kWh): 0.55 → 0.6", "Hand-picked clients: — → a"]);
  assert.deepEqual(
    auditLines({ action: "offer.updated", detail: { changed: { offer_expires_at: ["a", "b"] } } }, (x) => `T${x}`),
    ["Closes: Ta → Tb"],
  );
  assert.deepEqual(auditLines({ action: "offer.created", detail: { type: "consume" } }), []);
  assert.deepEqual(auditLines({ action: "offer.settled", detail: { amount_bani: -120 } }), [
    `Amount: ${MINUS}1.20 RON`,
  ]);
  assert.deepEqual(auditLines({ action: "offer.published", detail: null }), []);
});
