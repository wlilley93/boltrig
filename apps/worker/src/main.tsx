import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./App";
import { bootstrapCharacter } from "./character";
import { AuthGate } from "./components/AuthGate";
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
    <AuthGate>
      <WorkerGlobalContextProvider>
        <App />
      </WorkerGlobalContextProvider>
    </AuthGate>
  </React.StrictMode>,
);
