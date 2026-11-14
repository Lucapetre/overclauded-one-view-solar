import siteProfiles from "../../backend/fixtures/site_profiles.json" with { type: "json" };
export const roles = {
  client: "Client",
  ceo: "Overall manager",
  manager: "Area manager",
  dispatcher: "PPC dispatcher",
  technician: "O&M technician",
};
export const users = [
  {
    id: "u1",
    name: "Alex Morgan",
    email: "alex@solarlenes.demo",
    role: "client",
    sites: ["S01"],
    area: "North",
  },
  {
    id: "u2",
    name: "Elena Popescu",
    email: "elena@solarlenes.demo",
    role: "client",
    sites: ["S02"],
    area: "North",
  },
  {
    id: "u3",
    name: "David Ionescu",
    email: "david@solarlenes.demo",
    role: "client",
    sites: ["S09"],
    area: "Central",
  },
  {
    id: "u4",
    name: "Sofia Marin",
    email: "sofia@solarlenes.demo",
    role: "client",
    sites: ["S17"],
    area: "South",
  },
  {
    id: "u5",
    name: "Andrei Radu",
    email: "ceo@solarlenes.demo",
    role: "ceo",
    sites: [],
    area: "All",
  },
  {
    id: "u6",
    name: "Maria Stan",
    email: "manager@solarlenes.demo",
    role: "manager",
    sites: [],
    area: "North",
  },
  {
    id: "u7",
    name: "Radu Pavel",
    email: "dispatch@solarlenes.demo",
    role: "dispatcher",
    sites: [],
    area: "North",
  },
  {
    id: "u8",
    name: "Ioana Dima",
    email: "ioana@solarlenes.demo",
    role: "technician",
    sites: [],
    area: "North",
    crew: "Solar Care",
  },
  {
    id: "u9",
    name: "Mihai Petrescu",
    email: "mihai@solarlenes.demo",
    role: "technician",
    sites: [],
    area: "Central",
    crew: "Grid Response",
  },
  {
    id: "u10",
    name: "Ana Tudor",
    email: "ana@solarlenes.demo",
    role: "technician",
    sites: [],
    area: "South",
    crew: "Field Service",
  },
  {
    id: "u14",
    name: "Carmen Voicu",
    email: "dispatch.central@solarlenes.demo",
    role: "dispatcher",
    sites: [],
    area: "Central",
  },
  {
    id: "u15",
    name: "Dorin Ilie",
    email: "dispatch.south@solarlenes.demo",
    role: "dispatcher",
    sites: [],
    area: "South",
  },
  {
    id: "u16",
    name: "Ilinca Barbu",
    email: "bistro@solarlenes.demo",
    role: "client",
    sites: ["S04"],
    area: "North",
    business: true,
  },
];
// Site placement, capacity and billing profiles come from the shared synthetic fixture.
// Profile area north/central/south + number 1–8 maps to demo sites S01–S08 / S09–S16 / S17–S24.
export const AREAS = ["North", "Central", "South"];
export const siteFixture = siteProfiles;
export const defaultTariff = siteProfiles.default_tariff;
const businessNames = {
  S04: "Bistro Soare",
  S06: "Pipera Office Park",
  S08: "Bucureștii Noi Warehouse",
  S11: "Old Town Bistro",
  S15: "Militari Factory",
  S21: "Berceni Factory",
  S24: "Progresul Supermarket",
};
export function profileFor(siteId) {
  const index = Number(siteId.slice(1)) - 1;
  const area = AREAS[Math.floor(index / 8)]?.toLowerCase();
  return siteProfiles.profiles.find(
    (p) => p.area === area && p.number === (index % 8) + 1,
  );
}
export const sites = Array.from({ length: 24 }, (_, i) => {
  const id = `S${String(i + 1).padStart(2, "0")}`;
  const profile = profileFor(id);
  const business = profile.segment === "business";
  return {
    id,
    name:
      i === 0
        ? "The Green House"
        : business
          ? businessNames[id] || `${profile.zone} ${profile.business_type}`
          : `Solar home ${String(i + 1).padStart(2, "0")}`,
    business,
    segment: profile.segment,
    businessType: profile.business_type || null,
    zone: profile.zone,
    latitude: profile.latitude,
    longitude: profile.longitude,
    area: AREAS[Math.floor(i / 8)],
    feeder: `DEMO-F${Math.floor(i / 8) + 1}`,
    capacity: profile.installed_kwp,
    battery: i % 4 === 1,
    stale: [5, 7, 14, 22].includes(i),
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
    routeTo: "Solar Care",
  },
  {
    id: "device-warning",
    label: "Inverter warning, error code or overheating",
    family: "Temperature",
    owner: "Solar O&M",
    routeTo: "Solar Care",
  },
  {
    id: "inverter-offline",
    label: "Inverter is off or not starting",
    family: "Production",
    owner: "Solar O&M",
    routeTo: "Solar Care",
  },
  {
    id: "battery",
    label: "Battery or storage issue",
    family: "Local issue",
    owner: "Solar O&M",
    routeTo: "Solar Care",
  },
  {
    id: "panel-damage",
    label: "Panel damage, dirt or shading",
    family: "Production",
    owner: "Solar O&M",
    routeTo: "Solar Care",
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
    routeTo: "Grid Response",
  },
  {
    id: "outage",
    label: "Power cut or frequent disconnections",
    family: "Area event",
    owner: "Grid operator",
    routeTo: "Grid Response",
  },
  {
    id: "electrical",
    label: "Electrical issue inside the building",
    family: "Local issue",
    owner: "Customer electrician",
    routeTo: "Field Service",
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
// Schematic 0–1 position inside a Bucharest bounding box (kept for the SQLite handoff).
export const BUCHAREST_BOUNDS = {
  south: 44.33,
  north: 44.54,
  west: 25.94,
  east: 26.25,
};
export function inverterModel(manufacturer, kw) {
  if (manufacturer === "Huawei") return `SUN2000-${kw}KTL-M1`;
  if (manufacturer === "Fronius")
    return kw <= 8 ? `Primo ${kw}.0-1` : `Tauro ${kw}-3`;
  return `SE${kw}K`;
}
export const inverters = sites.map((site, i) => {
  const manufacturer = ["Huawei", "Fronius", "SolarEdge"][i % 3];
  const b = BUCHAREST_BOUNDS;
  return {
    id: `INV-${site.id}`,
    site: site.id,
    manufacturer,
    model: inverterModel(manufacturer, site.capacity),
    serial: `DEMO-${site.id}-2024`,
    ratedKw: site.capacity,
    mapX: (site.longitude - b.west) / (b.east - b.west),
    mapY: (b.north - site.latitude) / (b.north - b.south),
  };
});
// Each area has one crew that covers that area's technical incident families.
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
export const crews = [
  {
    id: "C1",
    name: "Solar Care",
    area: "North",
    owner: "Solar O&M",
    skills: [...TECHNICAL_FAMILIES],
    shift: "08:00–18:00",
    lead: "u8",
    members: ["Ioana Dima", "Tudor Lazăr", "Bianca Neagu"],
  },
  {
    id: "C2",
    name: "Grid Response",
    area: "Central",
    owner: "Grid operator",
    skills: [...TECHNICAL_FAMILIES],
    shift: "08:00–18:00",
    lead: "u9",
    members: ["Mihai Petrescu", "Cristian Pop", "Raluca Stoica", "Emil Badea"],
  },
  {
    id: "C3",
    name: "Field Service",
    area: "South",
    owner: "Customer electrician",
    skills: [...TECHNICAL_FAMILIES],
    shift: "08:00–18:00",
    lead: "u10",
    members: ["Ana Tudor", "Sorin Vasile", "Diana Cazacu"],
  },
];
const base = [
  [
    "I101",
    "S01",
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
    "S02",
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
    "S06",
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
    "S09",
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
    "S10",
    "Related feeder voltage reports",
    "Area event",
    "P1",
    "Grid operator",
    "Sites S09 and S10 share simulated feeder DEMO-F2 and event timing. Parent event; child financial impact is not added twice.",
    "Known simulated topology",
    null,
  ],
  [
    "I106",
    "S17",
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
    "S18",
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
    "S03",
    "Unrecognised device code",
    "Unknown code",
    "P3",
    "Solar O&M",
    "Vendor code X-704 is not mapped. Preserve the code and request technical review; do not infer a component diagnosis.",
    "Unmapped code X-704",
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
  if (!user) return siteId === "S01";
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
  siteId = "S01",
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
