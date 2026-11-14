import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { sites, defaultTariff, inverters, BUCHAREST_BOUNDS, profileFor } from "../src/domain.js";
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
    { S04: { import_price_ron_kwh: 1, export_price_ron_kwh: 0.5 } },
    null,
    defaultTariff,
  );
  const bistro = withContract.businessAccounts.find((b) => b.id === "S04");
  assert.equal(bistro.priceSource, "contract");
  assert.equal(bistro.net, 3200 * 1 + 180 - 260 * 0.5);
  assert.equal(withContract.contractSites, 1);
  assert.equal(base.businessAccounts.find((b) => b.id === "S04").priceSource, "default");
});

test("revenue report totals, segments, areas and ranked business accounts", () => {
  const report = revenueReport(sites, {}, null, defaultTariff);
  let net = 0;
  for (const p of fixture.profiles)
    net += p.monthly_import_kwh * 1.3 + p.service_fee_ron - p.monthly_export_kwh * 0.55;
  assert.ok(Math.abs(report.totals.net - net) < 0.01);
  assert.equal(report.totals.sites, 24);
  assert.ok(Math.abs(report.annualNet - report.totals.net * 12) < 0.01);
  const { business, home } = report.bySegment;
  assert.equal(business.sites, 7);
  assert.equal(home.sites, 17);
  assert.ok(Math.abs(business.share + home.share - 1) < 1e-9);
  assert.ok(business.share > 0.9, "business accounts dominate synthetic revenue");
  assert.equal(report.byArea.length, 3);
  assert.ok(
    Math.abs(report.byArea.reduce((s, a) => s + a.net, 0) - report.totals.net) < 0.05,
  );
  const nets = report.businessAccounts.map((b) => b.net);
  assert.deepEqual(nets, [...nets].sort((a, b) => b - a));
  assert.equal(report.businessAccounts[0].name, "Militari Factory");
});

test("area scope keeps only that area", () => {
  const north = revenueReport(sites, {}, ["North"], defaultTariff);
  assert.equal(north.totals.sites, 8);
  assert.deepEqual(north.byArea.map((a) => a.area), ["North"]);
  assert.deepEqual(
    north.businessAccounts.map((b) => b.id).sort(),
    ["S04", "S06", "S08"],
  );
  const all = revenueReport(sites, {}, null, defaultTariff);
  assert.equal(north.totals.net, all.byArea.find((a) => a.area === "North").net);
});

test("demo sites map to the shared fixture inside Bucharest", () => {
  assert.equal(sites.length, 24);
  assert.equal(sites.filter((s) => s.business).length, 7);
  const area = { north: "North", central: "Central", south: "South" };
  for (const p of fixture.profiles) {
    const id = `S${String(["north", "central", "south"].indexOf(p.area) * 8 + p.number).padStart(2, "0")}`;
    const site = sites.find((s) => s.id === id);
    assert.equal(profileFor(id), site.profile);
    assert.equal(site.area, area[p.area]);
    assert.equal(site.latitude, p.latitude);
    assert.equal(site.longitude, p.longitude);
    assert.equal(site.zone, p.zone);
    assert.equal(site.segment, p.segment);
    assert.equal(site.capacity, p.installed_kwp);
    assert.equal(site.business, p.segment === "business");
    assert.equal(site.businessType, p.business_type || null);
  }
  for (const s of sites) {
    assert.ok(s.latitude > 44.33 && s.latitude < 44.54, s.id);
    assert.ok(s.longitude > 25.94 && s.longitude < 26.25, s.id);
    if (!s.business && s.id !== "S01") assert.match(s.name, /^Solar home \d\d$/);
  }
  assert.equal(sites[0].name, "The Green House");
  assert.equal(sites[3].name, "Bistro Soare");
  assert.ok(sites.find((s) => s.id === "S15").name.includes("Militari"));
  // Inverter ratings and model strings follow the site's capacity.
  for (const inv of inverters) {
    const site = sites.find((s) => s.id === inv.site);
    assert.equal(inv.ratedKw, site.capacity);
    assert.ok(inv.model.includes(String(site.capacity)), inv.model);
  }
  assert.ok(BUCHAREST_BOUNDS.south < BUCHAREST_BOUNDS.north);
});
