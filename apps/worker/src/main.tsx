import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./App";
import { AuthGate } from "./components/AuthGate";
import { WorkerGlobalContextProvider } from "./components/WorkerGlobalContext";
import "./styles.css";

try {
  const theme = localStorage.getItem("boltrig-worker-theme");
  const dark = theme === "dark"
    || (theme !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
} catch {
  // Storage can be unavailable in hardened browser contexts; the light
  // foundation remains usable without it.
}

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
