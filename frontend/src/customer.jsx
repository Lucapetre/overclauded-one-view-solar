// Connected (API-backed) customer features: energy totals, care card, support, lessons, contract.
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  BookOpen,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  LifeBuoy,
  MessageSquare,
  Paperclip,
  Send,
  ShieldCheck,
  Video,
} from "lucide-react";
import { poll } from "../../packages/contracts/client";
import { errorMessage, matchesSeries, primaryReadings, when } from "./telemetry";
import { bucketEnergy, PERIODS, periodRange, total } from "./periods";
import {
  ContractCard,
  EnergyBars,
  ForecastCard,
  LessonDeck,
} from "./features";
import { words } from "./friendly";
import { durationProblem, humanSize, videoProblem } from "./video";
import { friendlyError, keepIfSame, shortId } from "./opsData";
import { meetingLabel } from "./bucharestTime";

export function asOf(record) {
  const value = record?.provider
    ? record.data?.site.as_of_utc
    : record?.data?.freshness.evaluated_at || record?.data?.interval_end;
  const date = value ? new Date(value) : new Date();
  return Number.isNaN(date.getTime()) ? new Date() : date;
}

async function providerSeries(api, siteId, frame, from, to, signal) {
  if (!frame || frame.unit !== "kW") return [];
  const query = {
    from: from.toISOString(),
    to: to.toISOString(),
    metric: frame.metric_name,
    endpoint: frame.endpoint_key,
    device: frame.device_id || undefined,
    channel: frame.channel || undefined,
    limit: 1000,
  };
  const items = [];
  let page;
  do {
    page = await api.providerFrames(
      siteId,
      { ...query, offset: items.length },
      signal,
    );
    items.push(...page.items);
  } while (items.length < page.total && page.items.length);
  return items
    .filter((item) => matchesSeries(item, frame))
    .map((item) => ({
      time: item.frame_start_utc,
      // Mean power over the frame multiplied by the frame's duration.
      kwh:
        item.value == null
          ? null
          : (item.value *
              (Date.parse(item.frame_end_utc) -
                Date.parse(item.frame_start_utc))) /
            3600000,
    }));
}

/** Energy per source interval for production, consumption and export. */
export async function loadEnergy(api, site, record, from, to, daily, signal) {
  if (record.provider) {
    const [pv, load, , exported] = primaryReadings(record.data, true);
    const [production, consumption, exports] = await Promise.all(
      [pv, load, exported].map((reading) =>
        providerSeries(api, site.site_id, reading?.frame, from, to, signal),
      ),
    );
    return { production, consumption, export: exports };
  }
  const result = { production: [], consumption: [], export: [] };
  const names = {
    production: "pv_power",
    consumption: "home_load",
    export: "grid_export",
  };
  // The history endpoint accepts at most 31 elapsed days per request.
  for (let start = from; start < to; ) {
    const end = new Date(Math.min(to.getTime(), start.getTime() + 30 * 86400000));
    const history = await api.history(
      site.site_id,
      start.toISOString(),
      end.toISOString(),
      daily ? "1d" : "1h",
      signal,
    );
    for (const point of history.points)
      for (const [key, metric] of Object.entries(names))
        if (metric in point.energy_kwh)
          result[key].push({
            time: point.interval_start,
            kwh: point.energy_kwh[metric],
          });
    start = end;
  }
  return result;
}

export function useEnergy(api, site, record, period, onError) {
  const [state, setState] = useState({ loading: true });
  const ready = Boolean(record?.data);
  // Re-read at most hourly: a live clock otherwise changes on every poll.
  const hour = ready ? Math.floor(asOf(record).getTime() / 3600000) : 0;
  useEffect(() => {
    if (!ready) return;
    const controller = new AbortController();
    setState({ loading: true });
    const { from, to } = periodRange(period, asOf(record));
    loadEnergy(
      api,
      site,
      record,
      from,
      to,
      PERIODS[period].bucket !== "hour",
      controller.signal,
    )
      .then((series) => {
        if (!controller.signal.aborted) setState({ series, from, to });
      })
      .catch((error) => {
        if (!controller.signal.aborted && !onError?.(error)) setState({ error });
      });
    return () => controller.abort();
  }, [site.site_id, period, hour, ready, record?.provider]);
  return state;
}

