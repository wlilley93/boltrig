// US-CONV-01..04, US-CONV-07: the conversational chat surface. A left rail
// lists conversations (GET /v1/conversations); selecting one loads its
// transcript (GET /v1/conversations/{id}). Sending a message streams the
// response from POST /v1/chat (SSE) and renders text, dimmed reasoning, tool
// cards, sub-agent cards and inline HITL as the events arrive. The
// conversation_id is threaded into each send (omitted to start a new one; the
// first message_start returns the new id, which we capture).

import {
  Children,
  isValidElement,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { api, streamChat, streamRunEvents } from "../api/client";
import type { ChatEvent, ChatMessage, ConversationSummary } from "../api/types";
import { consumeComposerPrefill } from "../composerPrefill";
import { useSlideActive } from "../deck/context";
import { navigate, openRun } from "../router";
import { useFetch } from "../useFetch";
import { TurnExtras, normalizeEvents } from "./chatTurn";
import { apiReason } from "./shared";
import { EmptyState, PageIntro } from "./ux";
import { ArmConfirm } from "./uxFlow";

// The turn normaliser and renderer (tool / sub-agent / inline-HITL cards) live
// in chatTurn.tsx so the Run drawer reuses the exact same rendering.

const EXAMPLE_PROMPTS: ReadonlyArray<string> = [
  "Create a ticket for a refund request",
  "Summarise today's escalations",
  "What can you do for me?",
];

// Faithful server reason (a denied chat shows the kernel's message, not a 403).
const errText = apiReason;

async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall through to the textarea fallback */
  }
  try {
    const el = document.createElement("textarea");
    el.value = text;
    el.setAttribute("readonly", "true");
    el.style.position = "fixed";
    el.style.left = "-9999px";
    document.body.appendChild(el);
    el.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(el);
    return ok;
  } catch {
    return false;
  }
}

function CopyButton({
  text,
  label = "Copy",
  className = "btn btn--ghost btn--sm",
}: {
  text: string;
  label?: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    const ok = await copyText(text);
    if (!ok) return;
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  }
  return (
    <button type="button" className={className} onClick={() => void copy()}>
      {copied ? "Copied" : label}
    </button>
  );
}

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

function CodeBlock({ children }: { children: ReactNode }) {
  const only = Children.only(children) as ReactElement<{
    className?: string;
    children?: ReactNode;
  }>;
  const className = isValidElement(only) ? only.props.className ?? "" : "";
  const raw = isValidElement(only) ? only.props.children : children;
  const text = String(raw ?? "").replace(/\n$/, "");
  const lang = /language-([a-zA-Z0-9_-]+)/.exec(className)?.[1];
  return (
    <div className="md-code">
      <div className="md-code__bar">
        <span className="badge">{lang ?? "code"}</span>
        <CopyButton text={text} label="Copy" className="btn btn--ghost btn--sm md-code__copy" />
      </div>
      <pre>
        <code className={className}>{text}</code>
      </pre>
    </div>
  );
}

const MARKDOWN_COMPONENTS: Components = {
  a({ href, children }) {
    const target = href ?? "";
    if (target.startsWith("#/")) {
      return (
        <button
          type="button"
          className="chat-md__linkchip"
          onClick={() => navigate(target.slice(1))}
        >
          {children}
        </button>
      );
    }
    return (
      <a href={target} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    );
  },
  img({ src, alt }) {
    return (
      <a href={src ?? ""} target="_blank" rel="noopener noreferrer">
        {alt || src || "image"}
      </a>
    );
  },
  pre({ children }) {
    return <CodeBlock>{children}</CodeBlock>;
  },
};

function MarkdownText({ value }: { value: string }) {
  return (
    <div className="chat-md">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
        {value}
      </ReactMarkdown>
    </div>
  );
}

