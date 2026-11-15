// Pure Power Block Offers logic for the connected app: countdowns, wording, savings
// counter text, notification routing, builder form ⇄ OfferDraft, totals. No React.
// Money is the server's integer bani; nothing here recomputes a settlement.
import { t, tn } from "./offersText.js";
import { bucharestParts, bucharestToUtc } from "./bucharestTime.js";
import {
  addDecimals,
  compareDecimals,
  decimalPlaces,
  decimalString,
  decimalToBani,
  formatKwh,
  formatPrice,
  formatRon,
  multiplyDecimals,
  normalizeDecimal,
  parseDecimal,
} from "./money.js";

export const WINDOW_PRESETS = [30, 60, 120, 240];
export const SETTLEMENT_GRACE_MINUTES = 60;
const MINUTE = 60000;

/* ------------------------------------------------------------- durations */

/** "2 hours", "1 hour 30 minutes", "45 minutes" (the server's window wording). */
export function durationText(minutes) {
  const m = Math.max(0, Math.round(Number(minutes) || 0));
  const hours = Math.floor(m / 60),
    rest = m % 60;
  const parts = [];
  if (hours) parts.push(tn("duration.hours", hours));
  if (rest || !hours) parts.push(tn("duration.minutes", rest));
  return parts.join(" ");
}

const two = (n) => String(n).padStart(2, "0");

/**
 * Live countdown to `endIso`: { ended, secondsLeft, text }. Rounds up to the next
 * whole second so "0 s" is never shown while time remains; past ends are `ended`
 * and never negative.
 */
export function countdown(endIso, now = Date.now()) {
  const end = Date.parse(endIso);
  if (!Number.isFinite(end)) return { ended: false, secondsLeft: null, text: "—" };
  const ms = end - now;
  if (ms <= 0) return { ended: true, secondsLeft: 0, text: t("relative.past") };
  const total = Math.ceil(ms / 1000);
  const h = Math.floor(total / 3600),
    m = Math.floor((total % 3600) / 60),
    s = total % 60;
  const text = h
    ? t("countdown.hms", { h, mm: two(m), ss: two(s) })
    : m
      ? t("countdown.ms", { m, ss: two(s) })
      : t("countdown.s", { s });
  return { ended: false, secondsLeft: total, text };
}

/** "in 2 d 4 h", "in 3 h 20 min", "in 12 min", or "ended" for an offer's closing time. */
export function relativeUntil(iso, now = Date.now()) {
  const end = Date.parse(iso);
  if (!Number.isFinite(end)) return "—";
  const ms = end - now;
  if (ms <= 0) return t("relative.past");
  const minutes = Math.floor(ms / MINUTE);
  const d = Math.floor(minutes / 1440),
    h = Math.floor((minutes % 1440) / 60),
    m = minutes % 60;
  const time = d
    ? t("relative.short.dh", { d, h })
    : h
      ? t("relative.short.hm", { h, m })
      : m
        ? t("relative.short.m", { m })
        : t("relative.short.lessThanMinute");
  return t("relative.in", { time });
}

/* ---------------------------------------------------------- client views */

export const typeLabel = (type) => t(`type.${type}`);

/** The offer's title, or "Use 10 kWh at 0.55 RON/kWh" when it has none. */
export function offerTitle(offer) {
  if (offer?.title) return offer.title;
  return t(`title.${offer?.type === "export" ? "export" : "consume"}`, {
    kwh: formatKwh(offer?.energy_kwh),
    price: formatPrice(offer?.offer_price_ron_per_kwh),
  });
}

/** Remaining capacity in words; `null` capacity means the offer has no limits. */
export function capacityText(capacity) {
  if (!capacity) return t("common.noLimit");
  if (capacity.full) return t("offer.capacity.full");
  const parts = [];
  if (capacity.takers_left != null)
    parts.push(tn("offer.capacity.takers", capacity.takers_left));
  if (capacity.kwh_left != null)
    parts.push(t("offer.capacity.kwh", { kwh: formatKwh(capacity.kwh_left) }));
  return parts.length ? parts.join(" · ") : t("common.noLimit");
}

/** Why a site cannot take this offer (shown before accepting), or null. */
export function siteBlocker(type, site) {
  if (!site) return null;
  if (!site.has_meter) return t("accept.site.cannot.meter");
  if (type === "export" && !site.export_capable) return t("accept.site.cannot.export");
  return null;
}

