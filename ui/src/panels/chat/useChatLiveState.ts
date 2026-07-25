import { useState } from "react";

import type { ChatEvent } from "@/api/types";

type Setter<T> = React.Dispatch<React.SetStateAction<T>>;

export interface ChatLiveState {
  liveEvents: ChatEvent[];
  setLiveEvents: Setter<ChatEvent[]>;
  streaming: boolean;
  setStreaming: Setter<boolean>;
  stopped: boolean;
  setStopped: Setter<boolean>;
  streamError: string | null;
  setStreamError: Setter<string | null>;
  // A neutral outcome worth telling the user about that is NOT a failure.
  // Kept apart from streamError because that channel renders in error styling
  // under a hardcoded "Stream interrupted:" prefix.
  notice: string | null;
  setNotice: Setter<string | null>;
  resolvedHitls: Record<string, string>;
  setResolvedHitls: Setter<Record<string, string>>;
}

export function useChatLiveState(): ChatLiveState {
  const [liveEvents, setLiveEvents] = useState<ChatEvent[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [stopped, setStopped] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [resolvedHitls, setResolvedHitls] = useState<Record<string, string>>({});

  return {
    liveEvents,
    setLiveEvents,
    streaming,
    setStreaming,
    stopped,
    setStopped,
    streamError,
    setStreamError,
    notice,
    setNotice,
    resolvedHitls,
    setResolvedHitls,
  };
}
