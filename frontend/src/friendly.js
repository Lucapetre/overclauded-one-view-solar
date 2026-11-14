// Plain-language equivalents for energy amounts. Appliance ratings are rounded,
// typical values used for illustration only; real appliances differ.
const hours = (kw) => (kwh) => kwh / kw;
const unit = (n, word) => `${n} ${word}${n === "1" ? "" : "s"}`;
export const equivalents = {
  home: [
    {
      id: "tv",
      amount: hours(0.1),
      text: (n) => `run a big-screen TV for ${unit(n, "hour")}`,
      basis: "a big-screen TV at about 100 W",
    },
    {
      id: "laundry",
      amount: (kwh) => kwh / 1,
      text: (n) => `wash ${unit(n, "load")} of laundry`,
      basis: "about 1 kWh per wash",
    },
    {
      id: "ev",
      amount: (kwh) => kwh / 0.18,
      text: (n) => `drive an electric car about ${n} km`,
      basis: "about 18 kWh per 100 km",
    },
  ],
  business: [
    {
      id: "fridge",
      amount: hours(0.5),
      text: (n) => `keep a commercial display fridge cold for ${unit(n, "hour")}`,
      basis: "a display fridge averaging about 500 W",
    },
    {
      id: "oven",
      amount: hours(3),
      text: (n) => `run a professional oven for ${unit(n, "hour")}`,
      basis: "a convection oven at about 3 kW",
    },
    {
      id: "dishwasher",
      amount: (kwh) => kwh / 0.4,
      text: (n) => `run ${unit(n, "cycle")} of a commercial dishwasher`,
      basis: "about 0.4 kWh per cycle",
    },
  ],
};

const round = (value) =>
  new Intl.NumberFormat("en-GB", {
    maximumFractionDigits: value < 10 ? 1 : 0,
  }).format(value);

/** Returns null when the energy is unknown: missing data is never described as zero. */
export function friendlyEnergy(kwh, accountType = "home") {
  if (kwh == null || !Number.isFinite(kwh) || kwh < 0) return null;
  const list = equivalents[accountType] || equivalents.home;
  const phrases = list.map((item) => ({
    id: item.id,
    text: item.text(round(item.amount(kwh))),
    basis: item.basis,
  }));
  return { kwh, headline: phrases[0], others: phrases.slice(1) };
}

export const words = (accountType) =>
  accountType === "business"
    ? {
        place: "business",
        Place: "Your business",
        consumption: "Business consumption",
        eyebrow: "YOUR BUSINESS, CONNECTED",
        care: "Looking after your business",
      }
    : {
        place: "home",
        Place: "Your home",
        consumption: "Home consumption",
        eyebrow: "YOUR HOME, CONNECTED",
        care: "Looking after your home",
      };
