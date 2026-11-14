// Production forecast from a live public weather forecast.
// Only a fixed city-level location is sent to the weather service: no account or site data.
export const LOCATION = { name: "Bucharest", latitude: 44.43, longitude: 26.1 };
export const WEATHER_URL =
  "https://api.open-meteo.com/v1/forecast?" +
  new URLSearchParams({
    latitude: LOCATION.latitude,
    longitude: LOCATION.longitude,
    hourly: "shortwave_radiation,temperature_2m,relative_humidity_2m,cloud_cover",
    timezone: "Europe/Bucharest",
    forecast_days: 3,
  });

// Stated modelling assumptions (illustrative, not a fitted or certified model).
export const MODEL = {
  performanceRatio: 0.85, // inverter, wiring and soiling losses
  temperatureCoefficient: 0.004, // output lost per °C of cell temperature above 25 °C
  cellHeating: 25, // °C a cell runs above air temperature at 800 W/m²
  humidityStart: 60, // % relative humidity above which haze is assumed
  humidityMaxLoss: 0.05, // output lost at 100 % relative humidity
};

export function season(isoDate) {
  const month = Number(isoDate.slice(5, 7));
  return month <= 2 || month === 12
    ? "Winter"
    : month <= 5
      ? "Spring"
      : month <= 8
        ? "Summer"
        : "Autumn";
}

/** Expected AC power in kW for one hour of weather; null if an input is missing. */
export function hourlyPower(hour, kwp) {
  const { radiation, temperature, humidity } = hour;
  if (![radiation, temperature, humidity, kwp].every(Number.isFinite)) return null;
  const sun = Math.max(0, radiation) / 1000;
  const cell = temperature + (Math.max(0, radiation) / 800) * MODEL.cellHeating;
  const heat = Math.min(
    1.1,
    Math.max(0.7, 1 - MODEL.temperatureCoefficient * (cell - 25)),
  );
  const haze =
    1 -
    MODEL.humidityMaxLoss *
      Math.min(1, Math.max(0, (humidity - MODEL.humidityStart) / 40));
  return Math.min(kwp, kwp * sun * MODEL.performanceRatio * heat * haze);
}

const mean = (values) =>
  values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;

/**
 * Daily outlook. `prices` come from the customer's saved contract; without one the
 * money range is omitted rather than assumed.
 */
export function dailyForecast(weather, kwp, prices) {
  const h = weather?.hourly;
  if (!h?.time?.length) return [];
  const days = new Map();
  h.time.forEach((time, index) => {
    const hour = {
      time,
      radiation: h.shortwave_radiation?.[index],
      temperature: h.temperature_2m?.[index],
      humidity: h.relative_humidity_2m?.[index],
      cloud: h.cloud_cover?.[index],
    };
    hour.kw = hourlyPower(hour, kwp);
    const date = time.slice(0, 10);
    if (!days.has(date)) days.set(date, []);
    days.get(date).push(hour);
  });
  return [...days.entries()].map(([date, list]) => {
    const known = list.filter((hour) => hour.kw != null);
    const complete = known.length === list.length && list.length >= 23;
    // Hourly radiation is an hourly mean, so kW for one hour equals kWh.
    const kwh = complete ? known.reduce((sum, hour) => sum + hour.kw, 0) : null;
    const light = list.filter((hour) => hour.radiation > 20);
    const finite = (key, from = list) =>
      from.map((hour) => hour[key]).filter(Number.isFinite);
    return {
      date,
      season: season(date),
      kwh,
      peakKw: known.length ? Math.max(...known.map((hour) => hour.kw)) : null,
      daylightHours: light.length,
      cloud: mean(finite("cloud", light.length ? light : list)),
      humidity: mean(finite("humidity", light.length ? light : list)),
      temperatureMax: finite("temperature").length
        ? Math.max(...finite("temperature"))
        : null,
      // All exported (lowest value) to all used on site (highest value).
      value:
        kwh != null && prices
          ? {
              low: kwh * Math.min(prices.exportPrice, prices.importPrice),
              high: kwh * Math.max(prices.exportPrice, prices.importPrice),
            }
          : null,
      hours: list,
    };
  });
}

export function skyLabel(cloud) {
  if (cloud == null) return "Sky unknown";
  return cloud < 25
    ? "Mostly sunny"
    : cloud < 60
      ? "Partly cloudy"
      : cloud < 85
        ? "Mostly cloudy"
        : "Overcast";
}
