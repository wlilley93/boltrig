import { useState } from "react";

import { setComposerPrefill } from "@/composerPrefill";
import { navigate } from "@/router";
import type { WorkflowStep } from "./types";

const SUGGESTIONS = ["Add a retry path", "Explain this branch", "Add a human approval"];

interface BoltChatPanelProps {
  open: boolean;
  onToggle: () => void;
  workflowId: string;
  steps: WorkflowStep[];
}

function handoffPrompt(workflowId: string, steps: WorkflowStep[], request: string): string {
  return [
    `Help me review a proposed change to workflow "${workflowId || "untitled"}".`,
    "The canvas has not been changed. Return a concrete proposed step diff for me to review and apply manually.",
    `Requested change: ${request}`,
    "Current steps:",
    JSON.stringify(steps, null, 2),
  ].join("\n\n");
}

export function BoltChatPanel({ open, onToggle, workflowId, steps }: BoltChatPanelProps) {
  const [draft, setDraft] = useState("");

  const continueInChat = () => {
    const request = draft.trim();
    if (!request) return;
    setComposerPrefill(handoffPrompt(workflowId, steps, request));
    navigate("/chat");
  };

  if (!open) {
    return (
      <button
        type="button"
        className="wf3-bolt-fab"
        onClick={onToggle}
        title="Plan a workflow change in Chat"
        aria-label="Open workflow chat handoff"
      >
        <ChatBubble />
      </button>
    );
  }

  return (
    <div className="wf3-bolt" role="dialog" aria-label="Workflow chat handoff">
      <header className="wf3-bolt__head">
        <span className="wf3-bolt__avatar">B</span>
        <div className="wf3-bolt__titles">
          <div className="wf3-bolt__name">Plan in Chat</div>
          <div className="wf3-bolt__sub muted">Reviewable handoff</div>
        </div>
        <button type="button" className="wf3-bolt__min" onClick={onToggle} aria-label="Minimize" title="Minimize">-</button>
      </header>
      <div className="wf3-bolt__body">
        <div className="wf3-bolt__msg wf3-bolt__msg--bot">
          Describe the change. I will move the current steps into Chat as a draft request; nothing is published or changed automatically.
        </div>
        <div className="wf3-bolt__chips">
          {SUGGESTIONS.map((suggestion) => (
            <button type="button" key={suggestion} className="wf3-bolt__chip" onClick={() => setDraft(suggestion)}>
              {suggestion}
            </button>
          ))}
        </div>
      </div>
      <footer className="wf3-bolt__foot">
        <input
          className="wf3-bolt__input"
          aria-label="Proposed workflow change"
          placeholder="Describe a reviewable change..."
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") continueInChat();
          }}
        />
        <button type="button" className="wf3-bolt__send" onClick={continueInChat} disabled={!draft.trim()} aria-label="Continue in Chat">
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
