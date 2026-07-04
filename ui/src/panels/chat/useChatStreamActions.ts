import { useCallback } from "react";

import { ApiError, api, streamChat, streamRunEvents } from "@/api/client";
import type { ChatAttachment, ChatEvent } from "@/api/types";
import { apiReason } from "@/panels/shared";
import type { ChatDerivedState } from "@/panels/chat/useChatDerived";
import type { ChatPanelState } from "@/panels/chat/useChatState";
import { useConversationRail } from "@/panels/chat/useConversationRail";

export interface ChatStreamActions {
  send: () => void;
  reconnect: () => void;
  stopTurn: () => void;
  regenerate: (messageId: string) => void;
  watchAgain: () => void;
}

function buildSendRequest(
  text: string,
  activeId: string | null,
  atts: ChatAttachment[],
): { message: string; conversation_id?: string; attachments?: ChatAttachment[] } {
  const req = { message: text } as { message: string; conversation_id?: string; attachments?: ChatAttachment[] };
  if (activeId) req.conversation_id = activeId;
  if (atts.length > 0) req.attachments = atts;
  return req;
}

function handleStreamEvent(
  state: ChatPanelState,
  ctrl: AbortController,
): (ev: ChatEvent) => void {
  return (ev) => {
    if (ctrl.signal.aborted || !state.alive.current) return;
    if (ev.type === "message_start" && ev.conversation_id) {
      state.pendingConvId.current = ev.conversation_id;
    }
    if (ev.type === "text_delta" && ev.delta) state.turnTextRef.current += ev.delta;
    if (ev.type === "cancelled") {
      state.setStopped(true);
      state.turnCancelledRef.current = true;
    }
    state.setLiveEvents((prev) => [...prev, ev]);
  };
}

async function finalizeSend(
  state: ChatPanelState,
  rail: ReturnType<typeof useConversationRail>,
  loadConversation: (id: string) => void,
): Promise<void> {
  if (!state.alive.current) return;
  state.setStreaming(false);
  if (state.readAloud && !state.turnCancelledRef.current) {
    state.speech.speak(`auto:${state.pendingConvId.current ?? "live"}`, state.turnTextRef.current);
  }
  const convId = state.pendingConvId.current;
  if (convId) {
    if (!state.activeId) state.setActiveId(convId);
    await loadConversation(convId);
    if (!state.alive.current) return;
    rail.reload();
  }
  state.setPendingUser(null);
  state.setPendingAttachments([]);
  state.setLiveEvents([]);
}

function useSendAction(
  state: ChatPanelState,
  loadConversation: (id: string) => void,
): () => void {
  const { rail } = state;

  return useCallback(async () => {
    const text = state.input.trim();
    const atts = state.attachments;
    if ((!text && atts.length === 0) || state.streaming) return;

    if (state.dictation.listening) {
      state.suppressDictationRef.current = true;
      state.dictation.stop();
    }
    state.speech.cancel();
    state.turnTextRef.current = "";
    state.turnCancelledRef.current = false;

    state.setInput("");
    state.setStreamError(null);
    state.setAttachError(null);
    state.setStopped(false);
    state.setPendingUser(text);
    state.setPendingAttachments(atts);
    state.setAttachments([]);
    state.setLiveEvents([]);
    state.setStreaming(true);
    state.pendingConvId.current = state.activeId;

    const req = buildSendRequest(text, state.activeId, atts);
    const ctrl = new AbortController();
    state.abortRef.current = ctrl;

    try {
      await streamChat(req, handleStreamEvent(state, ctrl), ctrl.signal);
      await finalizeSend(state, rail, loadConversation);
    } catch (err) {
      if (!state.alive.current) return;
      state.setStreaming(false);
      if (ctrl.signal.aborted) return;
      if (err instanceof ApiError && err.status === 413) {
        state.setAttachments(atts);
        state.setAttachError(apiReason(err));
      }
      state.setStreamError(apiReason(err));
    } finally {
      if (state.abortRef.current === ctrl) state.abortRef.current = null;
    }
  }, [state, rail, loadConversation]);
}

function useReconnectAction(
  state: ChatPanelState,
  loadConversation: (id: string) => void,
): () => void {
  const { rail } = state;

  return useCallback(async () => {
    const convId = state.activeId ?? state.pendingConvId.current;
    state.setStreamError(null);
    if (convId) {
      if (!state.activeId) state.setActiveId(convId);
      await loadConversation(convId);
      if (!state.alive.current) return;
      rail.reload();
    }
    state.setPendingUser(null);
    state.setPendingAttachments([]);
    state.setLiveEvents([]);
    state.setStopped(false);
  }, [state, rail, loadConversation]);
}

