import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./App";
import { ErrorBoundary } from "./ErrorBoundary";
import "./styles.css";

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("root element #root not found");

ReactDOM.createRoot(rootEl).render(
  <React.StrictMode>
    <ErrorBoundary label="Boltrig">
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
);
