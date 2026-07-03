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
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { ApiError, api, streamChat, streamRunEvents } from "../api/client";
import type {
  ChatAttachment,
  ChatEvent,
  ChatMessage,
  ChatRequest,
  ConversationSearchResult,
} from "../api/types";
import { consumeComposerPrefill } from "../composerPrefill";
import { useSlideActive } from "../deck/context";
import { navigate, openRun } from "../router";
import {
  loadReadAloud,
  saveReadAloud,
  useDictation,
  useSpeech,
  type Speech,
} from "../voice";
import { TurnExtras, normalizeEvents } from "./chatTurn";
import { apiReason } from "./shared";
import { EmptyState, FetchError, PageIntro } from "./ux";
import { ArmConfirm, Skeleton } from "./uxFlow";
import { Switch } from "./uxForm";

// The turn normaliser and renderer (tool / sub-agent / inline-HITL cards) live
// in chatTurn.tsx so the Run drawer reuses the exact same rendering.

const EXAMPLE_PROMPTS: ReadonlyArray<string> = [
  "Create a ticket for a refund request",
  "Summarise today's escalations",
  "What can you do for me?",
];

// Faithful server reason (a denied chat shows the kernel's message, not a 403).
const errText = apiReason;

// Conversation-rail pagination + search (US-CONV-09 / US-CONV-10). The rail
// loads one bounded page at a time and follows next_offset until it is null; the
// default page size mirrors the kernel's conservative default (it is re-clamped
// under the config ceiling server-side either way). Typing in the search box is
// debounced so a term is not queried on every keystroke; clearing it restores
// the paginated list immediately.
const PAGE_SIZE = 25;
const SEARCH_DEBOUNCE_MS = 300;

type RailMode = "list" | "search";

interface RailState {
  mode: RailMode;
  // In list mode snippet is always null; in search mode it carries the matched
  // message preview (or null when the match was on the title alone).
  items: ConversationSearchResult[];
  // The offset to request for the next page, or null when the list/results are
  // exhausted (no more pages to load).
  nextOffset: number | null;
  loading: boolean; // first-page load (drives the Skeleton)
  loadingMore: boolean; // a "Load more" / scroll-triggered append in flight
  error: string | null;
  errorStatus: number | null;
}

function errStatus(err: unknown): number | null {
  return err instanceof ApiError ? err.status : null;
}

