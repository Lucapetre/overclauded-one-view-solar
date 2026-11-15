// Demo geography: Bucharest Sectors 1–6 and Ilfov County, the clusters of synthetic
// installations inside them, and the pure geometry the map draws (no Leaflet here, so
// everything is unit-tested in Node). Area polygons are passed in as GeoJSON.
import siteProfiles from "../../backend/fixtures/site_profiles.json" with { type: "json" };

/** Area ids in display order: sector-1 … sector-6, ilfov. */
export const AREA_IDS = Object.keys(siteProfiles.areas);
/** { "sector-1": "Sector 1", …, ilfov: "Ilfov" } */
export const AREA_LABELS = Object.fromEntries(
  AREA_IDS.map((id) => [id, siteProfiles.areas[id].label]),
);
/** Area labels in display order (what the demo stores as `site.area`). */
export const AREA_NAMES = AREA_IDS.map((id) => AREA_LABELS[id]);
export const areaLabel = (id) => AREA_LABELS[id] || id || "No area";
/** Label → id ("Sector 6" → "sector-6"); unknown labels give null. */
export const areaIdOf = (label) =>
  AREA_IDS.find((id) => AREA_LABELS[id] === label || id === label) || null;

/** Cluster metadata from the fixture: [{ id, name, area_id, kind }]. */
export const CLUSTERS = siteProfiles.clusters;
const clusterBySite = new Map(
  siteProfiles.profiles.map((p) => [p.site_id, p.cluster || null]),
);
/** The fixture cluster of a site id, or null (standalone or unknown site). */
export const clusterOf = (siteId) => clusterBySite.get(siteId) || null;

/**
 * Cluster kinds. Colour is never the only cue: each kind also has a name in the
 * legend, a dash pattern on the highlight outline and a plural in every label.
 */
export const CLUSTER_KINDS = {
  residential: {
    label: "Residential",
    one: "home",
    many: "homes",
    color: "#2f6fb0",
    dash: null,
  },
  hospitality: {
    label: "Restaurants & cafés",
    one: "restaurant or café",
    many: "restaurants & cafés",
    color: "#b0478f",
    dash: "7 5",
  },
  commercial: {
    label: "Commercial",
    one: "business",
    many: "businesses",
    color: "#6d55c4",
    dash: "2 5",
  },
  industrial: {
    label: "Industrial",
    one: "industrial site",
    many: "industrial sites",
    color: "#8a5a2b",
    dash: "12 5 3 5",
  },
  logistics: {
    label: "Logistics & depots",
    one: "depot or warehouse",
    many: "depots & warehouses",
    color: "#1d7f7f",
    dash: "14 7",
  },
};
const kindOf = (kind) => CLUSTER_KINDS[kind] || CLUSTER_KINDS.commercial;

/** "8 homes", "1 home", "6 restaurants & cafés". */
export function clusterCountLabel(kind, count) {
  const k = kindOf(kind);
  return `${count} ${count === 1 ? k.one : k.many}`;
}
/** "Militari · 8 homes". */
export const clusterSummary = (cluster, count) =>
  `${cluster.name} · ${clusterCountLabel(cluster.kind, count)}`;

/**
 * Groups sites by their `cluster` id. Only clusters with at least one of the given
 * sites are returned, in the order of `clusters`; sites with no (or an unknown)
 * cluster are returned as `standalone`.
 * → { groups: [{ cluster, sites, label }], standalone: [site] }
 */
export function groupByCluster(sites, clusters = CLUSTERS) {
  const known = new Map(clusters.map((c) => [c.id, c]));
  const members = new Map();
  const standalone = [];
  for (const site of sites) {
    const cluster = site.cluster && known.get(site.cluster);
    if (!cluster) {
      standalone.push(site);
      continue;
    }
    if (!members.has(cluster.id)) members.set(cluster.id, []);
    members.get(cluster.id).push(site);
  }
  const groups = clusters
    .filter((c) => members.has(c.id))
    .map((cluster) => {
      const list = members.get(cluster.id);
      return { cluster, sites: list, label: clusterSummary(cluster, list.length) };
    });
  return { groups, standalone };
}

const RAD = Math.PI / 180;
/** Great-circle distance in metres between two { latitude, longitude } points. */
export function distanceMeters(a, b) {
  const dLat = (b.latitude - a.latitude) * RAD,
    dLon = (b.longitude - a.longitude) * RAD;
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(a.latitude * RAD) * Math.cos(b.latitude * RAD) * Math.sin(dLon / 2) ** 2;
  return 2 * 6371008.8 * Math.asin(Math.min(1, Math.sqrt(h)));
}

