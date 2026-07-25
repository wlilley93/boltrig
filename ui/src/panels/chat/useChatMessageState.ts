import { useCallback, useRef, useState } from "react";

import type { ChatMessage } from "@/api/types";

type Setter<T> = React.Dispatch<React.SetStateAction<T>>;

export interface ChatMessageState {
  activeId: string | null;
  // Deliberately narrower than a React Setter: a plain value only, no updater
  // function. The updater form would have to resolve `prev` inside React's
  // reducer, and writing the ref there is a side effect in a function React may
  // invoke twice. Every call site passes a plain id, so nothing is lost.
  setActiveId: (next: string | null) => void;
  // The conversation the pane is on RIGHT NOW, readable from inside an async
  // callback. `activeId` there is the render-time snapshot the closure captured,
  // which is stale by definition after any await - and a transcript load that
  // trusts it repaints one conversation's messages under another's id.
  //
  // Kept in lockstep by `setActiveId` itself rather than by its callers. A ref
  // that every call site must remember to write is a defect waiting for the next
  // call site; there are five today and the one that forgets is invisible.
  activeIdRef: React.MutableRefObject<string | null>;
  messages: ChatMessage[];
  setMessages: Setter<ChatMessage[]>;
  msgsLoading: boolean;
  setMsgsLoading: Setter<boolean>;
  msgsError: string | null;
  setMsgsError: Setter<string | null>;
  lastAssistantId: string | null;
}

export function useChatMessageState(): ChatMessageState {
  const [activeId, setActiveIdState] = useState<string | null>(null);
  const activeIdRef = useRef<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [msgsLoading, setMsgsLoading] = useState(false);
  const [msgsError, setMsgsError] = useState<string | null>(null);

  // Written SYNCHRONOUSLY, before React commits the state. finalizeSend starts a
  // brand-new conversation by calling setActiveId(convId) and loadConversation(convId)
  // in the same tick, so a ref synced in an effect would still hold null when the
  // load checks it and the guard would swallow the first load of every new
  // conversation.
  const setActiveId = useCallback((next: string | null) => {
    activeIdRef.current = next;
    setActiveIdState(next);
  }, []);

  let lastAssistantId: string | null = null;
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m.role === "assistant" && !m.superseded_by) {
      lastAssistantId = m.id;
      break;
    }
  }

  return {
    activeId,
    setActiveId,
    activeIdRef,
    messages,
    setMessages,
    msgsLoading,
    setMsgsLoading,
    msgsError,
    setMsgsError,
    lastAssistantId,
  };
}
