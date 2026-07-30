import { useEffect, useState } from "react";
import type {
  ConversationSearchResult,
  ConversationSummary,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import { navigate, type WorkerRoute } from "../routes";
import { useWorkerGlobalContext } from "./WorkerGlobalContext";

const primary: Array<{ route: WorkerRoute; label: string; icon: string }> = [
  { route: "home", label: "Home", icon: "⌂" },
  { route: "chat", label: "New task", icon: "✦" },
  { route: "inbox", label: "Inbox", icon: "◫" },
  { route: "automations", label: "Automations", icon: "↻" },
  { route: "channels", label: "Channels", icon: "⌁" },
  { route: "integrations", label: "Integrations", icon: "⌁" },
];

const library: Array<{ route: WorkerRoute; label: string }> = [
  { route: "runs", label: "Runs" },
  { route: "work", label: "Work" },
  { route: "agents", label: "Agents" },
  { route: "knowledge", label: "Knowledge" },
  { route: "memory", label: "Memory" },
];

const control: Array<{ route: WorkerRoute; label: string }> = [
  { route: "build", label: "Build" },
  { route: "evaluations", label: "Evaluations" },
  { route: "operate", label: "Operate" },
  { route: "account", label: "Account" },
  { route: "organisation", label: "Organisation" },
  { route: "settings", label: "Settings" },
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

  return (
    <aside className="sidebar" aria-label="Worker navigation">
      <div className="brand">
        <span className="bolt-mark" aria-hidden>ϟ</span>
        <span>Boltrig</span>
        <span className="worker-label">Worker</span>
      </div>
      <nav className="primary-nav">
        {primary.map((item) => (
          <button
            className={route === item.route ? "nav-row active" : "nav-row"}
            key={item.route}
            onClick={() => onRoute(item.route)}
          >
            <span aria-hidden>{item.icon}</span>
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
      <div className="nav-section">
        <p className="eyebrow">Workspace</p>
        {library.map((item) => (
          <button
            className={route === item.route ? "nav-row active" : "nav-row"}
            key={item.route}
            onClick={() => onRoute(item.route)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div className="sessions">
        <p className="eyebrow">Recent</p>
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
          <button className="secondary-button" onClick={onLoadMore}>
            Load more conversations
          </button>
        )}
      </div>
      <div className="nav-section control-nav">
        <p className="eyebrow">Control</p>
        {control.map((item) => (
          <button
            className={route === item.route ? "nav-row active" : "nav-row"}
            key={item.route}
            onClick={() => onRoute(item.route)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div className="sidebar-footer">
        <span
          aria-label={identity
            ? `Signed in as ${identity.user}${identity.role ? `, role ${identity.role}` : ""}, ${identity.organisation}, ${identity.workspace}`
            : `Worker identity ${identityStatus}`}
          className={`sidebar-identity ${identityStatus}`}
          title={identity
            ? `${identity.user} · ${identity.role ?? "member"} · ${identity.organisation} / ${identity.workspace}`
            : undefined}
        >
          {identity
            ? `${identity.user}${identity.role ? ` (${identity.role})` : ""} · ${identity.organisation} / ${identity.workspace}`
            : (identityStatus === "unavailable" ? "Identity unavailable" : "Loading identity…")}
        </span>
        <div className="sidebar-footer-actions">
          <a href="/operator/" className="operator-link">Open Operator</a>
          {onCommandPalette && (
            <button
              aria-label="Open command palette"
              className="command-trigger"
              onClick={onCommandPalette}
              title="Command palette (Ctrl or Command K)"
              type="button"
            >
              ⌘K
            </button>
          )}
          <button className="icon-button" onClick={() => onRoute("settings")} aria-label="Settings">⚙</button>
        </div>
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
        <p className="eyebrow">Boltrig Worker</p>
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