export const CLUSTER_MIN_RADIUS = 250;
export const CLUSTER_PADDING = 160;
/**
 * Translucent highlight circle for a cluster: centred on the members' centroid, with
 * radius = farthest member + padding, never below `minRadius` metres.
 * → { latitude, longitude, radius } or null without valid points.
 */
export function clusterCircle(
  points,
  { minRadius = CLUSTER_MIN_RADIUS, padding = CLUSTER_PADDING } = {},
) {
  const valid = points.filter(
    (p) => Number.isFinite(p.latitude) && Number.isFinite(p.longitude),
  );
  if (!valid.length) return null;
  const center = {
    latitude: valid.reduce((s, p) => s + p.latitude, 0) / valid.length,
    longitude: valid.reduce((s, p) => s + p.longitude, 0) / valid.length,
  };
  const farthest = Math.max(...valid.map((p) => distanceMeters(center, p)));
  return { ...center, radius: Math.max(minRadius, farthest + padding) };
}

/** [[minLat, minLon], [maxLat, maxLon]] of a circle (metres → degrees, small-circle approximation). */
export function circleBounds({ latitude, longitude, radius }) {
  const dLat = radius / 111320,
    dLon = radius / (111320 * Math.max(0.01, Math.cos(latitude * RAD)));
  return [
    [latitude - dLat, longitude - dLon],
    [latitude + dLat, longitude + dLon],
  ];
}

/* ------------------------------ Boundaries ------------------------------ */

const polygonsOf = (geometry) =>
  geometry?.type === "Polygon"
    ? [geometry.coordinates]
    : geometry?.type === "MultiPolygon"
      ? geometry.coordinates
      : [];

/** Even-odd ray casting; GeoJSON rings are [longitude, latitude]. */
function inRing(ring, lon, lat) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [x1, y1] = ring[i],
      [x2, y2] = ring[j];
    if (y1 > lat !== y2 > lat && lon < ((x2 - x1) * (lat - y1)) / (y2 - y1) + x1)
      inside = !inside;
  }
  return inside;
}
/** Whether the point is inside the feature (outer ring minus holes). */
export function featureContains(feature, latitude, longitude) {
  return polygonsOf(feature.geometry).some(
    ([outer, ...holes]) =>
      inRing(outer, longitude, latitude) &&
      !holes.some((hole) => inRing(hole, longitude, latitude)),
  );
}
/** The area id whose boundary contains the point, or null. */
export function areaAt(boundaries, latitude, longitude) {
  return (
    (boundaries?.features || []).find((f) =>
      featureContains(f, latitude, longitude),
    )?.properties?.area_id || null
  );
}

/**
 * Boundary features with an `inScope` flag. `areas` lists the area ids (or labels)
 * the viewer may see; null/empty means everything is in scope. When none of the
 * given ids match a boundary (unknown ids from an API), everything stays in scope
 * rather than fading the whole map.
 * → [{ id, name, feature, inScope }]
 */
export function scopeBoundaries(boundaries, areas = null) {
  const features = (boundaries?.features || []).filter(
    (f) => f?.properties?.area_id,
  );
  const wanted = new Set(
    (areas || []).map((a) => areaIdOf(a) || a).filter(Boolean),
  );
  const matches = features.some((f) => wanted.has(f.properties.area_id));
  return features.map((feature) => ({
    id: feature.properties.area_id,
    name: feature.properties.name || areaLabel(feature.properties.area_id),
    feature,
    inScope: !wanted.size || !matches || wanted.has(feature.properties.area_id),
  }));
}

/** [[minLat, minLon], [maxLat, maxLon]] of one or more features, or null. */
export function featureBounds(features) {
  let minLat = Infinity,
    minLon = Infinity,
    maxLat = -Infinity,
    maxLon = -Infinity;
  for (const feature of features)
    for (const polygon of polygonsOf(feature.geometry))
      for (const [lon, lat] of polygon[0] || []) {
        minLat = Math.min(minLat, lat);
        maxLat = Math.max(maxLat, lat);
        minLon = Math.min(minLon, lon);
        maxLon = Math.max(maxLon, lon);
      }
  return Number.isFinite(minLat)
    ? [
        [minLat, minLon],
        [maxLat, maxLon],
      ]
    : null;
}

/** Where to put an area's name: the fixture's label point, else the bounds' middle. */
export function areaLabelPoint(id, feature) {
  const area = siteProfiles.areas[id];
  if (area) return [area.latitude, area.longitude];
  const b = feature && featureBounds([feature]);
  return b ? [(b[0][0] + b[1][0]) / 2, (b[0][1] + b[1][1]) / 2] : null;
}

/** HTML for the Leaflet attribution control (ODbL requires it next to the map). */
export const BOUNDARY_ATTRIBUTION =
  'Boundaries © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, <a href="https://opendatacommons.org/licenses/odbl/1-0/">ODbL 1.0</a>';
