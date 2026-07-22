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
  group?: string;
  parent?: string | null;
  children?: string[];
  tier: 1 | 2;
  unread?: number;
  history: Array<{ id: string; title: string; time: string }>;
}

export const CHAT_AGENTS: ChatAgent[] = [
  {
    id: "bolt",
    name: "Boltrig",
    role: "Governed assistant",
    initials: "B",
    color: "var(--color-accent)",
    dept: "Current scope",
    status: "active",
    snippet: "Conversations in your scope",
    time: "",
    group: "Current scope",
    parent: null,
    children: [],
    tier: 1,
    history: [],
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
