import { Suspense, lazy, useEffect, useState } from "react";

import { api } from "./api/client";
import { applyAppearance, loadAppearance } from "./appearance";
import { resetIdentity, updateIdentity, useIdentity } from "./identity";
import { navigate, useRoute } from "./router";
import { useFetch } from "./useFetch";
import { Field, InfoCallout, ROLE_OPTIONS, Select } from "./panels/ux";
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

// Studio pulls in the @xyflow/react canvas; lazy-load it so that heavy chunk
// only downloads when the user opens the authoring hub (code-split, Fix 5).
const StudioPanel = lazy(() =>
  import("./panels/StudioPanel").then((m) => ({ default: m.StudioPanel })),
);

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

// Compact line icons for the sidebar rail (kept dependency-free: small inline
// SVGs, stroke = currentColor, so they inherit the nav item's colour + glow).
const ICON: Record<Tab, JSX.Element> = {
  home: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M4 11.5 12 5l8 6.5" /><path d="M6 10.5V19h12v-8.5" /></svg>
  ),
  router: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><circle cx="6" cy="12" r="2" /><circle cx="18" cy="6" r="2" /><circle cx="18" cy="18" r="2" /><path d="M8 12h3M11 12V6.5h5M11 12v5.5h5" /></svg>
  ),
  studio: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="9.5" width="5" height="5" /><rect x="16" y="4" width="5" height="5" /><rect x="16" y="15" width="5" height="5" /><path d="M8 12h3.5M11.5 12V6.5H16M11.5 12v5.5H16" /></svg>
  ),
  dev: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="5" width="16" height="14" rx="1" /><path d="m8 10 2.5 2L8 14M13.5 14H16" /></svg>
  ),
  chat: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M5 5h14v10H9l-4 4V5Z" /></svg>
  ),
  kanban: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="4" width="4" height="16" /><rect x="10" y="4" width="4" height="11" /><rect x="16" y="4" width="4" height="8" /></svg>
  ),
  approvals: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3 5 6v6c0 4 3 6.5 7 9 4-2.5 7-5 7-9V6l-7-3Z" /><path d="m9 12 2 2 4-4" /></svg>
  ),
  insight: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M4 4v16h16" /><rect x="7" y="12" width="3" height="5" /><rect x="12" y="8" width="3" height="9" /><rect x="17" y="14" width="3" height="3" /></svg>
  ),
  eval: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><rect x="5" y="4" width="14" height="16" rx="1" /><path d="m8 10 2 2 3-4" /><path d="M8 15h7" /></svg>
  ),
  memory: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><ellipse cx="12" cy="6" rx="7" ry="3" /><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6" /><path d="M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" /></svg>
  ),
  admin: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M4 8h16M4 16h16" /><circle cx="9" cy="8" r="2" /><circle cx="15" cy="16" r="2" /></svg>
  ),
  me: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="8" r="3.5" /><path d="M5 20c0-3.9 3.1-7 7-7s7 3.1 7 7" /></svg>
  ),
  settings: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3" /><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1" /></svg>
  ),
};

// The Boltrig mark: a lightning bolt between two "rig" bracket uprights.
function BoltMark() {
  return (
    <svg className="side__mark" viewBox="0 0 24 24" width="22" height="22" fill="none" aria-hidden="true">
      <path d="M7.5 3.5H4.5V20.5H7.5" stroke="currentColor" strokeWidth="2" strokeLinecap="square" />
      <path d="M16.5 3.5H19.5V20.5H16.5" stroke="currentColor" strokeWidth="2" strokeLinecap="square" />
      <path d="M13.2 4.5L8.5 12.6H12L10.8 19.5L15.5 11.4H12L13.2 4.5Z" fill="currentColor" />
    </svg>
  );
}

// The chip that stands in for an always-on dev form: it reads like an identity
// ("Signed in as ...") and expands the editable dev sign-in. In the collapsed
// rail only the avatar initial shows; the text is hidden by CSS.
function IdentityChip({
  expanded,
  onToggle,
}: {
  expanded: boolean;
  onToggle: () => void;
}) {
  const id = useIdentity();
  const initial = (id.subject || "?").trim().charAt(0).toUpperCase() || "?";
  return (
    <button
      className={`identity-chip ${expanded ? "identity-chip--open" : ""}`}
      aria-expanded={expanded}
      title={`Acting as ${id.subject} (${id.role}) @ ${id.tenant}. Click to change the dev sign-in.`}
      onClick={onToggle}
    >
      <span className="identity-chip__avatar" aria-hidden="true">{initial}</span>
      <span className="identity-chip__who">
        <span className="identity-chip__line">
          <strong>{id.subject}</strong>
          <span className="identity-chip__dev" title="Dev sign-in - you can change who you are acting as">dev</span>
        </span>
        <span className="identity-chip__where">{id.role} @ {id.tenant}</span>
      </span>
    </button>
  );
}

const GRANT_PRESETS: ReadonlyArray<{ label: string; value: string }> = [
  { label: "Admin (everything)", value: "*" },
  { label: "Support agent", value: "ticket.*, conversation.*" },
  { label: "Read-only", value: "*.read" },
];

