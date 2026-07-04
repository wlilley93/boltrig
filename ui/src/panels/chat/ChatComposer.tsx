import { FleetBar } from "@/panels/chat/FleetBar";
import { ComposerBar } from "@/panels/chat/ComposerBar";
import { ComposerMeta, SlashMenu } from "@/panels/chat/ComposerParts";
import type { ChatAttachment } from "@/api/types";
import type { ChatAgent } from "@/panels/chat/constants";
import type { NormalizedTurn } from "@/panels/chatTurn";
import type { Dictation } from "@/voice";

type Setter<T> = (value: T | ((prev: T) => T)) => void;

interface ChatComposerProps {
  input: string;
  setInput: Setter<string>;
  inputRef: React.RefObject<HTMLTextAreaElement>;
  attachments: ChatAttachment[];
  removeAttachment: (index: number) => void;
  onComposerKey: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  fileInputRef: React.RefObject<HTMLInputElement>;
  addFiles: (files: FileList | null) => void;
  streaming: boolean;
  activeId: string | null;
  send: () => void;
  stopTurn: () => void;
  setInCall: (inCall: boolean) => void;
  setCallSeconds: Setter<number>;
  plusOpen: boolean;
  setPlusOpen: Setter<boolean>;
  slashOpen: boolean;
  slashIdx: number;
  setSlashIdx: Setter<number>;
  executeSlash: (kind: "clear" | "compact") => void;
  readAloud: boolean;
  setReadAloud: (on: boolean) => void;
  dictation: Dictation;
  dictationBaseRef: React.MutableRefObject<string>;
  attachError: string | null;
  contextRemaining: number;
  live: NormalizedTurn;
  selectedAgent: ChatAgent;
  onOpenRun: (runId: string) => void;
}

export function ChatComposer(props: ChatComposerProps): JSX.Element {
  const {
    input,
    setInput,
    inputRef,
    attachments,
    removeAttachment,
    onComposerKey,
    fileInputRef,
    addFiles,
    streaming,
    activeId,
    send,
    stopTurn,
    setInCall,
    setCallSeconds,
    plusOpen,
    setPlusOpen,
    slashOpen,
    slashIdx,
    setSlashIdx,
    executeSlash,
    readAloud,
    setReadAloud,
    dictation,
    dictationBaseRef,
    attachError,
    contextRemaining,
    live,
    selectedAgent,
    onOpenRun,
  } = props;

  return (
    <div className="chat-composer-zone">
      {slashOpen && (
        <SlashMenu slashIdx={slashIdx} setSlashIdx={setSlashIdx} executeSlash={executeSlash} />
      )}
      <ComposerBar
        streaming={streaming}
        activeId={activeId}
        plusOpen={plusOpen}
        setPlusOpen={setPlusOpen}
        fileInputRef={fileInputRef}
        readAloud={readAloud}
        setReadAloud={setReadAloud}
        input={input}
        setInput={setInput}
        inputRef={inputRef}
        attachments={attachments}
        removeAttachment={removeAttachment}
        onComposerKey={onComposerKey}
        addFiles={addFiles}
        setSlashIdx={setSlashIdx}
        dictation={dictation}
        dictationBaseRef={dictationBaseRef}
        send={send}
        stopTurn={stopTurn}
        setInCall={setInCall}
        setCallSeconds={setCallSeconds}
      />
      <ComposerMeta contextRemaining={contextRemaining} dictation={dictation} attachError={attachError} />
      <FleetBar live={live} activeAgent={selectedAgent} onOpenRun={onOpenRun} />
    </div>
  );
}

export { type ChatComposerProps };
