import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  normalizeEvents,
  type ChatAttachment,
  type ChatEvent,
  type ChatMessage,
} from "@wlilley93/boltrig-web-sdk";

import {
  loadLocalConversation,
  localAgentRoots,
  localAgentStatus,
  localConversationId,
  localEventToChatEvent,
  localThreadId,
  runLocalAgentTurn,
  saveLocalConversation,
  stopLocalAgentTurn,
  type LocalAgentEvent,
  type LocalAgentRoot,
  type LocalAgentStatus,
  type LocalConversation,
} from "../../localAgentClient";

export interface LocalChatControllerProps {
  conversationId: string | null;
  onConversation(id: string): void;
  onChanged(): void;
  onWorkingChange?(conversationId: string, working: boolean): void;
}

export function useLocalChatController(props: LocalChatControllerProps) {
  const runtime = useLocalRuntime();
  const projection = useLocalProjection(props.conversationId, runtime.setRootId);
  const send = (message: string, attachments: ChatAttachment[]) => executeLocalTurn(
    { props, projection, runtime },
    message,
    attachments,
  );
  return {
    ...projection,
    ...runtime,
    ready: runtime.status?.state === "ready" && Boolean(runtime.rootId),
    send,
    stop: async () => { await stopLocalAgentTurn().catch(() => undefined); },
  };
}

export type LocalChatController = ReturnType<typeof useLocalChatController>;

function useLocalRuntime() {
  const [status, setStatus] = useState<LocalAgentStatus | null>(null);
  const [roots, setRoots] = useState<LocalAgentRoot[]>([]);
  const [rootId, setRootId] = useState("");

  useEffect(() => {
    let active = true;
    void Promise.all([localAgentStatus(), localAgentRoots()])
      .then(([nextStatus, nextRoots]) => {
        if (!active) return;
        setStatus(nextStatus);
        setRoots(nextRoots);
        setRootId((current) => validCurrentRoot(current, nextRoots));
      })
      .catch(() => {
        if (active) setStatus(unavailableStatus("local_agent_status_unavailable"));
      });
    return () => {
      active = false;
    };
  }, []);
  return { rootId, roots, setRootId, status };
}

