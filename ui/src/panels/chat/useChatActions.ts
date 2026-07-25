import { useCallback, useRef } from "react";

import { saveAppearanceLocal, loadAppearance } from "@/appearance";
import { saveReadAloud } from "@/voice";
import { api } from "@/api/client";
import { apiReason } from "@/panels/shared";
import { encodeFile, formatBytes } from "@/panels/chat/attachmentUtils";
import { MAX_ATTACHMENTS, MAX_ATTACHMENT_BYTES, MAX_TOTAL_ATTACHMENT_BYTES } from "@/panels/chat/constants";
import type { ChatDerivedState } from "@/panels/chat/useChatDerived";
import type { ChatPanelState } from "@/panels/chat/useChatState";
import { useChatStreamActions, type ChatStreamActions } from "@/panels/chat/useChatStreamActions";
import {
  requestFleetFocus,
  shouldEnterFleetNavigation,
} from "@/panels/chat/fleetFocus";

export interface ChatActions extends ChatStreamActions {
  loadConversation: (id: string) => void;
  selectConversation: (id: string) => void;
  newConversation: () => void;
  executeSlash: (kind: "clear" | "compact") => void;
  onComposerKey: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  addFiles: (files: FileList | null) => void;
  removeAttachment: (index: number) => void;
  resolveHitl: (id: string, status: string) => void;
  onMessagesScroll: () => void;
  jumpToLatest: () => void;
  setReadAloudPref: (on: boolean) => void;
  toggleTheme: () => void;
}

function useLoadConversation(state: ChatPanelState): (id: string) => void {
  // Monotonic request id, the same guard useConversationRail and useFetch use:
  // transcript fetches take no abort signal, so two loads (a rail click landing
  // on top of finalizeSend's reload, or two fast rail clicks) can resolve out of
  // order. Without this the older response wins and paints one conversation's
  // messages while activeId, and therefore the composer, points at another.
  //
  // Recency alone is NOT enough, and the gap is reachable. useRegenerateAction
  // awaits a real model turn and only then reloads, using the conversation id its
  // render-time closure captured. Click another conversation while a regenerate
  // is in flight (nothing disables the rail during one) and the regenerate's
  // reload is issued LAST - so a monotonic guard SANCTIONS it, and the old
  // conversation repaints under the new one's id with no error shown. So the
  // fetched id must also still be the one the pane is on, read from a ref because
  // the closure's copy is stale by then.
  const seq = useRef(0);
  return useCallback(async (id: string) => {
    // Bail BEFORE touching any state, not after the await. A load that turns the
    // spinner on and is then disowned by the guard below leaves it on forever,
    // because the request that would have cleared it is the one being ignored.
    if (id !== state.activeIdRef.current) return;
    const mine = ++seq.current;
    // Both halves are load-bearing. The id check catches a slow load for a
    // conversation the pane has left; the sequence check catches two loads for
    // the SAME conversation resolving out of order, where the id check cannot
    // tell them apart and the older snapshot would win.
    const current = (): boolean => mine === seq.current && id === state.activeIdRef.current;
    state.setMsgsLoading(true);
    state.setMsgsError(null);
    try {
      const res = await api.conversation(id);
      if (!state.alive.current || !current()) return;
      state.setMessages(res.messages);
    } catch (err) {
      if (state.alive.current && current()) state.setMsgsError(apiReason(err));
    } finally {
      // Clear the spinner whenever THIS load is still the newest, even if the
      // pane has since moved on: the mover turns it back on for its own load, and
      // gating this on the id too is how it gets stuck.
      if (state.alive.current && mine === seq.current) state.setMsgsLoading(false);
    }
  }, [state]);
}

function useConversationSelectionActions(
  state: ChatPanelState,
  loadConversation: (id: string) => void,
): Pick<ChatActions, "selectConversation" | "newConversation"> {
  const selectConversation = useCallback(
    (id: string) => {
      if (id === state.activeId) return;
      state.speech.cancel();
      state.abortRef.current?.abort();
      state.setStreaming(false);
      state.setStopped(false);
      state.setStreamError(null);
      state.setPendingUser(null);
      state.setPendingAttachments([]);
      state.setLiveEvents([]);
      state.setChatTab("chat");
      state.setSelectedAgentId("bolt");
      state.setClearIndex(null);
      state.setCompacted(false);
      state.setActiveId(id);
      // Drop the outgoing transcript before the new one is fetched, the way
      // newConversation does. ChatMessages only shows its spinner while
      // messages is empty, so a load that fails (403 after a scope change, 404
      // after a delete elsewhere, a dropped connection) would otherwise leave
      // the previous conversation's messages on screen under the error line.
      state.setMessages([]);
      void loadConversation(id);
    },
    [state, loadConversation],
  );

  const newConversation = useCallback(() => {
    state.speech.cancel();
    state.abortRef.current?.abort();
    state.setStreaming(false);
    state.setStopped(false);
    state.setStreamError(null);
    state.setPendingUser(null);
    state.setPendingAttachments([]);
    state.setAttachments([]);
    state.setAttachError(null);
    state.setLiveEvents([]);
    state.setChatTab("chat");
    state.setClearIndex(null);
    state.setCompacted(false);
    state.setRightPanel(null);
    state.setSubRunId(null);
    state.setActiveId(null);
    state.setMessages([]);
  }, [state]);

  return { selectConversation, newConversation };
}

