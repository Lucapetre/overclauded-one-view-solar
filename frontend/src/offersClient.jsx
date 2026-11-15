// Customer "Offers" page: savings counter, available offers with an honest
// acceptance screen, running offers with live progress, and settled history.
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  CheckCircle2,
  Clock,
  Handshake,
  Info,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { formatKwh, formatPercent, formatPrice, formatRon, ratio } from "./money";
import {
  ACCEPT_REFRESH_CODES,
  capacityText,
  countdown,
  durationText,
  expectedOutcome,
  meterDelayed,
  offerTitle,
  outcomeLabel,
  outcomeTone,
  referenceText,
  relativeUntil,
  siteBlocker,
  typeLabel,
  waiverText,
  windowEndIfAccepted,
  windowPhase,
} from "./offersLogic";
import { t } from "./offersText";
import { when } from "./telemetry";
import {
  Fact,
  OfferDialog,
  OfferNotice,
  Pill,
  newIdempotencyKey,
  offerErrorText,
  prefersReducedMotion,
  useNow,
  usePoller,
} from "./offersShared";
import { SavingsCounter } from "./offersSavings";

function TypePill({ type }) {
  const Icon = type === "export" ? ArrowUpFromLine : ArrowDownToLine;
  return (
    <span className={`pill offer-type ${type}`}>
      <Icon size={12} aria-hidden="true" />
      {typeLabel(type)}
    </span>
  );
}

function PenaltyBox({ rule, maxPenaltyBani, label = t("offer.penalty") }) {
  return (
    <div className="offer-penalty">
      <TriangleAlert size={16} aria-hidden="true" />
      <div>
        <b>{label}</b>
        <p>{rule}</p>
        <p className="offer-penalty-max">
          {t("offer.maxPenalty", { amount: formatRon(maxPenaltyBani) })}
        </p>
      </div>
    </div>
  );
}

function OfferCard({ offer, now, onReview, highlighted }) {
  const full = offer.remaining_capacity?.full;
  return (
    <article
      id={`offer-${offer.offer_id}`}
      tabIndex={-1}
      className={`card offer-card ${highlighted ? "offer-highlight" : ""}`}
    >
      <div className="section-head">
        <TypePill type={offer.type} />
        <Pill tone={full ? "orange" : ""}>{capacityText(offer.remaining_capacity)}</Pill>
      </div>
      <h3>{offerTitle(offer)}</h3>
      <div className="offer-facts">
        <Fact label={t("offer.block")}>{formatKwh(offer.energy_kwh)}</Fact>
        <Fact label={t("offer.price")}>{formatPrice(offer.offer_price_ron_per_kwh)}</Fact>
        <Fact label={t("offer.window")}>
          {t("offer.window.value", { duration: durationText(offer.window_minutes) })}
        </Fact>
        <Fact label={t("offer.expires")}>
          {t("offer.expires.value", {
            relative: relativeUntil(offer.offer_expires_at, now),
            time: when(offer.offer_expires_at),
          })}
        </Fact>
      </div>
      <p className="offer-value">
        {t(`offer.blockValue.${offer.type}`, { amount: formatRon(offer.block_value_bani) })}
      </p>
      <PenaltyBox rule={offer.penalty_rule_text} maxPenaltyBani={offer.max_penalty_bani} />
      <button className="btn yellow full" disabled={full} onClick={() => onReview(offer)}>
        {full ? t("offer.full") : t("offer.review")}
        <Handshake size={17} />
      </button>
    </article>
  );
}

function SiteSummary({ offer, site }) {
  const blocker = siteBlocker(offer.type, site);
  return (
    <>
      <Fact label={t("accept.reference")}>{referenceText(site)}</Fact>
      <Fact label={t("accept.expected")}>
        <span className={site.savings_if_completed_bani < 0 ? "offer-negative" : ""}>
          {expectedOutcome(offer.type, site.savings_if_completed_bani)}
        </span>
      </Fact>
      {blocker && (
        <p className="offer-blocker" role="note">
          <Info size={14} aria-hidden="true" /> {blocker}
        </p>
      )}
    </>
  );
}

