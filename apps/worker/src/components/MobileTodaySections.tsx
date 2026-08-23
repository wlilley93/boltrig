import type { ConversationSummary, HITLRequest } from "@wlilley93/boltrig-web-sdk";

import { FamiliarBadge } from "./familiar/FamiliarBadge";

// The groups Today is made of. Each one draws from what it is handed and
// reports nothing of its own; MobileToday owns the loading and the decisions.

export function age(value?: string | null): string {
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

export function TodayHeader({ workspace, initials, onSettings }: { workspace: string; initials: string; onSettings(): void }) {
  return (
    <header className="m-today-head">
      <div>
        <span className="m-today-workspace">{workspace}</span>
        <span className="m-today-title">Today</span>
      </div>
      <button aria-label="Settings" className="m-avatar-button" onClick={onSettings} type="button">
        <span className="m-avatar">{initials}</span>
      </button>
    </header>
  );
}

export function AskBar({ onNewChat }: { onNewChat(): void }) {
  return (
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
  );
}

export function LoadFailedNotice({ onRetry }: { onRetry(): void }) {
  return (
    <section className="m-group">
      <div className="m-card m-load-failed">
        <p className="m-empty">Today could not be loaded.</p>
        <button className="m-approve" onClick={onRetry} type="button">Try again</button>
      </div>
    </section>
  );
}

export function NeedsYouSection({
  pending,
  busy,
  onSettle,
}: {
  pending: HITLRequest[];
  busy: string;
  onSettle(request: HITLRequest, decision: "approve" | "decline"): void;
}) {
  if (pending.length === 0) return null;
  return (
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
              <button className="m-approve" disabled={busy === request.id} onClick={() => onSettle(request, "approve")} type="button">Approve</button>
              <button className="m-decline" disabled={busy === request.id} onClick={() => onSettle(request, "decline")} type="button">Not now</button>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function Chevron() {
  return (
    <svg className="m-chev" fill="none" height="16" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.4" viewBox="0 0 24 24" width="16">
      <polyline points="9 6 15 12 9 18" />
    </svg>
  );
}

export function WorkingNowSection({ working, onOpen }: { working?: ConversationSummary; onOpen(id: string): void }) {
  if (!working) return null;
  const title = working.title || "Untitled task";
  return (
    <section className="m-group">
      <span className="m-group-label">Working now</span>
      <div className="m-card">
        <button className="m-row" onClick={() => onOpen(working.id)} type="button">
          <FamiliarBadge state="working" label={title} />
          <span className="m-row-main">
            <span className="m-row-title">{title}</span>
            <span className="m-row-sub">{working.status}</span>
          </span>
          <Chevron />
        </button>
      </div>
    </section>
  );
}

export function EarlierSection({ earlier, onOpen }: { earlier: ConversationSummary[]; onOpen(id: string): void }) {
  if (earlier.length === 0) return null;
  return (
    <section className="m-group">
      <span className="m-group-label">Earlier</span>
      <div className="m-card">
        {earlier.map((row) => (
          <button className="m-row" key={row.id} onClick={() => onOpen(row.id)} type="button">
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
  );
}
