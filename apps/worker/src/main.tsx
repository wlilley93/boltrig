import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./App";
import { bootstrapCharacter } from "./character";
// Side-effect import: installed characters register themselves. Empty in a
// stock build — see characterPlugins.ts.
import "./characterPlugins";
import { AuthGate } from "./components/AuthGate";
import { WorkerErrorBoundary } from "./components/WorkerErrorBoundary";
import { WorkerGlobalContextProvider } from "./components/WorkerGlobalContext";
import { bootstrapProductName } from "./productName";
import { bootstrapAppearance } from "./theme";
import "./styles.css";
import "./components/settings/appearance.css";

bootstrapAppearance();
bootstrapCharacter();
bootstrapProductName();

async function claimEntryTicket() {
  const params = new URLSearchParams(window.location.search);
  const ticket = params.get("enter");
  if (!ticket) return;

  const url = new URL(window.location.href);
  url.searchParams.delete("enter");
  window.history.replaceState({}, "", url.toString());

  try {
    await fetch("/api/auth/enter", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticket }),
    });
  } catch {
    // Swallowed per T8 spec: "swallowing failure, because a spent ticket
    // should fall through to ordinary routing rather than get a screen of its own."
  }
}

const root = document.getElementById("root");
if (!root) throw new Error("root element #root not found");

window.addEventListener("dragover", (event) => event.preventDefault());
window.addEventListener("drop", (event) => event.preventDefault());

(async () => {
  await claimEntryTicket();
  ReactDOM.createRoot(root).render(
    <React.StrictMode>
      <WorkerErrorBoundary>
        <AuthGate>
          <WorkerGlobalContextProvider>
            <App />
          </WorkerGlobalContextProvider>
        </AuthGate>
      </WorkerErrorBoundary>
    </React.StrictMode>,
  );
})();