function AcceptDialog({ api, offer, onClose, onAccepted, onStale, onError }) {
  const [idempotencyKey] = useState(newIdempotencyKey);
  const sites = offer.eligible_sites || [];
  const [siteId, setSiteId] = useState(sites.length === 1 ? sites[0].site_id : "");
  const [understood, setUnderstood] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const now = useNow(15000);
  const site = sites.find((item) => item.site_id === siteId);
  const blocked = site ? Boolean(siteBlocker(offer.type, site)) : true;
  async function accept() {
    setBusy(true);
    setError(null);
    try {
      // The same key on every retry from this screen: a repeat returns the original.
      const result = await api.acceptOffer(offer.offer_id, siteId || undefined, idempotencyKey);
      onAccepted(result);
    } catch (failure) {
      if (onError(failure)) return;
      setError(failure);
      if (ACCEPT_REFRESH_CODES.has(failure?.detail?.code)) onStale();
    } finally {
      setBusy(false);
    }
  }
  return (
    <OfferDialog title={t("accept.title")} onClose={onClose} busy={busy} wide>
      <div className="offer-accept">
        <div className="offer-accept-head">
          <TypePill type={offer.type} />
          <h3>{offerTitle(offer)}</h3>
        </div>
        <p className="small-note">
          <ShieldCheck size={14} aria-hidden="true" /> {t("accept.noPressure")}
        </p>
        <section className="offer-commit" aria-labelledby="offer-commit-title">
          <h4 id="offer-commit-title">{t("accept.commit")}</h4>
          <p>{offer.terms_text}</p>
        </section>
        <div className="offer-facts">
          <Fact label={t("accept.price")}>{formatPrice(offer.offer_price_ron_per_kwh)}</Fact>
          <Fact label={t("offer.block")}>
            {formatKwh(offer.energy_kwh)} ·{" "}
            {t(`offer.blockValue.${offer.type}`, { amount: formatRon(offer.block_value_bani) })}
          </Fact>
          <Fact label={t("accept.window")}>
            {t("accept.window.value", {
              duration: durationText(offer.window_minutes),
              end: when(windowEndIfAccepted(offer.window_minutes, now)),
            })}
          </Fact>
        </div>
        <div className="offer-penalty strong">
          <TriangleAlert size={16} aria-hidden="true" />
          <div>
            <b>{t("accept.penalty")}</b>
            <p>{offer.penalty_rule_text}</p>
            <p className="offer-penalty-max">
              {t("accept.maxPenalty", { amount: formatRon(offer.max_penalty_bani) })}
            </p>
          </div>
        </div>
        {sites.length > 1 ? (
          <fieldset className="offer-sites">
            <legend>{t("accept.site.choose")}</legend>
            {sites.map((item) => (
              <label
                key={item.site_id}
                className={`offer-site ${siteId === item.site_id ? "selected" : ""}`}
              >
                <input
                  type="radio"
                  name="offer-site"
                  value={item.site_id}
                  checked={siteId === item.site_id}
                  onChange={() => setSiteId(item.site_id)}
                />
                <span>
                  <b>{item.alias}</b>
                  <SiteSummary offer={offer} site={item} />
                </span>
              </label>
            ))}
          </fieldset>
        ) : (
          site && (
            <div className="offer-facts">
              <Fact label={t("accept.site")}>{site.alias}</Fact>
              <SiteSummary offer={offer} site={site} />
            </div>
          )
        )}
        <label className="offer-confirm">
          <input
            type="checkbox"
            checked={understood}
            onChange={(event) => setUnderstood(event.target.checked)}
          />
          <span>{t("accept.understand", { verb: t(`type.${offer.type}.verb`) })}</span>
        </label>
        <OfferNotice error={error} text={error ? offerErrorText(error) : undefined} />
        <div className="offer-actions">
          <button className="btn secondary" onClick={onClose} disabled={busy}>
            {t("common.cancel")}
          </button>
          <button
            className="btn yellow"
            onClick={accept}
            disabled={!understood || !site || blocked || busy}
            aria-busy={busy}
          >
            {busy ? t("accept.sending") : t("accept.confirm")}
          </button>
        </div>
      </div>
    </OfferDialog>
  );
}

function ProgressBar({ value, label }) {
  const percent = Math.round(value * 100);
  return (
    <div
      className="offer-progress"
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent}
      aria-label={label}
    >
      <i style={{ width: `${percent}%` }} />
    </div>
  );
}

