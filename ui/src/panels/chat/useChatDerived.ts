import { useMemo } from "react";

import { normalizeEvents } from "@/panels/chatTurn";
import type { ChatPanelState } from "@/panels/chat/useChatState";

export interface ChatDerivedState {
  live: ReturnType<typeof normalizeEvents>;
  railItems: import("@/api/types").ConversationSearchResult[];
  showLive: boolean;
  isEmpty: boolean;
  compactedCount: number;
  displayedMessages: import("@/api/types").ChatMessage[];
  visibleMessages: import("@/api/types").ChatMessage[];
  firstVisibleIndex: number;
  slashOpen: boolean;
  contextRemaining: number;
}

export function useChatDerived(state: ChatPanelState): ChatDerivedState {
  const {
    messages,
    liveEvents,
    streaming,
    pendingUser,
    msgsLoading,
    msgsError,
    compacted,
    chatSearchTerm,
    input,
    rail,
  } = state;

  const live = useMemo(() => normalizeEvents(liveEvents), [liveEvents]);

  const searching = rail.state.mode === "search";
  const railItems = searching
    ? rail.state.items
    : rail.state.items.filter((c) => c.status.toLowerCase() !== "closed");

  const showLive = streaming || liveEvents.length > 0 || state.streamError !== null;
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

  return {
    live,
    railItems,
    showLive,
    isEmpty,
    compactedCount,
    displayedMessages,
    visibleMessages,
    firstVisibleIndex,
    slashOpen,
    contextRemaining,
  };
}
