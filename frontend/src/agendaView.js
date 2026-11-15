// Pure presentation of the technician agenda: one card per assignment with where to go,
// when, what to do, why, an optional customer contact note and one primary progress
// action. No React, no fetch. Fields the backend may add later (a customer contact note,
// the dispatcher-linked customer video, past jobs) are read defensively.
import { activityText, caseTitle, progressText, shortSiteName } from "./opsView.js";
import { localDateTime, localTime } from "./planView.js";

const first = (...values) => values.find((v) => v != null && String(v).trim() !== "") ?? null;

/** Primary button wording per progress step (the one next forward move). */
export const PRIMARY_LABEL = {
  en_route: "Start trip",
  on_site: "I have arrived",
  done: "Finish job",
};
export const SECONDARY_NOTE = {
  en_route: "Tap when you leave for the site.",
  on_site: "Tap when you are at the site.",
  done: "Add a short note about what you found and did.",
};

/** The next forward step of an item, or null when it is finished. */
export function nextStep(item) {
  const remote = String(item?.activity || "").startsWith("remote");
  const order = remote ? ["done"] : ["en_route", "on_site", "done"];
  const at = item?.progress ? order.indexOf(item.progress) : -1;
  return order[at + 1] || null;
}

/** Linked customer media (dispatcher-attached): returns { id, filename } or null. */
export function linkedMedia(item) {
  const m = item?.media || item?.customer_media || item?.customer_video || null;
  if (!m) return null;
  const id = first(m.media_id, m.id);
  return id ? { id, filename: first(m.filename, m.name) || "Customer video", size: m.size_bytes ?? null } : null;
}

/** One card's text, from an AgendaItem. */
export function agendaCard(item) {
  const remote = String(item?.activity || "").startsWith("remote");
  const site = shortSiteName(item?.site_alias || "");
  const contact = first(item?.customer_note, item?.contact_note, item?.customer_contact_note);
  const eta = item?.eta_arrival
    ? `Arrive about ${localTime(item.eta_arrival)}${item.travel_minutes != null ? ` · ${item.travel_minutes} min drive` : ""} (estimate)`
    : null;
  return {
    id: item.assignment_id,
    time: item?.window_label
      ? String(item.window_label).replace("-", "–")
      : item?.scheduled_start
        ? `${localTime(item.scheduled_start)}–${localTime(item.scheduled_end)}`
        : "Time not planned",
    day: item?.scheduled_start ? localDateTime(item.scheduled_start).split(",")[0] : "",
    remote,
    where: remote ? "Remote work: no travel" : site || "Site not named",
    whereDetail: remote
      ? "From the remote desk"
      : first(item?.zone, item?.site_alias && item.site_alias !== site ? item.site_alias : null) || "",
    eta: remote ? null : eta,
    what: activityText(item?.activity || item?.kind),
    why: first(item?.reason, item?.why) || caseTitle(item?.title || "", item?.site_alias),
    tier: item?.tier || null,
    contact,
    media: linkedMedia(item),
    progress: item?.progress ? progressText(item.progress) : null,
    next: nextStep(item),
  };
}

/** Items in time order; the first unfinished one is the "next" job. */
export function agendaList(agenda) {
  return [...(agenda?.items || [])].sort((a, b) =>
    String(a.scheduled_start || "~").localeCompare(String(b.scheduled_start || "~")),
  );
}

/** Completed jobs for the "Past jobs" list (newest first), whatever the backend calls them. */
export function pastJobs(agenda) {
  const list = agenda?.history ?? agenda?.past ?? agenda?.past_jobs ?? agenda?.completed ?? [];
  return [...list]
    .map((job) => ({
      id: first(job.assignment_id, job.id, job.incident_id),
      title: caseTitle(job.title || "", job.site_alias),
      zone: first(job.zone),
      site: shortSiteName(job.site_alias || ""),
      activity: activityText(job.activity || job.kind),
      finished: first(job.completed_at, job.finished_at, job.updated_at, job.scheduled_end),
      note: first(job.note, job.outcome_note, job.resolution_detail),
      outcome: first(job.outcome),
    }))
    .sort((a, b) => String(b.finished || "").localeCompare(String(a.finished || "")));
}
