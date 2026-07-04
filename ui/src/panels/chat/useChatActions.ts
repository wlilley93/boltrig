import { useCallback } from "react";

import { saveAppearanceLocal, loadAppearance } from "@/appearance";
import { saveReadAloud } from "@/voice";
import { api } from "@/api/client";
import { apiReason } from "@/panels/shared";
import { CHAT_AGENTS } from "@/panels/chat/constants";
import { encodeFile, formatBytes } from "@/panels/chat/attachmentUtils";
import { MAX_ATTACHMENTS, MAX_ATTACHMENT_BYTES, MAX_TOTAL_ATTACHMENT_BYTES } from "@/panels/chat/constants";
import type { ChatDerivedState } from "@/panels/chat/useChatDerived";
import type { ChatPanelState } from "@/panels/chat/useChatState";
import { useChatStreamActions, type ChatStreamActions } from "@/panels/chat/useChatStreamActions";

export interface ChatActions extends ChatStreamActions {
  loadConversation: (id: string) => void;
  selectConversation: (id: string) => void;
  newConversation: () => void;
  cycleAgent: (dir: "left" | "right") => void;
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
  return useCallback(async (id: string) => {
    state.setMsgsLoading(true);
    state.setMsgsError(null);
    try {
      const res = await api.conversation(id);
      if (!state.alive.current) return;
      state.setMessages(res.messages);
    } catch (err) {
      if (state.alive.current) state.setMsgsError(apiReason(err));
    } finally {
      if (state.alive.current) state.setMsgsLoading(false);
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

function useCycleAgent(state: ChatPanelState): (dir: "left" | "right") => void {
  return useCallback(
    (dir: "left" | "right") => {
      const idx = CHAT_AGENTS.findIndex((a) => a.id === state.selectedAgentId);
      const next =
        dir === "left"
          ? (idx - 1 + CHAT_AGENTS.length) % CHAT_AGENTS.length
          : (idx + 1) % CHAT_AGENTS.length;
      state.setSelectedAgentId(CHAT_AGENTS[next].id);
      state.setSwitchDir(dir);
      state.setSwitchCount((n) => n + 1);
    },
    [state],
  );
}

function useComposerActions(
  state: ChatPanelState,
  send: () => void,
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
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        void send();
      }
    },
    [state, executeSlash, send],
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
  const cycleAgent = useCycleAgent(state);
  const stream = useChatStreamActions(state, derived, loadConversation);
  const composerActions = useComposerActions(state, stream.send);
  const attachmentActions = useAttachmentActions(state);
  const uiActions = useUiActions(state);

  return {
    ...conversationActions,
    ...composerActions,
    ...attachmentActions,
    ...uiActions,
    ...stream,
    loadConversation,
    cycleAgent,
  };
}
