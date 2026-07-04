import type { Speech } from "@/voice";
import { Icon } from "@/panels/chat/icons";

interface SpeakButtonProps {
  speech: Speech;
  msgKey: string;
  text: string;
  iconOnly?: boolean;
}

// A per-message "read aloud" control (only for assistant text, and only when
// the browser supports speechSynthesis). Speaks that message on demand and
// toggles to Stop while it is the one being spoken.
export function SpeakButton({ speech, msgKey, text, iconOnly = false }: SpeakButtonProps): JSX.Element | null {
  if (!speech.supported || !text.trim()) return null;
  const speaking = speech.speakingKey === msgKey;

  return (
    <button
      type="button"
      className={iconOnly ? "btn btn--ghost btn--sm chat-msg__action--icon" : "btn btn--ghost btn--sm"}
      aria-pressed={speaking}
      aria-label={speaking ? "Stop reading" : "Read aloud"}
      style={iconOnly ? { width: 26, height: 26 } : undefined}
      onClick={() => (speaking ? speech.cancel() : speech.speak(msgKey, text))}
    >
      {iconOnly ? <Icon name="speaker" size={16} /> : speaking ? "Stop" : "Read aloud"}
    </button>
  );
}

export { type SpeakButtonProps };
