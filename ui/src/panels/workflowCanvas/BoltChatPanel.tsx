// Floating Bolt chat panel (design brief sec 22.9). A 300x360 bottom-right
// window toggled by a cyan chat-bubble button. Collapses to a 36px cyan circle.
// Pure UI for now: sending echoes the text into the body.

import { useState } from "react";

const SUGGESTIONS = ["Add a retry loop", "Explain this branch", "Connect to Bolt"];

interface BoltChatPanelProps {
  open: boolean;
  onToggle: () => void;
}

interface Msg {
  from: "bot" | "me";
  text: string;
}

export function BoltChatPanel({ open, onToggle }: BoltChatPanelProps) {
  const [messages, setMessages] = useState<Msg[]>([
    { from: "bot", text: "Describe a change and I will wire it up." },
  ]);
  const [draft, setDraft] = useState("");

  const send = () => {
    const text = draft.trim();
    if (!text) return;
    setMessages((m) => [...m, { from: "me", text }]);
    setDraft("");
    window.setTimeout(() => {
      setMessages((m) => [...m, { from: "bot", text: `Got it: ${text}` }]);
    }, 120);
  };

  if (!open) {
    return (
      <button
        type="button"
        className="wf3-bolt-fab"
        onClick={onToggle}
        title="Ask Bolt"
        aria-label="Open Bolt chat"
      >
        <ChatBubble />
      </button>
    );
  }

  return (
    <div className="wf3-bolt" role="dialog" aria-label="Bolt chat">
      <header className="wf3-bolt__head">
        <span className="wf3-bolt__avatar">B</span>
        <div className="wf3-bolt__titles">
          <div className="wf3-bolt__name">Bolt</div>
          <div className="wf3-bolt__sub muted">Chief of Staff</div>
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
        {messages.map((m, i) => (
          <div key={i} className={`wf3-bolt__msg wf3-bolt__msg--${m.from}`}>
            {m.text}
          </div>
        ))}
        <div className="wf3-bolt__chips">
          {SUGGESTIONS.map((s) => (
            <button
              type="button"
              key={s}
              className="wf3-bolt__chip"
              onClick={() => setDraft(s)}
            >
              {s}
            </button>
          ))}
        </div>
      </div>
      <footer className="wf3-bolt__foot">
        <input
          className="wf3-bolt__input"
          placeholder="Describe changes..."
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") send();
          }}
        />
        <button type="button" className="wf3-bolt__send" onClick={send} aria-label="Send">
          <SendGlyph />
        </button>
      </footer>
    </div>
  );
}

function ChatBubble() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path
        d="M4 5h16v11H9l-5 4V5Z"
        fill="#04060D"
      />
    </svg>
  );
}

function SendGlyph() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M3 11.5 21 3l-8.5 18-2.5-7-7-2.5Z" fill="#04060D" />
    </svg>
  );
}
