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
import { bootstrapAppearance } from "./theme";
import "./styles.css";
import "./components/settings/appearance.css";

bootstrapAppearance();
bootstrapCharacter();

const root = document.getElementById("root");
if (!root) throw new Error("root element #root not found");

window.addEventListener("dragover", (event) => event.preventDefault());
window.addEventListener("drop", (event) => event.preventDefault());

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