function useComposerActions(
  state: ChatPanelState,
  send: () => void,
  fleetActive: boolean,
): Pick<ChatActions, "onComposerKey" | "executeSlash"> {
  const executeSlash = useCallback(
    (kind: "clear" | "compact") => {
      if (kind === "clear") {
        state.setClearIndex(state.messages.length);
        state.setInput("");
        state.setSlashIdx(0);
        return;
      }
      state.setCompacted(true);
      state.setInput("");
      state.setSlashIdx(0);
    },
    [state],
  );

  const onComposerKey = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (state.input.trim().startsWith("/")) {
        if (e.key === "ArrowUp") {
          e.preventDefault();
          state.setSlashIdx((i) => Math.max(0, i - 1));
          return;
        }
        if (e.key === "ArrowDown") {
          e.preventDefault();
          state.setSlashIdx((i) => Math.min(1, i + 1));
          return;
        }
        if (e.key === "Escape") {
          e.preventDefault();
          state.setInput("");
          state.setSlashIdx(0);
          return;
        }
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          executeSlash(state.slashIdx === 0 ? "clear" : "compact");
          return;
        }
      }
      // Empty-composer ArrowDown hands focus to the live fleet bar (sec 18),
      // so its existing Up/Down/Enter/Escape handling takes over. Only fires
      // when a run is live; the slash menu above still owns ArrowDown when the
      // input starts with "/".
      if (
        shouldEnterFleetNavigation({
          key: e.key,
          input: state.input,
          streaming: state.streaming,
          fleetActive,
        })
      ) {
        e.preventDefault();
        requestFleetFocus();
        return;
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        void send();
      }
    },
    [state, executeSlash, send, fleetActive],
  );

  return { onComposerKey, executeSlash };
}

function useAttachmentActions(state: ChatPanelState): Pick<ChatActions, "addFiles" | "removeAttachment"> {
  const addFiles = useCallback(
    async (files: FileList | null) => {
      if (!files || files.length === 0) return;
      state.setAttachError(null);
      const next = [...state.attachments];
      for (const file of Array.from(files)) {
        if (next.length >= MAX_ATTACHMENTS) {
          state.setAttachError(`Too many attachments (max ${MAX_ATTACHMENTS}).`);
          break;
        }
        if (file.size > MAX_ATTACHMENT_BYTES) {
          state.setAttachError(
            `${file.name} is ${formatBytes(file.size)} (max ` +
              `${formatBytes(MAX_ATTACHMENT_BYTES)} per file).`,
          );
          continue;
        }
        const total = next.reduce((s, a) => s + (a.size ?? 0), 0) + file.size;
        if (total > MAX_TOTAL_ATTACHMENT_BYTES) {
          state.setAttachError(
            `Attachments exceed the ${formatBytes(MAX_TOTAL_ATTACHMENT_BYTES)} total cap.`,
          );
          break;
        }
        try {
          const att = await encodeFile(file);
          if (!state.alive.current) return;
          next.push(att);
        } catch {
          state.setAttachError(`Could not read ${file.name}.`);
        }
      }
      state.setAttachments(next);
      if (state.fileInputRef.current) state.fileInputRef.current.value = "";
    },
    [state],
  );

  const removeAttachment = useCallback(
    (index: number) => {
      state.setAttachments((prev) => prev.filter((_, i) => i !== index));
      state.setAttachError(null);
    },
    [state],
  );

  return { addFiles, removeAttachment };
}

function useUiActions(
  state: ChatPanelState,
): Pick<ChatActions, "resolveHitl" | "onMessagesScroll" | "jumpToLatest" | "setReadAloudPref" | "toggleTheme"> {
  const resolveHitl = useCallback(
    (id: string, status: string) => {
      state.setResolvedHitls((prev) => ({ ...prev, [id]: status }));
    },
    [state],
  );

  const onMessagesScroll = useCallback(() => {
    const el = state.messagesRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    state.pinnedRef.current = atBottom;
    if (atBottom) state.setShowJump(false);
  }, [state]);

  const jumpToLatest = useCallback(() => {
    const el = state.messagesRef.current;
    if (!el) return;
    state.pinnedRef.current = true;
    state.setShowJump(false);
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [state]);

  const setReadAloudPref = useCallback(
    (on: boolean) => {
      state.setReadAloud(on);
      saveReadAloud(on);
      if (!on) state.speech.cancel();
    },
    [state],
  );

  const toggleTheme = useCallback(() => {
    const current = loadAppearance();
    const nextTheme = current.theme === "dark" ? "light" : current.theme === "light" ? "system" : "dark";
    saveAppearanceLocal({ ...current, theme: nextTheme });
    state.setTheme(nextTheme);
  }, [state]);

  return { resolveHitl, onMessagesScroll, jumpToLatest, setReadAloudPref, toggleTheme };
}

export function useChatActions(state: ChatPanelState, derived: ChatDerivedState): ChatActions {
  const loadConversation = useLoadConversation(state);
  const conversationActions = useConversationSelectionActions(state, loadConversation);
  const stream = useChatStreamActions(state, derived, loadConversation);
  // The fleet bar is "active" only when a run is live AND it would actually
  // render rows (has a run id, tools, or subagents). This gates the
  // empty-composer ArrowDown shortcut in onComposerKey (sec 18).
  const fleetActive =
    derived.showLive &&
    (!!derived.live.runId ||
      derived.live.tools.length > 0 ||
      derived.live.subagents.length > 0);
  const composerActions = useComposerActions(state, stream.send, fleetActive);
  const attachmentActions = useAttachmentActions(state);
  const uiActions = useUiActions(state);

  return {
    ...conversationActions,
    ...composerActions,
    ...attachmentActions,
    ...uiActions,
    ...stream,
    loadConversation,
  };
}
