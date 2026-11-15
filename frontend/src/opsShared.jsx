// Small shared pieces of the connected operations pages: polling hook, error notice,
// modal dialog and pill. Kept apart so the lazily loaded ops modules share them.
import React, { useEffect, useState } from "react";
import { AlertTriangle, X } from "lucide-react";
import { poll } from "../../packages/contracts/client";
import { friendlyError, keepIfSame } from "./opsData";

export function Pill({ children, tone = "", title }) {
  return (
    <span className={`pill ${tone}`} title={title}>
      {children}
    </span>
  );
}

/**
 * Polls `load` every 5 s (shared `poll` cadence) while mounted. Unchanged data keeps
 * its reference. `key` restarts polling and clears data (e.g. another filter).
 * 401 goes to `onError` (returns true when handled); poll stops on 401/403/404.
 */
export function usePolled(load, key, onError) {
  const [state, setState] = useState({ key, data: null, error: null });
  const [tick, setTick] = useState(0);
  useEffect(
    () =>
      poll(
        load,
        (value) =>
          setState((previous) => {
            const data =
              previous.key === key ? keepIfSame(previous.data, value) : value;
            return previous.key === key &&
              data === previous.data &&
              !previous.error
              ? previous
              : { key, data, error: null };
          }),
        (error) => {
          if (!onError(error))
            setState((previous) => ({
              key,
              data: previous.key === key ? previous.data : null,
              error,
            }));
        },
      ),
    [key, tick],
  );
  const current = state.key === key ? state : { data: null, error: null };
  return {
    data: current.data,
    error: current.error,
    loading: current.data === null && !current.error,
    refresh: () => setTick((value) => value + 1),
  };
}

export function OpsNotice({ error, onRetry }) {
  if (!error) return null;
  return (
    <div role="alert" className="connected-error">
      <AlertTriangle size={19} />
      <div>
        <b>{friendlyError(error)}</b>
        {error.detail?.request_id && (
          <small>Request {error.detail.request_id}</small>
        )}
      </div>
      {onRetry && (
        <button className="text-btn" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Modal({ title, children, onClose, className = "" }) {
  useEffect(() => {
    const previous = document.activeElement;
    const handler = (event) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    document.querySelector(".modal .icon-btn")?.focus();
    return () => {
      document.removeEventListener("keydown", handler);
      previous?.focus?.();
    };
  }, []);
  return (
    <div className="overlay" onClick={onClose}>
      <section
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`modal wide ops-modal ${className}`}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="section-head">
          <h2>{title}</h2>
          <button
            className="icon-btn"
            aria-label="Close dialog"
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}

/** A fresh Idempotency-Key (one per user click; reused only to retry that click). */
export function newIdempotencyKey() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return `k-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}
