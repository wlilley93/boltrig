import { useLayoutEffect, type MutableRefObject, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { CallStatus } from "@wlilley93/boltrig-web-sdk";

export interface VoiceLine {
  id: string;
  speaker: "You" | "Boltrig";
  text: string;
  typed?: boolean;
}

interface VoiceCallScreenProps {
  approvalCount: number;
  characterMuted: boolean;
  characterName: string;
  conversationTitle?: string;
  eventNotice: string;
  lines: VoiceLine[];
  microphoneMuted: boolean;
  noticeVisible: boolean;
  onDismissNotice(): void;
  onLeave(): void;
  onReconnect(): void;
  onSendText(): void;
  onTextChange(value: string): void;
  onToggleCharacterMute(): void;
  onToggleMicrophoneMute(): void;
  reconnectLabel: string | null;
  screenRef: MutableRefObject<HTMLElement | null>;
  stage: ReactNode;
  status: CallStatus | "idle";
  textDraft: string;
}

export function VoiceCallScreen(props: VoiceCallScreenProps) {
  useLayoutEffect(() => {
    if (typeof document === "undefined") return;
    document.body.classList.add("voice-call-present");
    const animationFrame = window.requestAnimationFrame(() => {
      document.body.classList.add("voice-call-animate");
    });
    return () => {
      window.cancelAnimationFrame(animationFrame);
      document.body.classList.remove("voice-call-present", "voice-call-animate");
    };
  }, []);

  const screen = (
    <section
      aria-label="Voice call"
      aria-modal="true"
      className="voice-call-screen"
      data-screen-label="Call"
      ref={(node) => { props.screenRef.current = node; }}
      role="dialog"
      tabIndex={-1}
    >
      <CallScreenHeader {...props} />
      <CallScreenBody {...props} />
      <CallScreenFooter {...props} />
    </section>
  );
  return typeof document === "undefined" ? screen : createPortal(screen, document.body);
}

function CallScreenHeader(props: VoiceCallScreenProps) {
  return <header className="voice-call-screen-header">
    <button className="voice-call-leave" onClick={props.onLeave} type="button">Leave</button>
  </header>;
}

function CallScreenBody(props: VoiceCallScreenProps) {
  return <div className="voice-call-freezone">
    {props.noticeVisible && props.approvalCount > 0 && <CallNotice {...props} />}
    <div className="voice-call-presence">
      <div className="voice-call-primary-familiar">{props.stage}</div>
    </div>
    <div className="voice-call-transcript-sr">
      <p>{props.conversationTitle ? `Voice call for ${props.conversationTitle}` : "Voice call"}</p>
      <p aria-live="polite">{voiceStatus(props.status)}</p>
      {props.eventNotice && !(props.noticeVisible && props.approvalCount > 0)
        && <p role="status">{props.eventNotice}</p>}
      <VoiceTranscript lines={props.lines} />
    </div>
  </div>;
}

function CallNotice(props: VoiceCallScreenProps) {
  return <article
    className="voice-call-notice"
    data-urgent={props.approvalCount > 0 ? "true" : "false"}
    role="status"
  >
    <div className="voice-call-notice-header">
      <span>Approval required</span>
      <button aria-label="Dismiss call notice" onClick={props.onDismissNotice} type="button">
        ×
      </button>
    </div>
    <p>{props.eventNotice}</p>
  </article>;
}

function CallScreenFooter(props: VoiceCallScreenProps) {
  return <footer className="voice-call-screen-footer">
    <div className="voice-call-controls">
      <CallTextBar {...props} />
      <button
        aria-pressed={props.microphoneMuted}
        onClick={props.onToggleMicrophoneMute}
        type="button"
      >
        {props.microphoneMuted ? "Unmute me" : "Mute me"}
      </button>
      <button
        aria-pressed={props.characterMuted}
        onClick={props.onToggleCharacterMute}
        type="button"
      >
        {props.characterMuted ? `Hear ${props.characterName}` : `Silence ${props.characterName}`}
      </button>
    </div>
  </footer>;
}

function CallTextBar(props: VoiceCallScreenProps) {
  const enabled = props.status === "active" || props.status === "held";
  const reconnecting = Boolean(props.reconnectLabel);
  return <form
    className="voice-call-text"
    onSubmit={(event) => {
      event.preventDefault();
      if (reconnecting) props.onReconnect();
      else props.onSendText();
    }}
  >
    <input
      aria-label="Type a message to the call"
      disabled={!enabled}
      onChange={(event) => props.onTextChange(event.target.value)}
      placeholder={enabled ? "Type a message…" : "Connecting the call…"}
      value={props.textDraft}
    />
    <button
      disabled={reconnecting ? false : !props.textDraft.trim() || !enabled}
      type="submit"
    >
      {props.reconnectLabel ?? "Send"}
    </button>
  </form>;
}

export function VoiceTranscript({ lines }: { lines: VoiceLine[] }) {
  if (lines.length === 0) return null;
  return <div className="voice-transcript" aria-label="Call transcript">
    {lines.map((line) => <p key={line.id}><b>{line.speaker}:</b> {line.text}</p>)}
  </div>;
}

function voiceStatus(status: CallStatus | "idle") {
  if (status === "active") return "Live voice";
  if (status === "held") return "Waiting for approval";
  if (status === "joining") return "Joining…";
  if (status === "reconnecting") return "Connection paused";
  if (status === "failed") return "Call interrupted";
  if (status === "ended") return "Call ended";
  return "Preparing voice…";
}