function useLocalProjection(
  conversationId: string | null,
  setRootId: (rootId: string) => void,
) {
  const [conversation, setConversation] = useState<LocalConversation | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [events, setEvents] = useState<ChatEvent[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const eventsRef = useRef<ChatEvent[]>([]);
  const generationRef = useRef(0);
  const busyRef = useRef(false);

  const setBusyOwned = useCallback((next: boolean) => {
    busyRef.current = next;
    setBusy(next);
  }, []);

  useLayoutEffect(() => {
    const generation = ++generationRef.current;
    const interrupted = busyRef.current;
    eventsRef.current = [];
    setEvents([]);
    setError("");
    setDraft("");
    const loaded = conversationId ? loadLocalConversation(conversationId) : null;
    setConversation(loaded);
    setMessages(loaded?.messages ?? []);
    if (loaded) setRootId(loaded.root_id);
    if (conversationId && !loaded) setError(missingConversationMessage(conversationId));
    if (interrupted) {
      void stopLocalAgentTurn()
        .catch(() => undefined)
        .finally(() => {
          if (generationRef.current === generation) setBusyOwned(false);
        });
    } else {
      setBusyOwned(false);
    }
  }, [conversationId, setBusyOwned, setRootId]);

  useEffect(() => () => {
    if (busyRef.current) void stopLocalAgentTurn().catch(() => undefined);
  }, []);

  return {
    busy,
    conversation,
    draft,
    error,
    events,
    eventsRef,
    generationRef,
    messages,
    setBusy: setBusyOwned,
    setConversation,
    setDraft,
    setError,
    setEvents,
    setMessages,
  };
}

type Runtime = ReturnType<typeof useLocalRuntime>;
type Projection = ReturnType<typeof useLocalProjection>;

interface TurnContext {
  props: LocalChatControllerProps;
  projection: Projection;
  runtime: Runtime;
}

interface TurnSession {
  generation: number;
  nextMessages: ChatMessage[];
  now: string;
  owner: LocalConversation | null;
  startedNewTask: boolean;
}

async function executeLocalTurn(
  context: TurnContext,
  message: string,
  attachments: ChatAttachment[],
): Promise<boolean> {
  if (!canStart(context, attachments)) return true;
  let session: TurnSession;
  try {
    session = beginTurn(context, message);
  } catch {
    context.projection.setError("This computer could not store the local task.");
    return false;
  }
  try {
    const outcome = await runLocalAgentTurn({
      rootId: context.runtime.rootId,
      threadId: session.owner?.thread_id,
      message,
    }, (event) => acceptNativeEvent(context, session, message, event));
    if (!ownsGeneration(context, session) || !session.owner) return false;
    persistTurn(context, session.owner, session.nextMessages, outcome.turn_id, outcome.model);
    if (session.startedNewTask) {
      context.projection.setBusy(false);
      context.props.onConversation(session.owner.id);
    }
  } catch (reason) {
    settleFailedTurn(context, session, reason);
  } finally {
    if (session.owner) context.props.onWorkingChange?.(session.owner.id, false);
    if (ownsGeneration(context, session)) context.projection.setBusy(false);
  }
  return false;
}

function canStart(context: TurnContext, attachments: ChatAttachment[]): boolean {
  return !context.projection.busy
    && attachments.length === 0
    && Boolean(context.runtime.rootId)
    && context.runtime.status?.state === "ready";
}

function beginTurn(context: TurnContext, message: string): TurnSession {
  const now = new Date().toISOString();
  const userMessage: ChatMessage = {
    id: `local-user-${crypto.randomUUID()}`,
    role: "user",
    content: message,
    created_at: now,
  };
  const nextMessages = [...context.projection.messages, userMessage];
  const owner = context.projection.conversation
    ? { ...context.projection.conversation, messages: nextMessages, updated_at: now }
    : null;
  context.projection.setMessages(nextMessages);
  context.projection.setBusy(true);
  context.projection.setError("");
  context.projection.eventsRef.current = [];
  context.projection.setEvents([]);
  if (owner) storeOwner(context, owner);
  if (owner) context.props.onWorkingChange?.(owner.id, true);
  return {
    generation: context.projection.generationRef.current,
    nextMessages,
    now,
    owner,
    startedNewTask: owner === null,
  };
}

function acceptNativeEvent(
  context: TurnContext,
  session: TurnSession,
  message: string,
  event: LocalAgentEvent,
) {
  if (!ownsGeneration(context, session)) return;
  if (event.type === "message_start" && !session.owner) {
    session.owner = createOwner(context.runtime.rootId, session, message, event);
    storeOwner(context, session.owner);
    context.props.onWorkingChange?.(session.owner.id, true);
  }
  const projected = localEventToChatEvent(event);
  if (!projected) return;
  context.projection.eventsRef.current = [
    ...context.projection.eventsRef.current,
    projected,
  ];
  context.projection.setEvents(context.projection.eventsRef.current);
}

function persistTurn(
  context: TurnContext,
  owner: LocalConversation,
  prior: ChatMessage[],
  turnId: string,
  model: string,
) {
  const turn = normalizeEvents(context.projection.eventsRef.current);
  const assistant: ChatMessage = {
    id: `local-assistant-${crypto.randomUUID()}`,
    role: "assistant",
    content: turn.text,
    run_id: turnId || turn.runId,
    events: context.projection.eventsRef.current,
    created_at: new Date().toISOString(),
  };
  const settled = {
    ...owner,
    model,
    messages: [...prior, assistant],
    updated_at: assistant.created_at,
  };
  saveLocalConversation(settled);
  context.projection.setConversation(settled);
  context.projection.setMessages(settled.messages);
  context.projection.eventsRef.current = [];
  context.projection.setEvents([]);
  context.props.onChanged();
}

function settleFailedTurn(context: TurnContext, session: TurnSession, reason: unknown) {
  if (!ownsGeneration(context, session)) return;
  if (session.owner && context.projection.eventsRef.current.length > 0) {
    try {
      persistTurn(
        context,
        session.owner,
        session.nextMessages,
        liveRunId(context.projection.eventsRef.current),
        session.owner.model,
      );
    } catch {
      context.projection.setError("This computer could not store the local task.");
      return;
    }
  }
  context.projection.setError(localError(reason));
}

function createOwner(
  rootId: string,
  session: TurnSession,
  message: string,
  event: Extract<LocalAgentEvent, { type: "message_start" }>,
): LocalConversation {
  return {
    id: localConversationId(event.thread_id),
    thread_id: event.thread_id,
    root_id: rootId,
    title: titleFrom(message),
    status: "active",
    model: event.model,
    messages: session.nextMessages,
    created_at: session.now,
    updated_at: session.now,
  };
}

function storeOwner(context: TurnContext, owner: LocalConversation) {
  saveLocalConversation(owner);
  context.projection.setConversation(owner);
  context.props.onChanged();
}

function ownsGeneration(context: TurnContext, session: TurnSession): boolean {
  return context.projection.generationRef.current === session.generation;
}

function validCurrentRoot(current: string, roots: LocalAgentRoot[]): string {
  return current && roots.some((root) => root.root_id === current)
    ? current
    : roots[0]?.root_id ?? "";
}

function missingConversationMessage(conversationId: string): string {
  return localThreadId(conversationId)
    ? "This local task is not stored on this computer."
    : "Cloud tasks run in the browser. Start a local task in this app.";
}

function titleFrom(message: string): string {
  const compact = message.replace(/\s+/g, " ").trim();
  return compact.length > 72 ? `${compact.slice(0, 71)}…` : compact || "Local task";
}

function liveRunId(events: ChatEvent[]): string {
  return events.find((event) => event.type === "message_start")?.run_id ?? "local-turn";
}

function localError(reason: unknown): string {
  const code = String(reason);
  if (code.includes("local_agent_cancelled")) return "Local task stopped.";
  if (code.includes("local_agent_binary")) return "The local Codex runtime is unavailable.";
  if (code.includes("local_agent_root")) {
    return "The selected local workspace is no longer available.";
  }
  if (code.includes("local_agent_busy")) return "Another local task is already running.";
  if (code.includes("local_agent_output_too_large")) {
    return "The local answer exceeded this app's safe display limit.";
  }
  if (code.includes("local_agent_policy_mismatch")) {
    return "The local runtime did not honor the selected approval posture.";
  }
  if (code.includes("local_agent_turn_failed")) return "The local agent reported a failed turn.";
  return "The local task stopped before it completed.";
}

function unavailableStatus(reason: string): LocalAgentStatus {
  return {
    runtime: "local",
    state: "unavailable",
    source: null,
    version: null,
    active: false,
    reason,
  };
}
