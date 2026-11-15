// Manager (supervisor) "Offers" area: dashboard list with totals, offer builder with a
// debounced audience preview, publish/cancel confirmations, and offer detail with
// takers and the audit log. Loaded lazily, like the other staff pages.
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  Ban,
  Lock,
  Pencil,
  Plus,
  Search,
  Send,
} from "lucide-react";
import { formatKwh, formatPercent, formatPrice, formatRon } from "./money";
import {
  WINDOW_PRESETS,
  auditAction,
  auditLines,
  defaultForm,
  draftKey,
  durationText,
  formFromOffer,
  formToDraft,
  offerStatusLabel,
  offerStatusTone,
  offerTitle,
  offerTotals,
  outcomeLabel,
  outcomeTone,
  penaltyPreviewText,
  typeLabel,
} from "./offersLogic";
import { t, tn } from "./offersText";
import { when } from "./telemetry";
import { shortId } from "./opsData";
import { Fact, OfferDialog, OfferNotice, Pill, usePoller } from "./offersShared";

const areaLabel = (aliases, id) => aliases[id] || id || "—";

function StatusPill({ offer }) {
  return (
    <span className="offer-status-pills">
      <Pill tone={offerStatusTone(offer.status)}>{offerStatusLabel(offer.status)}</Pill>
      {offer.locked && (
        <Pill>
          <Lock size={11} aria-hidden="true" /> {t("manager.locked")}
        </Pill>
      )}
    </span>
  );
}

/* --------------------------------------------------------------- list */

