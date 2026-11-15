import React, { useState, useEffect } from "react";
import {
  Sun,
  LayoutDashboard,
  Zap,
  CalendarDays,
  LifeBuoy,
  BookOpen,
  User,
  ArrowUpRight,
  ArrowRight,
  ArrowDown,
  Plus,
  Check,
  ChevronDown,
  ChevronRight,
  X,
  LogOut,
  ShieldCheck,
  Activity,
  MapPin,
  BatteryCharging,
  Plug,
  House,
  CloudSun,
  Bell,
  Menu,
  Search,
  Download,
  Users,
  Radio,
  Tickets,
  Video,
  Settings,
  Clock,
  AlertTriangle,
  Send,
  CheckCircle2,
  Upload,
  Building2,
  Leaf,
  RefreshCw,
  Lock,
  Eye,
  Mail,
  Play,
  FileText,
  Coins,
  Truck,
} from "lucide-react";
import {
  AREAS,
  DEFAULT_SITE,
  roles,
  users,
  sites,
  inverters,
  requestTypes,
  defaultPrices,
  routeRequest,
  canSee,
  canDispatch,
  canConfirmOwner,
  canReview,
  canReviewRequest,
  recommend,
  timeLabel,
  defaultTariff,
} from "./domain";
import {
  activeDispatch,
  assignCrew,
  autoAssign,
  cancelAssignment,
  crewBusy,
  eligibleCrews,
  isOpen,
  logIncident,
  meetingsFor,
  resolveIncident,
  routeVisit,
  scheduleMeeting,
  sendTeam,
  skipReason,
  teamsReport,
  technicianArea,
  visibleIncidents,
} from "./dispatch";
import { revenueReport } from "./revenue";
import { BucharestMap } from "./map";
import { AssignmentReport, CrewSummary, FleetForecast, RevenueView } from "./ops";
import {
  readDB,
  mutate,
  resetDB,
  putMedia,
  getMedia,
  clearMedia,
} from "./store";
import {
  ContractCard,
  DailyForecast,
  EnergyBars,
  ForecastCard,
  FriendlyEnergy,
  LessonDeck,
} from "./features";
import { words } from "./friendly";
import { consumptionShape, typicalDailyConsumption } from "./dailyForecast";
import { demoBuckets, PERIODS } from "./periods";
import lessonSource from "../../backend/fixtures/lessons.json";
import "./styles.css";
const icons = {
  Home: LayoutDashboard,
  Plan: CalendarDays,
  Support: LifeBuoy,
  Learn: BookOpen,
  Account: User,
  "Area Radar": Radio,
  Incidents: Tickets,
  "Virtual Visits": Video,
  Teams: Users,
  Revenue: Coins,
};
/** Menu per role (owner's sheet "2 — Workers PPC"). */
export function navsFor(user) {
  if (!user || user.role === "client")
    return ["Home", "Plan", "Support", "Learn", "Account"];
  if (user.role === "ceo" || user.role === "manager")
    return ["Area Radar", "Incidents", "Teams", "Revenue", "Account"];
  if (user.role === "dispatcher")
    return ["Area Radar", "Incidents", "Virtual Visits", "Teams", "Account"];
  return ["Incidents", "Virtual Visits", "Account"];
}
function Pill({ children, tone = "" }) {
  return <span className={"pill " + tone}>{children}</span>;
}
function Modal({ title, children, onClose, wide = false }) {
  useEffect(() => {
    const old = document.activeElement;
    const handler = (e) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab") {
        const all = [
          ...document.querySelectorAll(
            ".modal button,.modal input,.modal select,.modal textarea,.modal a",
          ),
        ].filter((x) => !x.disabled);
        if (e.shiftKey && document.activeElement === all[0]) {
          e.preventDefault();
          all.at(-1)?.focus();
        } else if (!e.shiftKey && document.activeElement === all.at(-1)) {
          e.preventDefault();
          all[0]?.focus();
        }
      }
    };
    document.addEventListener("keydown", handler);
    document.querySelector(".modal button")?.focus();
    return () => {
      document.removeEventListener("keydown", handler);
      old?.focus();
    };
  }, []);
  return (
    <div className="overlay" onClick={onClose}>
      <section
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={"modal " + (wide ? "wide" : "")}
        onClick={(e) => e.stopPropagation()}
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
export default function DemoApp() {
  const [db, setDb] = useState(readDB),
    [userId, setUserId] = useState(() =>
      sessionStorage.getItem("solar-session"),
    ),
    [page, setPage] = useState("Home"),
    [login, setLogin] = useState(false),
    [selected, setSelected] = useState(null),
    [toast, setToast] = useState(""),
    [menu, setMenu] = useState(false),
    [notifications, setNotifications] = useState(false),
    [siteId, setSiteId] = useState(DEFAULT_SITE);
  const user = db.users.find((u) => u.id === userId && u.active),
    client = !user || user.role === "client";
  useEffect(() => {
    const refresh = () => setDb(readDB());
    window.addEventListener("storage", refresh);
    window.addEventListener("solar-db", refresh);
    return () => {
      window.removeEventListener("storage", refresh);
      window.removeEventListener("solar-db", refresh);
    };
  }, []);
  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(""), 4000);
      return () => clearTimeout(t);
    }
  }, [toast]);
  const notify = (s) => setToast(s),
    nav = (p) => {
      setPage(p);
      setMenu(false);
    },
    requireLogin = (fn) => {
      if (!user) {
        setLogin(true);
        return;
      }
      fn();
    };
  const visibleSites = sites.filter((s) => canSee(user, s.id)),
    current =
      visibleSites.find((s) => s.id === siteId) || visibleSites[0] || sites[0];
  const navs = navsFor(user);
  const active = navs.includes(page) ? page : navs[0];
  const incidents = visibleIncidents(db, user);
  function onLogin(u) {
    sessionStorage.setItem("solar-session", u.id);
    setUserId(u.id);
    setPage(navsFor(u)[0]);
    setSiteId(u.sites[0] || DEFAULT_SITE);
    setLogin(false);
    notify(`Welcome, ${u.name.split(" ")[0]}.`);
  }
  function logout() {
    sessionStorage.removeItem("solar-session");
    setUserId(null);
    setPage("Home");
    notify("Signed out of the demo account.");
  }
  const ctx = {
    db,
    user,
    current,
    notify,
    requireLogin,
    setSelected,
    nav,
    incidents,
  };
  return (
    <div className="app">
      <aside className={"sidebar " + (menu ? "mobile-open" : "")}>
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            nav(navs[0]);
          }}
        >
          <Sun size={30} strokeWidth={1.7} />
          SolarLenes<span className="brand-dot">®</span>
        </a>
        <div className="workspace-label">
          {client ? "YOUR ENERGY WORKSPACE" : "PPC OPERATIONS"}
          <span>01</span>
        </div>
        <nav>
          {navs.map((n) => {
            const Icon = icons[n];
            return (
              <button
                key={n}
                className={"nav-item " + (active === n ? "active" : "")}
                onClick={() => nav(n)}
              >
                <Icon size={19} />
                <span>{n}</span>
                {n === "Support" && (
                  <span className="nav-count">
                    {incidents.filter((x) => x.status !== "Closed").length}
                  </span>
                )}
                {n === active && <span className="active-dot" />}
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
              to use energy.
            </h3>
            <p>Small shifts. Better energy days.</p>
            <button onClick={() => nav(client ? "Learn" : navs[0])}>
              Explore your workspace <ArrowUpRight size={16} />
            </button>
          </div>
          <div className="system-status">
            <span className="green-dot" />
            Synthetic demo <span>v1.0</span>
          </div>
          <button
            className="sidebar-user"
            onClick={() => (user ? nav("Account") : setLogin(true))}
          >
            <span className="avatar">
              {user
                ? user.name
                    .split(" ")
                    .map((s) => s[0])
                    .join("")
                : "SL"}
            </span>
            <span>
              <b>{user?.name || "Welcome to SolarLenes"}</b>
              <small>{user ? roles[user.role] : "Explore the preview"}</small>
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
          <a
            className="mobile-brand"
            href="#"
            onClick={(e) => {
              e.preventDefault();
              nav(navs[0]);
            }}
          >
            SolarLenes
          </a>
          <div className="breadcrumb">
            Workspace <ChevronRight size={13} /> <b>{active}</b>
          </div>
          <div className="header-actions">
            <span className="demo-tag">
              <span /> DEMO ENVIRONMENT
            </span>
            <button
              className="icon-btn notification"
              aria-label="Notifications"
              onClick={() => {
                if (db.preferences[user?.id]?.notifications === "Off") {
                  notify(
                    "In-app notifications are off. Safety alerts remain visible in your workspace.",
                  );
                  return;
                }
                setNotifications(!notifications);
              }}
            >
              <Bell size={19} />
              <i />
            </button>
            {user ? (
              <button className="account-button" onClick={() => nav("Account")}>
                <span className="avatar small">
                  {user.name
                    .split(" ")
                    .map((s) => s[0])
                    .join("")}
                </span>
                <span>{user.name.split(" ")[0]}</span>
                <ChevronDown size={14} />
              </button>
            ) : (
              <button className="login-button" onClick={() => setLogin(true)}>
                Log in <ArrowUpRight size={16} />
              </button>
            )}
          </div>
        </header>
        {notifications && (
          <div className="notification-panel">
            <h3>Your updates</h3>
            {incidents.slice(0, 3).map((i) => (
              <button
                key={i.id}
                onClick={() => {
                  setSelected(i.id);
                  setNotifications(false);
                }}
              >
                <Pill tone={["P0", "P1"].includes(i.tier) ? "orange" : ""}>{i.tier}</Pill>
                <span>
                  {i.title}
                  <small>{i.site} · synthetic replay</small>
                </span>
              </button>
            ))}
            {!incidents.length && <p>No updates in your scope.</p>}
          </div>
        )}
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                {client
                  ? "A LITTLE SUN. A LOT OF POSSIBILITY."
                  : "CONNECTED SITES. INFORMED DECISIONS."}
              </div>
              <h1>
                {active === "Home"
                  ? `Good afternoon, ${user?.name.split(" ")[0] || "Alex"}`
                  : active === "Area Radar"
                    ? "Your energy network"
                    : active === "Plan"
                      ? "Make room for sunshine"
                      : active === "Support"
                        ? "We’re here to help"
                        : active === "Learn"
                          ? "A little energy know-how"
                          : active === "Account"
                            ? "Your workspace, your way"
                            : active}
                <span className="yellow-dot">.</span>
              </h1>
              <p>
                {active === "Home"
                  ? "Your home is making the most of today’s sunshine."
                  : active === "Area Radar"
                    ? "A clear view of your monitored installations. A human behind every decision."
                    : active === "Revenue"
                      ? "Estimated from synthetic billing profiles and tariffs. Not invoices."
                      : active === "Teams"
                        ? "Who is assigned to which incident, and which crews are free."
                    : active === "Plan"
                      ? "Find a better time for the energy you already use."
                      : "Everything you need, connected in one place."}
              </p>
            </div>
            <div className="heading-controls">
              {client && (
                <label className="site-selector">
                  <House size={15} />
                  <select
                    aria-label="Select installation"
                    value={current.id}
                    onChange={(e) => setSiteId(e.target.value)}
                  >
                    {visibleSites.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <div className="date-label">
                <CalendarDays size={15} />
                14 November 2026 <span>· Replay</span>
              </div>
            </div>
          </div>
          {active === "Home" && <Home {...ctx} />}
          {active === "Plan" && <Plan {...ctx} />}
          {active === "Support" && <Support {...ctx} />}
          {active === "Learn" && <Learn user={user} />}
          {active === "Area Radar" && (
            <Radar {...ctx} visibleSites={visibleSites} />
          )}
          {active === "Incidents" && <Incidents {...ctx} />}
          {active === "Virtual Visits" && <Visits {...ctx} />}
          {active === "Teams" && <Teams {...ctx} />}
          {active === "Revenue" && ["ceo", "manager"].includes(user?.role) && (
            <Revenue {...ctx} />
          )}
          {active === "Account" && (
            <Account {...ctx} logout={logout} setLogin={setLogin} />
          )}
          <footer>
            <span>
              <Sun size={15} />
              SolarLenes <span className="footer-divider">/</span> Energy, in
              your hands.
            </span>
            <span>Synthetic data · Europe/Bucharest · No device control</span>
          </footer>
        </main>
      </div>
      {client && (
        <nav className="bottom-nav">
          {navs.slice(0, 5).map((n) => {
            const Icon = icons[n];
            return (
              <button
                key={n}
                onClick={() => nav(n)}
                className={active === n ? "active" : ""}
              >
                <Icon size={20} />
                <span>{n}</span>
              </button>
            );
          })}
        </nav>
      )}
      {login && (
        <Login db={db} onLogin={onLogin} onClose={() => setLogin(false)} />
      )}
      {selected && (
        <IncidentDetail
          {...ctx}
          incident={incidents.find((i) => i.id === selected)}
          onClose={() => setSelected(null)}
        />
      )}
      {toast && (
        <div role="status" className="toast">
          <CheckCircle2 size={19} />
          {toast}
        </div>
      )}
    </div>
  );
}
function Home({
  db,
  user,
  current,
  nav,
  setSelected,
  incidents,
  notify,
  requireLogin,
}) {
  const bat = current.battery;
  const accountType = current.business ? "business" : "home";
  const w = words(accountType);
  const contract = db.contracts?.[current.id] || null;
  return (
    <>
      <div className="home-grid">
        <section className="energy-hero">
          <div className="section-head">
            <div>
              <div className="eyebrow">{w.eyebrow}</div>
              <h2>Powered by a brighter day.</h2>
            </div>
            <Pill tone="dark">
              <span className="green-dot" />
              Synthetic replay
            </Pill>
          </div>
          <div className="energy-scene">
            <div className="scene-grid" />
            <div className="scene-sun">
              <Sun size={30} />
              <span>
                Solar production
                <b>
                  {current.stale ? "Unavailable" : "4.8"}{" "}
                  <small>{!current.stale && "kW"}</small>
                </b>
              </span>
            </div>
            <div className="flow-track solar-track">
              <i />
              <i />
              <i />
            </div>
            <div className="house-illustration">
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
            <div className="flow-track home-track">
              <i />
              <i />
            </div>
            <div className="scene-home">
              <House size={22} />
              <span>
                {w.consumption}
                <b>
                  {current.stale ? "Unavailable" : "1.6"}{" "}
                  <small>{!current.stale && "kW"}</small>
                </b>
              </span>
            </div>
            <div className="flow-track grid-track">
              <i />
              <i />
            </div>
            <div className="scene-grid-export">
              <Plug size={23} />
              <span>
                Exporting to grid
                <b>
                  {current.stale ? "Unavailable" : bat ? "2.4" : "3.2"}{" "}
                  <small>{!current.stale && "kW"}</small>
                </b>
              </span>
            </div>
          </div>
          <div className="hero-foot">
            <span>
              <span className="green-dot" />
              {current.stale
                ? "Feed is stale · measurements unavailable"
                : `Solar is covering your ${w.place}’s demand`}
            </span>
            <span>
              Updated 13:00 EET <Activity size={14} />
            </span>
          </div>
        </section>
        <DailyForecast
          kwp={contract?.installed_kwp || current.capacity}
          dailyConsumption={typicalDailyConsumption(current.profile)}
          shape={consumptionShape(current.segment, current.businessType)}
          prices={
            contract
              ? {
                  importPrice: contract.import_price_ron_kwh,
                  exportPrice: contract.export_price_ron_kwh,
                }
              : defaultPrices
          }
          pricesFromContract={Boolean(contract)}
          consumptionLabel={w.consumption}
          onPlan={() => nav("Plan")}
        />
      </div>
      <section className="card friendly-strip">
        <FriendlyEnergy
          kwh={current.stale ? null : bat ? 12.4 : 16.2}
          subject="Today’s export"
          accountType={accountType}
        />
      </section>
      <div className="stat-grid">
        <Stat
          icon={Sun}
          label="Solar generated today"
          value="24.8"
          unit="kWh"
          detail="Synthetic daily total"
          trend="+12.4% vs. prior replay day"
        />
        <Stat
          icon={House}
          label={current.business ? "Business energy today" : "Home energy today"}
          value="12.6"
          unit="kWh"
          detail="From solar and grid"
          spark="purple"
        />
        <Stat
          icon={Leaf}
          label={current.business ? "Solar used on site" : "Solar used at home"}
          value="68"
          unit="%"
          detail={`Share of ${w.place} demand from solar`}
        />
        <Stat
          icon={bat ? BatteryCharging : Plug}
          label={bat ? "Battery state of charge" : "Grid export today"}
          value={bat ? "76" : "16.2"}
          unit={bat ? "%" : "kWh"}
          detail={
            bat
              ? "Charging at 0.8 kW · simulated"
              : "Surplus solar sent to the grid"
          }
          spark="purple"
        />
      </div>
      <div className="lower-grid">
        <EnergyChart consumptionLabel={w.consumption} />
        <section className="card activity-card">
          <div className="section-head">
            <h3>{w.care}</h3>
            <span className="subtle-icon">
              <ShieldCheck size={19} />
            </span>
          </div>
          {incidents
            .filter((i) => i.site === current.id && i.status !== "Closed")
            .slice(0, 2)
            .map((i) => (
              <button
                className="alert-row"
                key={i.id}
                onClick={() => setSelected(i.id)}
              >
                <span className="alert-icon">
                  <AlertTriangle size={19} />
                </span>
                <div>
                  <b>{i.title}</b>
                  <p>
                    {i.tier} · {i.status} · Technical review available
                  </p>
                </div>
                <ChevronRight size={17} />
              </button>
            ))}
          {!incidents.some((i) => i.site === current.id) && (
            <p>No supported alerts in monitored inputs.</p>
          )}
          <button className="learn-teaser" onClick={() => nav("Learn")}>
            <span>
              <BookOpen size={20} />
            </span>
            <div>
              <small>ONE MINUTE · EARN A REWARD</small>
              <b>Making sense of your solar</b>
              <p>Short lessons with a mini test.</p>
            </div>
            <ArrowUpRight size={19} />
          </button>
          <div className="support-bottom">
            <span>Questions about your system?</span>
            <button className="text-btn" onClick={() => nav("Support")}>
              Let’s talk <ArrowUpRight size={14} />
            </button>
          </div>
        </section>
      </div>
      <div className="mt">
        <ForecastCard
          kwp={contract?.installed_kwp || current.capacity}
          contract={contract}
          accountType={accountType}
        />
      </div>
      <div className="preview-note">
        <Activity size={16} />
        <span>
          This is a frontend demonstrator. Energy, tariffs, incidents, and
          savings are simulated; no equipment is connected.
        </span>
      </div>
    </>
  );
}
function Stat({ icon: Icon, label, value, unit, detail, trend, spark }) {
  return (
    <section className="card stat">
      <div className="stat-label">
        <span>{label}</span>
        <Icon size={18} />
      </div>
      <div className="stat-number">
        {value}
        <span>{unit}</span>
        <svg className={"spark " + (spark || "")} viewBox="0 0 95 32">
          <path d="M0 27 L10 22 L20 26 L30 17 L40 20 L50 9 L60 13 L70 7 L80 11 L95 2" />
        </svg>
      </div>
      <small className={trend ? "positive" : ""}>{trend || detail}</small>
    </section>
  );
}
function EnergyChart({ consumptionLabel }) {
  const [period, setPeriod] = useState("Today"),
    [hover, setHover] = useState(null);
  const data = [
    0, 0, 0, 0, 0.1, 0.5, 1.2, 2.5, 3.8, 4.5, 4.8, 4.2, 3.2, 2.4, 1.5, 0.5,
    0.1, 0, 0,
  ];
  if (period !== "Today") {
    const buckets = demoBuckets(period);
    return (
      <section className="card chart-card">
        <div className="section-head">
          <div>
            <h3>Your energy, {PERIODS[period].title}</h3>
            <p>Simulated energy totals.</p>
          </div>
          <select
            aria-label="Chart period"
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
          >
            {Object.keys(PERIODS).map((name) => (
              <option key={name}>{name}</option>
            ))}
          </select>
        </div>
        <EnergyBars buckets={buckets} consumptionLabel={consumptionLabel} />
        <div className="chart-foot">
          <span>
            <Sun size={14} />
            Solar produced{" "}
            <b>
              {Math.round(
                buckets.reduce((sum, b) => sum + b.production, 0),
              ).toLocaleString("en-GB")}{" "}
              kWh
            </b>
          </span>
          <span>Up to 14 Nov · EET</span>
        </div>
      </section>
    );
  }
  const points = data.map((v, i) => `${45 + i * 32},${155 - v * 25}`).join(" ");
  return (
    <section className="card chart-card">
      <div className="section-head">
        <div>
          <h3>Your energy, throughout the day</h3>
          <p>Every flow, in one clear picture.</p>
        </div>
        <select
          aria-label="Chart period"
          value={period}
          onChange={(e) => setPeriod(e.target.value)}
        >
          {Object.keys(PERIODS).map((name) => (
            <option key={name}>{name}</option>
          ))}
        </select>
      </div>
      <div className="chart-legend">
        <span>
          <i className="yellow" />
          Solar production
        </span>
        <span>
          <i className="purple" />
          Home demand
        </span>
        <span className="forecast-label">Simulated readings</span>
      </div>
      <div className="chart-wrap">
        <svg
          viewBox="0 0 660 195"
          role="img"
          aria-label={`${period} simulated solar and home demand in kilowatts`}
        >
          <defs>
            <linearGradient id="chartFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#e8c848" stopOpacity=".25" />
              <stop offset="100%" stopColor="#e8c848" stopOpacity=".01" />
            </linearGradient>
          </defs>
          {[0, 1, 2, 3].map((i) => (
            <g key={i}>
              <line
                x1="40"
                x2="640"
                y1={155 - i * 40}
                y2={155 - i * 40}
                stroke="#eceeeb"
                strokeDasharray="3 4"
              />
              <text x="0" y={159 - i * 40}>
                {i * 2} kW
              </text>
            </g>
          ))}
          <polygon points={`45,155 ${points} 621,155`} fill="url(#chartFill)" />
          <polyline
            points={points}
            fill="none"
            stroke="#d6b32d"
            strokeWidth="2.5"
            strokeLinejoin="round"
          />
          <path
            d="M45 143 L77 145 L109 144 L141 138 L173 141 L205 115 L237 128 L269 132 L301 126 L333 123 L365 130 L397 127 L429 125 L461 115 L493 130 L525 118 L557 105 L589 128 L621 134"
            fill="none"
            stroke="#a49bc5"
            strokeWidth="2.4"
          />
          {["00:00", "04:00", "08:00", "12:00", "16:00", "20:00", "24:00"].map(
            (s, i) => (
              <text key={s} x={40 + i * 96} y="185">
                {s}
              </text>
            ),
          )}
          {data.map((v, i) => (
            <circle
              key={i}
              cx={45 + i * 32}
              cy={155 - v * 25}
              r="10"
              fill="transparent"
              onMouseEnter={() =>
                setHover(
                  `${timeLabel((i * 24) / 18).slice(0, 5)} · ${v} kW solar`,
                )
              }
              onMouseLeave={() => setHover(null)}
            />
          ))}
        </svg>
        {hover && <span className="chart-tooltip">{hover}</span>}
      </div>
      <div className="chart-foot">
        <span>
          <Sun size={14} />
          Peak production <b>4.8 kW</b>
        </span>
        <span>14 Nov · EET</span>
      </div>
    </section>
  );
}
function Login({ db, onLogin, onClose }) {
  const [email, setEmail] = useState("alex@solarlenes.demo"),
    [password, setPassword] = useState("SolarDemo2026!"),
    [error, setError] = useState("");
  return (
    <Modal title="Welcome to SolarLenes" onClose={onClose}>
      <p className="muted">One platform. A workspace shaped around you.</p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const u = db.users.find(
            (u) =>
              u.email.toLowerCase() === email.trim().toLowerCase() && u.active,
          );
          if (u && password === "SolarDemo2026!") onLogin(u);
          else
            setError(
              "Email or demo password is incorrect, or this account is inactive.",
            );
        }}
      >
        <label>
          Email address
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label>
          Password
          <input
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <button className="btn yellow full">
          Log in to workspace <ArrowRight size={17} />
        </button>
      </form>
      <div className="demo-login">
        <div className="eyebrow">TRY A DIFFERENT PERSPECTIVE</div>
        <div className="demo-role-grid">
          {[
            "client",
            "ceo",
            "manager",
            "dispatcher",
            "technician",
          ].map((role) => {
            const u = db.users.find((u) => u.role === role && u.active);
            return (
              u && (
                <button
                  key={role}
                  onClick={() => {
                    setEmail(u.email);
                    setError("");
                  }}
                  className={email === u.email ? "selected" : ""}
                >
                  {roles[role]}
                  <small>
                    {u.name}
                    {u.area && u.area !== "All" ? ` · ${u.area}` : ""}
                  </small>
                </button>
              )
            );
          })}
          {db.users
            .filter((u) => u.business && u.active)
            .map((u) => (
              <button
                key={u.id}
                onClick={() => {
                  setEmail(u.email);
                  setError("");
                }}
                className={email === u.email ? "selected" : ""}
              >
                Business client
                <small>
                  {u.name} · {u.area}
                </small>
              </button>
            ))}
        </div>
        <details>
          <summary>All demo accounts & password</summary>
          <p>
            <code>SolarDemo2026!</code> for every seeded account.
          </p>
          {db.users.map((u) => (
            <button
              key={u.id}
              className="account-link"
              onClick={() => setEmail(u.email)}
            >
              {u.email} · {roles[u.role]}
            </button>
          ))}
        </details>
        <p className="small-note">
          <Lock size={14} />
          Demo login only. Accounts and role checks run in your browser, not a
          secure authentication server. Use synthetic information only.
        </p>
      </div>
    </Modal>
  );
}
function Plan({ db, user, current, notify, requireLogin }) {
  const [task, setTask] = useState(() => {
      const p = db.preferences[user?.id];
      return {
        type: p?.task || "EV charging",
        energy: p?.task && p.task !== "EV charging" ? 2 : 6,
        power: p?.task && p.task !== "EV charging" ? 1 : 3,
        normal: 19,
        from: 12,
        to: 18,
        deadline: p?.deadline
          ? Number(p.deadline.split(":")[0]) +
            Number(p.deadline.split(":")[1]) / 60
          : 18,
      };
    }),
    [index, setIndex] = useState(0),
    [offer, setOffer] = useState(null);
  const contract = db.contracts?.[current.id];
  const prices = contract
    ? {
        importPrice: contract.import_price_ron_kwh,
        exportPrice: contract.export_price_ron_kwh,
      }
    : defaultPrices;
  const taskTypes = current.business
    ? ["Dishwasher cycle", "Oven pre-heat", "EV charging"]
    : ["EV charging", "Dishwasher", "Washing machine"];
  const options = recommend(task, db.plans, current.id, prices),
    best = options[index % Math.max(1, options.length)],
    plans = db.plans.filter((p) => p.site === current.id);
  const change = (k, v) => {
    setTask({ ...task, [k]: v });
    setIndex(0);
    setOffer(null);
  };
  function accept() {
    requireLogin(() => {
      if (offer && Date.now() > offer) {
        notify("This offer expired. Generate a fresh window.");
        setOffer(null);
        return;
      }
      const fresh = recommend(task, readDB().plans, current.id, prices).find(
        (x) => x.start === best?.start,
      );
      if (!fresh) {
        notify("Capacity changed. Choose a new available window.");
        return;
      }
      mutate((d) => {
        d.plans.push({
          ...fresh,
          id: crypto.randomUUID(),
          site: current.id,
          type: task.type,
          status: "Accepted",
          created: new Date().toISOString(),
        });
      });
      setOffer(null);
      notify(
        "Plan accepted. Start the appliance yourself at the chosen time. No device was operated.",
      );
    });
  }
  return (
    <div className="two-col">
      <div>
      <section className="card form-card">
        <div className="eyebrow">01 / YOUR TASK</div>
        <h2>What are we planning?</h2>
        <div className="segmented">
          {taskTypes.map((t) => (
            <button
              key={t}
              className={task.type === t ? "active" : ""}
              onClick={() => {
                setTask({
                  ...task,
                  type: t,
                  energy: t === "EV charging" ? 6 : 2,
                  power: t === "EV charging" ? 3 : 1,
                });
                setOffer(null);
              }}
            >
              {t === "EV charging" ? <Zap size={18} /> : <Plug size={18} />} {t}
            </button>
          ))}
        </div>
        <div className="form-grid">
          <label>
            Energy needed (kWh)
            <input
              type="number"
              min="0.5"
              max="50"
              step="0.5"
              value={task.energy}
              onChange={(e) => change("energy", +e.target.value)}
            />
          </label>
          <label>
            Task power (kW)
            <input
              type="number"
              min="0.5"
              max="7"
              step="0.5"
              value={task.power}
              onChange={(e) => change("power", +e.target.value)}
            />
          </label>
          <label>
            Usual start
            <select
              value={task.normal}
              onChange={(e) => change("normal", +e.target.value)}
            >
              {Array.from({ length: 24 }, (_, i) => (
                <option key={i} value={i}>
                  {timeLabel(i)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Finish by
            <select
              value={task.deadline}
              onChange={(e) => change("deadline", +e.target.value)}
            >
              {Array.from({ length: 24 }, (_, i) => (
                <option key={i} value={i + 1}>
                  {timeLabel(i + 1)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Earliest start
            <select
              value={task.from}
              onChange={(e) => change("from", +e.target.value)}
            >
              {Array.from({ length: 24 }, (_, i) => (
                <option key={i} value={i}>
                  {timeLabel(i)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Latest finish
            <select
              value={task.to}
              onChange={(e) => change("to", +e.target.value)}
            >
              {Array.from({ length: 24 }, (_, i) => (
                <option key={i} value={i + 1}>
                  {timeLabel(i + 1)}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="small-note">
          <Clock size={16} />
          {Number.isFinite(task.energy / task.power)
            ? (task.energy / task.power).toFixed(1)
            : "—"}{" "}
          hours · Contiguous cycle · All times EET
        </p>
        <div className="info-box">
          Only plan flexible loads. Essential, medical, and safety equipment are
          excluded. Battery dispatch is not optimised.
        </div>
        <button
          className="btn yellow"
          disabled={!best}
          onClick={() => {
            setOffer(Date.now() + 5 * 60000);
            notify(
              "Offer generated for five minutes. Capacity is rechecked on acceptance.",
            );
          }}
        >
          Find my window <ArrowRight size={17} />
        </button>
      </section>
      <div className="mt">
        <ContractCard
          key={current.id}
          contract={contract || null}
          defaultKwp={current.capacity}
          onSave={async (value) => {
            if (!user) {
              requireLogin(() => {});
              throw Error("Log in with a demo account to save a contract.");
            }
            mutate((d) => {
              d.contracts = { ...d.contracts, [current.id]: value };
            });
            notify("Contract saved. Estimates now use your prices.");
          }}
        />
      </div>
      </div>
      <div>
        <section className="card plan-result">
          <div className="eyebrow">02 / YOUR SOLAR OPPORTUNITY</div>
          {best ? (
            <>
              <div className="section-head">
                <h2>A sunnier time to start.</h2>
                <Sun className="sun-yellow" size={34} />
              </div>
              <div className="big-time">
                {timeLabel(best.start)}
                <ArrowRight size={25} />
                {timeLabel(best.start + best.duration)}
              </div>
              <div className="benefit">
                <b>
                  {best.saving.toFixed(2)} <small>RON</small>
                </b>
                <span>estimated incremental saving</span>
              </div>
              <div className="sensitivity">
                <span>
                  Lower solar<b>{best.low.toFixed(2)} RON</b>
                </span>
                <span>
                  Higher home demand<b>{best.higher.toFixed(2)} RON</b>
                </span>
              </div>
              <details>
                <summary>How we calculate this</summary>
                <p>
                  {contract
                    ? `From your ${contract.supplier} contract:`
                    : "Assumed (add your contract below the task form to replace these):"}{" "}
                  import {prices.importPrice.toFixed(2)} RON/kWh, export{" "}
                  {prices.exportPrice.toFixed(2)} RON/kWh.
                  Baseline cost {best.baseline.toFixed(2)} RON − proposed cost{" "}
                  {best.cost.toFixed(2)} RON = {best.saving.toFixed(2)} RON.
                  Surplus solar is 3 kW at 12:00–16:00, 1.5 kW at 10:00–12:00
                  and 16:00–17:00, zero otherwise. These are fixed-price demo
                  assumptions, not a bill or current offer.
                </p>
                <p>
                  Noon baseline:{" "}
                  {recommend(
                    {
                      ...task,
                      from: 12,
                      to: Math.min(24, 12 + best.duration),
                      deadline: Math.min(24, 12 + best.duration),
                    },
                    [],
                    current.id,
                    prices,
                  )[0]?.saving.toFixed(2) || "0.00"}{" "}
                  RON opportunity. Indexed-contract tariffs need a future
                  adapter.
                </p>
              </details>
              <div className="button-row">
                <button className="btn yellow" onClick={accept}>
                  Accept plan <Check size={17} />
                </button>
                <button
                  className="btn secondary"
                  onClick={() => {
                    setIndex(index + 1);
                    setOffer(null);
                  }}
                  disabled={options.length < 2}
                >
                  Another window
                </button>
                <button
                  className="text-btn"
                  onClick={() => {
                    setOffer(null);
                    notify("Suggestion declined. No capacity reserved.");
                  }}
                >
                  Decline
                </button>
              </div>
              <p className="small-note">
                {offer
                  ? `Offer expires ${new Date(offer).toLocaleTimeString("en-GB", { timeZone: "Europe/Bucharest" })} EET.`
                  : "Preview only; no capacity reserved until acceptance."}{" "}
                Advice only — start your appliance manually.
              </p>
            </>
          ) : (
            <div className="empty">
              <CloudSun size={40} />
              <h3>
                {plans.some((p) => p.status === "Accepted")
                  ? "Your energy plan is ready"
                  : "No useful window available"}
              </h3>
              <p>
                {plans.some((p) => p.status === "Accepted")
                  ? "Your accepted task is listed below. Cancel it first if you would like to choose a new time."
                  : "Check your deadline, energy and available hours. There may be no saving or remaining simulated capacity."}
              </p>
            </div>
          )}
        </section>
        <section className="card mt">
          <div className="section-head">
            <h3>Your plans</h3>
            <Pill>{plans.length}</Pill>
          </div>
          {!plans.length && (
            <p className="muted">Your accepted plans will appear here.</p>
          )}
          {plans.map((p) => (
            <div className="list-row" key={p.id}>
              <div>
                <b>{p.type}</b>
                <small>
                  {timeLabel(p.start)}–{timeLabel(p.start + p.duration)} ·{" "}
                  {p.saving.toFixed(2)} RON estimated
                </small>
              </div>
              <Pill tone={p.status === "Accepted" ? "green" : ""}>
                {p.status}
              </Pill>
              {p.status === "Accepted" && (
                <button
                  className="text-btn"
                  onClick={() =>
                    requireLogin(() => {
                      mutate((d) => {
                        d.plans.find((x) => x.id === p.id).status = "Cancelled";
                      });
                      notify("Plan cancelled; reserved capacity released.");
                    })
                  }
                >
                  Cancel
                </button>
              )}
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}
function Support({ db, user, current, notify, requireLogin, setSelected }) {
  const [followup, setFollowup] = useState({}),
    [description, setDescription] = useState(""),
    [requestType, setRequestType] = useState("solar"),
    [consent, setConsent] = useState(false),
    [danger, setDanger] = useState(false),
    [file, setFile] = useState(null),
    [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault();
    if (!user) {
      requireLogin(() => {});
      return;
    }
    if (!description.trim()) return;
    setBusy(true);
    try {
      const id = crypto.randomUUID();
      if (file) {
        if (
          file.size > 30 * 1024 * 1024 ||
          !["video/mp4", "video/webm"].includes(file.type)
        )
          throw Error("Use MP4 or WebM up to 30 MB.");
        await new Promise((resolve, reject) => {
          const v = document.createElement("video"),
            url = URL.createObjectURL(file),
            timer = setTimeout(() => {
              URL.revokeObjectURL(url);
              reject(Error("Video could not be validated."));
            }, 7000);
          v.preload = "metadata";
          v.onloadedmetadata = () => {
            clearTimeout(timer);
            URL.revokeObjectURL(url);
            Number.isFinite(v.duration) && v.duration <= 60
              ? resolve()
              : reject(Error("Video must be 60 seconds or shorter."));
          };
          v.onerror = () => {
            clearTimeout(timer);
            URL.revokeObjectURL(url);
            reject(Error("This video could not be decoded. Try MP4 or WebM."));
          };
          v.src = url;
        });
        await putMedia(id, file);
      }
      const request = routeRequest(requestType);
      const priority = danger ? "immediate_danger" : "standard";
      const owner = danger ? "Unassigned review" : request.owner;
      // Crew-routed types go to the crew of this site's area; the rest to PPC Triage.
      const routedTo = danger
        ? "PPC Triage"
        : routeVisit(requestType, current.id, db.crews);
      mutate((d) => {
        const incidentId = "I" + Date.now();
        d.incidents.unshift({
          id: incidentId,
          site: current.id,
          title: `Customer request: ${request.label}`,
          family: request.family,
          tier: danger ? "P0" : "P2",
          owner,
          requestType,
          priority,
          routedTo,
          reportedBy: user.id,
          confirmedOwner: "",
          evidence: description,
          strength: "Customer report",
          value: null,
          status: "New",
          revision: 1,
          age: 0,
          timeline: [
            {
              text: `Customer submitted a report: ${request.label} · routed to ${routedTo}`,
              actor: user.name,
              time: new Date().toISOString(),
            },
          ],
        });
        d.visits.unshift({
          id,
          incident: incidentId,
          site: current.id,
          user: user.id,
          requestType,
          priority,
          routedTo,
          description,
          media: !!file,
          filename: file?.name,
          status: "Awaiting review",
          replies: [],
          created: new Date().toISOString(),
        });
      });
      setDescription("");
      setRequestType("solar");
      setFile(null);
      setConsent(false);
      setDanger(false);
      notify(
        `Request routed to ${routedTo}. A staff account can review and reply.`,
      );
    } catch (e) {
      notify(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="two-col">
      <div>
        <section className="card form-card">
          <div className="section-head">
            <h2>Tell us what’s happening</h2>
            <LifeBuoy size={26} />
          </div>
          <p className="muted">
            A description is enough to start. A virtual visit is an asynchronous
            technician review, not a live call.
          </p>
          <label className="checkbox danger-check">
            <input
              type="checkbox"
              checked={danger}
              onChange={(e) => {
                setDanger(e.target.checked);
                setFile(null);
              }}
            />
            There is smoke, fire, or immediate danger
          </label>
          {danger && (
            <div className="danger-box">
              <b>Move away from danger. Do not approach to record a video.</b>
              <p>
                Contact local emergency services. Do not wait for this app or a
                technician reply. This demo is not an emergency response
                service.
              </p>
            </div>
          )}
          <form onSubmit={submit}>
            <label>
              Request type
              <select
                value={requestType}
                onChange={(e) => setRequestType(e.target.value)}
              >
                {requestTypes.map((request) => (
                  <option key={request.id} value={request.id}>
                    {request.label}
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
                onChange={(e) => setDescription(e.target.value)}
                placeholder="For example: the display has shown a warning since this morning…"
              />
            </label>
            {!danger && (
              <label className="upload-box">
                <Upload size={24} />
                <b>{file ? file.name : "Add an optional short video"}</b>
                <span>MP4 or WebM · Up to 60 seconds · 30 MB</span>
                <input
                  type="file"
                  accept="video/mp4,video/webm"
                  capture="environment"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                />
              </label>
            )}
            <p className="small-note">
              Record only from an already safe position. Do not open equipment,
              touch suspect parts, climb to inspect panels, or include people
              and private rooms.
            </p>
            <label className="checkbox">
              <input
                required
                type="checkbox"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
              />
              I understand this demo stores my request and optional clip in this
              browser until reset. Demo staff accounts can review it. I will
              only use synthetic information.
            </label>
            <button className="btn yellow full" disabled={busy}>
              {busy
                ? "Checking video…"
                : danger
                  ? "Record urgent report"
                  : "Request a technician review"}
              <Send size={17} />
            </button>
          </form>
        </section>
      </div>
      <div>
        <section className="card">
          <h3>Your support history</h3>
          {db.visits
            .filter((v) => v.site === current.id && v.user === user?.id)
            .map((v) => (
              <div className="request-card" key={v.id}>
                <div className="section-head">
                  <div className="detail-meta">
                    <Pill tone="green">{v.status}</Pill>
                    <Pill
                      tone={
                        v.priority === "immediate_danger" || v.priority === "urgent"
                          ? "orange"
                          : ""
                      }
                    >
                      {v.priority === "immediate_danger"
                        ? "Immediate danger"
                        : v.priority === "urgent"
                          ? "Urgent"
                          : "Standard"}
                    </Pill>
                  </div>
                  <small>
                    {new Date(v.created).toLocaleDateString("en-GB")}
                  </small>
                </div>
                <p className="small-note">
                  {requestTypes.find((request) => request.id === v.requestType)?.label ||
                    "Other or not sure"}{" "}
                  · Routed to {v.routedTo || "PPC Triage"}
                </p>
                <p>{v.description}</p>
                {meetingsFor(db, v.incident)
                  .filter((m) => m.status === "Scheduled")
                  .map((m) => (
                    <div className="meeting-note" key={m.id}>
                      <CalendarDays size={14} /> Meeting booked with{" "}
                      {m.crew}: <b>{m.date}</b>, {m.start}–{m.end} EET
                    </div>
                  ))}
                {v.replies.map((r, i) => (
                  <div className="reply" key={i}>
                    <b>
                      {r.author} ·{" "}
                      {r.kind === "customer"
                        ? "Your follow-up"
                        : "Technician response"}
                    </b>
                    <p>{r.text}</p>
                  </div>
                ))}
                {user && (
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      if (!followup[v.id]?.trim()) return;
                      mutate((d) => {
                        const row = d.visits.find((x) => x.id === v.id);
                        row.replies.push({
                          author: user.name,
                          text: followup[v.id],
                          kind: "customer",
                          outcome: "Follow-up",
                          time: new Date().toISOString(),
                        });
                        row.status = "Awaiting review";
                        const i = d.incidents.find((x) => x.id === v.incident);
                        if (i) {
                          if (!activeDispatch(d, i.id)) i.status = "Reviewing";
                          logIncident(
                            i,
                            `Customer added a follow-up: ${followup[v.id].trim()}`,
                            user.name,
                          );
                        }
                      });
                      setFollowup({ ...followup, [v.id]: "" });
                      notify("Follow-up added to the technician queue.");
                    }}
                  >
                    <label>
                      Add a follow-up
                      <input
                        required
                        maxLength={1000}
                        value={followup[v.id] || ""}
                        onChange={(e) =>
                          setFollowup({ ...followup, [v.id]: e.target.value })
                        }
                        placeholder="Add a safe observation or question…"
                      />
                    </label>
                    <button className="text-btn">
                      Send follow-up <Send size={14} />
                    </button>
                  </form>
                )}
                <button
                  className="text-btn"
                  onClick={() => setSelected(v.incident)}
                >
                  View incident <ArrowUpRight size={15} />
                </button>
              </div>
            ))}
          {!db.visits.some((v) => v.site === current.id) && (
            <div className="empty">
              <Video size={30} />
              <p>No requests yet. We’ll keep your conversation here.</p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
function Learn({ user }) {
  const key = `solar-lessons-v2:${user?.id || "guest"}`;
  const [earned, setEarned] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem(key)) || {};
    } catch {
      return {};
    }
  });
  const sum = (map) => Object.values(map).reduce((a, b) => a + b, 0);
  const catalog = {
    lessons: lessonSource.lessons.map((lesson) => ({
      ...lesson,
      completed: lesson.id in earned,
    })),
    total_reward_ron: sum(earned),
    reward_note: lessonSource.reward_note,
  };
  return (
    <LessonDeck
      catalog={catalog}
      onComplete={async (id, answers) => {
        const lesson = lessonSource.lessons.find((item) => item.id === id);
        const correct = lesson.questions.filter(
          (question, index) => question.answer === answers[index],
        ).length;
        const passed = correct === lesson.questions.length;
        const already = id in earned;
        const next =
          passed && !already ? { ...earned, [id]: lesson.reward_ron } : earned;
        if (next !== earned) {
          setEarned(next);
          localStorage.setItem(key, JSON.stringify(next));
        }
        return {
          passed,
          correct,
          total: lesson.questions.length,
          reward_ron: passed && !already ? lesson.reward_ron : 0,
          already_completed: already,
          total_reward_ron: sum(next),
        };
      }}
    />
  );
}
function Radar({ db, user, visibleSites, incidents, setSelected, notify }) {
  const [area, setArea] = useState("All"),
    [family, setFamily] = useState("All"),
    [owner, setOwner] = useState("All"),
    [focus, setFocus] = useState(null),
    [participation, setParticipation] = useState(50);
  // Area staff only ever get their own area: no "All areas" choice leaks others.
  const areas = AREAS.filter((a) => visibleSites.some((s) => s.area === a));
  // Map scope: the chosen area, else the staff member's own area(s); null = all.
  const mapAreas =
    area !== "All" ? [area] : user?.role === "ceo" ? null : areas;
  const open = incidents.filter((i) => isOpen(i));
  const filtered = visibleSites.filter(
    (s) =>
      (area === "All" || s.area === area) &&
      (family === "All" ||
        open.some((i) => i.site === s.id && i.family === family)) &&
      (owner === "All" || open.some((i) => i.site === s.id && i.owner === owner)),
  );
  const mapSites = filtered.map((s) => {
    const incident = open.find((i) => i.site === s.id);
    const inverter =
      db.inverters?.find((item) => item.site === s.id) ||
      inverters.find((item) => item.site === s.id);
    const customers =
      db.users
        .filter((a) => a.role === "client" && a.sites.includes(s.id))
        .map((a) => a.name)
        .join(", ") || "No demo client linked";
    return {
      id: s.id,
      name: s.name,
      latitude: s.latitude,
      longitude: s.longitude,
      zone: s.zone,
      segment: s.segment,
      businessType: s.businessType,
      kwp: s.capacity,
      status: incident ? "incident" : s.stale ? "stale" : "ok",
      tier: incident?.tier || null,
      area: s.area,
      cluster: s.cluster,
      detail: `Client: ${customers} · Inverter: ${inverter ? `${inverter.manufacturer} ${inverter.model}` : "not mapped"}${incident ? ` · ${incident.id} ${incident.title}` : ""}${incident && s.stale ? " · telemetry stale" : ""}`,
    };
  });
  const forecastAreas = areas.map((a) => {
    const list = visibleSites.filter((s) => s.area === a);
    return {
      name: a,
      sites: list.length,
      kwp: list.reduce((sum, s) => sum + s.capacity, 0),
    };
  });
  const acceptedPower = db.plans
    .filter((p) => p.status === "Accepted" && canSee(user, p.site))
    .reduce((a, p) => a + p.power, 0);
  return (
    <>
      <div className="stat-grid">
        <Stat
          icon={House}
          label="Monitored installations"
          value={visibleSites.length}
          unit="sites"
          detail={`${visibleSites.filter((s) => s.business).length} business · ${areas.join(", ")}`}
        />
        <Stat
          icon={Activity}
          label="Recent telemetry"
          value={visibleSites.filter((s) => !s.stale).length}
          unit={"/ " + visibleSites.length}
          detail="At replay time 13:00 EET"
        />
        <Stat
          icon={AlertTriangle}
          label="Open incidents"
          value={open.length}
          unit="cases"
          detail="Safety tier takes priority"
        />
        <Stat
          icon={Video}
          label="Virtual reviews"
          value={
            db.visits.filter(
              (v) => canSee(user, v.site) && v.status === "Awaiting review",
            ).length
          }
          unit="pending"
          detail="Human-led technical review"
        />
      </div>
      <div className="radar-layout">
        <section className="card radar">
          <div className="section-head">
            <div>
              <h3>Installation map · Bucharest and Ilfov</h3>
              <p>
                {visibleSites.length} synthetic sites ·{" "}
                {areas.length === 1
                  ? `${areas[0]} only`
                  : `${areas.length} areas (sectors and Ilfov)`}{" "}
                · zoom and pan the street map
              </p>
            </div>
            <Pill tone="green">
              <Radio size={12} />
              Replay 13:00
            </Pill>
          </div>
          <div className="filters ops-radar-filters">
            {areas.length > 1 && (
              <select
                aria-label="Filter area"
                value={area}
                onChange={(e) => setArea(e.target.value)}
              >
                <option value="All">All available areas</option>
                {areas.map((a) => (
                  <option key={a}>{a}</option>
                ))}
              </select>
            )}
            <select
              aria-label="Filter incident family"
              value={family}
              onChange={(e) => setFamily(e.target.value)}
            >
              <option value="All">All incident types</option>
              {[...new Set(open.map((i) => i.family))].map((f) => (
                <option key={f}>{f}</option>
              ))}
            </select>
            <select
              aria-label="Filter owner"
              value={owner}
              onChange={(e) => setOwner(e.target.value)}
            >
              <option value="All">All service owners</option>
              {[...new Set(open.map((i) => i.owner))].map((o) => (
                <option key={o}>{o}</option>
              ))}
            </select>
          </div>
          <BucharestMap
            sites={mapSites}
            areas={mapAreas}
            selectedId={focus}
            actionLabel="Open incident or site summary"
            onSelect={(id) => {
              setFocus(id);
              const incident = open.find((i) => i.site === id);
              const site = mapSites.find((s) => s.id === id);
              if (incident) setSelected(incident.id);
              else
                notify(
                  `${id} ${site?.name} · ${site?.detail} · ${visibleSites.find((s) => s.id === id)?.stale ? "stale telemetry" : "no supported alerts among monitored inputs"}.`,
                );
            }}
          />
          <p className="small-note">
            A coverage map, not a validated network digital twin. Nearby points
            do not establish shared feeder membership. Unmonitored
            infrastructure has no health status.
          </p>
        </section>
        <div className={"area-cards" + (areas.length > 3 ? " compact" : "")}>
          {areas.map((a) => {
            const ss = visibleSites.filter((s) => s.area === a);
            return (
              <section className="card area-card" key={a}>
                <div className="section-head">
                  <h3>{a}</h3>
                  <MapPin size={18} />
                </div>
                <strong>
                  {ss.filter((s) => !s.stale).length}
                  <span> / {ss.length} recent feeds</span>
                </strong>
                <div className="coverage">
                  <i
                    style={{
                      width:
                        (100 * ss.filter((s) => !s.stale).length) / ss.length +
                        "%",
                    }}
                  />
                </div>
                <p>
                  {open.filter((i) => ss.some((s) => s.id === i.site)).length}{" "}
                  open incidents · {ss.filter((s) => s.business).length}{" "}
                  business sites ·{" "}
                  {ss.reduce((sum, s) => sum + s.capacity, 0)} kWp
                </p>
                {areas.length > 1 && (
                  <button
                    className="text-btn"
                    aria-label={`Inspect ${a}`}
                    onClick={() => setArea(a)}
                  >
                    Inspect <ArrowUpRight size={15} />
                  </button>
                )}
              </section>
            );
          })}
        </div>
      </div>
      <FleetForecast areas={forecastAreas} />
      <section className="card mt">
        <div className="section-head">
          <div>
            <h3>Coordinated demand scenario</h3>
            <p>
              Full task power is reserved regardless of expected participation.
            </p>
          </div>
          <select
            aria-label="Participation scenario"
            value={participation}
            onChange={(e) => setParticipation(+e.target.value)}
          >
            {[20, 50, 100].map((p) => (
              <option key={p} value={p}>
                {p}% participation
              </option>
            ))}
          </select>
        </div>
        <div className="scenario-stats">
          <span>
            Expected added demand
            <b>{((acceptedPower * participation) / 100).toFixed(1)} kW</b>
          </span>
          <span>
            Full-participation task power
            <b>{acceptedPower.toFixed(1)} kW</b>
          </span>
          <span>
            Simulated envelope per area<b>6 kW / occupied slot</b>
          </span>
        </div>
        <p className="small-note">
          Task totals are not coincident peaks. Browser demo checks every
          occupied slot; transactional concurrent acceptance and timed offer
          reservations belong in the backend.
        </p>
      </section>
    </>
  );
}
function CrewBanner({ db, user, setSelected }) {
  const crew = db.crews.find((c) => c.name === user.crew);
  if (!crew) return null;
  const busy = crewBusy(db, crew.name);
  const meetings = db.assignments.filter(
    (a) => a.kind === "meeting" && a.crew === crew.name && a.status === "Scheduled",
  );
  return (
    <section className="card ops-crew-banner">
      <span className="crew-icon">
        <Users size={20} />
      </span>
      <span>
        <b>{crew.name}</b> · {crew.area} · {crew.members.length} members
      </span>
      <Pill tone={busy ? "orange" : "green"}>
        {busy ? `● ${busy.status} · ${busy.incident}` : "✓ Available"}
      </Pill>
      {busy && (
        <button className="text-btn" onClick={() => setSelected(busy.incident)}>
          Open {busy.incident} <ArrowUpRight size={14} />
        </button>
      )}
      <span className="muted">
        {meetings.length
          ? `Meetings: ${meetings.map((m) => `${m.incident} ${m.date} ${m.start}–${m.end}`).join(" · ")}`
          : "No customer meetings booked"}
      </span>
    </section>
  );
}
function Incidents({ db, user, incidents, setSelected }) {
  const [q, setQ] = useState(""),
    [tier, setTier] = useState("All");
  const list = incidents.filter(
    (i) =>
      (tier === "All" || i.tier === tier) &&
      `${i.id} ${i.site} ${i.title} ${i.owner}`
        .toLowerCase()
        .includes(q.toLowerCase()),
  );
  return (
    <>
    {user?.role === "technician" && (
      <CrewBanner db={db} user={user} setSelected={setSelected} />
    )}
    <section className="card">
      <div className="section-head">
        <div>
          <h3>
            {user?.role === "technician"
              ? `Every case in ${technicianArea(db, user)}, in the right order`
              : user?.role === "ceo"
                ? "Every case, in the right order"
                : `Every case in ${user?.area}, in the right order`}
          </h3>
          <p>
            Safety first, then age. Financial value never overrides urgency.
          </p>
        </div>
        <Pill>{list.length} cases</Pill>
      </div>
      <div className="filters">
        <label className="search">
          <Search size={17} />
          <input
            placeholder="Search site, case, or owner"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </label>
        <select
          aria-label="Safety tier"
          value={tier}
          onChange={(e) => setTier(e.target.value)}
        >
          <option value="All">All safety tiers</option>
          {["P0", "P1", "P2", "P3"].map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Priority / case</th>
              <th>Installation</th>
              <th>Suspected owner</th>
              <th>Crew</th>
              <th>Age</th>
              <th>Customer value</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {list.map((i) => (
              <tr key={i.id} onClick={() => setSelected(i.id)}>
                <td>
                  <div className="case-cell">
                    <Pill
                      tone={
                        ["P0", "P1"].includes(i.tier)
                          ? "orange"
                          : i.tier === "P2"
                            ? "yellow"
                            : ""
                      }
                    >
                      {i.tier}
                    </Pill>
                    <div>
                      <b>{i.title}</b>
                      <small>
                        {i.id} · {i.family}
                      </small>
                    </div>
                  </div>
                </td>
                <td>
                  {i.site}
                  <small>{sites.find((s) => s.id === i.site)?.name}</small>
                </td>
                <td>{i.owner}</td>
                <td>{activeDispatch(db, i.id)?.crew || "—"}</td>
                <td>{i.age} min</td>
                <td>
                  {i.value === null
                    ? "Unknown"
                    : i.value.toFixed(2) + " RON/day"}
                  <small>Operator: unknown</small>
                </td>
                <td>
                  <Pill>{i.status}</Pill>
                </td>
                <td>
                  <button className="icon-btn" aria-label={"Open " + i.id}>
                    <ArrowUpRight size={17} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!list.length && (
        <div className="empty">No matching cases in your scope.</div>
      )}
    </section>
    </>
  );
}
const CASE_STATES = [
  "New",
  "Acknowledged",
  "Reviewing",
  "Awaiting customer",
  "Awaiting owner",
  "Crew assigned",
  "Team sent",
  "Meeting booked",
  "Monitoring",
  "Resolved",
  "Closed",
];
function IncidentDetail({ incident: i, onClose, user, db, notify }) {
  const [status, setStatus] = useState(i?.status || "New"),
    [owner, setOwner] = useState(i?.confirmedOwner || i?.owner || ""),
    [reason, setReason] = useState(""),
    [crew, setCrew] = useState(""),
    [meeting, setMeeting] = useState({
      date: "2026-11-16",
      start: "10:00",
      end: "11:00",
    }),
    [note, setNote] = useState("");
  useEffect(() => {
    if (i) setStatus(i.status);
  }, [i?.status]);
  if (!i) return null;
  const staff = canReview(user),
    confirmOwner = canConfirmOwner(user),
    dispatcher = canDispatch(user),
    technician = user?.role === "technician";
  const active = activeDispatch(db, i.id),
    meetings = meetingsFor(db, i.id),
    myCrew = technician ? db.crews.find((c) => c.name === user.crew) : null,
    myBusy = myCrew ? crewBusy(db, myCrew.name) : null,
    open = isOpen(i);
  function run(action, success) {
    try {
      mutate(action);
      notify(success);
      return true;
    } catch (error) {
      notify(error.message);
      return false;
    }
  }
  function update() {
    if (["Resolved", "Closed"].includes(status) && !reason.trim()) {
      notify("Add an outcome reason before resolving or closing.");
      return;
    }
    const revision = i.revision;
    run((d) => {
      const row = d.incidents.find((x) => x.id === i.id);
      if (row.revision !== revision)
        throw Error("Case changed. Reopen it to review the latest version.");
      const time = new Date().toISOString();
      if (confirmOwner && owner && owner !== row.confirmedOwner) {
        row.confirmedOwner = owner;
        logIncident(row, `Service owner confirmed: ${owner}`, user.name, time);
      }
      if (status !== row.status || reason.trim()) {
        const from = row.status;
        row.status = status;
        logIncident(
          row,
          `Status ${from === status ? "kept" : "changed"}: ${status}${reason.trim() ? " · " + reason.trim() : ""}`,
          user.name,
          time,
        );
      }
      // Closing the case ends any active crew work, so the crew is free again.
      if (["Resolved", "Closed"].includes(status)) {
        const a = activeDispatch(d, i.id);
        if (a) {
          a.status = "Completed";
          a.completedAt = time;
          logIncident(row, `Crew released: ${a.crew}`, user.name, time);
        }
      }
    }, "Case updated. The change is in the incident log.");
    setReason("");
  }
  const crewOptions = eligibleCrews(db, i);
  return (
    <Modal title={i.id + " · " + i.title} onClose={onClose} wide>
      <div className="detail-meta">
        <Pill tone={["P0", "P1"].includes(i.tier) ? "orange" : "yellow"}>
          {i.tier}
        </Pill>
        <Pill>{i.status}</Pill>
        <span>
          {i.site} · {sites.find((s) => s.id === i.site)?.name} ·{" "}
          {sites.find((s) => s.id === i.site)?.area} · revision {i.revision}
        </span>
        {active && (
          <Pill tone="yellow">
            <Truck size={12} /> {active.crew} · {active.status}
          </Pill>
        )}
      </div>
      {["P0", "P1"].includes(i.tier) && (
        <div className="danger-box">
          <b>
            {i.tier === "P0"
              ? "Immediate danger reported"
              : "Urgent technical review"}
          </b>
          <p>
            If there is smoke, fire, or immediate danger, move away and contact
            emergency services. Do not approach to film or wait for a virtual
            review. No equipment operating instructions are provided.
          </p>
        </div>
      )}
      <h3>What the evidence tells us</h3>
      <p>{i.evidence}</p>
      <div className="info-box">
        Evidence: {i.strength}
        <br />
        Source: synthetic replay · 14 November 2026, 13:00 EET · rule v1.0
        <br />
        Suspected owner: {i.owner} · Confirmed:{" "}
        {i.confirmedOwner || "Awaiting human review"}
      </div>
      {i.family === "Production" && (
        <div className="scenario-stats">
          <span>
            Expected PV<b>4.2 kW</b>
          </span>
          <span>
            Observed PV<b>2.1 kW</b>
          </span>
          <span>
            Evidence window<b>65 minutes</b>
          </span>
        </div>
      )}
      {meetings.some((m) => m.status === "Scheduled") && (
        <div className="ops-meetings">
          {meetings
            .filter((m) => m.status === "Scheduled")
            .map((m) => (
              <div className="meeting-note" key={m.id}>
                <CalendarDays size={14} /> Customer meeting · {m.crew}:{" "}
                <b>{m.date}</b>, {m.start}–{m.end} EET (demo booking)
              </div>
            ))}
        </div>
      )}
      <div className="two-col compact">
        <div>
          <h3>Impact & next step</h3>
          <p>
            Customer consequence:{" "}
            {i.value === null
              ? "unknown"
              : i.value.toFixed(2) +
                " RON/day, conditional on 8 kWh recovered at 0.55 RON/kWh"}
            .
          </p>
          <p>
            Operator consequence: unknown. Repair cost: unknown until reviewed.
          </p>
          <p className="small-note">
            Keep the case open when evidence is insufficient. A qualified
            reviewer confirms routing and any repair advice.
          </p>
        </div>
        <div>
          <h3>Incident log</h3>
          <div className="timeline">
            {i.timeline.map((t, k) => (
              <div key={k}>
                <b>{t.text}</b>
                <small>
                  {t.actor} ·{" "}
                  {new Date(t.time).toLocaleString("en-GB", {
                    timeZone: "Europe/Bucharest",
                  })}{" "}
                  EET
                </small>
              </div>
            ))}
          </div>
        </div>
      </div>
      {technician && myCrew && (
        <div className="ops-actions">
          <h3>Your crew · {myCrew.name}</h3>
          <p className="small-note">
            {myBusy
              ? `${myCrew.name} is ${myBusy.status.toLowerCase()} on ${myBusy.incident}.`
              : `${myCrew.name} is available.`}{" "}
            Demo actions only: no real team, customer or calendar is contacted.
          </p>
          {i.family === "Billing" ? (
            <div className="info-box">
              Billing questions are answered by the PPC dispatcher; no crew visit
              is needed.
            </div>
          ) : (
            open && (
              <div className="button-row">
                <button
                  className="btn yellow"
                  disabled={
                    active?.status === "Team sent" ||
                    (myBusy && myBusy.incident !== i.id) ||
                    (active && active.crew !== myCrew.name)
                  }
                  onClick={() =>
                    run(
                      (d) => sendTeam(d, user, i.id),
                      `${myCrew.name} marked as on the way to ${i.site}. The crew is now unavailable.`,
                    )
                  }
                >
                  <Truck size={16} /> Send the team
                </button>
              </div>
            )
          )}
          {open && (
            <form
              className="ops-meeting-form mt"
              onSubmit={(e) => {
                e.preventDefault();
                run(
                  (d) => scheduleMeeting(d, user, i.id, meeting),
                  "Meeting booked. The customer sees it on their request.",
                );
              }}
            >
              <label>
                Meeting date
                <input
                  type="date"
                  required
                  value={meeting.date}
                  onChange={(e) =>
                    setMeeting({ ...meeting, date: e.target.value })
                  }
                />
              </label>
              <label>
                Start
                <input
                  type="time"
                  required
                  value={meeting.start}
                  onChange={(e) =>
                    setMeeting({ ...meeting, start: e.target.value })
                  }
                />
              </label>
              <label>
                End
                <input
                  type="time"
                  required
                  value={meeting.end}
                  onChange={(e) =>
                    setMeeting({ ...meeting, end: e.target.value })
                  }
                />
              </label>
              <button className="btn secondary">
                <CalendarDays size={16} /> Allocate meeting
              </button>
            </form>
          )}
          {active && active.crew === myCrew.name && (
            <div className="mt">
              <label>
                Resolution note (optional)
                <input
                  maxLength={300}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="What was checked or agreed (synthetic)…"
                />
              </label>
              <button
                className="btn dark"
                onClick={() => {
                  if (
                    run(
                      (d) => resolveIncident(d, user, i.id, note),
                      `Marked resolved. ${myCrew.name} is available again.`,
                    )
                  )
                    setNote("");
                }}
              >
                <CheckCircle2 size={16} /> Mark resolved
              </button>
            </div>
          )}
        </div>
      )}
      {staff && (
        <div className="review-panel">
          <h3>Human review</h3>
          <div className="form-grid">
            <label>
              Case state
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value)}
              >
                {CASE_STATES.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </label>
            {confirmOwner && (
              <label>
                Confirm service owner
                <select
                  value={owner}
                  onChange={(e) => setOwner(e.target.value)}
                >
                  {[
                    "Solar O&M",
                    "Grid operator",
                    "Customer electrician",
                    "PPC dispatch",
                    "Unassigned review",
                  ].map((o) => (
                    <option key={o}>{o}</option>
                  ))}
                </select>
              </label>
            )}
          </div>
          <label>
            Outcome / reason
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              maxLength={1000}
              placeholder="Record evidence, closure reason, or redirect destination…"
            />
          </label>
          <button className="btn yellow" onClick={update}>
            Save review <Check size={17} />
          </button>
          {dispatcher && (
            <>
              <h3 className="mt">Assign a crew</h3>
              {i.family === "Billing" ? (
                <div className="info-box">
                  Billing questions are never given to a crew. Answer the
                  customer in Virtual Visits.
                </div>
              ) : active ? (
                <div className="list-row">
                  <span>
                    <b>{active.crew}</b> · {active.status}
                    <small>
                      Assigned by {active.assignedBy} ·{" "}
                      {new Date(active.assignedAt).toLocaleString("en-GB", {
                        timeZone: "Europe/Bucharest",
                      })}{" "}
                      EET
                    </small>
                  </span>
                  <button
                    className="text-btn"
                    onClick={() =>
                      run(
                        (d) => cancelAssignment(d, user, active.id),
                        "Assignment cancelled; the crew is available again.",
                      )
                    }
                  >
                    Cancel assignment
                  </button>
                </div>
              ) : !open ? (
                <p className="small-note">This case is closed.</p>
              ) : (
                <>
                  <label>
                    Crew
                    <select
                      value={crew}
                      onChange={(e) => setCrew(e.target.value)}
                    >
                      <option value="">
                        {crewOptions.length
                          ? "Choose an available crew"
                          : "No eligible crew is free"}
                      </option>
                      {crewOptions.map((c) => (
                        <option key={c.name}>{c.name}</option>
                      ))}
                    </select>
                  </label>
                  <p className="small-note">
                    {crewOptions.length
                      ? "Eligible: same area as the site, the incident type in the crew's skills, and no active dispatch."
                      : skipReason(db, i)}
                  </p>
                  <button
                    className="btn secondary"
                    disabled={!crew}
                    onClick={() => {
                      if (
                        run(
                          (d) => assignCrew(d, user, i.id, crew),
                          `${crew} assigned to ${i.id}. Demo only: no team was contacted.`,
                        )
                      )
                        setCrew("");
                    }}
                  >
                    Assign crew
                  </button>
                </>
              )}
            </>
          )}
        </div>
      )}
    </Modal>
  );
}
function Media({ id }) {
  const [url, setUrl] = useState(null);
  useEffect(() => {
    let live = true,
      u;
    getMedia(id).then((file) => {
      if (file && live) {
        u = URL.createObjectURL(file);
        setUrl(u);
      }
    });
    return () => {
      live = false;
      if (u) URL.revokeObjectURL(u);
    };
  }, [id]);
  return url ? (
    <video controls src={url} className="video-preview" />
  ) : (
    <p className="small-note">
      Clip unavailable in this browser. Request clarification without relying on
      media.
    </p>
  );
}
function Visits({ db, user, notify, setSelected }) {
  const [selected, setSelectedVisit] = useState(null),
    [reply, setReply] = useState(""),
    [outcome, setOutcome] = useState("Clarification requested");
  const visits = db.visits.filter((v) => canReviewRequest(user, v)),
    visit = visits.find((v) => v.id === selected),
    canRespond = canReview(user);
  return (
    <div className="two-col">
      <section className="card">
        <div className="section-head">
          <div>
            <h3>Virtual visit inbox</h3>
            <p>Asynchronous review. A person, not a model, responds.</p>
          </div>
          <Pill>{visits.length}</Pill>
        </div>
        {!visits.length && (
          <div className="empty">
            <Video size={40} />
            <h3>Your review queue is clear</h3>
            <p>
              Submit a request from a client account to try the full shared
              workflow.
            </p>
          </div>
        )}
        {visits.map((v) => (
          <button
            className={"visit-row " + (selected === v.id ? "selected" : "")}
            key={v.id}
            onClick={() => setSelectedVisit(v.id)}
          >
            <span className="visit-icon">
              <Video size={21} />
            </span>
            <span>
              <b>
                {v.site} · {v.description.slice(0, 55)}
              </b>
              <small>
                {requestTypes.find((request) => request.id === v.requestType)?.label ||
                  "Other or not sure"}{" "}
                · {v.priority === "immediate_danger"
                  ? "Immediate danger"
                  : v.priority === "urgent"
                    ? "Urgent"
                    : "Standard"}{" "}
                · {v.status} · {v.media ? "Video attached" : "Description only"}
              </small>
            </span>
            <ChevronRight size={18} />
          </button>
        ))}
      </section>
      <section className="card">
        {visit ? (
          <>
            <div className="section-head">
              <h3>{visit.site} · Review request</h3>
              <Pill>{visit.status}</Pill>
            </div>
            <div className="info-box">
              <b>
                {requestTypes.find((request) => request.id === visit.requestType)?.label ||
                  "Other or not sure"}
              </b>
              <br />
              Priority:{" "}
              {visit.priority === "immediate_danger"
                ? "Immediate danger"
                : visit.priority === "urgent"
                  ? "Urgent"
                  : "Standard"}
              <br />
              Routed to: {visit.routedTo || "PPC Triage"}
            </div>
            <p>{visit.description}</p>
            {visit.media && <Media id={visit.id} />}
            <button
              className="text-btn"
              onClick={() => setSelected(visit.incident)}
            >
              View shared incident <ArrowUpRight size={16} />
            </button>
            {visit.replies.map((r, i) => (
              <div className="reply" key={i}>
                <b>{r.author}</b>
                <p>{r.text}</p>
                <small>{r.outcome}</small>
              </div>
            ))}
            {canRespond ? (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  mutate((d) => {
                    let v = d.visits.find((x) => x.id === visit.id);
                    v.replies.push({
                      author: user.name,
                      text: reply,
                      outcome,
                      time: new Date().toISOString(),
                    });
                    v.status = outcome;
                    let i = d.incidents.find((x) => x.id === v.incident);
                    if (i) {
                      // An active crew keeps its status; the reply is still logged.
                      if (!activeDispatch(d, i.id))
                        i.status =
                          outcome === "Clarification requested"
                            ? "Awaiting customer"
                            : outcome === "Remote resolution proposed" ||
                                outcome === "Answered by PPC"
                              ? "Monitoring"
                              : "Awaiting owner";
                      logIncident(i, `Reply to customer · ${outcome}: ${reply}`, user.name);
                    }
                  });
                  setReply("");
                  notify("Reply saved. The client can see it in Support.");
                }}
              >
                <label>
                  Response to customer
                  <textarea
                    required
                    minLength={5}
                    maxLength={2000}
                    rows={4}
                    value={reply}
                    onChange={(e) => setReply(e.target.value)}
                    placeholder="Explain the evidence, uncertainty, and approved next step…"
                  />
                </label>
                <label>
                  Review outcome
                  <select
                    value={outcome}
                    onChange={(e) => setOutcome(e.target.value)}
                  >
                    {[
                      "Clarification requested",
                      "Remote resolution proposed",
                      "Escalation proposed",
                      ...(user.role === "dispatcher" ? ["Answered by PPC"] : []),
                    ].map((s) => (
                      <option key={s}>{s}</option>
                    ))}
                  </select>
                </label>
                <button className="btn yellow">
                  Send demo reply <Send size={17} />
                </button>
                <p className="small-note">
                  Do not invent physical operating instructions. Owner and
                  dispatch approval remain separate.
                </p>
              </form>
            ) : (
              <div className="info-box">
                Replies need a dispatcher or technician account.
              </div>
            )}
          </>
        ) : (
          <div className="empty">
            <Mail size={35} />
            <h3>Open a request to review</h3>
            <p>Evidence, conversation and outcome stay together.</p>
          </div>
        )}
      </section>
    </div>
  );
}
function Teams({ db, user, notify, setSelected }) {
  // Overall manager, area manager and dispatcher all read the same db rows.
  const report = teamsReport(db, user);
  const dispatcher = canDispatch(user);
  const [result, setResult] = useState(null),
    [choice, setChoice] = useState({});
  const queue = visibleIncidents(db, user).filter(
    (i) => isOpen(i) && !activeDispatch(db, i.id),
  );
  const active = db.assignments.filter(
    (a) =>
      report.areas.includes(a.area) &&
      ["Assigned", "Team sent", "Scheduled"].includes(a.status),
  );
  const label = (id) => {
    const i = db.incidents.find((x) => x.id === id);
    return i ? `${i.tier} · ${i.id} · ${i.title}` : id;
  };
  function run(action, success) {
    try {
      mutate(action);
      notify(success);
      return true;
    } catch (error) {
      notify(error.message);
      return false;
    }
  }
  return (
    <>
      <section className="card">
        <div className="section-head">
          <div>
            <h3>Assignment report by incident</h3>
            <p>
              {report.areas.length === AREAS.length
                ? "All areas (Sectors 1–6 and Ilfov)"
                : report.areas.join(", ")}{" "}
              · safety tier first, then age · synthetic incidents and crews
            </p>
          </div>
          <Pill>{report.rows.length} rows</Pill>
        </div>
        {!dispatcher && (
          <div className="info-box">
            Read-only report. Only the PPC dispatcher assigns crews; technicians
            send their team, book customer meetings and resolve their cases.
          </div>
        )}
        <AssignmentReport rows={report.rows} onOpen={setSelected} />
      </section>
      <section className="mt">
        <div className="section-head">
          <h3>Crews</h3>
          <Pill>{report.crews.length}</Pill>
        </div>
        <CrewSummary crews={report.crews} />
      </section>
      {dispatcher && (
        <section className="card mt ops-tools">
          <div className="section-head">
            <div>
              <div className="eyebrow">DISPATCHER TOOLS</div>
              <h3>Assign available crews</h3>
              <p>
                Eligible: crew area matches the site, the incident type is in
                its skills, and it has no active dispatch. Billing questions are
                never given to a crew.
              </p>
            </div>
            <button
              className="btn yellow"
              onClick={() => {
                let outcome = null;
                if (
                  run(
                    (d) => {
                      outcome = autoAssign(d, user);
                    },
                    "Severity assignment finished. See the summary below.",
                  )
                )
                  setResult(outcome);
              }}
            >
              Assign by severity <ArrowRight size={16} />
            </button>
          </div>
          {result && (
            <div className="info-box ops-result" role="status">
              <b>
                Assigned {result.assigned.length} · skipped{" "}
                {result.skipped.length}
              </b>
              {result.assigned.length > 0 && (
                <ul>
                  {result.assigned.map((a) => (
                    <li key={a.id}>
                      ✓ {label(a.incident)} → <b>{a.crew}</b>
                    </li>
                  ))}
                </ul>
              )}
              {result.skipped.length > 0 && (
                <ul>
                  {result.skipped.map((s) => (
                    <li key={s.incident}>
                      – {label(s.incident)}: {s.reason}
                    </li>
                  ))}
                </ul>
              )}
              {!result.assigned.length && !result.skipped.length && (
                <p>No open, unassigned incidents in your area.</p>
              )}
            </div>
          )}
          <h3 className="mt">Open incidents without a crew</h3>
          {!queue.length && (
            <div className="empty">
              <CalendarDays size={28} />
              <p>Every open incident in your area has a crew.</p>
            </div>
          )}
          {queue.map((i) => {
            const options = eligibleCrews(db, i);
            return (
              <div className="ops-assign-row" key={i.id}>
                <div>
                  <b>
                    <Pill
                      tone={
                        ["P0", "P1"].includes(i.tier)
                          ? "orange"
                          : i.tier === "P2"
                            ? "yellow"
                            : ""
                      }
                    >
                      {i.tier}
                    </Pill>{" "}
                    {i.id} · {i.title}
                  </b>
                  <small>
                    {i.site} {sites.find((s) => s.id === i.site)?.name} ·{" "}
                    {i.family} · {i.age} min ·{" "}
                    {options.length
                      ? `${options.length} crew free`
                      : skipReason(db, i)}
                  </small>
                </div>
                <select
                  aria-label={`Crew for ${i.id}`}
                  value={choice[i.id] || ""}
                  disabled={!options.length}
                  onChange={(e) =>
                    setChoice({ ...choice, [i.id]: e.target.value })
                  }
                >
                  <option value="">
                    {options.length
                      ? "Choose a crew"
                      : i.family === "Billing"
                        ? "Not crew work"
                        : "No crew free"}
                  </option>
                  {options.map((c) => (
                    <option key={c.name}>{c.name}</option>
                  ))}
                </select>
                <button
                  className="btn secondary"
                  disabled={!choice[i.id]}
                  onClick={() =>
                    run(
                      (d) => assignCrew(d, user, i.id, choice[i.id]),
                      `${choice[i.id]} assigned to ${i.id}. Demo only: no team was contacted.`,
                    ) && setChoice({ ...choice, [i.id]: "" })
                  }
                >
                  Assign
                </button>
              </div>
            );
          })}
          <h3 className="mt">Active assignments and meetings</h3>
          {!active.length && (
            <p className="muted">No active assignments in your area.</p>
          )}
          {active.map((a) => (
            <div className="assignment-row" key={a.id}>
              <div>
                <b>
                  {a.crew} → {label(a.incident)}
                </b>
                <small>
                  {a.kind === "meeting"
                    ? `Meeting ${a.date} ${a.start}–${a.end}`
                    : "Dispatch"}{" "}
                  · {a.assignedBy} ·{" "}
                  {new Date(a.assignedAt).toLocaleString("en-GB", {
                    timeZone: "Europe/Bucharest",
                  })}{" "}
                  EET
                </small>
              </div>
              <Pill>{a.status}</Pill>
              <button
                className="text-btn"
                onClick={() =>
                  run(
                    (d) => cancelAssignment(d, user, a.id),
                    a.kind === "meeting"
                      ? "Meeting cancelled."
                      : "Assignment cancelled; the crew is available again.",
                  )
                }
              >
                Cancel
              </button>
            </div>
          ))}
        </section>
      )}
    </>
  );
}
function Revenue({ db, user }) {
  const scope = user.role === "ceo" ? null : [user.area];
  const report = revenueReport(sites, db.contracts, scope, defaultTariff);
  return (
    <RevenueView
      report={report}
      scopeLabel={scope ? user.area : "All areas (Sectors 1–6 and Ilfov)"}
    />
  );
}
function Account({ db, user, current, notify, logout, setLogin }) {
  const [prefs, setPrefs] = useState(
      db.preferences[user?.id] || {
        notifications: "In-app",
        task: "EV charging",
        deadline: "18:00",
      },
    ),
    [confirmReset, setConfirmReset] = useState(false);
  if (!user)
    return (
      <section className="card empty">
        <User size={40} />
        <h2>Your personal energy workspace</h2>
        <p>
          Log in with a demo account to save plans, contact support, and explore
          role-specific views.
        </p>
        <button className="btn yellow" onClick={() => setLogin(true)}>
          Log in <ArrowRight size={17} />
        </button>
      </section>
    );
  return (
    <div className="two-col">
      <section className="card form-card">
        <div className="profile-heading">
          <span className="avatar large">
            {user.name
              .split(" ")
              .map((s) => s[0])
              .join("")}
          </span>
          <div>
            <h2>{user.name}</h2>
            <p>{user.email}</p>
            <Pill>{roles[user.role]}</Pill>
          </div>
        </div>
        <h3>Preferences</h3>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            mutate((d) => {
              d.preferences[user.id] = prefs;
            });
            notify("Preferences saved in this browser.");
          }}
        >
          <label>
            Preferred task
            <select
              value={prefs.task}
              onChange={(e) => setPrefs({ ...prefs, task: e.target.value })}
            >
              {["EV charging", "Dishwasher", "Washing machine"].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          <label>
            Usual finish deadline
            <input
              type="time"
              value={prefs.deadline}
              onChange={(e) => setPrefs({ ...prefs, deadline: e.target.value })}
            />
          </label>
          <label>
            Notification preference
            <select
              value={prefs.notifications}
              onChange={(e) =>
                setPrefs({ ...prefs, notifications: e.target.value })
              }
            >
              <option>In-app</option>
              <option>Off</option>
            </select>
          </label>
          <button className="btn yellow">
            Save preferences <Check size={17} />
          </button>
        </form>
        <button className="text-btn mt" onClick={logout}>
          <LogOut size={17} />
          Log out
        </button>
      </section>
      <div>
        <section className="card">
          <h3>Your data & access</h3>
          <div className="list-row">
            <span>Access scope</span>
            <b>
              {user.role === "ceo"
                ? "All installations"
                : user.role === "technician"
                  ? `${user.area} · ${user.crew}`
                  : user.sites.length
                    ? user.sites.join(", ")
                    : user.area}
            </b>
          </div>
          <div className="list-row">
            <span>Data source</span>
            <Pill>Fully synthetic replay</Pill>
          </div>
          <div className="list-row">
            <span>Source time</span>
            <b>14 Nov 2026 · 13:00 EET</b>
          </div>
          <div className="list-row">
            <span>Device commands</span>
            <b>Not connected</b>
          </div>
          <p className="small-note">
            Demo data lives in this browser. Media remains until reset. For a
            future production service, configure a real deletion contact and
            retention policy; none is currently staffed.
          </p>
          <details>
            <summary>Download the editable project</summary>
            <p>
              React source, SQL schema, seeded SQLite database, domain tests and
              backend handoff notes.
            </p>
            <a className="btn secondary" href="/solarlenes-source.zip" download>
              <Download size={17} />
              Download source & database
            </a>
          </details>
        </section>
        {user.role === "ceo" && (
          <section className="card mt">
            <h3>Demo controls</h3>
            <p className="muted">
              Restore the {sites.length}-site replay. Clears plans, support requests,
              videos, crew assignments, meetings and incident-log entries in
              this browser.
            </p>
            <button
              className="btn secondary"
              onClick={() => setConfirmReset(true)}
            >
              <RefreshCw size={16} />
              Reset demo
            </button>
            {confirmReset && (
              <div className="danger-box">
                <b>Clear all browser demo changes?</b>
                <div className="button-row">
                  <button
                    className="btn dark"
                    onClick={async () => {
                      await clearMedia();
                      resetDB();
                      setConfirmReset(false);
                      notify("Demo reset to the original synthetic scene.");
                    }}
                  >
                    Yes, reset demo
                  </button>
                  <button
                    className="text-btn"
                    onClick={() => setConfirmReset(false)}
                  >
                    Keep changes
                  </button>
                </div>
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  );
}
