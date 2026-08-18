import { useMemo } from "react";
import type { ConversationModelContext } from "@wlilley93/boltrig-web-sdk";

/**
 * Which rendered message the compaction boundary sits after, or null.
 *
 * NULL COVERS TWO DIFFERENT THINGS ON PURPOSE: compaction is off, and
 * compaction happened but its boundary message is not in this transcript --
 * superseded by a regeneration, or simply older than what the view holds.
 * TranscriptBody renders inline for an id and falls back to the end for null,
 * so neither case loses the disclosure.
 */
export function useCompactionBoundary(
  modelContext: ConversationModelContext | null,
  messages: readonly { id: string }[],
): string | null {
  return useMemo(() => {
    const boundary = modelContext?.compacted ? modelContext.up_to_message_id : null;
    if (!boundary) return null;
    return messages.some((message) => message.id === boundary) ? boundary : null;
  }, [modelContext, messages]);
}
