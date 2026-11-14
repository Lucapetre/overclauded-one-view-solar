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
    sites: ["S01", "S02"],
    area: "North",
  },
];
export const sites = Array.from({ length: 24 }, (_, i) => ({
  id: `S${String(i + 1).padStart(2, "0")}`,
  name:
    i === 0
      ? "The Green House"
      : `Solar home ${String(i + 1).padStart(2, "0")}`,
  area: ["North", "Central", "South"][Math.floor(i / 8)],
  feeder: `DEMO-F${Math.floor(i / 8) + 1}`,
  capacity: 6 + (i % 3),
  battery: i % 4 === 1,
  stale: [5, 7, 14, 22].includes(i),
  pv: 3.6 + (i % 5) * 0.3,
}));
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
    visits: [],
    plans: [],
    preferences: {},
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
export function rank(incidents) {
  return [...incidents].sort(
    (a, b) => a.tier.localeCompare(b.tier) || b.age - a.age,
  );
}
export function recommend(task, plans = [], siteId = "S01") {
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
    const saving = (solar - baseSolar) * 0.75;
    if (available && saving > 0.05)
      slots.push({
        start,
        duration,
        power,
        energy,
        saving,
        low: Math.max(0, (solar * 0.5 - baseSolar) * 0.75),
        higher: Math.max(0, (solar * 0.7 - baseSolar) * 0.75),
        baseline: energy * 1.3 - baseSolar * 0.75,
        cost: energy * 1.3 - solar * 0.75,
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
