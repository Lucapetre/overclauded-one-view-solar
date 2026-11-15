// Real street map of Bucharest and Ilfov (OpenStreetMap tiles, plain Leaflet) with the
// sector/county boundaries, translucent cluster highlights and site markers.
// Reusable: takes plain data, no demo state. Markers and boundaries are DOM/SVG, so
// they still render on a plain background when the tiles cannot load (offline).
import React, { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "./ops.css";
import siteProfiles from "../../backend/fixtures/site_profiles.json" with { type: "json" };
import { AREA_BOUNDARIES } from "./areaBoundaries";
import {
  BOUNDARY_ATTRIBUTION,
  CLUSTERS,
  CLUSTER_KINDS,
  areaLabelPoint,
  circleBounds,
  clusterCircle,
  featureBounds,
  groupByCluster,
  scopeBoundaries,
} from "./geography";

export const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
export const TILE_ATTRIBUTION =
  '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
export { BOUNDARY_ATTRIBUTION };
export const MAP_NOTE =
  "Fictional installations placed near real Bucharest and Ilfov neighbourhoods. Coordinates, capacities and billing profiles are invented; no real customer or address is shown. Sector and county boundaries: © OpenStreetMap contributors (ODbL).";
/** Below this zoom a cluster of 2+ sites shows one highlight with a count badge. */
export const CLUSTER_ZOOM = 14;
const CENTER = [siteProfiles.center.latitude, siteProfiles.center.longitude];
const START_ZOOM = siteProfiles.center.zoom || 11;

export const STATUS = {
  ok: { label: "No open incident", glyph: "✓" },
  stale: { label: "Telemetry stale", glyph: "–" },
  review: { label: "Open incident · review (P2/P3)", glyph: "P2" },
  urgent: { label: "Open incident · urgent (P0/P1)", glyph: "P1" },
};
const SEVERITY = ["ok", "stale", "review", "urgent"];
/** Marker class from a site's status and tier. */
export function markerStatus(site) {
  if (site.status === "incident")
    return ["P0", "P1"].includes(site.tier) ? "urgent" : "review";
  return site.status === "stale" ? "stale" : "ok";
}
const glyph = (site, status) =>
  status === "urgent" || status === "review"
    ? site.tier || "!"
    : STATUS[status].glyph;
const fmt = (n) =>
  new Intl.NumberFormat("en-GB", { maximumFractionDigits: 1 }).format(n);
const escapeHtml = (text) =>
  String(text).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

function statusText(site) {
  if (site.status === "incident")
    return `Open incident${site.tier ? " · " + site.tier : ""}`;
  return site.status === "stale" ? "Telemetry stale" : "No open incident";
}

function popupContent(site, cluster, actionLabel, onAction) {
  const root = document.createElement("div");
  root.className = "bm-popup";
  const line = (tag, text, className) => {
    const el = document.createElement(tag);
    el.textContent = text;
    if (className) el.className = className;
    root.appendChild(el);
    return el;
  };
  line("b", site.name);
  line(
    "small",
    [site.id, site.zone || "Bucharest", site.area].filter(Boolean).join(" · "),
  );
  line(
    "span",
    `${site.segment === "business" ? `Business · ${site.businessType || "commercial"}` : "Home"} · ${fmt(site.kwp)} kWp`,
  );
  if (cluster)
    line(
      "small",
      `Group: ${cluster.name} (${(CLUSTER_KINDS[cluster.kind]?.label || cluster.kind).toLowerCase()})`,
    );
  line("span", statusText(site), "bm-popup-status");
  if (site.detail) line("small", site.detail);
  const button = line("button", actionLabel, "btn yellow");
  button.type = "button";
  button.addEventListener("click", () => onAction(site.id));
  return root;
}

/** "2 open incidents (worst P1)" for a cluster's members, or "". */
function incidentNote(sites) {
  const open = sites.filter((s) => s.status === "incident");
  if (!open.length) return "";
  const worst = open.map((s) => s.tier).filter(Boolean).sort()[0];
  return `${open.length} open incident${open.length === 1 ? "" : "s"}${worst ? ` (worst ${worst})` : ""}`;
}

/**
 * sites: [{ id, name, latitude, longitude, zone, segment: "home"|"business",
 *           businessType, kwp, status: "ok"|"stale"|"incident", tier: "P0".."P3"|null,
 *           area, cluster?: cluster id | null, detail? }]
 * selectedId: highlighted site id; onSelect(id): called from the popup button.
 * clusters: [{ id, name, area_id, kind }] (default: the shared fixture's clusters).
 * areas: area ids (or labels) in the viewer's scope; null = all. Areas outside the
 *        scope stay visible but faded (grey wash, thin dashed outline), so the
 *        viewer keeps the city context; in-scope areas get a strong outline and the
 *        view is fitted to include them.
 * showBoundaries: draw the sector/county boundaries (default true).
 * boundaries: GeoJSON FeatureCollection with properties.area_id (default: OSM file).
 */
export function BucharestMap({
  sites,
  selectedId = null,
  onSelect,
  height = 440,
  actionLabel = "Open details",
  note = MAP_NOTE,
  clusters = CLUSTERS,
  areas = null,
  showBoundaries = true,
  boundaries = AREA_BOUNDARIES,
}) {
  const container = useRef(null),
    mapRef = useRef(null),
    layersRef = useRef(null),
    markersRef = useRef(new Map()),
    selectRef = useRef(onSelect);
  selectRef.current = onSelect;
  const selectedRef = useRef(selectedId);
  selectedRef.current = selectedId;
  const [tiles, setTiles] = useState("loading");

  const areasKey = (areas || []).join("|");
  const scoped = useMemo(
    () => (showBoundaries ? scopeBoundaries(boundaries, areas) : []),
    [showBoundaries, boundaries, areasKey],
  );
  const limited = scoped.some((b) => !b.inScope);

  // Create the map once; remove it on unmount (StrictMode runs this twice).
  useEffect(() => {
    const map = L.map(container.current, {
      center: CENTER,
      zoom: START_ZOOM,
      minZoom: 9,
      maxZoom: 18,
      // Half steps let the whole city plus Ilfov fit without a tiny map.
      zoomSnap: 0.5,
      scrollWheelZoom: false,
    });
    let loaded = false;
    L.tileLayer(TILE_URL, { maxZoom: 19, attribution: TILE_ATTRIBUTION })
      .on("tileload", () => {
        loaded = true;
        setTiles("ok");
      })
      .on("tileerror", () => {
        if (!loaded) setTiles("failed");
      })
      .addTo(map);
    // Wheel zoom only after the map is focused, so the page still scrolls.
    map.on("focus", () => map.scrollWheelZoom.enable());
    map.on("blur", () => map.scrollWheelZoom.disable());
    // Panes keep the order boundaries < cluster highlights < labels < markers.
    for (const [name, z] of [
      ["bm-areas", 350],
      ["bm-clusters", 380],
      ["bm-labels", 450],
    ])
      map.createPane(name).style.zIndex = z;
    map.getPane("bm-labels").style.pointerEvents = "none";
    layersRef.current = {
      areas: L.layerGroup().addTo(map),
      clusters: L.layerGroup().addTo(map),
      markers: L.layerGroup().addTo(map),
    };
    mapRef.current = map;
    const resize =
      typeof ResizeObserver === "function"
        ? new ResizeObserver(() => map.invalidateSize())
        : null;
    resize?.observe(container.current);
    return () => {
      resize?.disconnect();
      map.remove();
      mapRef.current = null;
      layersRef.current = null;
      markersRef.current = new Map();
    };
  }, []);

  // Sector and county boundaries with their names; faded outside the scope.
  useEffect(() => {
    const map = mapRef.current,
      layer = layersRef.current?.areas;
    if (!map || !layer) return;
    layer.clearLayers();
    if (!scoped.length) return;
    for (const area of scoped) {
      L.geoJSON(area.feature, {
        pane: "bm-areas",
        interactive: false,
        style: area.inScope
          ? {
              color: "#2f4a3c",
              weight: 2,
              opacity: 0.8,
              fillColor: "#5f7f6c",
              fillOpacity: 0.05,
            }
          : {
              color: "#7d857d",
              weight: 1,
              opacity: 0.45,
              dashArray: "4 4",
              fillColor: "#8f968f",
              fillOpacity: 0.16,
            },
      }).addTo(layer);
      const point = areaLabelPoint(area.id, area.feature);
      if (point)
        L.marker(point, {
          pane: "bm-labels",
          interactive: false,
          keyboard: false,
          icon: L.divIcon({
            className: "bm-area-label-icon",
            iconSize: [120, 22],
            iconAnchor: [60, 11],
            html: `<span class="bm-area-label${area.inScope ? "" : " is-out"}">${escapeHtml(area.name)}</span>`,
          }),
        }).addTo(layer);
    }
    map.attributionControl?.addAttribution(BOUNDARY_ATTRIBUTION);
    return () => map.attributionControl?.removeAttribution(BOUNDARY_ATTRIBUTION);
  }, [scoped]);

  // Rebuild cluster highlights and markers whenever the sites change; fit the view.
  const siteKey = sites
    .map(
      (s) =>
        `${s.id}:${s.latitude}:${s.longitude}:${s.status}:${s.tier}:${s.name}:${s.cluster || ""}:${s.detail || ""}`,
    )
    .join("|");
  const clusterKey = clusters.map((c) => `${c.id}:${c.kind}:${c.name}`).join("|");
  useEffect(() => {
    const map = mapRef.current,
      layers = layersRef.current;
    if (!map || !layers) return;
    layers.clusters.clearLayers();
    layers.markers.clearLayers();
    markersRef.current = new Map();
    const valid = sites.filter(
      (s) => Number.isFinite(s.latitude) && Number.isFinite(s.longitude),
    );
    const clusterById = new Map(clusters.map((c) => [c.id, c]));

    const makeMarker = (site, target) => {
      const status = markerStatus(site);
      const business = site.segment === "business";
      const size = business ? 30 : 22;
      const icon = L.divIcon({
        className: "bm-icon",
        iconSize: [size, size],
        iconAnchor: [size / 2, size / 2],
        popupAnchor: [0, -size / 2],
        html: `<span class="bm-pin ${business ? "bm-business" : "bm-home"} bm-${status}${site.id === selectedId ? " is-selected" : ""}">${escapeHtml(glyph(site, status))}</span>`,
      });
      const marker = L.marker([site.latitude, site.longitude], {
        icon,
        keyboard: true,
        riseOnHover: true,
      })
        .bindTooltip(`${site.name} · ${statusText(site)}`, {
          direction: "top",
          offset: [0, -size / 2],
        })
        .bindPopup(() =>
          popupContent(site, clusterById.get(site.cluster), actionLabel, (id) => {
            map.closePopup();
            selectRef.current?.(id);
          }),
        );
      // Members of a collapsed cluster get their element only when shown.
      marker.on("add", () => {
        const el = marker.getElement();
        el?.setAttribute(
          "aria-label",
          `${site.name}, ${business ? "business" : "home"}, ${statusText(site)}`,
        );
        el?.querySelector(".bm-pin")?.classList.toggle(
          "is-selected",
          site.id === selectedRef.current,
        );
      });
      marker.addTo(target);
      markersRef.current.set(site.id, marker);
      return marker;
    };

    const zoomTo = (circle) => {
      const bounds = L.latLngBounds(circleBounds(circle));
      const fit = map.getBoundsZoom(bounds, false, L.point(32, 32));
      map.setView(
        [circle.latitude, circle.longitude],
        Math.min(17, Math.max(CLUSTER_ZOOM, fit)),
      );
    };

    const { groups, standalone } = groupByCluster(valid, clusters);
    const views = groups.map((group) => {
      const kind = CLUSTER_KINDS[group.cluster.kind] || CLUSTER_KINDS.commercial;
      const circle = clusterCircle(group.sites);
      const incidents = incidentNote(group.sites);
      const label = group.label + (incidents ? ` · ${incidents}` : "");
      L.circle([circle.latitude, circle.longitude], {
        pane: "bm-clusters",
        radius: circle.radius,
        color: kind.color,
        weight: 2,
        opacity: 0.9,
        dashArray: kind.dash,
        fillColor: kind.color,
        fillOpacity: 0.16,
        bubblingMouseEvents: false,
      })
        .bindTooltip(`${label} · ${kind.label}`, { sticky: true })
        .on("click", () => zoomTo(circle))
        .addTo(layers.clusters);
      const members = L.layerGroup();
      for (const site of group.sites) makeMarker(site, members);
      // Name above the highlight, shown when the members are visible.
      const nameTag = L.marker(
        [circle.latitude + circle.radius / 111320, circle.longitude],
        {
          pane: "bm-labels",
          interactive: false,
          keyboard: false,
          icon: L.divIcon({
            className: "bm-area-label-icon",
            iconSize: [180, 20],
            iconAnchor: [90, 20],
            html: `<span class="bm-cluster-label" style="--kind:${kind.color}">${escapeHtml(group.label)}</span>`,
          }),
        },
      );
      // Count badge, shown instead of the members below CLUSTER_ZOOM.
      const worst = group.sites
        .map(markerStatus)
        .reduce((a, b) => (SEVERITY.indexOf(b) > SEVERITY.indexOf(a) ? b : a), "ok");
      const worstTier = group.sites
        .filter((s) => s.status === "incident")
        .map((s) => s.tier)
        .filter(Boolean)
        .sort()[0];
      const flag =
        worst === "urgent" || worst === "review"
          ? `<i class="bm-pin bm-home bm-${worst}">${escapeHtml(worstTier || "!")}</i>`
          : "";
      const badge = L.marker([circle.latitude, circle.longitude], {
        keyboard: true,
        riseOnHover: true,
        // Where badges overlap city-wide, urgent and larger groups stay on top.
        zIndexOffset:
          (worst === "urgent" ? 400 : worst === "review" ? 200 : 0) +
          group.sites.length * 10,
        icon: L.divIcon({
          className: "bm-icon",
          iconSize: [34, 34],
          iconAnchor: [17, 17],
          html: `<span class="bm-cluster-badge" style="--kind:${kind.color}"><b>${group.sites.length}</b>${flag}</span>`,
        }),
      })
        .bindTooltip(`${label} · click to zoom in`, { direction: "top", offset: [0, -17] })
        .on("click", () => zoomTo(circle));
      return { members, nameTag, badge, collapsible: group.sites.length > 1, label };
    });
    for (const site of standalone) makeMarker(site, layers.markers);

    const applyZoom = () => {
      const expanded = map.getZoom() >= CLUSTER_ZOOM;
      for (const view of views) {
        const showMembers = expanded || !view.collapsible;
        const toggle = (layer, on) => {
          if (on && !layers.markers.hasLayer(layer)) layers.markers.addLayer(layer);
          if (!on && layers.markers.hasLayer(layer)) layers.markers.removeLayer(layer);
        };
        toggle(view.members, showMembers);
        toggle(view.badge, !showMembers);
        toggle(view.nameTag, showMembers);
        if (!showMembers)
          view.badge
            .getElement()
            ?.setAttribute("aria-label", `${view.label}. Press Enter to zoom in.`);
      }
    };

    // Fit to the sites; a limited scope also includes its whole area outline.
    const points = valid.map((s) => [s.latitude, s.longitude]);
    let bounds = points.length ? L.latLngBounds(points) : null;
    if (limited) {
      const own = featureBounds(scoped.filter((b) => b.inScope).map((b) => b.feature));
      if (own) bounds = bounds ? bounds.extend(L.latLngBounds(own)) : L.latLngBounds(own);
    }
    if (bounds && (points.length > 1 || limited))
      map.fitBounds(bounds, { padding: [20, 20], maxZoom: 14 });
    else if (points.length === 1) map.setView(points[0], 15);
    else map.setView(CENTER, START_ZOOM);
    applyZoom();
    map.on("zoomend", applyZoom);
    return () => {
      map.off("zoomend", applyZoom);
    };
  }, [siteKey, clusterKey, actionLabel, scoped]);

  // Highlight the selected marker without refitting the view.
  useEffect(() => {
    for (const [id, marker] of markersRef.current)
      marker
        .getElement()
        ?.querySelector(".bm-pin")
        ?.classList.toggle("is-selected", id === selectedId);
  }, [selectedId, siteKey]);

  const kindsShown = [
    ...new Set(
      groupByCluster(
        sites.filter((s) => Number.isFinite(s.latitude) && Number.isFinite(s.longitude)),
        clusters,
      ).groups.map((g) => g.cluster.kind),
    ),
  ];
  return (
    <div className="bm-wrap">
      <div
        ref={container}
        className={"bm-map" + (tiles === "failed" ? " bm-offline" : "")}
        style={{ height }}
        role="region"
        aria-label="Map of Bucharest Sectors 1 to 6 and Ilfov County with synthetic installations. Use the plus and minus buttons to zoom; drag to pan."
      />
      {tiles === "failed" && (
        <p className="bm-tiles-note" role="status">
          Street map tiles could not load (offline?). Area boundaries and sites
          are shown on a plain background at their positions.
        </p>
      )}
      <MapLegend
        kinds={kindsShown}
        boundaries={scoped.length > 0}
        faded={limited}
      />
      {note && <p className="small-note bm-note">{note}</p>}
    </div>
  );
}

function AreaSwatch({ out = false }) {
  return (
    <svg className="bm-kind-swatch" width="24" height="14" aria-hidden="true">
      <rect
        x="1"
        y="1"
        width="22"
        height="12"
        fill={out ? "#8f968f" : "#5f7f6c"}
        fillOpacity={out ? 0.35 : 0.08}
        stroke={out ? "#7d857d" : "#2f4a3c"}
        strokeWidth={out ? 1 : 2}
        strokeDasharray={out ? "3 3" : undefined}
      />
    </svg>
  );
}

function KindSwatch({ kind }) {
  const k = CLUSTER_KINDS[kind];
  return (
    <svg className="bm-kind-swatch" width="24" height="14" aria-hidden="true">
      <rect
        x="1.5"
        y="1.5"
        width="21"
        height="11"
        rx="5.5"
        fill={k.color}
        fillOpacity="0.2"
        stroke={k.color}
        strokeWidth="2"
        strokeDasharray={k.dash || undefined}
      />
    </svg>
  );
}

/**
 * kinds: cluster kinds to explain (default none); boundaries: explain the area
 * outlines; faded: explain the grey wash outside the viewer's scope.
 */
export function MapLegend({ kinds = [], boundaries = false, faded = false }) {
  return (
    <div className="map-legend bm-legend" aria-label="Map legend">
      <span>
        <i className="bm-pin bm-home bm-legend-shape" aria-hidden="true" />
        Home
      </span>
      <span>
        <i className="bm-pin bm-business bm-legend-shape" aria-hidden="true" />
        Business
      </span>
      {Object.entries(STATUS).map(([key, value]) => (
        <span key={key}>
          <i className={`bm-pin bm-home bm-${key}`} aria-hidden="true">
            {value.glyph}
          </i>
          {value.label}
        </span>
      ))}
      {boundaries && (
        <span>
          <AreaSwatch />
          Sector / county boundary
        </span>
      )}
      {faded && (
        <span>
          <AreaSwatch out />
          Outside your scope (faded)
        </span>
      )}
      {kinds
        .filter((kind) => CLUSTER_KINDS[kind])
        .map((kind) => (
          <span key={kind}>
            <KindSwatch kind={kind} />
            {CLUSTER_KINDS[kind].label} group
          </span>
        ))}
      {kinds.length > 0 && (
        <span className="bm-legend-hint">
          <span className="bm-cluster-badge bm-legend-badge" aria-hidden="true">
            <b>8</b>
          </span>
          Group of sites: zoom in or click it to see each one
        </span>
      )}
    </div>
  );
}
