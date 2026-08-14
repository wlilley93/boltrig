import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import type { ConversationSummary } from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import type { WorkerRoute } from "../routes";
import { SETTINGS_SECTIONS, type SettingsSection } from "../settingsSections";
import { ShellIcon, type ShellIconName } from "./shell/ShellIcon";
import { ShellNav } from "./shell/ShellNav";
import { TaskList } from "./shell/TaskList";
import { useWorkerGlobalContext } from "./WorkerGlobalContext";
import "./ShellParity.css";

// The user menu is intentionally small. The app's task surfaces stay in the
// primary rail; account actions are the only things that belong behind the
// identity control.
const accountMenuItems: Array<{
  action: "spend" | "invite" | "settings" | "logout";
  label: string;
  icon: ShellIconName;
  tail?: string;
}> = [
  { action: "spend", label: "Spend remaining", icon: "gauge", tail: "›" },
  { action: "invite", label: "Invite someone", icon: "invite" },
  { action: "settings", label: "Settings", icon: "gear", tail: "⌘," },
  { action: "logout", label: "Log out", icon: "logout" },
];

// Claude's concept also contains hard-coded release notes and support links.
// This build has neither a changelog feed nor a help destination, so its menu
// keeps the same shell treatment while exposing only destinations that exist.
const helpMenuItems: Array<{
  section: "shortcuts" | "health";
  label: string;
  icon: ShellIconName;
}> = [
  { section: "shortcuts", label: "Keyboard shortcuts", icon: "keyboard" },
  { section: "health", label: "Health and diagnostics", icon: "pulse" },
];

interface SidebarProps {
  route: WorkerRoute;
  conversations: ConversationSummary[];
  conversationStatus?: "loading" | "ready" | "unavailable";
  selectedConversation: string | null;
  onRoute(route: WorkerRoute): void;
  onConversation(id: string): void;
  /** @deprecated Recovery lives in Settings > Archived chats. */
  onConversationRestored?(id: string): void;
  onConversationArchived?(id: string): void;
  /** Conversation ids whose server-owned turn is currently active. */
  workingConversationIds?: readonly string[];
  onLoadMore(): void;
  onRetryConversations?(): void;
  hasMoreConversations: boolean;
  onCommandPalette?(): void;
  /** Present only while the settings surface is open. */
  settingsSection?: SettingsSection;
  onSettingsSection?(section: SettingsSection): void;
  /** Lifted settings search query; when provided, row-level results render in the page. */
  settingsQuery?: string;
  onSettingsQuery?(value: string): void;
}

