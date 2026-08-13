import {
  useLayoutEffect,
  useRef,
  useState,
  type Dispatch,
  type FormEvent,
  type ReactNode,
  type RefObject,
  type SetStateAction,
} from "react";
import type {
  ChatAttachment,
  ChatAttachmentLimits,
  ChatModelChoice,
} from "@wlilley93/boltrig-web-sdk";

import { navigate } from "../../routes";
import {
  ApprovalPostureMenu,
  type ApprovalRuntime,
} from "../ApprovalPostureControl";
import { ModelChip } from "./ModelChip";
import {
  arrayBufferToBase64,
  formatBytes,
  modelReadable,
} from "./attachmentPresentation";

export interface ComposerProps {
  busy: boolean;
  disabled: boolean;
  closed: boolean;
  /** Resets staged, conversation-owned inputs without remounting VoiceCall. */
  conversationKey: string | null;
  modelChoices: ChatModelChoice[];
  modelChoice: string;
  defaultModelName?: string | null;
  defaultModelAvailable: boolean;
  defaultModelUnavailableReason?: string | null;
  modelChoicesLoaded: boolean;
  modelSelectionLocked: boolean;
  attachmentLimits: ChatAttachmentLimits;
  /** Local App Server turns currently accept text only. Keep the control
      visibly unavailable instead of staging bytes the native bridge cannot
      lawfully bind to the selected workspace. */
  attachmentsDisabled?: boolean;
  /** Browser chat uses kernel-governed cloud tools. The signed desktop uses a
      separate, device-owned local posture and never inherits cloud consent. */
  agentRuntime?: ApprovalRuntime;
  /** The draft lives with the caller so starter cards can fill it. */
  value: string;
  onChange: Dispatch<SetStateAction<string>>;
  inputRef?: RefObject<HTMLTextAreaElement>;
  /** When live voice is verified reachable, an empty draft turns the primary
      button into "Start a voice call". */
  voicePrimary?: { onStart(): void };
  onModelChoice(value: string): void;
  onSend(message: string, files: ChatAttachment[]): Promise<boolean>;
  onStop(): Promise<void>;
  /** The voice control, so it sits with the other composer tools rather than
      crowding the title row. */
  voice?: ReactNode;
  /** The fresh-chat target centres the composer and hangs a truthful context
      rail below it. This changes presentation only; no policy is inferred. */
  newContext?: boolean;
  /** A failed state load is distinct from an in-progress load. */
  unavailable?: boolean;
  onCommandPalette?(): void;
}

