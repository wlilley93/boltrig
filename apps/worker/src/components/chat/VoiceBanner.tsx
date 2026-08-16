import { useState, type ReactNode } from "react";

const DISMISS_KEY = "boltrig-worker-voice-banner-dismissed";

function readDismissed(): boolean {
  try {
    return localStorage.getItem(DISMISS_KEY) === "true";
  } catch {
    return false;
  }
}

interface VoiceBannerProps {
  companionName: string;
  identity: ReactNode;
  onStartVoice(): void;
}

/** The live-voice invitation that sits immediately above the New-task input.
 * The caller supplies the active companion identity; dismissal is local
 * presentation state and never changes voice availability or account state. */
export function VoiceBanner({ companionName, identity, onStartVoice }: VoiceBannerProps) {
  const [dismissed, setDismissed] = useState(readDismissed);
  if (dismissed) return null;

  function dismiss() {
    setDismissed(true);
    try {
      localStorage.setItem(DISMISS_KEY, "true");
    } catch {
      // Storage is optional; the banner still hides for this session.
    }
  }

  return (
    <div className="voice-intro">
      {identity}
      <span className="voice-intro-copy">
        <strong>Talk to {companionName}</strong>
        <small>Say it out loud and it starts while you speak</small>
      </span>
      <button
        aria-label="Start voice chat"
        className="voice-intro-start"
        onClick={onStartVoice}
        type="button"
      >
        Start
      </button>
      <button
        aria-label="Not now"
        className="voice-intro-dismiss"
        onClick={dismiss}
        title="Not now"
        type="button"
      >
        <svg fill="none" height="12" stroke="currentColor" strokeLinecap="round" strokeWidth="2.3" viewBox="0 0 24 24" width="12">
          <line x1="6" x2="18" y1="6" y2="18" />
          <line x1="18" x2="6" y1="6" y2="18" />
        </svg>
      </button>
    </div>
  );
}
