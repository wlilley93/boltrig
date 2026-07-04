import { useState } from "react";

import { loadReadAloud, useSpeech } from "@/voice";

type Setter<T> = React.Dispatch<React.SetStateAction<T>>;

export interface ChatAudioState {
  readAloud: boolean;
  setReadAloud: Setter<boolean>;
  speech: ReturnType<typeof useSpeech>;
}

export function useChatAudioState(): ChatAudioState {
  const [readAloud, setReadAloud] = useState<boolean>(() => loadReadAloud());
  const speech = useSpeech();

  return {
    readAloud,
    setReadAloud,
    speech,
  };
}
