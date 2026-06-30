import { useEffect, useState } from "react";

import { api } from "./api/client";
import { applyAppearance, loadAppearance } from "./appearance";
import { resetIdentity, updateIdentity, useIdentity } from "./identity";
import { navigate, useRoute } from "./router";
import { useFetch } from "./useFetch";
import { AdminPanel } from "./panels/AdminPanel";
import { ApprovalsPanel } from "./panels/ApprovalsPanel";
import { ChatPanel } from "./panels/ChatPanel";
import { DevConsolePanel } from "./panels/DevConsolePanel";
import { EvalPanel } from "./panels/EvalPanel";
import { HomePanel } from "./panels/HomePanel";
import { InsightPanel } from "./panels/InsightPanel";
import { KanbanPanel } from "./panels/KanbanPanel";
import { MePanel } from "./panels/MePanel";
import { MemoryPanel } from "./panels/MemoryPanel";
import { RouterPanel } from "./panels/RouterPanel";
import { SettingsPanel } from "./panels/SettingsPanel";
import { RunView } from "./panels/RunView";
import { StudioPanel } from "./panels/StudioPanel";

type Tab =
  | "home"
  | "router"
  | "kanban"
  | "approvals"
  | "chat"
  | "studio"
  | "dev"
  | "admin"
  | "insight"
  | "eval"
  | "memory"
  | "me"
  | "settings";

// The three planes from the front-end spec (plus a small Account group). Each
// tab declares its plane; the nav renders the tabs grouped under these labels.
// This is presentation only: tab ids, routes (navigate) and role gates are
// unchanged, so deep links keep working.
type Plane = "capability" | "orchestration" | "activity" | "account";

const PLANES: ReadonlyArray<{ id: Plane; label: string }> = [
  { id: "capability", label: "Capability" },
  { id: "orchestration", label: "Orchestration" },
  { id: "activity", label: "Activity" },
  { id: "account", label: "Account" },
];

