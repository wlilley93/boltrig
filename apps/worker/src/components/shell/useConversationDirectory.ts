import { useCallback, useEffect, useRef, useState } from "react";
import type { ConversationSummary } from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import { hasDesktopRuntime } from "../../desktop";
import {
  listLocalConversations,
  listenLocalConversations,
} from "../../localAgentClient";

export type ConversationDirectoryStatus = "loading" | "ready" | "unavailable";

export function useConversationDirectory() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [workingConversationIds, setWorkingConversationIds] = useState<string[]>([]);
  const [conversationOffset, setConversationOffset] = useState<number | null>(0);
  const [conversationStatus, setConversationStatus] = useState<ConversationDirectoryStatus>(
    "loading",
  );
  // A page may publish only into the authoritative refresh generation it
  // started from. A slower stale page therefore cannot append to a new list.
  const epochRef = useRef(0);

  const refresh = useCallback(() => {
    const epoch = ++epochRef.current;
    setConversationStatus("loading");
    if (hasDesktopRuntime()) {
      setConversations(listLocalConversations());
      setConversationOffset(null);
      setConversationStatus("ready");
      return;
    }
    void client.conversationsPage(25, 0).then((result) => {
      if (epochRef.current !== epoch) return;
      setConversations(result.conversations);
      setConversationOffset(result.next_offset);
      setConversationStatus("ready");
    }).catch(() => {
      if (epochRef.current === epoch) setConversationStatus("unavailable");
    });
  }, []);

  useEffect(() => (
    hasDesktopRuntime() ? listenLocalConversations(refresh) : undefined
  ), [refresh]);

  const loadMore = useCallback(() => {
    if (conversationOffset === null) return;
    const epoch = epochRef.current;
    setConversationStatus("loading");
    void client.conversationsPage(25, conversationOffset).then((result) => {
      if (epochRef.current !== epoch) return;
      setConversations((current) => [
        ...current,
        ...result.conversations.filter(
          (conversation) => !current.some((item) => item.id === conversation.id),
        ),
      ]);
      setConversationOffset(result.next_offset);
      setConversationStatus("ready");
    }).catch(() => {
      if (epochRef.current === epoch) setConversationStatus("unavailable");
    });
  }, [conversationOffset]);

  const setWorking = useCallback((id: string, working: boolean) => {
    setWorkingConversationIds((current) => {
      if (working) return current.includes(id) ? current : [...current, id];
      return current.filter((conversationId) => conversationId !== id);
    });
  }, []);

  const remove = useCallback((id: string) => {
    setConversations((current) => current.filter((conversation) => conversation.id !== id));
    setWorkingConversationIds((current) => current.filter((currentId) => currentId !== id));
  }, []);

  return {
    conversations,
    conversationStatus,
    hasMore: conversationOffset !== null,
    loadMore,
    refresh,
    remove,
    setWorking,
    workingConversationIds,
  };
}