/** Honest sentence for `savings_if_completed_bani` (may be negative). */
export function expectedOutcome(type, bani) {
  if (!Number.isSafeInteger(bani)) return "—";
  if (bani === 0) return t("accept.expected.even");
  if (bani > 0)
    return t(type === "export" ? "accept.expected.earn" : "accept.expected.save", {
      amount: formatRon(bani),
    });
  return t(type === "export" ? "accept.expected.lossExport" : "accept.expected.lossConsume", {
    amount: formatRon(-bani),
  });
}

export function referenceText(site) {
  if (!site) return "—";
  const source = site.reference_price_source === "contract" ? "contract" : "default_tariff";
  return t(`accept.reference.${source}`, {
    price: formatPrice(site.reference_price_ron_per_kwh),
  });
}

/** The window end if the client accepted at `now` (ISO). */
export const windowEndIfAccepted = (windowMinutes, now = Date.now()) =>
  new Date(now + Number(windowMinutes) * MINUTE).toISOString();

/**
 * Phase of a user offer: "settled" (settlement written), "running" (window open), or
 * "settling" (window ended, waiting up to 60 min for late meter data).
 */
export function windowPhase(userOffer, now = Date.now()) {
  if (userOffer?.settlement) return "settled";
  const end = Date.parse(userOffer?.window_end);
  return Number.isFinite(end) && now >= end ? "settling" : "running";
}

/**
 * Meter data looks delayed: more than 30 minutes (two 15-minute intervals) of the
 * elapsed window have no reading. Readings arrive after each interval ends, so a
 * short lag is normal. After settlement, the server's waiver reason decides.
 */
export function meterDelayed(userOffer, now = Date.now()) {
  if (!userOffer) return false;
  if (userOffer.settlement)
    return userOffer.settlement.penalty_waived_reason === "meter_data_incomplete";
  const start = Date.parse(userOffer.window_start),
    end = Date.parse(userOffer.window_end);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return false;
  const elapsed = Math.min(now, end) - start;
  if (elapsed < 30 * MINUTE) return false;
  const covered = (Number(userOffer.coverage_ratio) || 0) * (end - start);
  return elapsed - covered > 30 * MINUTE;
}

export const outcomeLabel = (status) => t(`status.${status}`);
export const outcomeTone = (status) =>
  status === "completed"
    ? "green"
    : status === "partial"
      ? "yellow"
      : status === "expired_unfulfilled"
        ? "orange"
        : "";
export const waiverText = (reason) => (reason ? t(`waiver.${reason}`) : "");

/** Friendly message for an acceptance error code, or null for unknown codes. */
export function acceptErrorText(error) {
  const code = error?.detail?.code;
  const id = `acceptError.${code}`;
  const text = t(id);
  return text === id ? null : text;
}
/** These codes mean the list is stale and should be refetched. */
export const ACCEPT_REFRESH_CODES = new Set([
  "already_accepted",
  "offer_full",
  "offer_unavailable",
  "offer_closed",
  "not_found",
]);

/* --------------------------------------------------------------- savings */

/**
 * Savings/Earnings counter wording. Never clamps: a negative lifetime total says the
 * offers cost money. → { state: loading|empty|positive|negative|zero, headline, body? }
 */
export function savingsView(summary) {
  if (!summary) return { state: "loading", headline: t("savings.loading") };
  if (!summary.settled_count)
    return {
      state: "empty",
      headline: t("savings.empty.title"),
      body: t("savings.empty.body"),
    };
  const lifetime = summary.lifetime_bani;
  if (lifetime > 0) {
    const id =
      summary.consume_bani > 0 && summary.export_bani > 0
        ? "savings.savedEarned"
        : summary.export_bani > 0 && summary.consume_bani <= 0
          ? "savings.earned"
          : "savings.saved";
    return { state: "positive", headline: t(id, { amount: formatRon(lifetime) }) };
  }
  if (lifetime < 0)
    return {
      state: "negative",
      headline: t("savings.negative", { amount: formatRon(-lifetime) }),
    };
  return { state: "zero", headline: t("savings.zero") };
}

/** True when a newer summary settled more offers than the one seen before. */
export const settledMore = (previous, next) =>
  Boolean(previous && next && next.settled_count > previous.settled_count);

/* --------------------------------------------------------- notifications */

/**
 * Notification link → where to go. "offers/mine/<user_offer_id>" and
 * "offers/<offer_id>" open the Offers page with that item highlighted.
 * Returns null when the role has no Offers page or the link is unknown.
 */
