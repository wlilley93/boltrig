import { useSpeech, useDictation } from "@/voice";
import type { ChatRefs } from "@/panels/chat/useChatRefs";

export interface ChatVoice {
  speech: ReturnType<typeof useSpeech>;
  dictation: ReturnType<typeof useDictation>;
}

export function useChatVoice(refs: ChatRefs, setInput: Setter<string>): ChatVoice {
  const { suppressDictationRef, dictationBaseRef } = refs;

  const speech = useSpeech();
  const dictation = useDictation((transcript, done) => {
    if (suppressDictationRef.current) {
      if (done) suppressDictationRef.current = false;
      return;
    }
    const base = dictationBaseRef.current;
    const joined = base ? `${base.replace(/\s+$/, "")} ${transcript}` : transcript;
    setInput(done ? joined.trimEnd() : joined);
  });

  return { speech, dictation };
}

type Setter<T> = React.Dispatch<React.SetStateAction<T>>;