export function HomeEnergyChart({ api, site, record, accountType, onError }) {
  const [period, setPeriod] = useState("Today");
  const energy = useEnergy(api, site, record, period, onError);
  const w = words(accountType);
  const buckets = energy.series
    ? bucketEnergy(
        {
          production: energy.series.production,
          consumption: energy.series.consumption,
        },
        PERIODS[period].bucket,
      )
    : [];
  const produced = energy.series ? total(energy.series.production) : null;
  return (
    <section className="card chart-card">
      <div className="section-head">
        <div>
          <h3>Your energy, {PERIODS[period].title}</h3>
          <p>Measured energy only. Periods without data stay empty.</p>
        </div>
        <select
          aria-label="Chart period"
          value={period}
          onChange={(event) => setPeriod(event.target.value)}
        >
          {Object.keys(PERIODS).map((name) => (
            <option key={name}>{name}</option>
          ))}
        </select>
      </div>
      {energy.error ? (
        <div className="empty">
          <p>{errorMessage(energy.error)}</p>
        </div>
      ) : energy.loading ? (
        <div className="empty">Adding up your energy…</div>
      ) : (
        <EnergyBars buckets={buckets} consumptionLabel={w.consumption} />
      )}
      <div className="chart-foot">
        <span>
          Solar produced{" "}
          <b>
            {produced == null
              ? "unavailable"
              : `${new Intl.NumberFormat("en-GB", { maximumFractionDigits: 1 }).format(produced)} kWh`}
          </b>
        </span>
        <span>Up to {when(asOf(record))}</span>
      </div>
    </section>
  );
}

const careText = {
  fresh: ["ok", "Reporting normally"],
  fresh_documented_unavailable: ["ok", "Resting, as expected (for example at night)"],
  stale: ["warn", "No recent data from this source"],
  access_denied: ["warn", "Access to this data has not been granted"],
  capability_unsupported: ["info", "Not available on this equipment"],
  not_continuously_polled: ["info", "Checked from time to time"],
  unavailable: ["warn", "No data received yet"],
  future: ["warn", "The source clock looks wrong"],
  unknown_clock: ["info", "Freshness could not be checked"],
};
const pretty = (key) => {
  const text = key.replaceAll(/[_.:-]+/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
};

/** Source reporting health in the friendly "Looking after your home" form. */
export function CareCard({ record, accountType, onLearn, onSupport }) {
  const w = words(accountType);
  const data = record?.data;
  const sources = !data
    ? []
    : record.provider
      ? data.source_health.map((source) => ({
          key: `${source.endpoint_key}:${source.device_key}`,
          name: pretty(source.endpoint_key),
          status: source.freshness_status,
          time: source.latest_source_ms,
        }))
      : [
          {
            key: "feed",
            name: "Energy readings",
            status: data.freshness.status,
            time: data.interval_end,
          },
        ];
  const rows = sources.map((source) => {
    const [tone, text] = careText[source.status] ||
      (source.status.includes("stale")
        ? careText.stale
        : ["info", pretty(source.status)]);
    return { ...source, tone, text };
  });
  const attention = rows.filter((row) => row.tone === "warn");
  const fine = rows.filter((row) => row.tone === "ok").length;
  return (
    <section className="card activity-card">
      <div className="section-head">
        <h3>{w.care}</h3>
        <span className="subtle-icon">
          <ShieldCheck size={19} />
        </span>
      </div>
      {attention.slice(0, 3).map((row) => (
        <button className="alert-row" key={row.key} onClick={onSupport}>
          <span className="alert-icon">
            <AlertTriangle size={19} />
          </span>
          <div>
            <b>{row.name}</b>
            <p>
              {row.text}
              {row.time ? ` · last heard ${when(row.time)}` : ""}
            </p>
          </div>
          <ChevronRight size={17} />
        </button>
      ))}
      {attention.length > 3 && (
        <p className="small-note">
          {attention.length - 3} more sources need attention.
        </p>
      )}
      {rows.length > 0 && (
        <div className="alert-row care-ok">
          <span className="alert-icon">
            <CheckCircle2 size={19} />
          </span>
          <div>
            <b>
              {attention.length
                ? `${fine} of ${rows.length} data sources reporting normally`
                : "Everything is reporting normally"}
            </b>
            <p>
              This shows whether your system is sending data. It is not an
              equipment health check.
            </p>
          </div>
        </div>
      )}
      {!rows.length && <p>Checking your data sources…</p>}
      <button className="learn-teaser" onClick={onLearn}>
        <span>
          <BookOpen size={20} />
        </span>
        <div>
          <small>ONE MINUTE · EARN BILL CREDIT</small>
          <b>Making sense of your solar</b>
          <p>Short lessons with a mini test.</p>
        </div>
        <ArrowUpRight size={19} />
      </button>
      <div className="support-bottom">
        <span>Questions about your system?</span>
        <button className="text-btn" onClick={onSupport}>
          Let’s talk <ArrowUpRight size={14} />
        </button>
      </div>
    </section>
  );
}

export function useContract(api, siteId, onError) {
  const [view, setView] = useState(null);
  useEffect(() => {
    if (!siteId) return;
    const controller = new AbortController();
    setView(null);
    api
      .contract(siteId, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setView(value);
      })
      .catch((error) => {
        if (!controller.signal.aborted && !onError?.(error))
          setView({ site_id: siteId, contract: null, error });
      });
    return () => controller.abort();
  }, [siteId]);
  const save = useCallback(
    async (contract) => setView(await api.saveContract(siteId, contract)),
    [siteId],
  );
  return [view, save];
}