export function notificationTarget(link, role) {
  if (typeof link !== "string") return null;
  const mine = /^offers\/mine\/([\w-]+)$/.exec(link);
  const offer = /^offers\/([\w-]+)$/.exec(link);
  if (role === "customer") {
    if (mine) return { page: "Offers", focus: { kind: "userOffer", id: mine[1] } };
    if (offer) return { page: "Offers", focus: { kind: "offer", id: offer[1] } };
    if (link === "offers") return { page: "Offers", focus: null };
    return null;
  }
  if (role === "supervisor") {
    if (offer) return { page: "Offers", focus: { kind: "managerOffer", id: offer[1] } };
    if (link === "offers" || mine) return { page: "Offers", focus: null };
  }
  return null;
}

/* ------------------------------------------------------------ builder */

export const PENALTY_RULES = {
  per_unfulfilled_kwh: { places: 4, max: "10" },
  percent_of_unfulfilled_value: { places: 2, max: "100" },
  flat: { places: 2, max: "1000" },
};

/** Trim and accept a decimal comma ("0,55" → "0.55"); "" stays "". */
export const cleanDecimal = (raw) =>
  String(raw ?? "")
    .trim()
    .replace(",", ".");

// The server's DecimalText pattern: plain digits, optional fraction, no sign.
const DECIMAL_TEXT = /^\d{1,7}(\.\d{1,6})?$/;

function checkDecimal(raw, { places, max, positive = false }) {
  const text = cleanDecimal(raw);
  if (!DECIMAL_TEXT.test(text)) return null;
  if (decimalPlaces(text) > places) return null;
  if (compareDecimals(text, max) > 0) return null;
  if (positive && compareDecimals(text, "0") <= 0) return null;
  return normalizeDecimal(text);
}

/** Default form: consume, 10 kWh at 0.55, 2 hours, 0.30 RON/kWh, closes in 24 h. */
export function defaultForm(areaId = "", now = Date.now()) {
  const next = new Date(Math.ceil((now + 24 * 60 * MINUTE) / (60 * MINUTE)) * 60 * MINUTE);
  const local = bucharestParts(next);
  return {
    type: "consume",
    title: "",
    energy: "10",
    price: "0.55",
    windowChoice: "120",
    windowCustom: "",
    penaltyType: "per_unfulfilled_kwh",
    penaltyValue: "0.30",
    expiryDate: local.date,
    expiryTime: local.time,
    areaId,
    targetMode: "all",
    segment: "consumers",
    minKwp: "",
    userIds: [],
    maxTakers: "",
    maxTotalKwh: "",
    incidentId: "",
    incidentZone: "",
    zoneOnly: false,
  };
}

/** Saved offer → builder form (UTC expiry shown in Bucharest wall time). */
export function formFromOffer(offer) {
  const local = bucharestParts(offer.offer_expires_at) || { date: "", time: "" };
  const preset = WINDOW_PRESETS.includes(offer.window_minutes);
  return {
    type: offer.type,
    title: offer.title || "",
    energy: offer.energy_kwh,
    price: offer.offer_price_ron_per_kwh,
    windowChoice: preset ? String(offer.window_minutes) : "custom",
    windowCustom: preset ? "" : String(offer.window_minutes),
    penaltyType: offer.penalty_type,
    penaltyValue: offer.penalty_value,
    expiryDate: local.date,
    expiryTime: local.time,
    areaId: offer.area_id,
    targetMode: offer.target_mode || "all",
    segment: offer.target_segment || "consumers",
    minKwp: offer.target_min_kwp || "",
    userIds: [...(offer.target_user_ids || [])],
    maxTakers: offer.max_takers == null ? "" : String(offer.max_takers),
    maxTotalKwh: offer.max_total_kwh || "",
    incidentId: offer.linked_incident_id || "",
    incidentZone: offer.target_zone || "",
    zoneOnly: Boolean(offer.target_zone),
  };
}

export function windowMinutes(form) {
  const raw = form.windowChoice === "custom" ? form.windowCustom : form.windowChoice;
  return /^\d{1,4}$/.test(String(raw).trim()) ? Number(raw) : NaN;
}

/**
 * Builder form → { draft, errors }. The draft is an `OfferDraft` with decimal
 * strings and a UTC expiry converted from Bucharest local time; `errors` are
 * { field, message } problems found before asking the server. Targeting fields
 * are sent only for their mode.
 */
