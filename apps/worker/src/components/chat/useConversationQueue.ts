import { useState, type MutableRefObject } from "react";
import type { ChatMessage } from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import { reasonText } from "./chatErrors";

type QueueContext = {
  conversationId: string | null;
  generationRef: MutableRefObject<number>;
  selectedRef: MutableRefObject<string | null>;
  reload(id: string): Promise<unknown>;
  setContinuity(value: string): void;
  setError(value: string): void;
};

type PersistContext = QueueContext & {
  generation: number;
  owner: string;
  setOrder(value: string[]): void;
  setReordering(value: boolean): void;
};

function stillOwns(context: PersistContext): boolean {
  return context.selectedRef.current === context.owner
    && context.generationRef.current === context.generation;
}

async function persistQueueOrder(
  context: PersistContext,
  expectedMessageIds: string[],
  messageIds: string[],
) {
  try {
    const result = await client.reorderConversationQueue(context.owner, {
      expected_message_ids: expectedMessageIds,
      message_ids: messageIds,
    });
    if (stillOwns(context)) {
      context.setOrder(result.message_ids);
      context.setContinuity("Queue order updated.");
    }
  } catch (reason) {
    if (stillOwns(context)) {
      context.setError(reasonText(reason));
      await context.reload(context.owner).catch(() => undefined);
    }
  } finally {
    if (stillOwns(context)) context.setReordering(false);
  }
}

export function useConversationQueue(context: QueueContext) {
  const [localMessages, setLocalMessages] = useState<ChatMessage[]>([]);
  const [consumedIds, setConsumedIds] = useState<string[]>([]);
  const [order, setOrder] = useState<string[]>([]);
  const [reordering, setReordering] = useState(false);

  return {
    localMessages,
    consumedIds,
    order,
    reordering,
    reset() {
      setLocalMessages([]);
      setConsumedIds([]);
      setOrder([]);
      setReordering(false);
    },
    echo(message: ChatMessage) {
      setLocalMessages((current) => current.some((item) => item.id === message.id)
        ? current : [...current, message]);
      setOrder((current) => current.includes(message.id) ? current : [...current, message.id]);
    },
    hydrate(messageIds: string[], loadedIds: Set<string>) {
      setLocalMessages((current) => current.filter((message) => !loadedIds.has(message.id)));
      setOrder(messageIds);
    },
    consume(messageId: string) {
      setConsumedIds((current) => current.includes(messageId)
        ? current : [...current, messageId]);
      setOrder((current) => current.filter((id) => id !== messageId));
    },
    reorder(expectedMessageIds: string[], messageIds: string[]) {
      if (!context.conversationId || reordering) return;
      const owner = context.conversationId;
      const generation = context.generationRef.current;
      setReordering(true);
      setOrder(messageIds);
      void persistQueueOrder({
        ...context,
        generation,
        owner,
        setOrder,
        setReordering,
      }, expectedMessageIds, messageIds);
    },
  };
}
