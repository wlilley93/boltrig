import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import type {
  ConversationSearchResult,
  ConversationSummary,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import type { WorkerRoute } from "../routes";
import { SETTINGS_SECTIONS, type SettingsSection } from "../settingsSections";
import { useWorkerGlobalContext } from "./WorkerGlobalContext";
import "./ShellParity.css";

// Stroke-path icons carried over from the Boltrig Console design component so
// the sidebar reads exactly like the design. Each entry is one or more SVG
// path `d` strings drawn at 24x24 with a 1.7 stroke.
const ICON_PATHS: Record<string, string[]> = {
  plus: ["M12 5v14M5 12h14"],
  chat: ["M5 4.5h14a1.5 1.5 0 0 1 1.5 1.5v8a1.5 1.5 0 0 1-1.5 1.5H9l-4.5 4V6A1.5 1.5 0 0 1 5 4.5z"],
  agents: [
    "M12 3.4a2.6 2.6 0 1 1 0 5.2 2.6 2.6 0 0 1 0-5.2z",
    "M5 20.4a2.4 2.4 0 1 1 0-4.8 2.4 2.4 0 0 1 0 4.8zM19 20.4a2.4 2.4 0 1 1 0-4.8 2.4 2.4 0 0 1 0 4.8z",
    "M12 8.6v3.2M5 15.6c0-1.9 1.6-3.5 3.5-3.5h7c1.9 0 3.5 1.6 3.5 3.5",
  ],
  plug: ["M8 3v5M16 3v5", "M5.5 8h13v3a6.5 6.5 0 0 1-13 0z", "M12 17.5V21"],
  flow: ["M4.5 5.5h5v4h-5zM14.5 5.5h5v4h-5zM9.5 14.5h5v4h-5z", "M7 9.5v2.5h10V9.5M12 12v2.5"],
  home: ["M4.5 10.5l7.5-6.5 7.5 6.5V20h-15z"],
  clock: ["M12 4a8 8 0 1 1 0 16 8 8 0 0 1 0-16z", "M12 7.8V12l2.8 1.8"],
  work: ["M4 5.5h16v13H4z", "M4 10h16M10 5.5v13"],
  book: [
    "M4.5 4.5h6a3 3 0 0 1 3 3v12a2.5 2.5 0 0 0-2.5-2.5h-6.5z",
    "M19.5 4.5h-6a3 3 0 0 0-3 3v12a2.5 2.5 0 0 1 2.5-2.5h6.5z",
  ],
  brain: [
    "M9.5 4a3 3 0 0 0-3 3 2.8 2.8 0 0 0-1 5.4V16a3 3 0 0 0 5 2.2",
    "M14.5 4a3 3 0 0 1 3 3 2.8 2.8 0 0 1 1 5.4V16a3 3 0 0 1-5 2.2",
    "M12 5v14",
  ],
  registry: ["M4 4.5h16v5H4zM4 14.5h16v5H4z", "M7.5 7h.01M7.5 17h.01"],
  skill: ["M12 3.5l2.4 5 5.6.8-4 3.9 1 5.5-5-2.6-5 2.6 1-5.5-4-3.9 5.6-.8z"],
  monitor: ["M3.5 5h17v10h-17z", "M9 19h6M12 15v4"],
  pulse: ["M3 12h4l2-5 4 10 2-5h6"],
  pin: ["M8 4h8v4l2.5 3.5H5.5L8 8z", "M12 11.5V21"],
  shield: ["M12 3l7 3v5.5c0 4.6-3 7.2-7 8.5-4-1.3-7-3.9-7-8.5V6z"],
  gauge: ["M12 3.5a8.5 8.5 0 1 0 8.5 8.5", "M12 12l4.5-3.5"],
  invite: ["M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z", "M2.5 20c0-3.6 2.9-6.5 6.5-6.5s6.5 2.9 6.5 6.5M18.5 8.5v5M16 11h5"],
  keyboard: ["M3.5 6.5h17v11h-17z", "M7 10h.01M11 10h.01M15 10h.01M8 14h8"],
  moon: ["M20 14.5A8.2 8.2 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"],
  archive: ["M3.5 4.5h17v4h-17z", "M5 8.5v11h14v-11M10 12.5h4"],
  user: ["M12 4.6a3.4 3.4 0 1 1 0 6.8 3.4 3.4 0 0 1 0-6.8z", "M5 20c0-3.6 3.1-6 7-6s7 2.4 7 6"],
  org: [
    "M6.5 7.5v9",
    "M6.5 7.5a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM6.5 20.5a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM17.5 7.5a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
    "M17.5 7.5v2.5a3 3 0 0 1-3 3h-8",
  ],
  gear: [
    "M12 9.2a2.8 2.8 0 1 1 0 5.6 2.8 2.8 0 0 1 0-5.6z",
    "M19.9 14.6a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 0 1-4 0v-.1a1.6 1.6 0 0 0-2.7-1.1l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.6 1.6 0 0 0 4.1 14H4a2 2 0 0 1 0-4h.1a1.6 1.6 0 0 0 1.1-2.7l-.1-.1A2 2 0 1 1 7.9 4.4l.1.1A1.6 1.6 0 0 0 10.7 3.4V3a2 2 0 0 1 4 0v.4a1.6 1.6 0 0 0 2.7 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0 1.1 2.7H21a2 2 0 0 1 0 4h-.1a1.6 1.6 0 0 0-1 .6z",
  ],
  code: ["M8.5 7.5L4 12l4.5 4.5M15.5 7.5L20 12l-4.5 4.5"],
  logout: ["M10 4.5H5.5v15H10", "M14 8l4 4-4 4M18 12H9"],
  question: ["M9.2 9.2a2.9 2.9 0 1 1 4.3 2.6c-.9.5-1.5 1.1-1.5 2.1", "M12 17.6v.1"],
};

function Icon({
  name,
  size = 16,
  strokeWidth = 1.7,
}: {
  name: keyof typeof ICON_PATHS;
  size?: number;
  strokeWidth?: number;
}) {
  return (
    <svg
      aria-hidden
      fill="none"
      height={size}
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={strokeWidth}
      viewBox="0 0 24 24"
      width={size}
    >
      {ICON_PATHS[name].map((d) => <path d={d} key={d} />)}
    </svg>
  );
}

// The console nav holds the task-first surfaces under the names the decided
// target gives them — Plugins and Routines, not Integrations and Automations
// (the browser acceptance contract names them exactly, so it moves with this
// list). The design carries only these four; deeper operational records stay
// in their dedicated surfaces.
const primary: Array<{
  route: WorkerRoute;
  label: string;
  icon: keyof typeof ICON_PATHS;
  shortcut?: string;
  title?: string;
}> = [
  {
    route: "chat",
    label: "New chat",
    icon: "plus",
    shortcut: "⌘N",
    title: "Start something new. Anything running carries on",
  },
  { route: "agents", label: "Agents", icon: "agents" },
  { route: "integrations", label: "Plugins", icon: "plug" },
  { route: "automations", label: "Routines", icon: "flow" },
];

// The user menu is intentionally small. The app's task surfaces stay in the
// primary rail; account actions are the only things that belong behind the
// identity control.
const accountMenuItems: Array<{
  action: "spend" | "invite" | "settings" | "logout";
  label: string;
  icon: keyof typeof ICON_PATHS;
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
  icon: keyof typeof ICON_PATHS;
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

interface ConversationSearchState {
  query: string;
  status: "idle" | "loading" | "ready" | "unavailable";
  results: ConversationSearchResult[];
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
  const [conversationQuery, setConversationQuery] = useState("");
  const [searchAttempt, setSearchAttempt] = useState(0);
  const [searchState, setSearchState] = useState<ConversationSearchState>({
    query: "",
    status: "idle",
    results: [],
  });
  const [conversationAction, setConversationAction] = useState<string | null>(null);
  const [conversationActionError, setConversationActionError] = useState("");
  const [pinnedConversationIds, setPinnedConversationIds] = useState<string[]>(readPinnedConversationIds);
  const [accountOpen, setAccountOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [relativeNow, setRelativeNow] = useState(() => Date.now());
  const accountMenuRef = useRef<HTMLDivElement>(null);
  const helpMenuRef = useRef<HTMLDivElement>(null);
  const accountTriggerRef = useRef<HTMLButtonElement>(null);
  const helpTriggerRef = useRef<HTMLButtonElement>(null);
  const routeMenuOriginRef = useRef<"account" | "help" | null>(null);

  useEffect(() => {
    const timer = window.setInterval(() => setRelativeNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, []);

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
    const query = route === "chat" ? conversationQuery.trim() : "";
    if (!query) {
      setSearchState({ query: "", status: "idle", results: [] });
      return;
    }
    let active = true;
    setSearchState((current) => ({
      query,
      status: "loading",
      results: current.query === query ? current.results : [],
    }));
    const timer = window.setTimeout(() => {
      void client.searchConversations(query, 50)
        .then((result) => {
          if (active) {
            setSearchState({ query, status: "ready", results: result.results });
          }
        })
        .catch(() => {
          if (active) {
            setSearchState((current) => ({
              query,
              status: "unavailable",
              results: current.query === query ? current.results : [],
            }));
          }
        });
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [conversationQuery, route, searchAttempt]);

  useEffect(() => {
    if (route !== "chat" && conversationQuery) setConversationQuery("");
  }, [conversationQuery, route]);

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

  const query = route === "chat" ? conversationQuery.trim() : "";
  const activeSearch = searchState.query === query
    ? searchState
    : { query, status: "loading" as const, results: [] };
  const visibleConversations = query ? activeSearch.results : conversations;
  // Closed tasks live in Settings > Archived chats. Recents is shared by the
  // primary shell routes, so filter it at the list boundary instead of letting
  // a multi-line restore card leak back in whenever Chat is not selected.
  const recentConversations = visibleConversations.filter(
    (conversation) => conversation.status !== "closed",
  );
  const onlyClosedConversations = visibleConversations.length > 0
    && recentConversations.length === 0;
  const orderedConversations = [...recentConversations].sort((left, right) => (
    Number(pinnedConversationIds.includes(right.id))
    - Number(pinnedConversationIds.includes(left.id))
  ));

  function togglePinnedConversation(id: string) {
    setPinnedConversationIds((current) => {
      const next = current.includes(id)
        ? current.filter((conversationId) => conversationId !== id)
        : [...current, id];
      persistPinnedConversationIds(next);
      return next;
    });
  }

  async function archiveConversation(id: string) {
    setConversationAction(id);
    setConversationActionError("");
    try {
      const result = await client.deleteMyConversation(id);
      if (result.status !== "ok") {
        setConversationActionError(result.reason ?? "The conversation could not be archived.");
        return;
      }
      setSearchState((current) => ({
        ...current,
        results: current.results.filter((conversation) => conversation.id !== id),
      }));
      onConversationArchived?.(id);
    } catch {
      setConversationActionError("The conversation could not be archived. It is safe to retry.");
    } finally {
      setConversationAction(null);
    }
  }

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
  const workspaceLabel = identity
    ? `${identity.organisation} · ${identity.workspace}`
    : (identityStatus === "unavailable" ? "Workspace unavailable" : "Loading workspace…");

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
            <span className="side-menu-name">
              {identity
                ? identity.user
                : (identityStatus === "unavailable" ? "Identity unavailable" : "Loading identity…")}
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
              <span className="nav-icon"><Icon name={item.icon} size={15} /></span>
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
              <span className="nav-icon"><Icon name={item.icon} size={15} /></span>
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
            ? `Signed in as ${identity.user}${identity.role ? `, role ${identity.role}` : ""}, ${identity.organisation}, ${identity.workspace}. Account menu`
            : `Account menu, identity ${identityStatus}`}
          className="side-account"
          onClick={() => {
            setAccountOpen((current) => !current);
            setHelpOpen(false);
          }}
          title={identity
            ? `${identity.user} · ${identity.role ?? "member"} · ${identity.organisation} / ${identity.workspace}`
            : undefined}
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
          <Icon name="question" size={12} strokeWidth={2.1} />
        </button>
      </div>
    );
  }

  // In settings the sidebar becomes the self-contained settings rail drawn by
  // the decided target: back, search, the ten sections, and its quiet help
  // copy. Account and global-help controls remain one click away via Back to
  // app; repeating them here adds a second footer the signed frame does not
  // contain.
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
                <span className="nav-icon"><Icon name={settingsIcon(entry.id)} size={15} /></span>
                <span>{entry.label}</span>
              </button>
            </div>
          ))}
        </nav>
        <p className="settings-side-foot">
          Every setting is one search away. Nothing is hidden, only quiet.
        </p>
      </aside>
    );
  }

  return (
    <aside
      className={route === "chat" ? "sidebar shell-parity" : "sidebar"}
      aria-label="Worker navigation"
    >
      <div className="side-top">
        <span className="side-brand">boltrig</span>
        {onCommandPalette && (
          <button
            aria-label="Open command palette"
            className="side-icon-button"
            onClick={onCommandPalette}
            title="Search everything (Ctrl or Command K)"
            type="button"
          >
            <svg aria-hidden fill="none" height="16" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" viewBox="0 0 24 24" width="16">
              <circle cx="11" cy="11" r="7" />
              <line x1="16.5" x2="21" y1="16.5" y2="21" />
            </svg>
          </button>
        )}
      </div>

      <button
        className="side-workspace"
        onClick={() => {
          onRoute("organisation");
        }}
        title="Open organisation and workspace administration"
        type="button"
      >
        <span>{workspaceLabel}</span>
        <svg aria-hidden fill="none" height="12" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.2" viewBox="0 0 24 24" width="12">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      <nav className="side-nav">
        {primary.map((item) => (
          <button
            aria-label={item.label}
            className={route === item.route ? "nav-row active" : "nav-row"}
            key={item.route}
            onClick={() => onRoute(item.route)}
            title={item.title}
            type="button"
          >
            <span className="nav-icon"><Icon name={item.icon} /></span>
            <span>{item.label}</span>
            {item.shortcut && <span className="nav-key">{item.shortcut}</span>}
          </button>
        ))}
      </nav>

      <p className="side-recents-label">Recents</p>
      <div className="sessions">
        {route === "chat" && (
          <input
            className="conversation-search"
            aria-label="Search conversations"
            placeholder="Search conversations…"
            value={conversationQuery}
            onChange={(event) => setConversationQuery(event.target.value)}
          />
        )}
        {!query && conversationStatus === "loading" && (
          <p className="muted small" role="status">
            {conversations.length > 0 ? "Refreshing conversations…" : "Loading conversations…"}
          </p>
        )}
        {!query && conversationStatus === "unavailable" && (
          <div className="session-error" role="alert">
            <p>
              {conversations.length > 0
                ? "Conversation refresh is unavailable. Previously loaded conversations may be stale."
                : "Conversations are unavailable."}
            </p>
            {onRetryConversations && (
              <button
                className="secondary-button"
                onClick={onRetryConversations}
                type="button"
              >
                Retry conversations
              </button>
            )}
          </div>
        )}
        {query && activeSearch.status === "loading" && (
          <p className="muted small" role="status">
            {activeSearch.results.length > 0 ? "Refreshing conversation search…" : "Searching…"}
          </p>
        )}
        {query && activeSearch.status === "unavailable" && (
          <div className="session-error" role="alert">
            <p>
              {activeSearch.results.length > 0
                ? "Conversation search is unavailable. Previous results may be stale."
                : "Conversation search is unavailable."}
            </p>
            <button
              className="secondary-button"
              onClick={() => setSearchAttempt((current) => current + 1)}
              type="button"
            >
              Retry search
            </button>
          </div>
        )}
        {!query
          && conversationStatus === "ready"
          && recentConversations.length === 0 && (
          <p className="muted small">
            {onlyClosedConversations ? "No recent conversations" : "No conversations yet"}
          </p>
        )}
        {query
          && activeSearch.status === "ready"
          && recentConversations.length === 0 && (
          <p className="muted small">
            {onlyClosedConversations ? "No matching recent conversations" : "No matching conversations"}
          </p>
        )}
        {orderedConversations.map((conversation) => (
          <div
            className={`session-row${selectedConversation === conversation.id ? " active" : ""}${pinnedConversationIds.includes(conversation.id) ? " pinned" : ""}`}
            key={conversation.id}
          >
            <button
              aria-current={selectedConversation === conversation.id ? "page" : undefined}
              className="session-main"
              onClick={() => onConversation(conversation.id)}
              type="button"
            >
              <span className="session-title">
                <span>{conversation.title || "Untitled task"}</span>
                {workingConversationIds.includes(conversation.id) && (
                  <span
                    aria-label="Working on this chat"
                    className="session-working-indicator"
                    role="status"
                    title="Working on this chat"
                  />
                )}
              </span>
              <time className="shell-recent-meta" dateTime={conversation.updated_at}>
                {relativeTime(conversation.updated_at, relativeNow)}
              </time>
              {typeof (conversation as ConversationSearchResult).snippet === "string"
                && <small className="shell-recent-meta">{(conversation as ConversationSearchResult).snippet}</small>}
            </button>
            <div className="session-actions" aria-label={`Actions for ${conversation.title || "Untitled task"}`}>
              <button
                aria-label={pinnedConversationIds.includes(conversation.id)
                  ? `Unpin ${conversation.title || "conversation"}`
                  : `Pin ${conversation.title || "conversation"}`}
                className="session-action session-pin-action"
                onClick={(event) => {
                  event.stopPropagation();
                  togglePinnedConversation(conversation.id);
                }}
                title={pinnedConversationIds.includes(conversation.id) ? "Unpin conversation" : "Pin conversation"}
                type="button"
              >
                <Icon name="pin" size={13} />
              </button>
              <button
                aria-label={`Archive ${conversation.title || "conversation"}`}
                className="session-action"
                disabled={conversationAction === conversation.id}
                onClick={(event) => {
                  event.stopPropagation();
                  void archiveConversation(conversation.id);
                }}
                title="Archive conversation"
                type="button"
              >
                <Icon name="archive" size={13} />
              </button>
            </div>
          </div>
        ))}
        {conversationActionError && <p className="session-error" role="alert">{conversationActionError}</p>}
        {!query && conversationStatus === "ready" && hasMoreConversations && (
          <button className="secondary-button" onClick={onLoadMore} type="button">
            Load more conversations
          </button>
        )}
      </div>

      {renderAccountMenu()}
      {renderHelpMenu()}
      {renderSidebarFooter()}
    </aside>
  );
}

