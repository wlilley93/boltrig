import { useState } from "react";

import type { ChatAttachment } from "@/api/types";

type Setter<T> = React.Dispatch<React.SetStateAction<T>>;

export interface ChatInputState {
  input: string;
  setInput: Setter<string>;
  attachments: ChatAttachment[];
  setAttachments: Setter<ChatAttachment[]>;
  pendingUser: string | null;
  setPendingUser: Setter<string | null>;
  pendingAttachments: ChatAttachment[];
  setPendingAttachments: Setter<ChatAttachment[]>;
  attachError: string | null;
  setAttachError: Setter<string | null>;
  regenerating: string | null;
  setRegenerating: Setter<string | null>;
}

export function useChatInputState(): ChatInputState {
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [pendingUser, setPendingUser] = useState<string | null>(null);
  const [pendingAttachments, setPendingAttachments] = useState<ChatAttachment[]>([]);
  const [attachError, setAttachError] = useState<string | null>(null);
  const [regenerating, setRegenerating] = useState<string | null>(null);

  return {
    input,
    setInput,
    attachments,
    setAttachments,
    pendingUser,
    setPendingUser,
    pendingAttachments,
    setPendingAttachments,
    attachError,
    setAttachError,
    regenerating,
    setRegenerating,
  };
}