export function formToDraft(form) {
  const errors = [];
  const fail = (field, id) => errors.push({ field, message: t(id) });
  const energy = checkDecimal(form.energy, { places: 3, max: "10000", positive: true });
  if (energy === null) fail("energy", "form.energy");
  const price = checkDecimal(form.price, { places: 4, max: "10" });
  if (price === null) fail("price", "form.price");
  const minutes = windowMinutes(form);
  if (!(minutes >= 15 && minutes <= 1440)) fail("window", "form.window");
  const rule = PENALTY_RULES[form.penaltyType] || PENALTY_RULES.per_unfulfilled_kwh;
  const penalty = checkDecimal(form.penaltyValue, rule);
  if (penalty === null) fail("penaltyValue", `form.penalty.${form.penaltyType}`);
  const expiry = bucharestToUtc(form.expiryDate, form.expiryTime);
  if (!expiry) fail("expiry", "form.expiry");
  if (!form.areaId) fail("areaId", "form.area");
  const title = String(form.title || "").trim();
  if (title.length > 80) fail("title", "form.title");

  const draft = {
    type: form.type === "export" ? "export" : "consume",
    title: title || null,
    energy_kwh: energy ?? cleanDecimal(form.energy),
    offer_price_ron_per_kwh: price ?? cleanDecimal(form.price),
    window_minutes: Number.isFinite(minutes) ? minutes : 0,
    penalty_type: form.penaltyType,
    penalty_value: penalty ?? cleanDecimal(form.penaltyValue),
    offer_expires_at: expiry ? expiry.toISOString() : "",
    area_id: form.areaId,
    target_mode: form.targetMode,
    target_segment: null,
    target_min_kwp: null,
    target_user_ids: [],
    max_takers: null,
    max_total_kwh: null,
    linked_incident_id: form.incidentId || null,
    target_zone: form.incidentId && form.zoneOnly && form.incidentZone ? form.incidentZone : null,
  };
  if (form.targetMode === "segment") {
    draft.target_segment = form.segment === "prosumers" ? "prosumers" : "consumers";
    if (cleanDecimal(form.minKwp)) {
      const kwp = checkDecimal(form.minKwp, { places: 3, max: "1000" });
      if (kwp === null) fail("minKwp", "form.minKwp");
      else draft.target_min_kwp = kwp;
    }
  } else if (form.targetMode === "clients") {
    draft.target_user_ids = [...new Set(form.userIds || [])];
    if (!draft.target_user_ids.length) fail("userIds", "form.clients");
  }
  const takers = String(form.maxTakers ?? "").trim();
  if (takers) {
    if (/^\d{1,6}$/.test(takers) && Number(takers) >= 1 && Number(takers) <= 100000)
      draft.max_takers = Number(takers);
    else fail("maxTakers", "form.maxTakers");
  }
  if (cleanDecimal(form.maxTotalKwh)) {
    const total = checkDecimal(form.maxTotalKwh, { places: 3, max: "1000000", positive: true });
    if (total === null || (energy !== null && compareDecimals(total, energy) < 0))
      fail("maxTotalKwh", "form.maxTotalKwh");
    else draft.max_total_kwh = total;
  }
  return { draft, errors };
}

// At least two decimals, more when the value has them (the server's price_text).
const priceText = (text) => formatPrice(text, { unit: false }).replaceAll(",", "");

/**
 * Instant plain-language penalty rule for the builder, mirroring the server's
 * `penalty_rule_text`. The server's own text (preview summary) is shown as well
 * and is what clients read.
 */
export function penaltyPreviewText(form) {
  const { draft, errors } = formToDraft(form);
  const bad = new Set(errors.map((e) => e.field));
  if (["energy", "price", "window", "penaltyValue"].some((f) => bad.has(f))) return null;
  const type = draft.type;
  const kwh = draft.energy_kwh;
  const window = durationText(draft.window_minutes);
  const value = draft.penalty_value;
  if (compareDecimals(value, "0") === 0) return t(`rule.none.${type}`, { kwh, window });
  const condition = t(`rule.condition.${type}`, { kwh, window });
  const done = t(`rule.done.${type}`);
  if (draft.penalty_type === "per_unfulfilled_kwh")
    return t("rule.per_unfulfilled_kwh", { condition, value: priceText(value), done });
  if (draft.penalty_type === "percent_of_unfulfilled_value") {
    // price × percent / 100, exact; shown only when it fits in 4 decimals.
    const product = parseDecimal(multiplyDecimals(draft.offer_price_ron_per_kwh, value));
    const text = decimalString({ units: product.units, scale: product.scale + 2 });
    const exact = decimalPlaces(text) <= 4;
    return t(exact ? "rule.percentExact" : "rule.percent", {
      condition,
      value: normalizeDecimal(value),
      done,
      perKwh: exact ? priceText(text) : "",
    });
  }
  return t("rule.flat", { condition, amount: formatRon(decimalToBani(value)) });
}

