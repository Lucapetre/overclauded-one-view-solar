import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  AREA_IDS,
  AREA_NAMES,
  BOUNDARY_ATTRIBUTION,
  CLUSTERS,
  CLUSTER_KINDS,
  areaAt,
  areaIdOf,
  circleBounds,
  clusterCircle,
  clusterCountLabel,
  clusterOf,
  clusterSummary,
  distanceMeters,
  featureBounds,
  groupByCluster,
  scopeBoundaries,
} from "../src/geography.js";
import { AREAS, crews, seed, sites, users } from "../src/domain.js";
import { autoAssign, teamsReport, visibleIncidents } from "../src/dispatch.js";
import { consumptionShape } from "../src/dailyForecast.js";

const boundaries = JSON.parse(
  readFileSync(new URL("../../backend/fixtures/bucharest_areas.geojson", import.meta.url), "utf8"),
);
const byId = (id) => users.find((u) => u.id === id);

test("areas are Sector 1–6 and Ilfov, in display order", () => {
  assert.deepEqual(AREA_IDS, [
    "sector-1",
    "sector-2",
    "sector-3",
    "sector-4",
    "sector-5",
    "sector-6",
    "ilfov",
  ]);
  assert.deepEqual(AREAS, [...AREA_NAMES]);
  assert.deepEqual(AREAS, ["Sector 1", "Sector 2", "Sector 3", "Sector 4", "Sector 5", "Sector 6", "Ilfov"]);
  assert.equal(areaIdOf("Sector 6"), "sector-6");
  assert.equal(areaIdOf("ilfov"), "ilfov");
  assert.equal(areaIdOf("Somewhere"), null);
});

test("cluster labels name the group and count its sites in words", () => {
  const militari = CLUSTERS.find((c) => c.id === "militari-homes");
  const oldTown = CLUSTERS.find((c) => c.id === "old-town-hospitality");
  assert.equal(clusterSummary(militari, 8), "Militari · 8 homes");
  assert.equal(clusterSummary(oldTown, 6), "Old Town (Lipscani) · 6 restaurants & cafés");
  assert.equal(clusterCountLabel("residential", 1), "1 home");
  assert.equal(clusterCountLabel("logistics", 2), "2 depots & warehouses");
  assert.equal(clusterCountLabel("industrial", 3), "3 industrial sites");
  // Every fixture kind has a name, a plural and a colour; dashes differ per kind.
  for (const cluster of CLUSTERS) assert.ok(CLUSTER_KINDS[cluster.kind], cluster.kind);
  const dashes = Object.values(CLUSTER_KINDS).map((k) => k.dash);
  assert.equal(new Set(dashes).size, dashes.length);
});

test("sites group by cluster; standalone sites stay separate", () => {
  const { groups, standalone } = groupByCluster(sites);
  const militari = groups.find((g) => g.cluster.id === "militari-homes");
  assert.equal(militari.sites.length, 8);
  assert.equal(militari.label, "Militari · 8 homes");
  assert.equal(groups.find((g) => g.cluster.id === "old-town-hospitality").label,
    "Old Town (Lipscani) · 4 restaurants & cafés");
  assert.equal(groups.length, 15);
  assert.deepEqual(
    standalone.map((s) => s.id).sort(),
    sites.filter((s) => !s.cluster).map((s) => s.id).sort(),
  );
  assert.equal(groups.reduce((n, g) => n + g.sites.length, 0) + standalone.length, sites.length);
  // Only clusters with a visible site are returned; unknown cluster ids are standalone.
  const some = groupByCluster([
    { ...sites[0] },
    { id: "x", cluster: "no-such-cluster", latitude: 44.4, longitude: 26.1 },
  ]);
  assert.equal(some.groups.length, 1);
  assert.deepEqual(some.standalone.map((s) => s.id), ["x"]);
  assert.equal(clusterOf("s6-04"), "militari-homes");
  assert.equal(clusterOf("s1-04"), null);
  assert.equal(clusterOf("unknown"), null);
});

