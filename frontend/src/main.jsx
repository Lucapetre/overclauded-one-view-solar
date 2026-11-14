import React, { Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import ConnectedApp from "./connected";
import "./styles.css";
import "./connected.css";

const DemoApp = lazy(() => import("./demo"));
const demo =
  location.pathname === "/demo" || location.pathname.startsWith("/demo/");

createRoot(document.getElementById("root")).render(
  demo ? (
    <>
      <div className="workflow-demo-banner">
        Browser-only workflow simulation · Synthetic accounts and decisions{" "}
        <a href="/consumer">Return to connected app →</a>
      </div>
      <Suspense
        fallback={<p className="app-loading">Loading workflow demo…</p>}
      >
        <DemoApp />
      </Suspense>
    </>
  ) : (
    <ConnectedApp />
  ),
);
