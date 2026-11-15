import siteProfiles from "../../backend/fixtures/site_profiles.json" with { type: "json" };
import { AREA_LABELS, AREA_NAMES } from "./geography.js";
export const roles = {
  client: "Client",
  ceo: "Overall manager",
  manager: "Area manager",
  dispatcher: "PPC dispatcher",
  technician: "O&M technician",
};
// Areas are the real Bucharest Sectors 1–6 and Ilfov County; every account, site,
// crew and incident below is fictional.
export const users = [
  {
    id: "u1",
    name: "Alex Morgan",
    email: "alex@solarlens.demo",
    role: "client",
    sites: ["s6-01"],
    area: "Sector 6",
  },
  {
    id: "u2",
    name: "Elena Popescu",
    email: "elena@solarlens.demo",
    role: "client",
    sites: ["s3-01"],
    area: "Sector 3",
  },
  {
    id: "u3",
    name: "David Ionescu",
    email: "david@solarlens.demo",
    role: "client",
    sites: ["s1-01"],
    area: "Sector 1",
  },
  {
    id: "u4",
    name: "Sofia Marin",
    email: "sofia@solarlens.demo",
    role: "client",
    sites: ["s4-01"],
    area: "Sector 4",
  },
  {
    id: "u5",
    name: "Andrei Radu",
    email: "ceo@solarlens.demo",
    role: "ceo",
    sites: [],
    area: "All",
  },
  {
    id: "u6",
    name: "Maria Stan",
    email: "manager@solarlens.demo",
    role: "manager",
    sites: [],
    area: "Sector 6",
  },
  {
    id: "u7",
    name: "Radu Pavel",
    email: "dispatch@solarlens.demo",
    role: "dispatcher",
    sites: [],
    area: "Sector 6",
  },
  {
    id: "u8",
    name: "Ioana Dima",
    email: "ioana@solarlens.demo",
    role: "technician",
    sites: [],
    area: "Sector 6",
    crew: "Sector 6 Solar Care",
  },
  {
    id: "u9",
    name: "Mihai Petrescu",
    email: "mihai@solarlens.demo",
    role: "technician",
    sites: [],
    area: "Sector 3",
    crew: "Sector 3 Grid Response",
  },
  {
    id: "u10",
    name: "Ana Tudor",
    email: "ana@solarlens.demo",
    role: "technician",
    sites: [],
    area: "Ilfov",
    crew: "Ilfov Field Service",
  },
  {
    id: "u14",
    name: "Carmen Voicu",
    email: "dispatch.s3@solarlens.demo",
    role: "dispatcher",
    sites: [],
    area: "Sector 3",
  },
  {
    id: "u15",
    name: "Dorin Ilie",
    email: "dispatch.ilfov@solarlens.demo",
    role: "dispatcher",
    sites: [],
    area: "Ilfov",
  },
  {
    id: "u16",
    name: "Ilinca Barbu",
    email: "bistro@solarlens.demo",
    role: "client",
    sites: ["s1-05"],
    area: "Sector 1",
    business: true,
  },
];
// Site placement, capacity, cluster and billing profiles come from the shared synthetic
// fixture; the demo uses the fixture's site ids (s1-01 … s6-14, ilfov-01 … ilfov-10).
/** Area labels in display order: Sector 1 … Sector 6, Ilfov. */
export const AREAS = AREA_NAMES;
export const siteFixture = siteProfiles;
export const defaultTariff = siteProfiles.default_tariff;
/** The site a visitor sees before logging in (Alex's Militari home). */
export const DEFAULT_SITE = "s6-01";
const nameOverrides = { "s6-01": "The Green House" };
// Synthetic replay: these feeds have no recent reading at 13:00.
const STALE = new Set(["s1-04", "s2-01", "s4-05", "s5-04", "s6-13", "ilfov-05"]);
export function profileFor(siteId) {
  return siteProfiles.profiles.find((p) => p.site_id === siteId) || null;
}
export const sites = siteProfiles.profiles.map((profile, i) => {
  const id = profile.site_id;
  const business = profile.segment === "business";
  return {
    id,
    name: nameOverrides[id] || profile.name,
    business,
    segment: profile.segment,
    businessType: profile.business_type || null,
    zone: profile.zone,
    latitude: profile.latitude,
    longitude: profile.longitude,
    area: AREA_LABELS[profile.area_id],
    areaId: profile.area_id,
    cluster: profile.cluster || null,
    feeder: `DEMO-F-${profile.cluster || id}`,
    capacity: profile.installed_kwp,
    battery: i % 4 === 1,
    stale: STALE.has(id),
    pv: 3.6 + (i % 5) * 0.3,
    profile,
  };
});
export const requestTypes = [
  {
    id: "solar",
    label: "Solar production looks low",
    family: "Production",
    owner: "Solar O&M",
    routeTo: "Area crew",
  },
  {
    id: "device-warning",
    label: "Inverter warning, error code or overheating",
    family: "Temperature",
    owner: "Solar O&M",
    routeTo: "Area crew",
  },
  {
    id: "inverter-offline",
    label: "Inverter is off or not starting",
    family: "Production",
    owner: "Solar O&M",
    routeTo: "Area crew",
  },
  {
    id: "battery",
    label: "Battery or storage issue",
    family: "Local issue",
    owner: "Solar O&M",
    routeTo: "Area crew",
  },
  {
    id: "panel-damage",
    label: "Panel damage, dirt or shading",
    family: "Production",
    owner: "Solar O&M",
    routeTo: "Area crew",
  },
  {
    id: "monitoring",
    label: "App data missing or not updating",
    family: "Telemetry",
    owner: "Unassigned review",
    routeTo: "PPC Triage",
  },
  {
    id: "grid",
    label: "Grid connection or voltage",
    family: "Voltage",
    owner: "Grid operator",
    routeTo: "Area crew",
  },
  {
    id: "outage",
    label: "Power cut or frequent disconnections",
    family: "Area event",
    owner: "Grid operator",
    routeTo: "Area crew",
  },
  {
    id: "electrical",
    label: "Electrical issue inside the building",
    family: "Local issue",
    owner: "Customer electrician",
    routeTo: "Area crew",
  },
  {
    id: "meter",
    label: "Meter reading or prosumer settlement",
    family: "Billing",
    owner: "PPC dispatch",
    routeTo: "PPC Triage",
  },
  {
    id: "billing",
    label: "Billing or contract question",
    family: "Billing",
    owner: "PPC dispatch",
    routeTo: "PPC Triage",
  },
  {
    id: "upgrade",
    label: "Extend the system (panels, battery, EV charger)",
    family: "Other",
    owner: "PPC dispatch",
    routeTo: "PPC Triage",
  },
  {
    id: "other",
    label: "Other or not sure",
    family: "Other",
    owner: "Unassigned review",
    routeTo: "PPC Triage",
  },
];
export function routeRequest(id) {
  return requestTypes.find((request) => request.id === id) || requestTypes.at(-1);
}
// Schematic 0–1 position inside a box around Bucharest and Ilfov (kept for the SQLite handoff).
export const DEMO_BOUNDS = {
  minLat: 44.2,
  maxLat: 44.8,
  minLon: 25.8,
  maxLon: 26.5,
};
export function inverterModel(manufacturer, kw) {
  if (manufacturer === "Huawei") return `SUN2000-${kw}KTL-M1`;
  if (manufacturer === "Fronius")
    return kw <= 8 ? `Primo ${kw}.0-1` : `Tauro ${kw}-3`;
  return `SE${kw}K`;
}
export const inverters = sites.map((site, i) => {
  const manufacturer = ["Huawei", "Fronius", "SolarEdge"][i % 3];
  const b = DEMO_BOUNDS;
  return {
    id: `INV-${site.id}`,
    site: site.id,
    manufacturer,
    model: inverterModel(manufacturer, site.capacity),
    serial: `DEMO-${site.id}-2024`,
    ratedKw: site.capacity,
    mapX: (site.longitude - b.minLon) / (b.maxLon - b.minLon),
    mapY: (b.maxLat - site.latitude) / (b.maxLat - b.minLat),
  };
});
// One crew per area covers that area's technical incident families.
// Billing questions are answered by the PPC dispatcher, never by a crew.
export const TECHNICAL_FAMILIES = [
  "Production",
  "Temperature",
  "Telemetry",
  "Voltage",
  "Area event",
  "Local issue",
  "Unknown code",
  "Other",
];
const crew = (id, name, area, lead, members, owner = "Solar O&M") => ({
  id,
  name,
  area,
  owner,
  skills: [...TECHNICAL_FAMILIES],
  shift: "08:00–18:00",
  lead,
  members,
});
export const crews = [
  crew("C1", "Sector 1 Rooftop Care", "Sector 1", null, [
    "Victor Enache",
    "Oana Mitrea",
    "Paul Sandu",
  ]),
  crew("C2", "Sector 2 Solar Service", "Sector 2", null, [
    "Gabriel Toma",
    "Irina Lupu",
    "Marius Neagoe",
  ]),
  crew(
    "C3",
    "Sector 3 Grid Response",
    "Sector 3",
    "u9",
    ["Mihai Petrescu", "Cristian Pop", "Raluca Stoica", "Emil Badea"],
    "Grid operator",
  ),
  crew("C4", "Sector 4 PV Care", "Sector 4", null, [
    "Lavinia Preda",
    "Sergiu Matei",
    "Adela Rusu",
  ]),
  crew("C5", "Sector 5 Solar Response", "Sector 5", null, [
    "Ovidiu Stan",
    "Teodora Ilie",
    "Rareș Dumitru",
  ]),
  crew("C6", "Sector 6 Solar Care", "Sector 6", "u8", [
    "Ioana Dima",
    "Tudor Lazăr",
    "Bianca Neagu",
  ]),
  crew("C7", "Ilfov Field Service", "Ilfov", "u10", [
    "Ana Tudor",
    "Sorin Vasile",
    "Diana Cazacu",
    "Florin Ghiță",
  ]),
];
// Incidents follow a synthetic demo policy (P0 safety first); no real equipment
// threshold, customer or event is represented.
const base = [
  [
    "I101",
    "s6-01",
    "Production below expected",
    "Production",
    "P2",
    "Solar O&M",
    "Observed 2.1 kW against a 4.2 kW synthetic baseline for 65 minutes. Clouds or shading remain possible.",
    "Fresh PV + synthetic baseline",
    4.4,
  ],
  [
    "I102",
    "s6-03",
    "Device temperature warning",
    "Temperature",
    "P1",
    "Solar O&M",
    "DEMO_TEMP_WARN is present. The synthetic device policy requires urgent technical review; this is not a real equipment threshold.",
    "Simulated device alarm",
    null,
  ],
  [
    "I103",
    "s6-13",
    "Telemetry connection interrupted",
    "Telemetry",
    "P3",
    "Unassigned review",
    "Last reading at 10:00; replay time 13:00. Production is unavailable, not zero.",
    "Missing telemetry",
    null,
  ],
  [
    "I104",
    "s3-06",
    "Voltage outside demo policy",
    "Voltage",
    "P1",
    "Grid operator",
    "DEMO_VOLT_WARN at 249 V. Owner remains unconfirmed pending technical review.",
    "Simulated voltage + device alarm",
    null,
  ],
  [
    "I105",
    "s3-07",
    "Related feeder voltage reports",
    "Area event",
    "P1",
    "Grid operator",
    "Old Town sites s3-06 and s3-07 share simulated feeder DEMO-F-old-town-hospitality and event timing. Parent event; child financial impact is not added twice.",
    "Known simulated topology",
    null,
  ],
  [
    "I106",
    "s4-01",
    "Customer reports a local issue",
    "Local issue",
    "P2",
    "Customer electrician",
    "Customer describes an intermittent display. A safe observation and qualified review are needed.",
    "Customer report",
    null,
  ],
  [
    "I107",
    "s5-01",
    "Weather-related output change",
    "Weather",
    "P3",
    "Unassigned review",
    "PV follows the broad cloudy-weather baseline. No equipment fault is established.",
    "Synthetic weather context",
    null,
  ],
  [
    "I108",
    "s6-02",
    "Unrecognised device code",
    "Unknown code",
    "P3",
    "Solar O&M",
    "Vendor code X-704 is not mapped. Preserve the code and request technical review; do not infer a component diagnosis.",
    "Unmapped code X-704",
    null,
  ],
  [
    "I109",
    "ilfov-04",
    "Simulated insulation fault alarm",
    "Local issue",
    "P0",
    "Solar O&M",
    "DEMO_ISO_ALARM from the synthetic replay. The demo safety policy ranks it P0: keep people away from the array and send a qualified crew. Not a real equipment threshold.",
    "Simulated device alarm",
    null,
  ],
  [
    "I110",
    "ilfov-06",
    "Production below expected",
    "Production",
    "P2",
    "Solar O&M",
    "Observed 96 kW against a 168 kW synthetic baseline for 50 minutes on the depot roof. Shading or soiling remain possible.",
    "Fresh PV + synthetic baseline",
    61.2,
  ],
  [
    "I111",
    "s1-05",
    "Inverter restarts during service hours",
    "Production",
    "P2",
    "Solar O&M",
    "Three synthetic restart events between 11:00 and 13:00. Output recovers each time; no fault is established.",
    "Simulated device events",
    7.8,
  ],
  [
    "I112",
    "s2-01",
    "Telemetry connection interrupted",
    "Telemetry",
    "P3",
    "Unassigned review",
    "Last reading at 09:30; replay time 13:00. Production is unavailable, not zero.",
    "Missing telemetry",
    null,
  ],
];
export function seed() {
  return {
    incidents: base.map((r, i) => ({
      id: r[0],
      site: r[1],
      title: r[2],
      family: r[3],
      tier: r[4],
      owner: r[5],
      evidence: r[6],
      strength: r[7],
      value: r[8],
      status: "New",
      confirmedOwner: "",
      revision: 1,
      age: 65 + i * 12,
      timeline: [
        {
          text: "Episode opened from synthetic replay · rule v1.0",
          actor: "Replay",
          time: "2026-11-14T11:00:00Z",
        },
      ],
    })),
    inverters: inverters.map((inverter) => ({ ...inverter })),
    // One source of truth for crews: every staff view reads db.crews.
    crews: crews.map((crew) => ({
      ...crew,
      skills: [...crew.skills],
      members: [...crew.members],
    })),
    visits: [],
    plans: [],
    preferences: {},
    contracts: {},
    // { id, kind: "dispatch"|"meeting", incident, site, area, crew, status, assignedBy, assignedAt, ... }
    assignments: [],
    users: users.map((x) => ({ ...x, active: true })),
  };
}
export function canSee(user, siteId) {
  if (!user) return siteId === DEFAULT_SITE;
  const site = sites.find((x) => x.id === siteId);
  return (
    user.role === "ceo" ||
    // Area staff see their area; a technician's area is the area of his crew.
    (["manager", "dispatcher", "technician"].includes(user.role) &&
      site?.area === user.area) ||
    user.sites.includes(siteId)
  );
}
// Only the PPC dispatcher assigns crews; managers read the assignment report.
export const canDispatch = (u) => u?.role === "dispatcher";
export const canConfirmOwner = (u) =>
  ["ceo", "manager", "dispatcher"].includes(u?.role);