function useStopTurnAction(state: ChatPanelState, derived: ChatDerivedState): () => void {
  const { live } = derived;

  return useCallback(async () => {
    const runId = live.runId;
    state.turnCancelledRef.current = true;
    state.speech.cancel();
    state.setStopped(true);
    if (!runId) {
      state.abortRef.current?.abort();
      state.setStreaming(false);
      return;
    }
    try {
      const res = await api.cancelRun(runId);
      if (!state.alive.current) return;
      if (res.status !== "ok") {
        state.abortRef.current?.abort();
        state.setStreaming(false);
      }
    } catch {
      if (!state.alive.current) return;
      state.abortRef.current?.abort();
      state.setStreaming(false);
    }
  }, [state, live]);
}

function useRegenerateAction(
  state: ChatPanelState,
  loadConversation: (id: string) => void,
): (messageId: string) => void {
  const { rail } = state;

  return useCallback(
    async (messageId: string) => {
      if (!state.activeId || state.streaming || state.regenerating) return;
      state.setRegenerating(messageId);
      state.setStreamError(null);
      state.setMsgsError(null);
      try {
        const res = await api.regenerateMessage(state.activeId, messageId);
        if (!state.alive.current) return;
        if (res.status !== "ok") {
          state.setMsgsError(res.reason ?? `Regenerate failed: ${res.status}`);
        }
        await loadConversation(state.activeId);
        if (!state.alive.current) return;
        rail.reload();
      } catch (err) {
        if (state.alive.current) state.setMsgsError(apiReason(err));
      } finally {
        if (state.alive.current) state.setRegenerating(null);
      }
    },
    [state, rail, loadConversation],
  );
}

function useWatchAgainAction(
  state: ChatPanelState,
  derived: ChatDerivedState,
  loadConversation: (id: string) => void,
  reconnect: () => void,
): () => void {
  const { live } = derived;
  const { rail } = state;

  return useCallback(async () => {
    if (!live.runId) {
      await reconnect();
      return;
    }
    state.speech.cancel();
    state.turnTextRef.current = "";
    state.turnCancelledRef.current = false;
    state.setStopped(false);
    state.setStreamError(null);
    state.setStreaming(true);
    state.setLiveEvents([]);
    const ctrl = new AbortController();
    state.abortRef.current = ctrl;
    try {
      await streamRunEvents(
        live.runId,
        (ev) => {
          if (ctrl.signal.aborted || !state.alive.current) return;
          if (ev.type === "text_delta") state.turnTextRef.current += ev.delta;
          if (ev.type === "cancelled") state.turnCancelledRef.current = true;
          state.setLiveEvents((prev) => [...prev, ev]);
        },
        { signal: ctrl.signal, follow: true },
      );
      if (!state.alive.current) return;
      state.setStreaming(false);
      if (state.readAloud && !state.turnCancelledRef.current) {
        state.speech.speak(`auto:${state.activeId ?? state.pendingConvId.current ?? "live"}`, state.turnTextRef.current);
      }
      const convId = state.activeId ?? state.pendingConvId.current ?? live.conversationId;
      if (convId) {
        if (!state.activeId) state.setActiveId(convId);
        await loadConversation(convId);
        if (!state.alive.current) return;
        rail.reload();
      }
      state.setPendingUser(null);
      state.setLiveEvents([]);
    } catch (err) {
      if (!state.alive.current) return;
      state.setStreaming(false);
      if (ctrl.signal.aborted) return;
      state.setStreamError(apiReason(err));
    } finally {
      if (state.abortRef.current === ctrl) state.abortRef.current = null;
    }
  }, [state, live, rail, loadConversation, reconnect]);
}

export function useChatStreamActions(
  state: ChatPanelState,
  derived: ChatDerivedState,
  loadConversation: (id: string) => void,
): ChatStreamActions {
  const send = useSendAction(state, loadConversation);
  const reconnect = useReconnectAction(state, loadConversation);
  const stopTurn = useStopTurnAction(state, derived);
  const regenerate = useRegenerateAction(state, loadConversation);
  const watchAgain = useWatchAgainAction(state, derived, loadConversation, reconnect);

  return { send, reconnect, stopTurn, regenerate, watchAgain };
}