export function Sidebar({
  route,
  conversations,
  conversationStatus = "ready",
  selectedConversation,
  onRoute,
  onConversation,
  onConversationArchived,
  workingConversationIds = [],
  onLoadMore,
  onRetryConversations,
  hasMoreConversations,
  onCommandPalette,
  settingsSection,
  onSettingsSection,
  settingsQuery: settingsQueryProp,
  onSettingsQuery,
}: SidebarProps) {
  const [localSettingsQuery, setLocalSettingsQuery] = useState("");
  const settingsQuery = settingsQueryProp ?? localSettingsQuery;
  const setSettingsQuery = onSettingsQuery ?? setLocalSettingsQuery;
  const {
    identity,
    identityStatus,
  } = useWorkerGlobalContext();
  const [accountOpen, setAccountOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const accountMenuRef = useRef<HTMLDivElement>(null);
  const helpMenuRef = useRef<HTMLDivElement>(null);
  const accountTriggerRef = useRef<HTMLButtonElement>(null);
  const helpTriggerRef = useRef<HTMLButtonElement>(null);
  const routeMenuOriginRef = useRef<"account" | "help" | null>(null);

  // Overlay-menu state belongs to the route where it was opened. A keyboard
  // shortcut, browser history change, or host-driven navigation can replace
  // that route without clicking the scrim/menu item; never project the old
  // menu over the new surface when that happens.
  useEffect(() => {
    const origin = routeMenuOriginRef.current
      ?? (accountOpen ? "account" : helpOpen ? "help" : null);
    setAccountOpen(false);
    setHelpOpen(false);
    routeMenuOriginRef.current = null;
    if (!origin) return;
    const destination = route === "settings"
      ? document.querySelector<HTMLButtonElement>(".settings-back")
      : origin === "account"
        ? accountTriggerRef.current
        : helpTriggerRef.current;
    destination?.focus();
  }, [route]);

  useEffect(() => {
    if (!accountOpen && !helpOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        const trigger = accountOpen ? accountTriggerRef.current : helpTriggerRef.current;
        setAccountOpen(false);
        setHelpOpen(false);
        trigger?.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [accountOpen, helpOpen]);

  useEffect(() => {
    const menu = accountOpen ? accountMenuRef.current : helpOpen ? helpMenuRef.current : null;
    menu?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
  }, [accountOpen, helpOpen]);

  function chooseAccountAction(action: (typeof accountMenuItems)[number]["action"]) {
    routeMenuOriginRef.current = "account";
    setAccountOpen(false);
    if (action === "spend") {
      onSettingsSection?.("spend");
      onRoute("settings");
      return;
    }
    if (action === "settings") {
      onSettingsSection?.("you");
      onRoute("settings");
      return;
    }
    if (action === "invite") {
      onRoute("organisation");
      return;
    }
    void client.logout().finally(() => window.location.reload());
  }

  function chooseHelpAction(section: (typeof helpMenuItems)[number]["section"]) {
    routeMenuOriginRef.current = "help";
    setHelpOpen(false);
    onSettingsSection?.(section);
    onRoute("settings");
  }

  const initials = (identity?.user ?? "?")
    .split(/[\s@._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("") || "?";
  function moveMenuFocus(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const items = [...event.currentTarget.querySelectorAll<HTMLButtonElement>(
      '[role="menuitem"]:not(:disabled)',
    )];
    if (items.length === 0) return;
    const current = items.indexOf(document.activeElement as HTMLButtonElement);
    const next = event.key === "ArrowDown"
      ? (current + 1) % items.length
      : current < 0
        ? items.length - 1
        : (current - 1 + items.length) % items.length;
    event.preventDefault();
    items[next]?.focus();
  }

  function leaveMenuWithTab(
    event: ReactKeyboardEvent<HTMLDivElement>,
    trigger: HTMLButtonElement | null,
  ) {
    if (event.key !== "Tab") return false;
    event.preventDefault();
    const tabStops = [...document.querySelectorAll<HTMLElement>([
      "a[href]",
      "button:not(:disabled)",
      "input:not(:disabled)",
      "select:not(:disabled)",
      "textarea:not(:disabled)",
      "summary",
      "[contenteditable='true']",
      "[tabindex]",
    ].join(", "))].filter((element) => {
      if (element.tabIndex < 0 || element.closest("[hidden], [aria-hidden='true'], [inert]")) {
        return false;
      }
      for (let current: HTMLElement | null = element; current; current = current.parentElement) {
        const style = window.getComputedStyle(current);
        if (style.display === "none" || style.visibility === "hidden") return false;
      }
      return true;
    });
    const triggerIndex = trigger ? tabStops.indexOf(trigger) : -1;
    const offset = event.shiftKey ? -1 : 1;
    const destination = triggerIndex >= 0 ? tabStops[triggerIndex + offset] : null;
    setAccountOpen(false);
    setHelpOpen(false);
    // Moving relative to the originating trigger reproduces normal document
    // Tab order even though focus is currently on a programmatic menuitem.
    (destination ?? trigger)?.focus();
    return true;
  }

  function handleMenuKeyDown(
    event: ReactKeyboardEvent<HTMLDivElement>,
    trigger: HTMLButtonElement | null,
  ) {
    if (leaveMenuWithTab(event, trigger)) return;
    moveMenuFocus(event);
  }

  function renderAccountMenu() {
    if (!accountOpen) return null;
    return (
      <>
        <button
          aria-label="Close account menu"
          className="side-menu-scrim"
          onClick={() => {
            setAccountOpen(false);
            accountTriggerRef.current?.focus();
          }}
          tabIndex={-1}
          type="button"
        />
        <div
          aria-label="Account"
          className="side-menu shell-overlay-menu"
          onKeyDown={(event) => handleMenuKeyDown(event, accountTriggerRef.current)}
          ref={accountMenuRef}
          role="menu"
        >
          <div className="side-menu-identity">
            <span aria-hidden className="side-avatar">{initials}</span>
            <span className="side-menu-identity-copy">
              <span className="side-menu-name">
                {identity
                  ? identity.user
                  : (identityStatus === "unavailable" ? "Identity unavailable" : "Loading identity…")}
              </span>
              {identity?.role && <small className="side-menu-role">{identity.role}</small>}
            </span>
          </div>
          {accountMenuItems.map((item) => (
            <button
              className="side-menu-row shell-parity-menu-row"
              key={item.action}
              onClick={() => chooseAccountAction(item.action)}
              role="menuitem"
              tabIndex={-1}
              type="button"
            >
              <span className="nav-icon"><ShellIcon name={item.icon} size={15} /></span>
              <span className="shell-menu-label">{item.label}</span>
              {item.tail && (
                <span aria-hidden className={`shell-menu-tail${item.action === "spend" ? " disclosure" : ""}`}>
                  {item.tail}
                </span>
              )}
            </button>
          ))}
        </div>
      </>
    );
  }

  function renderHelpMenu() {
    if (!helpOpen) return null;
    return (
      <>
        <button
          aria-label="Close help menu"
          className="side-menu-scrim"
          onClick={() => {
            setHelpOpen(false);
            helpTriggerRef.current?.focus();
          }}
          tabIndex={-1}
          type="button"
        />
        <div
          aria-label="Help"
          className="side-menu shell-overlay-menu shell-help-menu"
          onKeyDown={(event) => handleMenuKeyDown(event, helpTriggerRef.current)}
          ref={helpMenuRef}
          role="menu"
        >
          <p className="shell-help-heading">Help</p>
          {helpMenuItems.map((item) => (
            <button
              className="side-menu-row shell-parity-menu-row"
              key={item.section}
              onClick={() => chooseHelpAction(item.section)}
              role="menuitem"
              tabIndex={-1}
              type="button"
            >
              <span className="nav-icon"><ShellIcon name={item.icon} size={15} /></span>
              <span className="shell-menu-label">{item.label}</span>
            </button>
          ))}
        </div>
      </>
    );
  }

  function renderSidebarFooter() {
    return (
      <div className="sidebar-footer">
        <button
          aria-expanded={accountOpen}
          aria-haspopup="menu"
          aria-label={identity
            ? `Signed in as ${identity.user}${identity.role ? `, role ${identity.role}` : ""}. Account menu`
            : `Account menu, identity ${identityStatus}`}
          className="side-account"
          onClick={() => {
            setAccountOpen((current) => !current);
            setHelpOpen(false);
          }}
          ref={accountTriggerRef}
          type="button"
        >
          <span aria-hidden className="side-avatar">{initials}</span>
          <span className="side-account-name">
            {identity?.user
              ?? (identityStatus === "unavailable" ? "Identity unavailable" : "Loading identity…")}
          </span>
        </button>
        <button
          aria-expanded={helpOpen}
          aria-haspopup="menu"
          aria-label="Help and shortcuts"
          className="side-round-button"
          onClick={() => {
            setHelpOpen((current) => !current);
            setAccountOpen(false);
          }}
          title="Help and shortcuts"
          ref={helpTriggerRef}
          type="button"
        >
          <ShellIcon name="question" size={12} strokeWidth={2.1} />
        </button>
      </div>
    );
  }

  // In settings the sidebar becomes the self-contained settings rail drawn by
  // the decided target: back, search, and the registered sections. Account and
  // global-help controls remain one click away via Back to app; repeating them
  // here adds a second footer the signed frame does not contain.
  if (route === "settings" && onSettingsSection) {
    return (
      <aside className="sidebar" aria-label="Settings navigation">
        <div className="settings-side-top">
          <button className="settings-back" onClick={() => onRoute("chat")} type="button">
            <svg aria-hidden fill="none" height="15" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" viewBox="0 0 24 24" width="15">
              <line x1="19" x2="5" y1="12" y2="12" />
              <polyline points="11 18 5 12 11 6" />
            </svg>
            <span>Back to app</span>
          </button>
          <div className="settings-search">
            <svg aria-hidden fill="none" height="14" stroke="var(--text-4)" strokeLinecap="round" strokeWidth="2" viewBox="0 0 24 24" width="14">
              <circle cx="11" cy="11" r="7" />
              <line x1="16.5" x2="21" y1="16.5" y2="21" />
            </svg>
            <input
              aria-label="Search every setting"
              onChange={(event) => setSettingsQuery(event.target.value)}
              placeholder="Search every setting"
              value={settingsQuery}
            />
          </div>
        </div>
        <nav aria-label="Settings sections" className="settings-side-nav">
          {SETTINGS_SECTIONS.map((entry) => (
            <div key={entry.id}>
              {entry.head && (
                <p className="settings-side-head">{entry.head}</p>
              )}
              <button
                aria-current={settingsSection === entry.id ? "page" : undefined}
                className={settingsSection === entry.id ? "nav-row active" : "nav-row"}
                onClick={() => onSettingsSection(entry.id)}
                type="button"
              >
                <span className="nav-icon"><ShellIcon name={settingsIcon(entry.id)} size={15} /></span>
                <span>{entry.label}</span>
              </button>
            </div>
          ))}
        </nav>
      </aside>
    );
  }

  return (
    <aside
      className="sidebar shell-parity"
      aria-label="Worker navigation"
    >
      <ShellNav
        onCommandPalette={onCommandPalette}
        onRoute={onRoute}
        route={route}
      />
      <TaskList
        conversations={conversations}
        conversationStatus={conversationStatus}
        hasMoreConversations={hasMoreConversations}
        onConversation={onConversation}
        onConversationArchived={onConversationArchived}
        onLoadMore={onLoadMore}
        onRetryConversations={onRetryConversations}
        selectedConversation={selectedConversation}
        workingConversationIds={workingConversationIds}
      />

      {renderAccountMenu()}
      {renderHelpMenu()}
      {renderSidebarFooter()}
    </aside>
  );
}
const settingsIcons: Record<SettingsSection, ShellIconName> = {
  you: "user",
  sensing: "camera",
  autonomy: "shield",
  spend: "gauge",
  models: "code",
  shortcuts: "keyboard",
  knowledge: "book",
  overnight: "moon",
  health: "pulse",
  operations: "pulse",
  organisation: "org",
  advanced: "code",
  archived: "archive",
};

function settingsIcon(section: SettingsSection): ShellIconName {
  return settingsIcons[section];
}

export function Topbar({ title, status }: { title: string; status?: string }) {
  const { identity, identityStatus } = useWorkerGlobalContext();
  const identityTitle = identity
    ? `Signed in as ${identity.user}${identity.role ? ` (${identity.role})` : ""}`
    : undefined;

  return (
    <header className="topbar">
      <div className="topbar-heading">
        <h1>{title}</h1>
        {status && <span className="topbar-context">{status}</span>}
      </div>
      <div className="topbar-actions">
        <span
          className={`identity-chip ${identityStatus}`}
          title={identityTitle}
        >
          <strong>{identity?.user ?? (identityStatus === "unavailable" ? "Identity unavailable" : "You")}</strong>
        </span>
      </div>
    </header>
  );
}

export function Unavailable({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="empty-card" role="status">
      <div className="empty-orbit" aria-hidden>◌</div>
      <h2>{title}</h2>
      <p>{children}</p>
    </section>
  );
}
