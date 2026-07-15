import { useEffect } from "react";

import { consumeComposerPrefill } from "@/composerPrefill";
import type { ChatPanelState } from "@/panels/chat/useChatState";

function useAbortOnUnmount(state: ChatPanelState): void {
  const { alive, abortRef } = state;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      abortRef.current?.abort();
    };
  }, [alive, abortRef]);
}

function usePrefill(state: ChatPanelState): void {
  const { slideActive, setInput, inputRef } = state;
  useEffect(() => {
    if (!slideActive) return;
    const text = consumeComposerPrefill();
    if (!text) return;
    setInput((prev) => (prev.trim() ? `${prev}\n${text}` : text));
    const focusComposer = () => {
      const el = inputRef.current;
      if (!el) return;
      el.focus();
      el.selectionStart = el.value.length;
      el.selectionEnd = el.value.length;
    };
    window.requestAnimationFrame(focusComposer);
    window.setTimeout(focusComposer, 460);
  }, [slideActive, setInput, inputRef]);
}

function useAutoGrow(state: ChatPanelState): void {
  const { input, inputRef } = state;
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [input, inputRef]);
}

function usePinToBottom(state: ChatPanelState): void {
  const { messagesRef, pinnedRef, setShowJump, messages, pendingUser, liveEvents, streaming } = state;
  useEffect(() => {
    const el = messagesRef.current;
    if (!el) return;
    if (pinnedRef.current) {
      el.scrollTop = el.scrollHeight;
      setShowJump(false);
    } else {
      setShowJump(true);
    }
  }, [messages.length, pendingUser, liveEvents.length, streaming, messagesRef, pinnedRef, setShowJump]);
}

export function useChatEffects(state: ChatPanelState): void {
  useAbortOnUnmount(state);
  usePrefill(state);
  useAutoGrow(state);
  usePinToBottom(state);
}
