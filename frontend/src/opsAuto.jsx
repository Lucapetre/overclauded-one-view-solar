// "Assign by severity": the original automation for simple cases (customer requests and
// legacy incidents). Gives each open case, P0 first, to the first eligible free crew.
import React, { useState } from "react";
import { ArrowRight } from "lucide-react";
import { friendlyError, shortId, skipReason } from "./opsData";

export function AutoDispatch({ api, labels, onDone, onError, onResult, compact = false }) {
  const [busy, setBusy] = useState(false),
    [result, setResult] = useState(null),
    [error, setError] = useState(null);
  async function run() {
    setBusy(true);
    setError(null);
    try {
      const value = await api.autoDispatch();
      setResult(value);
      onResult?.(value);
      onDone?.();
    } catch (failure) {
      if (!onError(failure)) setError(failure);
    } finally {
      setBusy(false);
    }
  }
  const label = (id, tier) => labels[id] || `${tier} · ${shortId(id)}`;
  return (
    <div className={`ops-auto${compact ? " is-compact" : ""}`}>
      <button
        className={compact ? "btn secondary" : "btn yellow"}
        onClick={run}
        disabled={busy}
        title="Gives each simple open case, P0 first, to the first eligible free crew. Correlated cases go through the plan."
      >
        {busy ? "Assigning…" : "Assign by severity"} <ArrowRight size={16} />
      </button>
      {error && <p className="error">{friendlyError(error)}</p>}
      {result && (
        <div className="info-box ops-result" role="status">
          <b>
            Assigned {result.assigned.length} · skipped {result.skipped.length}
          </b>
          {result.assigned.length > 0 && (
            <ul>
              {result.assigned.map((a) => (
                <li key={a.incident_id}>
                  ✓ {label(a.incident_id, a.tier)} → <b>{a.crew_name}</b>
                </li>
              ))}
            </ul>
          )}
          {result.skipped.length > 0 && (
            <ul>
              {result.skipped.map((s) => (
                <li key={s.incident_id}>
                  – Not assigned: {label(s.incident_id, s.tier)}, because{" "}
                  {skipReason(s.reason)}.
                </li>
              ))}
            </ul>
          )}
          {!result.assigned.length && !result.skipped.length && (
            <p>Every open incident in your scope already has a crew.</p>
          )}
          <p className="small-note">
            Demo only: no real team was contacted.
          </p>
        </div>
      )}
    </div>
  );
}
