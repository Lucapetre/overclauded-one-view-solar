// The existing Bucharest map fed by the common status projection (OpsMap.status_sites,
// unmapped, counts, crews, routes), plus the unmapped list and an accessible list view
// of every site in scope. Used by Area Radar and the ranked Incidents queue.
import React, { useMemo } from "react";
import { MapPinOff } from "lucide-react";
import { BucharestMap, MAP_NOTE } from "./map";
import { toMapClusters, toMapSites } from "./opsData";
import {
  attentionBadge,
  conditionText,
  progressText,
  shortSiteName,
  telemetryBadge,
  toMapOverlays,
  toStatusMapSites,
  unmappedSites,
  workflowText,
  bandTone,
  filterMapView,
} from "./opsView";
import { localDateTime, localTime } from "./planView";
import { Pill } from "./opsShared";

/** Site rows of the projection (mapped first, then unmapped), for the list view. */
function statusRows(map) {
  return [...(map?.status_sites || []), ...(map?.unmapped || [])];
}

export function OpsStatusMap({
  map,
  aliases,
  selectedSiteId = null,
  relatedIds = null,
  selectedIncident = null,
  onSiteClick,
  onAction,
  actionLabel = "Select in queue",
  visibleSiteIds = null,
  height = 440,
  showList = true,
  tickets = null,
}) {
  const all = useMemo(
    () => (map ? toStatusMapSites(map, aliases, toMapSites, tickets) : []),
    [map, aliases, tickets],
  );
  const sites = useMemo(
    () => (visibleSiteIds ? all.filter((s) => visibleSiteIds.has(s.id)) : all),
    [all, visibleSiteIds],
  );
  const clusters = useMemo(() => toMapClusters(map), [map]);
  const overlays = useMemo(
    () => (map ? toMapOverlays(filterMapView(map, visibleSiteIds), selectedIncident) : null),
    [map, selectedIncident, visibleSiteIds],
  );
  const scopeAreaIds = useMemo(() => Object.keys(aliases || {}), [aliases]);
  const visibleMap = useMemo(() => filterMapView(map, visibleSiteIds), [map, visibleSiteIds]);
  const unmapped = useMemo(() => unmappedSites(visibleMap), [visibleMap]);
  const counts = visibleMap?.counts;
  const rows = statusRows(visibleMap);
  return (
    <div className="ops-status-map">
      {counts && (
        <div className="ops-count-strip" aria-label="Status counts">
          <span>
            <b>{counts.affected_sites}</b> affected site{counts.affected_sites === 1 ? "" : "s"}
          </span>
          <span>
            <b>{counts.unique_episodes}</b> unique episode{counts.unique_episodes === 1 ? "" : "s"}
          </span>
          <span>
            <b>{counts.mapped_sites}</b> of {counts.sites} sites on the map
          </span>
          {counts.unmapped_sites > 0 && (
            <span className="warn">
              <b>{counts.unmapped_sites}</b> unmapped
            </span>
          )}
          {map.status_as_of && (
            <span className="muted">
              Status as of {localDateTime(map.status_as_of)} · revision {map.revision}
            </span>
          )}
        </div>
      )}
      {visibleSiteIds && (
        <p className="small-note">
          Filters active: {sites.length} of {all.length} mapped sites shown.
        </p>
      )}
      <BucharestMap
        sites={sites}
        clusters={clusters}
        areas={scopeAreaIds.length ? scopeAreaIds : null}
        selectedId={selectedSiteId}
        relatedIds={relatedIds}
        onMarkerClick={onSiteClick}
        onSelect={onAction}
        actionLabel={actionLabel}
        overlays={overlays}
        legend={map?.status_sites?.length ? "status" : "default"}
        note={map?.note || MAP_NOTE}
        height={height}
        ariaLabel="Map of Bucharest and Ilfov with the sites in your scope, their status, crew base locations and schematic crew routes. Use the plus and minus buttons to zoom; drag to pan. The list below the map has the same information."
      />
      {overlays?.routes?.length > 0 && (
        <p className="small-note">
          {overlays.routes[0].note}. Proposed routes are dashed; applied routes are solid.
          {overlays.routes.some((r) => r.redacted) &&
            " Some stops outside your scope are hidden."}
        </p>
      )}
      {unmapped.length > 0 && (
        <div className="ops-unmapped" role="region" aria-label="Unmapped sites">
          <h4>
            <MapPinOff size={15} aria-hidden="true" /> Unmapped sites ({unmapped.length})
          </h4>
          <p className="small-note">
            No coordinates on record, so these sites are not placed on the map
            (never at 0,0 or next to another site).
          </p>
          <ul>
            {unmapped.map((s) => (
              <li key={s.id}>
                <b>{s.name}</b> · {s.area} · {s.condition} · {s.telemetry} ·{" "}
                {s.workflow}
                {s.priority && <Pill tone={bandTone(s.priority)}>{s.priority}</Pill>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {showList && rows.length > 0 && (
        <details className="ops-site-list">
          <summary>List view: {visibleSiteIds ? "filtered sites" : "every site in scope"} ({rows.length})</summary>
          <div className="table-scroll">
            <table className="ops-table">
              <thead>
                <tr>
                  <th>Site</th>
                  <th>Condition</th>
                  <th>Attention</th>
                  <th>Telemetry</th>
                  <th>Workflow</th>
                  <th>Crew / ETA</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => (
                  <tr
                    key={s.site_id}
                    className={s.site_id === selectedSiteId ? "is-selected" : ""}
                  >
                    <td>
                      <b>{shortSiteName(s.alias)}</b>
                      <small>
                        {s.area_alias || s.area_id || "No area"}
                        {s.position ? "" : " · unmapped"}
                      </small>
                    </td>
                    <td>
                      {conditionText(s.condition)}
                      {s.condition_note && <small>{s.condition_note}</small>}
                    </td>
                    <td>
                      <Pill tone={attentionBadge(s.attention).tone}>
                        {s.highest_priority ? `${s.highest_priority} · ` : ""}
                        {attentionBadge(s.attention).label}
                      </Pill>
                    </td>
                    <td>
                      <Pill tone={telemetryBadge(s.telemetry?.state).tone}>
                        {telemetryBadge(s.telemetry?.state).label}
                      </Pill>
                      {s.telemetry?.access_errors?.length > 0 && (
                        <small>
                          {s.telemetry.access_errors
                            .map((e) => `${e.source}: ${e.failure_class.replaceAll("_", " ")}`)
                            .join("; ")}
                        </small>
                      )}
                    </td>
                    <td>{workflowText(s.workflow)}</td>
                    <td>
                      {s.crew?.crew_name ? (
                        <>
                          {s.crew.crew_name}
                          <small>
                            {[
                              s.crew.progress && progressText(s.crew.progress),
                              s.crew.eta && `ETA ${localTime(s.crew.eta)} (estimate)`,
                            ]
                              .filter(Boolean)
                              .join(" · ") || "Assigned"}
                          </small>
                        </>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </div>
  );
}
