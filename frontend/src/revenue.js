// Estimated monthly supplier revenue from synthetic billing profiles × tariff.
// Not invoices: profiles and prices are fictional demo inputs.
//
// Per site per month:
//   energySales    = monthly_import_kwh × import price   (energy the customer buys)
//   exportPayments = monthly_export_kwh × export price   (paid to the customer for surplus)
//   serviceFees    = service_fee_ron
//   net            = energySales + serviceFees − exportPayments
//
// Prices: the site's saved contract when present, else the fixture's default tariff.

export const DEFAULT_TARIFF = {
  import_price_ron_kwh: 1.3,
  export_price_ron_kwh: 0.55,
};
const round2 = (n) => Math.round(n * 100) / 100;

/** Prices for one site, with their source ("contract" or "default"). */
export function pricesFor(contract, defaultTariff = DEFAULT_TARIFF) {
  const valid = (v) => Number.isFinite(v) && v >= 0;
  if (
    contract &&
    valid(contract.import_price_ron_kwh) &&
    valid(contract.export_price_ron_kwh)
  )
    return {
      importPrice: contract.import_price_ron_kwh,
      exportPrice: contract.export_price_ron_kwh,
      source: "contract",
    };
  return {
    importPrice: defaultTariff.import_price_ron_kwh,
    exportPrice: defaultTariff.export_price_ron_kwh,
    source: "default",
  };
}

/** profile: { monthly_import_kwh, monthly_export_kwh, service_fee_ron }; prices: { importPrice, exportPrice }. */
export function siteRevenue(profile, prices) {
  const importKwh = profile.monthly_import_kwh || 0,
    exportKwh = profile.monthly_export_kwh || 0;
  const energySales = importKwh * prices.importPrice,
    exportPayments = exportKwh * prices.exportPrice,
    serviceFees = profile.service_fee_ron || 0;
  return {
    importKwh,
    exportKwh,
    energySales: round2(energySales),
    exportPayments: round2(exportPayments),
    serviceFees: round2(serviceFees),
    net: round2(energySales + serviceFees - exportPayments),
  };
}

const empty = () => ({
  sites: 0,
  importKwh: 0,
  exportKwh: 0,
  energySales: 0,
  exportPayments: 0,
  serviceFees: 0,
  net: 0,
});
function add(total, row) {
  total.sites++;
  for (const key of [
    "importKwh",
    "exportKwh",
    "energySales",
    "exportPayments",
    "serviceFees",
    "net",
  ])
    total[key] = round2(total[key] + row[key]);
  return total;
}
const share = (part, whole) => (whole ? part / whole : 0);

/**
 * sites: [{ id, name, area, zone, segment, businessType, capacity, profile }]
 * contracts: { [siteId]: { import_price_ron_kwh, export_price_ron_kwh } }
 * scopeAreas: area names to include (e.g. ["Sector 6"]); null or omitted means all.
 */
export function revenueReport(
  sites,
  contracts = {},
  scopeAreas = null,
  defaultTariff = DEFAULT_TARIFF,
) {
  const rows = sites
    .filter((s) => s.profile && (!scopeAreas || scopeAreas.includes(s.area)))
    .map((s) => {
      const prices = pricesFor(contracts?.[s.id], defaultTariff);
      return {
        id: s.id,
        name: s.name,
        area: s.area,
        zone: s.zone,
        segment: s.segment,
        businessType: s.businessType || null,
        kwp: s.capacity,
        importPrice: prices.importPrice,
        exportPrice: prices.exportPrice,
        priceSource: prices.source,
        ...siteRevenue(s.profile, prices),
      };
    });
  const totals = rows.reduce(add, empty());
  const bySegment = {};
  for (const segment of ["business", "home"]) {
    const t = rows.filter((r) => r.segment === segment).reduce(add, empty());
    bySegment[segment] = { ...t, share: share(t.net, totals.net) };
  }
  const areas = [...new Set(rows.map((r) => r.area))];
  const byArea = areas.map((area) => {
    const list = rows.filter((r) => r.area === area);
    const t = list.reduce(add, empty());
    const business = list
      .filter((r) => r.segment === "business")
      .reduce(add, empty());
    return {
      area,
      ...t,
      share: share(t.net, totals.net),
      businessNet: business.net,
      homeNet: round2(t.net - business.net),
    };
  });
  const businessAccounts = rows
    .filter((r) => r.segment === "business")
    .sort((a, b) => b.net - a.net || a.id.localeCompare(b.id));
  return {
    totals,
    annualNet: round2(totals.net * 12),
    bySegment,
    byArea,
    businessAccounts,
    sites: rows,
    contractSites: rows.filter((r) => r.priceSource === "contract").length,
  };
}