// Split `text` on every case-insensitive occurrence of `term` and wrap the
// matches in <mark>, so a search result shows WHY it matched. An empty term (or
// no match) returns the text untouched. Regex specials in the term are escaped
// so a user typing "a.b" matches the literal string, never a wildcard.
function Highlight({ text, term }: { text: string; term: string }) {
  const needle = term.trim();
  if (!needle) return <>{text}</>;
  const escaped = needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const parts = text.split(new RegExp(`(${escaped})`, "ig"));
  const lower = needle.toLowerCase();
  return (
    <>
      {parts.map((part, i) =>
        part.toLowerCase() === lower ? (
          <mark key={i} className="conv-item__hl">
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

// The conversation rail's data engine: it owns the paginated list, the debounced
// search, and the next_offset cursor, and exposes reload() (refetch the first
// page in place, e.g. after a send / delete / rename) and loadMore() (append the
// next page). A monotonic request id drops stale in-flight responses so a fast
// switch between the list and a search term never renders the wrong page.
function useConversationRail(query: string) {
  const trimmed = query.trim();
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    // Clearing the box restores the list immediately (0ms); typing a term waits
    // out the debounce so we do not query on every keystroke.
    const delay = trimmed ? SEARCH_DEBOUNCE_MS : 0;
    const timer = window.setTimeout(() => setDebounced(trimmed), delay);
    return () => window.clearTimeout(timer);
  }, [trimmed]);

  const [state, setState] = useState<RailState>({
    mode: "list",
    items: [],
    nextOffset: null,
    loading: true,
    loadingMore: false,
    error: null,
    errorStatus: null,
  });
  // Mirror the latest state so loadMore can read the live cursor without being a
  // dependency of its own callback (which would rebuild it every render).
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const seq = useRef(0);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // Load the first page for the current query. `background` (a reload) leaves the
  // existing rows in place instead of flashing the Skeleton.
  const fetchFirst = useCallback(
    async (background: boolean) => {
      const mine = ++seq.current;
      const q = debounced;
      const mode: RailMode = q ? "search" : "list";
      if (!background) {
        setState((s) => ({
          ...s,
          loading: true,
          loadingMore: false,
          error: null,
          errorStatus: null,
        }));
      }
      try {
        let items: ConversationSearchResult[];
        let nextOffset: number | null;
        if (mode === "list") {
          const res = await api.listConversations(PAGE_SIZE, 0);
          items = res.conversations.map((c) => ({ ...c, snippet: null }));
          nextOffset = res.next_offset ?? null;
        } else {
          const res = await api.searchConversations(q, PAGE_SIZE, 0);
          items = res.results;
          nextOffset = res.next_offset ?? null;
        }
        if (!alive.current || mine !== seq.current) return;
        setState({
          mode,
          items,
          nextOffset,
          loading: false,
          loadingMore: false,
          error: null,
          errorStatus: null,
        });
      } catch (err) {
        if (!alive.current || mine !== seq.current) return;
        setState((s) => ({
          ...s,
          loading: false,
          loadingMore: false,
          error: apiReason(err),
          errorStatus: errStatus(err),
        }));
      }
    },
    [debounced],
  );

  useEffect(() => {
    void fetchFirst(false);
  }, [fetchFirst]);

  // Append the next page (following next_offset). Tied to the first-page request
  // id: if the query changes while a page is in flight, its response is dropped.
  const loadMore = useCallback(async () => {
    const cur = stateRef.current;
    if (cur.nextOffset === null || cur.loading || cur.loadingMore) return;
    const offset = cur.nextOffset;
    const mine = seq.current;
    const q = debounced;
    const mode: RailMode = q ? "search" : "list";
    setState((s) => ({ ...s, loadingMore: true }));
    try {
      let more: ConversationSearchResult[];
      let nextOffset: number | null;
      if (mode === "list") {
        const res = await api.listConversations(PAGE_SIZE, offset);
        more = res.conversations.map((c) => ({ ...c, snippet: null }));
        nextOffset = res.next_offset ?? null;
      } else {
        const res = await api.searchConversations(q, PAGE_SIZE, offset);
        more = res.results;
        nextOffset = res.next_offset ?? null;
      }
      if (!alive.current || mine !== seq.current) return;
      setState((s) => {
        // Dedupe by id so a row already on screen is never doubled (e.g. a new
        // conversation shifting the offsets between pages).
        const seen = new Set(s.items.map((i) => i.id));
        return {
          ...s,
          items: [...s.items, ...more.filter((m) => !seen.has(m.id))],
          nextOffset,
          loadingMore: false,
        };
      });
    } catch (err) {
      if (!alive.current || mine !== seq.current) return;
      setState((s) => ({
        ...s,
        loadingMore: false,
        error: apiReason(err),
        errorStatus: errStatus(err),
      }));
    }
  }, [debounced]);

  return { state, reload: () => void fetchFirst(true), loadMore };
}

// Attachment caps mirror the fail-closed ChatConfig defaults on the kernel
// ([2026] VJS-COUNTY 3): a count cap, a per-file decoded-bytes cap, and a total
// decoded-bytes cap. They are enforced here so an over-cap turn is rejected
// before it is sent; the backend re-checks and returns 413 attachment_rejected,
// which the send path also surfaces (never a silent drop).
const MAX_ATTACHMENTS = 8;
const MAX_ATTACHMENT_BYTES = 256 * 1024;
const MAX_TOTAL_ATTACHMENT_BYTES = 1024 * 1024;

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10 * 1024 ? 1 : 0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function isTextAttachment(mediaType: string): boolean {
  return (mediaType || "").toLowerCase().startsWith("text/");
}

// Base64-encode raw bytes in chunks: btoa over one huge binary string can blow
// the call stack on a large file.
function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

function decodeTextAttachment(data: string): string {
  try {
    const bin = atob(data);
    const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
    return new TextDecoder().decode(bytes);
  } catch {
    return "";
  }
}

// A single rendered attachment: name + media type (+ size when recorded). A
// text/* attachment gets an expandable inline preview; every other type is a
// record-only chip (the kernel never decodes it into the model input either).
function AttachmentChip({ att }: { att: ChatAttachment }) {
  const meta = `${att.media_type}${att.size ? ` - ${formatBytes(att.size)}` : ""}`;
  if (isTextAttachment(att.media_type)) {
    const text = decodeTextAttachment(att.data);
    return (
      <details className="chat-att chat-att--text">
        <summary className="chat-att__head">
          <span className="chat-att__name">{att.name}</span>
          <span className="chat-att__meta muted">{meta}</span>
        </summary>
        <pre className="chat-att__preview">{text.slice(0, 4000)}</pre>
      </details>
    );
  }
  return (
    <span className="chat-att">
      <span className="chat-att__name">{att.name}</span>
      <span className="chat-att__meta muted">{meta}</span>
    </span>
  );
}

function AttachmentList({ attachments }: { attachments?: ChatAttachment[] }) {
  if (!attachments || attachments.length === 0) return null;
  return (
    <div className="chat-atts">
      {attachments.map((a, i) => (
        <AttachmentChip key={`${a.name}-${i}`} att={a} />
      ))}
    </div>
  );
}

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
  highlight = "",
  onSelect,
  onDeleted,
  onRenamed,
}: {
  conversation: ConversationSearchResult;
  active: boolean;
  // the search term to highlight in the title + snippet ("" in list mode)
  highlight?: string;
  onSelect: () => void;
  onDeleted: () => void;
  onRenamed: () => void;
}) {
  const title = conversation.title || "(untitled)";
  const snippet = conversation.snippet;
  const [renaming, setRenaming] = useState(false);
  const [draft, setDraft] = useState("");
  const [renameError, setRenameError] = useState<string | null>(null);
  // Escape cancels; the blur that follows must not commit the draft.
  const cancelledRef = useRef(false);
  async function deleteConversation() {
    const res = await api.deleteMyConversation(conversation.id);
    if (res.status !== "ok") throw new Error(res.reason ?? `Delete failed: ${res.status}`);
    onDeleted();
  }
  function startRename() {
    setDraft(conversation.title || "");
    setRenameError(null);
    cancelledRef.current = false;
    setRenaming(true);
  }
  async function commitRename() {
    const next = draft.trim();
    if (!next || next === (conversation.title ?? "")) {
      setRenaming(false);
      return;
    }
    const res = await api.renameConversation(conversation.id, next);
    if (res.status !== "ok") {
      setRenameError(res.reason ?? `Rename failed: ${res.status}`);
      return;
    }
    setRenaming(false);
    onRenamed();
  }
  return (
    <li className="conv-row">
      {renaming ? (
        <input
          className="chat__search"
          aria-label="Conversation title"
          value={draft}
          autoFocus
          maxLength={120}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.currentTarget.blur(); // blur commits (single commit path)
            } else if (e.key === "Escape") {
              e.stopPropagation();
              cancelledRef.current = true;
              setRenaming(false);
            }
          }}
          onBlur={() => {
            if (cancelledRef.current) {
              cancelledRef.current = false;
              return;
            }
            void commitRename();
          }}
        />
      ) : (
        <button
          className={`conv-item ${active ? "conv-item--active" : ""}`}
          onClick={onSelect}
        >
          <span className="conv-item__title">
            <Highlight text={title} term={highlight} />
          </span>
          {snippet && (
            <span className="conv-item__snippet">
              <Highlight text={snippet} term={highlight} />
            </span>
          )}
          <span className="conv-item__meta">
            <span className="muted" title={conversation.updated_at}>
              {whenText(conversation.updated_at)}
            </span>
          </span>
        </button>
      )}
      <div className="conv-row__actions">
        {!renaming && (
          <button type="button" className="btn" onClick={startRename}>
            Rename
          </button>
        )}
        <ArmConfirm
          label="Delete"
          armLabel={<>Delete <strong>{title}</strong>? The audit log is kept.</>}
          confirmLabel="Confirm delete"
          busyLabel="Deleting"
          tone="danger"
          onConfirm={deleteConversation}
        />
      </div>
      {renameError && (
        <p className="error" role="alert">
          {renameError}
        </p>
      )}
    </li>
  );
}

