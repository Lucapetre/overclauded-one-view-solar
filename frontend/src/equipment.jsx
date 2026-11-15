// Connected customer workspace: replay indicator and the three equipment evidence
// cards (Grid, Battery, Solar conditions). Data come from the API only; a failure is
// shown as such, never replaced by sample values.
import React, { useState } from "react";
import {
  AlertTriangle,
  BatteryCharging,
  CheckCircle2,
  Clock3,
  History,
  Info,
  Plug,
  SunMedium,
} from "lucide-react";
import { SolarApiError } from "../../packages/contracts/client";
import { usePoller } from "./offersShared";
import { FAMILY_ORDER, evidenceLabel, familyCard, hasEquipment } from "./equipmentView";
import { localDateTime, planErrorText, replayBadge } from "./planView";
import "./equipment.css";

/** Conspicuous replay/scenario indicator; renders nothing in live mode. */
export function ReplayBadge({ clock }) {
  const badge = replayBadge(clock);
  if (!badge) return null;
  return (
    <div className="replay-badge" role="status" aria-live="polite" title={badge.detail}>
      <History size={16} aria-hidden="true" />
      <b>{badge.text}</b>
      <span className="replay-scenario">Scenario {badge.scenario}</span>
      <span className="visually-hidden">{badge.detail}</span>
    </div>
  );
}

const ICONS = { meter: Plug, battery: BatteryCharging, weather: SunMedium };
const STATE_ICONS = { ok: CheckCircle2, limited: Info, stale: Clock3, partial: AlertTriangle, not_installed: Info };