// Roles permitted to author (studios) / administer (admin console). The server
// is the real gate (403); these only decide whether the tab is offered up front.
export const AUTHOR_ROLES: ReadonlySet<string> = new Set([
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
  // which plane the tab is grouped under in the nav (presentation only).
  plane: Plane;
  // when present, the tab is shown only if the predicate accepts the role.
  gate?: (role: string) => boolean;
}

const TABS: ReadonlyArray<TabDef> = [
  {
    id: "router",
    label: "Router",
    hint: "Nouns, verbs and adapter health",
    plane: "capability",
  },
  {
    id: "studio",
    label: "Studio",
    hint: "Authoring: skills, router, adapters, workflows",
    plane: "capability",
    gate: (role) => AUTHOR_ROLES.has(role),
  },
  {
    id: "dev",
    label: "Dev console",
    hint: "Invoke a verb, spawn an agent, view adapter source",
    plane: "capability",
    gate: (role) => AUTHOR_ROLES.has(role),
  },
  {
    id: "chat",
    label: "Chat",
    hint: "Converse with the orchestrator",
    plane: "orchestration",
  },
  {
    id: "home",
    label: "Home",
    hint: "Your dashboard: approvals, runs and work",
    plane: "activity",
  },
  {
    id: "kanban",
    label: "Kanban",
    hint: "Work items by status",
    plane: "activity",
  },
  {
    id: "approvals",
    label: "Approvals",
    hint: "Pending human-in-the-loop",
    plane: "activity",
  },
  {
    id: "insight",
    label: "Insight",
    hint: "Cost, audit and runs (scoped)",
    plane: "activity",
  },
  {
    id: "eval",
    label: "Eval",
    hint: "No-escalation evaluation harness",
    plane: "activity",
  },
  {
    id: "memory",
    label: "Memory",
    hint: "Recall, browse, remember and ingest (scoped)",
    plane: "activity",
  },
  {
    id: "admin",
    label: "Admin",
    hint: "Manifest config, history, credentials",
    plane: "account",
    gate: (role) => ADMIN_ROLES.has(role),
  },
  {
    id: "me",
    label: "Me",
    hint: "Personal agent, prefs and memory",
    plane: "account",
  },
  {
    id: "settings",
    label: "Settings",
    hint: "Account, tokens, connections, directory",
    plane: "account",
  },
];

// The chip that stands in for an always-on dev form: it reads like an identity
// ("Signed in as ...") and expands the editable dev sign-in below the header.
function IdentityChip({
  expanded,
  onToggle,
}: {
  expanded: boolean;
  onToggle: () => void;
}) {
  const id = useIdentity();
  return (
    <button
      className={`identity-chip ${expanded ? "identity-chip--open" : ""}`}
      aria-expanded={expanded}
      title="Session and identity (dev sign-in)"
      onClick={onToggle}
    >
      <span className="identity-chip__who">
        Signed in as <strong>{id.subject}</strong> ({id.role})
      </span>
      <span className="identity-chip__where">@ {id.tenant}</span>
    </button>
  );
}

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
      <p className="identity-bar__note muted">
        Dev sign-in: these headers set the caller. Production resolves identity
        from SSO / PAT (the backend resolver already supports it).
      </p>
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
  // The active tab is driven by the URL hash (#/chat, #/work, ...) so deep links
  // and browser back / forward work; navigate() writes the hash, useRoute reads.
  const route = useRoute();
  const tab = route.tab as Tab;

  // The dev sign-in is collapsed behind the header chip by default; expanding it
  // reveals the editable identity bar (the dev auth mechanism).
  const [identityOpen, setIdentityOpen] = useState(false);

  // Apply the persisted appearance (theme / density / contrast / font scale /
  // reduced motion) to the document root on first load, before any panel paints,
  // so the saved choice takes effect with no flash. The Settings panel keeps it
  // in sync with the server thereafter.
  useEffect(() => {
    applyAppearance(loadAppearance());
  }, []);

  // Tabs gated by role are hidden when the role does not qualify. If the active
  // tab becomes hidden (role changed), fall back to Router for the render.
  const visibleTabs = TABS.filter((t) => !t.gate || t.gate(identity.role));
  const active: Tab = visibleTabs.some((t) => t.id === tab) ? tab : "home";

  return (
    <div className="app">
      <header className="app__header">
        <div className="app__brand">
          <strong>Boltrig</strong>
          <span className="app__subtitle">orchestration console</span>
        </div>
        <div className="app__header-right">
          <IdentityChip
            expanded={identityOpen}
            onToggle={() => setIdentityOpen((v) => !v)}
          />
          <HealthDot />
        </div>
      </header>

      {identityOpen && <IdentityBar />}

      <nav className="tabs tabs--grouped" aria-label="Panels">
        {PLANES.map((plane) => {
          const planeTabs = visibleTabs.filter((t) => t.plane === plane.id);
          if (planeTabs.length === 0) return null;
          return (
            <div className="tab-group" key={plane.id} role="group" aria-label={plane.label}>
              <span className="tab-group__label">{plane.label}</span>
              <div className="tab-group__tabs">
                {planeTabs.map((t) => (
                  <button
                    key={t.id}
                    className={`tab ${active === t.id ? "tab--active" : ""}`}
                    aria-current={active === t.id ? "page" : undefined}
                    title={t.hint}
                    onClick={() => navigate(`/${t.id}`)}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </nav>

      <main className="app__main">
        {active === "home" && <HomePanel />}
        {active === "router" && <RouterPanel />}
        {active === "kanban" && <KanbanPanel />}
        {active === "approvals" && <ApprovalsPanel />}
        {active === "chat" && <ChatPanel />}
        {active === "studio" && <StudioPanel />}
        {active === "dev" && <DevConsolePanel />}
        {active === "admin" && <AdminPanel />}
        {active === "insight" && <InsightPanel />}
        {active === "eval" && <EvalPanel />}
        {active === "memory" && <MemoryPanel />}
        {active === "me" && <MePanel />}
        {active === "settings" && <SettingsPanel />}
      </main>

      {/* The global Run drawer: any surface can raise it via openRun(runId). */}
      <RunView />
    </div>
  );
}
