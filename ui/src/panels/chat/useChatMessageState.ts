import { useState } from "react";

import type { ChatMessage } from "@/api/types";

type Setter<T> = React.Dispatch<React.SetStateAction<T>>;

export interface ChatMessageState {
  activeId: string | null;
  setActiveId: Setter<string | null>;
  messages: ChatMessage[];
  setMessages: Setter<ChatMessage[]>;
  msgsLoading: boolean;
  setMsgsLoading: Setter<boolean>;
  msgsError: string | null;
  setMsgsError: Setter<string | null>;
  lastAssistantId: string | null;
}

export function useChatMessageState(): ChatMessageState {
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [msgsLoading, setMsgsLoading] = useState(false);
  const [msgsError, setMsgsError] = useState<string | null>(null);

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
    messages,
    setMessages,
    msgsLoading,
    setMsgsLoading,
    msgsError,
    setMsgsError,
    lastAssistantId,
  };
}