function ActiveOfferCard({ offer, now, highlighted }) {
  const phase = windowPhase(offer, now);
  const timer = countdown(offer.window_end, now);
  const delayed = meterDelayed(offer, now);
  const share = ratio(offer.metered_kwh, offer.energy_kwh);
  const progressText = t(`progress.${offer.type}`, {
    done: formatKwh(offer.metered_kwh),
    block: formatKwh(offer.energy_kwh),
  });
  const delivered = Number(offer.remaining_kwh) <= 0;
  return (
    <article
      id={`user-offer-${offer.user_offer_id}`}
      tabIndex={-1}
      className={`card offer-active ${highlighted ? "offer-highlight" : ""}`}
    >
      <div className="section-head">
        <div>
          <TypePill type={offer.type} />
          <h3>{offerTitle(offer)}</h3>
          <small className="offer-site-name">{offer.site_alias}</small>
        </div>
        <Pill tone={offer.status === "active" ? "green" : ""}>{outcomeLabel(offer.status)}</Pill>
      </div>
      <div className="offer-active-grid">
        <div>
          <div className="offer-progress-label">
            <b>{progressText}</b>
            <span>
              {delivered
                ? t("progress.complete")
                : t("progress.remaining", { kwh: formatKwh(offer.remaining_kwh) })}
            </span>
          </div>
          <ProgressBar value={share} label={progressText} />
          <small>
            {t("meter.coverage", { percent: formatPercent(offer.coverage_ratio) })}
          </small>
        </div>
        <div className="offer-countdown" aria-live="off">
          <Clock size={18} aria-hidden="true" />
          {phase === "running" ? (
            <div>
              <span>{t("countdown.left")}</span>
              <b className="offer-timer">{timer.text}</b>
              <small>{t("countdown.endsAt", { time: when(offer.window_end) })}</small>
            </div>
          ) : (
            <div>
              <b>{t("countdown.settling")}</b>
              <small>{t("countdown.ended", { time: when(offer.window_end) })}</small>
            </div>
          )}
        </div>
      </div>
      {delayed && (
        <p className="offer-warning" role="status">
          <Info size={15} aria-hidden="true" /> {t("meter.delayed")}
        </p>
      )}
      <div className="offer-projection">
        <b>
          {offer.projected_penalty_bani > 0
            ? t("projected.penalty", { amount: formatRon(offer.projected_penalty_bani) })
            : t("projected.none")}
        </b>
        <span>{t("projected.max", { amount: formatRon(offer.max_penalty_bani) })}</span>
      </div>
      <p className="offer-rule">{offer.penalty_rule_text}</p>
    </article>
  );
}

function HistoryRow({ offer, highlighted }) {
  const s = offer.settlement;
  const waived = s.penalty_waived_reason;
  return (
    <li
      id={`user-offer-${offer.user_offer_id}`}
      tabIndex={-1}
      className={`offer-history-row ${highlighted ? "offer-highlight" : ""}`}
    >
      <div className="offer-history-what">
        <Pill tone={outcomeTone(offer.status)}>
          {offer.status === "completed" && <CheckCircle2 size={12} aria-hidden="true" />}
          {outcomeLabel(offer.status)}
        </Pill>
        <b>{offerTitle(offer)}</b>
        <small>
          {typeLabel(offer.type)} · {offer.site_alias} ·{" "}
          {t("history.settled", { time: when(s.settled_at) })}
        </small>
      </div>
      <dl className="offer-history-figures">
        <div>
          <dt>{t("offer.block")}</dt>
          <dd>
            {t("history.delivered", {
              done: formatKwh(s.fulfilled_kwh),
              block: formatKwh(offer.energy_kwh),
            })}
          </dd>
        </div>
        <div>
          <dt>{t("history.penalty")}</dt>
          <dd>
            {waived
              ? t("history.penalty.waived", { reason: waiverText(waived) })
              : s.penalty_bani
                ? formatRon(s.penalty_bani)
                : t("history.penalty.none")}
          </dd>
        </div>
        <div>
          <dt>{t(s.direction === "credit" ? "history.credit" : "history.charge")}</dt>
          <dd>{formatRon(s.amount_bani)}</dd>
        </div>
        <div>
          <dt>{t(`history.saving.${offer.type}`)}</dt>
          <dd className={s.savings_bani < 0 ? "offer-negative" : "offer-positive"}>
            {formatRon(s.savings_bani, { signed: true })}
          </dd>
        </div>
      </dl>
    </li>
  );
}

