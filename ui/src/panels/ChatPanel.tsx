// US-CONV-01..04, US-CONV-07: the conversational chat surface. A left rail
// lists conversations (GET /v1/conversations); selecting one loads its
// transcript (GET /v1/conversations/{id}). Sending a message streams the
// response from POST /v1/chat (SSE) and renders text, dimmed reasoning, tool
// cards, sub-agent cards and inline HITL as the events arrive. The
// conversation_id is threaded into each send (omitted to start a new one; the
// first message_start returns the new id, which we capture).

import { useEffect, useMemo, useRef, useState } from "react";

import { api, streamChat } from "../api/client";
import type {
  ChatEvent,
  ChatMessage,
  HITLKind,
} from "../api/types";
import { useFetch } from "../useFetch";

// --- normalisation: ChatEvent[] -> renderable turn -------------------------
// The same reducer serves the live stream (events accumulated as they arrive)
// and a persisted message's `events`, so both render identically.

interface ToolEntry {
  key: string;
  verb: string;
  input?: unknown;
  status: "running" | "ok" | "error";
  output?: unknown;
}

interface SubagentEntry {
  key: string;
  childRunId: string;
  task: string;
  skills: string[];
}

interface HitlEntry {
  hitlRequestId: string;
  kind: HITLKind;
  question: string;
  options: string[];
}

interface NormalizedTurn {
  runId?: string;
  conversationId?: string;
  text: string;
  reasoning: string;
  tools: ToolEntry[];
  subagents: SubagentEntry[];
  hitls: HitlEntry[];
  ended: boolean;
}

function normalizeEvents(events: ChatEvent[]): NormalizedTurn {
  let runId: string | undefined;
  let conversationId: string | undefined;
  let text = "";
  let reasoning = "";
  let ended = false;
  const tools: ToolEntry[] = [];
  const subagents: SubagentEntry[] = [];
  const hitls: HitlEntry[] = [];

  events.forEach((ev, i) => {
    switch (ev.type) {
      case "message_start":
        runId = ev.run_id;
        conversationId = ev.conversation_id;
        break;
      case "text_delta":
        text += ev.delta;
        break;
      case "reasoning_delta":
        reasoning += ev.delta;
        break;
      case "tool_call":
        tools.push({ key: `t${i}`, verb: ev.verb, input: ev.input, status: "running" });
        break;
      case "tool_result": {
        // Pair a result with the most recent still-running call of the same verb.
        const match = [...tools]
          .reverse()
          .find((t) => t.verb === ev.verb && t.status === "running");
        if (match) {
          match.status = ev.status;
          match.output = ev.output;
        } else {
          tools.push({ key: `t${i}`, verb: ev.verb, status: ev.status, output: ev.output });
        }
        break;
      }
      case "subagent":
        subagents.push({
          key: `s${i}`,
          childRunId: ev.child_run_id,
          task: ev.task,
          skills: ev.skills ?? [],
        });
        break;
      case "hitl":
        hitls.push({
          hitlRequestId: ev.hitl_request_id,
          kind: ev.kind,
          question: ev.question,
          options: ev.options ?? [],
        });
        break;
      case "message_end":
        ended = true;
        runId = ev.run_id ?? runId;
        break;
    }
  });

  return { runId, conversationId, text, reasoning, tools, subagents, hitls, ended };
}

