import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./App";
import { AuthGate } from "./panels/AuthGate";
import { ErrorBoundary } from "./ErrorBoundary";
import "./styles.css";
import "./styles/shell-vnext.css";
import "./styles/work-board.css";
import "./styles/home-operations.css";

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("root element #root not found");

const PrototypeApp = React.lazy(() =>
  import("./prototype/PrototypeApp").then((module) => ({ default: module.PrototypeApp })),
);

function isPrototypeRoute(hash: string) {
  const route = hash.replace(/^#\/?/, "");
  return route === "prototype" || route.startsWith("prototype/");
}

function RootApp() {
  const [hash, setHash] = React.useState(() => window.location.hash);
  React.useEffect(() => {
    const update = () => setHash(window.location.hash);
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);

  // D15: the prototype is a local design harness, never a production client.
  const prototypeEnabled = import.meta.env.DEV;
  if (prototypeEnabled && isPrototypeRoute(hash)) {
    return <React.Suspense fallback={<div className="auth-loading">Opening prototype…</div>}><PrototypeApp /></React.Suspense>;
  }
  return <AuthGate><App /></AuthGate>;
}

ReactDOM.createRoot(rootEl).render(
  <React.StrictMode>
    <ErrorBoundary label="Boltrig">
      <RootApp />
    </ErrorBoundary>
  </React.StrictMode>,
);
