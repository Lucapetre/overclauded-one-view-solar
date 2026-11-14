export const roles = {
  client: "Client",
  ceo: "Overall manager",
  manager: "Area manager",
  dispatcher: "PPC dispatcher",
  technician: "O&M technician",
  support: "Supplier support",
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
    sites: ["S01", "S02", "S03"],
    area: "North",
    crew: "Solar Care",
  },
  {
    id: "u9",
    name: "Mihai Petrescu",
    email: "mihai@solarlenes.demo",
    role: "technician",
    sites: ["S09", "S10"],
    area: "Central",
    crew: "Grid Response",
  },
  {
    id: "u10",
    name: "Ana Tudor",
    email: "ana@solarlenes.demo",
    role: "technician",
    sites: ["S17", "S18"],
    area: "South",
    crew: "Field Service",
  },
  {
    id: "u11",
    name: "Victor Ene",
    email: "support@solarlenes.demo",
    role: "support",
    sites: Array.from({ length: 8 }, (_, i) => `S${String(i + 1).padStart(2, "0")}`),
    area: "North",
  },
  {
    id: "u12",
    name: "Irina Matei",
    email: "support.central@solarlenes.demo",
    role: "support",
    sites: Array.from({ length: 8 }, (_, i) => `S${String(i + 9).padStart(2, "0")}`),
    area: "Central",
  },
  {
    id: "u13",
    name: "Paul Dumitru",
    email: "support.south@solarlenes.demo",
    role: "support",
    sites: Array.from({ length: 8 }, (_, i) => `S${String(i + 17).padStart(2, "0")}`),
    area: "South",
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
export const sites = Array.from({ length: 24 }, (_, i) => ({
  id: `S${String(i + 1).padStart(2, "0")}`,
  name:
    i === 0
      ? "The Green House"
      : i === 3
        ? "Bistro Soare"
        : `Solar home ${String(i + 1).padStart(2, "0")}`,
  business: i === 3,
  area: ["North", "Central", "South"][Math.floor(i / 8)],
  feeder: `DEMO-F${Math.floor(i / 8) + 1}`,
  capacity: 6 + (i % 3),
  battery: i % 4 === 1,
  stale: [5, 7, 14, 22].includes(i),
  pv: 3.6 + (i % 5) * 0.3,
}));
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
    owner: "Supplier support",
    routeTo: "Supplier Support",
  },
  {
    id: "billing",
    label: "Billing or contract question",
    family: "Billing",
    owner: "Supplier support",
    routeTo: "Supplier Support",
  },
  {
    id: "upgrade",
    label: "Extend the system (panels, battery, EV charger)",
    family: "Other",
    owner: "Supplier support",
    routeTo: "Supplier Support",
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
export const inverters = sites.map((site, i) => {
  const index = i % 8;
  const group = Math.floor(i / 8);
  const x = [110, 420, 195][group] + (index % 4) * 48;
  const y = [120, 140, 280][group] + Math.floor(index / 4) * 54;
  const manufacturer = ["Huawei", "Fronius", "SolarEdge"][i % 3];
  const model =
    manufacturer === "Huawei"
      ? `SUN2000-${site.capacity}KTL-M1`
      : manufacturer === "Fronius"
        ? `Primo ${site.capacity}.0-1`
        : `SE${site.capacity}K`;
  return {
    id: `INV-${site.id}`,
    site: site.id,
    manufacturer,
    model,
    serial: `DEMO-${site.id}-2024`,
    ratedKw: site.capacity,
    mapX: x / 720,
    mapY: y / 380,
  };
});
export const crews = [
  {
    name: "Solar Care",
    area: "North",
    owner: "Solar O&M",
    skills: ["Production", "Temperature", "Unknown code", "Local issue"],
    shift: "08:00–18:00",
    members: "Ioana Dima · 2 technicians",
  },
  {
    name: "Grid Response",
    area: "Central",
    owner: "Grid operator",
    skills: ["Voltage", "Area event"],
    shift: "08:00–18:00",
    members: "Mihai Petrescu · 3 technicians",
  },
  {
    name: "Field Service",
    area: "South",
    owner: "Customer electrician",
    skills: ["Local issue"],
    shift: "08:00–18:00",
    members: "Ana Tudor · 2 technicians",
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
    visits: [],
    plans: [],
    preferences: {},
    contracts: {},
    assignments: [],
    audit: [],
    users: users.map((x) => ({ ...x, active: true })),
  };
}
export function canSee(user, siteId) {
  if (!user) return siteId === "S01";
  const site = sites.find((x) => x.id === siteId);
  return (
    user.role === "ceo" ||
    (["manager", "dispatcher"].includes(user.role) &&
      site?.area === user.area) ||
    user.sites.includes(siteId)
  );
}
export const canDispatch = (u) =>
  ["ceo", "manager", "dispatcher"].includes(u?.role);
export const canReview = (u) =>
  ["ceo", "manager", "dispatcher", "technician"].includes(u?.role);
export function canReviewRequest(user, visit) {
  if (!user || !canSee(user, visit.site)) return false;
  if (user.role === "technician") return visit.routedTo === user.crew;
  if (user.role === "support") return visit.routedTo === "Supplier Support";
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
export function eligible(crew, incident, assignments) {
  return (
    crew.area === sites.find((s) => s.id === incident.site)?.area &&
    crew.owner === (incident.confirmedOwner || incident.owner) &&
    crew.skills.includes(incident.family) &&
    !assignments.some((a) => a.crew === crew.name && a.status === "Confirmed")
  );
}
export const timeLabel = (n) => {
  const mins = Math.round(n * 60);
  return `${String(Math.floor(mins / 60)).padStart(2, "0")}:${String(mins % 60).padStart(2, "0")}`;
};