function asPretty(value: unknown): string {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

// --- structured-turn sub-views ---------------------------------------------

function ToolCard({ tool }: { tool: ToolEntry }) {
  return (
    <details className="tool-card">
      <summary className="tool-card__head">
        <code className="badge badge--verb">{tool.verb}</code>
        <span className={`badge badge--tool-${tool.status}`}>{tool.status}</span>
      </summary>
      <div className="tool-card__body">
        {tool.input !== undefined && (
          <div className="tool-card__io">
            <span className="muted">input</span>
            <pre>{asPretty(tool.input)}</pre>
          </div>
        )}
        {tool.output !== undefined && (
          <div className="tool-card__io">
            <span className="muted">output</span>
            <pre>{asPretty(tool.output)}</pre>
          </div>
        )}
      </div>
    </details>
  );
}

function SubagentCard({ sub }: { sub: SubagentEntry }) {
  return (
    <div className="subagent-card">
      <div className="subagent-card__head">
        <span className="badge">sub-agent</span>
        <span className="subagent-card__task">{sub.task || "(no task)"}</span>
      </div>
      {sub.skills.length > 0 && (
        <div className="subagent-card__skills">
          {sub.skills.map((s) => (
            <span className="chip" key={s}>
              {s}
            </span>
          ))}
        </div>
      )}
      <code className="muted">{sub.childRunId}</code>
    </div>
  );
}

// Inline HITL. The same request also surfaces in the Approvals panel (one
// shared store), so answering it here resolves it there too, and vice versa.
function ChatHitlCard({
  entry,
  resolved,
  onResolve,
}: {
  entry: HitlEntry;
  resolved: string | undefined;
  onResolve: (id: string, status: string) => void;
}) {
  const [value, setValue] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // approval shows option buttons (falling back to approve/reject); a
  // clarification shows a free-text input.
  const options =
    entry.kind === "approval"
      ? entry.options.length > 0
        ? entry.options
        : ["approve", "reject"]
      : entry.options;

  async function submit(decision: string) {
    if (!decision) {
      setError("Provide a response.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await api.respondHitl(entry.hitlRequestId, { decision, notes });
      onResolve(entry.hitlRequestId, `recorded (${res.status})`);
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="chat-hitl">
      <div className="chat-hitl__head">
        <span className={`badge badge--type badge--type-${entry.kind}`}>{entry.kind}</span>
        <code className="muted">{entry.hitlRequestId}</code>
      </div>
      <p className="chat-hitl__question">{entry.question || "(no question)"}</p>

      {resolved ? (
        <p className="ok">Answered: {resolved}</p>
      ) : (
        <div className="chat-hitl__respond">
          {entry.kind === "clarification" ? (
            <div className="chat-hitl__row">
              <input
                className="chat-hitl__text"
                placeholder="your answer"
                value={value}
                disabled={busy}
                onChange={(e) => setValue(e.target.value)}
              />
              <button
                className="btn btn--primary"
                disabled={busy}
                onClick={() => submit(value)}
              >
                {busy ? "..." : "Send"}
              </button>
            </div>
          ) : (
            <div className="chat-hitl__options">
              {options.map((opt) => (
                <button key={opt} className="btn" disabled={busy} onClick={() => submit(opt)}>
                  {opt}
                </button>
              ))}
            </div>
          )}
          <textarea
            className="chat-hitl__notes"
            placeholder="notes (optional)"
            value={notes}
            disabled={busy}
            rows={1}
            onChange={(e) => setNotes(e.target.value)}
          />
          {error && <p className="error">{error}</p>}
        </div>
      )}
    </article>
  );
}

function TurnExtras({
  turn,
  resolvedHitls,
  onResolve,
}: {
  turn: NormalizedTurn;
  resolvedHitls: Record<string, string>;
  onResolve: (id: string, status: string) => void;
}) {
  return (
    <>
      {turn.reasoning && (
        <div className="thinking">
          <span className="thinking__label">thinking</span>
          <div className="thinking__body">{turn.reasoning}</div>
        </div>
      )}
      {turn.tools.map((t) => (
        <ToolCard key={t.key} tool={t} />
      ))}
      {turn.subagents.map((s) => (
        <SubagentCard key={s.key} sub={s} />
      ))}
      {turn.hitls.map((h) => (
        <ChatHitlCard
          key={h.hitlRequestId}
          entry={h}
          resolved={resolvedHitls[h.hitlRequestId]}
          onResolve={onResolve}
        />
      ))}
    </>
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
  return (
    <div className={`chat-msg chat-msg--${isAssistant ? "assistant" : message.role}`}>
      <div className="chat-msg__role">{message.role}</div>
      <div className="chat-msg__bubble">
        {isAssistant && <TurnExtras turn={turn} resolvedHitls={resolvedHitls} onResolve={onResolve} />}
        {message.content && <div className="chat-msg__text">{message.content}</div>}
      </div>
    </div>
  );
}

// --- the panel --------------------------------------------------------------

export function ChatPanel() {
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

  // Abort any in-flight stream when the panel unmounts.
  useEffect(() => () => abortRef.current?.abort(), []);

  const live = useMemo(() => normalizeEvents(liveEvents), [liveEvents]);

  function resolveHitl(id: string, status: string) {
    setResolvedHitls((prev) => ({ ...prev, [id]: status }));
  }

  async function loadConversation(id: string) {
    setMsgsLoading(true);
    setMsgsError(null);
    try {
      const res = await api.conversation(id);
      setMessages(res.messages);
    } catch (err) {
      setMsgsError(errText(err));
    } finally {
      setMsgsLoading(false);
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
          if (ev.type === "message_start" && ev.conversation_id) {
            pendingConvId.current = ev.conversation_id;
          }
          setLiveEvents((prev) => [...prev, ev]);
        },
        ctrl.signal,
      );

      // Stream finished cleanly. The transcript persists kernel-side, so reload
      // it (and the conversation list) and drop the local live/optimistic state.
      setStreaming(false);
      const convId = pendingConvId.current;
      if (convId) {
        if (!activeId) setActiveId(convId);
        await loadConversation(convId);
        convs.reload();
      }
      setPendingUser(null);
      setLiveEvents([]);
    } catch (err) {
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
      <div className="panel__head">
        <h2>Chat</h2>
        <div className="panel__actions">
          <span className="muted">{conversations.length} conversation(s)</span>
          <button className="btn" onClick={newConversation}>
            New conversation
          </button>
        </div>
      </div>

      <div className="chat__layout">
        <aside className="chat__rail" aria-label="Conversations">
          {convs.loading && !convs.data && <p className="muted">Loading...</p>}
          {convs.error && <p className="error">Failed to load: {convs.error}</p>}
          {!convs.loading && conversations.length === 0 && (
            <p className="muted">No conversations yet.</p>
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
                    <span className="badge">{c.status}</span>
                    <span className="muted">{c.updated_at}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <div className="chat__main">
          <div className="chat__messages">
            {msgsLoading && messages.length === 0 && (
              <p className="muted">Loading conversation...</p>
            )}
            {msgsError && <p className="error">Failed to load conversation: {msgsError}</p>}
            {isEmpty && (
              <p className="muted chat__empty">
                Start a new conversation, or pick one from the left.
              </p>
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
                  <TurnExtras turn={live} resolvedHitls={resolvedHitls} onResolve={resolveHitl} />
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

          <div className="chat__composer">
            <textarea
              className="chat__input"
              placeholder="Message the orchestrator... (Enter to send, Shift+Enter for newline)"
              value={input}
              rows={2}
              disabled={streaming}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onComposerKey}
            />
            <button
              className="btn btn--primary"
              disabled={streaming || input.trim().length === 0}
              onClick={() => void send()}
            >
              {streaming ? "..." : "Send"}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
