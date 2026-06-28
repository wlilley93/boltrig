import { useState } from "react";

import { api } from "./api/client";
import { resetIdentity, updateIdentity, useIdentity } from "./identity";
import { useFetch } from "./useFetch";
import { ApprovalsPanel } from "./panels/ApprovalsPanel";
import { KanbanPanel } from "./panels/KanbanPanel";
import { RouterPanel } from "./panels/RouterPanel";

type Tab = "router" | "kanban" | "approvals";

const TABS: ReadonlyArray<{ id: Tab; label: string; hint: string }> = [
  { id: "router", label: "Router", hint: "Nouns, verbs and adapter health" },
  { id: "kanban", label: "Kanban", hint: "Work items by status" },
  { id: "approvals", label: "Approvals", hint: "Pending human-in-the-loop" },
];

function IdentityBar() {
  const id = useIdentity();
  return (
    <div className="identity-bar" role="group" aria-label="Dev identity">
      <span className="identity-bar__title">Identity</span>
      <label className="field">
        <span>tenant</span>
        <input
          value={id.tenant}
          onChange={(e) => updateIdentity({ tenant: e.target.value })}
        />
      </label>
      <label className="field">
        <span>subject</span>
        <input
          value={id.subject}
          onChange={(e) => updateIdentity({ subject: e.target.value })}
        />
      </label>
      <label className="field field--wide">
        <span>grants</span>
        <input
          value={id.grants}
          placeholder="* or noun.verb,other.*"
          onChange={(e) => updateIdentity({ grants: e.target.value })}
        />
      </label>
      <label className="field">
        <span>role</span>
        <input
          value={id.role}
          onChange={(e) => updateIdentity({ role: e.target.value })}
        />
      </label>
      <button className="btn btn--ghost" onClick={() => resetIdentity()}>
        reset
      </button>
    </div>
  );
}

function HealthDot() {
  const health = useFetch(() => api.health(), [], 15000);
  let cls = "dot dot--unknown";
  let text = "kernel: unknown";
  if (health.error) {
    cls = "dot dot--down";
    text = "kernel: unreachable";
  } else if (health.data) {
    cls = "dot dot--ok";
    text = `kernel: ${health.data.status}`;
  }
  return (
    <span className="health-dot" title={text}>
      <span className={cls} aria-hidden="true" />
      {text}
    </span>
  );
}

export function App() {
  const [tab, setTab] = useState<Tab>("router");
  return (
    <div className="app">
      <header className="app__header">
        <div className="app__brand">
          <strong>Nankle</strong>
          <span className="app__subtitle">orchestration console</span>
        </div>
        <HealthDot />
      </header>

      <IdentityBar />

      <nav className="tabs" aria-label="Panels">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`tab ${tab === t.id ? "tab--active" : ""}`}
            aria-current={tab === t.id ? "page" : undefined}
            title={t.hint}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <main className="app__main">
        {tab === "router" && <RouterPanel />}
        {tab === "kanban" && <KanbanPanel />}
        {tab === "approvals" && <ApprovalsPanel />}
      </main>
    </div>
  );
}
