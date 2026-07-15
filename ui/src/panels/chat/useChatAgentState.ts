import { useMemo, useState } from "react";

import { CHAT_AGENTS } from "@/panels/chat/constants";
import type { ChatAgent, ChatTab } from "@/panels/chat/constants";

type Setter<T> = React.Dispatch<React.SetStateAction<T>>;

export interface ChatAgentState {
  selectedAgentId: string;
  setSelectedAgentId: Setter<string>;
  chatTab: ChatTab;
  setChatTab: Setter<ChatTab>;
  selectedAgent: ChatAgent;
}

export function useChatAgentState(): ChatAgentState {
  const [selectedAgentId, setSelectedAgentId] = useState("bolt");
  const [chatTab, setChatTab] = useState<ChatTab>("chat");
  const selectedAgent = useMemo(
    () => CHAT_AGENTS.find((a) => a.id === selectedAgentId) ?? CHAT_AGENTS[0],
    [selectedAgentId],
  );

  return {
    selectedAgentId,
    setSelectedAgentId,
    chatTab,
    setChatTab,
    selectedAgent,
  };
}