function useComposerAttachments(
  conversationKey: string | null,
  attachmentLimits: ChatAttachmentLimits,
) {
  const [files, setFiles] = useState<ChatAttachment[]>([]);
  const [fileError, setFileError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const conversationKeyRef = useRef(conversationKey);
  conversationKeyRef.current = conversationKey;

  useLayoutEffect(() => {
    setFiles([]);
    setFileError("");
    if (input.current) input.current.value = "";
  }, [conversationKey]);

  async function addFiles(list: FileList | null) {
    if (!list) return;
    const owner = conversationKey;
    setFileError("");
    const selected = Array.from(list);
    if (files.length + selected.length > attachmentLimits.max_count) {
      setFileError(`Attach at most ${attachmentLimits.max_count} files to one turn.`);
      return;
    }
    const tooLarge = selected.find((file) => file.size > attachmentLimits.max_bytes);
    if (tooLarge) {
      setFileError(
        `${tooLarge.name} is too large. Each file must be ${formatBytes(attachmentLimits.max_bytes)} or smaller.`,
      );
      return;
    }
    const total = files.reduce((sum, file) => sum + (file.size ?? 0), 0)
      + selected.reduce((sum, file) => sum + file.size, 0);
    if (total > attachmentLimits.max_total_bytes) {
      setFileError(
        `Attachments must total ${formatBytes(attachmentLimits.max_total_bytes)} or less.`,
      );
      return;
    }
    const added = await Promise.all(selected.map(async (file) => ({
      name: file.name,
      media_type: file.type || "application/octet-stream",
      data: arrayBufferToBase64(await file.arrayBuffer()),
      size: file.size,
    })));
    if (conversationKeyRef.current !== owner) return;
    setFiles((current) => [...current, ...added]);
  }

  return {
    addFiles,
    fileError,
    files,
    input,
    ownsConversation: (owner: string | null) => conversationKeyRef.current === owner,
    setFiles,
  };
}

export function Composer(props: ComposerProps) {
  const staged = useComposerAttachments(props.conversationKey, props.attachmentLimits);
  const selectedModelAvailable = props.modelChoice
    ? props.modelChoices.some((choice) => choice.id === props.modelChoice && choice.available)
    : props.defaultModelAvailable;
  // Wait for the server-owned catalogue, then fail closed when the selected
  // route is unavailable. The model menu stays operable so the user can
  // recover by choosing a live route or opening Settings.
  const modelReady = props.modelChoicesLoaded && selectedModelAvailable;
  const voicePrimaryVisible = Boolean(
    props.voicePrimary && !props.value.trim() && !props.busy && !props.disabled,
  );

  async function submit(event: FormEvent) {
    event.preventDefault();
    const message = props.value.trim();
    if (!message || !modelReady) return;
    props.onChange("");
    const sentFiles = staged.files;
    const owner = props.conversationKey;
    staged.setFiles([]);
    const restore = await props.onSend(message, sentFiles);
    if (!staged.ownsConversation(owner)) return;
    if (restore) {
      props.onChange((current) => current || message);
      staged.setFiles((current) => current.length ? current : sentFiles);
    }
  }

  return (
    <form className={`composer${props.closed ? " closed" : ""}${props.newContext ? " new-context" : " conversation-context"}`} onSubmit={submit}>
      <div className="composer-frame">
        {props.closed && (
          <p className="composer-closed" role="status">
            Restore this conversation to continue it.
          </p>
        )}
        <AttachmentStatus
          attachmentLimits={props.attachmentLimits}
          fileError={staged.fileError}
          files={staged.files}
          onRemove={(file) => staged.setFiles((items) => items.filter((item) => item !== file))}
        />
        <ComposerTextarea {...props} />
        <ComposerTools
          {...props}
          addFiles={staged.addFiles}
          fileInputRef={staged.input}
          modelReady={modelReady}
          voicePrimaryVisible={voicePrimaryVisible}
        />
      </div>
      {props.newContext && <ComposerContext runtime={props.agentRuntime ?? "cloud"} />}
    </form>
  );
}

function AttachmentStatus({
  attachmentLimits,
  fileError,
  files,
  onRemove,
}: {
  attachmentLimits: ChatAttachmentLimits;
  fileError: string;
  files: ChatAttachment[];
  onRemove(file: ChatAttachment): void;
}) {
  return (
    <>
      {files.length > 0 && <div className="file-row">{files.map((file, index) => (
        <button type="button" className="file-chip" key={`${file.name}-${index}`} onClick={() => onRemove(file)}>▧ {file.name} · {modelReadable(file.media_type, attachmentLimits.model_readable_media_types) ? "model-readable" : "record only"} ×</button>
      ))}</div>}
      {fileError && <p className="notice" role="alert">{fileError}</p>}
    </>
  );
}

function ComposerTextarea(props: ComposerProps) {
  return (
    <textarea
      aria-label="Task instructions"
      placeholder={
        props.closed
          ? "This conversation is closed"
          : props.unavailable
            ? "Conversation unavailable — retry above"
          : props.disabled
            ? "Loading conversation state…"
            : "Describe the work"
      }
      disabled={props.disabled}
      ref={props.inputRef}
      value={props.value}
      onChange={(event) => props.onChange(event.target.value)}
      onKeyDown={(event) => {
        if (event.nativeEvent.isComposing || event.keyCode === 229) return;
        if (event.key === "/" && !event.currentTarget.value && props.onCommandPalette) {
          event.preventDefault();
          props.onCommandPalette();
          return;
        }
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          event.currentTarget.form?.requestSubmit();
        }
      }}
    />
  );
}

type ComposerToolsProps = ComposerProps & {
  addFiles(list: FileList | null): Promise<void>;
  fileInputRef: RefObject<HTMLInputElement>;
  modelReady: boolean;
  voicePrimaryVisible: boolean;
};

function ComposerTools(props: ComposerToolsProps) {
  return (
    <div className="composer-tools">
      <AttachmentAndPolicyTools {...props} />
      <div>
        {(props.modelChoicesLoaded || props.modelChoices.length > 0 || props.defaultModelName) && (
          <ModelChip
            choices={props.modelChoices}
            defaultModelName={props.defaultModelName}
            defaultAvailable={props.defaultModelAvailable}
            defaultUnavailableReason={props.defaultModelUnavailableReason}
            value={props.modelChoice}
            disabled={props.disabled || props.modelSelectionLocked}
            disabledReason={props.modelSelectionLocked
              ? "The model can be changed after the current turn finishes."
              : undefined}
            onChange={props.onModelChoice}
            onManage={() => navigate("settings", "models")}
          />
        )}
        <ComposerActions {...props} />
      </div>
    </div>
  );
}

