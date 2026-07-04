// US-CONV-01..04, US-CONV-07: the conversational chat surface. A left rail
// lists conversations (GET /v1/conversations); selecting one loads its
// transcript (GET /v1/conversations/{id}). Sending a message streams the
// response from POST /v1/chat (SSE) and renders text, dimmed reasoning, tool
// cards, sub-agent cards and inline HITL as the events arrive. The
// conversation_id is threaded into each send (omitted to start a new one; the
// first message_start returns the new id, which we capture).

import {
  Children,
  Fragment,
  isValidElement,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
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
import { useIdentity } from "../identity";
import { navigate, openRun } from "../router";
import { loadAppearance, saveAppearanceLocal } from "../appearance";
import {
  loadReadAloud,
  saveReadAloud,
  useDictation,
  useSpeech,
  type Speech,
} from "../voice";
import { TurnExtras, normalizeEvents, type NormalizedTurn } from "./chatTurn";
import { apiReason, cleanTaskText } from "./shared";
import { ArmConfirm, Skeleton } from "./uxFlow";

// The turn normaliser and renderer (tool / sub-agent / inline-HITL cards) live
// in chatTurn.tsx so the Run drawer reuses the exact same rendering.

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

type ChatTab = "chat" | "activity";

interface ChatAgent {
  id: string;
  name: string;
  role: string;
  initials: string;
  color: string;
  dept: string;
  status: "active" | "idle" | "offline";
  snippet: string;
  time: string;
  tier: 1 | 2;
  unread?: number;
  history: Array<{ id: string; title: string; time: string }>;
}

const CHAT_AGENTS: ChatAgent[] = [
  {
    id: "bolt",
    name: "Bolt",
    role: "Chief of Staff",
    initials: "B",
    color: "#3DD3F0",
    dept: "Org-wide",
    status: "active",
    snippet: "All departments green. 3 runs today.",
    time: "now",
    tier: 1,
    history: [
      { id: "h-release", title: "Push the 2.14 release", time: "now" },
      { id: "h-weekly", title: "Weekly status check", time: "yesterday" },
      { id: "h-adapter", title: "Onboard new adapter", time: "3d ago" },
    ],
  },
  {
    id: "head-eng",
    name: "Head of Engineering",
    role: "Engineering lead",
    initials: "E",
    color: "#5E69DD",
    dept: "Engineering",
    status: "active",
    snippet: "Release 2.14 in progress",
    time: "12m",
    tier: 2,
    history: [
      { id: "h-deps", title: "Dependency risk review", time: "2h ago" },
      { id: "h-ci", title: "CI failure triage", time: "1d ago" },
    ],
  },
  {
    id: "head-sre",
    name: "Head of SRE",
    role: "Reliability lead",
    initials: "S",
    color: "#FF7A45",
    dept: "Site Reliability",
    status: "idle",
    snippet: "Monitoring nominal, 1 alert cleared",
    time: "31m",
    tier: 2,
    history: [
      { id: "h-latency", title: "Latency budget check", time: "4h ago" },
      { id: "h-backup", title: "Backup restore drill", time: "2d ago" },
    ],
  },
  {
    id: "head-support",
    name: "Head of Support",
    role: "Support lead",
    initials: "H",
    color: "#7C8BFF",
    dept: "Support",
    status: "idle",
    snippet: "Ticket queue clear",
    time: "44m",
    tier: 2,
    unread: 1,
    history: [
      { id: "h-refunds", title: "Refund exception review", time: "1h ago" },
      { id: "h-sla", title: "SLA summary", time: "yesterday" },
    ],
  },
];

const GREETINGS = {
  morning: [
    "Morning",
    "Good morning",
    "Ready when you are",
    "What should we move first",
    "Where do we start",
  ],
  afternoon: [
    "Afternoon",
    "Still with you",
    "What needs attention",
    "What should we pick up",
    "Next move",
  ],
  evening: [
    "Evening",
    "Late run",
    "Still on deck",
    "What should finish tonight",
    "Quiet room, clear signal",
  ],
} as const;

function greetingFor(subject: string): ReactNode {
  const hour = new Date().getHours();
  const bucket = hour < 12 ? "morning" : hour < 17 ? "afternoon" : "evening";
  const list = GREETINGS[bucket];
  const msg = list[Math.floor((Date.now() / 60000) % list.length)];
  const name = subject || "there";
  return (
    <>
      {msg}, <span>{name}</span>.
    </>
  );
}

function Icon({
  name,
  size = 18,
}: {
  name:
    | "panel"
    | "search"
    | "plus"
    | "file"
    | "phone"
    | "moon"
    | "sun"
    | "mic"
    | "send"
    | "wave"
    | "x"
    | "chevDown"
    | "chevLeft"
    | "chevRight"
    | "copy"
    | "refresh"
    | "download"
    | "paperclip"
    | "speaker";
  size?: number;
}) {
  const common = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
  if (name === "panel") return <svg {...common}><path d="M4 5h16v14H4z" /><path d="M9 5v14" /></svg>;
  if (name === "search") return <svg {...common}><circle cx="11" cy="11" r="6" /><path d="m16 16 4 4" /></svg>;
  if (name === "plus") return <svg {...common}><path d="M12 5v14M5 12h14" /></svg>;
  if (name === "file") return <svg {...common}><path d="M7 3h7l4 4v14H7z" /><path d="M14 3v5h5" /></svg>;
  if (name === "phone") return <svg {...common}><path d="M6.6 4.8 9 4l2.1 4-1.5 1.1c1.1 2.2 2.9 4 5.1 5.1l1.1-1.5 4 2.1-.8 2.4c-.4 1.2-1.6 1.9-2.8 1.6C10.8 17.7 6.3 13.2 5.2 7.8 4.9 6.6 5.5 5.2 6.6 4.8Z" /></svg>;
  if (name === "moon") return <svg {...common}><path d="M20 15.5A8 8 0 0 1 8.5 4 7 7 0 1 0 20 15.5Z" /></svg>;
  if (name === "sun") return <svg {...common}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" /></svg>;
  if (name === "mic") return <svg {...common}><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>;
  if (name === "send") return <svg {...common}><path d="M12 19V5M6 11l6-6 6 6" /></svg>;
  if (name === "wave") return <svg {...common}><path d="M6 14v-4M10 17V7M14 15V9M18 13v-2" /></svg>;
  if (name === "x") return <svg {...common}><path d="M6 6l12 12M18 6 6 18" /></svg>;
  if (name === "chevDown") return <svg {...common}><path d="m7 10 5 5 5-5" /></svg>;
  if (name === "chevLeft") return <svg {...common}><path d="m15 18-6-6 6-6" /></svg>;
  if (name === "chevRight") return <svg {...common}><path d="m9 18 6-6-6-6" /></svg>;
  if (name === "copy") return <svg {...common}><rect x="8" y="8" width="11" height="11" rx="2" /><path d="M5 15V5h10" /></svg>;
  if (name === "refresh") return <svg {...common}><path d="M20 12a8 8 0 0 1-14 5M4 12a8 8 0 0 1 14-5" /><path d="M18 3v4h-4M6 21v-4h4" /></svg>;
  if (name === "paperclip") return <svg {...common}><path d="M16.5 6.5 8.5 14.5a2.5 2.5 0 0 0 3.5 3.5l8.5-8.5a4.5 4.5 0 0 0-6.36-6.36l-9.5 9.5a6.5 6.5 0 0 0 9.19 9.19l9.25-9.25" /></svg>;
  if (name === "speaker") return <svg {...common}><path d="M11 5 6 9H2v6h4l5 4V5z" /><path d="M15.5 8.5a5 5 0 0 1 0 7" /><path d="M19.5 4.5a10 10 0 0 1 0 15" /></svg>;
  return <svg {...common}><path d="M12 4v12" /><path d="m7 11 5 5 5-5" /><path d="M5 20h14" /></svg>;
}

function AgentAvatar({
  agent,
  size = 32,
  status = true,
}: {
  agent: ChatAgent;
  size?: number;
  status?: boolean;
}) {
  return (
    <span
      className="agent-avatar"
      style={{ "--agent-color": agent.color, width: size, height: size } as CSSProperties}
      aria-hidden="true"
    >
      {agent.initials}
      {status && <span className={`agent-avatar__status agent-avatar__status--${agent.status}`} />}
    </span>
  );
}

function statusColor(status: "active" | "idle" | "offline"): string {
  if (status === "active") return "#3FB984";
  if (status === "idle") return "#F0C059";
  return "#7E95B0";
}

function MeshCanvas({ active }: { active: boolean }) {
  const ref = useRef<HTMLCanvasElement | null>(null);
  useEffect(() => {
    if (!active) return;
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    let frame = 0;
    let raf = 0;
    const colors = [
      [61, 211, 240],
      [30, 180, 220],
      [94, 105, 221],
      [124, 139, 255],
      [63, 185, 132],
      [61, 240, 200],
      [30, 46, 70],
    ];
    const draw = () => {
      const rect = canvas.getBoundingClientRect();
      const w = Math.max(1, Math.floor(rect.width * 0.5));
      const h = Math.max(1, Math.floor(rect.height * 0.5));
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
      }
      ctx.clearRect(0, 0, w, h);
      colors.forEach((c, i) => {
        const t = frame * 0.002 + i * 1.7;
        const x = w * (0.25 + 0.5 * ((Math.sin(t) + 1) / 2));
        const y = h * (0.22 + 0.56 * ((Math.cos(t * 0.83) + 1) / 2));
        const r = w * (0.18 + 0.05 * (i % 3));
        const g = ctx.createRadialGradient(x, y, 0, x, y, r);
        g.addColorStop(0, `rgba(${c[0]},${c[1]},${c[2]},0.40)`);
        g.addColorStop(1, `rgba(${c[0]},${c[1]},${c[2]},0)`);
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, w, h);
      });
      frame += 1;
      raf = window.requestAnimationFrame(draw);
    };
    raf = window.requestAnimationFrame(draw);
    return () => window.cancelAnimationFrame(raf);
  }, [active]);
  return <canvas ref={ref} className="chat-mesh" aria-hidden="true" />;
}