const DEFAULT_KWP = { home: 5, business: 30 };

export function ContractAndForecast({ api, site, accountType, readOnly, onError, replay }) {
  const [view, save] = useContract(api, site.site_id, onError);
  const contract = view?.contract || null;
  return (
    <div className="two-col mt">
      <ForecastCard
        kwp={contract?.installed_kwp || DEFAULT_KWP[accountType] || 5}
        kwpAssumed={!contract?.installed_kwp}
        contract={contract}
        accountType={accountType}
        replay={replay}
      />
      {view ? (
        <ContractCard
          key={site.site_id}
          contract={contract}
          version={view.version}
          onSave={save}
          readOnly={readOnly}
        />
      ) : (
        <section className="card empty">Loading your contract…</section>
      )}
    </div>
  );
}

export function LearnPage({ api, onError }) {
  const [catalog, setCatalog] = useState(null);
  const [error, setError] = useState(null);
  const load = useCallback(
    () =>
      api
        .lessons()
        .then(setCatalog)
        .catch((failure) => {
          if (!onError(failure)) setError(failure);
        }),
    [],
  );
  useEffect(() => {
    load();
  }, [load]);
  if (error)
    return <section className="card empty">{errorMessage(error)}</section>;
  if (!catalog)
    return <section className="card empty">Loading your lessons…</section>;
  return (
    <LessonDeck
      catalog={catalog}
      onComplete={async (id, answers) => {
        const result = await api.completeLesson(id, answers);
        load();
        return result;
      }}
    />
  );
}

function useRequests(api, onError) {
  const [requests, setRequests] = useState(null);
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);
  useEffect(
    () =>
      poll(
        (signal) => api.supportRequests(signal),
        (value) => {
          setRequests((previous) => keepIfSame(previous, value));
          setError(null);
        },
        (failure) => {
          if (!onError(failure)) setError(failure);
        },
      ),
    [tick],
  );
  return [requests, error, () => setTick((value) => value + 1)];
}

/**
 * Video duration in seconds, read from metadata in a detached <video> element.
 * Rejects on decode failure or after `timeoutMs`. Some recorders (MediaRecorder
 * WebM) report an infinite duration until the end is sought, so we seek once.
 */
export function readVideoDuration(file, timeoutMs = 8000) {
  return new Promise((resolve, reject) => {
    const video = document.createElement("video");
    const url = URL.createObjectURL(file);
    let done = false;
    const finish = (settle, value) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      video.removeAttribute("src");
      video.load();
      URL.revokeObjectURL(url);
      settle(value);
    };
    const timer = setTimeout(
      () => finish(reject, new Error("timeout")),
      timeoutMs,
    );
    video.preload = "metadata";
    video.muted = true;
    video.onloadedmetadata = () => {
      if (video.duration === Infinity) {
        video.ondurationchange = () => {
          if (Number.isFinite(video.duration)) finish(resolve, video.duration);
        };
        video.currentTime = 1e9;
      } else finish(resolve, video.duration);
    };
    video.onerror = () => finish(reject, new Error("decode"));
    video.src = url;
  });
}

