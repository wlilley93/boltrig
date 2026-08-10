import { useEffect, useState } from "react";
import type { ConversationSummary, HITLRequest } from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import { FamiliarBadge } from "./familiar/FamiliarBadge";

// Today: the mobile home. What needs you, what is working, what happened
// earlier, and one way in at the bottom. Same scoped iOS palette as the
// conversation surface (.mobile-surface), so the two read as one app.

function age(value?: string | null): string {
  if (!value) return "";
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return "now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
}

export function MobileToday({
  workspace,
  initials,
  onOpenConversation,
  onNewChat,
  onSettings,
}: {
  workspace: string;
  initials: string;
  onOpenConversation(id: string): void;
  onNewChat(): void;
  onSettings(): void;
}) {
  const [pending, setPending] = useState<HITLRequest[]>([]);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [busy, setBusy] = useState("");

  useEffect(() => {
    document.documentElement.dataset.mobileSurface = "today";
    return () => { delete document.documentElement.dataset.mobileSurface; };
  }, []);

  async function load() {
    const [hitl, convo] = await Promise.all([
      client.hitl().catch(() => null),
      client.conversations().catch(() => null),
    ]);
    setPending(hitl?.requests ?? []);
    setConversations((convo?.conversations ?? []).filter((row) => row.status !== "closed"));
  }
  useEffect(() => { void load(); }, []);

  async function settle(request: HITLRequest, decision: "approve" | "decline") {
    setBusy(request.id);
    try {
      await client.respondHitl(request.id, decision);
      await load();
    } catch {
      // A refusal is the kernel's to report; the row simply stays.
    } finally {
      setBusy("");
    }
  }

  // "Working now" is the conversation that has moved most recently; everything
  // else is Earlier. Without a per-conversation run state on the summary this
  // is the honest split, rather than inventing a running flag.
  const [working, ...earlier] = conversations;

  return (
    <div className="mobile-surface">
      <header className="m-today-head">
        <div>
          <span className="m-today-workspace">{workspace}</span>
          <span className="m-today-title">Today</span>
        </div>
        <button aria-label="Settings" className="m-avatar-button" onClick={onSettings} type="button">
          <span className="m-avatar">{initials}</span>
        </button>
      </header>

      <div className="m-body">
        {pending.length > 0 && (
          <section className="m-group">
            <span className="m-group-label">Needs you</span>
            <div className="m-card">
              {pending.map((request) => (
                <div key={request.id}>
                  <div className="m-needs-head">
                    <div className="m-needs-title">
                      <span className="m-dot" data-tone="waiting" />
                      <span>{request.verb ?? "A decision"}</span>
                    </div>
                    <span className="m-needs-sub">{request.question}</span>
                  </div>
                  <div className="m-needs-actions">
                    <button
                      className="m-approve"
                      disabled={busy === request.id}
                      onClick={() => void settle(request, "approve")}
                      type="button"
                    >Approve</button>
                    <button
                      className="m-decline"
                      disabled={busy === request.id}
                      onClick={() => void settle(request, "decline")}
                      type="button"
                    >Not now</button>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {working && (
          <section className="m-group">
            <span className="m-group-label">Working now</span>
            <div className="m-card">
              <button className="m-row" onClick={() => onOpenConversation(working.id)} type="button">
                <FamiliarBadge state="working" label={working.title || "Untitled task"} />
                <span className="m-row-main">
                  <span className="m-row-title">{working.title || "Untitled task"}</span>
                  <span className="m-row-sub">{working.status}</span>
                </span>
                <svg className="m-chev" fill="none" height="16" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.4" viewBox="0 0 24 24" width="16">
                  <polyline points="9 6 15 12 9 18" />
                </svg>
              </button>
            </div>
          </section>
        )}

        {earlier.length > 0 && (
          <section className="m-group">
            <span className="m-group-label">Earlier</span>
            <div className="m-card">
              {earlier.slice(0, 12).map((row) => (
                <button className="m-row" key={row.id} onClick={() => onOpenConversation(row.id)} type="button">
                  <FamiliarBadge state="ready" label={row.title || "Untitled task"} />
                  <span className="m-row-main">
                    <span className="m-row-title" data-quiet="true">{row.title || "Untitled task"}</span>
                    <span className="m-row-sub">{row.status}</span>
                  </span>
                  <span className="m-row-age">{age(row.updated_at)}</span>
                </button>
              ))}
            </div>
          </section>
        )}

        {pending.length === 0 && conversations.length === 0 && (
          <p className="m-empty">Nothing is waiting and nothing is running. Ask for something below.</p>
        )}
      </div>

      <div className="m-today-foot">
        <button className="m-ask" onClick={onNewChat} type="button">
          <span>Ask boltrig to do something</span>
          <span className="m-ask-mic" aria-hidden>
            <svg fill="none" height="19" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" viewBox="0 0 24 24" width="19">
              <rect height="11" rx="3" width="6" x="9" y="3" />
              <path d="M5 11a7 7 0 0 0 14 0" />
              <line x1="12" x2="12" y1="18" y2="21" />
            </svg>
          </span>
        </button>
      </div>
    </div>
  );
}
