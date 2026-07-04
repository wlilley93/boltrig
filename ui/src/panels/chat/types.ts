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
}
