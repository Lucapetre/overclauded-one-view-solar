// Local demo landing: one-click sign-in to every account type of the SAME connected app.
import React, { useEffect, useState } from "react";
import { ArrowRight, Sun } from "lucide-react";
import { SolarClient } from "../../packages/contracts/client";
import { demoGroups } from "./demoAccounts";

const api = new SolarClient(import.meta.env.VITE_API_URL || "");

export default function DemoLanding() {
  const [accounts, setAccounts] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState("");
  useEffect(() => {
    api
      .demoAccounts()
      .then(setAccounts)
      .catch((failure) => setError(failure));
  }, []);
  async function enter(account) {
    setBusy(account.username);
    try {
      await api.demoLogin(account.username);
      location.assign(account.role === "customer" ? "/consumer" : "/ops");
    } catch (failure) {
      setError(failure);
      setBusy("");
    }
  }
  return (
    <main className="demo-landing">
      <header>
        <a className="brand" href="/demo/">
          <Sun size={30} /> SolarLens<span className="brand-dot">®</span>
        </a>
        <div className="eyebrow">DEMO · SYNTHETIC DATA · NOT CONNECTED TO REAL EQUIPMENT</div>
        <h1>
          Try every account type<span className="yellow-dot">.</span>
        </h1>
        <p className="muted">
          One click signs you in to the real app with a fictional account. Everything you
          see is synthetic replay data; no device is ever controlled.
        </p>
      </header>
      {error && (
        <section className="card demo-landing-off" role="alert">
          <b>Demo sign-in is not available.</b>
          <p>
            Start the local server with <code>SOLAR_DEMO_LOGIN=true</code> (local demo
            only), or sign in normally at <a href="/consumer">/consumer</a>.
          </p>
          <p>
            The older browser-only workflow simulation is still at{" "}
            <a href="/demo/classic">/demo/classic</a>.
          </p>
        </section>
      )}
      {!accounts && !error && <p className="muted">Loading demo accounts…</p>}
      {accounts &&
        demoGroups(accounts).map((group) => (
          <section key={group.title} className="demo-landing-group">
            <h2>{group.title}</h2>
            <div className="demo-landing-grid">
              {group.accounts.map((account) => (
                <article className="card demo-account" key={account.username}>
                  <div className="section-head">
                    <h3>{account.name}</h3>
                    <span className="pill">{account.label}</span>
                  </div>
                  <p>{account.description}</p>
                  <small className="muted">Username: {account.username}</small>
                  <button
                    className="btn yellow full"
                    disabled={Boolean(busy)}
                    onClick={() => enter(account)}
                  >
                    {busy === account.username
                      ? "Signing in…"
                      : `Enter as ${account.name}`}
                    <ArrowRight size={16} />
                  </button>
                </article>
              ))}
            </div>
          </section>
        ))}
      <p className="small-note">
        Looking for the old browser-only simulation?{" "}
        <a href="/demo/classic">Open it here</a>.
      </p>
    </main>
  );
}
