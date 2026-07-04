import type { ChatAgent } from "@/panels/chat/constants";
import { Icon } from "@/panels/chat/icons";

interface VoiceOverlayProps {
  agent: ChatAgent;
  seconds: number;
  muted: boolean;
  speaker: boolean;
  onMute: () => void;
  onSpeaker: () => void;
  onEnd: () => void;
}

export function VoiceOverlay({
  agent,
  seconds,
  muted,
  speaker,
  onMute,
  onSpeaker,
  onEnd,
}: VoiceOverlayProps): JSX.Element {
  const mm = String(Math.floor(seconds / 60)).padStart(2, "0");
  const ss = String(seconds % 60).padStart(2, "0");

  return (
    <div className="voice-overlay" role="dialog" aria-modal="true" aria-label="Voice call">
      <div className="voice-card">
        <div className="voice-card__mic">
          <span />
          <span />
          <Icon name="mic" size={28} />
        </div>
        <h2>Voice call active</h2>
        <p>
          {agent.name} - governed by the same kernel policy
        </p>
        <code>{mm}:{ss}</code>
        <div className="voice-card__transcript" aria-label="Live transcript">
          <p><strong>You</strong> Review the release run.</p>
          <p><strong>{agent.name}</strong> Reading the active transcript and receipts.</p>
        </div>
        <div className="voice-card__controls">
          <button
            className={muted ? "voice-card__toggle voice-card__toggle--off" : "voice-card__toggle"}
            onClick={onMute}
            type="button"
          >
            Mute
          </button>
          <button className="voice-card__end" onClick={onEnd} type="button" aria-label="End call">
            <Icon name="phone" size={22} />
          </button>
          <button
            className={speaker ? "voice-card__toggle voice-card__toggle--on" : "voice-card__toggle"}
            onClick={onSpeaker}
            type="button"
          >
            Speaker
          </button>
        </div>
      </div>
    </div>
  );
}

export { type VoiceOverlayProps };
