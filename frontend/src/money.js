// Money, energy and decimal-string helpers for Power Block Offers. Pure; Intl only.
//
// Money arrives from the server as integer bani (1 RON = 100 bani) and is never
// recomputed here. kWh and RON/kWh prices are decimal strings ("10", "0.55"); the
// helpers below parse them into BigInt units so nothing shown to people goes through
// binary floating point. One display style everywhere: "1,234.50 RON", "−7.50 RON".

const LOCALE = "en-GB";
const MINUS = "−"; // a real minus sign, not a hyphen

const ronFormats = {
  plain: new Intl.NumberFormat(LOCALE, {
    style: "currency",
    currency: "RON",
    currencyDisplay: "code",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }),
  signed: new Intl.NumberFormat(LOCALE, {
    style: "currency",
    currency: "RON",
    currencyDisplay: "code",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    signDisplay: "exceptZero",
  }),
};

/** Integer bani → exact decimal string in RON ("-1234.05"). */
export function baniToDecimal(bani) {
  const n = BigInt(bani);
  const negative = n < 0n;
  const abs = negative ? -n : n;
  return `${negative ? "-" : ""}${abs / 100n}.${String(abs % 100n).padStart(2, "0")}`;
}

const isBani = (value) =>
  typeof value === "bigint" ||
  (typeof value === "number" && Number.isSafeInteger(value));

/**
 * "1,234.50 RON" / "−7.50 RON" from integer bani. `signed: true` adds "+" to
 * positive amounts (for gains and changes). Anything that is not an integer is "—".
 */
export function formatRon(bani, { signed = false } = {}) {
  if (!isBani(bani)) return "—";
  const parts = (signed ? ronFormats.signed : ronFormats.plain).formatToParts(
    baniToDecimal(bani),
  );
  const number = parts
    .filter((part) => part.type !== "currency" && part.type !== "literal")
    .map((part) => (part.type === "minusSign" ? MINUS : part.value))
    .join("");
  return `${number} RON`;
}

/** Absolute value of integer bani (for "cost you X" wording). */
export const absBani = (bani) => (isBani(bani) ? (bani < 0 ? -bani : bani) : bani);

/* ------------------------------------------------------------------ decimals */

const DECIMAL = /^(-)?(\d+)(?:\.(\d+))?$/;

/** Decimal string → { units: BigInt, scale } (value = units / 10^scale), or null. */
export function parseDecimal(text) {
  if (typeof text !== "string" && typeof text !== "bigint") return null;
  const match = DECIMAL.exec(String(text).trim());
  if (!match) return null;
  const fraction = match[3] || "";
  const units = BigInt(match[2] + fraction);
  return { units: match[1] ? -units : units, scale: fraction.length };
}

const pow10 = (n) => 10n ** BigInt(n);
const rescale = (d, scale) => d.units * pow10(scale - d.scale);

/** Canonical plain decimal string: no exponent, no trailing zeros ("10", "0.55"). */
export function decimalString({ units, scale }) {
  const negative = units < 0n;
  const digits = (negative ? -units : units).toString().padStart(scale + 1, "0");
  let whole = scale ? digits.slice(0, -scale) : digits;
  let fraction = scale ? digits.slice(-scale) : "";
  fraction = fraction.replace(/0+$/, "");
  whole = whole.replace(/^0+(?=\d)/, "");
  const text = fraction ? `${whole}.${fraction}` : whole;
  return negative && text !== "0" ? `-${text}` : text;
}

/** Canonical form of a decimal string, or null when it is not one. */
export function normalizeDecimal(text) {
  const d = parseDecimal(text);
  return d ? decimalString(d) : null;
}

export function addDecimals(...values) {
  let total = { units: 0n, scale: 0 };
  for (const value of values) {
    const d = parseDecimal(value);
    if (!d) continue;
    const scale = Math.max(total.scale, d.scale);
    total = { units: rescale(total, scale) + rescale(d, scale), scale };
  }
  return decimalString(total);
}

export function subtractDecimals(a, b) {
  const x = parseDecimal(a),
    y = parseDecimal(b);
  if (!x || !y) return null;
  const scale = Math.max(x.scale, y.scale);
  return decimalString({ units: rescale(x, scale) - rescale(y, scale), scale });
}

export function multiplyDecimals(a, b) {
  const x = parseDecimal(a),
    y = parseDecimal(b);
  if (!x || !y) return null;
  return decimalString({ units: x.units * y.units, scale: x.scale + y.scale });
}

/** −1, 0 or 1; null when either side is not a decimal. */
export function compareDecimals(a, b) {
  const x = parseDecimal(a),
    y = parseDecimal(b);
  if (!x || !y) return null;
  const scale = Math.max(x.scale, y.scale);
  const diff = rescale(x, scale) - rescale(y, scale);
  return diff < 0n ? -1 : diff > 0n ? 1 : 0;
}

/** Number of decimals as written ("0.550" → 3); null when not a decimal. */
export function decimalPlaces(text) {
  const d = parseDecimal(text);
  return d ? d.scale : null;
}

/**
 * Exact decimal → integer bani, rounded half-up away from zero (the server's rule).
 * Used only to *display* a typed amount (e.g. a flat penalty) in the RON style.
 */
export function decimalToBani(text) {
  const d = parseDecimal(text);
  if (!d) return null;
  const scaled = d.units * 100n;
  const divisor = pow10(d.scale);
  const negative = scaled < 0n;
  const abs = negative ? -scaled : scaled;
  let result = abs / divisor;
  if ((abs % divisor) * 2n >= divisor) result += 1n;
  return Number(negative ? -result : result);
}

/** Share a/b in [0, 1] for progress bars only (display, never money). */
export function ratio(part, whole) {
  const x = parseDecimal(part),
    y = parseDecimal(whole);
  if (!x || !y || y.units <= 0n) return 0;
  const scale = Math.max(x.scale, y.scale);
  const value = Number((rescale(x, scale) * 10000n) / rescale(y, scale)) / 10000;
  return Math.min(1, Math.max(0, value));
}

/* --------------------------------------------------------------- formatting */

const numberFormat = (min, max) =>
  new Intl.NumberFormat(LOCALE, {
    minimumFractionDigits: min,
    maximumFractionDigits: max,
  });
const kwhFormat = numberFormat(0, 3);
const priceFormat = numberFormat(2, 4);
const percentFormat = new Intl.NumberFormat(LOCALE, {
  style: "percent",
  maximumFractionDigits: 0,
});

const formatDecimal = (format, text) => {
  const normalized = normalizeDecimal(text);
  if (normalized === null) return null;
  return format
    .formatToParts(normalized)
    .map((part) => (part.type === "minusSign" ? MINUS : part.value))
    .join("");
};

/** "10 kWh", "2.5 kWh", "1,234.567 kWh" from a decimal string. */
export function formatKwh(text, { unit = true } = {}) {
  const value = formatDecimal(kwhFormat, text);
  if (value === null) return "—";
  return unit ? `${value} kWh` : value;
}

/** "0.55 RON/kWh", "0.5525 RON/kWh" from a decimal string (2–4 decimals). */
export function formatPrice(text, { unit = true } = {}) {
  const value = formatDecimal(priceFormat, text);
  if (value === null) return "—";
  return unit ? `${value} RON/kWh` : value;
}

/** "60%" from a ratio in [0, 1] (coverage, progress). */
export function formatPercent(value) {
  return Number.isFinite(value) ? percentFormat.format(value) : "—";
}