function IdentityBar() {
  const id = useIdentity();
  return (
    <div className="identity-bar" role="group" aria-label="Dev identity">
      <InfoCallout title="Dev sign-in">
        These five values become the <code>x-boltrig-*</code> headers on every
        request, so you can act as any user while building. Production resolves
        identity from SSO or a personal access token instead - the backend
        already supports it.
      </InfoCallout>

      <div className="identity-bar__fields">
        <Field
          label="Organisation"
          hint="Your organisation (tenant) id. Use 'default' for local dev."
        >
          <input
            value={id.tenant}
            onChange={(e) => updateIdentity({ tenant: e.target.value })}
          />
        </Field>

        <Field
          label="Acting as"
          hint="The user id you are acting as - anything works in dev."
          example="alice"
        >
          <input
            value={id.subject}
            onChange={(e) => updateIdentity({ subject: e.target.value })}
          />
        </Field>

        <Field
          label="Role"
          hint="Controls which tabs you see and what the server lets you do. org-admin sees everything; agent is the most limited."
        >
          <Select
            value={id.role}
            ariaLabel="Role"
            onChange={(v) => updateIdentity({ role: v })}
            options={ROLE_OPTIONS}
          />
        </Field>

        <Field
          label="Departments"
          hint="Comma-separated departments you belong to. Narrows what you see in Insight, runs and audit. Leave blank for no extra restriction."
          example="support, billing"
          wide
        >
          <input
            value={id.departments}
            placeholder="support, billing"
            onChange={(e) => updateIdentity({ departments: e.target.value })}
          />
        </Field>

        <Field
          label="Grants"
          hint="What this identity is allowed to do. A grant is a verb id or pattern: * is everything, ticket.* is all ticket actions, ticket.create is one action."
          wide
        >
          <input
            value={id.grants}
            placeholder="* or ticket.*, conversation.read"
            onChange={(e) => updateIdentity({ grants: e.target.value })}
          />
        </Field>
      </div>

      <div className="identity-bar__presets">
        <span className="ux-hint">Quick presets:</span>
        {GRANT_PRESETS.map((p) => (
          <button
            key={p.label}
            type="button"
            className="tag tag--accent identity-bar__preset"
            title={`Set grants to ${p.value}`}
            onClick={() => updateIdentity({ grants: p.value })}
          >
            {p.label}
          </button>
        ))}
        <button
          className="btn btn--ghost btn--sm"
          title="Restore the default dev identity (org 'default', acting as 'dev', role org-admin, grants *)"
          onClick={() => resetIdentity()}
        >
          Reset to defaults
        </button>
      </div>
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
      <span className="health-dot__text">{text}</span>
    </span>
  );
}

export function App() {
  const identity = useIdentity();
  // The active tab is driven by the URL hash (#/chat, #/work, ...) so deep links
  // and browser back / forward work; navigate() writes the hash, useRoute reads.
  const route = useRoute();
  const tab = route.tab as Tab;

  // The dev sign-in is collapsed behind the identity chip by default; expanding it
  // reveals the editable identity bar (the dev auth mechanism).
  const [identityOpen, setIdentityOpen] = useState(false);

  // The expandable sidebar (Opbox pattern): collapsed state persists in
  // localStorage, and drives a single CSS variable on :root that BOTH the sidebar
  // and the main content offset consume, so they move in lockstep.
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem("boltrig:sidebar-collapsed") === "true";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    document.documentElement.style.setProperty(
      "--app-sidebar-width",
      sidebarCollapsed ? "64px" : "236px",
    );
    try {
      localStorage.setItem("boltrig:sidebar-collapsed", sidebarCollapsed ? "true" : "false");
    } catch {
      /* storage may be unavailable; the in-memory state still drives the layout */
    }
  }, [sidebarCollapsed]);

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
    <div className="app app--shell">
      <aside
        className="side"
        data-collapsed={sidebarCollapsed ? "true" : undefined}
        aria-label="Primary navigation"
      >
        <div className="side__brand">
          <BoltMark />
          <strong className="side__word">boltrig</strong>
          <button
            className="side__collapse"
            aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            onClick={() => setSidebarCollapsed((v) => !v)}
          >
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              {sidebarCollapsed ? (
                <path d="m9 6 6 6-6 6" />
              ) : (
                <path d="m15 6-6 6 6 6" />
              )}
            </svg>
          </button>
        </div>

        <nav className="side__nav" aria-label="Panels">
          {PLANES.map((plane) => {
            const planeTabs = visibleTabs.filter((t) => t.plane === plane.id);
            if (planeTabs.length === 0) return null;
            return (
              <div className="side-group" key={plane.id} role="group" aria-label={plane.label}>
                <span className="side-group__label">{plane.label}</span>
                {planeTabs.map((t) => (
                  <button
                    key={t.id}
                    className={`side-item ${active === t.id ? "side-item--active" : ""}`}
                    aria-current={active === t.id ? "page" : undefined}
                    title={t.hint}
                    onClick={() => navigate(`/${t.id}`)}
                  >
                    <span className="side-item__icon" aria-hidden="true">{ICON[t.id]}</span>
                    <span className="side-item__label">{t.label}</span>
                  </button>
                ))}
              </div>
            );
          })}
        </nav>

        <div className="side__foot">
          <HealthDot />
          <IdentityChip
            expanded={identityOpen}
            onToggle={() => setIdentityOpen((v) => !v)}
          />
        </div>
      </aside>

      <div className="app__body">
        {identityOpen && <IdentityBar />}
        <main className="app__main">
          <Suspense fallback={<p className="muted">Loading...</p>}>
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
          </Suspense>
        </main>
      </div>

      {/* The global Run drawer: any surface can raise it via openRun(runId). */}
      <RunView />
    </div>
  );
}
