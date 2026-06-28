import { useState } from "react";

import { api } from "./api/client";
import { resetIdentity, updateIdentity, useIdentity } from "./identity";
import { useFetch } from "./useFetch";
import { AdminPanel } from "./panels/AdminPanel";
import { ApprovalsPanel } from "./panels/ApprovalsPanel";
import { ChatPanel } from "./panels/ChatPanel";
import { EvalPanel } from "./panels/EvalPanel";
import { InsightPanel } from "./panels/InsightPanel";
import { KanbanPanel } from "./panels/KanbanPanel";
import { MePanel } from "./panels/MePanel";
import { RouterPanel } from "./panels/RouterPanel";
import { StudioPanel } from "./panels/StudioPanel";

type Tab =
  | "router"
  | "kanban"
  | "approvals"
  | "chat"
  | "studio"
  | "admin"
  | "insight"
  | "eval"
  | "me";

// Roles permitted to author (studios) / administer (admin console). The server
// is the real gate (403); these only decide whether the tab is offered up front.
const AUTHOR_ROLES: ReadonlySet<string> = new Set([
  "org-admin",
  "department-head",
  "manager",
  "lead",
  "integrator",
]);
const ADMIN_ROLES: ReadonlySet<string> = new Set(["org-admin"]);

interface TabDef {
  id: Tab;
  label: string;
  hint: string;
  // when present, the tab is shown only if the predicate accepts the role.
  gate?: (role: string) => boolean;
}

const TABS: ReadonlyArray<TabDef> = [
  { id: "router", label: "Router", hint: "Nouns, verbs and adapter health" },
  { id: "kanban", label: "Kanban", hint: "Work items by status" },
  { id: "approvals", label: "Approvals", hint: "Pending human-in-the-loop" },
  { id: "chat", label: "Chat", hint: "Converse with the orchestrator" },
  {
    id: "studio",
    label: "Studio",
    hint: "Authoring: skills, router, adapters, workflows",
    gate: (role) => AUTHOR_ROLES.has(role),
  },
  {
    id: "admin",
    label: "Admin",
    hint: "Manifest config, history, credentials",
    gate: (role) => ADMIN_ROLES.has(role),
  },
  { id: "insight", label: "Insight", hint: "Cost, audit and runs (scoped)" },
  { id: "eval", label: "Eval", hint: "No-escalation evaluation harness" },
  { id: "me", label: "Me", hint: "Personal agent, prefs and memory" },
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
      <label className="field field--wide">
        <span>departments</span>
        <input
          value={id.departments}
          placeholder="support,billing (scopes audit/runs)"
          onChange={(e) => updateIdentity({ departments: e.target.value })}
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
  const identity = useIdentity();
  const [tab, setTab] = useState<Tab>("router");

  // Tabs gated by role are hidden when the role does not qualify. If the active
  // tab becomes hidden (role changed), fall back to Router for the render.
  const visibleTabs = TABS.filter((t) => !t.gate || t.gate(identity.role));
  const active: Tab = visibleTabs.some((t) => t.id === tab) ? tab : "router";

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
        {visibleTabs.map((t) => (
          <button
            key={t.id}
            className={`tab ${active === t.id ? "tab--active" : ""}`}
            aria-current={active === t.id ? "page" : undefined}
            title={t.hint}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <main className="app__main">
        {active === "router" && <RouterPanel />}
        {active === "kanban" && <KanbanPanel />}
        {active === "approvals" && <ApprovalsPanel />}
        {active === "chat" && <ChatPanel />}
        {active === "studio" && <StudioPanel />}
        {active === "admin" && <AdminPanel />}
        {active === "insight" && <InsightPanel />}
        {active === "eval" && <EvalPanel />}
        {active === "me" && <MePanel />}
      </main>
    </div>
  );
}
