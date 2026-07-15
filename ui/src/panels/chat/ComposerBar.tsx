import { useEffect } from "react";

import { Icon } from "@/panels/chat/icons";
import type { ChatAttachment } from "@/api/types";
import { onComposerFocusRequest } from "@/panels/chat/fleetFocus";
import {
  ComposerActions,
  ComposerInput,
} from "@/panels/chat/ComposerParts";

type Setter<T> = (value: T | ((prev: T) => T)) => void;

interface ComposerMenuProps {
  plusOpen: boolean;
  setPlusOpen: (value: boolean | ((prev: boolean) => boolean)) => void;
  fileInputRef: React.RefObject<HTMLInputElement>;
  readAloud: boolean;
  setReadAloud: (on: boolean) => void;
}

function ComposerMenu({
  plusOpen,
  setPlusOpen,
  fileInputRef,
  readAloud,
  setReadAloud,
}: ComposerMenuProps): JSX.Element {
  return (
    <>
      <button
        type="button"
        className={`composer-plus ${plusOpen ? "composer-plus--open" : ""}`}
        aria-label="Add attachment or options"
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
          <button type="button" onClick={() => setReadAloud(!readAloud)}>
            <span>Read aloud</span>
            <code>{readAloud ? "on" : "off"}</code>
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
  } = props;

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
      />
    </div>
  );
}

export { type ComposerBarProps };