function EvidenceDetails({ card }) {
  return (
    <details className="evidence-details">
      <summary>Why? Show the evidence</summary>
      {card.measured.length > 0 && (
        <>
          <h4>Measured</h4>
          <ul>
            {card.measured.map((item) => (
              <li key={item.evidence_id}>
                {item.text.label}: <b>{item.text.value} {item.text.unit}</b>
                <small>
                  {item.aggregation === "mean" ? "15-minute average" : "last reading"} ending{" "}
                  {localDateTime(item.frame_end)} · coverage {Math.round(item.coverage_ratio * 100)} % · synthetic observation
                </small>
              </li>
            ))}
          </ul>
        </>
      )}
      {card.derived.length > 0 && (
        <>
          <h4>Derived or estimated</h4>
          <ul>
            {card.derived.map((item) => (
              <li key={item.evidence_id}>
                {item.text.label}: <b>{item.text.value} {item.text.unit}</b>
                <small>{item.origin}</small>
              </li>
            ))}
          </ul>
        </>
      )}
      {card.assumptions.length > 0 && (
        <>
          <h4>Assumptions and configuration</h4>
          <ul>
            {card.assumptions.map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
        </>
      )}
      {card.declared.length > 0 && (
        <>
          <h4>What this device can report</h4>
          <ul>
            {card.declared.map((item) => (
              <li key={item.name}>
                {item.name}: {item.state}
              </li>
            ))}
          </ul>
        </>
      )}
      <details className="technical-details">
        <summary>Technical details</summary>
        <dl>
          <dt>Source family</dt>
          <dd>{card.family}</dd>
          {card.technical.asset_id && (
            <>
              <dt>Selected device</dt>
              <dd>{card.technical.asset_id}</dd>
              <dt>Profile</dt>
              <dd>{card.technical.profile_id}</dd>
              <dt>Boundary</dt>
              <dd>{card.technical.boundary || "not stated"}</dd>
            </>
          )}
          <dt>Evidence ids</dt>
          <dd>
            {card.technical.evidence_ids.length ? (
              <ul className="evidence-ids">
                {[...new Set(card.technical.evidence_ids)].map((id) => (
                  <li key={id}>
                    <code>{id}</code>
                  </li>
                ))}
              </ul>
            ) : (
              "none"
            )}
          </dd>
        </dl>
      </details>
    </details>
  );
}

function EvidenceCard({ card }) {
  const Icon = ICONS[card.family];
  const StateIcon = STATE_ICONS[card.state] || Info;
  return (
    <section className={`card evidence-card state-${card.state}`} aria-labelledby={`evidence-${card.family}`}>
      <div className="evidence-head">
        <span className="evidence-icon" aria-hidden="true">
          <Icon size={18} />
        </span>
        <h3 id={`evidence-${card.family}`}>{card.title}</h3>
        <span className={`pill ${card.tone}`}>
          <StateIcon size={11} aria-hidden="true" />
          {card.label}
        </span>
      </div>
      <p className="evidence-device">{card.device}</p>
      {card.primary ? (
        <div className="evidence-value">
          <span>{card.primary.text.label}</span>
          <b>
            {card.primary.text.value} <small>{card.primary.text.unit}</small>
          </b>
        </div>
      ) : (
        card.state !== "not_installed" && <p className="evidence-value missing">No recent value</p>
      )}
      {card.secondary.length > 0 && (
        <ul className="evidence-secondary">
          {card.secondary.map((item) => (
            <li key={item.evidence_id}>{item.text.sentence}</li>
          ))}
        </ul>
      )}
      {card.state !== "not_installed" && (
        <p className="evidence-time">
          <Clock3 size={12} aria-hidden="true" /> Last update {card.lastUpdate || "unknown"}
          {card.age && ` · ${card.age}`}
        </p>
      )}
      {card.reasons.length > 0 && (
        <ul className={`evidence-reasons ${card.capabilityAvailable === false ? "limited" : ""}`}>
          {card.reasons.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      )}
      {card.state !== "not_installed" && <EvidenceDetails card={card} />}
    </section>
  );
}

/**
 * Grid / Battery / Solar conditions for one site. `nudge` refetches (e.g. when the
 * replay clock moves); otherwise it refreshes every 30 s.
 */
export function EquipmentCards({ api, siteId, onError, nudge = 0 }) {
  const { data, error, loading, refresh } = usePoller((signal) => api.equipmentSummary(siteId, signal), {
    key: siteId,
    interval: 30000,
    nudge,
    onError,
  });
  const [open, setOpen] = useState(false);
  if (loading)
    return (
      <section className="evidence-strip" aria-busy="true">
        <p className="muted">Loading equipment evidence…</p>
      </section>
    );
  if (!data && error) {
    const denied = error instanceof SolarApiError && [403, 404].includes(error.status);
    return (
      <section className="evidence-strip">
        <div role="alert" className="connected-error">
          <AlertTriangle size={19} />
          <div>
            <b>{denied ? "Equipment data for this site are not available to your account." : "Equipment evidence could not be loaded."}</b>
            <small>{denied ? "Ask your administrator if this looks wrong." : planErrorText(error)}</small>
          </div>
          {!denied && (
            <button className="text-btn" onClick={refresh}>
              Retry
            </button>
          )}
        </div>
      </section>
    );
  }
  if (!hasEquipment(data))
    return (
      <p className="evidence-none">
        <Info size={14} aria-hidden="true" /> No connected equipment data for this site.
      </p>
    );
  const cards = FAMILY_ORDER.map((family) => familyCard(data, family));
  return (
    <section className="evidence-strip" aria-label="Equipment evidence">
      <div className="evidence-strip-head">
        <h2>Your equipment, right now</h2>
        <span className="pill yellow">{evidenceLabel(data)}</span>
        <button className="text-btn" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? "Hide note" : "About these readings"}
        </button>
      </div>
      {open && <p className="small-note">{data.label} Times are Europe/Bucharest; freshness is judged at {localDateTime(data.as_of)}.</p>}
      {error && (
        <p className="error" role="status">
          Refresh failed ({planErrorText(error)}); the values below may be older.
        </p>
      )}
      <div className="evidence-grid">
        {cards.map((card) => (
          <EvidenceCard key={card.family} card={card} />
        ))}
      </div>
    </section>
  );
}