/** A picked video file with its validation state (type, size, then duration). */
function useVideoPick() {
  const [state, setState] = useState({
    file: null,
    problem: null,
    checking: false,
  });
  const token = useRef(0);
  const pick = useCallback(async (file) => {
    const mine = ++token.current;
    if (!file) {
      setState({ file: null, problem: null, checking: false });
      return;
    }
    const problem = videoProblem(file);
    if (problem) {
      setState({ file, problem, checking: false });
      return;
    }
    setState({ file, problem: null, checking: true });
    let result;
    try {
      result = durationProblem(await readVideoDuration(file));
    } catch (error) {
      result =
        error?.message === "timeout"
          ? "We could not check this video's length in time. Try again or choose another file."
          : "This video could not be read in your browser. Try an MP4 or WebM file.";
    }
    if (mine === token.current)
      setState({ file, problem: result, checking: false });
  }, []);
  return [state, pick];
}

function VideoInput({ id, state, onPick, disabled }) {
  return (
    <div className="video-field">
      <label htmlFor={id}>
        Short video (optional) · MP4 or WebM, up to 30 MB and 60 seconds
      </label>
      <input
        id={id}
        type="file"
        accept="video/mp4,video/webm,.mp4,.webm"
        disabled={disabled}
        onChange={(event) => onPick(event.target.files?.[0] || null)}
      />
      {state.file && !state.problem && (
        <small className="video-status">
          {state.checking
            ? "Checking the video…"
            : `Ready: ${state.file.name} · ${humanSize(state.file.size)}`}
        </small>
      )}
      {state.problem && <p className="error">{state.problem}</p>}
    </div>
  );
}

export function SupportVideo({ api, media }) {
  return (
    <figure className="support-video">
      <video
        controls
        preload="metadata"
        src={api.supportMediaUrl(media.media_id)}
        className="video-preview"
      />
      <figcaption>
        <Video size={13} /> {media.filename} · {humanSize(media.size_bytes)}
      </figcaption>
    </figure>
  );
}

