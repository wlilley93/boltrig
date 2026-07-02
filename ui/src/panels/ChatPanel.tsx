// US-CONV-01..04, US-CONV-07: the conversational chat surface. A left rail
// lists conversations (GET /v1/conversations); selecting one loads its
// transcript (GET /v1/conversations/{id}). Sending a message streams the
// response from POST /v1/chat (SSE) and renders text, dimmed reasoning, tool
// cards, sub-agent cards and inline HITL as the events arrive. The
// conversation_id is threaded into each send (omitted to start a new one; the
// first message_start returns the new id, which we capture).

import { useEffect, useMemo, useRef, useState } from "react";

import { api, streamChat } from "../api/client";
import type { ChatEvent, ChatMessage } from "../api/types";
import { openRun } from "../router";
import { useSlideActive } from "../deck/context";
import { useFetch } from "../useFetch";
import { TurnExtras, normalizeEvents } from "./chatTurn";
import { apiReason } from "./shared";
import { EmptyState, PageIntro } from "./ux";

// The turn normaliser and renderer (tool / sub-agent / inline-HITL cards) live
// in chatTurn.tsx so the Run drawer reuses the exact same rendering.

const EXAMPLE_PROMPTS: ReadonlyArray<string> = [
  "Create a ticket for a refund request",
  "Summarise today's escalations",
  "What can you do for me?",
];

// Faithful server reason (a denied chat shows the kernel's message, not a 403).
const errText = apiReason;