const settingsIcons: Record<SettingsSection, keyof typeof ICON_PATHS> = {
  you: "user",
  autonomy: "shield",
  spend: "gauge",
  shortcuts: "keyboard",
  knowledge: "book",
  overnight: "moon",
  health: "pulse",
  operations: "pulse",
  organisation: "org",
  advanced: "code",
  archived: "archive",
};

const PINNED_CONVERSATIONS_KEY = "boltrig-worker-pinned-conversations";

function readPinnedConversationIds(): string[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(PINNED_CONVERSATIONS_KEY) ?? "[]");
    return Array.isArray(value)
      ? value.filter((id): id is string => typeof id === "string" && id.length > 0)
      : [];
  } catch {
    return [];
  }
}

function persistPinnedConversationIds(ids: string[]): void {
  try {
    localStorage.setItem(PINNED_CONVERSATIONS_KEY, JSON.stringify(ids));
  } catch {
    // Pinning is a presentation preference; the action still applies for the
    // current render when storage is unavailable.
  }
}

function settingsIcon(section: SettingsSection): keyof typeof ICON_PATHS {
  return settingsIcons[section];
}

function relativeTime(value: string, now = Date.now()): string {
  const time = Date.parse(value);
  if (!Number.isFinite(time)) return "";
  const minutes = Math.max(0, Math.round((now - time) / 60_000));
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
}

export function Topbar({ title, status }: { title: string; status?: string }) {
  const { identity, identityStatus } = useWorkerGlobalContext();
  const identityTitle = identity
    ? [
      `Signed in as ${identity.user}${identity.role ? ` (${identity.role})` : ""}`,
      `${identity.organisation} / ${identity.workspace}`,
    ].join(" · ")
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
          {identity && <small className="identity-context">{identity.organisation} / {identity.workspace}</small>}
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