function AttachmentAndPolicyTools(props: ComposerToolsProps) {
  return (
    <div>
      <input ref={props.fileInputRef} hidden type="file" multiple onChange={(event) => void props.addFiles(event.target.files)} />
      <button
        type="button"
        className="icon-button"
        disabled={props.disabled || props.attachmentsDisabled}
        onClick={() => props.fileInputRef.current?.click()}
        aria-label={props.attachmentsDisabled ? "Attachments unavailable for local tasks" : "Attach files"}
        title={props.attachmentsDisabled ? "Local task attachments are not available yet" : undefined}
      >
        <svg aria-hidden fill="none" height="17" stroke="currentColor" strokeLinecap="round" strokeWidth="1.9" viewBox="0 0 24 24" width="17">
          <line x1="12" x2="12" y1="5" y2="19" />
          <line x1="5" x2="19" y1="12" y2="12" />
        </svg>
      </button>
      <ApprovalPostureMenu
        disabled={props.disabled || (props.agentRuntime === "local" && props.busy)}
        runtime={props.agentRuntime}
      />
    </div>
  );
}

function ComposerActions(props: ComposerToolsProps) {
  return (
    <>
      {props.busy && (
        <button className="stop-button" type="button" onClick={() => void props.onStop()}>
          ■ Stop
        </button>
      )}
      {props.newContext && (
        <button
          aria-label="Dictation unavailable"
          aria-disabled="true"
          className="icon-button composer-dictate"
          title="Dictation is not available in this client"
          type="button"
        >
          <svg aria-hidden fill="none" height="16" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" viewBox="0 0 24 24" width="16">
            <rect height="11" rx="3" width="6" x="9" y="3" />
            <path d="M5 11a7 7 0 0 0 14 0" />
            <line x1="12" x2="12" y1="18" y2="21" />
          </svg>
        </button>
      )}
      {/* VoiceCall stays mounted as the single owner of call state. Its
          idle trigger is hidden while the empty-draft primary proxies the
          same action, so one action never appears as two waveforms. */}
      {props.voice && (
        <div className="composer-voice-controller" hidden={props.voicePrimaryVisible}>
          {props.voice}
        </div>
      )}
      <ComposerPrimaryAction {...props} />
    </>
  );
}

function ComposerPrimaryAction(props: ComposerToolsProps) {
  // The primary is dual: with a draft it sends (or queues); with an empty draft
  // it starts a voice call. Only an explicit click starts a call - Enter on an
  // empty draft stays inert, so a stray keystroke never opens a microphone.
  if (props.voicePrimaryVisible) return (
    <button
      aria-label="Start a voice call"
      className="send-button voice-primary"
      onClick={() => props.voicePrimary?.onStart()}
      title="Start a voice call"
      type="button"
    >
      <svg aria-hidden fill="currentColor" height="15" viewBox="0 0 24 24" width="15">
        <rect height="4" rx="1.2" width="2.4" x="4" y="10" />
        <rect height="10" rx="1.2" width="2.4" x="8.4" y="7" />
        <rect height="15" rx="1.2" width="2.4" x="12.8" y="4.5" />
        <rect height="6" rx="1.2" width="2.4" x="17.2" y="9" />
      </svg>
    </button>
  );

  return (
    <button
      aria-label={props.busy ? "Queue next ↑" : "Send ↑"}
      className="send-button"
      disabled={props.disabled || !props.value.trim() || !props.modelReady}
      title={!props.modelReady
        ? props.defaultModelUnavailableReason ?? "Choose an available model"
        : props.busy ? "Queue next" : "Send"}
      type="submit"
    >
      <svg aria-hidden fill="none" height="14" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.3" viewBox="0 0 24 24" width="14">
        <line x1="12" x2="12" y1="19" y2="5" />
        <polyline points="5 12 12 5 19 12" />
      </svg>
    </button>
  );
}

function ComposerContext({ runtime }: { runtime: ApprovalRuntime }) {
  if (runtime === "local") return (
    <div className="composer-context" aria-label="Local task context">
      <span className="composer-context-item">
        <span aria-hidden className="composer-plugin-stack"><i>⌘</i></span>
        <span>Local workspace</span>
      </span>
      <span className="composer-context-hint">Cloud plugins are not connected</span>
    </div>
  );
  return (
    <div className="composer-context" aria-label="Task context">
      <button className="composer-context-item" onClick={() => navigate("integrations")} type="button">
        <span aria-hidden className="composer-plugin-stack"><i>P</i><i>＋</i></span>
        <span>Plugins</span>
      </button>
      <span className="composer-context-hint">Everything it does is recorded</span>
    </div>
  );
}
