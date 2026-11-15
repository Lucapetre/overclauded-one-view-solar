import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { AREAS, sites, defaultTariff, inverters, DEMO_BOUNDS, profileFor } from "../src/domain.js";
import { DEFAULT_TARIFF, pricesFor, revenueReport, siteRevenue } from "../src/revenue.js";

const fixture = JSON.parse(
  readFileSync(new URL("../../backend/fixtures/site_profiles.json", import.meta.url), "utf8"),
);

test("site revenue is sales plus fees minus export payments", () => {
  const r = siteRevenue(
    { monthly_import_kwh: 3200, monthly_export_kwh: 260, service_fee_ron: 180 },
    { importPrice: 1.3, exportPrice: 0.55 },
  );
  assert.equal(r.energySales, 4160);
  assert.equal(r.exportPayments, 143);
  assert.equal(r.serviceFees, 180);
  assert.equal(r.net, 4197);
});

test("contract prices replace the fixture tariff only when present", () => {
  assert.deepEqual(DEFAULT_TARIFF, fixture.default_tariff);
  assert.deepEqual(defaultTariff, fixture.default_tariff);
  assert.equal(pricesFor(null).source, "default");
  assert.equal(pricesFor({ import_price_ron_kwh: 1, export_price_ron_kwh: 0.4 }).source, "contract");
  assert.equal(pricesFor({ import_price_ron_kwh: Number.NaN, export_price_ron_kwh: 0.4 }).source, "default");
  const base = revenueReport(sites, {}, null, defaultTariff);
  const withContract = revenueReport(
    sites,
    { "s1-05": { import_price_ron_kwh: 1, export_price_ron_kwh: 0.5 } },
    null,
    defaultTariff,
  );
  const bistro = withContract.businessAccounts.find((b) => b.id === "s1-05");
  assert.equal(bistro.priceSource, "contract");
  assert.equal(bistro.net, 3200 * 1 + 180 - 260 * 0.5);
  assert.equal(withContract.contractSites, 1);
  assert.equal(base.businessAccounts.find((b) => b.id === "s1-05").priceSource, "default");
});

test("revenue report totals, segments, areas and ranked business accounts", () => {
  const report = revenueReport(sites, {}, null, defaultTariff);
  let net = 0;
  for (const p of fixture.profiles)
    net += p.monthly_import_kwh * 1.3 + p.service_fee_ron - p.monthly_export_kwh * 0.55;
  assert.ok(Math.abs(report.totals.net - net) < 0.01);
  assert.equal(report.totals.sites, 60);
  assert.ok(Math.abs(report.annualNet - report.totals.net * 12) < 0.01);
  const { business, home } = report.bySegment;
  assert.equal(business.sites, 25);
  assert.equal(home.sites, 35);
  assert.ok(Math.abs(business.share + home.share - 1) < 1e-9);
  assert.ok(business.share > 0.9, "business accounts dominate synthetic revenue");
  assert.deepEqual(report.byArea.map((a) => a.area), AREAS);
  assert.ok(
    Math.abs(report.byArea.reduce((s, a) => s + a.net, 0) - report.totals.net) < 0.05,
  );
  const nets = report.businessAccounts.map((b) => b.net);
  assert.deepEqual(nets, [...nets].sort((a, b) => b - a));
  assert.equal(report.businessAccounts[0].name, "Popești-Leordeni Factory");
});

test("area scope keeps only that sector", () => {
  const s6 = revenueReport(sites, {}, ["Sector 6"], defaultTariff);
  assert.equal(s6.totals.sites, 14);
  assert.deepEqual(s6.byArea.map((a) => a.area), ["Sector 6"]);
  assert.deepEqual(
    s6.businessAccounts.map((b) => b.id).sort(),
    ["s6-13", "s6-14"],
  );
  const all = revenueReport(sites, {}, null, defaultTariff);
  assert.equal(s6.totals.net, all.byArea.find((a) => a.area === "Sector 6").net);
  const ilfov = revenueReport(sites, {}, ["Ilfov"], defaultTariff);
  assert.equal(ilfov.totals.sites, 10);
  assert.equal(ilfov.bySegment.home.sites, 0);
});

test("demo sites are the shared fixture's profiles, ids and names", () => {
  assert.equal(sites.length, 60);
  assert.equal(sites.filter((s) => s.business).length, 25);
  for (const p of fixture.profiles) {
    const site = sites.find((s) => s.id === p.site_id);
    assert.ok(site, p.site_id);
    assert.equal(profileFor(p.site_id), site.profile);
    assert.equal(site.area, fixture.areas[p.area_id].label);
    assert.equal(site.areaId, p.area_id);
    assert.equal(site.cluster, p.cluster || null);
    assert.equal(site.latitude, p.latitude);
    assert.equal(site.longitude, p.longitude);
    assert.equal(site.zone, p.zone);
    assert.equal(site.segment, p.segment);
    assert.equal(site.capacity, p.installed_kwp);
    assert.equal(site.business, p.segment === "business");
    assert.equal(site.businessType, p.business_type || null);
    if (p.site_id !== "s6-01") assert.equal(site.name, p.name);
  }
  for (const s of sites) {
    assert.ok(s.latitude > DEMO_BOUNDS.minLat && s.latitude < DEMO_BOUNDS.maxLat, s.id);
    assert.ok(s.longitude > DEMO_BOUNDS.minLon && s.longitude < DEMO_BOUNDS.maxLon, s.id);
  }
  // Alex's Militari home keeps its story name.
  const green = sites.find((s) => s.id === "s6-01");
  assert.equal(green.name, "The Green House");
  assert.equal(green.cluster, "militari-homes");
  assert.equal(sites.find((s) => s.id === "s1-05").name, "Bistro Soare");
  // Inverter ratings and model strings follow the site's capacity.
  for (const inv of inverters) {
    const site = sites.find((s) => s.id === inv.site);
    assert.equal(inv.ratedKw, site.capacity);
    assert.ok(inv.model.includes(String(site.capacity)), inv.model);
    assert.ok(inv.mapX > 0 && inv.mapX < 1 && inv.mapY > 0 && inv.mapY < 1, inv.id);
  }
});
