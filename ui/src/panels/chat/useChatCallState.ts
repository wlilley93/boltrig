import { useState } from "react";

type Setter<T> = React.Dispatch<React.SetStateAction<T>>;

export interface ChatCallState {
  inCall: boolean;
  setInCall: Setter<boolean>;
  callMuted: boolean;
  setCallMuted: Setter<boolean>;
  callSpeaker: boolean;
  setCallSpeaker: Setter<boolean>;
  callSeconds: number;
  setCallSeconds: Setter<number>;
}

export function useChatCallState(): ChatCallState {
  const [inCall, setInCall] = useState(false);
  const [callMuted, setCallMuted] = useState(false);
  const [callSpeaker, setCallSpeaker] = useState(true);
  const [callSeconds, setCallSeconds] = useState(0);

  return {
    inCall,
    setInCall,
    callMuted,
    setCallMuted,
    callSpeaker,
    setCallSpeaker,
    callSeconds,
    setCallSeconds,
  };
}
