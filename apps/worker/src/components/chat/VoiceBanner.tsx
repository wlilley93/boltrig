import { useState } from "react";

const DISMISS_KEY = "boltrig-worker-voice-banner-dismissed";

function readDismissed(): boolean {
  try {
    return localStorage.getItem(DISMISS_KEY) === "true";
  } catch {
    return false;
  }
}

/** The "Try boltrig Voice" invitation above the New-state composer. Rendered
 * only when the caller has verified live voice is actually reachable; the
 * dismissal persists locally (it is a piece of chrome, not account state). */
export function VoiceBanner({ onStartVoice }: { onStartVoice(): void }) {
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
    <div className="voice-banner">
      <span aria-hidden className="voice-banner-mark">
        <svg fill="currentColor" height="15" viewBox="0 0 24 24" width="15">
          <rect height="4" rx="1.2" width="2.4" x="4" y="10" />
          <rect height="10" rx="1.2" width="2.4" x="8.4" y="7" />
          <rect height="15" rx="1.2" width="2.4" x="12.8" y="4.5" />
          <rect height="6" rx="1.2" width="2.4" x="17.2" y="9" />
        </svg>
      </span>
      <span className="voice-banner-copy">
        <span>Try boltrig Voice</span>
        <small>Talk it through and it starts working while you speak</small>
      </span>
      <button className="voice-banner-start" onClick={onStartVoice} type="button">
        Start voice
      </button>
      <button
        aria-label="Dismiss the voice banner"
        className="voice-banner-dismiss"
        onClick={dismiss}
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
