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
} from "lucide-react";
import {
  roles,
  users,
  sites,
  inverters,
  requestTypes,
  defaultPrices,
  routeRequest,
  crews,
  canSee,
  canDispatch,
  canReview,
  canReviewRequest,
  rank,
  recommend,
  eligible,
  timeLabel,
} from "./domain";
import {
  readDB,
  mutate,
  audit,
  resetDB,
  putMedia,
  getMedia,
  clearMedia,
} from "./store";
import {
  ContractCard,
  EnergyBars,
  ForecastCard,
  FriendlyEnergy,
  LessonDeck,
} from "./features";
import { words } from "./friendly";
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
  Users: ShieldCheck,
  Audit: Clock,
};
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
    [siteId, setSiteId] = useState("S01");
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
  const navs = client
    ? ["Home", "Plan", "Support", "Learn", "Account"]
    : user.role === "support"
      ? ["Virtual Visits", "Account"]
      : [
          "Area Radar",
          "Incidents",
          "Virtual Visits",
          "Teams",
          ...(user.role === "ceo" ? ["Users", "Audit"] : []),
          "Account",
        ];
  const active = navs.includes(page) ? page : navs[0];
  const incidents = rank(db.incidents.filter((i) => canSee(user, i.site)));
  function onLogin(u) {
    sessionStorage.setItem("solar-session", u.id);
    setUserId(u.id);
    setPage(
      u.role === "client"
        ? "Home"
        : u.role === "support"
          ? "Virtual Visits"
          : "Area Radar",
    );
    setSiteId(u.sites[0] || "S01");
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
            <button onClick={() => nav(client ? "Learn" : "Area Radar")}>
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
                <Pill tone={i.tier === "P1" ? "orange" : ""}>{i.tier}</Pill>
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
          {active === "Users" && user?.role === "ceo" && <UserAdmin {...ctx} />}
          {active === "Audit" && user?.role === "ceo" && <Audit db={db} />}
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
          incident={db.incidents.find(
            (i) => i.id === selected && canSee(user, i.site),
          )}
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
        <section className="solar-opportunity">
          <div className="section-head">
            <span className="opportunity-icon">
              <Zap size={23} />
            </span>
            <span className="tiny-label">YOUR NEXT SMART MOVE</span>
            <ArrowUpRight size={19} />
          </div>
          <h2>
            Let the sun
            <br />
            take the next shift.
          </h2>
          <p>
            Move your EV charge to a sunnier window. Same full battery, a better
            use of energy.
          </p>
          <div className="saving">
            <b>4.50</b>
            <span>
              RON
              <br />
              estimated saving
            </span>
          </div>
          <div className="opportunity-time">
            <Clock size={16} />
            <span>13:00 – 15:00</span>
            <Pill>Best window</Pill>
          </div>
          <button className="btn dark full" onClick={() => nav("Plan")}>
            Explore my energy plan <ArrowRight size={17} />
          </button>
          <small>Illustrative 6 kWh charge · Advice, not automation</small>
        </section>
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
      <div className="two-col mt">
        <ForecastCard
          kwp={contract?.installed_kwp || current.capacity}
          contract={contract}
          accountType={accountType}
        />
        <ContractCard
          key={current.id}
          contract={contract}
          defaultKwp={current.capacity}
          onSave={async (value) => {
            if (!user) {
              requireLogin(() => {});
              throw Error("Log in with a demo account to save a contract.");
            }
            mutate((d) => {
              d.contracts = { ...d.contracts, [current.id]: value };
              audit(d, user, "Saved energy contract", current.id);
            });
            notify("Contract saved. Estimates now use your prices.");
          }}
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
            "support",
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
                  <small>{u.name}</small>
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
                <small>{u.name}</small>
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
        audit(d, user, "Accepted energy advice", current.id);
      });
      setOffer(null);
      notify(
        "Plan accepted. Start the appliance yourself at the chosen time. No device was operated.",
      );
    });
  }
  return (
    <div className="two-col">
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
                    : "Assumed (add your contract on Home to replace these):"}{" "}
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
                        audit(d, user, "Cancelled recommendation", p.id);
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
      const routedTo = danger ? "PPC Triage" : request.routeTo;
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
              text: "Customer submitted a report",
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
        audit(d, user, "Submitted support request", incidentId);
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
                        i.status = "Reviewing";
                        i.revision++;
                        i.timeline.push({
                          text: "Customer added a follow-up",
                          actor: user.name,
                          time: new Date().toISOString(),
                        });
                        audit(d, user, "Added support follow-up", v.incident);
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
    [participation, setParticipation] = useState(50);
  let filtered = visibleSites.filter(
    (s) =>
      (area === "All" || s.area === area) &&
      (family === "All" ||
        incidents.some((i) => i.site === s.id && i.family === family)) &&
      (owner === "All" ||
        incidents.some((i) => i.site === s.id && i.owner === owner)),
  );
  return (
    <>
      <div className="stat-grid">
        <Stat
          icon={House}
          label="Monitored installations"
          value={visibleSites.length}
          unit="sites"
          detail="Within your account scope"
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
          value={incidents.filter((i) => i.status !== "Closed").length}
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
              <h3>Installation coverage radar</h3>
              <p>24 synthetic sites · 3 simulated areas</p>
            </div>
            <Pill tone="green">
              <Radio size={12} />
              Replay 13:00
            </Pill>
          </div>
          <div className="filters">
            <select
              aria-label="Filter area"
              value={area}
              onChange={(e) => setArea(e.target.value)}
            >
              <option value="All">All available areas</option>
              {[...new Set(visibleSites.map((s) => s.area))].map((a) => (
                <option key={a}>{a}</option>
              ))}
            </select>
            <select
              aria-label="Filter incident family"
              value={family}
              onChange={(e) => setFamily(e.target.value)}
            >
              <option value="All">All incident types</option>
              {[...new Set(incidents.map((i) => i.family))].map((f) => (
                <option key={f}>{f}</option>
              ))}
            </select>
            <select
              aria-label="Filter owner"
              value={owner}
              onChange={(e) => setOwner(e.target.value)}
            >
              <option value="All">All service owners</option>
              {[...new Set(incidents.map((i) => i.owner))].map((o) => (
                <option key={o}>{o}</option>
              ))}
            </select>
          </div>
          <div className="radar-map">
            <svg
              viewBox="0 0 720 380"
              role="img"
              aria-label="Synthetic installation map with three areas"
            >
              <defs>
                <pattern
                  id="dots"
                  width="18"
                  height="18"
                  patternUnits="userSpaceOnUse"
                >
                  <circle cx="2" cy="2" r=".8" fill="#cbd3cb" />
                </pattern>
              </defs>
              <rect width="720" height="380" fill="url(#dots)" />
              <path
                d="M95 60 L270 35 350 120 304 235 105 260 45 165Z"
                fill="#e8eee5"
                stroke="#c5d1c2"
              />
              <path
                d="M350 120 L520 48 655 135 600 270 442 287 304 235Z"
                fill="#efede1"
                stroke="#d5cfb4"
              />
              <path
                d="M105 260 L304 235 442 287 600 270 572 345 245 365Z"
                fill="#e5eae8"
                stroke="#c4ceca"
              />
              <path
                d="M60 190 Q260 110 360 210 T680 190"
                stroke="#fff"
                strokeWidth="14"
                fill="none"
              />
              <path
                d="M250 35 Q240 180 330 350"
                stroke="#fff"
                strokeWidth="9"
                fill="none"
              />
              {["North", "Central", "South"].map((a, i) => (
                <text
                  key={a}
                  x={[110, 475, 300][i]}
                  y={[85, 95, 340][i]}
                  className="map-label"
                >
                  {a.toUpperCase()} / DEMO-F{i + 1}
                </text>
              ))}
              {filtered.map((s) => {
                const n = +s.id.slice(1) - 1,
                  group = Math.floor(n / 8),
                  j = n % 8;
                const fallbackX = [110, 420, 195][group] + (j % 4) * 48,
                  fallbackY = [120, 140, 280][group] + Math.floor(j / 4) * 54,
                  inverter =
                    db.inverters?.find((item) => item.site === s.id) ||
                    inverters.find((item) => item.site === s.id),
                  x = inverter ? inverter.mapX * 720 : fallbackX,
                  y = inverter ? inverter.mapY * 380 : fallbackY,
                  customers = db.users
                    .filter(
                      (account) =>
                        account.role === "client" &&
                        account.sites.includes(s.id),
                    )
                    .map((account) => account.name)
                    .join(", ") || "No demo client linked";
                const incident = incidents.find(
                    (i) => i.site === s.id && i.status !== "Closed",
                  ),
                  color = s.stale
                    ? "#9aa29a"
                    : incident?.tier === "P1" || incident?.tier === "P0"
                      ? "#df785a"
                      : incident
                        ? "#d2ad22"
                        : "#4a8b6c";
                return (
                  <g
                    key={s.id}
                    role="button"
                    tabIndex="0"
                    aria-label={`${s.id} ${s.name}; client: ${customers}; inverter: ${inverter?.model || "not mapped"}${s.stale ? "; telemetry stale" : ""}`}
                    onKeyDown={(e) =>
                      e.key === "Enter" &&
                      (incident
                        ? setSelected(incident.id)
                        : notify(
                            `${s.id} · ${customers} · ${inverter?.model || "No inverter mapped"} · no supported alerts among monitored inputs.`,
                          ))
                    }
                    onClick={() =>
                      incident
                        ? setSelected(incident.id)
                        : notify(
                            `${s.id} · ${customers} · ${inverter?.model || "No inverter mapped"} · ${s.stale ? "stale telemetry" : "no supported alerts among monitored inputs"}.`,
                          )
                    }
                    style={{ cursor: "pointer" }}
                  >
                    <title>
                      {`${s.name} · Client: ${customers} · Inverter: ${inverter?.manufacturer || ""} ${inverter?.model || "not mapped"} · ${inverter?.serial || "synthetic"}`}
                    </title>
                    <circle cx={x} cy={y} r="15" fill={color} opacity=".12" />
                    <circle
                      cx={x}
                      cy={y}
                      r="6"
                      fill={color}
                      stroke="white"
                      strokeWidth="2"
                    />
                    <text x={x + 10} y={y + 4}>
                      {s.id}
                    </text>
                  </g>
                );
              })}
            </svg>
            <div className="map-legend">
              <span>
                <i style={{ background: "#4a8b6c" }} />
                No supported alert
              </span>
              <span>
                <i style={{ background: "#d2ad22" }} />
                Review
              </span>
              <span>
                <i style={{ background: "#df785a" }} />
                Urgent
              </span>
              <span>
                <i style={{ background: "#9aa29a" }} />
                Stale
              </span>
            </div>
          </div>
          <p className="small-note">
            A coverage diagram, not a validated network digital twin. Nearby
            points do not establish shared feeder membership. Unmonitored
            infrastructure has no health status.
          </p>
        </section>
        <div>
          {["North", "Central", "South"]
            .filter((a) => visibleSites.some((s) => s.area === a))
            .map((a) => {
              const ss = visibleSites.filter((s) => s.area === a);
              return (
                <section className="card area-card" key={a}>
                  <div className="section-head">
                    <h3>{a} area</h3>
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
                          (100 * ss.filter((s) => !s.stale).length) /
                            ss.length +
                          "%",
                      }}
                    />
                  </div>
                  <p>
                    {
                      incidents.filter(
                        (i) =>
                          ss.some((s) => s.id === i.site) &&
                          i.status !== "Closed",
                      ).length
                    }{" "}
                    open incidents · Simulated feeder
                  </p>
                  <button className="text-btn" onClick={() => setArea(a)}>
                    Inspect area <ArrowUpRight size={15} />
                  </button>
                </section>
              );
            })}
        </div>
      </div>
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
            <b>
              {(
                (db.plans
                  .filter(
                    (p) => p.status === "Accepted" && canSee(user, p.site),
                  )
                  .reduce((a, p) => a + p.power, 0) *
                  participation) /
                100
              ).toFixed(1)}{" "}
              kW
            </b>
          </span>
          <span>
            Full-participation task power
            <b>
              {db.plans
                .filter((p) => p.status === "Accepted" && canSee(user, p.site))
                .reduce((a, p) => a + p.power, 0)
                .toFixed(1)}{" "}
              kW
            </b>
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
function Incidents({ incidents, setSelected }) {
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
    <section className="card">
      <div className="section-head">
        <div>
          <h3>Every case, in the right order</h3>
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
                <td>{i.site}</td>
                <td>{i.owner}</td>
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
  );
}
function IncidentDetail({ incident: i, onClose, user, db, notify }) {
  const [status, setStatus] = useState(i?.status || "New"),
    [owner, setOwner] = useState(i?.confirmedOwner || i?.owner || ""),
    [reason, setReason] = useState(""),
    [crew, setCrew] = useState("");
  if (!i) return null;
  const staff = canReview(user),
    dispatch = canDispatch(user);
  function update() {
    if (["Resolved", "Closed"].includes(status) && !reason.trim()) {
      notify("Add an outcome reason before resolving or closing.");
      return;
    }
    const revision = i.revision;
    mutate((d) => {
      const row = d.incidents.find((x) => x.id === i.id);
      if (row.revision !== revision) {
        notify("Case changed. Reopen it to review the latest version.");
        return;
      }
      row.status = status;
      if (dispatch) row.confirmedOwner = owner;
      row.revision++;
      row.timeline.push({
        text: `${status}${reason ? ": " + reason : ""}${dispatch ? " · Owner: " + owner : ""}`,
        actor: user.name,
        time: new Date().toISOString(),
      });
      audit(d, user, "Updated incident: " + status, i.id);
    });
    notify("Case updated with an audit entry.");
    setReason("");
  }
  return (
    <Modal title={i.id + " · " + i.title} onClose={onClose} wide>
      <div className="detail-meta">
        <Pill tone={["P0", "P1"].includes(i.tier) ? "orange" : "yellow"}>
          {i.tier}
        </Pill>
        <Pill>{i.status}</Pill>
        <span>
          {i.site} · {sites.find((s) => s.id === i.site)?.area} · revision{" "}
          {i.revision}
        </span>
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
          <h3>Shared timeline</h3>
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
                {[
                  "New",
                  "Acknowledged",
                  "Reviewing",
                  "Awaiting customer",
                  "Awaiting owner",
                  "Monitoring",
                  "Resolved",
                  "Closed",
                ].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </label>
            {dispatch && (
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
                    "Supplier support",
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
          {dispatch && (
            <>
              <h3 className="mt">Propose a qualified crew</h3>
              <label>
                Crew
                <select value={crew} onChange={(e) => setCrew(e.target.value)}>
                  <option value="">Choose an eligible crew</option>
                  {crews
                    .filter((c) => eligible(c, i, db.assignments))
                    .map((c) => (
                      <option key={c.name}>{c.name}</option>
                    ))}
                </select>
              </label>
              <p className="small-note">
                Matched by owner, qualification, area, 13:00–15:00 shift and
                availability. A proposal is not a dispatch.
              </p>
              <button
                className="btn secondary"
                disabled={!crew}
                onClick={() => {
                  if (
                    !eligible(
                      crews.find((c) => c.name === crew),
                      i,
                      readDB().assignments,
                    )
                  ) {
                    notify("Crew is no longer available.");
                    return;
                  }
                  mutate((d) => {
                    if (
                      d.assignments.some(
                        (a) => a.incident === i.id && a.status !== "Cancelled",
                      )
                    )
                      return;
                    d.assignments.push({
                      id: crypto.randomUUID(),
                      crew,
                      incident: i.id,
                      site: i.site,
                      status: "Proposed",
                      window: "14 Nov · 13:00–15:00 EET",
                    });
                    d.incidents.find((x) => x.id === i.id).status =
                      "Dispatch proposed";
                    audit(d, user, "Proposed crew " + crew, i.id);
                  });
                  notify("Proposal added to Teams for human confirmation.");
                }}
              >
                Propose assignment
              </button>
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
    canRespond =
      canReview(user) ||
      (user.role === "support" && visit?.routedTo === "Supplier Support");
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
            {visit.media && user.role !== "support" && <Media id={visit.id} />}
            {user.role !== "support" && (
              <button
                className="text-btn"
                onClick={() => setSelected(visit.incident)}
              >
                View shared incident <ArrowUpRight size={16} />
              </button>
            )}
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
                    if (user.role !== "support") {
                      let i = d.incidents.find((x) => x.id === v.incident);
                      i.status =
                        outcome === "Clarification requested"
                          ? "Awaiting customer"
                          : outcome === "Remote resolution proposed"
                            ? "Monitoring"
                            : "Awaiting owner";
                      i.revision++;
                      i.timeline.push({
                        text: outcome + ": " + reply,
                        actor: user.name,
                        time: new Date().toISOString(),
                      });
                    }
                    audit(d, user, "Replied to virtual visit", visit.incident);
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
                      ...(user.role === "support"
                        ? ["Supplier response sent", "Clarification requested"]
                        : [
                            "Clarification requested",
                            "Remote resolution proposed",
                            "Escalation proposed",
                          ]),
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
                Supplier support can read assigned request text. Technical media
                review and repair decisions require a technical role.
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
function Teams({ db, user, notify }) {
  const cs = crews.filter(
      (c) =>
        user.role === "ceo" ||
        (user.role === "technician"
          ? c.name === user.crew
          : c.area === user.area),
    ),
    assignments = db.assignments.filter((a) => canSee(user, a.site));
  return (
    <>
      <div className="learn-grid">
        {cs.map((c) => (
          <section className="card crew-card" key={c.name}>
            <div className="section-head">
              <span className="crew-icon">
                <Users size={26} />
              </span>
              <Pill
                tone={
                  db.assignments.some(
                    (a) => a.crew === c.name && a.status === "Confirmed",
                  )
                    ? "orange"
                    : "green"
                }
              >
                {db.assignments.some(
                  (a) => a.crew === c.name && a.status === "Confirmed",
                )
                  ? "Assigned"
                  : "Available"}
              </Pill>
            </div>
            <h2>{c.name}</h2>
            <p>{c.members}</p>
            <div className="list-row">
              <MapPin size={17} />
              {c.area} area · {c.owner}
            </div>
            <div className="list-row">
              <Clock size={17} />
              {c.shift} EET
            </div>
            <div className="skill-tags">
              {c.skills.map((s) => (
                <Pill key={s}>{s}</Pill>
              ))}
            </div>
          </section>
        ))}
      </div>
      <section className="card mt">
        <h3>Assignments awaiting your decision</h3>
        <p className="muted">
          Crew proposals are filtered by qualifications, service owner, shift
          and availability.
        </p>
        {!assignments.length && (
          <div className="empty">
            <CalendarDays size={32} />
            <p>Propose an eligible crew from an incident to begin.</p>
          </div>
        )}
        {assignments.map((a) => (
          <div className="assignment-row" key={a.id}>
            <div>
              <b>
                {a.crew} → {a.incident}
              </b>
              <small>
                {a.site} · {a.window}
              </small>
            </div>
            <Pill>{a.status}</Pill>
            {canDispatch(user) && a.status === "Proposed" && (
              <button
                className="btn yellow"
                onClick={() => {
                  const latest = readDB(),
                    incident = latest.incidents.find(
                      (i) => i.id === a.incident,
                    );
                  if (!incident.confirmedOwner) {
                    notify("Confirm the service owner in the incident review before dispatch.");
                    return;
                  }
                  if (
                    !eligible(
                      crews.find((c) => c.name === a.crew),
                      incident,
                      latest.assignments,
                    )
                  ) {
                    notify("Crew is unavailable or no longer eligible.");
                    return;
                  }
                  mutate((d) => {
                    d.assignments.find((x) => x.id === a.id).status =
                      "Confirmed";
                    let i = d.incidents.find((x) => x.id === a.incident);
                    i.status = "Dispatched";
                    i.revision++;
                    i.timeline.push({
                      text: "Dispatch confirmed: " + a.crew,
                      actor: user.name,
                      time: new Date().toISOString(),
                    });
                    audit(d, user, "Confirmed dispatch " + a.crew, a.incident);
                  });
                  notify(
                    "Demo dispatch confirmed. No external team was contacted.",
                  );
                }}
              >
                Confirm assignment <Check size={16} />
              </button>
            )}
            {canDispatch(user) && a.status !== "Cancelled" && (
              <button
                className="text-btn"
                onClick={() => {
                  mutate((d) => {
                    d.assignments.find((x) => x.id === a.id).status =
                      "Cancelled";
                    let i = d.incidents.find((x) => x.id === a.incident);
                    i.status = "Reviewing";
                    i.revision++;
                    i.timeline.push({
                      text: "Assignment cancelled: " + a.crew,
                      actor: user.name,
                      time: new Date().toISOString(),
                    });
                    audit(d, user, "Cancelled assignment", a.incident);
                  });
                  notify("Assignment cancelled; crew is available again.");
                }}
              >
                Cancel
              </button>
            )}
          </div>
        ))}
      </section>
    </>
  );
}
function UserAdmin({ db, user, notify }) {
  const [q, setQ] = useState("");
  return (
    <section className="card">
      <div className="section-head">
        <div>
          <h3>People & access</h3>
          <p>
            11 seeded accounts. One overall manager. All records are fictional.
          </p>
        </div>
        <a href="/solarlenes-source.zip" download className="btn secondary">
          <Download size={17} />
          Source & database
        </a>
      </div>
      <div className="info-box">
        Frontend permissions demonstrate the intended experience. The included
        SQLite seed uses password hashes; connect server-side sessions and
        enforce these scopes in every API endpoint before real use.
      </div>
      <label className="search mt">
        <Search size={17} />
        <input
          placeholder="Search people or roles"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </label>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Person</th>
              <th>Role</th>
              <th>Scope</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {db.users
              .filter((u) =>
                `${u.name} ${u.email} ${roles[u.role]}`
                  .toLowerCase()
                  .includes(q.toLowerCase()),
              )
              .map((u) => (
                <tr key={u.id}>
                  <td>
                    <b>{u.name}</b>
                    <small>{u.email}</small>
                  </td>
                  <td>{roles[u.role]}</td>
                  <td>
                    {u.role === "ceo"
                      ? "All sites"
                      : u.sites.length
                        ? u.sites.join(", ")
                        : u.area + " area"}
                  </td>
                  <td>
                    <Pill tone={u.active ? "green" : ""}>
                      {u.active ? "Active" : "Disabled"}
                    </Pill>
                  </td>
                  <td>
                    {u.id !== user.id && (
                      <button
                        className="text-btn"
                        onClick={() => {
                          mutate((d) => {
                            d.users.find((x) => x.id === u.id).active =
                              !u.active;
                            audit(
                              d,
                              user,
                              u.active ? "Disabled account" : "Enabled account",
                              u.id,
                            );
                          });
                          notify("Demo account status updated.");
                        }}
                      >
                        {u.active ? "Disable" : "Enable"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
function Audit({ db }) {
  return (
    <section className="card">
      <h3>Decision audit trail</h3>
      <p className="muted">
        Actor, action, subject and receipt time. Browser-local demo history.
      </p>
      {!db.audit.length ? (
        <div className="empty">
          <Clock size={32} />
          <p>Actions taken in the workspace will appear here.</p>
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Time (EET)</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Subject</th>
              </tr>
            </thead>
            <tbody>
              {db.audit.map((a) => (
                <tr key={a.id}>
                  <td>
                    {new Date(a.time).toLocaleString("en-GB", {
                      timeZone: "Europe/Bucharest",
                    })}
                  </td>
                  <td>{a.actor}</td>
                  <td>{a.action}</td>
                  <td>{a.subject}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
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
              audit(d, user, "Updated preferences", user.id);
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
                : user.sites.length
                  ? user.sites.join(", ")
                  : user.area + " area"}
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
              Restore the 24-site replay. Clears plans, support requests,
              videos, decisions and account changes in this browser.
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
