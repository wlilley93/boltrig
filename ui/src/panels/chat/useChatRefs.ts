import { useRef } from "react";

export interface ChatRefs {
  fileInputRef: React.RefObject<HTMLInputElement>;
  inputRef: React.RefObject<HTMLTextAreaElement>;
  messagesRef: React.RefObject<HTMLDivElement>;
  pinnedRef: React.MutableRefObject<boolean>;
  pendingConvId: React.MutableRefObject<string | null>;
  abortRef: React.MutableRefObject<AbortController | null>;
  alive: React.MutableRefObject<boolean>;
  dictationBaseRef: React.MutableRefObject<string>;
  suppressDictationRef: React.MutableRefObject<boolean>;
  turnTextRef: React.MutableRefObject<string>;
  turnCancelledRef: React.MutableRefObject<boolean>;
}

export function useChatRefs(): ChatRefs {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const pendingConvId = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const alive = useRef(true);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const messagesRef = useRef<HTMLDivElement | null>(null);
  const pinnedRef = useRef(true);
  const dictationBaseRef = useRef("");
  const suppressDictationRef = useRef(false);
  const turnTextRef = useRef("");
  const turnCancelledRef = useRef(false);

  return {
    fileInputRef,
    inputRef,
    messagesRef,
    pinnedRef,
    pendingConvId,
    abortRef,
    alive,
    dictationBaseRef,
    suppressDictationRef,
    turnTextRef,
    turnCancelledRef,
  };
}
