import { Fragment, lazy, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { api } from "./api/client";
import { applyAppearance, loadAppearance } from "./appearance";
import { Deck } from "./deck/Deck";
import type { DeckCol } from "./deck/Deck";
import { buildRows, routeToCell } from "./deck/deckMap";
import { resetIdentity, updateIdentity, useIdentity } from "./identity";
import { navigate, useRoute } from "./router";
import { useFetch } from "./useFetch";
import { Field, InfoCallout, ROLE_OPTIONS, Select } from "./panels/ux";
import { AgentSlide } from "./panels/AgentSlide";
import { AdminPanel } from "./panels/AdminPanel";
import { AgentsSlide, useAgentDeckCols } from "./panels/AgentsSlide";
import { ApprovalsPanel } from "./panels/ApprovalsPanel";
import { ChannelsPanel } from "./panels/ChannelsPanel";
import { AutomationsSlide, useAutomationDeckCols } from "./panels/AutomationsSlide";
import { ChatPanel } from "./panels/ChatPanel";
import { DevConsolePanel } from "./panels/DevConsolePanel";
import { EvalPanel } from "./panels/EvalPanel";
import { HomePanel } from "./panels/HomePanel";
import { InsightPanel } from "./panels/InsightPanel";
import { KanbanPanel } from "./panels/KanbanPanel";
import { MePanel } from "./panels/MePanel";
import { MemoryPanel } from "./panels/MemoryPanel";
import { RouterPanel } from "./panels/RouterPanel";
import { SettingsAnchorSlide } from "./panels/settings/AnchorSlide";
import { AccountSlide } from "./panels/settings/AccountSlide";
import { AppearanceSlide } from "./panels/settings/AppearanceSlide";
import { NotificationsSlide } from "./panels/settings/NotificationsSlide";
import { DeveloperSlide } from "./panels/settings/DeveloperSlide";
import { PersonalAgentSlide } from "./panels/settings/PersonalAgentSlide";
import { PrivacySlide } from "./panels/settings/PrivacySlide";
import { SecuritySlide } from "./panels/settings/SecuritySlide";
import { OrganisationSlide } from "./panels/settings/OrganisationSlide";
import { StepSlide } from "./panels/StepSlide";
import { RunView } from "./panels/RunView";
import { CommandPalette } from "./panels/CommandPalette";
import { SessionControls } from "./panels/SessionControls";

// The role gates live with the deck row model now; App re-exports them so the
// existing `import { AUTHOR_ROLES } from "../App"` call sites keep working.
export { ADMIN_ROLES, AUTHOR_ROLES } from "./deck/deckMap";

// Studio pulls in the @xyflow/react canvas; lazy-load it so that heavy chunk
// only downloads when the user opens the authoring hub (code-split, Fix 5).
const StudioPanel = lazy(() =>
  import("./panels/StudioPanel").then((m) => ({ default: m.StudioPanel })),
);

const SIDEBAR_MIN = 200;
const SIDEBAR_MAX = 420;
const SIDEBAR_DEFAULT = 236;

// One-line purpose per nav id (zone rows + ops columns), surfaced as title
// hints. Ids match the deck row / column keys from deckMap.
const HINT: Record<string, string> = {
  chat: "Converse with the orchestrator",
  agents: "The durable agent org chart and worker pool",
  automations: "Workflows: pick one to see its canvas",
  settings: "Account, tokens, connections, directory",
  home: "Your dashboard: approvals, runs and work",
  router: "Nouns, verbs and adapter health",
  studio: "Authoring: skills, router, adapters, workflows",
  dev: "Invoke a verb, spawn an agent, view adapter source",
  kanban: "Work items by status",
  approvals: "Pending human-in-the-loop",
  insight: "Cost, audit and runs (scoped)",
  eval: "No-escalation evaluation harness",
  memory: "Recall, browse, remember and ingest (scoped)",
  admin: "Manifest config, history, credentials",
  me: "Personal agent, prefs and memory",
};

// Compact line icons for the sidebar rail (kept dependency-free: small inline
// SVGs, stroke = currentColor, so they inherit the nav item's colour + glow).
const ICON: Record<string, JSX.Element> = {
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
  agents: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="5.5" r="2.5" /><circle cx="6" cy="18" r="2.5" /><circle cx="18" cy="18" r="2.5" /><path d="M12 8v3.5M12 11.5l-4.5 4M12 11.5l4.5 4" /></svg>
  ),
  automations: (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><circle cx="5" cy="12" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="19" cy="12" r="2" /><path d="M7 12h3M14 12h3" /></svg>
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

// The deck cell -> panel mapping. Module-level so its identity stays stable
// across renders. Unknown cells render null (the deck only asks for cells the
// row model names, so this is a type-level backstop).
function renderCell(rowId: string, colKey: string): ReactNode {
  if (rowId === "chat") return <ChatPanel />;
  if (rowId === "agents") {
    return colKey === "agents" ? <AgentsSlide /> : <AgentSlide agentName={colKey} />;
  }
  if (rowId === "automations") {
    return colKey === "automations" ? <AutomationsSlide /> : <StepSlide stepKey={colKey} />;
  }
  if (rowId === "settings") {
    switch (colKey) {
      case "settings":
        return <SettingsAnchorSlide />;
      case "account":
        return <AccountSlide />;
      case "appearance":
        return <AppearanceSlide />;
      case "notifications":
        return <NotificationsSlide />;
      case "developer":
        return <DeveloperSlide />;
      case "agent":
        return <PersonalAgentSlide />;
      case "privacy":
        return <PrivacySlide />;
      case "security":
        return <SecuritySlide />;
      case "organisation":
        return <OrganisationSlide />;
    }
  }
  if (rowId === "ops") {
    switch (colKey) {
      case "home":
        return <HomePanel />;
      case "router":
        return <RouterPanel />;
      case "studio":
        return <StudioPanel />;
      case "dev":
        return <DevConsolePanel />;
      case "kanban":
        return <KanbanPanel />;
      case "approvals":
        return <ApprovalsPanel />;
      case "insight":
        return <InsightPanel />;
      case "eval":
        return <EvalPanel />;
      case "memory":
        return <MemoryPanel />;
      case "admin":
        return <AdminPanel />;
      case "channels":
        return <ChannelsPanel />;
      case "me":
        return <MePanel />;
    }
  }
  return null;
}

// The chat anchor keeps its React state (an in-flight SSE stream included)
// once visited, even when it is no longer a neighbour of the active cell.
const KEEP_ALIVE = ["chat:chat"];

// The Ops group: Home + the remaining tabs as deck columns, with a pending
// approvals count. The lightweight 30s poll lives HERE so its re-render stays
// inside this sidebar group instead of re-rendering the whole shell + deck.
function OpsGroup({
  cols,
  active,
}: {
  cols: DeckCol[];
  active: { rowId: string; colKey: string };
}) {
  const hitl = useFetch(() => api.hitl(), [], 30000);
  const pending = hitl.data?.requests.length ?? 0;
  const badgeTitle = `${pending} approval(s) waiting`;
  return (
    <div className="side-group" role="group" aria-label="Ops">
      <div className="side-group__head">
        <span className="side-group__label">Ops</span>
        {pending > 0 && (
          <span className="side-badge side-badge--group" title={badgeTitle}>
            {pending}
          </span>
        )}
      </div>
      {cols.map((col) => {
        const isActive = active.rowId === "ops" && active.colKey === col.key;
        return (
          <button
            key={col.key}
            className={`side-item ${isActive ? "side-item--active" : ""}`}
            aria-current={isActive ? "page" : undefined}
            title={HINT[col.key]}
            onClick={() => navigate(col.path)}
          >
            <span className="side-item__icon" aria-hidden="true">{ICON[col.key]}</span>
            <span className="side-item__label">{col.label}</span>
            {col.key === "approvals" && pending > 0 && (
              <span className="side-badge side-badge--item" title={badgeTitle}>
                {pending}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export function App() {
  const identity = useIdentity();
  // The URL hash drives everything: the deck cell via routeToCell, and the Run
  // drawer via route.runId; navigate() writes the hash, useRoute reads it.
  const route = useRoute();

  // Visible rows derive from the CURRENT role each render (the dev IdentityBar
  // changes role live); the deck addresses cells by id, never a stored index.
  const agentCols = useAgentDeckCols();
  const automationCols = useAutomationDeckCols();
  const rows = useMemo(
    () => buildRows(identity.role, agentCols, automationCols),
    [identity.role, agentCols, automationCols],
  );
  const active = routeToCell(route, rows);
  const zoneRows = rows.filter((r) => r.id !== "ops");
  const opsCols = rows.find((r) => r.id === "ops")?.cols ?? [];

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
  const [sidebarWidth, setSidebarWidth] = useState<number>(() => {
    try {
      const w = parseInt(localStorage.getItem("boltrig:sidebar-width") || "", 10);
      return !Number.isNaN(w) && w >= SIDEBAR_MIN && w <= SIDEBAR_MAX ? w : SIDEBAR_DEFAULT;
    } catch {
      return SIDEBAR_DEFAULT;
    }
  });
  const [resizing, setResizing] = useState(false);

  useEffect(() => {
    document.documentElement.style.setProperty(
      "--app-sidebar-width",
      sidebarCollapsed ? "64px" : `${sidebarWidth}px`,
    );
    try {
      localStorage.setItem("boltrig:sidebar-collapsed", sidebarCollapsed ? "true" : "false");
      localStorage.setItem("boltrig:sidebar-width", String(sidebarWidth));
    } catch {
      /* storage may be unavailable; the in-memory state still drives the layout */
    }
  }, [sidebarCollapsed, sidebarWidth]);

  const clampWidth = (w: number) => Math.max(SIDEBAR_MIN, Math.min(SIDEBAR_MAX, w));

  // drag-to-resize the sidebar from its right edge (no-op while collapsed).
  // During the drag we drive the CSS variable IMPERATIVELY so the layout tracks
  // the pointer without a React re-render (and a localStorage write) on every
  // frame; we commit the final width to state once on pointerup, which persists.
  function startResize(e: React.PointerEvent) {
    if (sidebarCollapsed) return;
    e.preventDefault();
    setResizing(true);
    let latest = sidebarWidth;
    const move = (ev: PointerEvent) => {
      latest = clampWidth(ev.clientX);
      document.documentElement.style.setProperty("--app-sidebar-width", `${latest}px`);
    };
    const up = () => {
      setResizing(false);
      setSidebarWidth(latest); // single state update -> single persist
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  // Keyboard-operable resizer (WAI-ARIA separator): arrows nudge, Home/End jump.
  function onResizerKey(e: React.KeyboardEvent) {
    if (sidebarCollapsed) return;
    const step = e.shiftKey ? 32 : 8;
    let next: number | null = null;
    if (e.key === "ArrowLeft") next = sidebarWidth - step;
    else if (e.key === "ArrowRight") next = sidebarWidth + step;
    else if (e.key === "Home") next = SIDEBAR_MIN;
    else if (e.key === "End") next = SIDEBAR_MAX;
    if (next !== null) {
      e.preventDefault();
      setSidebarWidth(clampWidth(next));
    }
  }

  // Apply the persisted appearance (theme / density / contrast / font scale /
  // reduced motion) to the document root on first load, before any panel paints,
  // so the saved choice takes effect with no flash. The Settings panel keeps it
  // in sync with the server thereafter.
  useEffect(() => {
    applyAppearance(loadAppearance());
  }, []);

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

        <button
          className="side-search"
          title="Search and run anything (Cmd/Ctrl-K)"
          onClick={() => window.dispatchEvent(new Event("boltrig:open-palette"))}
        >
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <span className="side-search__label">Search</span>
          <kbd className="side-search__kbd">⌘K</kbd>
        </button>

        <nav className="side__nav" aria-label="Panels">
          <div className="side-group" role="group" aria-label="Zones">
            {zoneRows.map((row) => {
              const rowActive = active.rowId === row.id;
              return (
                <Fragment key={row.id}>
                  <button
                    className={`side-item ${rowActive ? "side-item--active" : ""}`}
                    aria-current={rowActive ? "page" : undefined}
                    title={HINT[row.id]}
                    onClick={() => navigate(row.cols[0].path)}
                  >
                    <span className="side-item__icon" aria-hidden="true">{ICON[row.id]}</span>
                    <span className="side-item__label">{row.label}</span>
                  </button>
                  {rowActive && row.cols.length > 1 && (
                    <div
                      className="side-sublist"
                      role="group"
                      aria-label={`${row.label} slides`}
                    >
                      {row.cols.map((col) => (
                        <button
                          key={col.key}
                          className={`side-subitem ${active.colKey === col.key ? "side-subitem--active" : ""}`}
                          aria-current={active.colKey === col.key ? "page" : undefined}
                          onClick={() => navigate(col.path)}
                        >
                          <span className="side-subitem__label">{col.label}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </Fragment>
              );
            })}
          </div>
          <OpsGroup cols={opsCols} active={active} />
        </nav>

        <div className="side__foot">
          <HealthDot />
          <SessionControls />
          <IdentityChip
            expanded={identityOpen}
            onToggle={() => setIdentityOpen((v) => !v)}
          />
        </div>

        {!sidebarCollapsed && (
          <div
            className={`side__resizer ${resizing ? "side__resizer--on" : ""}`}
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize sidebar"
            aria-valuenow={sidebarWidth}
            aria-valuemin={SIDEBAR_MIN}
            aria-valuemax={SIDEBAR_MAX}
            tabIndex={0}
            onPointerDown={startResize}
            onKeyDown={onResizerKey}
          />
        )}
      </aside>

      <div className="app__body">
        {identityOpen && <IdentityBar />}
        <main className="app__main app__main--deck">
          <Deck
            rows={rows}
            active={active}
            render={renderCell}
            keepAlive={KEEP_ALIVE}
          />
        </main>
      </div>

      {/* The global Run drawer: any surface can raise it via openRun(runId).
          It is position:fixed, so it must stay OUTSIDE the transformed deck. */}
      <RunView />

      {/* Cmd/Ctrl-K jump-to-anything palette - also outside the deck. */}
      <CommandPalette />
    </div>
  );
}