function whenText(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  const mins = Math.round((Date.now() - d.getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return d.toLocaleDateString();
}

function MessageBubble({
  message,
  resolvedHitls,
  onResolve,
}: {
  message: ChatMessage;
  resolvedHitls: Record<string, string>;
  onResolve: (id: string, status: string) => void;
}) {
  const turn = useMemo(() => normalizeEvents(message.events ?? []), [message.events]);
  const isAssistant = message.role === "assistant";
  return (
    <div className={`chat-msg chat-msg--${isAssistant ? "assistant" : message.role}`}>
      <div className="chat-msg__role">{message.role}</div>
      <div className="chat-msg__bubble">
        {isAssistant && (
          <TurnExtras
            turn={turn}
            resolvedHitls={resolvedHitls}
            onResolve={onResolve}
            onOpenRun={openRun}
          />
        )}
        {message.content && <div className="chat-msg__text">{message.content}</div>}
      </div>
    </div>
  );
}

// --- the panel --------------------------------------------------------------

export function ChatPanel() {
  // The kept-alive chat slide streams in the background; its live region goes
  // quiet ("off") while the slide is not active so it never talks over the
  // panel the user is actually on.
  const slideActive = useSlideActive();
  const convs = useFetch(() => api.conversations(), []);

  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [msgsLoading, setMsgsLoading] = useState(false);
  const [msgsError, setMsgsError] = useState<string | null>(null);

  const [input, setInput] = useState("");
  const [pendingUser, setPendingUser] = useState<string | null>(null);
  const [liveEvents, setLiveEvents] = useState<ChatEvent[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [resolvedHitls, setResolvedHitls] = useState<Record<string, string>>({});

  // The conversation_id is unknown until the first message_start of a new
  // conversation; we hold it in a ref so the stream callback can stash it
  // without churning React state mid-stream.
  const pendingConvId = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const alive = useRef(true); // false after unmount: guards setState past an await

  // Abort any in-flight stream and stop touching state when the panel unmounts.
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      abortRef.current?.abort();
    };
  }, []);

  const live = useMemo(() => normalizeEvents(liveEvents), [liveEvents]);

  function resolveHitl(id: string, status: string) {
    setResolvedHitls((prev) => ({ ...prev, [id]: status }));
  }

  async function loadConversation(id: string) {
    setMsgsLoading(true);
    setMsgsError(null);
    try {
      const res = await api.conversation(id);
      if (!alive.current) return;
      setMessages(res.messages);
    } catch (err) {
      if (alive.current) setMsgsError(errText(err));
    } finally {
      if (alive.current) setMsgsLoading(false);
    }
  }

  function selectConversation(id: string) {
    if (id === activeId) return;
    abortRef.current?.abort();
    setStreaming(false);
    setStreamError(null);
    setPendingUser(null);
    setLiveEvents([]);
    setActiveId(id);
    void loadConversation(id);
  }

  function newConversation() {
    abortRef.current?.abort();
    setStreaming(false);
    setStreamError(null);
    setPendingUser(null);
    setLiveEvents([]);
    setActiveId(null);
    setMessages([]);
  }

  async function send() {
    const text = input.trim();
    if (!text || streaming) return;

    setInput("");
    setStreamError(null);
    setPendingUser(text);
    setLiveEvents([]);
    setStreaming(true);
    pendingConvId.current = activeId;

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      await streamChat(
        activeId ? { conversation_id: activeId, message: text } : { message: text },
        (ev) => {
          if (ctrl.signal.aborted || !alive.current) return;
          if (ev.type === "message_start" && ev.conversation_id) {
            pendingConvId.current = ev.conversation_id;
          }
          setLiveEvents((prev) => [...prev, ev]);
        },
        ctrl.signal,
      );

      if (!alive.current) return;
      // Stream finished cleanly. The transcript persists kernel-side, so reload
      // it (and the conversation list) and drop the local live/optimistic state.
      setStreaming(false);
      const convId = pendingConvId.current;
      if (convId) {
        if (!activeId) setActiveId(convId);
        await loadConversation(convId);
        if (!alive.current) return;
        convs.reload();
      }
      setPendingUser(null);
      setLiveEvents([]);
    } catch (err) {
      if (!alive.current) return;
      setStreaming(false);
      if (ctrl.signal.aborted) return; // user switched/cancelled; not an error
      // US-CONV-07: keep the partial turn on screen and offer a reconnect.
      setStreamError(errText(err));
    } finally {
      if (abortRef.current === ctrl) abortRef.current = null;
    }
  }

  // US-CONV-07: the result persisted server-side; re-fetch the conversation to
  // show the completed messages after a dropped stream.
  async function reconnect() {
    const convId = activeId ?? pendingConvId.current;
    setStreamError(null);
    if (convId) {
      if (!activeId) setActiveId(convId);
      await loadConversation(convId);
      if (!alive.current) return;
      convs.reload();
    }
    setPendingUser(null);
    setLiveEvents([]);
  }

  function onComposerKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  }

  const conversations = convs.data?.conversations ?? [];
  const showLive = streaming || liveEvents.length > 0 || streamError !== null;
  const isEmpty =
    !msgsLoading &&
    !msgsError &&
    messages.length === 0 &&
    pendingUser === null &&
    !showLive;

  return (
    <section className="panel chat">
      <PageIntro
        title="Chat"
        lead="Talk to the orchestrator in plain language; it plans, calls tools, and asks for approval when an action needs a human."
        how="Everything it does shows here as a live transcript - its reasoning, each tool call, and any approval it needs."
        actions={
          <>
            <span className="muted">{conversations.length} conversation(s)</span>
            <button className="btn" onClick={newConversation}>
              New conversation
            </button>
          </>
        }
      />

      <div className="chat__layout">
        <aside className="chat__rail" aria-label="Conversations">
          {convs.loading && !convs.data && <p className="muted">Loading...</p>}
          {convs.error && <p className="error">Failed to load: {convs.error}</p>}
          {!convs.loading && conversations.length === 0 && (
            <p className="muted">No conversations yet - start one below.</p>
          )}
          <ul className="conv-list">
            {conversations.map((c) => (
              <li key={c.id}>
                <button
                  className={`conv-item ${c.id === activeId ? "conv-item--active" : ""}`}
                  onClick={() => selectConversation(c.id)}
                >
                  <span className="conv-item__title">{c.title || "(untitled)"}</span>
                  <span className="conv-item__meta">
                    <span className="badge" title={`Conversation status: ${c.status}`}>
                      {c.status}
                    </span>
                    <span className="muted" title={c.updated_at}>
                      {whenText(c.updated_at)}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <div className="chat__main">
          <div
            className="chat__messages"
            aria-live={slideActive ? "polite" : "off"}
            aria-busy={streaming}
          >
            {msgsLoading && messages.length === 0 && (
              <p className="muted">Loading conversation...</p>
            )}
            {msgsError && <p className="error">Failed to load conversation: {msgsError}</p>}
            {isEmpty && (
              <div className="chat__empty">
                <EmptyState
                  title="Start a conversation"
                  body="Ask in plain language, or pick one to try:"
                  action={
                    <div className="kv" style={{ justifyContent: "center" }}>
                      {EXAMPLE_PROMPTS.map((ex) => (
                        <button
                          key={ex}
                          type="button"
                          className="tag tag--accent"
                          style={{ cursor: "pointer" }}
                          onClick={() => setInput(ex)}
                        >
                          {ex}
                        </button>
                      ))}
                    </div>
                  }
                />
              </div>
            )}

            {messages.map((m) => (
              <MessageBubble
                key={m.id}
                message={m}
                resolvedHitls={resolvedHitls}
                onResolve={resolveHitl}
              />
            ))}

            {pendingUser !== null && (
              <div className="chat-msg chat-msg--user">
                <div className="chat-msg__role">user</div>
                <div className="chat-msg__bubble">
                  <div className="chat-msg__text">{pendingUser}</div>
                </div>
              </div>
            )}

            {showLive && (
              <div className="chat-msg chat-msg--assistant">
                <div className="chat-msg__role">assistant</div>
                <div className="chat-msg__bubble">
                  <TurnExtras
                    turn={live}
                    resolvedHitls={resolvedHitls}
                    onResolve={resolveHitl}
                    onOpenRun={openRun}
                  />
                  {live.text ? (
                    <div className="chat-msg__text">{live.text}</div>
                  ) : (
                    streaming &&
                    !live.reasoning && <div className="chat-msg__typing muted">thinking...</div>
                  )}
                </div>
              </div>
            )}

            {streamError && (
              <div className="chat__reconnect">
                <span className="error">Stream interrupted: {streamError}</span>
                <button className="btn" onClick={() => void reconnect()}>
                  Reconnect
                </button>
              </div>
            )}
          </div>

          <div className={`chat__composer ${streaming ? "chat__composer--thinking" : ""}`}>
            <div className="chat__inputwrap">
              <textarea
                className="chat__input"
                placeholder="Message the orchestrator..."
                value={input}
                rows={2}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onComposerKey}
              />
            </div>
            <button
              className="btn btn--primary"
              disabled={streaming || input.trim().length === 0}
              onClick={() => void send()}
            >
              {streaming ? "Thinking..." : "Send"}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
