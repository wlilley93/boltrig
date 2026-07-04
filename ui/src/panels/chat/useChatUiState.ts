import { useState } from "react";

import { loadAppearance } from "@/appearance";

type Setter<T> = React.Dispatch<React.SetStateAction<T>>;

export interface ChatUiState {
  showJump: boolean;
  setShowJump: Setter<boolean>;
  chatSidebarOpen: boolean;
  setChatSidebarOpen: Setter<boolean>;
  chatSearchOpen: boolean;
  setChatSearchOpen: Setter<boolean>;
  chatSearchTerm: string;
  setChatSearchTerm: Setter<string>;
  theme: string;
  setTheme: Setter<string>;
  rightPanel: "files" | null;
  setRightPanel: Setter<"files" | null>;
  plusOpen: boolean;
  setPlusOpen: Setter<boolean>;
  dragOver: boolean;
  setDragOver: Setter<boolean>;
  clearIndex: number | null;
  setClearIndex: Setter<number | null>;
  compacted: boolean;
  setCompacted: Setter<boolean>;
  slashIdx: number;
  setSlashIdx: Setter<number>;
  subRunId: string | null;
  setSubRunId: Setter<string | null>;
  subRunFull: boolean;
  setSubRunFull: Setter<boolean>;
}

export function useChatUiState(): ChatUiState {
  const [showJump, setShowJump] = useState(false);
  const [chatSidebarOpen, setChatSidebarOpen] = useState(false);
  const [chatSearchOpen, setChatSearchOpen] = useState(false);
  const [chatSearchTerm, setChatSearchTerm] = useState("");
  const [theme, setTheme] = useState(loadAppearance().theme);
  const [rightPanel, setRightPanel] = useState<"files" | null>(null);
  const [plusOpen, setPlusOpen] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [clearIndex, setClearIndex] = useState<number | null>(null);
  const [compacted, setCompacted] = useState(false);
  const [slashIdx, setSlashIdx] = useState(0);
  const [subRunId, setSubRunId] = useState<string | null>(null);
  const [subRunFull, setSubRunFull] = useState(false);

  return {
    showJump,
    setShowJump,
    chatSidebarOpen,
    setChatSidebarOpen,
    chatSearchOpen,
    setChatSearchOpen,
    chatSearchTerm,
    setChatSearchTerm,
    theme,
    setTheme,
    rightPanel,
    setRightPanel,
    plusOpen,
    setPlusOpen,
    dragOver,
    setDragOver,
    clearIndex,
    setClearIndex,
    compacted,
    setCompacted,
    slashIdx,
    setSlashIdx,
    subRunId,
    setSubRunId,
    subRunFull,
    setSubRunFull,
  };
}