/** Stable JSON of a draft, to detect unsaved changes and to debounce previews. */
export const draftKey = (draft) => JSON.stringify(draft);

/* -------------------------------------------------------------- manager */

export const offerStatusLabel = (status) => t(`offerStatus.${status}`);
export const offerStatusTone = (status) =>
  status === "available" ? "green" : status === "draft" ? "yellow" : "";

/** Totals across listed offers: counts, exact kWh sums and bani sums. */
export function offerTotals(offers = []) {
  const totals = {
    count: offers.length,
    audience: 0,
    targeted: 0,
    accepted: 0,
    fulfilled: 0,
    partial: 0,
    failed: 0,
    committed: "0",
    delivered: "0",
    penalties: 0,
    charges: 0,
    payouts: 0,
    savings: 0,
  };
  for (const offer of offers) {
    const s = offer.stats || {};
    totals.audience += offer.audience_size || 0;
    totals.targeted += s.targeted || 0;
    totals.accepted += s.accepted || 0;
    totals.fulfilled += s.fulfilled || 0;
    totals.partial += s.partial || 0;
    totals.failed += s.failed || 0;
    totals.committed = addDecimals(totals.committed, s.total_kwh_committed || "0");
    totals.delivered = addDecimals(totals.delivered, s.total_kwh_delivered || "0");
    totals.penalties += s.total_penalties_bani || 0;
    totals.charges += s.charges_bani || 0;
    totals.payouts += s.payouts_bani || 0;
    totals.savings += s.client_savings_bani || 0;
  }
  return totals;
}

const FIELD_NAMES = {
  type: "Type",
  title: "Title",
  energy_kwh: "Energy (kWh)",
  offer_price_ron_per_kwh: "Price (RON/kWh)",
  window_minutes: "Window (minutes)",
  penalty_type: "Penalty type",
  penalty_value: "Penalty value",
  offer_expires_at: "Closes",
  area_id: "Area",
  target_mode: "Targeting",
  target_segment: "Segment",
  target_min_kwp: "Minimum kWp",
  target_zone: "Zone",
  target_user_ids: "Hand-picked clients",
  max_takers: "Maximum clients",
  max_total_kwh: "Maximum total kWh",
  linked_incident_id: "Linked incident",
  status: "Status",
  // offer.accepted / settled / published / cancelled details
  user_offer_id: "Acceptance",
  site_id: "Site",
  outcome: "Outcome",
  fulfilled_kwh: "Fulfilled (kWh)",
  amount_bani: "Amount",
  penalty_bani: "Penalty",
  savings_bani: "Client saving",
  reference_price_ron_per_kwh: "Reference price (RON/kWh)",
  reference_price_source: "Reference source",
  audience_size: "Audience",
  previous_status: "Previous status",
  running_windows_closed: "Running windows closed",
};
export const fieldName = (key) => FIELD_NAMES[key] || String(key).replaceAll("_", " ");

const auditValue = (key, value, formatTime) => {
  if (value === null || value === undefined || value === "") return t("common.none");
  if (Array.isArray(value)) return value.length ? value.join(", ") : t("common.none");
  if (key === "offer_expires_at" && formatTime) return formatTime(value);
  if (key.endsWith("_bani") && Number.isSafeInteger(value)) return formatRon(value);
  return String(value);
};

/**
 * Readable lines for an audit entry's detail: "Price (RON/kWh): 0.55 → 0.60" for
 * edits, "key: value" otherwise. `formatTime` renders timestamps (Bucharest).
 */
export function auditLines(entry, formatTime) {
  const detail = entry?.detail;
  if (!detail || typeof detail !== "object") return [];
  if (detail.changed && typeof detail.changed === "object")
    return Object.entries(detail.changed).map(([key, pair]) =>
      t("audit.change", {
        field: fieldName(key),
        old: auditValue(key, pair?.[0], formatTime),
        new: auditValue(key, pair?.[1], formatTime),
      }),
    );
  if (entry.action === "offer.created") return [];
  return Object.entries(detail).map(
    ([key, value]) => `${fieldName(key)}: ${auditValue(key, value, formatTime)}`,
  );
}

export const auditAction = (action) => {
  const id = `audit.${action}`;
  const text = t(id);
  return text === id ? String(action).replace(/^offer\./, "").replaceAll("_", " ") : text;
};

/** Friendly manager error text (offer API codes), or null. */
export function managerErrorText(error) {
  const code = error?.detail?.code;
  const id = `managerError.${code}`;
  const text = t(id, { detail: error?.detail?.message || "" });
  return text === id ? null : text;
}
