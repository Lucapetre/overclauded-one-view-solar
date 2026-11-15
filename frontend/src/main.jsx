import React, { Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import ConnectedApp from "./connected";
import "./styles.css";
import "./connected.css";

const DemoApp = lazy(() => import("./demo"));
const DemoLanding = lazy(() => import("./demoLanding"));
const path = location.pathname.replace(/\/+$/, "");
const classic = path === "/demo/classic" || path.startsWith("/demo/classic/");
const landing = path === "/demo" || (path.startsWith("/demo/") && !classic);

createRoot(document.getElementById("root")).render(
  landing ? (
    <Suspense fallback={<p className="app-loading">Loading demo accounts…</p>}>
      <DemoLanding />
    </Suspense>
  ) : classic ? (
    <>
      <div className="workflow-demo-banner">
        Browser-only workflow simulation · Synthetic accounts and decisions{" "}
        <a href="/demo/">Back to the demo accounts →</a>
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
