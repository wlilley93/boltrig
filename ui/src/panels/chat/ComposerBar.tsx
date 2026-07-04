import { useEffect, useState } from "react";

import { Icon } from "@/panels/chat/icons";
import type { ChatAttachment } from "@/api/types";
import { CHAT_AGENTS } from "@/panels/chat/constants";
import { onComposerFocusRequest } from "@/panels/chat/fleetFocus";
import {
  ComposerActions,
  ComposerInput,
} from "@/panels/chat/ComposerParts";

type Setter<T> = (value: T | ((prev: T) => T)) => void;

// Static placeholder model list for the plus-menu "Change model" row (sec 5).
// There is no client-side model catalogue today; when one lands in the API this
// constant should be replaced with the live list. glm-5.2 is first so it is the
// default current selection, matching the runtime model router.
const MODEL_OPTIONS = ["glm-5.2", "gpt-5", "claude-sonnet-4", "gemini-2-pro"] as const;

// "auto" plus every chat agent id, in catalogue order. Cycles wrap around.
const AGENT_CYCLE = ["auto", ...CHAT_AGENTS.map((a) => a.id)];

function agentLabel(id: string): string {
  if (id === "auto") return "auto";
  return CHAT_AGENTS.find((a) => a.id === id)?.name ?? id;
}

interface ComposerMenuProps {
  plusOpen: boolean;
  setPlusOpen: (value: boolean | ((prev: boolean) => boolean)) => void;
  fileInputRef: React.RefObject<HTMLInputElement>;
  readAloud: boolean;
  setReadAloud: (on: boolean) => void;
  startCall: () => void;
  model: string;
  onCycleModel: () => void;
  agent: string;
  onCycleAgent: () => void;
}

function ComposerMenu({
  plusOpen,
  setPlusOpen,
  fileInputRef,
  readAloud,
  setReadAloud,
  startCall,
  model,
  onCycleModel,
  agent,
  onCycleAgent,
}: ComposerMenuProps): JSX.Element {
  return (
    <>
      <button
        type="button"
        className={`composer-plus ${plusOpen ? "composer-plus--open" : ""}`}
        aria-expanded={plusOpen}
        style={{ width: 30, height: 30 }}
        onClick={() => setPlusOpen((open) => !open)}
      >
        <Icon name="plus" size={16} />
      </button>
      {plusOpen && (
        <div className="composer-menu">
          <button type="button" onClick={() => fileInputRef.current?.click()}>
            <Icon name="file" size={14} />
            Attach file
          </button>
          <button type="button" onClick={onCycleModel}>
            <span>Model</span>
            <code>{model}</code>
          </button>
          <button type="button" onClick={onCycleAgent}>
            <span>Direct to agent</span>
            <code>{agent}</code>
          </button>
          <button type="button" onClick={() => setReadAloud(!readAloud)}>
            <span>Read aloud</span>
            <code>{readAloud ? "on" : "off"}</code>
          </button>
          <i />
          <button type="button" onClick={startCall}>
            <Icon name="phone" size={14} />
            Voice call
          </button>
        </div>
      )}
    </>
  );
}

interface ComposerBarProps {
  streaming: boolean;
  activeId: string | null;
  plusOpen: boolean;
  setPlusOpen: (value: boolean | ((prev: boolean) => boolean)) => void;
  fileInputRef: React.RefObject<HTMLInputElement>;
  readAloud: boolean;
  setReadAloud: (on: boolean) => void;
  input: string;
  setInput: Setter<string>;
  inputRef: React.RefObject<HTMLTextAreaElement>;
  attachments: ChatAttachment[];
  removeAttachment: (index: number) => void;
  onComposerKey: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  addFiles: (files: FileList | null) => void;
  setSlashIdx: Setter<number>;
  dictation: import("@/voice").Dictation;
  dictationBaseRef: React.MutableRefObject<string>;
  send: () => void;
  stopTurn: () => void;
  setInCall: (inCall: boolean) => void;
  setCallSeconds: Setter<number>;
}

export function ComposerBar(props: ComposerBarProps): JSX.Element {
  const {
    streaming,
    activeId,
    plusOpen,
    setPlusOpen,
    fileInputRef,
    readAloud,
    setReadAloud,
    input,
    setInput,
    inputRef,
    attachments,
    removeAttachment,
    onComposerKey,
    addFiles,
    setSlashIdx,
    dictation,
    dictationBaseRef,
    send,
    stopTurn,
    setInCall,
    setCallSeconds,
  } = props;

  const startCall = () => {
    setCallSeconds(() => 0);
    setInCall(true);
  };

  // Plus-menu selections for the Model / Direct-to-agent rows (sec 5). These are
  // local composer state so the rows are stateful and reflect the current value;
  // clicking cycles through the option lists above.
  const [modelIdx, setModelIdx] = useState(0);
  const [agentIdx, setAgentIdx] = useState(0);
  const cycleModel = () => setModelIdx((i) => (i + 1) % MODEL_OPTIONS.length);
  const cycleAgent = () => setAgentIdx((i) => (i + 1) % AGENT_CYCLE.length);

  // Honour the fleet Escape shortcut (sec 18): return focus to the composer
  // textarea when the fleet bar asks. The composer is always mounted, so this
  // subscription is live whenever a run is being navigated.
  useEffect(() => {
    return onComposerFocusRequest(() => {
      inputRef.current?.focus();
    });
  }, [inputRef]);

  return (
    <div
      className={`chat__composer ${streaming ? "chat__composer--thinking" : ""} ${!activeId ? "chat__composer--empty" : ""}`}
      style={{ borderRadius: 22, boxShadow: "0 4px 20px rgba(0,0,0,0.35)", padding: "7px 7px 7px 10px" }}
    >
      <ComposerMenu
        plusOpen={plusOpen}
        setPlusOpen={setPlusOpen}
        fileInputRef={fileInputRef}
        readAloud={readAloud}
        setReadAloud={setReadAloud}
        startCall={startCall}
        model={MODEL_OPTIONS[modelIdx]}
        onCycleModel={cycleModel}
        agent={agentLabel(AGENT_CYCLE[agentIdx])}
        onCycleAgent={cycleAgent}
      />
      <ComposerInput
        input={input}
        setInput={setInput}
        inputRef={inputRef}
        attachments={attachments}
        removeAttachment={removeAttachment}
        onComposerKey={onComposerKey}
        fileInputRef={fileInputRef}
        addFiles={addFiles}
        setSlashIdx={setSlashIdx}
      />
      <ComposerActions
        dictation={dictation}
        dictationBaseRef={dictationBaseRef}
        input={input}
        streaming={streaming}
        attachments={attachments}
        send={send}
        stopTurn={stopTurn}
        startCall={startCall}
      />
    </div>
  );
}

export { type ComposerBarProps };