export const canReview = (u) =>
  ["ceo", "manager", "dispatcher", "technician"].includes(u?.role);
export function canReviewRequest(user, visit) {
  if (!user || !canSee(user, visit.site)) return false;
  if (user.role === "technician") return visit.routedTo === user.crew;
  return ["ceo", "manager", "dispatcher"].includes(user.role);
}
export function rank(incidents) {
  return [...incidents].sort(
    (a, b) => a.tier.localeCompare(b.tier) || b.age - a.age,
  );
}
export const defaultPrices = { importPrice: 1.3, exportPrice: 0.55 };
// Prices come from the customer's saved contract when there is one.
export function recommend(
  task,
  plans = [],
  siteId = DEFAULT_SITE,
  prices = defaultPrices,
) {
  const margin = prices.importPrice - prices.exportPrice;
  const { energy, power, from, to, deadline, normal } = task;
  const duration = energy / power;
  if (
    ![energy, power, from, to, deadline, normal].every(Number.isFinite) ||
    energy <= 0 ||
    power <= 0 ||
    power > 7 ||
    duration > 24 ||
    from < 0 ||
    to > 24 ||
    from >= to ||
    deadline <= from ||
    normal + duration > 24
  )
    return [];
  const area = sites.find((s) => s.id === siteId)?.area;
  if (plans.some((p) => p.site === siteId && p.status === "Accepted"))
    return [];
  let slots = [];
  for (
    let start = from;
    start + duration <= Math.min(to, deadline);
    start += 0.5
  ) {
    let solar = 0,
      available = true;
    for (let t = start; t < start + duration - 0.001; t += 0.5) {
      let step = Math.min(0.5, start + duration - t);
      let pv = t >= 12 && t < 16 ? 3 : t >= 10 && t < 17 ? 1.5 : 0;
      solar += Math.min(power, pv) * step;
      let used = plans
        .filter(
          (p) =>
            p.status === "Accepted" &&
            sites.find((s) => s.id === p.site)?.area === area &&
            t < p.start + p.duration &&
            t + step > p.start,
        )
        .reduce((a, p) => a + p.power, 0);
      if (used + power > 6) available = false;
    }
    let baseSolar = 0;
    for (let t = normal; t < normal + duration - 0.001; t += 0.5) {
      baseSolar +=
        Math.min(power, t >= 12 && t < 16 ? 3 : t >= 10 && t < 17 ? 1.5 : 0) *
        Math.min(0.5, normal + duration - t);
    }
    const saving = (solar - baseSolar) * margin;
    if (available && saving > 0.05)
      slots.push({
        start,
        duration,
        power,
        energy,
        saving,
        low: Math.max(0, (solar * 0.5 - baseSolar) * margin),
        higher: Math.max(0, (solar * 0.7 - baseSolar) * margin),
        baseline: energy * prices.importPrice - baseSolar * margin,
        cost: energy * prices.importPrice - solar * margin,
      });
  }
  return slots.sort(
    (a, b) =>
      b.saving - a.saving || Math.abs(a.start - 13) - Math.abs(b.start - 13),
  );
}
export const ACTIVE_DISPATCH = ["Assigned", "Team sent"];
/** Crew area matches the site area, the family is in its skills and it has no active dispatch. */
export function eligible(crew, incident, assignments) {
  return (
    crew.area === sites.find((s) => s.id === incident.site)?.area &&
    incident.family !== "Billing" &&
    crew.skills.includes(incident.family) &&
    !assignments.some(
      (a) =>
        a.crew === crew.name &&
        (a.kind || "dispatch") === "dispatch" &&
        ACTIVE_DISPATCH.includes(a.status),
    )
  );
}
export const timeLabel = (n) => {
  const mins = Math.round(n * 60);
  return `${String(Math.floor(mins / 60)).padStart(2, "0")}:${String(mins % 60).padStart(2, "0")}`;
};
