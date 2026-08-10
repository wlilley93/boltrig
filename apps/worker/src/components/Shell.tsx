import { useEffect, useState } from "react";
import type {
  ConversationSearchResult,
  ConversationSummary,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import { navigate, type WorkerRoute } from "../routes";
import { useWorkerGlobalContext } from "./WorkerGlobalContext";

// Stroke-path icons carried over from the Boltrig Console design component so
// the sidebar reads exactly like the design. Each entry is one or more SVG
// path `d` strings drawn at 24x24 with a 1.7 stroke.
const ICON_PATHS: Record<string, string[]> = {
  chat: ["M5 4.5h14a1.5 1.5 0 0 1 1.5 1.5v8a1.5 1.5 0 0 1-1.5 1.5H9l-4.5 4V6A1.5 1.5 0 0 1 5 4.5z"],
  agents: [
    "M12 3.4a2.6 2.6 0 1 1 0 5.2 2.6 2.6 0 0 1 0-5.2z",
    "M5 20.4a2.4 2.4 0 1 1 0-4.8 2.4 2.4 0 0 1 0 4.8zM19 20.4a2.4 2.4 0 1 1 0-4.8 2.4 2.4 0 0 1 0 4.8z",
    "M12 8.6v3.2M5 15.6c0-1.9 1.6-3.5 3.5-3.5h7c1.9 0 3.5 1.6 3.5 3.5",
  ],
  plug: ["M8 3v5M16 3v5", "M5.5 8h13v3a6.5 6.5 0 0 1-13 0z", "M12 17.5V21"],
  flow: ["M4.5 5.5h5v4h-5zM14.5 5.5h5v4h-5zM9.5 14.5h5v4h-5z", "M7 9.5v2.5h10V9.5M12 12v2.5"],
  inbox: ["M3.5 13.5l3-8h11l3 8v6h-17z", "M3.5 13.5h5l1.5 2.5h4l1.5-2.5h5"],
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
};

function Icon({ name, size = 16 }: { name: keyof typeof ICON_PATHS; size?: number }) {
  return (
    <svg
      aria-hidden
      fill="none"
      height={size}
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={1.7}
      viewBox="0 0 24 24"
      width={size}
    >
      {ICON_PATHS[name].map((d) => <path d={d} key={d} />)}
    </svg>
  );
}

// The console nav holds the task-first surfaces under their canonical Worker
// names (the browser acceptance contract in ui/e2e-worker/worker.spec.ts
// names them exactly), a quiet Workspace group keeps the record surfaces
// visible, and the remainder stays one press away inside the account menu.
const primary: Array<{ route: WorkerRoute; label: string; icon: keyof typeof ICON_PATHS }> = [
  { route: "chat", label: "Chat", icon: "chat" },
  { route: "inbox", label: "Inbox", icon: "inbox" },
  { route: "agents", label: "Agents", icon: "agents" },
  { route: "integrations", label: "Integrations", icon: "plug" },
  { route: "automations", label: "Automations", icon: "flow" },
];

const workspace: Array<{ route: WorkerRoute; label: string; icon: keyof typeof ICON_PATHS }> = [
  { route: "runs", label: "Runs", icon: "clock" },
  { route: "work", label: "Work", icon: "work" },
  { route: "knowledge", label: "Knowledge", icon: "book" },
  { route: "memory", label: "Memory", icon: "brain" },
];

const menuSurfaces: Array<{ route: WorkerRoute; label: string; icon: keyof typeof ICON_PATHS }> = [
  { route: "home", label: "Home", icon: "home" },
  { route: "build", label: "Build", icon: "registry" },
  { route: "evaluations", label: "Evaluations", icon: "skill" },
  { route: "channels", label: "Channels", icon: "monitor" },
  { route: "operate", label: "Operate", icon: "pulse" },
];

const menuControl: Array<{ route: WorkerRoute; label: string; icon: keyof typeof ICON_PATHS }> = [
  { route: "account", label: "Account", icon: "user" },
  { route: "organisation", label: "Organisation", icon: "org" },
  { route: "settings", label: "Settings", icon: "gear" },
];

interface SidebarProps {
  route: WorkerRoute;
  conversations: ConversationSummary[];
  conversationStatus?: "loading" | "ready" | "unavailable";
  selectedConversation: string | null;
  onRoute(route: WorkerRoute): void;
  onConversation(id: string): void;
  onConversationRestored(id: string): void;
  onLoadMore(): void;
  onRetryConversations?(): void;
  hasMoreConversations: boolean;
  onCommandPalette?(): void;
}

interface ConversationSearchState {
  query: string;
  status: "idle" | "loading" | "ready" | "unavailable";
  results: ConversationSearchResult[];
}

interface HealthState {
  status: "loading" | "ready" | "degraded" | "unavailable";
  failing: number;
}

export function Sidebar({
  route,
  conversations,
  conversationStatus = "ready",
  selectedConversation,
  onRoute,
  onConversation,
  onConversationRestored,
  onLoadMore,
  onRetryConversations,
  hasMoreConversations,
  onCommandPalette,
}: SidebarProps) {
  const {
    identity,
    identityStatus,
    pendingCount,
    pendingStatus,
  } = useWorkerGlobalContext();
  const [conversationQuery, setConversationQuery] = useState("");
  const [searchAttempt, setSearchAttempt] = useState(0);
  const [searchState, setSearchState] = useState<ConversationSearchState>({
    query: "",
    status: "idle",
    results: [],
  });
  const [restoring, setRestoring] = useState<string | null>(null);
  const [restoreError, setRestoreError] = useState("");
  const [accountOpen, setAccountOpen] = useState(false);
  const [health, setHealth] = useState<HealthState>({ status: "loading", failing: 0 });

  useEffect(() => {
    const query = conversationQuery.trim();
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
  }, [conversationQuery, searchAttempt]);

  // The status line at the foot of the rail reads the same /readyz projection
  // Operate renders in full; it never invents health it did not measure.
  useEffect(() => {
    if (typeof client.readiness !== "function") {
      setHealth({ status: "unavailable", failing: 0 });
      return;
    }
    let cancelled = false;
    const pull = () => {
      void client.readiness()
        .then((result) => {
          if (cancelled) return;
          const failing = Object.values(result.checks ?? {})
            .filter((check) => check.status !== "ok" && check.status !== "ready").length;
          setHealth(result.status === "ready"
            ? { status: "ready", failing: 0 }
            : { status: "degraded", failing });
        })
        .catch(() => {
          if (!cancelled) setHealth({ status: "unavailable", failing: 0 });
        });
    };
    pull();
    const timer = window.setInterval(pull, 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (!accountOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setAccountOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [accountOpen]);

  const query = conversationQuery.trim();
  const activeSearch = searchState.query === query
    ? searchState
    : { query, status: "loading" as const, results: [] };
  const visibleConversations = query ? activeSearch.results : conversations;

  async function restoreConversation(id: string) {
    setRestoring(id);
    setRestoreError("");
    try {
      const result = await client.restoreMyConversation(id);
      if (result.status !== "ok") {
        setRestoreError(result.reason ?? "The conversation could not be restored.");
        return;
      }
      setSearchState((current) => ({
        ...current,
        results: current.results.map((conversation) => (
          conversation.id === id ? { ...conversation, status: "active" } : conversation
        )),
      }));
      onConversationRestored(id);
    } catch {
      setRestoreError("The conversation could not be restored.");
    } finally {
      setRestoring(null);
    }
  }

  function chooseFromMenu(next: WorkerRoute) {
    setAccountOpen(false);
    onRoute(next);
  }

  const initials = (identity?.user ?? "?").slice(0, 1).toUpperCase();
  const workspaceLabel = identity
    ? `${identity.organisation} / ${identity.workspace}`
    : (identityStatus === "unavailable" ? "Workspace unavailable" : "Loading workspace…");
  const healthLabel = health.status === "loading"
    ? "Checking health…"
    : health.status === "ready"
      ? "Everything responding"
      : health.status === "degraded"
        ? (health.failing > 0
          ? `${health.failing} check${health.failing === 1 ? "" : "s"} not ready`
          : "Some checks not ready")
        : "Health unavailable";
  const healthTone = health.status === "ready"
    ? "green"
    : health.status === "degraded" ? "amber" : "unknown";

  return (
    <aside className="sidebar" aria-label="Worker navigation">
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
        onClick={() => onRoute("account")}
        title="Workspace switching lives in Account"
        type="button"
      >
        <span>{workspaceLabel}</span>
        <svg aria-hidden fill="none" height="12" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.2" viewBox="0 0 24 24" width="12">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      <button className="side-new-chat" onClick={() => onRoute("chat")} type="button">
        <svg aria-hidden fill="none" height="15" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" viewBox="0 0 24 24" width="15">
          <line x1="12" x2="12" y1="5" y2="19" />
          <line x1="5" x2="19" y1="12" y2="12" />
        </svg>
        <span>New chat</span>
        <kbd>⌘N</kbd>
      </button>

      <nav className="side-nav">
        {primary.map((item) => (
          <button
            className={route === item.route ? "nav-row active" : "nav-row"}
            key={item.route}
            onClick={() => onRoute(item.route)}
            type="button"
          >
            <span className="nav-icon"><Icon name={item.icon} /></span>
            <span>{item.label}</span>
            {item.route === "inbox"
              && pendingStatus === "ready"
              && pendingCount !== null
              && pendingCount > 0 && (
                <span
                  className="nav-badge"
                  aria-label={`${pendingCount} pending decisions`}
                >
                  {pendingCount}
                </span>
              )}
          </button>
        ))}
      </nav>

      <p className="side-recents-label">Workspace</p>
      <nav className="side-nav" aria-label="Workspace surfaces">
        {workspace.map((item) => (
          <button
            className={route === item.route ? "nav-row active" : "nav-row"}
            key={item.route}
            onClick={() => onRoute(item.route)}
            type="button"
          >
            <span className="nav-icon"><Icon name={item.icon} /></span>
            <span>{item.label}</span>
          </button>
        ))}
      </nav>

      <p className="side-recents-label">Recents</p>
      <div className="sessions">
        <input
          className="conversation-search"
          aria-label="Search conversations"
          placeholder="Search conversations…"
          value={conversationQuery}
          onChange={(event) => setConversationQuery(event.target.value)}
        />
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
          && visibleConversations.length === 0 && (
          <p className="muted small">No conversations yet</p>
        )}
        {query
          && activeSearch.status === "ready"
          && visibleConversations.length === 0 && (
          <p className="muted small">No matching conversations</p>
        )}
        {visibleConversations.map((conversation) => (
          conversation.status === "closed" ? (
            <div className="session-row closed" data-status="closed" key={conversation.id}>
              <span>{conversation.title || "Untitled task"}</span>
              <time>{relativeTime(conversation.updated_at)}</time>
              <small>Closed · retained during the recovery window</small>
              <button
                type="button"
                className="session-restore"
                disabled={restoring === conversation.id}
                onClick={() => void restoreConversation(conversation.id)}
              >
                {restoring === conversation.id ? "Restoring…" : "Restore"}
              </button>
            </div>
          ) : (
            <button
              className={
                selectedConversation === conversation.id
                  ? "session-row active"
                  : "session-row"
              }
              key={conversation.id}
              onClick={() => onConversation(conversation.id)}
              type="button"
            >
              <span>{conversation.title || "Untitled task"}</span>
              <time>{relativeTime(conversation.updated_at)}</time>
              {typeof (conversation as ConversationSearchResult).snippet === "string"
                && <small>{(conversation as ConversationSearchResult).snippet}</small>}
            </button>
          )
        ))}
        {restoreError && <p className="session-error" role="alert">{restoreError}</p>}
        {!query && conversationStatus === "ready" && hasMoreConversations && (
          <button className="secondary-button" onClick={onLoadMore} type="button">
            Load more conversations
          </button>
        )}
      </div>

      <button
        className="side-status"
        onClick={() => onRoute("operate")}
        title="Open Operate"
        type="button"
      >
        <span aria-hidden className={`side-status-dot ${healthTone}`} />
        <span>{healthLabel}</span>
      </button>

      <a className="side-status side-operator" href="/operator/">
        <span className="nav-icon"><Icon name="code" size={13} /></span>
        <span>Open Operator</span>
      </a>

      {accountOpen && (
        <>
          <button
            aria-label="Close account menu"
            className="side-menu-scrim"
            onClick={() => setAccountOpen(false)}
            type="button"
          />
          <div className="side-menu" role="presentation">
            <div className="side-menu-identity">
              <span aria-hidden className="side-avatar">{initials}</span>
              <span className="side-menu-name">
                {identity
                  ? `${identity.user}${identity.role ? ` (${identity.role})` : ""}`
                  : (identityStatus === "unavailable" ? "Identity unavailable" : "Loading identity…")}
              </span>
            </div>
            {menuSurfaces.map((item) => (
              <button
                className="side-menu-row"
                key={item.route}
                onClick={() => chooseFromMenu(item.route)}
                type="button"
              >
                <span className="nav-icon"><Icon name={item.icon} size={15} /></span>
                <span>{item.label}</span>
              </button>
            ))}
            <div className="side-menu-divider" aria-hidden />
            {menuControl.map((item) => (
              <button
                className="side-menu-row"
                key={item.route}
                onClick={() => chooseFromMenu(item.route)}
                type="button"
              >
                <span className="nav-icon"><Icon name={item.icon} size={15} /></span>
                <span>{item.label}</span>
              </button>
            ))}
          </div>
        </>
      )}

      <div className="sidebar-footer">
        <button
          aria-expanded={accountOpen}
          aria-label={identity
            ? `Signed in as ${identity.user}${identity.role ? `, role ${identity.role}` : ""}, ${identity.organisation}, ${identity.workspace}. Account menu`
            : `Account menu, identity ${identityStatus}`}
          className="side-account"
          onClick={() => setAccountOpen((current) => !current)}
          title={identity
            ? `${identity.user} · ${identity.role ?? "member"} · ${identity.organisation} / ${identity.workspace}`
            : undefined}
          type="button"
        >
          <span aria-hidden className="side-avatar">{initials}</span>
          <span className="side-account-name">
            {identity?.user
              ?? (identityStatus === "unavailable" ? "Identity unavailable" : "Loading identity…")}
          </span>
        </button>
        <button
          aria-label="Open settings"
          className="side-round-button"
          onClick={() => onRoute("settings")}
          type="button"
        >
          <Icon name="gear" size={13} />
        </button>
      </div>
    </aside>
  );
}

function relativeTime(value: string): string {
  const time = Date.parse(value);
  if (!Number.isFinite(time)) return "";
  const minutes = Math.max(0, Math.round((Date.now() - time) / 60_000));
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
}

export function Topbar({ title, status }: { title: string; status?: string }) {
  const {
    identity,
    identityStatus,
    pendingCount,
    pendingStatus,
  } = useWorkerGlobalContext();
  const hasPending = pendingStatus === "ready" && pendingCount !== null && pendingCount > 0;
  const pendingLabel = pendingStatus === "ready"
    ? (hasPending ? `${pendingCount} pending` : "Inbox clear")
    : (pendingStatus === "unavailable" ? "Inbox unavailable" : "Checking Inbox");
  const pendingAriaLabel = pendingStatus === "ready"
    ? `Open Inbox, ${pendingCount ?? 0} pending decisions`
    : `Open Inbox, status ${pendingStatus}`;
  const identityTitle = identity
    ? [
      `Signed in as ${identity.user}${identity.role ? ` (${identity.role})` : ""}`,
      `${identity.organisation} / ${identity.workspace}`,
    ].join(" · ")
    : undefined;

  return (
    <header className="topbar">
      <div>
        <h1>{title}</h1>
      </div>
      <div className="topbar-actions">
        {status && <span className="status-pill"><i />{status}</span>}
        <button
          type="button"
          className={`inbox-pill ${pendingStatus}${hasPending ? " has-pending" : ""}`}
          aria-label={pendingAriaLabel}
          onClick={() => navigate("inbox")}
        >
          <i aria-hidden />
          {pendingLabel}
        </button>
        <span
          className={`identity-chip ${identityStatus}`}
          title={identityTitle}
        >
          <strong>
            {identity?.user ?? (identityStatus === "unavailable" ? "Identity unavailable" : "You")}
          </strong>
          {identity && (
            <small>{identity.organisation} / {identity.workspace}</small>
          )}
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
