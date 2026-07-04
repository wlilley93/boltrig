// ChatPanel constants and agent catalogue. Pure data, no side effects.

export type ChatTab = "chat" | "activity";

export interface ChatAgent {
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

export const CHAT_AGENTS: ChatAgent[] = [
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

export const GREETINGS = {
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

// Conversation-rail pagination + search (US-CONV-09 / US-CONV-10). The rail
// loads one bounded page at a time and follows next_offset until it is null; the
// default page size mirrors the kernel's conservative default (it is re-clamped
// under the config ceiling server-side either way). Typing in the search box is
// debounced so a term is not queried on every keystroke; clearing it restores
// the paginated list immediately.
export const PAGE_SIZE = 25;
export const SEARCH_DEBOUNCE_MS = 300;

// Attachment caps mirror the fail-closed ChatConfig defaults on the kernel
// ([2026] VJS-COUNTY 3): a count cap, a per-file decoded-bytes cap, and a total
// decoded-bytes cap. They are enforced here so an over-cap turn is rejected
// before it is sent; the backend re-checks and returns 413 attachment_rejected,
// which the send path also surfaces (never a silent drop).
export const MAX_ATTACHMENTS = 8;
export const MAX_ATTACHMENT_BYTES = 256 * 1024;
export const MAX_TOTAL_ATTACHMENT_BYTES = 1024 * 1024;
