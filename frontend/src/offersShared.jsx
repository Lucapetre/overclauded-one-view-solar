// Shared React pieces for the Power Block Offers screens: polling with a custom
// interval and refetch on focus, a ticking clock, an accessible dialog, the
// count-up animation and small presentational helpers.
import React, { useEffect, useRef, useState } from "react";
import { AlertTriangle, X } from "lucide-react";
import { SolarApiError } from "../../packages/contracts/client";
import { friendlyError, keepIfSame } from "./opsData";
import { acceptErrorText, managerErrorText } from "./offersLogic";
import { t } from "./offersText";
import "./offers.css";

/**
 * Loads now, then every `interval` ms while mounted (and on window focus when
 * `focus`). Unchanged data keeps its reference. Changing `key` clears the data;
 * changing `nudge` refetches without clearing. A 401 goes to `onError` (returns
 * true when handled) and stops polling, as do 403 and 404.
 */
export function usePoller(load, { key = "", interval = 30000, focus = false, nudge = 0, onError }) {
  const [state, setState] = useState({ key, data: null, error: null });
  const loadRef = useRef(load);
  const errorRef = useRef(onError);
  const runRef = useRef(() => {});
  loadRef.current = load;
  errorRef.current = onError;
  useEffect(() => {
    const controller = new AbortController();
    let timer;
    let busy = false;
    let again = false;
    let stopped = false;
    const run = async () => {
      if (stopped || controller.signal.aborted) return;
      if (busy) {
        again = true; // a refetch was asked for while loading: run once more after
        return;
      }
      busy = true;
      again = false;
      clearTimeout(timer);
      try {
        const value = await loadRef.current(controller.signal);
        if (controller.signal.aborted) return;
        setState((previous) => {
          const data = previous.key === key ? keepIfSame(previous.data, value) : value;
          return previous.key === key && data === previous.data && !previous.error
            ? previous
            : { key, data, error: null };
        });
      } catch (error) {
        if (controller.signal.aborted) return;
        if (errorRef.current?.(error)) {
          stopped = true;
          return;
        }
        if (error instanceof SolarApiError && [403, 404].includes(error.status)) stopped = true;
        setState((previous) => ({
          key,
          data: previous.key === key ? previous.data : null,
          error,
        }));
      } finally {
        busy = false;
        if (!controller.signal.aborted && !stopped)
          timer = again ? setTimeout(run, 0) : setTimeout(run, interval);
      }
    };
    runRef.current = run;
    run();
    const onFocus = () => {
      if (document.visibilityState !== "hidden") run();
    };
    if (focus) {
      window.addEventListener("focus", onFocus);
      document.addEventListener("visibilitychange", onFocus);
    }
    return () => {
      controller.abort();
      clearTimeout(timer);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onFocus);
    };
  }, [key, interval, focus]);
  useEffect(() => {
    if (nudge) runRef.current();
  }, [nudge]);
  const current = state.key === key ? state : { data: null, error: null };
  return {
    data: current.data,
    error: current.error,
    loading: current.data === null && !current.error,
    refresh: () => runRef.current(),
  };
}

/** Current time in ms, re-rendering every `every` ms while `active`. */
export function useNow(every = 1000, active = true) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), every);
    return () => clearInterval(id);
  }, [every, active]);
  return now;
}

export const prefersReducedMotion = () =>
  typeof window !== "undefined" &&
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/**
 * Count-up from `from` to `to` (integers, e.g. bani) with requestAnimationFrame.
 * Jumps straight to `to` when reduced motion is preferred. Returns the shown value.
 */
export function useCountUp(to, from, duration = 1400) {
  const [value, setValue] = useState(to);
  useEffect(() => {
    if (!Number.isFinite(to)) return;
    if (!Number.isFinite(from) || from === to || prefersReducedMotion()) {
      setValue(to);
      return;
    }
    let frame;
    const start = performance.now();
    const step = (time) => {
      const progress = Math.min(1, (time - start) / duration);
      const eased = 1 - (1 - progress) ** 3;
      setValue(Math.round(from + (to - from) * eased));
      if (progress < 1) frame = requestAnimationFrame(step);
    };
    setValue(from);
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [to, from, duration]);
  return value;
}

export function Pill({ children, tone = "" }) {
  return <span className={`pill ${tone}`}>{children}</span>;
}

/** Offer-aware error text: known offer codes first, then the app's general wording. */
export function offerErrorText(error) {
  return acceptErrorText(error) || managerErrorText(error) || friendlyError(error);
}

export function OfferNotice({ error, onRetry, text }) {
  if (!error) return null;
  return (
    <div role="alert" className="connected-error">
      <AlertTriangle size={19} />
      <div>
        <b>{text || offerErrorText(error)}</b>
        {error.detail?.request_id && <small>Request {error.detail.request_id}</small>}
      </div>
      {onRetry && (
        <button className="text-btn" onClick={onRetry}>
          {t("common.retry")}
        </button>
      )}
    </div>
  );
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Accessible dialog: focus moves into it, Tab stays inside, Escape closes (unless
 * `busy`), and focus returns to where it was on close.
 */
export function OfferDialog({ title, children, onClose, busy = false, wide = false, className = "" }) {
  const ref = useRef(null);
  const closeRef = useRef(onClose);
  const busyRef = useRef(busy);
  closeRef.current = onClose;
  busyRef.current = busy;
  useEffect(() => {
    const previous = document.activeElement;
    ref.current?.focus();
    const handler = (event) => {
      if (event.key === "Escape" && !busyRef.current) {
        event.stopPropagation();
        closeRef.current();
      }
      if (event.key === "Tab" && ref.current) {
        const items = [...ref.current.querySelectorAll(FOCUSABLE)];
        if (!items.length) return;
        const first = items[0],
          last = items.at(-1);
        if (event.shiftKey && (document.activeElement === first || document.activeElement === ref.current)) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", handler);
    return () => {
      document.removeEventListener("keydown", handler);
      previous?.focus?.();
    };
  }, []);
  return (
    <div className="overlay" onClick={() => !busy && onClose()}>
      <section
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby="offer-dialog-title"
        tabIndex={-1}
        className={`modal ${wide ? "wide" : ""} offer-dialog ${className}`}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="section-head">
          <h2 id="offer-dialog-title">{title}</h2>
          <button
            className="icon-btn"
            aria-label={t("common.close")}
            onClick={onClose}
            disabled={busy}
          >
            <X size={20} />
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}

/** One label/value fact in an offer card or dialog. */
export function Fact({ label, children }) {
  return (
    <div className="offer-fact">
      <span>{label}</span>
      <b>{children}</b>
    </div>
  );
}

/** A random key per opened acceptance screen (crypto.randomUUID when available). */
export function newIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  return [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
}
