import {
  type ClipboardEvent,
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

import { modelUnavailableCopy } from "./modelAvailabilityCopy";

import { navigate } from "../../routes";
import {
  ApprovalPostureMenu,
  type ApprovalRuntime,
} from "../ApprovalPostureControl";
import { ModelChip } from "./ModelChip";
import { ComposerAddMenu } from "./ComposerAddMenu";
import {
  AttachmentStatus,
  useComposerAttachmentIngress,
  useComposerAttachments,
} from "./ComposerAttachments";

export interface ComposerProps {
  busy: boolean;
  disabled: boolean;
  closed: boolean;
  /** Resets staged, conversation-owned inputs without remounting VoiceCall. */
  conversationKey: string | null;
  modelChoices: ChatModelChoice[];
  modelChoice: string;
  defaultModelName?: string | null;
  defaultModelSource?: "personal" | "platform";
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
  /** A known disabled runtime must not masquerade as an in-progress load. */
  disabledPlaceholder?: string;
  onCommandPalette?(): void;
}

export function Composer(props: ComposerProps) {
  const staged = useComposerAttachments(props.conversationKey, props.attachmentLimits);
  const ingress = useComposerAttachmentIngress({
    addFiles: staged.addFiles,
    addText: staged.addText,
    enabled: !props.attachmentsDisabled && !props.disabled && !props.closed,
  });
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
    <form
      className={`composer${props.closed ? " closed" : ""}${props.newContext ? " new-context" : " conversation-context"}`}
      data-drop-active={ingress.dragActive ? "true" : undefined}
      onSubmit={submit}
    >
      {props.newContext && <ComposerContext runtime={props.agentRuntime ?? "cloud"} />}
      <div className="composer-frame">
        {ingress.dragActive && <ComposerDropTarget />}
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
        <ComposerTextarea {...props} onPaste={ingress.onPaste} />
        <ComposerTools
          {...props}
          addFiles={staged.addFiles}
          fileInputRef={staged.input}
          modelReady={modelReady}
          voicePrimaryVisible={voicePrimaryVisible}
        />
      </div>
    </form>
  );
}

function ComposerTextarea(props: ComposerProps & {
  onPaste(event: ClipboardEvent<HTMLTextAreaElement>): void;
}) {
  return (
    <textarea
      aria-label="Task instructions"
      placeholder={
        props.closed
          ? "This conversation is closed"
          : props.unavailable
            ? "Conversation unavailable — retry above"
          : props.disabled
            ? props.disabledPlaceholder ?? "Loading conversation state…"
            : "Describe the work"
      }
      disabled={props.disabled}
      ref={props.inputRef}
      value={props.value}
      onChange={(event) => props.onChange(event.target.value)}
      onPaste={props.onPaste}
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

function ComposerDropTarget() {
  return (
    <div aria-live="polite" className="composer-drop-target" role="status">
      <svg aria-hidden fill="none" height="22" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" viewBox="0 0 24 24" width="22">
        <path d="M12 16V4" /><polyline points="7 9 12 4 17 9" />
        <path d="M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4" />
      </svg>
      <strong>Drop to attach</strong>
      <small>Files, media, or text</small>
    </div>
  );
}

type ComposerToolsProps = ComposerProps & {
  addFiles(list: FileList | readonly File[] | null): Promise<boolean>;
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
            defaultModelSource={props.defaultModelSource}
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
      <ComposerAddMenu
        attachmentsDisabled={props.attachmentsDisabled}
        disabled={props.disabled}
        onAttach={() => props.fileInputRef.current?.click()}
        onOpenCommands={props.onCommandPalette}
      />
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
          <svg aria-hidden fill="none" height="16" stroke="currentColor" strokeLinecap="round" strokeWidth="2.2" viewBox="0 0 24 24" width="16">
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
        ? modelUnavailableCopy(props.defaultModelUnavailableReason)
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
