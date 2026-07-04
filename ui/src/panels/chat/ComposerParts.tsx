import { Icon } from "@/panels/chat/icons";
import type { ChatAttachment } from "@/api/types";
import type { Dictation } from "@/voice";

type Setter<T> = (value: T | ((prev: T) => T)) => void;

interface SlashMenuProps {
  slashIdx: number;
  setSlashIdx: Setter<number>;
  executeSlash: (kind: "clear" | "compact") => void;
}

export function SlashMenu({ slashIdx, setSlashIdx, executeSlash }: SlashMenuProps): JSX.Element {
  return (
    <div className="slash-menu" role="listbox" aria-label="Slash commands" style={{ minWidth: 220, borderRadius: 8 }}>
      <button
        type="button"
        className={slashIdx === 0 ? "slash-menu__item slash-menu__item--active" : "slash-menu__item"}
        onMouseEnter={() => setSlashIdx(() => 0)}
        onClick={() => executeSlash("clear")}
      >
        <code>/clear</code>
        <span>Insert a visual divider</span>
      </button>
      <button
        type="button"
        className={slashIdx === 1 ? "slash-menu__item slash-menu__item--active" : "slash-menu__item"}
        onMouseEnter={() => setSlashIdx(() => 1)}
        onClick={() => executeSlash("compact")}
      >
        <code>/compact</code>
        <span>Collapse earlier messages</span>
      </button>
    </div>
  );
}

interface AttachmentListProps {
  attachments: ChatAttachment[];
  removeAttachment: (index: number) => void;
}

export function AttachmentList({ attachments, removeAttachment }: AttachmentListProps): JSX.Element | null {
  if (attachments.length === 0) return null;
  return (
    <div className="chat-atts chat-atts--pending">
      {attachments.map((a, i) => (
        <span className="chat-att chat-att--pending" key={`${a.name}-${i}`}>
          <span className="chat-att__name">{a.name}</span>
          <span className="chat-att__meta muted">{a.size ?? 0} B</span>
          <button
            type="button"
            className="chat-att__remove"
            aria-label={`Remove ${a.name}`}
            onClick={() => removeAttachment(i)}
          >
            x
          </button>
        </span>
      ))}
    </div>
  );
}

interface ComposerInputProps {
  input: string;
  setInput: Setter<string>;
  inputRef: React.RefObject<HTMLTextAreaElement>;
  attachments: ChatAttachment[];
  removeAttachment: (index: number) => void;
  onComposerKey: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  fileInputRef: React.RefObject<HTMLInputElement>;
  addFiles: (files: FileList | null) => void;
  setSlashIdx: Setter<number>;
}

export function ComposerInput({
  input,
  setInput,
  inputRef,
  attachments,
  removeAttachment,
  onComposerKey,
  fileInputRef,
  addFiles,
  setSlashIdx,
}: ComposerInputProps): JSX.Element {
  return (
    <div className="chat__inputwrap">
      <AttachmentList attachments={attachments} removeAttachment={removeAttachment} />
      <textarea
        ref={inputRef}
        className="chat__input"
        placeholder="Type a message"
        value={input}
        rows={1}
        onChange={(e) => {
          setInput(e.target.value);
          if (!e.target.value.trim().startsWith("/")) setSlashIdx(() => 0);
        }}
        onKeyDown={onComposerKey}
      />
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="chat__fileinput"
        style={{ display: "none" }}
        onChange={(e) => void addFiles(e.target.files)}
      />
    </div>
  );
}

interface ComposerActionsProps {
  dictation: Dictation;
  dictationBaseRef: React.MutableRefObject<string>;
  input: string;
  streaming: boolean;
  attachments: ChatAttachment[];
  send: () => void;
  stopTurn: () => void;
  startCall: () => void;
}

export function ComposerActions({
  dictation,
  dictationBaseRef,
  input,
  streaming,
  attachments,
  send,
  stopTurn,
  startCall,
}: ComposerActionsProps): JSX.Element {
  return (
    <>
      {dictation.supported && (
        <button
          type="button"
          className={`composer-mic ${dictation.listening ? "composer-mic--on" : ""}`}
          aria-pressed={dictation.listening}
          disabled={streaming}
          style={{ width: 30, height: 30 }}
          onClick={() => {
            if (dictation.listening) {
              dictation.stop();
              return;
            }
            dictationBaseRef.current = input;
            dictation.start();
          }}
          title={dictation.listening ? "Stop dictation" : "Dictate your message"}
        >
          <Icon name="mic" size={15} />
        </button>
      )}
      {streaming ? (
        <button
          className="composer-stop"
          onClick={() => void stopTurn()}
          type="button"
          style={{
            background: "rgba(240,101,74,0.15)",
            border: "1px solid rgba(240,101,74,0.35)",
            color: "#F0654A",
            height: 30,
            borderRadius: 15,
          }}
        >
          Stop
        </button>
      ) : input.trim().length > 0 || attachments.length > 0 ? (
        <button
          className="composer-send"
          onClick={() => void send()}
          type="button"
          aria-label="Send"
          style={{ width: 30, height: 30 }}
        >
          <Icon name="send" size={16} />
        </button>
      ) : (
        <button
          className="composer-wave"
          onClick={startCall}
          type="button"
          aria-label="Start voice call"
          style={{ width: 30, height: 30 }}
        >
          <Icon name="wave" size={16} />
        </button>
      )}
    </>
  );
}

interface ComposerMetaProps {
  contextRemaining: number;
  dictation: Dictation;
  attachError: string | null;
}

export function ComposerMeta({ contextRemaining, dictation, attachError }: ComposerMetaProps): JSX.Element {
  return (
    <>
      <div className="chat-composer-meta">
        <span>
          Shift+Enter for a new line, type / for commands
          {dictation.listening && <b> Listening...</b>}
        </span>
        <code>{contextRemaining}k remaining</code>
      </div>
      {attachError && <p className="error chat-composer-error" role="alert">{attachError}</p>}
      {dictation.error && <p className="error chat-composer-error" role="alert">{dictation.error}</p>}
    </>
  );
}

export type {
  SlashMenuProps,
  AttachmentListProps,
  ComposerInputProps,
  ComposerActionsProps,
  ComposerMetaProps,
};
