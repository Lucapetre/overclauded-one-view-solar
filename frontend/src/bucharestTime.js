// Europe/Bucharest wall-clock helpers for meeting booking. Pure; uses Intl only.
export const TIME_ZONE = "Europe/Bucharest";
export const MAX_MEETING_MINUTES = 4 * 60;

const partsFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: TIME_ZONE,
  hourCycle: "h23",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

function wallParts(utcMs) {
  const p = Object.fromEntries(
    partsFormat.formatToParts(new Date(utcMs)).map((x) => [x.type, x.value]),
  );
  return {
    year: +p.year,
    month: +p.month,
    day: +p.day,
    hour: +p.hour % 24,
    minute: +p.minute,
    second: +p.second,
  };
}

/** Offset of Bucharest wall time from UTC at the given instant, in ms. */
function offsetMs(utcMs) {
  const p = wallParts(utcMs);
  const asUtc = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second);
  return asUtc - Math.floor(utcMs / 1000) * 1000;
}

/**
 * Bucharest local date ("YYYY-MM-DD") and time ("HH:MM") → UTC Date.
 * Returns null for malformed input, impossible dates, and wall times that do not
 * exist because the clocks jump forward (last Sunday of March, 03:00–04:00).
 * In the repeated autumn hour the later (winter-time) instant is chosen.
 */
export function bucharestToUtc(date, time) {
  const d = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date || "");
  const t = /^(\d{2}):(\d{2})$/.exec(time || "");
  if (!d || !t) return null;
  const [year, month, day, hour, minute] = [d[1], d[2], d[3], t[1], t[2]].map(Number);
  const wall = Date.UTC(year, month - 1, day, hour, minute);
  let utc = wall - offsetMs(wall);
  const second = wall - offsetMs(utc);
  if (second !== utc) utc = second;
  const back = wallParts(utc);
  if (
    back.year !== year ||
    back.month !== month ||
    back.day !== day ||
    back.hour !== hour ||
    back.minute !== minute
  )
    return null;
  return new Date(utc);
}

/** Today's calendar date in Bucharest, "YYYY-MM-DD". */
export function bucharestToday(now = new Date()) {
  const p = wallParts(now.getTime());
  return `${p.year}-${String(p.month).padStart(2, "0")}-${String(p.day).padStart(2, "0")}`;
}

/**
 * A meeting window from Bucharest local inputs.
 * → { start, end } as ISO 8601 UTC strings, or { error } with a plain sentence.
 */
export function meetingWindow(date, startTime, endTime) {
  if (!date || !startTime || !endTime)
    return { error: "Choose a date, a start time and an end time." };
  const start = bucharestToUtc(date, startTime),
    end = bucharestToUtc(date, endTime);
  if (!start || !end)
    return {
      error:
        "That date or time does not exist in Bucharest (for example during the spring clock change). Choose another time.",
    };
  if (end <= start)
    return { error: "The meeting must end after it starts, on the same day." };
  if (end - start > MAX_MEETING_MINUTES * 60000)
    return { error: "A meeting can last at most 4 hours." };
  return { start: start.toISOString(), end: end.toISOString() };
}

const two = (n) => String(n).padStart(2, "0");
const clock = (p) => `${two(p.hour)}:${two(p.minute)}`;
const dateOf = (p) => `${p.year}-${two(p.month)}-${two(p.day)}`;

/** "YYYY-MM-DD HH:MM–HH:MM" in Bucharest time (the AssignmentReport slot format). */
export function slotLabel(startIso, endIso) {
  if (!startIso || !endIso) return null;
  const a = Date.parse(startIso),
    b = Date.parse(endIso);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  const s = wallParts(a),
    e = wallParts(b);
  return dateOf(s) === dateOf(e)
    ? `${dateOf(s)} ${clock(s)}–${clock(e)}`
    : `${dateOf(s)} ${clock(s)}–${dateOf(e)} ${clock(e)}`;
}

const dayFormat = new Intl.DateTimeFormat("en-GB", {
  timeZone: TIME_ZONE,
  weekday: "short",
  day: "numeric",
  month: "short",
  year: "numeric",
});

/** "Mon, 16 Nov 2026, 10:00–11:00 (Bucharest time)" for people. */
export function meetingLabel(startIso, endIso) {
  const a = Date.parse(startIso),
    b = Date.parse(endIso);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return "an unknown time";
  const s = wallParts(a),
    e = wallParts(b);
  const sameDay = dateOf(s) === dateOf(e);
  return sameDay
    ? `${dayFormat.format(a)}, ${clock(s)}–${clock(e)} (Bucharest time)`
    : `${dayFormat.format(a)}, ${clock(s)} – ${dayFormat.format(b)}, ${clock(e)} (Bucharest time)`;
}