export function OffersPage({ api, user, onError, focus, onFocusHandled, onActivity }) {
  const available = usePoller((signal) => api.offers(signal), {
    key: `offers:${user.user_id}`,
    interval: 30000,
    focus: true,
    onError,
  });
  const mine = usePoller(
    async (signal) => {
      const [active, history] = await Promise.all([
        api.myOffers("active", signal),
        api.myOffers("history", signal),
      ]);
      return { active, history };
    },
    { key: `mine:${user.user_id}`, interval: 30000, focus: true, onError },
  );
  const [reviewing, setReviewing] = useState(null);
  const [notice, setNotice] = useState("");
  const [highlight, setHighlight] = useState(null);
  const [savingsNudge, setSavingsNudge] = useState(0);
  const active = mine.data?.active || [];
  const history = mine.data?.history || [];
  const now = useNow(1000, active.length > 0 || Boolean(available.data?.length));

  // A newly settled offer: refresh the counter right away so it animates.
  const settledCount = useRef(null);
  useEffect(() => {
    if (!mine.data) return;
    if (settledCount.current !== null && history.length > settledCount.current)
      setSavingsNudge((value) => value + 1);
    settledCount.current = history.length;
  }, [mine.data]);

  // Notification links: highlight the offer or the user offer once data is in.
  useEffect(() => {
    if (!focus || !available.data || !mine.data) return;
    const all = [...active, ...history];
    let target = null;
    if (focus.kind === "userOffer") target = `user-offer-${focus.id}`;
    else if (available.data.some((offer) => offer.offer_id === focus.id))
      target = `offer-${focus.id}`;
    else {
      const taken = all.find((item) => item.offer_id === focus.id);
      if (taken) target = `user-offer-${taken.user_offer_id}`;
    }
    onFocusHandled?.();
    if (!target) return;
    setHighlight(target);
    requestAnimationFrame(() => {
      const element = document.getElementById(target);
      element?.scrollIntoView({
        block: "center",
        behavior: prefersReducedMotion() ? "auto" : "smooth",
      });
      element?.focus({ preventScroll: true });
    });
    const timer = setTimeout(() => setHighlight(null), 4000);
    return () => clearTimeout(timer);
  }, [focus, available.data, mine.data]);

  function accepted(result) {
    setReviewing(null);
    setNotice(t("accept.done"));
    available.refresh();
    mine.refresh();
    onActivity?.();
    setHighlight(`user-offer-${result.user_offer_id}`);
    setTimeout(() => {
      document.getElementById(`user-offer-${result.user_offer_id}`)?.scrollIntoView({
        block: "center",
        behavior: prefersReducedMotion() ? "auto" : "smooth",
      });
    }, 400);
  }

  const offers = useMemo(() => available.data || [], [available.data]);
  return (
    <div className="offers-page">
      <SavingsCounter api={api} userId={user.user_id} onError={onError} nudge={savingsNudge} />
      {notice && (
        <p className="offer-success" role="status">
          <CheckCircle2 size={16} aria-hidden="true" /> {notice}
        </p>
      )}
      <section className="card mt offer-section" aria-labelledby="offers-mine">
        <div className="section-head">
          <div>
            <div className="eyebrow">{t("mine.title").toUpperCase()}</div>
            <h2 id="offers-mine">{t("mine.activeTitle")}</h2>
          </div>
          <Pill>{mine.data ? active.length : t("common.loading")}</Pill>
        </div>
        <OfferNotice error={mine.error} onRetry={mine.refresh} />
        {mine.data && !active.length && <p className="muted">{t("mine.active.empty")}</p>}
        <div className="offer-active-list">
          {active.map((offer) => (
            <ActiveOfferCard
              key={offer.user_offer_id}
              offer={offer}
              now={now}
              highlighted={highlight === `user-offer-${offer.user_offer_id}`}
            />
          ))}
        </div>
      </section>
      <section className="card mt offer-section" aria-labelledby="offers-available">
        <div className="section-head">
          <div>
            <h2 id="offers-available">{t("available.title")}</h2>
            <p>{t("available.lead")}</p>
          </div>
          <Pill>{available.data ? offers.length : t("common.loading")}</Pill>
        </div>
        <OfferNotice error={available.error} onRetry={available.refresh} />
        {available.data && !offers.length && (
          <div className="empty">
            <Handshake size={32} />
            <h3>{t("available.empty.title")}</h3>
            <p>{t("available.empty.body")}</p>
          </div>
        )}
        <div className="offer-grid">
          {offers.map((offer) => (
            <OfferCard
              key={offer.offer_id}
              offer={offer}
              now={now}
              onReview={(item) => {
                setNotice("");
                setReviewing(item);
              }}
              highlighted={highlight === `offer-${offer.offer_id}`}
            />
          ))}
        </div>
      </section>
      <section className="card mt offer-section" aria-labelledby="offers-history">
        <div className="section-head">
          <div>
            <h2 id="offers-history">{t("mine.historyTitle")}</h2>
            <p>{t("common.synthetic")}</p>
          </div>
        </div>
        {mine.data && !history.length && <p className="muted">{t("mine.history.empty")}</p>}
        {history.length > 0 && (
          <ul className="offer-history">
            {history.map((offer) => (
              <HistoryRow
                key={offer.user_offer_id}
                offer={offer}
                highlighted={highlight === `user-offer-${offer.user_offer_id}`}
              />
            ))}
          </ul>
        )}
      </section>
      {reviewing && (
        <AcceptDialog
          key={reviewing.offer_id}
          api={api}
          offer={reviewing}
          onClose={() => setReviewing(null)}
          onAccepted={accepted}
          onStale={() => {
            available.refresh();
            mine.refresh();
          }}
          onError={onError}
        />
      )}
    </div>
  );
}
