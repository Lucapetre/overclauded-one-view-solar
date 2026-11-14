// Real street map of Bucharest (OpenStreetMap tiles, plain Leaflet) with site markers.
// Reusable: takes plain site data, no demo state. Markers are DOM elements, so they
// still render on a plain background when the tiles cannot load (offline).
import React, { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import "./ops.css";
import siteProfiles from "../../backend/fixtures/site_profiles.json" with { type: "json" };

export const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
export const TILE_ATTRIBUTION =
  '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
export const MAP_NOTE =
  "Fictional installations placed near real Bucharest neighbourhoods. Coordinates, capacities and billing profiles are invented; no real customer or address is shown.";
const CENTER = [siteProfiles.center.latitude, siteProfiles.center.longitude];

export const STATUS = {
  ok: { label: "No open incident", glyph: "✓" },
  stale: { label: "Telemetry stale", glyph: "–" },
  review: { label: "Open incident · review (P2/P3)", glyph: "P2" },
  urgent: { label: "Open incident · urgent (P0/P1)", glyph: "P1" },
};
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

function statusText(site) {
  if (site.status === "incident")
    return `Open incident${site.tier ? " · " + site.tier : ""}`;
  return site.status === "stale" ? "Telemetry stale" : "No open incident";
}

function popupContent(site, actionLabel, onAction) {
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
  line("small", `${site.id} · ${site.zone || "Bucharest"} · ${site.area || ""} area`);
  line(
    "span",
    `${site.segment === "business" ? `Business · ${site.businessType || "commercial"}` : "Home"} · ${fmt(site.kwp)} kWp`,
  );
  line("span", statusText(site), "bm-popup-status");
  if (site.detail) line("small", site.detail);
  const button = line("button", actionLabel, "btn yellow");
  button.type = "button";
  button.addEventListener("click", () => onAction(site.id));
  return root;
}

/**
 * sites: [{ id, name, latitude, longitude, zone, segment: "home"|"business",
 *           businessType, kwp, status: "ok"|"stale"|"incident", tier: "P0".."P3"|null,
 *           area, detail? }]
 * selectedId: highlighted site id; onSelect(id): called from the popup button.
 */
export function BucharestMap({
  sites,
  selectedId = null,
  onSelect,
  height = 440,
  actionLabel = "Open details",
  note = MAP_NOTE,
}) {
  const container = useRef(null),
    mapRef = useRef(null),
    layerRef = useRef(null),
    markersRef = useRef(new Map()),
    selectRef = useRef(onSelect);
  selectRef.current = onSelect;
  const [tiles, setTiles] = useState("loading");

  // Create the map once; remove it on unmount (StrictMode runs this twice).
  useEffect(() => {
    const map = L.map(container.current, {
      center: CENTER,
      zoom: siteProfiles.center.zoom || 12,
      minZoom: 10,
      maxZoom: 18,
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
    layerRef.current = L.layerGroup().addTo(map);
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
      layerRef.current = null;
      markersRef.current = new Map();
    };
  }, []);

  // Rebuild markers whenever the sites change, and fit the view to them.
  const siteKey = sites
    .map((s) => `${s.id}:${s.latitude}:${s.longitude}:${s.status}:${s.tier}:${s.name}:${s.detail || ""}`)
    .join("|");
  useEffect(() => {
    const map = mapRef.current,
      layer = layerRef.current;
    if (!map || !layer) return;
    layer.clearLayers();
    markersRef.current = new Map();
    const points = [];
    for (const site of sites) {
      if (!Number.isFinite(site.latitude) || !Number.isFinite(site.longitude))
        continue;
      const status = markerStatus(site);
      const business = site.segment === "business";
      const size = business ? 32 : 24;
      const icon = L.divIcon({
        className: "bm-icon",
        iconSize: [size, size],
        iconAnchor: [size / 2, size / 2],
        popupAnchor: [0, -size / 2],
        html: `<span class="bm-pin ${business ? "bm-business" : "bm-home"} bm-${status}${site.id === selectedId ? " is-selected" : ""}">${glyph(site, status)}</span>`,
      });
      const marker = L.marker([site.latitude, site.longitude], {
        icon,
        keyboard: true,
        riseOnHover: true,
      })
        .bindTooltip(`${site.name} · ${statusText(site)}`, { direction: "top", offset: [0, -size / 2] })
        .bindPopup(() =>
          popupContent(site, actionLabel, (id) => {
            map.closePopup();
            selectRef.current?.(id);
          }),
        )
        .addTo(layer);
      marker
        .getElement()
        ?.setAttribute(
          "aria-label",
          `${site.name}, ${business ? "business" : "home"}, ${statusText(site)}`,
        );
      markersRef.current.set(site.id, marker);
      points.push([site.latitude, site.longitude]);
    }
    if (points.length > 1)
      map.fitBounds(L.latLngBounds(points), { padding: [36, 36], maxZoom: 14 });
    else if (points.length === 1) map.setView(points[0], 14);
    else map.setView(CENTER, siteProfiles.center.zoom || 12);
  }, [siteKey, actionLabel]);

  // Highlight the selected marker without refitting the view.
  useEffect(() => {
    for (const [id, marker] of markersRef.current)
      marker
        .getElement()
        ?.querySelector(".bm-pin")
        ?.classList.toggle("is-selected", id === selectedId);
  }, [selectedId, siteKey]);

  return (
    <div className="bm-wrap">
      <div
        ref={container}
        className={"bm-map" + (tiles === "failed" ? " bm-offline" : "")}
        style={{ height }}
        role="region"
        aria-label="Map of Bucharest with synthetic installations. Use the plus and minus buttons to zoom; drag to pan."
      />
      {tiles === "failed" && (
        <p className="bm-tiles-note" role="status">
          Street map tiles could not load (offline?). Sites are shown on a plain
          background at their positions.
        </p>
      )}
      <MapLegend />
      {note && <p className="small-note bm-note">{note}</p>}
    </div>
  );
}

export function MapLegend() {
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
    </div>
  );
}