function OffersList({ api, aliases, onError, reload, onOpen, onNew }) {
  const [status, setStatus] = useState("");
  const list = usePoller((signal) => api.managerOffers(status || undefined, signal), {
    key: `manager-offers:${status}:${reload}`,
    interval: 30000,
    focus: true,
    onError,
  });
  const offers = list.data || [];
  const totals = useMemo(() => offerTotals(offers), [offers]);
  return (
    <section className="card">
      <div className="section-head">
        <div>
          <h2>{t("manager.list.title")}</h2>
          <p>{t("manager.list.lead")}</p>
        </div>
        <button className="btn yellow" onClick={onNew}>
          <Plus size={16} /> {t("manager.new")}
        </button>
      </div>
      <div className="filters">
        <select
          aria-label={t("manager.filter")}
          value={status}
          onChange={(event) => setStatus(event.target.value)}
        >
          <option value="">{t("manager.filter.all")}</option>
          {["draft", "available", "cancelled", "expired"].map((value) => (
            <option key={value} value={value}>
              {offerStatusLabel(value)}
            </option>
          ))}
        </select>
        <Pill>{list.data ? tn("manager.count", offers.length) : t("common.loading")}</Pill>
      </div>
      <OfferNotice error={list.error} onRetry={list.refresh} />
      {list.data && !offers.length && <div className="empty">{t("manager.empty")}</div>}
      {offers.length > 0 && (
        <div className="table-scroll">
          <table className="ops-table offer-table">
            <thead>
              <tr>
                <th>{t("manager.col.offer")}</th>
                <th>{t("manager.col.status")}</th>
                <th>{t("manager.col.expires")}</th>
                <th>{t("manager.col.audience")}</th>
                <th>{t("manager.col.accepted")}</th>
                <th>{t("manager.col.outcomes")}</th>
                <th>{t("manager.col.kwh")}</th>
                <th>{t("manager.col.penalties")}</th>
                <th>{t("manager.col.money")}</th>
                <th>{t("manager.col.savings")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {offers.map((offer) => (
                <tr key={offer.offer_id} className="clickable" onClick={() => onOpen(offer.offer_id)}>
                  <td>
                    <b>{offerTitle(offer)}</b>
                    <small>
                      {typeLabel(offer.type)} · {areaLabel(aliases, offer.area_id)}
                    </small>
                  </td>
                  <td>
                    <StatusPill offer={offer} />
                  </td>
                  <td>{when(offer.offer_expires_at)}</td>
                  <td>
                    {offer.audience_size} / {offer.stats.targeted}
                  </td>
                  <td>{offer.stats.accepted}</td>
                  <td>
                    {offer.stats.fulfilled} / {offer.stats.partial} / {offer.stats.failed}
                  </td>
                  <td>
                    {formatKwh(offer.stats.total_kwh_committed, { unit: false })} /{" "}
                    {formatKwh(offer.stats.total_kwh_delivered, { unit: false })}
                  </td>
                  <td>{formatRon(offer.stats.total_penalties_bani)}</td>
                  <td>
                    {formatRon(offer.stats.charges_bani)}
                    <small>{formatRon(offer.stats.payouts_bani)}</small>
                  </td>
                  <td>{formatRon(offer.stats.client_savings_bani)}</td>
                  <td>
                    <button
                      className="icon-btn"
                      aria-label={t("manager.open", { title: offerTitle(offer) })}
                      onClick={(event) => {
                        event.stopPropagation();
                        onOpen(offer.offer_id);
                      }}
                    >
                      <ArrowUpRight size={17} />
                    </button>
                  </td>
                </tr>
              ))}
              <tr className="ops-total">
                <td>
                  <b>{t("manager.totals", { n: totals.count })}</b>
                </td>
                <td />
                <td />
                <td>
                  {totals.audience} / {totals.targeted}
                </td>
                <td>{totals.accepted}</td>
                <td>
                  {totals.fulfilled} / {totals.partial} / {totals.failed}
                </td>
                <td>
                  {formatKwh(totals.committed, { unit: false })} /{" "}
                  {formatKwh(totals.delivered, { unit: false })}
                </td>
                <td>{formatRon(totals.penalties)}</td>
                <td>
                  {formatRon(totals.charges)}
                  <small>{formatRon(totals.payouts)}</small>
                </td>
                <td>{formatRon(totals.savings)}</td>
                <td />
              </tr>
            </tbody>
          </table>
        </div>
      )}
      <p className="small-note">
        {t("manager.col.money")}: {t("stat.charges")} / {t("stat.payouts")}. {t("common.synthetic")}
      </p>
    </section>
  );
}

/* ------------------------------------------------------------ preview */

function PreviewPanel({ preview, localErrors }) {
  if (localErrors.length)
    return (
      <div className="offer-preview">
        <h4>{t("builder.preview.errors")}</h4>
        <ul className="offer-problems errors">
          {localErrors.map((error) => (
            <li key={error.field}>{error.message}</li>
          ))}
        </ul>
      </div>
    );
  if (preview.error)
    return (
      <div className="offer-preview">
        <OfferNotice error={preview.error} />
      </div>
    );
  const data = preview.data;
  if (!data)
    return (
      <div className="offer-preview" aria-busy="true">
        {t("builder.preview.pending")}
      </div>
    );
  return (
    <div className={`offer-preview ${preview.pending ? "is-pending" : ""}`} aria-live="polite">
      <div className="offer-audience">
        <b>{tn("builder.preview.audience", data.audience_size)}</b>
        <span>{tn("builder.preview.sites", data.sites)}</span>
        {preview.pending && <small>{t("builder.preview.pending")}</small>}
      </div>
      {data.sample_clients.length > 0 && (
        <p className="muted">
          {t("builder.preview.sample", { names: data.sample_clients.join(", ") })}
        </p>
      )}
      {data.errors.length > 0 && (
        <>
          <h4>{t("builder.preview.errors")}</h4>
          <ul className="offer-problems errors">
            {data.errors.map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
        </>
      )}
      {data.warnings.length > 0 && (
        <>
          <h4>{t("builder.preview.warnings")}</h4>
          <ul className="offer-problems warnings">
            {data.warnings.map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
        </>
      )}
      {data.summary && <Summary summary={data.summary} />}
    </div>
  );
}

function Summary({ summary }) {
  return (
    <div className="offer-summary">
      <h4>{t("builder.preview.terms")}</h4>
      <p>{summary.terms_text}</p>
      <div className="offer-facts">
        <Fact label={t("builder.preview.blockValue")}>{formatRon(summary.block_value_bani)}</Fact>
        <Fact label={t("builder.preview.maxPenalty")}>{formatRon(summary.max_penalty_bani)}</Fact>
        <Fact label={t("builder.preview.clientValue")}>
          <span className={summary.max_client_value_bani < 0 ? "offer-negative" : ""}>
            {formatRon(summary.max_client_value_bani, { signed: true })}
          </span>
        </Fact>
      </div>
      <p className="offer-rule">{summary.penalty_rule_text}</p>
    </div>
  );
}

function PublishDialog({ preview, onConfirm, onClose, busy, error }) {
  const blocked = !preview || preview.errors.length > 0 || !preview.summary;
  return (
    <OfferDialog title={t("publish.title")} onClose={onClose} busy={busy} wide>
      <p className="muted">{t("publish.lead")}</p>
      {preview ? (
        <PreviewPanel preview={{ data: preview }} localErrors={[]} />
      ) : (
        <p>{t("builder.preview.pending")}</p>
      )}
      {blocked && preview && <p className="offer-blocker">{t("publish.blocked")}</p>}
      <OfferNotice error={error} />
      <div className="offer-actions">
        <button className="btn secondary" onClick={onClose} disabled={busy}>
          {t("common.cancel")}
        </button>
        <button className="btn yellow" onClick={onConfirm} disabled={blocked || busy}>
          <Send size={15} /> {busy ? t("publish.sending") : t("publish.confirm")}
        </button>
      </div>
    </OfferDialog>
  );
}

function CancelDialog({ onConfirm, onClose, busy, error }) {
  return (
    <OfferDialog title={t("cancel.title")} onClose={onClose} busy={busy}>
      <p className="muted">{t("cancel.lead")}</p>
      <OfferNotice error={error} />
      <div className="offer-actions">
        <button className="btn secondary" onClick={onClose} disabled={busy}>
          {t("cancel.keep")}
        </button>
        <button className="btn dark" onClick={onConfirm} disabled={busy}>
          <Ban size={15} /> {busy ? t("cancel.sending") : t("cancel.confirm")}
        </button>
      </div>
    </OfferDialog>
  );
}

/** Publish (with a preview step) and cancel actions shared by the builder and detail. */
function useOfferActions(api, onError, onDone) {
  const [dialog, setDialog] = useState(null); // {kind, id, preview}
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const fail = (failure) => {
    if (!onError(failure)) setError(failure);
  };
  async function openPublish(id, getId) {
    setError(null);
    setDialog({ kind: "publish", id, preview: null });
    try {
      const offerId = getId ? await getId() : id;
      const preview = await api.previewOffer(offerId);
      setDialog({ kind: "publish", id: offerId, preview });
    } catch (failure) {
      setDialog((current) => current && { ...current, preview: { errors: [], warnings: [], sample_clients: [], audience_size: 0, sites: 0, summary: null } });
      fail(failure);
    }
  }
  async function run(action) {
    setBusy(true);
    setError(null);
    try {
      const detail = await action(dialog.id);
      setDialog(null);
      onDone(detail);
    } catch (failure) {
      fail(failure);
    } finally {
      setBusy(false);
    }
  }
  const node =
    dialog?.kind === "publish" ? (
      <PublishDialog
        preview={dialog.preview}
        busy={busy}
        error={error}
        onClose={() => setDialog(null)}
        onConfirm={() => run((id) => api.publishOffer(id))}
      />
    ) : dialog?.kind === "cancel" ? (
      <CancelDialog
        busy={busy}
        error={error}
        onClose={() => setDialog(null)}
        onConfirm={() => run((id) => api.cancelOffer(id))}
      />
    ) : null;
  return {
    openPublish,
    openCancel: (id) => {
      setError(null);
      setDialog({ kind: "cancel", id });
    },
    node,
  };
}

/* ------------------------------------------------------------ builder */

function Field({ label, error, children, id }) {
  return (
    <label className={`offer-field ${error ? "has-error" : ""}`} htmlFor={id}>
      <span>{label}</span>
      {children}
      {error && (
        <small className="offer-field-error" id={`${id}-error`}>
          {error}
        </small>
      )}
    </label>
  );
}

function ClientPicker({ clients, selected, onChange }) {
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const shown = (clients || []).filter(
    (client) =>
      !q ||
      client.username.toLowerCase().includes(q) ||
      client.sites.some((site) =>
        [site.alias, site.site_id, site.zone || ""].some((v) => v.toLowerCase().includes(q)),
      ),
  );
  const toggle = (id) =>
    onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  return (
    <div className="offer-clients">
      <label className="offer-search">
        <Search size={15} aria-hidden="true" />
        <input
          type="search"
          aria-label={t("builder.clients.search")}
          placeholder={t("builder.clients.search")}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </label>
      <p className="muted">{tn("builder.clients.selected", selected.length)}</p>
      {!clients && <p className="muted">{t("common.loading")}</p>}
      {clients && !shown.length && <p className="muted">{t("builder.clients.empty")}</p>}
      <ul>
        {shown.map((client) => (
          <li key={client.user_id}>
            <label>
              <input
                type="checkbox"
                checked={selected.includes(client.user_id)}
                onChange={() => toggle(client.user_id)}
              />
              <span>
                <b>{client.username}</b>
                <small>
                  {client.sites
                    .map((site) =>
                      [
                        site.alias,
                        site.zone && `zone ${site.zone}`,
                        site.segment === "prosumers"
                          ? `prosumer${site.installed_kwp ? ` ${site.installed_kwp} kWp` : ""}`
                          : "consumer",
                        !site.has_meter && "no meter",
                      ]
                        .filter(Boolean)
                        .join(" · "),
                    )
                    .join(" | ")}
                </small>
              </span>
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Builder({ api, areas, offer: initial, onPublished, onBack, onError }) {
  const [form, setForm] = useState(() =>
    initial ? formFromOffer(initial) : defaultForm(areas[0]?.area_id || ""),
  );
  // The saved version: a new draft gets one on its first save, without a remount,
  // so "Publish" can save first and then open its confirmation.
  const [offer, setOffer] = useState(initial);
  const savedKey = useMemo(
    () => (offer ? draftKey(formToDraft(formFromOffer(offer)).draft) : null),
    [offer],
  );
  const { draft, errors: localErrors } = useMemo(() => formToDraft(form), [form]);
  const key = draftKey(draft);
  const dirty = key !== savedKey;
  const status = offer?.status || "draft";
  const closed = status === "cancelled" || status === "expired";
  const readOnly = Boolean(offer?.locked) || closed;
  const set = (patch) => setForm((current) => ({ ...current, ...patch }));
  const fieldError = (field) => localErrors.find((e) => e.field === field)?.message;

  const clients = usePoller(
    (signal) =>
      form.targetMode === "clients" && form.areaId
        ? api.offerClients(form.areaId, signal)
        : Promise.resolve(null),
    { key: `clients:${form.targetMode}:${form.areaId}`, interval: 300000, onError },
  );
  const incidents = usePoller((signal) => api.opsIncidents("open", signal), {
    key: "offer-incidents",
    interval: 120000,
    onError,
  });
  const areaIncidents = (incidents.data || []).filter((i) => i.area_id === form.areaId);
  const linked = areaIncidents.find((i) => i.incident_id === form.incidentId);

  // Debounced audience preview of the current form (~500 ms after the last change).
  const [preview, setPreview] = useState({ key: null, data: null, error: null, pending: false });
  const sequence = useRef(0);
  useEffect(() => {
    if (readOnly || localErrors.length) return;
    const id = ++sequence.current;
    setPreview((current) => ({ ...current, pending: true }));
    const timer = setTimeout(async () => {
      try {
        const data = await api.previewOfferDraft(draft);
        if (id === sequence.current) setPreview({ key, data, error: null, pending: false });
      } catch (failure) {
        if (id !== sequence.current || onError(failure)) return;
        setPreview({ key, data: null, error: failure, pending: false });
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [key, readOnly]);
  const previewReady =
    !localErrors.length && preview.key === key && !preview.pending && preview.data;
  const canPublish =
    status === "draft" && previewReady && !preview.data.errors.length && !readOnly;

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [message, setMessage] = useState("");
  async function save() {
    setSaving(true);
    setSaveError(null);
    setMessage("");
    try {
      const detail = offer
        ? await api.updateOffer(offer.offer_id, draft)
        : await api.createOffer(draft);
      setMessage(t(detail.status === "draft" ? "builder.saved" : "builder.savedChanges"));
      setOffer(detail);
      return detail;
    } catch (failure) {
      if (!onError(failure)) setSaveError(failure);
      throw failure;
    } finally {
      setSaving(false);
    }
  }
  const actions = useOfferActions(api, onError, (detail) => onPublished(detail));

  return (
    <>
      <button className="text-btn" onClick={onBack}>
        <ArrowLeft size={15} /> {t("common.back")}
      </button>
      <section className="card offer-builder">
        <div className="section-head">
          <div>
            <h2>{offer ? t("builder.edit") : t("builder.new")}</h2>
            {offer && (
              <p>
                {shortId(offer.offer_id)} · <StatusPill offer={offer} />
              </p>
            )}
          </div>
          {dirty && !readOnly && <Pill tone="yellow">{t("builder.unsaved")}</Pill>}
        </div>
        {offer?.locked && (
          <p className="offer-warning" role="note">
            <Lock size={15} aria-hidden="true" /> {t("builder.lockedNote")}
          </p>
        )}
        {closed && (
          <p className="offer-warning" role="note">
            {t("builder.closedNote", { status: offerStatusLabel(status).toLowerCase() })}
          </p>
        )}
        <fieldset className="offer-form" disabled={readOnly}>
          <div className="offer-form-grid">
            <div className="offer-field wide">
              <span id="offer-type-label">{t("builder.type")}</span>
              <div className="offer-toggle" role="radiogroup" aria-labelledby="offer-type-label">
                {["consume", "export"].map((type) => (
                  <button
                    type="button"
                    key={type}
                    role="radio"
                    aria-checked={form.type === type}
                    className={form.type === type ? "active" : ""}
                    onClick={() => set({ type })}
                  >
                    {typeLabel(type)}
                  </button>
                ))}
              </div>
              <small>{t(`builder.type.${form.type}.hint`)}</small>
            </div>
            <Field id="offer-title" label={t("builder.titleField")} error={fieldError("title")}>
              <input
                id="offer-title"
                maxLength={80}
                value={form.title}
                placeholder={t("builder.titlePlaceholder")}
                onChange={(event) => set({ title: event.target.value })}
              />
            </Field>
            <Field id="offer-area" label={t("builder.area")} error={fieldError("areaId")}>
              <select
                id="offer-area"
                value={form.areaId}
                onChange={(event) =>
                  set({
                    areaId: event.target.value,
                    userIds: [],
                    incidentId: "",
                    incidentZone: "",
                    zoneOnly: false,
                  })
                }
              >
                {!form.areaId && <option value="">—</option>}
                {areas.map((area) => (
                  <option key={area.area_id} value={area.area_id}>
                    {area.alias}
                  </option>
                ))}
              </select>
            </Field>
            <Field id="offer-energy" label={t("builder.energy")} error={fieldError("energy")}>
              <input
                id="offer-energy"
                inputMode="decimal"
                value={form.energy}
                onChange={(event) => set({ energy: event.target.value })}
              />
            </Field>
            <Field id="offer-price" label={t("builder.price")} error={fieldError("price")}>
              <input
                id="offer-price"
                inputMode="decimal"
                value={form.price}
                onChange={(event) => set({ price: event.target.value })}
              />
            </Field>
            <div className="offer-field wide">
              <span id="offer-window-label">{t("builder.window")}</span>
              <div className="offer-toggle" role="radiogroup" aria-labelledby="offer-window-label">
                {[...WINDOW_PRESETS.map(String), "custom"].map((choice) => (
                  <button
                    type="button"
                    key={choice}
                    role="radio"
                    aria-checked={form.windowChoice === choice}
                    className={form.windowChoice === choice ? "active" : ""}
                    onClick={() => set({ windowChoice: choice })}
                  >
                    {choice === "custom" ? t("builder.window.custom") : durationText(Number(choice))}
                  </button>
                ))}
              </div>
              {form.windowChoice === "custom" && (
                <input
                  aria-label={t("builder.window.customMinutes")}
                  placeholder={t("builder.window.customMinutes")}
                  inputMode="numeric"
                  value={form.windowCustom}
                  onChange={(event) => set({ windowCustom: event.target.value })}
                />
              )}
              {fieldError("window") && <small className="offer-field-error">{fieldError("window")}</small>}
            </div>
            <Field id="offer-penalty-type" label={t("builder.penaltyType")}>
              <select
                id="offer-penalty-type"
                value={form.penaltyType}
                onChange={(event) => set({ penaltyType: event.target.value })}
              >
                {["per_unfulfilled_kwh", "percent_of_unfulfilled_value", "flat"].map((type) => (
                  <option key={type} value={type}>
                    {t(`builder.penalty.${type}`)}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              id="offer-penalty-value"
              label={t("builder.penaltyValue")}
              error={fieldError("penaltyValue")}
            >
              <input
                id="offer-penalty-value"
                inputMode="decimal"
                value={form.penaltyValue}
                onChange={(event) => set({ penaltyValue: event.target.value })}
              />
            </Field>
            <div className="offer-field wide offer-rule-preview" aria-live="polite">
              <span>{t("builder.penaltyPreview")}</span>
              <p className="offer-rule">{penaltyPreviewText(form) || "—"}</p>
            </div>
            <div className="offer-field">
              <span>{t("builder.expiry")}</span>
              <div className="offer-inline">
                <input
                  type="date"
                  aria-label={t("builder.expiryDate")}
                  value={form.expiryDate}
                  onChange={(event) => set({ expiryDate: event.target.value })}
                />
                <input
                  type="time"
                  aria-label={t("builder.expiryTime")}
                  value={form.expiryTime}
                  onChange={(event) => set({ expiryTime: event.target.value })}
                />
              </div>
              {fieldError("expiry") && <small className="offer-field-error">{fieldError("expiry")}</small>}
            </div>
            <div className="offer-field">
              <span>{t("builder.limits")}</span>
              <div className="offer-inline">
                <input
                  aria-label={t("builder.maxTakers")}
                  placeholder={t("builder.maxTakers")}
                  inputMode="numeric"
                  value={form.maxTakers}
                  onChange={(event) => set({ maxTakers: event.target.value })}
                />
                <input
                  aria-label={t("builder.maxTotalKwh")}
                  placeholder={t("builder.maxTotalKwh")}
                  inputMode="decimal"
                  value={form.maxTotalKwh}
                  onChange={(event) => set({ maxTotalKwh: event.target.value })}
                />
              </div>
              {(fieldError("maxTakers") || fieldError("maxTotalKwh")) && (
                <small className="offer-field-error">
                  {fieldError("maxTakers") || fieldError("maxTotalKwh")}
                </small>
              )}
            </div>
            <div className="offer-field wide">
              <span id="offer-target-label">{t("builder.targeting")}</span>
              <div className="offer-toggle" role="radiogroup" aria-labelledby="offer-target-label">
                {["all", "segment", "clients"].map((mode) => (
                  <button
                    type="button"
                    key={mode}
                    role="radio"
                    aria-checked={form.targetMode === mode}
                    className={form.targetMode === mode ? "active" : ""}
                    onClick={() => set({ targetMode: mode })}
                  >
                    {t(`builder.target.${mode}`)}
                  </button>
                ))}
              </div>
              {form.targetMode === "segment" && (
                <div className="offer-inline">
                  <select
                    aria-label={t("builder.target.segment")}
                    value={form.segment}
                    onChange={(event) => set({ segment: event.target.value })}
                  >
                    <option value="consumers">{t("builder.segment.consumers")}</option>
                    <option value="prosumers">{t("builder.segment.prosumers")}</option>
                  </select>
                  <input
                    aria-label={t("builder.minKwp")}
                    placeholder={t("builder.minKwp")}
                    inputMode="decimal"
                    value={form.minKwp}
                    onChange={(event) => set({ minKwp: event.target.value })}
                  />
                </div>
              )}
              {fieldError("minKwp") && <small className="offer-field-error">{fieldError("minKwp")}</small>}
              {form.targetMode === "clients" && (
                <ClientPicker
                  clients={clients.data}
                  selected={form.userIds}
                  onChange={(userIds) => set({ userIds })}
                />
              )}
              {fieldError("userIds") && <small className="offer-field-error">{fieldError("userIds")}</small>}
            </div>
            <div className="offer-field wide">
              <span>{t("builder.incident")}</span>
              <select
                aria-label={t("builder.incident")}
                value={form.incidentId}
                onChange={(event) => {
                  const incident = areaIncidents.find((i) => i.incident_id === event.target.value);
                  set({
                    incidentId: event.target.value,
                    incidentZone: incident?.zone || "",
                    zoneOnly: false,
                  });
                }}
              >
                <option value="">{t("builder.incident.none")}</option>
                {form.incidentId && !linked && (
                  <option value={form.incidentId}>{shortId(form.incidentId)}</option>
                )}
                {areaIncidents.map((incident) => (
                  <option key={incident.incident_id} value={incident.incident_id}>
                    {incident.tier} · {incident.title} · {incident.site_alias}
                    {incident.zone ? ` · zone ${incident.zone}` : ""}
                  </option>
                ))}
              </select>
              {form.incidentId &&
                (form.incidentZone ? (
                  <label className="offer-check">
                    <input
                      type="checkbox"
                      checked={form.zoneOnly}
                      onChange={(event) => set({ zoneOnly: event.target.checked })}
                    />
                    {t("builder.zoneOnly", { zone: form.incidentZone })}
                  </label>
                ) : (
                  <small>{t("builder.zoneUnknown")}</small>
                ))}
            </div>
          </div>
        </fieldset>
        {!readOnly && (
          <section className="offer-preview-wrap" aria-labelledby="offer-preview-title">
            <h3 id="offer-preview-title">{t("builder.preview")}</h3>
            <PreviewPanel preview={preview} localErrors={localErrors} />
          </section>
        )}
        <OfferNotice error={saveError} />
        {message && !dirty && (
          <p className="offer-success" role="status">
            {message}
          </p>
        )}
        <div className="offer-actions builder">
          {!readOnly && (
            <button
              className="btn secondary"
              onClick={() => save().catch(() => {})}
              disabled={saving || localErrors.length > 0 || (!dirty && Boolean(offer))}
            >
              {saving ? t("builder.saving") : status === "draft" ? t("builder.save") : t("builder.saveChanges")}
            </button>
          )}
          {status === "draft" && !readOnly && (
            <button
              className="btn yellow"
              disabled={!canPublish || saving}
              onClick={() =>
                actions.openPublish(
                  offer?.offer_id,
                  dirty || !offer ? async () => (await save()).offer_id : undefined,
                )
              }
            >
              <Send size={15} /> {t("builder.publish")}
            </button>
          )}
          {offer && !closed && (
            <button className="btn dark" onClick={() => actions.openCancel(offer.offer_id)}>
              <Ban size={15} /> {t("builder.cancelOffer")}
            </button>
          )}
        </div>
      </section>
      {actions.node}
    </>
  );
}

function EditOffer({ api, id, areas, onPublished, onBack, onError }) {
  const [offer, setOffer] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    const controller = new AbortController();
    api
      .managerOffer(id, controller.signal)
      .then((value) => !controller.signal.aborted && setOffer(value))
      .catch((failure) => {
        if (!controller.signal.aborted && !onError(failure)) setError(failure);
      });
    return () => controller.abort();
  }, [id]);
  if (error) return <OfferNotice error={error} />;
  if (!offer) return <section className="card empty">{t("common.loading")}</section>;
  return (
    <Builder
      key={offer.offer_id}
      api={api}
      areas={areas}
      offer={offer}
      onPublished={onPublished}
      onBack={onBack}
      onError={onError}
    />
  );
}

/* ------------------------------------------------------------- detail */

function targetingText(offer, aliases) {
  const area = areaLabel(aliases, offer.area_id);
  const base =
    offer.target_mode === "segment"
      ? t("detail.target.segment", {
          segment: t(`builder.segment.${offer.target_segment || "consumers"}`),
          area,
        })
      : offer.target_mode === "clients"
        ? tn("detail.target.clients", offer.target_user_ids.length, { area })
        : t("detail.target.all", { area });
  return [
    base,
    offer.target_min_kwp && t("detail.target.minKwp", { kwp: offer.target_min_kwp }),
    offer.target_zone && t("detail.target.zone", { zone: offer.target_zone }),
  ]
    .filter(Boolean)
    .join(" · ");
}

function OfferDetail({ api, id, aliases, onBack, onEdit, onError }) {
  const [nudge, setNudge] = useState(0);
  const detail = usePoller((signal) => api.managerOffer(id, signal), {
    key: `manager-offer:${id}`,
    interval: 15000,
    focus: true,
    nudge,
    onError,
  });
  const audit = usePoller((signal) => api.offerAudit(id, signal), {
    key: `manager-offer-audit:${id}`,
    interval: 15000,
    focus: true,
    nudge,
    onError,
  });
  const actions = useOfferActions(api, onError, () => setNudge((value) => value + 1));
  const offer = detail.data;
  if (!offer)
    return (
      <>
        <button className="text-btn" onClick={onBack}>
          <ArrowLeft size={15} /> {t("common.back")}
        </button>
        {detail.error ? (
          <OfferNotice error={detail.error} onRetry={detail.refresh} />
        ) : (
          <section className="card empty">{t("common.loading")}</section>
        )}
      </>
    );
  const s = offer.stats;
  const editable = !offer.locked && ["draft", "available"].includes(offer.status);
  const stats = [
    ["stat.targeted", s.targeted],
    ["stat.accepted", s.accepted],
    ["stat.active", s.active],
    ["stat.fulfilled", s.fulfilled],
    ["stat.partial", s.partial],
    ["stat.failed", s.failed],
    ["stat.cancelled", s.cancelled],
    ["stat.committed", formatKwh(s.total_kwh_committed)],
    ["stat.delivered", formatKwh(s.total_kwh_delivered)],
    ["stat.penalties", formatRon(s.total_penalties_bani)],
    [offer.type === "export" ? "stat.payouts" : "stat.charges", formatRon(offer.type === "export" ? s.payouts_bani : s.charges_bani)],
    ["stat.savings", formatRon(s.client_savings_bani)],
  ];
  return (
    <>
      <button className="text-btn" onClick={onBack}>
        <ArrowLeft size={15} /> {t("common.back")}
      </button>
      <section className="card offer-detail">
        <div className="section-head">
          <div>
            <div className="eyebrow">
              {typeLabel(offer.type).toUpperCase()} · {areaLabel(aliases, offer.area_id).toUpperCase()}
            </div>
            <h2>{offerTitle(offer)}</h2>
            <p>
              {shortId(offer.offer_id)} · {t("detail.refresh")}
            </p>
          </div>
          <StatusPill offer={offer} />
        </div>
        <OfferNotice error={detail.error} onRetry={detail.refresh} />
        <div className="offer-facts">
          <Fact label={t("offer.block")}>{formatKwh(offer.energy_kwh)}</Fact>
          <Fact label={t("offer.price")}>{formatPrice(offer.offer_price_ron_per_kwh)}</Fact>
          <Fact label={t("offer.window")}>{durationText(offer.window_minutes)}</Fact>
          <Fact label={t("offer.expires")}>{when(offer.offer_expires_at)}</Fact>
          <Fact label={t("builder.preview.blockValue")}>{formatRon(offer.block_value_bani)}</Fact>
          <Fact label={t("builder.preview.maxPenalty")}>{formatRon(offer.max_penalty_bani)}</Fact>
          <Fact label={t("detail.targeting")}>{targetingText(offer, aliases)}</Fact>
          <Fact label={t("builder.limits")}>
            {[
              offer.max_takers != null && `${t("builder.maxTakers")}: ${offer.max_takers}`,
              offer.max_total_kwh && `${t("builder.maxTotalKwh")}: ${formatKwh(offer.max_total_kwh)}`,
            ]
              .filter(Boolean)
              .join(" · ") || t("common.noLimit")}
          </Fact>
        </div>
        <h3 className="mt">{t("detail.terms")}</h3>
        <p className="offer-terms">{offer.terms_text}</p>
        <p className="offer-rule">{offer.penalty_rule_text}</p>
        {offer.locked && ["draft", "available"].includes(offer.status) && (
          <p className="offer-warning" role="note">
            <Lock size={15} aria-hidden="true" /> {t("builder.lockedNote")}
          </p>
        )}
        <div className="offer-actions builder">
          {editable && (
            <button className="btn secondary" onClick={() => onEdit(offer.offer_id)}>
              <Pencil size={15} /> {t("detail.edit")}
            </button>
          )}
          {offer.status === "draft" && (
            <button className="btn yellow" onClick={() => actions.openPublish(offer.offer_id)}>
              <Send size={15} /> {t("builder.publish")}
            </button>
          )}
          {["draft", "available"].includes(offer.status) && (
            <button className="btn dark" onClick={() => actions.openCancel(offer.offer_id)}>
              <Ban size={15} /> {t("builder.cancelOffer")}
            </button>
          )}
        </div>
      </section>
      <section className="card mt">
        <h3>{t("detail.stats")}</h3>
        <dl className="offer-stats">
          {stats.map(([id, value]) => (
            <div key={id}>
              <dt>{t(id)}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      </section>
      <section className="card mt">
        <h3>{t("detail.takers")}</h3>
        {!offer.takers.length ? (
          <p className="muted">{t("detail.takers.empty")}</p>
        ) : (
          <div className="table-scroll">
            <table className="ops-table offer-table">
              <thead>
                <tr>
                  <th>{t("detail.col.client")}</th>
                  <th>{t("detail.col.status")}</th>
                  <th>{t("detail.col.progress")}</th>
                  <th>{t("detail.col.window")}</th>
                  <th>{t("detail.col.penalty")}</th>
                  <th>{t("detail.col.amount")}</th>
                  <th>{t("detail.col.saving")}</th>
                </tr>
              </thead>
              <tbody>
                {offer.takers.map((taker) => (
                  <tr key={taker.user_offer_id}>
                    <td>
                      <b>{taker.username}</b>
                      <small>{taker.site_alias}</small>
                    </td>
                    <td>
                      <Pill tone={outcomeTone(taker.status)}>{outcomeLabel(taker.status)}</Pill>
                    </td>
                    <td>
                      {formatKwh(taker.metered_kwh)} / {formatKwh(taker.fulfilled_kwh)}
                      <small>{t("meter.coverageShort", { percent: formatPercent(taker.coverage_ratio) })}</small>
                    </td>
                    <td>{when(taker.window_end)}</td>
                    <td>{taker.penalty_bani == null ? "—" : formatRon(taker.penalty_bani)}</td>
                    <td>{taker.amount_bani == null ? "—" : formatRon(taker.amount_bani)}</td>
                    <td>
                      {taker.savings_bani == null ? "—" : formatRon(taker.savings_bani, { signed: true })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section className="card mt">
        <h3>{t("detail.audit")}</h3>
        <OfferNotice error={audit.error} onRetry={audit.refresh} />
        {audit.data && !audit.data.length && <p className="muted">{t("detail.audit.empty")}</p>}
        {audit.data?.length > 0 && (
          <div className="table-scroll">
            <table className="ops-table offer-table">
              <thead>
                <tr>
                  <th>{t("detail.col.time")}</th>
                  <th>{t("detail.col.actor")}</th>
                  <th>{t("detail.col.action")}</th>
                  <th>{t("detail.col.changes")}</th>
                </tr>
              </thead>
              <tbody>
                {audit.data.map((entry, index) => (
                  <tr key={`${entry.request_id}:${index}`}>
                    <td>{when(entry.created_at)}</td>
                    <td>{entry.actor}</td>
                    <td>{auditAction(entry.action)}</td>
                    <td>
                      {auditLines(entry, when).map((line) => (
                        <small key={line}>{line}</small>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {actions.node}
    </>
  );
}

/* --------------------------------------------------------------- page */

export function ManagerOffersPage({ api, areas = [], onError, reload, focus, onFocusHandled }) {
  const [view, setView] = useState({ mode: "list" });
  const aliases = useMemo(
    () => Object.fromEntries(areas.map((area) => [area.area_id, area.alias])),
    [areas],
  );
  useEffect(() => {
    if (focus?.kind === "managerOffer") setView({ mode: "detail", id: focus.id });
    if (focus) onFocusHandled?.();
  }, [focus]);
  useEffect(() => {
    window.scrollTo?.({ top: 0 });
  }, [view.mode, view.id]);
  const list = () => setView({ mode: "list" });
  const detail = (id) => setView({ mode: "detail", id });
  if (view.mode === "new")
    return (
      <Builder
        api={api}
        areas={areas}
        offer={null}
        onPublished={(saved) => detail(saved.offer_id)}
        onBack={list}
        onError={onError}
      />
    );
  if (view.mode === "edit")
    return (
      <EditOffer
        api={api}
        id={view.id}
        areas={areas}
        onPublished={(saved) => detail(saved.offer_id)}
        onBack={() => detail(view.id)}
        onError={onError}
      />
    );
  if (view.mode === "detail")
    return (
      <OfferDetail
        api={api}
        id={view.id}
        aliases={aliases}
        onBack={list}
        onEdit={(id) => setView({ mode: "edit", id })}
        onError={onError}
      />
    );
  return (
    <OffersList
      api={api}
      aliases={aliases}
      onError={onError}
      reload={reload}
      onOpen={detail}
      onNew={() => setView({ mode: "new" })}
    />
  );
}