test("cluster highlight: centroid circle covering every member, at least 250 m", () => {
  const militari = sites.filter((s) => s.cluster === "militari-homes");
  const circle = clusterCircle(militari);
  for (const site of militari) assert.ok(distanceMeters(circle, site) < circle.radius, site.id);
  assert.ok(circle.radius < 1500, "a neighbourhood, not the whole sector");
  const meanLat = militari.reduce((s, x) => s + x.latitude, 0) / militari.length;
  assert.ok(Math.abs(circle.latitude - meanLat) < 1e-9);
  // A single site (or two very close ones) still gets a visible minimum radius.
  assert.equal(clusterCircle([{ latitude: 44.43, longitude: 26.1 }]).radius, 250);
  assert.equal(clusterCircle([{ latitude: 44.43, longitude: 26.1 }], { minRadius: 400 }).radius, 400);
  assert.equal(clusterCircle([]), null);
  assert.equal(clusterCircle([{ latitude: NaN, longitude: 1 }]), null);
  const [[s, w], [n, e]] = circleBounds({ latitude: 44.43, longitude: 26.1, radius: 1000 });
  assert.ok(Math.abs(distanceMeters({ latitude: s, longitude: 26.1 }, { latitude: n, longitude: 26.1 }) - 2000) < 5);
  assert.ok(Math.abs(distanceMeters({ latitude: 44.43, longitude: w }, { latitude: 44.43, longitude: e }) - 2000) < 10);
});

test("every demo site and area label lies inside its own real boundary", () => {
  assert.deepEqual(
    boundaries.features.map((f) => f.properties.area_id).sort(),
    [...AREA_IDS].sort(),
  );
  assert.match(boundaries.attribution, /OpenStreetMap/);
  assert.match(BOUNDARY_ATTRIBUTION, /OpenStreetMap/);
  assert.match(BOUNDARY_ATTRIBUTION, /ODbL/);
  for (const site of sites) {
    assert.equal(areaAt(boundaries, site.latitude, site.longitude), site.areaId, site.id);
    assert.ok(AREAS.includes(site.area), site.id);
  }
  // Ilfov has Bucharest as a hole: the city centre is in a sector, not in Ilfov.
  assert.notEqual(areaAt(boundaries, 44.4268, 26.1025), "ilfov");
  assert.equal(areaAt(boundaries, 44.58, 26.2), "ilfov");
  assert.equal(areaAt(boundaries, 45.5, 27), null);
});

test("boundary scope: own areas strong, others faded; unknown ids fade nothing", () => {
  const all = scopeBoundaries(boundaries, null);
  assert.equal(all.length, 7);
  assert.ok(all.every((b) => b.inScope));
  const s6 = scopeBoundaries(boundaries, ["sector-6"]);
  assert.deepEqual(s6.filter((b) => b.inScope).map((b) => b.id), ["sector-6"]);
  // Labels are accepted too (the demo stores "Sector 6").
  assert.deepEqual(
    scopeBoundaries(boundaries, ["Sector 3", "Ilfov"]).filter((b) => b.inScope).map((b) => b.id).sort(),
    ["ilfov", "sector-3"],
  );
  assert.ok(scopeBoundaries(boundaries, ["unknown-area"]).every((b) => b.inScope));
  assert.deepEqual(scopeBoundaries(null, ["sector-6"]), []);
  // The Sector 6 outline contains every Sector 6 site, so fitting to it shows them all.
  const [[minLat, minLon], [maxLat, maxLon]] = featureBounds(
    s6.filter((b) => b.inScope).map((b) => b.feature),
  );
  for (const site of sites.filter((x) => x.area === "Sector 6"))
    assert.ok(
      site.latitude > minLat && site.latitude < maxLat && site.longitude > minLon && site.longitude < maxLon,
      site.id,
    );
});

test("seven crews, exactly one per area, all covering the technical families", () => {
  assert.equal(crews.length, 7);
  assert.deepEqual(crews.map((c) => c.area), AREAS);
  assert.equal(new Set(crews.map((c) => c.name)).size, 7);
  for (const crew of crews) assert.ok(crew.name.startsWith(crew.area), crew.name);
  // Crew leads with a login: Sector 6 (Ioana), Sector 3 (Mihai) and Ilfov (Ana).
  const leads = users.filter((u) => u.role === "technician");
  assert.deepEqual(
    leads.map((u) => [u.name, u.area, u.crew]),
    [
      ["Ioana Dima", "Sector 6", "Sector 6 Solar Care"],
      ["Mihai Petrescu", "Sector 3", "Sector 3 Grid Response"],
      ["Ana Tudor", "Ilfov", "Ilfov Field Service"],
    ],
  );
  for (const u of leads) assert.equal(crews.find((c) => c.name === u.crew).area, u.area);
  const db = seed();
  assert.equal(teamsReport(db, byId("u5")).crews.length, 7);
  assert.deepEqual(teamsReport(db, byId("u6")).crews.map((c) => c.name), ["Sector 6 Solar Care"]);
});

