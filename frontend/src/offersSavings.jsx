// Savings/Earnings counter for customers (Home and the Offers page). The figures are
// the server's integer bani; the count-up animation is display only.
import React, { useEffect, useRef, useState } from "react";
import { ArrowRight, PiggyBank } from "lucide-react";
import { formatRon } from "./money";
import { savingsView, settledMore } from "./offersLogic";
import { t, tn } from "./offersText";
import { when } from "./telemetry";
import { OfferNotice, useCountUp, usePoller } from "./offersShared";

// Last summary seen per user, so moving between Home and Offers still animates a
// settlement that happened in between, and a remount alone never does.
const lastSeen = new Map();

export function SavingsCounter({ api, userId, onError, onOpenOffers, compact = false, nudge = 0 }) {
  const savings = usePoller((signal) => api.offerSavings(signal), {
    key: `savings:${userId}`,
    interval: 30000,
    focus: true,
    nudge,
    onError,
  });
  const summary = savings.data;
  const [animation, setAnimation] = useState(null);
  const [announce, setAnnounce] = useState("");
  const highlightTimer = useRef();
  useEffect(() => {
    if (!summary) return;
    const previous = lastSeen.get(userId);
    lastSeen.set(userId, summary);
    if (settledMore(previous, summary)) {
      setAnimation({ from: previous.lifetime_bani, to: summary.lifetime_bani, at: Date.now() });
      setAnnounce(t("savings.announce", { amount: formatRon(summary.lifetime_bani) }));
      clearTimeout(highlightTimer.current);
      highlightTimer.current = setTimeout(() => setAnimation(null), 2600);
    }
  }, [summary, userId]);
  useEffect(() => () => clearTimeout(highlightTimer.current), []);
  const target = summary?.lifetime_bani ?? 0;
  const shown = useCountUp(target, animation ? animation.from : target);
  const view = savingsView(summary);
  const negative = view.state === "negative";
  return (
    <section
      className={`solar-opportunity offer-savings ${compact ? "compact" : ""} ${animation ? "just-settled" : ""} ${negative ? "is-negative" : ""}`}
      aria-labelledby={`savings-${compact ? "home" : "offers"}`}
    >
      <div className="offer-savings-main">
        <span className="opportunity-icon" aria-hidden="true">
          <PiggyBank size={22} />
        </span>
        <div>
          <div className="eyebrow">{t("savings.eyebrow")}</div>
          <h2 id={`savings-${compact ? "home" : "offers"}`}>
            {view.state === "empty" || view.state === "loading" ? (
              view.headline
            ) : (
              <>
                <span className="offer-savings-number">{formatRon(shown)}</span>
                <span className="offer-savings-headline">{view.headline}</span>
              </>
            )}
          </h2>
          {view.state === "empty" && <p className="offer-savings-body">{view.body}</p>}
          {summary && summary.settled_count > 0 && (
            <p className="offer-savings-body">
              {tn("savings.settled", summary.settled_count, {
                time: when(summary.last_settled_at),
              })}
            </p>
          )}
        </div>
        {onOpenOffers && (
          <button className="btn dark" onClick={onOpenOffers}>
            {t("savings.see")} <ArrowRight size={16} />
          </button>
        )}
      </div>
      {summary && summary.settled_count > 0 && (
        <dl className="offer-savings-breakdown">
          <div>
            <dt>{t("savings.thisMonth")}</dt>
            <dd>{formatRon(summary.this_month_bani)}</dd>
          </div>
          <div>
            <dt>{t("savings.lifetime")}</dt>
            <dd>{formatRon(summary.lifetime_bani)}</dd>
          </div>
          <div>
            <dt>{t("savings.penalties")}</dt>
            <dd>{formatRon(summary.penalties_paid_bani)}</dd>
          </div>
          <div>
            <dt>{t("savings.consume")}</dt>
            <dd>{formatRon(summary.consume_bani)}</dd>
          </div>
          <div>
            <dt>{t("savings.export")}</dt>
            <dd>{formatRon(summary.export_bani)}</dd>
          </div>
        </dl>
      )}
      {!compact && summary && summary.settled_count > 0 && (
        <p className="small-note">{t("savings.basis")}</p>
      )}
      <OfferNotice error={savings.error} onRetry={savings.refresh} />
      <span className="visually-hidden" aria-live="polite">
        {announce}
      </span>
    </section>
  );
}
