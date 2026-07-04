import { useChatState, type ChatPanelState as ChatPanelBaseState } from "@/panels/chat/useChatState";
import { useChatEffects } from "@/panels/chat/useChatEffects";
import { useChatDerived } from "@/panels/chat/useChatDerived";
import { useChatActions } from "@/panels/chat/useChatActions";
import type { ChatActions } from "@/panels/chat/useChatActions";
import type { ChatDerivedState } from "@/panels/chat/useChatDerived";

export type ChatPanelState = ChatPanelBaseState & ChatDerivedState & ChatActions;

export function useChatPanel(): ChatPanelState {
  const state = useChatState();
  const derived = useChatDerived(state);
  const actions = useChatActions(state, derived);
  useChatEffects(state, actions);
  return { ...state, ...derived, ...actions };
}