test("demo accounts are scoped to sectors and Ilfov", () => {
  const areaOf = (id) => sites.find((s) => s.id === id).area;
  assert.equal(areaOf(byId("u1").sites[0]), "Sector 6");
  assert.equal(sites.find((s) => s.id === byId("u1").sites[0]).cluster, "militari-homes");
  for (const u of users.filter((x) => x.role === "client"))
    assert.equal(areaOf(u.sites[0]), u.area, u.email);
  assert.equal(byId("u16").email, "bistro@solarlens.demo");
  assert.equal(sites.find((s) => s.id === "s1-05").cluster, "dorobanti-floreasca-hospitality");
  assert.deepEqual(
    users.filter((u) => u.role === "dispatcher").map((u) => [u.email, u.area]),
    [
      ["dispatch@solarlens.demo", "Sector 6"],
      ["dispatch.s3@solarlens.demo", "Sector 3"],
      ["dispatch.ilfov@solarlens.demo", "Ilfov"],
    ],
  );
  for (const u of users)
    assert.ok(u.area === "All" || AREAS.includes(u.area), `${u.email} ${u.area}`);
});

test("incidents are spread over the new areas and P0 leads in Ilfov", () => {
  const db = seed();
  assert.ok(db.incidents.length >= 10 && db.incidents.length <= 12);
  const areas = new Set(db.incidents.map((i) => sites.find((s) => s.id === i.site).area));
  assert.deepEqual([...areas].sort(), [...AREAS].sort());
  assert.ok(db.incidents.some((i) => i.tier === "P0"));
  const ana = byId("u10");
  const ilfov = visibleIncidents(db, ana);
  assert.deepEqual(ilfov.map((i) => i.id), ["I109", "I110"]);
  assert.equal(ilfov[0].tier, "P0");
  // The Ilfov dispatcher's severity run gives the P0 to the Ilfov crew first.
  const { assigned, skipped } = autoAssign(db, byId("u15"), "2026-11-14T11:30:00Z");
  assert.deepEqual(assigned.map((a) => [a.incident, a.crew, a.area]), [["I109", "Ilfov Field Service", "Ilfov"]]);
  assert.match(skipped.find((s) => s.incident === "I110").reason, /Ilfov Field Service is on I109/);
});

test("no North/Central/South left in the demo data", () => {
  const db = seed();
  const text = JSON.stringify({ db, sites, crews, users, CLUSTERS });
  assert.doesNotMatch(text, /\b(north|central|south)\b/i);
});

test("business sites of every kind get a sensible consumption shape", () => {
  const hospitality = consumptionShape("business", "Restaurant");
  const industrial = consumptionShape("business", "Factory");
  const office = consumptionShape("business", "Office park");
  for (const type of ["Café", "Bar", "Hotel", "Bistro"])
    assert.deepEqual(consumptionShape("business", type), hospitality, type);
  for (const type of ["Warehouse", "Cold storage", "Logistics hub", "Data centre", "Supermarket"])
    assert.deepEqual(consumptionShape("business", type), industrial, type);
  assert.notDeepEqual(office, industrial);
  assert.deepEqual(consumptionShape("business", "Research campus"), office);
  for (const site of sites.filter((s) => s.business))
    assert.equal(consumptionShape(site.segment, site.businessType).length, 24, site.id);
});

test("the SQLite handoff fixtures match the demo seed", () => {
  const fixtures = JSON.parse(
    readFileSync(new URL("../database/fixtures.json", import.meta.url), "utf8"),
  );
  assert.deepEqual(fixtures.sites.map((s) => s.id), sites.map((s) => s.id));
  assert.deepEqual(fixtures.sites.map((s) => s.area), sites.map((s) => s.area));
  assert.deepEqual(fixtures.crews.map((c) => c.name), crews.map((c) => c.name));
  assert.deepEqual(fixtures.users.map((u) => [u.email, u.area]), users.map((u) => [u.email, u.area]));
  assert.deepEqual(fixtures.incidents.map((i) => i.site), seed().incidents.map((i) => i.site));
});