function ConversationRow({
  conversation,
  active,
  onSelect,
  onDeleted,
}: {
  conversation: ConversationSummary;
  active: boolean;
  onSelect: () => void;
  onDeleted: () => void;
}) {
  const title = conversation.title || "(untitled)";
  async function deleteConversation() {
    const res = await api.deleteMyConversation(conversation.id);
    if (res.status !== "ok") throw new Error(res.reason ?? `Delete failed: ${res.status}`);
    onDeleted();
  }
  return (
    <li className="conv-row">
      <button
        className={`conv-item ${active ? "conv-item--active" : ""}`}
        onClick={onSelect}
      >
        <span className="conv-item__title">{title}</span>
        <span className="conv-item__meta">
          <span className="muted" title={conversation.updated_at}>
            {whenText(conversation.updated_at)}
          </span>
        </span>
      </button>
      <div className="conv-row__actions">
        <ArmConfirm
          label="Delete"
          armLabel={<>Delete <strong>{title}</strong>? The audit log is kept.</>}
          confirmLabel="Confirm delete"
          busyLabel="Deleting"
          tone="danger"
          onConfirm={deleteConversation}
        />
      </div>
    </li>
  );
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
  const roleLabel = isAssistant ? "orchestrator" : message.role === "user" ? "you" : message.role;
  return (
    <div className={`chat-msg chat-msg--${isAssistant ? "assistant" : message.role}`}>
      <div className="chat-msg__role">{roleLabel}</div>
      <div className="chat-msg__bubble">
        {isAssistant && (
          <TurnExtras
            turn={turn}
            resolvedHitls={resolvedHitls}
            onResolve={onResolve}
            onOpenRun={openRun}
          />
        )}
        {message.content && <MarkdownText value={message.content} />}
        <div className="chat-msg__meta">
          <span title={message.created_at}>{whenText(message.created_at)}</span>
          {message.content && <CopyButton text={message.content} />}
          {message.run_id && (
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() => openRun(message.run_id as string)}
            >
              View run
            </button>
          )}
        </div>
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

  const [query, setQuery] = useState("");
  const [input, setInput] = useState("");
  const [pendingUser, setPendingUser] = useState<string | null>(null);
  const [liveEvents, setLiveEvents] = useState<ChatEvent[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [stopped, setStopped] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [resolvedHitls, setResolvedHitls] = useState<Record<string, string>>({});
  const [showJump, setShowJump] = useState(false);

  // The conversation_id is unknown until the first message_start of a new
  // conversation; we hold it in a ref so the stream callback can stash it
  // without churning React state mid-stream.
  const pendingConvId = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const alive = useRef(true); // false after unmount: guards setState past an await
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const messagesRef = useRef<HTMLDivElement | null>(null);
  const pinnedRef = useRef(true);

  // Abort any in-flight stream and stop touching state when the panel unmounts.
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      abortRef.current?.abort();
    };
  }, []);

  const live = useMemo(() => normalizeEvents(liveEvents), [liveEvents]);

  useEffect(() => {
    if (!slideActive) return;
    const text = consumeComposerPrefill();
    if (!text) return;
    setInput((prev) => (prev.trim() ? `${prev}\n${text}` : text));
    const focusComposer = () => {
      const el = inputRef.current;
      if (!el) return;
      el.focus();
      el.selectionStart = el.value.length;
      el.selectionEnd = el.value.length;
    };
    window.requestAnimationFrame(focusComposer);
    window.setTimeout(focusComposer, 460);
  }, [slideActive]);

  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [input]);

  useEffect(() => {
    const el = messagesRef.current;
    if (!el) return;
    if (pinnedRef.current) {
      el.scrollTop = el.scrollHeight;
      setShowJump(false);
    } else if (streaming || liveEvents.length > 0) {
      setShowJump(true);
    }
  }, [messages.length, pendingUser, live.text, liveEvents.length, streaming]);

  function onMessagesScroll() {
    const el = messagesRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    pinnedRef.current = atBottom;
    if (atBottom) setShowJump(false);
  }

  function jumpToLatest() {
    const el = messagesRef.current;
    if (!el) return;
    pinnedRef.current = true;
    setShowJump(false);
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }

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
    setStopped(false);
    setStreamError(null);
    setPendingUser(null);
    setLiveEvents([]);
    setActiveId(id);
    void loadConversation(id);
  }

  function newConversation() {
    abortRef.current?.abort();
    setStreaming(false);
    setStopped(false);
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
    setStopped(false);
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
    setStopped(false);
  }

  function onComposerKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  }

  function stopWatching() {
    abortRef.current?.abort();
    setStreaming(false);
    setStopped(true);
  }

  async function watchAgain() {
    if (!live.runId) {
      await reconnect();
      return;
    }
    setStopped(false);
    setStreamError(null);
    setStreaming(true);
    setLiveEvents([]);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      await streamRunEvents(
        live.runId,
        (ev) => {
          if (ctrl.signal.aborted || !alive.current) return;
          setLiveEvents((prev) => [...prev, ev]);
        },
        { signal: ctrl.signal, follow: true },
      );
      if (!alive.current) return;
      setStreaming(false);
      const convId = activeId ?? pendingConvId.current ?? live.conversationId;
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
      if (ctrl.signal.aborted) return;
      setStreamError(errText(err));
    } finally {
      if (abortRef.current === ctrl) abortRef.current = null;
    }
  }

  const conversations = convs.data?.conversations ?? [];
  const filteredConversations = conversations.filter((c) => {
    if (c.status.toLowerCase() === "closed") return false;
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return (c.title || "(untitled)").toLowerCase().includes(q);
  });
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
          <div className="chat__railhead">
            <span className="chat__railtitle">Conversations</span>
            <span className="muted">{filteredConversations.length}</span>
          </div>
          <input
            className="chat__search"
            aria-label="Filter conversations"
            placeholder="Filter conversations"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {convs.loading && !convs.data && <p className="muted">Loading...</p>}
          {convs.error && <p className="error">Failed to load: {convs.error}</p>}
          {!convs.loading && conversations.length === 0 && (
            <p className="muted">No conversations yet - start one below.</p>
          )}
          {!convs.loading && conversations.length > 0 && filteredConversations.length === 0 && (
            <p className="muted">No matches.</p>
          )}
          <ul className="conv-list">
            {filteredConversations.map((c) => (
              <ConversationRow
                key={c.id}
                conversation={c}
                active={c.id === activeId}
                onSelect={() => selectConversation(c.id)}
                onDeleted={() => {
                  if (c.id === activeId) newConversation();
                  convs.reload();
                }}
              />
            ))}
          </ul>
        </aside>

        <div className="chat__main">
          <div
            className="chat__messages"
            aria-live={slideActive ? "polite" : "off"}
            aria-busy={streaming}
            ref={messagesRef}
            onScroll={onMessagesScroll}
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
                <div className="chat-msg__role">you</div>
                <div className="chat-msg__bubble">
                  <MarkdownText value={pendingUser} />
                  <div className="chat-msg__meta">
                    <span>sending</span>
                    <CopyButton text={pendingUser} />
                  </div>
                </div>
              </div>
            )}

            {showLive && (
              <div className="chat-msg chat-msg--assistant">
                <div className="chat-msg__role">orchestrator</div>
                <div className="chat-msg__bubble">
                  <TurnExtras
                    turn={live}
                    resolvedHitls={resolvedHitls}
                    onResolve={resolveHitl}
                    onOpenRun={openRun}
                  />
                  {live.text ? (
                    <MarkdownText value={live.text} />
                  ) : (
                    streaming &&
                    !live.reasoning && <div className="chat-msg__typing muted">thinking...</div>
                  )}
                  {live.text && (
                    <div className="chat-msg__meta">
                      {live.runId && (
                        <button
                          type="button"
                          className="btn btn--ghost btn--sm"
                          onClick={() => openRun(live.runId as string)}
                        >
                          View run
                        </button>
                      )}
                      <CopyButton text={live.text} />
                    </div>
                  )}
                </div>
              </div>
            )}

            {stopped && (
              <div className="chat__stopped">
                <span>
                  Stopped watching. The agent may still be finishing on the server.
                </span>
                <button className="btn" onClick={() => void watchAgain()}>
                  Watch again
                </button>
                <button className="btn btn--ghost" onClick={() => void reconnect()}>
                  Refresh transcript
                </button>
              </div>
            )}

            {streamError && (
              <div className="chat__reconnect">
                <span className="error">Stream interrupted: {streamError}</span>
                {live.runId && (
                  <button className="btn" onClick={() => void watchAgain()}>
                    Reconnect live
                  </button>
                )}
                <button className="btn" onClick={() => void reconnect()}>
                  Refresh transcript
                </button>
              </div>
            )}

            {showJump && (
              <button className="chat__jump" type="button" onClick={jumpToLatest}>
                Jump to latest
              </button>
            )}
          </div>

          <div className={`chat__composer ${streaming ? "chat__composer--thinking" : ""}`}>
            <div className="chat__inputwrap">
              <textarea
                ref={inputRef}
                className="chat__input"
                placeholder="Message the orchestrator..."
                value={input}
                rows={2}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onComposerKey}
              />
              <div className="chat__hint">Shift+Enter for a new line.</div>
            </div>
            {streaming ? (
              <button className="btn" onClick={stopWatching}>
                Stop
              </button>
            ) : (
              <button
                className="btn btn--primary"
                disabled={input.trim().length === 0}
                onClick={() => void send()}
              >
                Send
              </button>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
