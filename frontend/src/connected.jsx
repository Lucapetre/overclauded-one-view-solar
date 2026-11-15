import React, {
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  Sun,
  House,
  Activity,
  ArrowRight,
  ArrowUpRight,
  ChevronRight,
  LogOut,
  Lock,
  Menu,
  RefreshCw,
  Radio,
  BarChart3,
  BookOpen,
  User,
  Database,
  AlertTriangle,
  LifeBuoy,
  MessageSquare,
  BatteryCharging,
  Plug,
  Zap,
  Tickets,
  Users,
  Coins,
  Handshake,
  CalendarClock,
  ListChecks,
} from "lucide-react";
import {
  SolarClient,
  SolarApiError,
  poll,
} from "../../packages/contracts/client";
import {
  chartSegments,
  defaultRange,
  errorMessage,
  label,
  matchesSeries,
  number,
  primaryReadings,
  readings,
  seriesKey,
  sourceInfo,
  unit,
  when,
} from "./telemetry";
import {
  CareCard,
  ContractAndForecast,
  HomeEnergyChart,
  LearnPage,
  StaffRequests,
  SupportPage,
  useEnergy,
} from "./customer";
import { FriendlyEnergy } from "./features";
import { EquipmentCards, ReplayBadge } from "./equipment";
import { NotificationBell } from "./notifications";
import { SavingsCounter } from "./offersSavings";
import { notificationTarget } from "./offersLogic";
import { t as offerText } from "./offersText";
// Shared staff/support styles (e.g. .meeting-note) also used by customer pages.
import "./ops.css";
// Staff pages (and Leaflet) load only for operations accounts.
const lazyOps = (name) =>
  lazy(() => import("./opsPages").then((module) => ({ default: module[name] })));
const RadarOps = lazyOps("RadarOps");
// Ranked queue + map + episode drawer, and the technician agenda (phase d2).
const IncidentsPage = lazy(() =>
  import("./opsQueue").then((module) => ({ default: module.IncidentsPage })),
);
const AgendaPage = lazy(() =>
  import("./opsAgenda").then((module) => ({ default: module.AgendaPage })),
);
const TeamsPage = lazyOps("TeamsPage");
const RevenuePage = lazyOps("RevenuePage");
// Power Block Offers pages load on first visit.
const OffersPage = lazy(() =>
  import("./offersClient").then((module) => ({ default: module.OffersPage })),
);
// Business task planner (Plan page and the Home "Next task" card) loads on first use.
const PlanPage = lazy(() =>
  import("./planner").then((module) => ({ default: module.PlanPage })),
);
const NextTaskCard = lazy(() =>
  import("./planner").then((module) => ({ default: module.NextTaskCard })),
);
const ManagerOffersPage = lazy(() =>
  import("./offersManager").then((module) => ({ default: module.ManagerOffersPage })),
);
import { bottomNav, pagesFor } from "./opsData";
import { words } from "./friendly";
import { total } from "./periods";

const api = new SolarClient(import.meta.env.VITE_API_URL || "");
const roles = {
  customer: "Customer",
  dispatcher: "PPC dispatcher",
  technician: "Assigned technician",
  supervisor: "Manager",
};
const pageIcons = {
  Home: House,
  Plan: CalendarClock,
  Agenda: ListChecks,
  "Area Radar": Radio,
  Incidents: Tickets,
  Teams: Users,
  Revenue: Coins,
  Offers: Handshake,
  Sites: House,
  History: BarChart3,
  Support: LifeBuoy,
  Requests: MessageSquare,
  Learn: BookOpen,
  Account: User,
};