function AgentHoverCard({ agent }: { agent: ChatAgent }) {
  const dot = statusColor(agent.status);
  return (
    <div className="agent-card" role="status">
      <div className="agent-card__head">
        <AgentAvatar agent={agent} size={40} />
        <div>
          <strong>{agent.name}</strong>
          <span>{agent.dept}</span>
        </div>
        <span
          className={`agent-card__status-dot agent-card__status-dot--${agent.status}`}
          style={{
            width: 8,
            height: 8,
            borderRadius: 9999,
            background: dot,
            boxShadow: `0 0 8px ${dot}`,
          }}
          aria-label={agent.status}
        />
      </div>
      <div className="agent-card__org" aria-label="Agent position">
        {agent.tier === 2 && (
          <>
            <div className="agent-card__node agent-card__node--parent">
              <span>B</span>
              <p>Bolt</p>
            </div>
            <svg
              className="agent-card__connector"
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <line x1="12" y1="0" x2="12" y2="18" />
              <polygon points="12,24 8,18 16,18" fill="currentColor" stroke="none" />
            </svg>
          </>
        )}
        <div className="agent-card__node agent-card__node--current">
          <span style={{ background: agent.color }}>{agent.initials}</span>
          <p>{agent.name}</p>
        </div>
        {agent.id === "bolt" && (
          <>
            <svg
              className="agent-card__connector"
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <line x1="12" y1="0" x2="12" y2="18" />
              <polygon points="12,24 8,18 16,18" fill="currentColor" stroke="none" />
            </svg>
            <div className="agent-card__children">
              {CHAT_AGENTS.filter((a) => a.tier === 2).map((child) => (
                <div className="agent-card__node" key={child.id}>
                  <span style={{ background: child.color }}>{child.initials}</span>
                  <p>{child.name.replace("Head of ", "")}</p>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
      <div className="agent-card__meta">
        <code>runtime pi</code>
        <code>glm-5.2</code>
        <code>{agent.tier === 1 ? 12 : 6} skills</code>
      </div>
    </div>
  );
}

function ChatAgentSidebar({
  open,
  agents,
  activeAgent,
  railItems,
  railTerm,
  railState,
  onNew,
  onSelectAgent,
  onSelectConversation,
  onDeleted,
  onRenamed,
  loadMore,
  onRailTerm,
}: {
  open: boolean;
  agents: ChatAgent[];
  activeAgent: ChatAgent;
  railItems: ConversationSearchResult[];
  railTerm: string;
  railState: RailState;
  onNew: () => void;
  onSelectAgent: (agent: ChatAgent) => void;
  onSelectConversation: (id: string) => void;
  onDeleted: (id: string) => void;
  onRenamed: () => void;
  loadMore: () => void;
  onRailTerm: (term: string) => void;
}) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({ bolt: true });
  const [searchOpen, setSearchOpen] = useState(false);
  if (!open) return null;
  return (
    <aside className="chat-agent-rail" aria-label="Chat agents">
      <div className="chat-agent-rail__head">
        <strong>Chat</strong>
        <div className="chat-agent-rail__tools">
          <button
            className={`icon-btn ${searchOpen ? "icon-btn--active" : ""}`}
            title="Search conversations"
            type="button"
            aria-pressed={searchOpen}
            onClick={() => setSearchOpen((v) => !v)}
          >
            <Icon name="search" size={15} />
          </button>
          <button className="icon-btn" title="New chat" type="button" onClick={onNew}>
            <Icon name="plus" size={15} />
          </button>
        </div>
      </div>
      {searchOpen && (
        <div className="chat-agent-rail__search">
          <input
            type="text"
            value={railTerm}
            placeholder="Search conversations..."
            aria-label="Search conversations"
            onChange={(e) => onRailTerm(e.target.value)}
          />
        </div>
      )}
      <div className="chat-agent-rail__filters" role="tablist" aria-label="Chat filters">
        <button className="chat-agent-rail__filter chat-agent-rail__filter--active" type="button">
          All
        </button>
        <button className="chat-agent-rail__filter" type="button">
          Unread
        </button>
      </div>
      <div className="chat-agent-list">
        {agents.map((agent) => {
          const isOpen = Boolean(expanded[agent.id]);
          const isActive = agent.id === activeAgent.id;
          return (
            <div className="chat-agent-group" key={agent.id}>
              <button
                type="button"
                className={`chat-agent-row ${isActive ? "chat-agent-row--active" : ""}`}
                onClick={() => onSelectAgent(agent)}
              >
                <span
                  className={`chat-agent-row__chev ${isOpen ? "chat-agent-row__chev--open" : ""}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    setExpanded((prev) => ({ ...prev, [agent.id]: !isOpen }));
                  }}
                >
                  <Icon name="chevRight" size={13} />
                </span>
                <AgentAvatar agent={agent} />
                <span className="chat-agent-row__copy">
                  <strong>{agent.name}</strong>
                  <span>{agent.snippet}</span>
                </span>
                {agent.unread && <span className="chat-agent-row__badge">{agent.unread}</span>}
              </button>
              {isOpen && (
                <div className="chat-agent-history">
                  {agent.id === "bolt" && (
                    <>
                      {railState.loading && railItems.length === 0 && <Skeleton variant="rows" count={3} />}
                      {!railState.loading && railItems.length === 0 && (
                        <p className="chat-agent-history__empty">
                          {railState.mode === "search" ? "No matches" : "No conversations yet."}
                        </p>
                      )}
                      {railItems.map((c) => (
                        <ConversationRow
                          key={c.id}
                          conversation={c}
                          active={false}
                          highlight={railTerm}
                          onSelect={() => onSelectConversation(c.id)}
                          onDeleted={() => onDeleted(c.id)}
                          onRenamed={onRenamed}
                        />
                      ))}
                      {railState.nextOffset !== null && (
                        <button
                          type="button"
                          className="chat-agent-history__more"
                          disabled={railState.loadingMore}
                          onClick={loadMore}
                        >
                          {railState.loadingMore ? "Loading..." : "Load more"}
                        </button>
                      )}
                    </>
                  )}
                  {agent.id !== "bolt" &&
                    agent.history.map((h) => (
                      <button
                        type="button"
                        className="chat-agent-history__item"
                        key={h.id}
                        onClick={() => onSelectAgent(agent)}
                      >
                        <span>{h.title}</span>
                        <time>{h.time}</time>
                      </button>
                    ))}
                  <button className="chat-agent-history__new" type="button" onClick={onNew}>
                    <Icon name="plus" size={12} />
                    New chat
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </aside>
  );
}

function EmptyChatStart({
  activeAgent,
  onPrev,
  onNext,
  switchDir,
  switchCount,
  userName,
}: {
  activeAgent: ChatAgent;
  onPrev: () => void;
  onNext: () => void;
  switchDir: "left" | "right" | "";
  switchCount: number;
  userName: string;
}) {
  const anim = switchDir ? `agent-switcher__profile--${switchDir}-${switchCount % 2 ? "a" : "b"}` : "";
  return (
    <div className="chat-empty-v3">
      <MeshCanvas active />
      <div className="chat-empty-v3__content">
        <h1>{greetingFor(userName)}</h1>
        <div className="agent-switcher" aria-label="Choose agent">
          <button className="agent-switcher__arrow" type="button" onClick={onPrev} aria-label="Previous agent">
            <Icon name="chevLeft" size={18} />
          </button>
          <div className={`agent-switcher__profile ${anim}`}>
            <strong style={{ color: activeAgent.color }}>{activeAgent.name}</strong>
            <span>{activeAgent.role}</span>
          </div>
          <button className="agent-switcher__arrow" type="button" onClick={onNext} aria-label="Next agent">
            <Icon name="chevRight" size={18} />
          </button>
        </div>
      </div>
    </div>
  );
}

function fileExtClass(name: string): string {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  const safe = ext.replace(/[^a-z0-9]/g, "");
  return safe ? `file-row--${safe}` : "";
}

function FilesPanel({
  attachments,
  messages,
  onClose,
}: {
  attachments: ChatAttachment[];
  messages: ChatMessage[];
  onClose: () => void;
}) {
  const sessionFiles = [
    ...attachments.map((a) => ({
      name: a.name,
      size: a.size ?? 0,
      meta: `${formatBytes(a.size ?? 0)} - pending - now`,
      type: a.media_type,
    })),
    ...messages.flatMap((m) =>
      (m.attachments ?? []).map((a) => ({
        name: a.name,
        size: a.size ?? 0,
        meta: `${formatBytes(a.size ?? 0)} - ${m.role} - ${whenText(m.created_at)}`,
        type: a.media_type,
      })),
    ),
  ];
  const rows = sessionFiles;
  const totalSize = rows.reduce((sum, f) => sum + f.size, 0);
  const FileRow = ({
    file,
    dim,
    downloadable = true,
  }: {
    file: { name: string; size: number; meta: string; type: string };
    dim?: boolean;
    downloadable?: boolean;
  }) => (
    <div className={`file-row ${fileExtClass(file.name)} ${dim ? "file-row--dim" : ""}`}>
      <span className="file-row__icon"><Icon name="file" size={15} /></span>
      <span className="file-row__copy">
        <strong>{file.name}</strong>
        <small>{file.meta}</small>
      </span>
      {downloadable && (
        <button className="icon-btn" type="button" aria-label={`Download ${file.name}`}>
          <Icon name="download" size={14} />
        </button>
      )}
    </div>
  );
  return (
    <aside className="files-panel" aria-label="Files">
      <header className="files-panel__head">
        <strong>Files</strong>
        <button className="btn btn--ghost btn--sm" type="button">
          <Icon name="plus" size={13} />
          Upload
        </button>
        <button className="icon-btn" type="button" onClick={onClose} aria-label="Close files">
          <Icon name="x" size={15} />
        </button>
      </header>
      <input className="files-panel__search" placeholder="Search files" aria-label="Search files" />
      <div className="files-panel__body">
        <span className="files-panel__section">This session</span>
        {rows.length === 0 && (
          <p className="files-panel__empty">No files attached to this conversation.</p>
        )}
        {rows.map((file) => <FileRow file={file} key={`${file.name}-${file.meta}`} />)}
      </div>
      <footer className="files-panel__foot">
        <span>{rows.length} files · {formatBytes(totalSize)}</span>
      </footer>
    </aside>
  );
}

function VoiceOverlay({
  agent,
  seconds,
  muted,
  speaker,
  onMute,
  onSpeaker,
  onEnd,
}: {
  agent: ChatAgent;
  seconds: number;
  muted: boolean;
  speaker: boolean;
  onMute: () => void;
  onSpeaker: () => void;
  onEnd: () => void;
}) {
  const mm = String(Math.floor(seconds / 60)).padStart(2, "0");
  const ss = String(seconds % 60).padStart(2, "0");
  return (
    <div className="voice-overlay" role="dialog" aria-modal="true" aria-label="Voice call">
      <div className="voice-card">
        <div className="voice-card__mic">
          <span />
          <span />
          <Icon name="mic" size={28} />
        </div>
        <h2>Voice call active</h2>
        <p>
          {agent.name} - governed by the same kernel policy
        </p>
        <code>{mm}:{ss}</code>
        <div className="voice-card__transcript" aria-label="Live transcript">
          <p><strong>You</strong> Review the release run.</p>
          <p><strong>{agent.name}</strong> Reading the active transcript and receipts.</p>
        </div>
        <div className="voice-card__controls">
          <button className={muted ? "voice-card__toggle voice-card__toggle--off" : "voice-card__toggle"} onClick={onMute} type="button">
            Mute
          </button>
          <button className="voice-card__end" onClick={onEnd} type="button" aria-label="End call">
            <Icon name="phone" size={22} />
          </button>
          <button className={speaker ? "voice-card__toggle voice-card__toggle--on" : "voice-card__toggle"} onClick={onSpeaker} type="button">
            Speaker
          </button>
        </div>
      </div>
    </div>
  );
}

interface ActivityNode {
  key: string;
  label: string;
  detail: string;
  time: string;
  tone: string;
  runId?: string;
  badge?: string;
  children?: ActivityNode[];
}

function toolTone(status: string): string {
  if (status === "ok") return "#3FB984";
  if (status === "pending" || status === "running") return "#3DD3F0";
  return "#F0654A";
}

function ActivityTimeline({
  messages,
  live,
  activeAgent,
  onOpenRun,
}: {
  messages: ChatMessage[];
  live: NormalizedTurn;
  activeAgent: ChatAgent;
  onOpenRun: (runId: string) => void;
}) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({
    live: true,
  });
  const nodes: ActivityNode[] = [
    {
      key: "session",
      label: "Session start",
      detail: `Conversation with ${activeAgent.name}`,
      time: "now",
      tone: activeAgent.color,
      badge: "session",
    },
  ];
  messages.forEach((message) => {
    const turn = normalizeEvents(message.events ?? []);
    if (message.role === "assistant") {
      const children: ActivityNode[] = [
        ...turn.tools.map((tool) => ({
          key: `${message.id}-${tool.key}`,
          label: toolLabel(tool.verb),
          detail: `${tool.verb} - ${tool.status}`,
          time: whenText(message.created_at),
          tone: toolTone(tool.status),
          badge: "tool",
        })),
        ...turn.steps.map((step) => ({
          key: `${message.id}-${step.stepId}`,
          label: step.action,
          detail: step.status,
          time: whenText(message.created_at),
          tone: toolTone(step.status),
          badge: "step",
        })),
        ...turn.subagents.map((sub) => ({
          key: `${message.id}-${sub.key}`,
          label: "Delegation",
          detail: cleanTaskText(sub.task),
          time: whenText(message.created_at),
          tone: "#5E69DD",
          runId: sub.childRunId,
          badge: "handoff",
          children: sub.skills.map((skill, i) => ({
            key: `${message.id}-${sub.key}-skill-${i}`,
            label: "Skill loaded",
            detail: skill,
            time: whenText(message.created_at),
            tone: "#7E95B0",
            badge: "ephemeral",
          })),
        })),
      ];
      nodes.push({
        key: message.id,
        label: "Agent response",
        detail: message.content ? message.content.slice(0, 120) : "Structured response",
        time: whenText(message.created_at),
        tone: activeAgent.color,
        runId: message.run_id ?? turn.runId,
        badge: "agent",
        children,
      });
    }
  });
  if (live.runId || live.tools.length > 0 || live.subagents.length > 0) {
    nodes.push({
      key: "live",
      label: live.ended ? "Run complete" : "Agent action",
      detail: live.text || live.reasoning || "Streaming execution events",
      time: "live",
      tone: activeAgent.color,
      runId: live.runId,
      badge: live.ended ? "complete" : "agent",
      children: [
        ...live.tools.map((tool) => ({
          key: `live-${tool.key}`,
          label: toolLabel(tool.verb),
          detail: `${tool.verb} - ${tool.status}`,
          time: "live",
          tone: toolTone(tool.status),
          badge: "tool",
        })),
        ...live.subagents.map((sub) => ({
          key: `live-${sub.key}`,
          label: "Delegation",
          detail: cleanTaskText(sub.task),
          time: "live",
          tone: "#5E69DD",
          runId: sub.childRunId,
          badge: "handoff",
          children: sub.skills.map((skill, i) => ({
            key: `live-${sub.key}-skill-${i}`,
            label: "Skill loaded",
            detail: skill,
            time: "live",
            tone: "#7E95B0",
            badge: "ephemeral",
          })),
        })),
      ],
    });
  }
  if (nodes.length === 1) {
    nodes.push({
      key: "pending",
      label: "Waiting for first instruction",
      detail: "Activity appears here as the agent plans, delegates and calls tools.",
      time: "pending",
      tone: "#3DD3F0",
      badge: "pending",
    });
  }
  const toggle = (key: string) => {
    setExpanded((current) => ({ ...current, [key]: !current[key] }));
  };
  const renderNode = (node: ActivityNode, depth = 0, index = 0, total = 1): ReactNode => {
    const hasChildren = Boolean(node.children?.length);
    const isExpanded = expanded[node.key] ?? depth < 1;
    return (
      <Fragment key={node.key}>
        <button
          type="button"
          className={`activity-row ${hasChildren ? "activity-row--expandable" : ""}`}
          style={{ "--activity-color": node.tone, "--depth": depth } as CSSProperties}
          aria-expanded={hasChildren ? isExpanded : undefined}
          onClick={() => {
            if (hasChildren) toggle(node.key);
            if (node.runId) onOpenRun(node.runId);
          }}
        >
          <span className="activity-row__rail">
            <span />
            {(index < total - 1 || (hasChildren && isExpanded)) && <i />}
          </span>
          <span className="activity-row__body">
            <strong>
              {hasChildren && <Icon name={isExpanded ? "chevDown" : "chevRight"} size={12} />}
              {node.label}
            </strong>
            <small>{node.detail}</small>
          </span>
          {node.badge && <span className="activity-row__badge">{node.badge}</span>}
          <time className="activity-row__time">{node.time}</time>
        </button>
        {hasChildren && isExpanded && (
          <div className="activity-row__children">
            {node.children!.map((child, childIndex) =>
              renderNode(child, depth + 1, childIndex, node.children!.length),
            )}
          </div>
        )}
      </Fragment>
    );
  };
  return (
    <div className="activity-timeline">
      {nodes.map((node, index) => renderNode(node, 0, index, nodes.length))}
    </div>
  );
}

function toolLabel(verb: string): string {
  const clean = verb.replace(/^control\./, "").replace(/\./g, " ");
  return clean.charAt(0).toUpperCase() + clean.slice(1);
}

function FleetBar({
  live,
  activeAgent,
  onOpenRun,
}: {
  live: NormalizedTurn;
  activeAgent: ChatAgent;
  onOpenRun: (runId: string) => void;
}) {
  const WINDOW_SIZE = 4;
  const [offset, setOffset] = useState(0);
  const [focusIdx, setFocusIdx] = useState(0);
  const rows = [
    {
      id: live.runId ?? "bolt",
      name: activeAgent.name,
      role: activeAgent.role,
      color: activeAgent.color,
      initials: activeAgent.initials,
      elapsed: live.ended ? "done" : "00:00",
      phase: live.ended ? "complete" : "coordinating",
      cost: "$0.00",
      tools: live.tools.length,
      tier: activeAgent.tier,
    },
    ...live.subagents.map((sub, i) => ({
      id: sub.childRunId,
      name: `Worker ${i + 1}`,
      role: "ephemeral",
      color: ["#5E69DD", "#3FB984", "#FF7A45"][i % 3],
      initials: String(i + 1),
      elapsed: `00:${String(Math.min(59, 12 + i * 7)).padStart(2, "0")}`,
      phase: "executing",
      cost: "$0.00",
      tools: Math.max(1, sub.skills.length),
      tier: 3,
    })),
  ];
  if (!live.runId && live.tools.length === 0 && live.subagents.length === 0) return null;
  const maxOffset = Math.max(0, rows.length - WINDOW_SIZE);
  const clampedOffset = Math.min(offset, maxOffset);
  const visible = rows.slice(clampedOffset, clampedOffset + WINDOW_SIZE);
  const moveFocus = (next: number) => {
    const clamped = Math.max(0, Math.min(rows.length - 1, next));
    setFocusIdx(clamped);
    if (clamped < clampedOffset) setOffset(clamped);
    if (clamped >= clampedOffset + WINDOW_SIZE) setOffset(clamped - WINDOW_SIZE + 1);
  };
  return (
    <div
      className="fleet-bar"
      aria-label="Live fleet"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          moveFocus(focusIdx + 1);
        } else if (e.key === "ArrowUp") {
          e.preventDefault();
          moveFocus(focusIdx - 1);
        } else if (e.key === "Enter") {
          e.preventDefault();
          const row = rows[focusIdx];
          if (row?.id) onOpenRun(row.id);
        } else if (e.key === "Escape") {
          (e.currentTarget as HTMLDivElement).blur();
        }
      }}
    >
      {clampedOffset > 0 && (
        <button
          className="fleet-bar__nav"
          type="button"
          aria-label="Previous fleet rows"
          onClick={() => {
            setOffset((value) => Math.max(0, value - 1));
            moveFocus(Math.max(0, focusIdx - 1));
          }}
        >
          <Icon name="chevDown" size={14} />
        </button>
      )}
      <div className="fleet-bar__window">
        {visible.map((row, visibleIndex) => {
          const absoluteIndex = clampedOffset + visibleIndex;
          return (
            <button
              className={`fleet-row ${absoluteIndex === focusIdx ? "fleet-row--focus" : ""}`}
              type="button"
              key={row.id}
              onFocus={() => setFocusIdx(absoluteIndex)}
              onClick={() => row.id && onOpenRun(row.id)}
              style={{
                "--agent-color": row.color,
                gridTemplateColumns: "auto auto 1fr auto auto 56px 56px 70px auto",
              } as CSSProperties}
            >
              <span className="fleet-row__tree">{absoluteIndex === 0 ? " " : "└"}</span>
              <span className="fleet-row__avatar">{row.initials}</span>
              <strong>{row.name}</strong>
              <span
                className="fleet-row__status"
                aria-hidden="true"
                style={{ width: 6, height: 6, borderRadius: 9999, background: row.color }}
              />
              <em>{row.tier === 3 ? "ephemeral" : row.role}</em>
              <span>{row.elapsed}</span>
              <span>{row.cost}</span>
              <span>{row.tools} tool calls</span>
              <span>{row.phase}</span>
            </button>
          );
        })}
      </div>
      {clampedOffset < maxOffset && (
        <button
          className="fleet-bar__nav fleet-bar__nav--down"
          type="button"
          aria-label="Next fleet rows"
          onClick={() => {
            setOffset((value) => Math.min(maxOffset, value + 1));
            moveFocus(Math.min(rows.length - 1, focusIdx + 1));
          }}
        >
          <Icon name="chevDown" size={14} />
        </button>
      )}
    </div>
  );
}

function SubRunPanel({
  runId,
  full,
  agent,
  onClose,
  onFull,
  onCollapse,
}: {
  runId: string | null;
  full: boolean;
  agent: ChatAgent;
  onClose: () => void;
  onFull: () => void;
  onCollapse: () => void;
}) {
  const [events, setEvents] = useState<ChatEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!runId) return;
    let alive = true;
    const ctrl = new AbortController();
    setEvents([]);
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        await streamRunEvents(
          runId,
          (ev) => {
            if (!alive) return;
            setEvents((prev) => [...prev, ev]);
          },
          { signal: ctrl.signal, follow: false },
        );
        if (alive) setLoading(false);
      } catch (err) {
        if (!alive) return;
        setError(errText(err));
        setLoading(false);
      }
    })();
    return () => {
      alive = false;
      ctrl.abort();
    };
  }, [runId]);
  if (!runId) return null;
  return (
    <aside className={full ? "subrun-panel subrun-panel--full" : "subrun-panel"} aria-label="Sub-run">
      <header className="subrun-panel__head">
        <button className="icon-btn" type="button" onClick={onClose} aria-label="Close sub-run">
          <Icon name="x" size={15} />
        </button>
        <AgentAvatar agent={agent} size={20} />
        <span>
          <strong>{agent.name}</strong>
          <small>{agent.role}</small>
        </span>
        <span
          className={`subrun-panel__status subrun-panel__status--${agent.status}`}
          style={{ color: statusColor(agent.status) }}
        >
          {agent.status}
        </span>
        <button className="btn btn--ghost btn--sm" type="button" onClick={full ? onCollapse : onFull}>
          {full ? "Back" : "Expand"}
        </button>
        <button className="btn btn--ghost btn--sm" type="button" onClick={() => openRun(runId)}>
          Open run
        </button>
      </header>
      <div className="subrun-panel__body">
        {loading && <p className="muted subrun-panel__loading">Loading run events...</p>}
        {error && <p className="error subrun-panel__error">{error}</p>}
        {!loading && !error && events.length === 0 && (
          <div className="subrun-transcript">
            <p><strong>{agent.name}</strong> - {agent.role}</p>
            <p>Run {runId}</p>
            <p className="muted">Detailed run data is available in the run drawer.</p>
          </div>
        )}
        {events.map((ev, i) => {
          if (ev.type === "text_delta") {
            return <p key={i} className="subrun-line subrun-line--text">{ev.delta}</p>;
          }
          if (ev.type === "reasoning_delta") {
            return <p key={i} className="subrun-line subrun-line--reasoning">{ev.delta}</p>;
          }
          if (ev.type === "tool_call") {
            const verb = ev.verb || ev.tool || "tool";
            return (
              <div key={i} className="subrun-tool">
                <span className="tool-card__dot" />
                <span>{toolLabel(verb)}</span>
              </div>
            );
          }
          if (ev.type === "tool_result") {
            const verb = ev.verb || "tool";
            return (
              <div key={i} className="subrun-tool">
                <span className="tool-card__dot" />
                <span>{toolLabel(verb)} - {ev.status}</span>
              </div>
            );
          }
          if (ev.type === "subagent") {
            return (
              <div key={i} className="subrun-line subrun-line--sub">
                <strong>Sub-agent</strong>: {cleanTaskText(ev.task)}
              </div>
            );
          }
          return null;
        })}
      </div>
      <footer className="subrun-panel__composer">
        <input placeholder={`Steer ${agent.name}...`} />
        <button className="icon-btn" type="button"><Icon name="send" size={15} /></button>
      </footer>
    </aside>
  );
}

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
  iconOnly = false,
}: {
  text: string;
  label?: string;
  className?: string;
  iconOnly?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    const ok = await copyText(text);
    if (!ok) return;
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  }
  return (
    <button
      type="button"
      className={iconOnly ? `${className} chat-msg__action--icon` : className}
      aria-label={copied ? "Copied" : label}
      style={iconOnly ? { width: 26, height: 26 } : undefined}
      onClick={() => void copy()}
    >
      {iconOnly ? <Icon name="copy" size={16} /> : copied ? "Copied" : label}
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
function SpeakButton({
  speech,
  msgKey,
  text,
  iconOnly = false,
}: {
  speech: Speech;
  msgKey: string;
  text: string;
  iconOnly?: boolean;
}) {
  if (!speech.supported || !text.trim()) return null;
  const speaking = speech.speakingKey === msgKey;
  return (
    <button
      type="button"
      className={iconOnly ? "btn btn--ghost btn--sm chat-msg__action--icon" : "btn btn--ghost btn--sm"}
      aria-pressed={speaking}
      aria-label={speaking ? "Stop reading" : "Read aloud"}
      style={iconOnly ? { width: 26, height: 26 } : undefined}
      onClick={() => (speaking ? speech.cancel() : speech.speak(msgKey, text))}
    >
      {iconOnly ? <Icon name="speaker" size={16} /> : speaking ? "Stop" : "Read aloud"}
    </button>
  );
}

function MessageBubble({
  message,
  agent,
  resolvedHitls,
  onResolve,
  canRegenerate,
  regenerating,
  onRegenerate,
  onOpenRun,
  speech,
}: {
  message: ChatMessage;
  agent: ChatAgent;
  resolvedHitls: Record<string, string>;
  onResolve: (id: string, status: string) => void;
  canRegenerate: boolean;
  regenerating: boolean;
  onRegenerate: () => void;
  onOpenRun: (runId: string) => void;
  speech: Speech;
}) {
  const turn = useMemo(() => normalizeEvents(message.events ?? []), [message.events]);
  const isAssistant = message.role === "assistant";
  const superseded = Boolean(message.superseded_by);

  const body = (
    <>
      {isAssistant && (
        <TurnExtras
          turn={turn}
          resolvedHitls={resolvedHitls}
          onResolve={onResolve}
          onOpenRun={onOpenRun}
        />
      )}
      {message.content && <MarkdownText value={message.content} />}
      <AttachmentList attachments={message.attachments} />
      {!isAssistant && (
        <span className="chat-msg__time chat-msg__time--bubble" title={message.created_at}>
          {whenText(message.created_at)}
        </span>
      )}
      <div className="chat-msg__meta">
        {message.content && (
          <CopyButton text={message.content} label="Copy" className="chat-msg__action" iconOnly />
        )}
        {isAssistant && message.content && (
          <SpeakButton speech={speech} msgKey={message.id} text={message.content} iconOnly />
        )}
        {canRegenerate && (
          <button
            type="button"
            className="chat-msg__action chat-msg__action--icon"
            aria-label="Regenerate"
            disabled={regenerating}
            style={{ width: 26, height: 26 }}
            onClick={onRegenerate}
          >
            <Icon name="refresh" size={16} />
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
      {isAssistant ? (
        <div className="chat-msg__head">
          <AgentAvatar agent={agent} size={22} status={false} />
          <span className="chat-msg__role">{agent.name}</span>
          <span className="chat-msg__time" title={message.created_at}>{whenText(message.created_at)}</span>
        </div>
      ) : null}
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
  const identity = useIdentity();

  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [msgsLoading, setMsgsLoading] = useState(false);
  const [msgsError, setMsgsError] = useState<string | null>(null);

  // The conversation rail: paginated list + debounced search over the same rail.
  const [railTerm, setRailTerm] = useState("");
  const rail = useConversationRail(railTerm);
  const [input, setInput] = useState("");
  const [pendingUser, setPendingUser] = useState<string | null>(null);
  const [liveEvents, setLiveEvents] = useState<ChatEvent[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [stopped, setStopped] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [resolvedHitls, setResolvedHitls] = useState<Record<string, string>>({});
  const [showJump, setShowJump] = useState(false);
  const [chatSidebarOpen, setChatSidebarOpen] = useState(false);
  const [chatSearchOpen, setChatSearchOpen] = useState(false);
  const [chatSearchTerm, setChatSearchTerm] = useState("");
  const [theme, setTheme] = useState(loadAppearance().theme);
  const [selectedAgentId, setSelectedAgentId] = useState("bolt");
  const [chatTab, setChatTab] = useState<ChatTab>("chat");
  const [rightPanel, setRightPanel] = useState<"files" | null>(null);
  const [plusOpen, setPlusOpen] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [clearIndex, setClearIndex] = useState<number | null>(null);
  const [compacted, setCompacted] = useState(false);
  const [slashIdx, setSlashIdx] = useState(0);
  const [switchDir, setSwitchDir] = useState<"left" | "right" | "">("");
  const [switchCount, setSwitchCount] = useState(0);
  const [inCall, setInCall] = useState(false);
  const [callMuted, setCallMuted] = useState(false);
  const [callSpeaker, setCallSpeaker] = useState(true);
  const [callSeconds, setCallSeconds] = useState(0);
  const [subRunId, setSubRunId] = useState<string | null>(null);
  const [subRunFull, setSubRunFull] = useState(false);

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

  function toggleTheme() {
    const current = loadAppearance();
    const nextTheme = current.theme === "dark" ? "light" : current.theme === "light" ? "system" : "dark";
    saveAppearanceLocal({ ...current, theme: nextTheme });
    setTheme(nextTheme);
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

  const selectedAgent = useMemo(
    () => CHAT_AGENTS.find((a) => a.id === selectedAgentId) ?? CHAT_AGENTS[0],
    [selectedAgentId],
  );

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
    if (!inCall) return;
    const timer = window.setInterval(() => setCallSeconds((s) => s + 1), 1000);
    return () => window.clearInterval(timer);
  }, [inCall]);

  useEffect(() => {
    if (activeId || messages.length > 0 || pendingUser !== null) return;
    const handler = (e: KeyboardEvent) => {
      if (document.activeElement && ["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) return;
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        cycleAgent("left");
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        cycleAgent("right");
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [activeId, messages.length, pendingUser, selectedAgentId]);

  useEffect(() => {
    const el = messagesRef.current;
    if (!el) return;
    if (pinnedRef.current) {
      el.scrollTop = el.scrollHeight;
      setShowJump(false);
    } else {
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
    setChatTab("chat");
    setSelectedAgentId("bolt");
    setClearIndex(null);
    setCompacted(false);
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
    setChatTab("chat");
    setClearIndex(null);
    setCompacted(false);
    setRightPanel(null);
    setSubRunId(null);
    setActiveId(null);
    setMessages([]);
  }

  function cycleAgent(dir: "left" | "right") {
    const idx = CHAT_AGENTS.findIndex((a) => a.id === selectedAgentId);
    const next =
      dir === "left"
        ? (idx - 1 + CHAT_AGENTS.length) % CHAT_AGENTS.length
        : (idx + 1) % CHAT_AGENTS.length;
    setSelectedAgentId(CHAT_AGENTS[next].id);
    setSwitchDir(dir);
    setSwitchCount((n) => n + 1);
  }

  function executeSlash(kind: "clear" | "compact") {
    if (kind === "clear") {
      setClearIndex(messages.length);
      setInput("");
      setSlashIdx(0);
      return;
    }
    setCompacted(true);
    setInput("");
    setSlashIdx(0);
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
    if (input.trim().startsWith("/")) {
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSlashIdx((i) => Math.max(0, i - 1));
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSlashIdx((i) => Math.min(1, i + 1));
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setInput("");
        setSlashIdx(0);
        return;
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        executeSlash(slashIdx === 0 ? "clear" : "compact");
        return;
      }
    }
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
  const showLive = streaming || liveEvents.length > 0 || streamError !== null;
  const isEmpty =
    !msgsLoading &&
    !msgsError &&
    messages.length === 0 &&
    pendingUser === null &&
    !showLive;
  const compactedCount = compacted && messages.length > 4 ? messages.length - 4 : 0;
  const displayedMessages = compactedCount > 0 ? messages.slice(-4) : messages;
  const visibleMessages = chatSearchTerm.trim()
    ? displayedMessages.filter((m) =>
        (m.content ?? "").toLowerCase().includes(chatSearchTerm.toLowerCase())
      )
    : displayedMessages;
  const firstVisibleIndex = compactedCount > 0 ? compactedCount : 0;
  const slashOpen = input.trim().startsWith("/");
  const contextRemaining = Math.max(
    4,
    128 - Math.ceil((messages.map((m) => m.content).join(" ").length + input.length) / 1000),
  );

  return (
    <section
      className={`panel chat chat-v3 ${chatSidebarOpen ? "chat-v3--rail-open" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={(e) => {
        if (e.currentTarget === e.target) setDragOver(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        void addFiles(e.dataTransfer.files);
      }}
    >
      <ChatAgentSidebar
        open={chatSidebarOpen}
        agents={CHAT_AGENTS}
        activeAgent={selectedAgent}
        railItems={railItems}
        railTerm={railTerm}
        railState={rail.state}
        onRailTerm={setRailTerm}
        onNew={newConversation}
        onSelectAgent={(agent) => {
          setSelectedAgentId(agent.id);
          setChatTab("chat");
        }}
        onSelectConversation={selectConversation}
        onDeleted={(id) => {
          if (id === activeId) newConversation();
          rail.reload();
        }}
        onRenamed={() => rail.reload()}
        loadMore={() => void rail.loadMore()}
      />

      <main className="chat-stage">
        <header className="chat-header">
          <button
            className="icon-btn chat-header__rail-toggle"
            type="button"
            aria-label="Toggle chat sidebar"
            aria-pressed={chatSidebarOpen}
            onClick={() => setChatSidebarOpen((open) => !open)}
          >
            <Icon name="panel" size={16} />
          </button>
          <div className="chat-header__agent">
            <div>
              <strong>
                {selectedAgent.name}
                <span
                  className="chat-header__status-dot"
                  style={{ background: statusColor(selectedAgent.status) }}
                  aria-label={`Status: ${selectedAgent.status}`}
                />
              </strong>
              <span>{selectedAgent.role}</span>
            </div>
            <AgentHoverCard agent={selectedAgent} />
          </div>
          <nav className="chat-tabs" aria-label="Chat tabs">
            <button
              type="button"
              className={chatTab === "chat" ? "chat-tabs__tab chat-tabs__tab--active" : "chat-tabs__tab"}
              onClick={() => setChatTab("chat")}
            >
              Chat
            </button>
            <button
              type="button"
              className={chatTab === "activity" ? "chat-tabs__tab chat-tabs__tab--active" : "chat-tabs__tab"}
              onClick={() => setChatTab("activity")}
            >
              Activity
            </button>
            <button
              className="chat-tabs__new"
              type="button"
              title="New chat"
              onClick={newConversation}
              style={{ width: 24, height: 24, marginLeft: 4 }}
            >
              <Icon name="plus" size={14} />
            </button>
          </nav>
          <div className="chat-header__spacer" />
          <button
            className="icon-btn chat-header__action"
            type="button"
            title="Files"
            aria-pressed={rightPanel === "files"}
            onClick={() => setRightPanel((p) => (p === "files" ? null : "files"))}
          >
            <Icon name="file" size={16} />
          </button>
          <button
            className="icon-btn chat-header__action"
            type="button"
            title="Voice call"
            onClick={() => {
              setCallSeconds(0);
              setInCall(true);
            }}
          >
            <Icon name="phone" size={16} />
          </button>
          <button
            className="icon-btn chat-header__action"
            type="button"
            title="Search"
            onClick={() => {
              setChatSearchOpen((open) => {
                if (open) setChatSearchTerm("");
                return !open;
              });
            }}
          >
            <Icon name="search" size={16} />
          </button>
          <button
            className="icon-btn chat-header__action"
            type="button"
            title="Theme"
            onClick={toggleTheme}
          >
            <Icon name={theme === "light" ? "sun" : "moon"} size={16} />
          </button>
        </header>

        {chatSearchOpen && (
          <div
            className="chat-header-search"
            style={{
              padding: "6px 20px",
              background: "rgba(8,14,26,0.92)",
              borderBottom: "1px solid rgba(255,255,255,0.04)",
            }}
          >
            <input
              className="chat-header-search__input"
              type="search"
              placeholder="Search this conversation..."
              aria-label="Search this conversation"
              value={chatSearchTerm}
              onChange={(e) => setChatSearchTerm(e.target.value)}
            />
          </div>
        )}

        {rightPanel === "files" && (
          <FilesPanel attachments={attachments} messages={messages} onClose={() => setRightPanel(null)} />
        )}
        <SubRunPanel
          runId={subRunId}
          full={subRunFull}
          agent={selectedAgent}
          onClose={() => {
            setSubRunId(null);
            setSubRunFull(false);
          }}
          onFull={() => setSubRunFull(true)}
          onCollapse={() => setSubRunFull(false)}
        />
        {inCall && (
          <VoiceOverlay
            agent={selectedAgent}
            seconds={callSeconds}
            muted={callMuted}
            speaker={callSpeaker}
            onMute={() => setCallMuted((m) => !m)}
            onSpeaker={() => setCallSpeaker((s) => !s)}
            onEnd={() => setInCall(false)}
          />
        )}
        {dragOver && (
          <div className="chat-drop" role="status">
            <Icon name="paperclip" size={40} />
            <strong>Drop files to attach</strong>
            <span>Up to {MAX_ATTACHMENTS} files, {formatBytes(MAX_ATTACHMENT_BYTES)} each</span>
          </div>
        )}

        {chatTab === "activity" ? (
          <div className="chat-stage__activity">
            <ActivityTimeline
              messages={messages}
              live={live}
              activeAgent={selectedAgent}
              onOpenRun={(runId) => setSubRunId(runId)}
            />
          </div>
        ) : (
          <div
            className="chat__messages"
            aria-live={slideActive ? "polite" : "off"}
            aria-busy={streaming}
            ref={messagesRef}
            onScroll={onMessagesScroll}
          >
            {msgsLoading && messages.length === 0 && (
              <p className="muted chat-statusline">Loading conversation...</p>
            )}
            {msgsError && <p className="error chat-statusline">Failed to load conversation: {msgsError}</p>}
            {isEmpty && (
              <EmptyChatStart
                activeAgent={selectedAgent}
                onPrev={() => cycleAgent("left")}
                onNext={() => cycleAgent("right")}
                switchDir={switchDir}
                switchCount={switchCount}
                userName={identity.subject}
              />
            )}
            {compactedCount > 0 && (
              <button className="chat-compact-line" type="button" onClick={() => setCompacted(false)}>
                {compactedCount} earlier messages, scroll to expand
              </button>
            )}
            {visibleMessages.map((m, i) => {
              const realIndex = firstVisibleIndex + i;
              return (
                <Fragment key={m.id}>
                  {clearIndex === realIndex && (
                    <div className="chat-clear-line">
                      <span>cleared, scroll up for history</span>
                    </div>
                  )}
                  <MessageBubble
                    message={m}
                    agent={selectedAgent}
                    resolvedHitls={resolvedHitls}
                    onResolve={resolveHitl}
                    canRegenerate={m.id === lastAssistantId && !streaming && pendingUser === null}
                    regenerating={regenerating === m.id}
                    onRegenerate={() => void regenerate(m.id)}
                    onOpenRun={(runId) => setSubRunId(runId)}
                    speech={speech}
                  />
                </Fragment>
              );
            })}
            {chatSearchTerm.trim() && visibleMessages.length === 0 && !msgsLoading && (
              <p className="muted chat-statusline">No matching messages.</p>
            )}

            {pendingUser !== null && (
              <div className="chat-msg chat-msg--user">
                <div className="chat-msg__bubble">
                  {pendingUser && <MarkdownText value={pendingUser} />}
                  <AttachmentList attachments={pendingAttachments} />
                  <div className="chat-msg__meta">
                    <span>sending</span>
                    {pendingUser && <CopyButton text={pendingUser} label="Copy" className="chat-msg__action" />}
                  </div>
                </div>
              </div>
            )}

            {showLive && (
              <div className="chat-msg chat-msg--assistant">
                <div className="chat-msg__head">
                  <AgentAvatar agent={selectedAgent} size={22} status={false} />
                  <span className="chat-msg__role">{selectedAgent.name}</span>
                  <span className="chat-msg__time">live</span>
                </div>
                <div className="chat-msg__bubble">
                  <TurnExtras
                    turn={live}
                    resolvedHitls={resolvedHitls}
                    onResolve={resolveHitl}
                    onOpenRun={(runId) => setSubRunId(runId)}
                  />
                  {live.text ? (
                    <MarkdownText value={live.text} />
                  ) : (
                    streaming && !live.reasoning && (
                      <div className="thinking-indicator" style={{ "--agent-color": selectedAgent.color } as CSSProperties}>
                        <AgentAvatar agent={selectedAgent} size={22} status={false} />
                        <span className="thinking-dot" style={{ animationDelay: "0s" }} />
                        <span className="thinking-dot" style={{ animationDelay: "0.14s" }} />
                        <span className="thinking-dot" style={{ animationDelay: "0.28s" }} />
                        <em>thinking</em>
                      </div>
                    )
                  )}
                  {live.text && (
                    <div className="chat-msg__meta">
                      <CopyButton text={live.text} label="Copy" className="chat-msg__action" iconOnly />
                      {!streaming && (
                        <SpeakButton speech={speech} msgKey="auto:live" text={live.text} iconOnly />
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}

            {stopped && (
              <div className="chat__stopped">
                <span>Stopped watching. The agent may still be finishing on the server.</span>
                <button className="btn" onClick={() => void watchAgain()}>Watch again</button>
                <button className="btn btn--ghost" onClick={() => void reconnect()}>Refresh transcript</button>
              </div>
            )}

            {streamError && (
              <div className="chat__reconnect">
                <span className="error">Stream interrupted: {streamError}</span>
                {live.runId && <button className="btn" onClick={() => void watchAgain()}>Reconnect live</button>}
                <button className="btn" onClick={() => void reconnect()}>Refresh transcript</button>
              </div>
            )}

            {showJump && (
              <button
                className="chat__jump"
                type="button"
                onClick={jumpToLatest}
                aria-label="Jump to bottom"
                style={{ left: "50%", transform: "translateX(-50%)", bottom: 12 }}
              >
                <Icon name="chevDown" size={18} />
              </button>
            )}
          </div>
        )}

        <div className="chat-composer-zone">
          {slashOpen && (
            <div className="slash-menu" role="listbox" aria-label="Slash commands" style={{ minWidth: 220, borderRadius: 8 }}>
              <button
                type="button"
                className={slashIdx === 0 ? "slash-menu__item slash-menu__item--active" : "slash-menu__item"}
                onMouseEnter={() => setSlashIdx(0)}
                onClick={() => executeSlash("clear")}
              >
                <code>/clear</code>
                <span>Insert a visual divider</span>
              </button>
              <button
                type="button"
                className={slashIdx === 1 ? "slash-menu__item slash-menu__item--active" : "slash-menu__item"}
                onMouseEnter={() => setSlashIdx(1)}
                onClick={() => executeSlash("compact")}
              >
                <code>/compact</code>
                <span>Collapse earlier messages</span>
              </button>
            </div>
          )}
          <div
            className={`chat__composer ${streaming ? "chat__composer--thinking" : ""} ${!activeId ? "chat__composer--empty" : ""}`}
            style={{ borderRadius: 22, boxShadow: "0 4px 20px rgba(0,0,0,0.35)", padding: "7px 7px 7px 10px" }}
          >
            <button
              type="button"
              className={`composer-plus ${plusOpen ? "composer-plus--open" : ""}`}
              aria-expanded={plusOpen}
              style={{ width: 30, height: 30 }}
              onClick={() => setPlusOpen((open) => !open)}
            >
              <Icon name="plus" size={16} />
            </button>
            {plusOpen && (
              <div className="composer-menu">
                <button type="button" onClick={() => fileInputRef.current?.click()}>
                  <Icon name="file" size={14} />
                  Attach file
                </button>
                <button type="button">
                  <span>Model</span>
                  <code>glm-5.2</code>
                </button>
                <button type="button">
                  <span>Direct to agent</span>
                  <code>auto</code>
                </button>
                <button type="button" onClick={() => setReadAloudPref(!readAloud)}>
                  <span>Read aloud</span>
                  <code>{readAloud ? "on" : "off"}</code>
                </button>
                <i />
                <button type="button" onClick={() => setInCall(true)}>
                  <Icon name="phone" size={14} />
                  Voice call
                </button>
              </div>
            )}
            <div className="chat__inputwrap">
              {attachments.length > 0 && (
                <div className="chat-atts chat-atts--pending">
                  {attachments.map((a, i) => (
                    <span className="chat-att chat-att--pending" key={`${a.name}-${i}`}>
                      <span className="chat-att__name">{a.name}</span>
                      <span className="chat-att__meta muted">{formatBytes(a.size ?? 0)}</span>
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
                placeholder="Type a message"
                value={input}
                rows={1}
                onChange={(e) => {
                  setInput(e.target.value);
                  if (!e.target.value.trim().startsWith("/")) setSlashIdx(0);
                }}
                onKeyDown={onComposerKey}
              />
            </div>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="chat__fileinput"
              style={{ display: "none" }}
              onChange={(e) => void addFiles(e.target.files)}
            />
            {dictation.supported && (
              <button
                type="button"
                className={`composer-mic ${dictation.listening ? "composer-mic--on" : ""}`}
                aria-pressed={dictation.listening}
                disabled={streaming}
                style={{ width: 30, height: 30 }}
                onClick={() => {
                  if (dictation.listening) {
                    dictation.stop();
                    return;
                  }
                  dictationBaseRef.current = input;
                  dictation.start();
                }}
                title={dictation.listening ? "Stop dictation" : "Dictate your message"}
              >
                <Icon name="mic" size={15} />
              </button>
            )}
            {streaming ? (
              <button
                className="composer-stop"
                onClick={() => void stopTurn()}
                type="button"
                style={{
                  background: "rgba(240,101,74,0.15)",
                  border: "1px solid rgba(240,101,74,0.35)",
                  color: "#F0654A",
                  height: 30,
                  borderRadius: 15,
                }}
              >
                Stop
              </button>
            ) : input.trim().length > 0 || attachments.length > 0 ? (
              <button
                className="composer-send"
                onClick={() => void send()}
                type="button"
                aria-label="Send"
                style={{ width: 30, height: 30 }}
              >
                <Icon name="send" size={16} />
              </button>
            ) : (
              <button
                className="composer-wave"
                onClick={() => {
                  setCallSeconds(0);
                  setInCall(true);
                }}
                type="button"
                aria-label="Start voice call"
                style={{ width: 30, height: 30 }}
              >
                <Icon name="wave" size={16} />
              </button>
            )}
          </div>
          <div className="chat-composer-meta">
            <span>
              Shift+Enter for a new line, type / for commands
              {dictation.listening && <b> Listening...</b>}
            </span>
            <code>{contextRemaining}k remaining</code>
          </div>
          {attachError && <p className="error chat-composer-error" role="alert">{attachError}</p>}
          {dictation.error && <p className="error chat-composer-error" role="alert">{dictation.error}</p>}
          <FleetBar live={live} activeAgent={selectedAgent} onOpenRun={(runId) => setSubRunId(runId)} />
        </div>
      </main>
    </section>
  );
}
