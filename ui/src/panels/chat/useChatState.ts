import { useState } from "react";

import { useIdentity } from "@/identity";
import { useSlideActive } from "@/deck/context";
import { useDictation } from "@/voice";
import { useChatAgentState, type ChatAgentState } from "@/panels/chat/useChatAgentState";
import { useChatAudioState, type ChatAudioState } from "@/panels/chat/useChatAudioState";
import { useChatInputState, type ChatInputState } from "@/panels/chat/useChatInputState";
import { useChatLiveState, type ChatLiveState } from "@/panels/chat/useChatLiveState";
import { useChatMessageState, type ChatMessageState } from "@/panels/chat/useChatMessageState";
import { useChatRefs, type ChatRefs } from "@/panels/chat/useChatRefs";
import { useChatUiState, type ChatUiState } from "@/panels/chat/useChatUiState";
import { useConversationRail } from "@/panels/chat/useConversationRail";

export interface ChatPanelState
  extends ChatAgentState,
    ChatAudioState,
    ChatInputState,
    ChatLiveState,
    ChatMessageState,
    ChatRefs,
    ChatUiState {
  userName: string;
  slideActive: boolean;

  railTerm: string;
  setRailTerm: React.Dispatch<React.SetStateAction<string>>;
  rail: ReturnType<typeof useConversationRail>;

  dictation: ReturnType<typeof useDictation>;
}

export function useChatState(): ChatPanelState {
  const slideActive = useSlideActive();
  const identity = useIdentity();
  const refs = useChatRefs();
  const agentState = useChatAgentState();
  const audioState = useChatAudioState();
  const inputState = useChatInputState();
  const liveState = useChatLiveState();
  const messageState = useChatMessageState();
  const uiState = useChatUiState();
  const [railTerm, setRailTerm] = useState("");
  const rail = useConversationRail(railTerm);

  const dictation = useDictation((transcript, done) => {
    if (refs.suppressDictationRef.current) {
      if (done) refs.suppressDictationRef.current = false;
      return;
    }
    const base = refs.dictationBaseRef.current;
    const joined = base ? `${base.replace(/\s+$/, "")} ${transcript}` : transcript;
    inputState.setInput(done ? joined.trimEnd() : joined);
  });

  return {
    ...refs,
    ...agentState,
    ...audioState,
    ...inputState,
    ...liveState,
    ...messageState,
    ...uiState,
    userName: identity.subject,
    slideActive,
    railTerm,
    setRailTerm,
    rail,
    dictation,
  };
}
