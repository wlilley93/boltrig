// The Studio's docked right side panel chat - the ONLY authoring channel for
// workflows (design pivot: describe flows in words; the canvas is a read-only
// projection you inspect, not a node editor). Replaces the old handoff stub
// that prefilled the main chat composer and navigated away: the conversation
// now lives here, next to the canvas it is changing.
//
// Approval holds surface inline as cards; deciding them stays on the
// Approvals surface (one respond path, one eligibility check) - the card
// deep-links there and the thread reports the hold honestly.

import { useState } from "react";
import { api } from "@/api/client";
import { navigate } from "@/router";
import type { WorkflowStep } from "./types";
import { useStudioChat, type StudioChatMessage, type StudioHitl } from "./useStudioChat";

const SUGGESTIONS = [
  "Add a retry path",
  "Explain this branch",
  "Add a human approval step",
];

interface BoltChatPanelProps {
  open: boolean;
  onToggle: () => void;
  workflowId: string;
  steps: WorkflowStep[];
  chat: ReturnType<typeof useStudioChat>;
}

// One approval hold, decidable inline. The decision goes through the SAME
// respond path as the Approvals surface (POST /v1/hitl/{id}/respond), so
// eligibility (four-eyes, assignee, verb binding) is enforced server-side
// identically; an ineligible click renders the denial, never a workaround.
function HitlCard({ hitl }: { hitl: StudioHitl }) {
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<string | null>(null);

  const decide = async (decision: "approve" | "reject") => {
    setBusy(true);
    try {
      await api.respondHitl(hitl.requestId, { decision });
      setOutcome(decision === "approve" ? "Approved - resuming." : "Rejected.");
    } catch (err) {
      setOutcome(err instanceof Error ? err.message : "Could not record the decision.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="wf3-bolt__hitl">
      <div className="wf3-bolt__hitl-q">{hitl.question}</div>
      {outcome ? (
        <div className="wf3-bolt__hitl-outcome muted">{outcome}</div>
      ) : (
        <div className="wf3-bolt__hitl-actions">
          <button
            type="button"
            className="btn btn--primary wf3-bolt__hitl-btn"
            disabled={busy}
            onClick={() => void decide("approve")}
          >
            Approve
          </button>
          <button
            type="button"
            className="btn wf3-bolt__hitl-btn"
            disabled={busy}
            onClick={() => void decide("reject")}
          >
            Reject
          </button>
          <button
            type="button"
            className="btn btn--ghost wf3-bolt__hitl-btn"
            onClick={() => navigate("/approvals")}
            title="Full request detail on the Approvals surface"
          >
            Detail
          </button>
        </div>
      )}
    </div>
  );
}

function Message({ msg }: { msg: StudioChatMessage }) {
  const cls =
    msg.role === "user" ? "wf3-bolt__msg wf3-bolt__msg--user" : "wf3-bolt__msg wf3-bolt__msg--bot";
  return (
    <div className={cls}>
      {msg.text || (msg.pending ? "…" : "")}
      {msg.activity.length > 0 && (
        <div className="wf3-bolt__activity code muted">
          {msg.activity.map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </div>
      )}
      {msg.hitls.map((h) => (
        <HitlCard key={h.requestId} hitl={h} />
      ))}
    </div>
  );
}

export function BoltChatPanel({ open, onToggle, workflowId, chat }: BoltChatPanelProps) {
  if (!open) {
    return (
      <button
        type="button"
        className="wf3-bolt-fab"
        onClick={onToggle}
        title="Open the workflow chat"
        aria-label="Open workflow chat"
      >
        <ChatBubble />
      </button>
    );
  }

  return (
    <div className="wf3-bolt wf3-bolt--docked" role="complementary" aria-label="Workflow chat">
      <header className="wf3-bolt__head">
        <span className="wf3-bolt__avatar">B</span>
        <div className="wf3-bolt__titles">
          <div className="wf3-bolt__name">Describe the flow</div>
          <div className="wf3-bolt__sub muted">
            {workflowId ? `editing ${workflowId}` : "chat-first authoring"}
          </div>
        </div>
        <button
          type="button"
          className="wf3-bolt__min"
          onClick={onToggle}
          aria-label="Minimize"
          title="Minimize"
        >
          -
        </button>
      </header>
      <div className="wf3-bolt__body">
        {chat.messages.length === 0 && (
          <>
            <div className="wf3-bolt__msg wf3-bolt__msg--bot">
              Describe the change in words - I draft it, you review the hold,
              nothing applies without your approval. Click a node to inspect it;
              use its &quot;Ask in chat&quot; to point at a step.
            </div>
            <div className="wf3-bolt__chips">
              {SUGGESTIONS.map((s) => (
                <button
                  type="button"
                  key={s}
                  className="wf3-bolt__chip"
                  onClick={() => chat.setDraft(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          </>
        )}
        {chat.messages.map((msg, i) => (
          <Message key={i} msg={msg} />
        ))}
        {chat.error && <div className="wf3-bolt__msg wf3-bolt__msg--bot error">{chat.error}</div>}
      </div>
      <footer className="wf3-bolt__foot">
        <input
          className="wf3-bolt__input"
          aria-label="Describe a workflow change"
          placeholder={chat.busy ? "Working…" : "Describe the flow…"}
          value={chat.draft}
          disabled={chat.busy}
          onChange={(e) => chat.setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void chat.send();
          }}
        />
        <button
          type="button"
          className="wf3-bolt__send"
          onClick={() => void chat.send()}
          disabled={chat.busy || !chat.draft.trim()}
          aria-label="Send"
        >
          <SendGlyph />
        </button>
      </footer>
    </div>
  );
}

function ChatBubble() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M4 5h16v11H9l-5 4V5Z" fill="currentColor" />
    </svg>
  );
}

function SendGlyph() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M3 11.5 21 3l-8.5 18-2.5-7-7-2.5Z" fill="currentColor" />
    </svg>
  );
}
