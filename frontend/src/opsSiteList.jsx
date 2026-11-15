// Manager radar pieces: the live indicator, priority chips with counts (they filter the map
// and the list together) and the complete site/incident list with status, priority, area,
// open tickets, assignment and last update.
import React from "react";
import { MapPinOff } from "lucide-react";
import { Pill } from "./opsShared";
import { bandTone } from "./opsView";
import { priorityCounts } from "./dispatchView";
import { localDateTime } from "./planView";

/** "Live · as of 07:30 (replay time) · refreshing every 5 s". */
export function LiveStamp({ asOf, error }) {
  return (
    <span className={`live-stamp${error ? " is-paused" : ""}`} role="status">
      <i aria-hidden="true" />
      {error ? "Refresh interrupted, showing the last data" : "Live"}
      {asOf ? ` · as of ${localDateTime(asOf)}` : ""} · refreshes every 5 s
    </span>
  );
}

/** P0..P3 chips with the server's counts; toggling one filters map and list. */
export function PriorityChips({ counts, rows, selected, onToggle, onClear }) {
  const byBand = priorityCounts(counts, []);
  const noIssue = rows.filter((r) => !r.priority).length;
  return (
    <div className="priority-chips" role="group" aria-label="Filter sites by priority">
      {byBand.map(({ band, count }) => (
        <button
          key={band}
          className={`priority-chip band-${band}${selected.includes(band) ? " is-on" : ""}`}
          aria-pressed={selected.includes(band)}
          onClick={() => onToggle(band)}
        >
          <Pill tone={bandTone(band)}>{band}</Pill>
          <b>{count}</b>
          <small>{count === 1 ? "case" : "cases"}</small>
        </button>
      ))}
      <button
        className={`priority-chip${selected.includes("none") ? " is-on" : ""}`}
        aria-pressed={selected.includes("none")}
        onClick={() => onToggle("none")}
      >
        <Pill>No case</Pill>
        <b>{noIssue}</b>
        <small>sites</small>
      </button>
      {selected.length > 0 && (
        <button className="text-btn" onClick={onClear}>
          Clear filter
        </button>
      )}
    </div>
  );
}

export function SiteTable({ rows, shownIds, selectedId, onSelect, onOpen }) {
  const list = shownIds ? rows.filter((r) => shownIds.has(r.id)) : rows;
  return (
    <div className="table-scroll">
      <table className="ops-table live-site-table">
        <thead>
          <tr>
            <th>Site</th>
            <th>Area</th>
            <th>Status</th>
            <th>Priority</th>
            <th>Open tickets</th>
            <th>Assignment</th>
            <th>Last update</th>
          </tr>
        </thead>
        <tbody>
          {list.map((r) => (
            <tr key={r.id} className={r.id === selectedId ? "is-selected" : ""}>
              <td>
                <button className="link-row" onClick={() => onSelect?.(r.id)}>
                  <b>{r.name}</b>
                </button>
                <small>
                  {r.segment === "business" ? "Business" : "Home"}
                  {r.mapped ? "" : " · "}
                  {!r.mapped && (
                    <>
                      <MapPinOff size={11} aria-hidden="true" /> unmapped
                    </>
                  )}
                </small>
              </td>
              <td>{r.area}</td>
              <td>
                <Pill tone={r.telemetry.tone}>{r.telemetry.label}</Pill>
                <small>{r.priority ? r.workflow : r.condition}</small>
              </td>
              <td>
                {r.priority ? <Pill tone={bandTone(r.priority)}>{r.priority}</Pill> : <span className="muted">—</span>}
              </td>
              <td>
                {r.tickets.length ? (
                  <ul className="site-tickets">
                    {r.tickets.map((t) => (
                      <li key={t.id}>
                        <button className="link-row" onClick={() => onOpen?.(t.id)}>
                          <Pill tone={bandTone(t.band)}>{t.band}</Pill> {t.title}
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <span className="muted">None</span>
                )}
              </td>
              <td>{r.crew || <span className="muted">{r.tickets.length ? "No crew yet" : "—"}</span>}</td>
              <td>
                {r.lastCase ? (
                  <>
                    {localDateTime(r.lastCase)}
                    <small>case updated</small>
                  </>
                ) : r.lastData ? (
                  <>
                    {localDateTime(r.lastData)}
                    <small>last data</small>
                  </>
                ) : (
                  <span className="muted">No data yet</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!list.length && <div className="empty">No sites match this filter.</div>}
    </div>
  );
}