// A per-message "read aloud" control (only for assistant text, and only when
// the browser supports speechSynthesis). Speaks that message on demand and
// toggles to Stop while it is the one being spoken.
function SpeakButton({ speech, msgKey, text }: { speech: Speech; msgKey: string; text: string }) {
  if (!speech.supported || !text.trim()) return null;
  const speaking = speech.speakingKey === msgKey;
  return (
    <button
      type="button"
      className="btn btn--ghost btn--sm"
      aria-pressed={speaking}
      onClick={() => (speaking ? speech.cancel() : speech.speak(msgKey, text))}
    >
      {speaking ? "Stop" : "Read aloud"}
    </button>
  );
}

function MessageBubble({
  message,
  resolvedHitls,
  onResolve,
  canRegenerate,
  regenerating,
  onRegenerate,
  speech,
}: {
  message: ChatMessage;
  resolvedHitls: Record<string, string>;
  onResolve: (id: string, status: string) => void;
  canRegenerate: boolean;
  regenerating: boolean;
  onRegenerate: () => void;
  speech: Speech;
}) {
  const turn = useMemo(() => normalizeEvents(message.events ?? []), [message.events]);
  const isAssistant = message.role === "assistant";
  const roleLabel = isAssistant ? "orchestrator" : message.role === "user" ? "you" : message.role;
  const superseded = Boolean(message.superseded_by);

  const body = (
    <>
      {isAssistant && (
        <TurnExtras
          turn={turn}
          resolvedHitls={resolvedHitls}
          onResolve={onResolve}
          onOpenRun={openRun}
        />
      )}
      {message.content && <MarkdownText value={message.content} />}
      <AttachmentList attachments={message.attachments} />
      <div className="chat-msg__meta">
        <span title={message.created_at}>{whenText(message.created_at)}</span>
        {message.content && <CopyButton text={message.content} />}
        {isAssistant && message.content && (
          <SpeakButton speech={speech} msgKey={message.id} text={message.content} />
        )}
        {message.run_id && (
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => openRun(message.run_id as string)}
          >
            View run
          </button>
        )}
        {canRegenerate && (
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            disabled={regenerating}
            onClick={onRegenerate}
          >
            {regenerating ? "Regenerating..." : "Regenerate"}
          </button>
        )}
      </div>
    </>
  );

  return (
    <div
      className={`chat-msg chat-msg--${isAssistant ? "assistant" : message.role}${
        superseded ? " chat-msg--superseded" : ""
      }`}
    >
      <div className="chat-msg__role">{roleLabel}</div>
      <div className="chat-msg__bubble">
        {superseded ? (
          // A regenerated reply is frozen, not deleted: keep it on the record,
          // collapsed and dimmed, behind a disclosure (US: append-plus-supersede).
          <details className="chat-msg__superseded">
            <summary className="chat-msg__supersededhead muted">
              Superseded reply (regenerated) - click to view
            </summary>
            {body}
          </details>
        ) : (
          body
        )}
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

  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [msgsLoading, setMsgsLoading] = useState(false);
  const [msgsError, setMsgsError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  // The conversation rail: paginated list + debounced search over the same rail.
  const rail = useConversationRail(query);
  const [input, setInput] = useState("");
  const [pendingUser, setPendingUser] = useState<string | null>(null);
  const [liveEvents, setLiveEvents] = useState<ChatEvent[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [stopped, setStopped] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [resolvedHitls, setResolvedHitls] = useState<Record<string, string>>({});
  const [showJump, setShowJump] = useState(false);

  // Composer attachments awaiting send, the copy shown on the optimistic user
  // bubble while a turn streams, and any client-side cap rejection.
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [pendingAttachments, setPendingAttachments] = useState<ChatAttachment[]>([]);
  const [attachError, setAttachError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // The message id currently being regenerated (its button shows a busy state).
  const [regenerating, setRegenerating] = useState<string | null>(null);

  // Browser-native voice (Web Speech API). Both are feature-detected inside the
  // hooks and are inert when the browser lacks support, so the controls simply
  // do not render and nothing throws.
  const speech = useSpeech();
  const [readAloud, setReadAloud] = useState<boolean>(() => loadReadAloud());
  // The composer text captured when dictation starts: transcribed words are
  // appended to it so the user can dictate mid-message and still edit.
  const dictationBaseRef = useRef("");
  // While sending we stop dictation but must not let its trailing final result
  // repopulate the just-cleared composer; this suppresses that last callback.
  const suppressDictationRef = useRef(false);
  const dictation = useDictation((transcript, done) => {
    if (suppressDictationRef.current) {
      if (done) suppressDictationRef.current = false;
      return;
    }
    const base = dictationBaseRef.current;
    const joined = base ? `${base.replace(/\s+$/, "")} ${transcript}` : transcript;
    setInput(done ? joined.trimEnd() : joined);
  });
  // The assistant text accumulated across a streaming turn (text deltas only,
  // never tool callouts or heartbeats), plus whether the turn was cancelled, so
  // a completed turn can be read aloud when the preference is on.
  const turnTextRef = useRef("");
  const turnCancelledRef = useRef(false);

  function setReadAloudPref(on: boolean) {
    setReadAloud(on);
    saveReadAloud(on);
    if (!on) speech.cancel();
  }

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

  // Regenerate is offered on the LAST live (non-superseded) assistant reply only
  // (the backend rejects any earlier target with 409 regenerate_not_eligible).
  const lastAssistantId = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      if (m.role === "assistant" && !m.superseded_by) return m.id;
    }
    return null;
  }, [messages]);

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

  // Read the chosen files, base64-encode them, and enforce the caps client-side
  // (count, per-file, total). A rejected file is reported, never silently dropped.
  async function addFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setAttachError(null);
    const next = [...attachments];
    for (const file of Array.from(files)) {
      if (next.length >= MAX_ATTACHMENTS) {
        setAttachError(`Too many attachments (max ${MAX_ATTACHMENTS}).`);
        break;
      }
      if (file.size > MAX_ATTACHMENT_BYTES) {
        setAttachError(
          `${file.name} is ${formatBytes(file.size)} (max ` +
            `${formatBytes(MAX_ATTACHMENT_BYTES)} per file).`,
        );
        continue;
      }
      const total = next.reduce((s, a) => s + (a.size ?? 0), 0) + file.size;
      if (total > MAX_TOTAL_ATTACHMENT_BYTES) {
        setAttachError(
          `Attachments exceed the ${formatBytes(MAX_TOTAL_ATTACHMENT_BYTES)} total cap.`,
        );
        break;
      }
      try {
        const buf = await file.arrayBuffer();
        if (!alive.current) return;
        next.push({
          name: file.name || "attachment",
          media_type: file.type || "application/octet-stream",
          data: bytesToBase64(new Uint8Array(buf)),
          size: file.size,
        });
      } catch {
        setAttachError(`Could not read ${file.name}.`);
      }
    }
    setAttachments(next);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function removeAttachment(index: number) {
    setAttachments((prev) => prev.filter((_, i) => i !== index));
    setAttachError(null);
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
    speech.cancel();
    abortRef.current?.abort();
    setStreaming(false);
    setStopped(false);
    setStreamError(null);
    setPendingUser(null);
    setPendingAttachments([]);
    setLiveEvents([]);
    setActiveId(id);
    void loadConversation(id);
  }

  function newConversation() {
    speech.cancel();
    abortRef.current?.abort();
    setStreaming(false);
    setStopped(false);
    setStreamError(null);
    setPendingUser(null);
    setPendingAttachments([]);
    setAttachments([]);
    setAttachError(null);
    setLiveEvents([]);
    setActiveId(null);
    setMessages([]);
  }

  async function send() {
    const text = input.trim();
    const atts = attachments;
    if ((!text && atts.length === 0) || streaming) return;

    // Stop dictation (its trailing final result is suppressed) and silence any
    // reply still being read aloud before a new turn begins.
    if (dictation.listening) {
      suppressDictationRef.current = true;
      dictation.stop();
    }
    speech.cancel();
    turnTextRef.current = "";
    turnCancelledRef.current = false;

    setInput("");
    setStreamError(null);
    setAttachError(null);
    setStopped(false);
    setPendingUser(text);
    setPendingAttachments(atts);
    setAttachments([]);
    setLiveEvents([]);
    setStreaming(true);
    pendingConvId.current = activeId;

    const req: ChatRequest = activeId
      ? { conversation_id: activeId, message: text }
      : { message: text };
    if (atts.length > 0) req.attachments = atts;

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      await streamChat(
        req,
        (ev) => {
          if (ctrl.signal.aborted || !alive.current) return;
          if (ev.type === "message_start" && ev.conversation_id) {
            pendingConvId.current = ev.conversation_id;
          }
          // Accumulate only the assistant's own text for read-aloud (tool cards
          // and heartbeats are never spoken).
          if (ev.type === "text_delta") turnTextRef.current += ev.delta;
          // A server-side cancel ends the stream: mark the turn stopped so the
          // banner shows once the (partial) reply settles (and do not speak it).
          if (ev.type === "cancelled") {
            setStopped(true);
            turnCancelledRef.current = true;
          }
          setLiveEvents((prev) => [...prev, ev]);
        },
        ctrl.signal,
      );

      if (!alive.current) return;
      // Stream finished cleanly. The transcript persists kernel-side, so reload
      // it (and the conversation list) and drop the local live/optimistic state.
      setStreaming(false);
      // Read the completed reply aloud when the preference is on (never a
      // cancelled turn, and only the assistant text collected above).
      if (readAloud && !turnCancelledRef.current) {
        speech.speak(`auto:${pendingConvId.current ?? "live"}`, turnTextRef.current);
      }
      const convId = pendingConvId.current;
      if (convId) {
        if (!activeId) setActiveId(convId);
        await loadConversation(convId);
        if (!alive.current) return;
        rail.reload();
      }
      setPendingUser(null);
      setPendingAttachments([]);
      setLiveEvents([]);
    } catch (err) {
      if (!alive.current) return;
      setStreaming(false);
      if (ctrl.signal.aborted) return; // user switched/cancelled; not an error
      // The kernel rejects an over-cap turn with 413 before it streams; restore
      // the attachments to the composer so the user can trim and retry.
      if (err instanceof ApiError && err.status === 413) {
        setAttachments(atts);
        setAttachError(errText(err));
      }
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
      rail.reload();
    }
    setPendingUser(null);
    setPendingAttachments([]);
    setLiveEvents([]);
    setStopped(false);
  }

  function onComposerKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  }

  // Stop the active turn: cancel it server-side (owner-only, cooperative) so the
  // stream emits a terminal `cancelled` event and closes cleanly. Before the
  // first message_start there is no run id yet, so fall back to a local abort;
  // likewise if the cancel could not be recorded (e.g. not yet a work item).
  async function stopTurn() {
    const runId = live.runId;
    // The user is stopping: mark the turn cancelled so it is not read aloud, and
    // silence anything already speaking.
    turnCancelledRef.current = true;
    speech.cancel();
    setStopped(true);
    if (!runId) {
      abortRef.current?.abort();
      setStreaming(false);
      return;
    }
    try {
      const res = await api.cancelRun(runId);
      if (!alive.current) return;
      if (res.status !== "ok") {
        abortRef.current?.abort();
        setStreaming(false);
      }
      // On success the backend closes the stream via the `cancelled` event; the
      // send() loop then settles on its own (no local abort needed).
    } catch {
      if (!alive.current) return;
      abortRef.current?.abort();
      setStreaming(false);
    }
  }

  // Regenerate the last assistant reply (owner-only, append-plus-supersede). The
  // route drives the whole turn server-side and returns the new message, so we
  // reload the transcript to show the fresh reply and the now-dimmed prior one.
  async function regenerate(messageId: string) {
    if (!activeId || streaming || regenerating) return;
    setRegenerating(messageId);
    setStreamError(null);
    setMsgsError(null);
    try {
      const res = await api.regenerateMessage(activeId, messageId);
      if (!alive.current) return;
      if (res.status !== "ok") {
        setMsgsError(res.reason ?? `Regenerate failed: ${res.status}`);
      }
      await loadConversation(activeId);
      if (!alive.current) return;
      rail.reload();
    } catch (err) {
      if (alive.current) setMsgsError(errText(err));
    } finally {
      if (alive.current) setRegenerating(null);
    }
  }

  async function watchAgain() {
    if (!live.runId) {
      await reconnect();
      return;
    }
    speech.cancel();
    turnTextRef.current = "";
    turnCancelledRef.current = false;
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
          if (ev.type === "text_delta") turnTextRef.current += ev.delta;
          if (ev.type === "cancelled") turnCancelledRef.current = true;
          setLiveEvents((prev) => [...prev, ev]);
        },
        { signal: ctrl.signal, follow: true },
      );
      if (!alive.current) return;
      setStreaming(false);
      if (readAloud && !turnCancelledRef.current) {
        speech.speak(`auto:${activeId ?? pendingConvId.current ?? "live"}`, turnTextRef.current);
      }
      const convId = activeId ?? pendingConvId.current ?? live.conversationId;
      if (convId) {
        if (!activeId) setActiveId(convId);
        await loadConversation(convId);
        if (!alive.current) return;
        rail.reload();
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

  // The rail rows to render. In list mode, hide any closed conversation (the
  // former client behaviour); search results come pre-scoped from the server, so
  // they are shown as-is. next_offset pagination is independent of this display
  // filter (it follows the server's cursor, not the rendered count).
  const searching = rail.state.mode === "search";
  const railItems = searching
    ? rail.state.items
    : rail.state.items.filter((c) => c.status.toLowerCase() !== "closed");
  const railTerm = searching ? query.trim() : "";
  const railFirstLoad = rail.state.loading && rail.state.items.length === 0;
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
            <span className="muted">{railItems.length} loaded</span>
            {speech.supported && (
              <Switch
                checked={readAloud}
                onChange={setReadAloudPref}
                label="Read aloud"
                hint="Speak replies as they finish."
              />
            )}
            <button className="btn" onClick={newConversation}>
              New conversation
            </button>
          </>
        }
      />

      <div className="chat__layout">
        <aside className="chat__rail" aria-label="Conversations">
          <div className="chat__railhead">
            <span className="chat__railtitle">
              {searching ? "Search results" : "Conversations"}
            </span>
            <span className="muted">{railItems.length}</span>
          </div>
          <input
            className="chat__search"
            type="search"
            aria-label="Search conversations"
            placeholder="Search conversations"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {railFirstLoad && <Skeleton variant="rows" count={6} />}
          {!railFirstLoad && rail.state.error && (
            <FetchError
              error={rail.state.error}
              status={rail.state.errorStatus}
              onRetry={rail.reload}
            />
          )}
          {!railFirstLoad && !rail.state.error && railItems.length === 0 && (
            searching ? (
              <EmptyState
                title="No matches"
                body={
                  <>
                    Nothing matched <strong>{query.trim()}</strong>. Try a
                    different word, or clear the box to see all conversations.
                  </>
                }
              />
            ) : (
              <p className="muted">No conversations yet - start one below.</p>
            )
          )}
          <ul
            className="conv-list"
            onScroll={(e) => {
              // Scroll-to-bottom auto-loads the next page when the rail list is a
              // scroll container; the Load more button below is the always-present
              // fallback. Both follow the same next_offset cursor.
              const el = e.currentTarget;
              if (
                rail.state.nextOffset !== null &&
                !rail.state.loadingMore &&
                el.scrollHeight - el.scrollTop - el.clientHeight < 48
              ) {
                void rail.loadMore();
              }
            }}
          >
            {railItems.map((c) => (
              <ConversationRow
                key={c.id}
                conversation={c}
                active={c.id === activeId}
                highlight={railTerm}
                onSelect={() => selectConversation(c.id)}
                onDeleted={() => {
                  if (c.id === activeId) newConversation();
                  rail.reload();
                }}
                onRenamed={() => rail.reload()}
              />
            ))}
          </ul>
          {rail.state.nextOffset !== null && (
            <button
              type="button"
              className="btn btn--ghost chat__loadmore"
              disabled={rail.state.loadingMore}
              onClick={() => void rail.loadMore()}
            >
              {rail.state.loadingMore ? "Loading..." : "Load more"}
            </button>
          )}
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
                canRegenerate={
                  m.id === lastAssistantId && !streaming && pendingUser === null
                }
                regenerating={regenerating === m.id}
                onRegenerate={() => void regenerate(m.id)}
                speech={speech}
              />
            ))}

            {pendingUser !== null && (
              <div className="chat-msg chat-msg--user">
                <div className="chat-msg__role">you</div>
                <div className="chat-msg__bubble">
                  {pendingUser && <MarkdownText value={pendingUser} />}
                  <AttachmentList attachments={pendingAttachments} />
                  <div className="chat-msg__meta">
                    <span>sending</span>
                    {pendingUser && <CopyButton text={pendingUser} />}
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
                      {!streaming && (
                        <SpeakButton speech={speech} msgKey="auto:live" text={live.text} />
                      )}
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
              {attachments.length > 0 && (
                <div className="chat-atts chat-atts--pending">
                  {attachments.map((a, i) => (
                    <span className="chat-att chat-att--pending" key={`${a.name}-${i}`}>
                      <span className="chat-att__name">{a.name}</span>
                      <span className="chat-att__meta muted">
                        {formatBytes(a.size ?? 0)}
                      </span>
                      <button
                        type="button"
                        className="chat-att__remove"
                        aria-label={`Remove ${a.name}`}
                        onClick={() => removeAttachment(i)}
                      >
                        x
                      </button>
                    </span>
                  ))}
                </div>
              )}
              <textarea
                ref={inputRef}
                className="chat__input"
                placeholder="Message the orchestrator..."
                value={input}
                rows={2}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onComposerKey}
              />
              <div className="chat__hint">
                Shift+Enter for a new line.
                {dictation.listening && (
                  <span className="chat__listening" role="status">
                    Listening... speak now.
                  </span>
                )}
              </div>
              {attachError && (
                <p className="error" role="alert">
                  {attachError}
                </p>
              )}
              {dictation.error && (
                <p className="error" role="alert">
                  {dictation.error}
                </p>
              )}
            </div>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="chat__fileinput"
              style={{ display: "none" }}
              onChange={(e) => void addFiles(e.target.files)}
            />
            <button
              type="button"
              className="btn btn--ghost"
              disabled={streaming || attachments.length >= MAX_ATTACHMENTS}
              onClick={() => fileInputRef.current?.click()}
              title={`Attach files (max ${MAX_ATTACHMENTS}, ${formatBytes(
                MAX_ATTACHMENT_BYTES,
              )} each)`}
            >
              Attach
            </button>
            {dictation.supported && (
              <button
                type="button"
                className={`btn btn--ghost chat__mic ${
                  dictation.listening ? "chat__mic--on" : ""
                }`}
                aria-pressed={dictation.listening}
                disabled={streaming}
                onClick={() => {
                  if (dictation.listening) {
                    dictation.stop();
                    return;
                  }
                  dictationBaseRef.current = input;
                  dictation.start();
                }}
                title={
                  dictation.listening
                    ? "Stop dictation"
                    : "Dictate your message (speech to text)"
                }
              >
                {dictation.listening ? "Listening" : "Speak"}
              </button>
            )}
            {streaming ? (
              <button className="btn" onClick={() => void stopTurn()}>
                Stop
              </button>
            ) : (
              <button
                className="btn btn--primary"
                disabled={input.trim().length === 0 && attachments.length === 0}
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
