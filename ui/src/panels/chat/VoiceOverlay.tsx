import { useEffect, useRef, useState } from "react";

import type { ChatAgent } from "@/panels/chat/constants";
import { cssVarColor } from "@/panels/chat/formatting";
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

type TranscriptRole = "user" | "agent";

interface TranscriptLine {
  role: TranscriptRole;
  text: string;
}

// Simulated live transcript (sec 12, line 339). Revealed one line at a time via
// a setTimeout chain while the call is active; timers are cleared on unmount.
export const VOICE_TRANSCRIPT_QUEUE: readonly TranscriptLine[] = [
  { role: "user", text: "Review the 2.14 release run." },
  { role: "agent", text: "Reading the active transcript and tool receipts now." },
  { role: "user", text: "Is the tag cut yet?" },
  { role: "agent", text: "Yes, v2.14.0 is tagged. Opening the release PR against main." },
  { role: "user", text: "Notify the channel once it merges." },
  { role: "agent", text: "Queued. I'll post to #releases the moment CI is green." },
] as const;

const TRANSCRIPT_FIRST_MS = 900;
const TRANSCRIPT_STEP_MS = 1500;

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

  const [revealed, setRevealed] = useState(1);
  const timers = useRef<Array<ReturnType<typeof setTimeout>>>([]);

  useEffect(() => {
    let delay = TRANSCRIPT_FIRST_MS;
    for (let i = 1; i < VOICE_TRANSCRIPT_QUEUE.length; i++) {
      const index = i;
      const handle = setTimeout(() => {
        setRevealed((prev) => Math.max(prev, index + 1));
      }, delay);
      timers.current.push(handle);
      delay += TRANSCRIPT_STEP_MS;
    }
    return () => {
      for (const h of timers.current) clearTimeout(h);
      timers.current = [];
    };
  }, []);

  const lines = VOICE_TRANSCRIPT_QUEUE.slice(0, revealed);

  return (
    <div className="voice-overlay" role="dialog" aria-modal="true" aria-label="Voice call">
      <div className="voice-card" style={cssVarColor("--agent-color", agent.color)}>
        <div className="voice-card__mic">
          <span />
          <span />
          <span />
          <Icon name="mic" size={28} />
        </div>
        <h2>Voice call active</h2>
        <p>
          {agent.name} - governed by the same kernel policy
        </p>
        <code>{mm}:{ss}</code>
        <div className="voice-card__transcript" aria-label="Live transcript" aria-live="polite">
          {lines.map((line, i) => (
            <p key={i} className={`voice-card__line voice-card__line--${line.role}`}>
              <span className="voice-card__line-label">{line.role === "user" ? "You" : agent.name}</span>
              <span>{line.text}</span>
            </p>
          ))}
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
