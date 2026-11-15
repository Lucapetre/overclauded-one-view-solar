// Real OSM boundaries of Bucharest Sectors 1–6 and Ilfov County (© OpenStreetMap
// contributors, ODbL 1.0), loaded as text because Vite only parses `.json` imports.
// Browser-only (Vite `?raw`); Node tests read the file with readFileSync instead.
import raw from "../../backend/fixtures/bucharest_areas.geojson?raw";

export const AREA_BOUNDARIES = JSON.parse(raw);