function Pill({ children, tone = "" }) {
  return <span className={`pill ${tone}`}>{children}</span>;
}
function Status({ value }) {
  const names = {
    fresh: "Recent telemetry",
    stale: "Stale telemetry",
    unavailable: "Unavailable",
    future: "Future timestamp",
    unknown_clock: "Replay clock unavailable",
    loading: "Loading",
  };
  return (
    <Pill
      tone={value === "fresh" ? "green" : value === "stale" ? "orange" : ""}
    >
      {names[value] || value.replaceAll("_", " ")}
    </Pill>
  );
}
function ErrorNotice({ error, onRetry }) {
  if (!error) return null;
  return (
    <div role="alert" className="connected-error">
      <AlertTriangle size={19} />
      <div>
        <b>{errorMessage(error)}</b>
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
function HouseScene() {
  return (
    <div className="house-illustration" aria-hidden="true">
      <div className="house-shadow" />
      <div className="house-side" />
      <div className="house-front">
        <div className="window" />
        <div className="door" />
      </div>
      <div className="house-roof">
        <div className="panel-grid">
          {Array.from({ length: 12 }, (_, i) => (
            <i key={i} />
          ))}
        </div>
      </div>
      <div className="house-base" />
    </div>
  );
}

function SignIn({ onSession, initialError }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(initialError);
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const session = await api.login(username.trim(), password);
      setPassword("");
      onSession(session);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="connected-auth">
      <section className="auth-story">
        <a className="brand" href="/">
          <Sun size={32} />
          SolarLenes<span className="brand-dot">®</span>
        </a>
        <div className="eyebrow">YOUR ENERGY, CONNECTED</div>
        <h1>
          A clearer view.
          <br />A brighter day<span className="yellow-dot">.</span>
        </h1>
        <p>
          Understand your solar production, see where your energy goes, and stay
          connected to your installation.
        </p>
        <div className="energy-scene auth-scene">
          <div className="scene-grid" />
          <div className="scene-sun">
            <Sun size={36} />
            <span>
              A little sunshine.
              <br />
              <b>A lot of possibility.</b>
            </span>
          </div>
          <HouseScene />
        </div>
        <div className="auth-foot">
          <Lock size={16} />
          Your account. Your authorized installations.
        </div>
      </section>
      <section className="auth-form">
        <div className="eyebrow">WELCOME TO YOUR WORKSPACE</div>
        <h2>Good to see you.</h2>
        <p className="muted">Sign in with your application account.</p>
        <form onSubmit={submit}>
          <label>
            Username
            <input
              name="username"
              autoComplete="username"
              required
              maxLength={96}
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="e.g. alice"
            />
          </label>
          <label>
            Password
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              required
              maxLength={256}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          <ErrorNotice error={error} />
          <button className="btn yellow full" disabled={busy}>
            {busy ? "Signing in…" : "Sign in to workspace"}
            <ArrowRight size={18} />
          </button>
        </form>
        <p className="small-note">
          Your role and installation access are assigned by your administrator.
        </p>
        <div className="auth-demo">
          <b>Exploring the full product journey?</b>
          <p>
            Try the separate planning, support and dispatch simulation with
            fictional accounts.
          </p>
          <a className="text-btn" href="/demo/">
            Explore workflow demo <ArrowUpRight size={15} />
          </a>
        </div>
      </section>
    </div>
  );
}

export default function ConnectedApp() {
  const [session, setSession] = useState(undefined);
  const [authError, setAuthError] = useState(null);
  const [scope, setScope] = useState({ sites: [], providers: [], areas: [] });
  const [scopeReady, setScopeReady] = useState(false);
  const [scopeError, setScopeError] = useState(null);
  const [records, setRecords] = useState({});
  const [areaRecords, setAreaRecords] = useState({});
  const [siteId, setSiteId] = useState("");
  const [page, setPage] = useState("Home");
  const [menu, setMenu] = useState(false);
  const [reload, setReload] = useState(0);
  // Cross-page focus: map → incidents of a site; request ↔ incident links.
  const [incidentSite, setIncidentSite] = useState(null);
  const [incidentFocus, setIncidentFocus] = useState(null);
  const [requestFocus, setRequestFocus] = useState(null);
  // Notification link → item to highlight on the Offers page.
  const [offerFocus, setOfferFocus] = useState(null);
  const [bellNudge, setBellNudge] = useState(0);
  // Analytical clock (live wall time or the local replay scenario), all roles.
  const [clock, setClock] = useState(null);
  const expire = useCallback((error) => {
    if (error instanceof SolarApiError && error.status === 401) {
      setSession(null);
      setScope({ sites: [], providers: [], areas: [] });
      setScopeReady(false);
      setRecords({});
      setAreaRecords({});
      setAuthError(null);
      return true;
    }
    return false;
  }, []);
  const acceptSession = useCallback((value) => {
    setScope({ sites: [], providers: [], areas: [] });
    setRecords({});
    setAreaRecords({});
    setScopeReady(false);
    setSiteId("");
    setIncidentSite(null);
    setIncidentFocus(null);
    setRequestFocus(null);
    setOfferFocus(null);
    setClock(null);
    setSession(value);
    setPage(pagesFor(value.user.role)[0]);
    const path = value.user.role === "customer" ? "/consumer" : "/ops";
    if (location.pathname !== path) history.replaceState(null, "", path);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    api
      .me(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) acceptSession(value);
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setSession(null);
          if (!(error instanceof SolarApiError && error.status === 401))
            setAuthError(error);
        }
      });
    return () => controller.abort();
  }, [acceptSession]);
  const user = session?.user;
  useEffect(() => {
    if (!user) return;
    return poll(
      async (signal) => {
        const [sites, providers, areas] = await Promise.all([
          api.sites(signal),
          api.providerSites(signal),
          user.role === "customer" ? Promise.resolve([]) : api.areas(signal),
        ]);
        return { sites, providers, areas };
      },
      (value) => {
        setScope((previous) =>
          JSON.stringify(previous) === JSON.stringify(value) ? previous : value,
        );
        setScopeReady(true);
        setScopeError(null);
        setSiteId((previous) =>
          value.sites.some((site) => site.site_id === previous)
            ? previous
            : value.providers[0]?.site_id || value.sites[0]?.site_id || "",
        );
      },
      (error) => {
        if (!expire(error)) {
          setScopeReady(true);
          setScopeError(error);
        }
      },
    );
  }, [user?.user_id, reload, expire]);
  useEffect(() => {
    if (!user) return;
    return poll(
      (signal) => api.clock(signal),
      (value) =>
        setClock((previous) =>
          JSON.stringify(previous) === JSON.stringify(value) ? previous : value,
        ),
      (error) => {
        if (!expire(error)) setClock(null);
      },
    );
  }, [user?.user_id, expire]);
  const providers = useMemo(
    () =>
      Object.fromEntries(scope.providers.map((site) => [site.site_id, site])),
    [scope.providers],
  );
  const aliases = useMemo(
    () => Object.fromEntries(scope.areas.map((area) => [area.area_id, area.alias])),
    [scope.areas],
  );
  useEffect(() => {
    if (!user || !scope.sites.length) return;
    return poll(
      async (signal) => {
        const siteResults = await Promise.all(
          scope.sites.map(async (site) => {
            const provider = Boolean(providers[site.site_id]);
            try {
              return [
                site.site_id,
                {
                  provider,
                  data: await (provider
                    ? api.providerLatest(site.site_id, signal)
                    : api.latest(site.site_id, signal)),
                  refreshedAt: new Date().toISOString(),
                },
              ];
            } catch (error) {
              if (error instanceof SolarApiError && error.status === 401)
                throw error;
              return [site.site_id, { provider, error }];
            }
          }),
        );
        const areaResults = await Promise.all(
          scope.areas.map(async (area) => {
            try {
              return [
                area.area_id,
                { data: await api.areaSummary(area.area_id, signal) },
              ];
            } catch (error) {
              if (error instanceof SolarApiError && error.status === 401)
                throw error;
              return [area.area_id, { error }];
            }
          }),
        );
        return { siteResults, areaResults };
      },
      ({ siteResults, areaResults }) => {
        setRecords((previous) =>
          Object.fromEntries(
            siteResults.map(([id, value]) => [
              id,
              value.error ? { ...previous[id], ...value } : value,
            ]),
          ),
        );
        setAreaRecords(Object.fromEntries(areaResults));
      },
      (error) => {
        if (!expire(error)) setScopeError(error);
      },
    );
  }, [user?.user_id, scope.sites, scope.areas, providers, reload, expire]);
  async function logout() {
    try {
      await api.logout();
      expire(
        new SolarApiError(401, {
          code: "signed_out",
          message: "",
          request_id: "",
        }),
      );
    } catch (error) {
      if (!expire(error)) setScopeError(error);
    }
  }
  if (session === undefined)
    return (
      <div className="app-loading">
        <Sun size={36} />
        <h2>Connecting your workspace…</h2>
      </div>
    );
  if (!session)
    return (
      <SignIn
        key={authError?.message || "login"}
        onSession={acceptSession}
        initialError={authError}
      />
    );
  const customer = user.role === "customer";
  const pages = pagesFor(user.role);
  const accountType = customer ? user.account_type || "home" : "home";
  const active = pages.includes(page) ? page : pages[0];
  const current = scope.sites.find((site) => site.site_id === siteId);
  const record = records[siteId];
  const info = sourceInfo(record);
  const refreshInterrupted = Boolean(
    scopeError || Object.values(records).some((item) => item.error),
  );
  const mobileNav = bottomNav(pages, active);
  const opsPage = ["Agenda", "Incidents", "Teams", "Revenue", "Requests", "Offers"].includes(active);
  function navigate(next) {
    setPage(next);
    setMenu(false);
    if (next !== "Incidents") setIncidentSite(null);
    if (next !== "Requests") setRequestFocus(null);
    if (next !== "Offers") setOfferFocus(null);
  }
  function openNotification(link) {
    const target = notificationTarget(link, user.role);
    if (!target || !pages.includes(target.page)) return;
    navigate(target.page);
    setOfferFocus(target.focus);
  }
  function selectSite(id) {
    if (!scope.sites.some((site) => site.site_id === id)) return;
    setSiteId(id);
    navigate(customer ? "Home" : "Sites");
  }
  function openSiteIncidents(id, alias) {
    navigate("Incidents");
    setIncidentSite({ id, alias });
  }
  function openIncident(id) {
    navigate("Incidents");
    setIncidentSite(null);
    setIncidentFocus(id);
  }
  function openRequest(id) {
    if (!pages.includes("Requests")) return;
    navigate("Requests");
    setRequestFocus(id);
  }
  const retry = () => setReload((value) => value + 1);
  return (
    <div className="app connected-app">
      <aside className={`sidebar ${menu ? "mobile-open" : ""}`}>
        <a className="brand" href={customer ? "/consumer" : "/ops"}>
          <Sun size={30} strokeWidth={1.7} />
          SolarLenes<span className="brand-dot">®</span>
        </a>
        <div className="workspace-label">
          {customer ? "YOUR ENERGY WORKSPACE" : "PPC OPERATIONS"}
          <span>01</span>
        </div>
        <nav>
          {pages.map((name) => {
            const Icon = pageIcons[name];
            return (
              <button
                key={name}
                className={`nav-item ${active === name ? "active" : ""}`}
                onClick={() => navigate(name)}
              >
                <Icon size={19} />
                <span>{name}</span>
                {active === name && <span className="active-dot" />}
              </button>
            );
          })}
        </nav>
        <div className="sidebar-bottom">
          <div className="side-note">
            <div className="orbit-small">
              <Sun size={27} />
            </div>
            <h3>
              A brighter way
              <br />
              to understand energy.
            </h3>
            <p>One account. Your connected sites.</p>
            <a href="/demo/">
              Explore workflow demo <ArrowUpRight size={16} />
            </a>
          </div>
          <div className="system-status">
            <span className={refreshInterrupted ? "paused-dot" : "green-dot"} />
            {refreshInterrupted ? "Refresh interrupted" : "API connected"}
            <span>v1.0</span>
          </div>
          <button className="sidebar-user" onClick={() => navigate("Account")}>
            <span className="avatar">
              {user.username.slice(0, 2).toUpperCase()}
            </span>
            <span>
              <b>{user.username}</b>
              <small>{roles[user.role]}</small>
            </span>
            <ChevronRight size={16} />
          </button>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <button
            className="icon-btn mobile-menu"
            aria-label="Toggle navigation"
            onClick={() => setMenu(!menu)}
          >
            <Menu />
          </button>
          <a className="mobile-brand" href={customer ? "/consumer" : "/ops"}>
            SolarLenes
          </a>
          <div className="breadcrumb">
            Workspace <ChevronRight size={13} />
            <b>{active}</b>
          </div>
          <div className="header-actions">
            <span className="demo-tag">
              <span />
              CONNECTED WORKSPACE
            </span>
            <NotificationBell
              api={api}
              userId={user.user_id}
              onError={expire}
              onOpen={openNotification}
              nudge={bellNudge}
            />
            <button
              className="icon-btn"
              aria-label="Refresh data"
              onClick={retry}
            >
              <RefreshCw size={18} />
            </button>
            <button
              className="account-button"
              onClick={() => navigate("Account")}
            >
              <span className="avatar small">
                {user.username.slice(0, 2).toUpperCase()}
              </span>
              <span>{user.username}</span>
            </button>
            <button
              className="icon-btn"
              aria-label="Sign out"
              title="Sign out"
              onClick={logout}
            >
              <LogOut size={18} />
            </button>
          </div>
        </header>
        <ReplayBadge clock={clock} />
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                {customer
                  ? "A LITTLE SUN. A CLEARER PICTURE."
                  : "CONNECTED SITES. INFORMED DECISIONS."}
              </div>
              <h1>
                {active === "Home"
                  ? `Your energy, ${user.username}`
                  : active === "Plan"
                    ? "Run flexible work at the right time"
                  : active === "Area Radar"
                    ? "Your monitored installations"
                    : active === "Agenda"
                      ? "Your visits for today"
                    : active === "Incidents"
                      ? "Every case, in the right order"
                      : active === "Teams"
                        ? "Plan teams and assignments"
                        : active === "Revenue"
                          ? "Estimated revenue"
                    : active === "Offers"
                      ? customer
                        ? offerText("page.client.title")
                        : offerText("page.manager.title")
                    : active === "Sites"
                      ? "Installation detail"
                      : active === "History"
                        ? "Every reading has a story"
                        : active === "Learn"
                          ? "Learn a little, earn a little"
                          : active === "Support"
                            ? "We’re here to help"
                            : active === "Requests"
                              ? "Customer conversations"
                              : "Your workspace, your way"}
                <span className="yellow-dot">.</span>
              </h1>
              <p>
                {active === "Plan"
                  ? "Your tasks, a recommended time and the evidence behind it. Costs are estimates; you decide."
                  : active === "Area Radar"
                  ? "Map, forecast and source coverage across your authorized scope. Equipment health remains unassessed."
                  : active === "Agenda"
                    ? "Your crew's planned visits in order, with progress you report. Synthetic planning inputs; times are estimates."
                  : active === "Incidents"
                    ? "Correlated synthetic episodes in your scope, safety and deadlines first, next to the same cases on the map. Each change is kept in the log."
                    : active === "Teams"
                      ? "Propose, review and apply a crew plan, then follow who is on which case. Synthetic crews, shifts and travel times."
                      : active === "Revenue"
                        ? "A monthly estimate from synthetic billing profiles. Not invoices."
                  : active === "Offers"
                    ? customer
                      ? offerText("page.client.lead")
                      : offerText("page.manager.lead")
                        : active === "Requests"
                          ? "Customer requests in your scope, with their videos and booked meetings."
                  : active === "Learn"
                    ? "Short interactive lessons. Pass the mini test to earn a small reward."
                    : active === "Support"
                      ? "One request, sent to the right team."
                      : customer
                        ? accountType === "business"
                          ? "What your business produces, uses and sends to the grid, in plain words."
                          : "What your home produces, uses and sends to the grid, in plain words."
                        : "A shared view of the installation, with its source and quality always in sight."}
              </p>
            </div>
            {scope.sites.length > 0 && !opsPage && active !== "Account" && (
              <label className="site-selector">
                <House size={15} />
                <select
                  aria-label="Select installation"
                  value={siteId}
                  onChange={(event) => setSiteId(event.target.value)}
                >
                  {scope.sites.map((site) => (
                    <option key={site.site_id} value={site.site_id}>
                      {site.alias}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          <ErrorNotice error={scopeError} onRetry={retry} />
          {!scopeReady ? (
            <section className="card empty">
              Loading your authorized installations…
            </section>
          ) : !scope.sites.length &&
            !["Account", "Learn", "Requests", "Agenda", "Incidents", "Teams", "Revenue", "Offers"].includes(
              active,
            ) ? (
            <section className="card empty">
              <House size={36} />
              <h2>No installations assigned yet.</h2>
              <p>
                Your account is active. Ask your administrator to grant site
                access.
              </p>
            </section>
          ) : (
            <Suspense
              fallback={<section className="card empty">Loading…</section>}
            >
              {active === "Area Radar" && (
                <RadarOps
                  api={api}
                  aliases={aliases}
                  scopeSites={scope.sites.length}
                  onOpenSite={selectSite}
                  onOpenIncidents={openSiteIncidents}
                  onError={expire}
                  reload={reload}
                />
              )}
              {active === "Area Radar" && (
                <Radar
                  scope={scope}
                  records={records}
                  areaRecords={areaRecords}
                  onSelect={selectSite}
                />
              )}
              {(active === "Home" || active === "Sites") && current && (
                <SiteHome
                  site={current}
                  record={record}
                  onHistory={() => navigate("History")}
                  retry={retry}
                  customer={customer}
                  accountType={accountType}
                  navigate={navigate}
                  onError={expire}
                  userId={user.user_id}
                  showOffers={pages.includes("Offers")}
                  clock={clock}
                />
              )}
              {active === "Plan" && customer && current && (
                <PlanPage
                  key={siteId}
                  api={api}
                  site={current}
                  clock={clock}
                  onError={expire}
                />
              )}
              {active === "History" &&
                current &&
                (record?.data ? (
                  <History
                    key={siteId}
                    site={current}
                    record={record}
                    reload={reload}
                    onError={expire}
                  />
                ) : (
                  <section className="card empty">
                    <ErrorNotice error={record?.error} onRetry={retry} />
                    Waiting for source data…
                  </section>
                ))}
              {active === "Learn" && <LearnPage api={api} onError={expire} />}
              {active === "Support" && current && (
                <SupportPage
                  key={siteId}
                  api={api}
                  site={current}
                  onError={expire}
                />
              )}
              {active === "Incidents" && (
                <IncidentsPage
                  api={api}
                  user={user}
                  aliases={aliases}
                  siteFilter={incidentSite}
                  onClearSite={() => setIncidentSite(null)}
                  focusIncident={incidentFocus}
                  onFocusHandled={() => setIncidentFocus(null)}
                  onOpenRequest={openRequest}
                  onOpenPlan={pages.includes("Teams") ? () => navigate("Teams") : null}
                  onError={expire}
                  reload={reload}
                />
              )}
              {active === "Agenda" && (
                <AgendaPage api={api} onError={expire} reload={reload} />
              )}
              {active === "Teams" && (
                <TeamsPage
                  api={api}
                  user={user}
                  aliases={aliases}
                  onOpenIncident={openIncident}
                  onError={expire}
                  reload={reload}
                />
              )}
              {active === "Revenue" && (
                <RevenuePage api={api} onError={expire} reload={reload} />
              )}
              {active === "Offers" && customer && (
                <OffersPage
                  api={api}
                  user={user}
                  onError={expire}
                  focus={offerFocus}
                  onFocusHandled={() => setOfferFocus(null)}
                  onActivity={() => setBellNudge((value) => value + 1)}
                />
              )}
              {active === "Offers" && user.role === "supervisor" && (
                <ManagerOffersPage
                  api={api}
                  areas={scope.areas}
                  onError={expire}
                  reload={reload}
                  focus={offerFocus}
                  onFocusHandled={() => setOfferFocus(null)}
                />
              )}
              {active === "Requests" && (
                <StaffRequests
                  key={requestFocus || "all"}
                  api={api}
                  onError={expire}
                  focusId={requestFocus}
                  onOpenIncident={openIncident}
                />
              )}
              {active === "Account" && (
                <section className="card connected-account">
                  <div className="avatar">
                    {user.username.slice(0, 2).toUpperCase()}
                  </div>
                  <h2>{user.username}</h2>
                  <Pill>
                    {customer
                      ? accountType === "business"
                        ? "Business customer"
                        : "Home customer"
                      : roles[user.role]}
                  </Pill>
                  {!customer && scope.areas.length > 0 && (
                    <div className="list-row">
                      <b>
                        {user.role === "supervisor"
                          ? "Areas you manage"
                          : "Areas in scope"}
                      </b>
                      <span>
                        {scope.areas.map((area) => area.alias).join(", ")}
                      </span>
                    </div>
                  )}
                  <div className="list-row">
                    <b>Installation access</b>
                    <span>
                      {scope.sites.length} assigned{" "}
                      {scope.sites.length === 1 ? "site" : "sites"}
                    </span>
                  </div>
                  <div className="list-row">
                    <b>Time display</b>
                    <span>Europe/Bucharest</span>
                  </div>
                  <div className="list-row">
                    <b>Session expires</b>
                    <span>{when(session.expires_at)}</span>
                  </div>
                  <p className="muted">
                    Your administrator manages your password, access and
                    account type (home or business). Source
                    labels distinguish synthetic replay from live readings.
                  </p>
                  <button className="btn secondary" onClick={logout}>
                    Sign out <LogOut size={16} />
                  </button>
                </section>
              )}
            </Suspense>
          )}
          <footer>
            <span>
              <Sun size={15} />
              SolarLenes <span className="footer-divider">/</span> Energy, in
              your hands.
            </span>
            <span>
              {info.mode === "unknown"
                ? "Source-aware data"
                : `${info.mode} source`}{" "}
              · Europe/Bucharest · No device control
            </span>
          </footer>
        </main>
      </div>
      <nav className="bottom-nav" aria-label="Main pages">
        {mobileNav.items.map((name) => {
          const Icon = pageIcons[name];
          return (
            <button
              key={name}
              onClick={() => navigate(name)}
              className={active === name ? "active" : ""}
              aria-current={active === name ? "page" : undefined}
            >
              <Icon size={20} />
              <span>{name}</span>
            </button>
          );
        })}
        {mobileNav.more && (
          <button
            onClick={() => setMenu(!menu)}
            className={mobileNav.moreActive ? "active" : ""}
            aria-label="More pages"
            aria-expanded={menu}
          >
            <Menu size={20} />
            <span>{mobileNav.moreActive ? active : "More"}</span>
          </button>
        )}
      </nav>
    </div>
  );
}

function SiteHome({
  site,
  record,
  onHistory,
  retry,
  customer,
  accountType,
  navigate,
  onError,
  userId,
  showOffers,
  clock,
}) {
  const w = words(accountType);
  const clockNudge =
    clock?.mode === "scenario" ? Date.parse(clock.analytical_now) || 0 : 0;
  const today = useEnergy(api, site, record, "Today", onError);
  const info = sourceInfo(record);
  const data = record?.data;
  const primary = primaryReadings(data, record?.provider);
  const all = readings(data, record?.provider);
  const main = primary[0];
  const home = primary[1];
  const exporting = primary[3];
  return (
    <>
      <ErrorNotice error={record?.error} onRetry={retry} />
      <div className="source-banner">
        <div>
          <Database size={17} />
          <b>
            {info.mode === "synthetic"
              ? "Synthetic replay"
              : info.mode === "replay"
                ? "Recorded replay"
                : info.mode === "live"
                  ? "Live source"
                  : "Connecting source"}
          </b>
          <span>{when(info.time)}</span>
        </div>
        <Status value={info.status} />
      </div>
      {customer && showOffers && (
        <SavingsCounter
          api={api}
          userId={userId}
          onError={onError}
          compact
          onOpenOffers={() => navigate("Offers")}
        />
      )}
      {customer && (
        <>
          <EquipmentCards
            key={site.site_id}
            api={api}
            siteId={site.site_id}
            onError={onError}
            nudge={clockNudge}
          />
          <Suspense fallback={null}>
            <NextTaskCard
              key={site.site_id}
              api={api}
              site={site}
              clock={clock}
              onError={onError}
              onOpenPlan={() => navigate("Plan")}
            />
          </Suspense>
        </>
      )}
      <div className="home-grid">
        <section className="energy-hero">
          <div className="section-head">
            <div>
              <div className="eyebrow">{w.eyebrow}</div>
              <h2>{site.alias}</h2>
            </div>
            <Pill tone="dark">
              {record?.provider
                ? data?.site.provider || "Provider source"
                : "Normalized telemetry"}
            </Pill>
          </div>
          <div className="energy-scene">
            <div className="scene-grid" />
            <div className="scene-sun">
              <Sun size={30} />
              <span>
                {main?.name || "Solar production"}
                <b>
                  {main?.value == null ? "Unavailable" : number(main.value)}{" "}
                  <small>{main?.value != null && main.unit}</small>
                </b>
              </span>
            </div>
            <div className="flow-track solar-track">
              <i />
              <i />
              <i />
            </div>
            <HouseScene />
            <div className="scene-home">
              <House size={22} />
              <span>
                {w.consumption}
                <b>
                  {home?.value == null ? "Unavailable" : number(home.value)}{" "}
                  <small>{home?.value != null && home.unit}</small>
                </b>
              </span>
            </div>
            <div className="scene-grid-export">
              <Plug size={23} />
              <span>
                Grid export
                <b>
                  {exporting?.value == null
                    ? "Unavailable"
                    : number(exporting.value)}{" "}
                  <small>{exporting?.value != null && exporting.unit}</small>
                </b>
              </span>
            </div>
          </div>
          <div className="hero-foot">
            <span>
              {record?.error
                ? "Refresh failed; displayed readings may be older"
                : "Readings retain their original measurement boundaries"}
            </span>
            <span>
              <Activity size={14} />
              Refreshes every 5 seconds
            </span>
          </div>
        </section>
        <section className="solar-opportunity connected-opportunity">
          <span className="opportunity-icon">
            <BarChart3 size={25} />
          </span>
          <div className="eyebrow">TODAY, IN PLAIN WORDS</div>
          <FriendlyEnergy
            kwh={today.series ? total(today.series.export) : null}
            subject="Today’s export"
            accountType={accountType}
            loading={today.loading}
          />
          <button className="btn dark" onClick={onHistory}>
            Explore history <ArrowRight size={17} />
          </button>
          <p className="small-note">
            Missing data remains unavailable. A recent feed does not certify
            that equipment is healthy.
          </p>
        </section>
      </div>
      <div className="connected-metrics">
        {primary.map((reading, index) => {
          const Icon = [Sun, House, Plug, Zap, BatteryCharging, Activity][
            index
          ];
          return (
            <section className="card metric-card" key={reading.key}>
              <div className="section-head">
                <Icon size={20} />
                <Pill>{reading.state.replaceAll("_", " ")}</Pill>
              </div>
              <h3>
                {index === 1 && customer ? w.consumption : reading.name}
              </h3>
              <div
                className={`metric-value ${reading.value == null ? "missing-value" : ""}`}
              >
                {number(reading.value)}{" "}
                <small>{reading.value != null && reading.unit}</small>
              </div>
              {!customer && <p>{reading.detail}</p>}
              <small>
                {reading.time ? when(reading.time) : "No reading supplied"}
              </small>
            </section>
          );
        })}
      </div>
      {!data && (
        <section className="card empty">
          Loading installation telemetry…
        </section>
      )}
      {customer && data && (
        <>
          <div className="lower-grid">
            <HomeEnergyChart
              api={api}
              site={site}
              record={record}
              accountType={accountType}
              onError={onError}
            />
            <CareCard
              record={record}
              accountType={accountType}
              onLearn={() => navigate("Learn")}
              onSupport={() => navigate("Support")}
            />
          </div>
          <ContractAndForecast
            api={api}
            site={site}
            accountType={accountType}
            onError={onError}
          />
        </>
      )}
      {!customer && data && (
        <section className="card connected-readings">
          <div className="section-head">
            <div>
              <h3>Measurements and source context</h3>
              <p className="muted">
                Each sensor and device retains its own time, unit and
                availability.
              </p>
            </div>
            <button className="text-btn" onClick={onHistory}>
              View history <ArrowUpRight size={16} />
            </button>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Measurement</th>
                  <th>Value</th>
                  <th>Quality</th>
                  <th>Source interval end</th>
                </tr>
              </thead>
              <tbody>
                {all.map((reading) => (
                  <tr key={reading.key}>
                    <td>
                      <b>{reading.name}</b>
                      <small>
                        {reading.frame
                          ? [
                              reading.frame.endpoint_key,
                              reading.frame.device_id,
                              reading.frame.channel,
                            ]
                              .filter(Boolean)
                              .join(" · ")
                          : reading.detail}
                      </small>
                    </td>
                    <td>
                      {number(reading.value)}{" "}
                      {reading.value != null && reading.unit}
                    </td>
                    <td>
                      <Pill>{reading.state.replaceAll("_", " ")}</Pill>
                      <small>{reading.detail}</small>
                      <small>{reading.flags.join(" · ")}</small>
                    </td>
                    <td>{when(reading.time)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      {!customer && record?.provider && data && (
        <section className="card mt">
          <h3>Source reporting health</h3>
          <p className="muted">
            Freshness is evaluated against the displayed replay time, separately
            from equipment condition.
          </p>
          {data.source_health.map((source) => (
            <div
              className="list-row source-health"
              key={`${source.endpoint_key}:${source.device_key}`}
            >
              <div>
                <b>{source.endpoint_key}</b>
                <small>{source.notes || "Source reporting status"}</small>
              </div>
              <Pill
                tone={source.freshness_status.includes("stale") ? "orange" : ""}
              >
                {source.freshness_status.replaceAll("_", " ")}
              </Pill>
              <span>
                {source.latest_source_ms
                  ? when(source.latest_source_ms)
                  : "No accepted readings"}
              </span>
            </div>
          ))}
        </section>
      )}
    </>
  );
}

function Radar({ scope, records, areaRecords, onSelect }) {
  const [filter, setFilter] = useState("");
  const visible = scope.sites.filter(
    (site) => !filter || (site.area_id || "unassigned") === filter,
  );
  const groups = [
    ...new Set(scope.sites.map((site) => site.area_id || "unassigned")),
  ];
  return (
    <>
      <div className="connected-area-grid">
        {groups.map((id) => {
          const sites = scope.sites.filter(
            (site) => (site.area_id || "unassigned") === id,
          );
          const summary = areaRecords[id]?.data;
          const recent =
            summary?.recent_sites ??
            sites.filter(
              (site) => sourceInfo(records[site.site_id]).status === "fresh",
            ).length;
          return (
            <button
              key={id}
              className={`card area-card connected-area ${filter === id ? "selected" : ""}`}
              onClick={() => setFilter(filter === id ? "" : id)}
            >
              <div className="section-head">
                <Radio size={20} />
                <Pill>
                  {id === "unassigned"
                    ? "Topology unknown"
                    : summary?.area.topology_mode || "Scoped area"}
                </Pill>
              </div>
              <h3>
                {summary?.area.alias ||
                  (id === "unassigned" ? "Unassigned installations" : id)}
              </h3>
              <strong>
                {recent}
                <span> / {summary?.monitored_sites ?? sites.length}</span>
              </strong>
              <p>monitored sites have recent telemetry</p>
              {areaRecords[id]?.error && (
                <p className="error">Area summary could not refresh</p>
              )}
            </button>
          );
        })}
      </div>
      <section className="card mt">
        <div className="section-head">
          <div>
            <h2>Installation coverage radar</h2>
            <p className="muted">
              Only authorized installations appear here. Missing inputs remain
              unknown.
            </p>
          </div>
          <select
            aria-label="Filter area"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          >
            <option value="">All assigned areas</option>
            {groups.map((id) => (
              <option key={id} value={id}>
                {id === "unassigned" ? "Unassigned" : id}
              </option>
            ))}
          </select>
        </div>
        <div className="installation-grid">
          {visible.map((site) => {
            const record = records[site.site_id];
            const info = sourceInfo(record);
            return (
              <button
                key={site.site_id}
                className={`installation ${info.status}`}
                onClick={() => onSelect(site.site_id)}
              >
                <div>
                  <Sun size={22} />
                  <Status
                    value={record?.error ? "Refresh failed" : info.status}
                  />
                </div>
                <h3>{site.alias}</h3>
                <p>
                  {record?.provider
                    ? record.data?.site.provider || "Provider source"
                    : "Normalized telemetry"}
                </p>
                <small>{when(info.time)}</small>
                <span>
                  Open installation <ArrowUpRight size={16} />
                </span>
              </button>
            );
          })}
        </div>
        <div className="info-box">
          Coverage indicates reporting availability. Incident diagnosis, safety
          ranking and dispatch decisions are not inferred from these readings.
        </div>
      </section>
    </>
  );
}

function History({ site, record, reload, onError }) {
  const choices = readings(record.data, record.provider);
  const [selectedKey, setSelectedKey] = useState(
    primaryReadings(record.data, record.provider)[0]?.key ||
      choices[0]?.key ||
      "pv_power",
  );
  const [range, setRange] = useState(() => defaultRange(record));
  const [offset, setOffset] = useState(0);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const selected =
    choices.find((reading) => reading.key === selectedKey) || choices[0];
  useEffect(() => {
    if (!selected) {
      setResult({ points: [], observations: null });
      return;
    }
    const controller = new AbortController();
    async function load() {
      setBusy(true);
      setError(null);
      setResult(null);
      try {
        const from = new Date(`${range.from}Z`),
          to = new Date(`${range.to}Z`);
        if (
          !Number.isFinite(from.getTime()) ||
          !Number.isFinite(to.getTime()) ||
          to <= from
        )
          throw new Error("Choose a valid start and end time in UTC.");
        if (record.provider) {
          const frame = selected.frame;
          const query = {
            from: from.toISOString(),
            to: to.toISOString(),
            metric: frame.metric_name,
            endpoint: frame.endpoint_key,
            device: frame.device_id || undefined,
            channel: frame.channel || undefined,
          };
          const [firstPage, observations] = await Promise.all([
            api.providerFrames(
              site.site_id,
              { ...query, limit: 1000, offset: 0 },
              controller.signal,
            ),
            api.providerObservations(
              site.site_id,
              { ...query, limit: 50, offset },
              controller.signal,
            ),
          ]);
          const frames = [...firstPage.items];
          let page = firstPage;
          while (frames.length < page.total && page.items.length) {
            page = await api.providerFrames(
              site.site_id,
              { ...query, limit: 1000, offset: frames.length },
              controller.signal,
            );
            frames.push(...page.items);
          }
          if (!controller.signal.aborted)
            setResult({
              points: frames
                .filter((item) => matchesSeries(item, frame))
                .map((item) => ({
                  time: item.frame_start_utc,
                  end: item.frame_end_utc,
                  value: item.value,
                  coverage: item.coverage_ratio,
                  status: item.frame_status,
                })),
              observations,
            });
        } else {
          const history = await api.history(
            site.site_id,
            from.toISOString(),
            to.toISOString(),
            "1h",
            controller.signal,
          );
          if (!controller.signal.aborted)
            setResult({
              points: history.points.map((point) => ({
                time: point.interval_start,
                end: point.interval_end,
                value: point.measurements[selected.key]?.value ?? null,
                coverage: point.coverage[selected.key] || 0,
                status:
                  point.measurements[selected.key]?.availability || "missing",
              })),
              observations: null,
            });
        }
      } catch (failure) {
        if (!controller.signal.aborted && !onError(failure)) setError(failure);
      } finally {
        if (!controller.signal.aborted) setBusy(false);
      }
    }
    load();
    return () => controller.abort();
  }, [
    site.site_id,
    selectedKey,
    range.from,
    range.to,
    offset,
    reload,
    onError,
  ]);
  const observations = result?.observations;
  return (
    <>
      <section className="card history-controls">
        <label>
          Measurement
          <select
            aria-label="History measurement"
            value={selected?.key || ""}
            onChange={(event) => {
              setSelectedKey(event.target.value);
              setOffset(0);
            }}
          >
            {choices.map((reading) => (
              <option key={reading.key} value={reading.key}>
                {reading.name}
                {reading.frame?.channel ? ` · ${reading.frame.channel}` : ""}
                {reading.frame?.device_id
                  ? ` · ${reading.frame.device_id}`
                  : ""}
              </option>
            ))}
          </select>
        </label>
        <label>
          From (UTC)
          <input
            aria-label="History from UTC"
            type="datetime-local"
            value={range.from}
            onChange={(event) => {
              setRange({ ...range, from: event.target.value });
              setOffset(0);
            }}
          />
        </label>
        <label>
          To (UTC)
          <input
            aria-label="History to UTC"
            type="datetime-local"
            value={range.to}
            onChange={(event) => {
              setRange({ ...range, to: event.target.value });
              setOffset(0);
            }}
          />
        </label>
      </section>
      <ErrorNotice error={error} />
      <section className="card mt">
        <div className="section-head">
          <div>
            <h3>{selected?.name || "Measurement history"}</h3>
            <p className="muted">
              {record.provider
                ? "Original 15-minute frames; source cadence and coverage are preserved."
                : "Hourly averages over available coverage. Missing hours stay empty."}
            </p>
          </div>
          <Pill>
            {busy
              ? "Loading…"
              : `${result?.points.filter((point) => point.value != null).length || 0} available intervals`}
          </Pill>
        </div>
        {busy ? (
          <div className="empty">Loading source history…</div>
        ) : (
          result && (
            <HistoryChart points={result.points} displayUnit={selected?.unit} />
          )
        )}
        <p className="small-note">
          Gaps are not interpolated. Values from different devices, channels or
          measurement boundaries are never combined in this chart.
        </p>
      </section>
      {observations && (
        <section className="card mt">
          <div className="section-head">
            <div>
              <h3>Source observations</h3>
              <p className="muted">
                Original requirement class, measurement boundary and time basis.
              </p>
            </div>
            <Pill>{observations.total} observations</Pill>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Effective time</th>
                  <th>Value</th>
                  <th>Classification</th>
                  <th>Availability and origin</th>
                  <th>Time and boundary</th>
                </tr>
              </thead>
              <tbody>
                {observations.items.map((item) => (
                  <tr key={item.obs_id}>
                    <td>
                      {when(item.effective_time_utc)}
                      <small>
                        {item.device_id || "Site-level source"}
                        {item.channel ? ` · ${item.channel}` : ""}
                      </small>
                    </td>
                    <td>
                      {item.canonical_text || number(item.canonical_value)}{" "}
                      {item.canonical_value != null &&
                        unit(item.canonical_unit)}
                    </td>
                    <td>{item.requirement_class.replaceAll("_", " ")}</td>
                    <td>
                      <Pill>
                        {item.is_conflicted
                          ? "conflicted"
                          : item.availability_status}
                      </Pill>
                      <small>{item.value_origin.replaceAll("_", " ")}</small>
                      <small>{item.quality_flags}</small>
                    </td>
                    <td>
                      {item.boundary || "Unspecified"}
                      <small>
                        {item.effective_time_basis.replaceAll("_", " ")}
                      </small>
                      <small>
                        {item.measurement_time_utc
                          ? `Measured ${when(item.measurement_time_utc)}`
                          : "Sensor measurement time not supplied"}
                      </small>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!observations.items.length && (
            <div className="empty">No observations in this time window.</div>
          )}
          <div className="pagination">
            <span>
              {observations.total
                ? `${offset + 1}–${Math.min(offset + 50, observations.total)} of ${observations.total}`
                : "0 observations"}
            </span>
            <button
              className="btn secondary"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - 50))}
            >
              Previous
            </button>
            <button
              className="btn secondary"
              disabled={offset + 50 >= observations.total}
              onClick={() => setOffset(offset + 50)}
            >
              Next
            </button>
          </div>
        </section>
      )}
      {result && (
        <section className="card mt">
          <h3>Interval coverage</h3>
          <div
            className="coverage-strip"
            aria-label="Interval reporting coverage"
          >
            {result.points.map((point, index) => (
              <span
                key={`${point.time}:${index}`}
                className={
                  point.value == null
                    ? "missing"
                    : point.coverage < 1
                      ? "partial"
                      : "complete"
                }
                title={`${when(point.time)} · ${point.status} · ${number(point.coverage * 100, 0)}% coverage`}
              />
            ))}
          </div>
          <p className="small-note">
            Green: covered interval · Yellow: partial coverage · Grey: no
            available value
          </p>
        </section>
      )}
    </>
  );
}

function HistoryChart({ points, displayUnit }) {
  const available = points.filter((point) => point.value != null);
  if (!available.length)
    return (
      <div className="empty">
        <BarChart3 size={36} />
        <h3>No available readings in this window.</h3>
        <p>
          Try another interval or measurement. Missing data is not zero
          consumption.
        </p>
      </div>
    );
  const start = Date.parse(points[0].time),
    end = Math.max(Date.parse(points.at(-1).end), start + 1);
  const max = Math.max(...available.map((point) => point.value), 1),
    min = Math.min(...available.map((point) => point.value), 0);
  const x = (point) =>
    48 + ((Date.parse(point.time) - start) / (end - start)) * 890;
  const y = (point) => 190 - ((point.value - min) / (max - min)) * 155;
  return (
    <div className="connected-chart">
      <svg
        viewBox="0 0 1000 230"
        role="img"
        aria-label={`Historical ${displayUnit || "measurement"} readings with gaps preserved`}
      >
        {[0, 0.5, 1].map((fraction) => (
          <g key={fraction}>
            <line
              x1="48"
              x2="950"
              y1={190 - fraction * 155}
              y2={190 - fraction * 155}
              stroke="#e7eae2"
            />
            <text x="4" y={194 - fraction * 155}>
              {number(min + fraction * (max - min), 1)}
            </text>
          </g>
        ))}
        {chartSegments(points).map((segment, index) => (
          <g key={index}>
            <polyline
              points={segment
                .map((point) => `${x(point)},${y(point)}`)
                .join(" ")}
              fill="none"
              stroke="#6f8d4a"
              strokeWidth="3"
            />
            {segment.length === 1 && (
              <circle
                cx={x(segment[0])}
                cy={y(segment[0])}
                r="4"
                fill="#6f8d4a"
              />
            )}
          </g>
        ))}
        <text x="48" y="222">
          {when(points[0].time)}
        </text>
        <text textAnchor="end" x="950" y="222">
          {when(points.at(-1).end)}
        </text>
      </svg>
      <span>{displayUnit}</span>
    </div>
  );
}
