import { useMemo } from "react";
import {
  normalizeEvents,
  type Artifact,
  type ChatAttachment,
  type ChatEvent,
  type ChatMessage,
  type NormalizedTurn,
} from "@wlilley93/boltrig-web-sdk";

import { attachmentIdentity } from "./attachmentPresentation";
import { buildTaskInspectorModel } from "./TaskInspectorModel";
import { integrationsUsedByConversation } from "./toolActivity";

interface ChatProjectionInput {
  artifacts: Artifact[];
  consumedSteerIds: string[];
  continuity: string;
  error: string;
  events: ChatEvent[];
  localQueuedMessages: ChatMessage[];
  queuedMessageOrder: string[];
  materializedOutputs: Record<string, string>;
  messages: ChatMessage[];
}

/** Derive the transcript and lossy task-inspector model from canonical chat state. */
export function useChatProjection(input: ChatProjectionInput) {
  const live = useMemo(() => normalizeEvents(input.events), [input.events]);
  const visibleMessages = useMemo(
    () => input.messages.filter((message) => !message.superseded_by),
    [input.messages],
  );
  const durableRailTurn = useMemo(
    () => durableTurnFromMessages(visibleMessages),
    [visibleMessages],
  );
  const railTurn = live.runId ? live : durableRailTurn;
  const queuedMessages = useMemo(
    () => queuedMessagesFrom(
      visibleMessages,
      input.localQueuedMessages,
      input.consumedSteerIds,
      input.queuedMessageOrder,
    ),
    [
      input.consumedSteerIds,
      input.localQueuedMessages,
      input.queuedMessageOrder,
      visibleMessages,
    ],
  );
  const transcriptMessages = useMemo(() => {
    const queuedIds = new Set(queuedMessages.map((message) => message.id));
    return visibleMessages.filter((message) => !queuedIds.has(message.id));
  }, [queuedMessages, visibleMessages]);
  const sources = useMemo(
    () => uniqueConversationSources(visibleMessages, input.localQueuedMessages),
    [input.localQueuedMessages, visibleMessages],
  );
  const integrationSources = useMemo(
    () => integrationsUsedByConversation(visibleMessages, live.tools),
    [live.tools, visibleMessages],
  );
  const inspectorModel = useMemo(() => buildTaskInspectorModel({
    artifacts: input.artifacts,
    integrationSources,
    sources,
    turn: railTurn,
  }), [input.artifacts, integrationSources, railTurn, sources]);
  const conversationSubagentCount = useMemo(
    () => countConversationSubagents(visibleMessages, live),
    [live, visibleMessages],
  );

  return {
    conversationSubagentCount,
    inspectorModel,
    live,
    materializedOutputIds: new Set(Object.keys(input.materializedOutputs)),
    queuedMessages,
    railTurn,
    railTurnIsLive: Boolean(live.runId && live.runId === railTurn.runId && !live.ended),
    sources,
    transcriptMessages,
    transcriptRevision: transcriptRevisionOf({
      continuity: input.continuity,
      error: input.error,
      events: input.events,
      live,
      queuedMessages,
      transcriptMessages,
    }),
  };
}

function countConversationSubagents(
  messages: ChatMessage[],
  live: NormalizedTurn,
): number {
  const seen = new Set<string>();
  for (const message of messages) {
    if (!message.events?.length) continue;
    for (const agent of normalizeEvents(message.events).subagents) {
      seen.add(agent.childRunId || agent.key);
    }
  }
  for (const agent of live.subagents) seen.add(agent.childRunId || agent.key);
  return seen.size;
}

export function durableTurnFromMessages(messages: ChatMessage[]): NormalizedTurn {
  const latest = [...messages].reverse().find((message) => (
    message.role === "assistant"
    && ((message.events?.length ?? 0) > 0 || Boolean(message.run_id))
  ));
  const turn = normalizeEvents(latest?.events ?? []);
  if (!latest?.run_id) return turn;
  return { ...turn, runId: turn.runId ?? latest.run_id, ended: true };
}

export function queuedMessagesFrom(
  messages: ChatMessage[],
  localQueuedMessages: ChatMessage[],
  consumedSteerIds: string[],
  queuedMessageOrder: string[] = [],
): ChatMessage[] {
  const assistantCount = messages.filter((message) => message.role === "assistant").length;
  const serverQueued = messages
    .filter((message) => message.role === "user")
    .slice(assistantCount)
    .filter((message) => !message.run_id && !consumedSteerIds.includes(message.id));
  const byId = new Map<string, ChatMessage>();
  for (const message of [...serverQueued, ...localQueuedMessages]) {
    if (!consumedSteerIds.includes(message.id)) byId.set(message.id, message);
  }
  const ordered: ChatMessage[] = [];
  for (const id of queuedMessageOrder) {
    const message = byId.get(id);
    if (!message) continue;
    ordered.push(message);
    byId.delete(id);
  }
  return [...ordered, ...byId.values()];
}

export function uniqueConversationSources(
  messages: ChatMessage[],
  localQueuedMessages: ChatMessage[],
): ChatAttachment[] {
  const seen = new Set<string>();
  const result: ChatAttachment[] = [];
  for (const message of [...messages, ...localQueuedMessages]) {
    for (const attachment of message.attachments ?? []) {
      const key = attachmentIdentity(attachment);
      if (seen.has(key)) continue;
      seen.add(key);
      result.push(attachment);
    }
  }
  return result;
}

function transcriptRevisionOf(input: {
  continuity: string;
  error: string;
  events: ChatEvent[];
  live: NormalizedTurn;
  queuedMessages: ChatMessage[];
  transcriptMessages: ChatMessage[];
}): string {
  return [
    ...input.transcriptMessages.map((message) => (
      `${message.id}:${message.content.length}:${message.events?.length ?? 0}`
    )),
    `events:${input.events.length}`,
    `live:${input.live.text.length}:${input.live.timeline.length}`,
    `notices:${input.continuity.length}:${input.error.length}`,
    `queued:${input.queuedMessages.length}`,
  ].join("|");
}
