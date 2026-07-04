// Local types used only inside the ChatPanel family.

import type { ConversationSearchResult } from "@/api/types";

export type RailMode = "list" | "search";

export interface RailState {
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

export interface ActivityNode {
  key: string;
  label: string;
  detail: string;
  time: string;
  tone: string;
  runId?: string;
  badge?: string;
  children?: ActivityNode[];
  // Per-event-type visual treatment (brief sec 13.1, lines 374-380). All
  // optional so existing callers keep working; the timeline renders them when
  // present and falls back to the uniform treatment otherwise.
  dotSize?: number; // 8 session, 12 agent/delegation, 7 tool, 9 ephemeral, 8 pending
  dotColor?: string; // overrides the tone-driven dot background when set
  dotExtra?: string; // CSS border string, e.g. "2px solid #04060D" for agent dots
  hasLine?: boolean; // bottom connecting line; false suppresses it (pending)
  hasAvatar?: boolean;
  avatarColor?: string;
  avatarInitials?: string;
  avatarSize?: number; // 20 agent-action, 16 ephemeral
  labelWeight?: number; // 500 session, 600 agent/delegation, 400 tool, 500 ephemeral
  labelColor?: string;
  badgeColor?: string;
  badgeBorder?: string;
}