/** Retry attaching a video to an existing request of the customer's. */
function AttachVideo({ api, request, onChanged, onError }) {
  const [open, setOpen] = useState(false),
    [video, pick] = useVideoPick(),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(null);
  if (!open)
    return (
      <button className="text-btn" onClick={() => setOpen(true)}>
        <Paperclip size={14} /> Attach a video
      </button>
    );
  async function upload() {
    setBusy(true);
    setError(null);
    try {
      await api.uploadSupportVideo(
        request.request_id,
        video.file,
        video.file.name,
      );
      setOpen(false);
      pick(null);
      onChanged();
    } catch (failure) {
      if (!onError(failure)) setError(friendlyError(failure));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="attach-video">
      <VideoInput
        id={`attach-${request.request_id}`}
        state={video}
        onPick={pick}
        disabled={busy}
      />
      <p className="small-note">
        Record only from a safe place. Do not open equipment, touch damaged
        parts or climb.
      </p>
      {error && (
        <p className="error">The video could not be attached: {error}</p>
      )}
      {busy && (
        <p className="video-status" role="status">
          Uploading video…
        </p>
      )}
      <div className="button-row">
        <button
          className="btn secondary"
          disabled={
            !video.file || video.checking || Boolean(video.problem) || busy
          }
          onClick={upload}
        >
          {busy ? "Uploading video…" : "Upload video"}
        </button>
        <button
          className="text-btn"
          disabled={busy}
          onClick={() => {
            pick(null);
            setOpen(false);
          }}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

function Conversation({
  api,
  request,
  staff,
  onChanged,
  onError,
  onOpenIncident,
  focused,
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  async function submit(event) {
    event.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.replyToSupportRequest(request.request_id, text);
      setText("");
      onChanged();
    } catch (failure) {
      if (!onError?.(failure)) setError(failure);
    } finally {
      setBusy(false);
    }
  }
  const danger = request.priority === "immediate_danger";
  const ref = useRef(null);
  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({ block: "center" });
  }, [focused]);
  return (
    <div
      className={`request-card ${focused ? "focused" : ""}`}
      ref={ref}
      id={`request-${request.request_id}`}
    >
      <div className="section-head">
        <div className="detail-meta">
          <span className={`pill ${request.status === "answered" ? "green" : ""}`}>
            {request.status === "answered" ? "Answered" : "Awaiting review"}
          </span>
          {danger && <span className="pill orange">Immediate danger</span>}
        </div>
        <small>{when(request.created_at)}</small>
      </div>
      <p className="small-note">
        {request.request_label} · With {request.routed_to}
        {staff ? ` · ${request.site_alias} · from ${request.requested_by}` : ""}
      </p>
      <p>{request.description}</p>
      {request.meeting && (
        <div className="meeting-note">
          <CalendarDays size={14} />{" "}
          {staff ? "Customer meeting booked" : "A technician meeting is booked"}{" "}
          for <b>{meetingLabel(request.meeting.start, request.meeting.end)}</b>{" "}
          with {request.meeting.crew_name}.
        </div>
      )}
      {request.media && <SupportVideo api={api} media={request.media} />}
      {!staff && !request.media && !danger && (
        <AttachVideo
          api={api}
          request={request}
          onChanged={onChanged}
          onError={onError}
        />
      )}
      {staff && request.incident_id && onOpenIncident && (
        <button
          className="text-btn"
          onClick={() => onOpenIncident(request.incident_id)}
        >
          Open incident {shortId(request.incident_id)}{" "}
          <ArrowUpRight size={14} />
        </button>
      )}
      {request.replies.map((reply, index) => (
        <div className="reply" key={index}>
          <b>
            {reply.author} ·{" "}
            {reply.kind === "customer"
              ? staff
                ? "Customer follow-up"
                : "Your follow-up"
              : "Support team"}
          </b>
          <p>{reply.text}</p>
        </div>
      ))}
      <form onSubmit={submit}>
        <label>
          {staff ? "Reply to the customer" : "Add a follow-up"}
          <input
            required
            maxLength={1000}
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder={
              staff
                ? "Write a clear next step…"
                : "Add a safe observation or question…"
            }
          />
        </label>
        {error && <p className="error">{errorMessage(error)}</p>}
        <button className="text-btn" disabled={busy}>
          {busy ? "Sending…" : staff ? "Send reply" : "Send follow-up"}{" "}
          <Send size={14} />
        </button>
      </form>
    </div>
  );
}

export function SupportPage({ api, site, onError }) {
  const [types, setTypes] = useState([]);
  const [requestType, setRequestType] = useState("");
  const [description, setDescription] = useState("");
  const [danger, setDanger] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);
  const [phase, setPhase] = useState(null);
  const [video, pickVideo] = useVideoPick();
  const [inputKey, setInputKey] = useState(0);
  const [requests, listError, refresh] = useRequests(api, onError);
  const clearVideo = () => {
    pickVideo(null);
    setInputKey((value) => value + 1);
  };
  useEffect(() => {
    const controller = new AbortController();
    api
      .requestTypes(controller.signal)
      .then((value) => {
        setTypes(value);
        setRequestType(value[0]?.id || "");
      })
      .catch((error) => {
        if (!controller.signal.aborted && !onError(error))
          setNotice({ error: errorMessage(error) });
      });
    return () => controller.abort();
  }, []);
  async function submit(event) {
    event.preventDefault();
    if (!description.trim()) return;
    const file = danger ? null : video.file;
    if (file && (video.checking || video.problem)) return;
    setBusy(true);
    setNotice(null);
    setPhase("Sending your request…");
    let created;
    try {
      created = await api.createSupportRequest({
        site_id: site.site_id,
        request_type: requestType,
        description,
        immediate_danger: danger,
      });
      setDescription("");
      setDanger(false);
      setNotice({
        ok: `Request sent to ${created.routed_to}. You will see the reply here.`,
      });
      refresh();
    } catch (failure) {
      if (!onError(failure)) setNotice({ error: errorMessage(failure) });
      setBusy(false);
      setPhase(null);
      return;
    }
    if (file) {
      setPhase(`Uploading video… (${humanSize(file.size)})`);
      try {
        await api.uploadSupportVideo(created.request_id, file, file.name);
        setNotice({
          ok: `Request and video sent to ${created.routed_to}. You will see the reply here.`,
        });
      } catch (failure) {
        if (!onError(failure))
          setNotice({
            error: `Your request was sent, but the video could not be attached: ${friendlyError(failure)} You can try again with “Attach a video” on this request in your support history.`,
          });
      }
      clearVideo();
      refresh();
    }
    setBusy(false);
    setPhase(null);
  }
  const mine = requests?.filter((request) => request.site_id === site.site_id);
  return (
    <div className="two-col">
      <section className="card form-card">
        <div className="section-head">
          <h2>Tell us what’s happening</h2>
          <LifeBuoy size={26} />
        </div>
        <p className="muted">
          A short description is enough. A person on the right team reviews it
          and replies here; this is not a live call.
        </p>
        <label className="checkbox danger-check">
          <input
            type="checkbox"
            checked={danger}
            onChange={(event) => {
              setDanger(event.target.checked);
              if (event.target.checked) clearVideo();
            }}
          />
          There is smoke, fire, or immediate danger
        </label>
        {danger && (
          <div className="danger-box">
            <b>Move away from danger. Do not go near the equipment.</b>
            <p>
              Call the emergency services on 112 now. Do not wait for this app
              or a technician reply. This is not an emergency response service.
            </p>
          </div>
        )}
        <form onSubmit={submit}>
          <label>
            Installation
            <input value={site.alias} readOnly />
          </label>
          <label>
            Request type
            <select
              value={requestType}
              onChange={(event) => setRequestType(event.target.value)}
            >
              {types.map((type) => (
                <option key={type.id} value={type.id}>
                  {type.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            What have you noticed?
            <textarea
              required
              maxLength={2000}
              rows={4}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="For example: the display has shown a warning since this morning…"
            />
          </label>
          {danger ? (
            <p className="small-note">
              Video is turned off for danger reports. Do not film a dangerous
              situation.
            </p>
          ) : (
            <VideoInput
              key={inputKey}
              id="support-video"
              state={video}
              onPick={pickVideo}
              disabled={busy}
            />
          )}
          <p className="small-note">
            Describe or record only what you can see from a safe place. Do not
            open equipment, touch damaged parts or climb to inspect panels.
          </p>
          {notice?.error && <p className="error">{notice.error}</p>}
          {phase && (
            <p className="video-status" role="status">
              {phase}
            </p>
          )}
          {notice?.ok && <div className="info-box">{notice.ok}</div>}
          <button
            className="btn yellow full"
            disabled={
              busy ||
              !requestType ||
              (!danger &&
                Boolean(video.file) &&
                (video.checking || Boolean(video.problem)))
            }
          >
            {busy
              ? "Sending…"
              : danger
                ? "Record danger report"
                : "Send request"}
            <Send size={17} />
          </button>
        </form>
      </section>
      <section className="card">
        <h3>Your support history</h3>
        {listError && <p className="error">{errorMessage(listError)}</p>}
        {mine?.map((request) => (
          <Conversation
            key={request.request_id}
            api={api}
            request={request}
            onChanged={refresh}
            onError={onError}
          />
        ))}
        {mine && !mine.length && (
          <div className="empty">
            <MessageSquare size={30} />
            <p>No requests yet. We’ll keep your conversation here.</p>
          </div>
        )}
        {!mine && !listError && <div className="empty">Loading…</div>}
      </section>
    </div>
  );
}

export function StaffRequests({ api, onError, focusId, onOpenIncident }) {
  const [requests, error, refresh] = useRequests(api, onError);
  const [waiting, setWaiting] = useState(!focusId);
  const visible = requests?.filter(
    (request) =>
      !waiting ||
      request.status === "awaiting_review" ||
      request.request_id === focusId,
  );
  // Danger reports first, then oldest waiting first.
  visible?.sort(
    (a, b) =>
      (b.priority === "immediate_danger") - (a.priority === "immediate_danger") ||
      a.updated_at.localeCompare(b.updated_at),
  );
  return (
    <section className="card">
      <div className="section-head">
        <div>
          <h2>Customer requests</h2>
          <p className="muted">
            Requests for installations in your authorized scope.
          </p>
        </div>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={waiting}
            onChange={(event) => setWaiting(event.target.checked)}
          />
          Awaiting review only
        </label>
      </div>
      {error && <p className="error">{errorMessage(error)}</p>}
      {visible?.map((request) => (
        <Conversation
          key={request.request_id}
          api={api}
          request={request}
          staff
          onChanged={refresh}
          onError={onError}
          onOpenIncident={onOpenIncident}
          focused={request.request_id === focusId}
        />
      ))}
      {visible && !visible.length && (
        <div className="empty">
          <MessageSquare size={30} />
          <p>No requests {waiting ? "awaiting review" : "yet"}.</p>
        </div>
      )}
      {!visible && !error && <div className="empty">Loading…</div>}
    </section>
  );
}
