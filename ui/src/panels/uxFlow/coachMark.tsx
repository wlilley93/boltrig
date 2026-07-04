/** CoachMark (N12, P21 rung 5): one-time, persisted, never re-shown. */

import { useState, type ReactNode } from "react";
import { InfoCallout } from "@/panels/ux";

export function CoachMark({ id, children }: { id: string; children: ReactNode }) {
  const storageKey = `boltrig.coach.${id}`;
  const [dismissed, setDismissed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(storageKey) !== null;
    } catch {
      return false; // storage unavailable: session-only dismissal below
    }
  });
  if (dismissed) return null;
  const dismiss = () => {
    try {
      localStorage.setItem(storageKey, "1");
    } catch {
      // storage unavailable: the state below still hides it for this session
    }
    setDismissed(true);
  };
  return (
    <div className="ux-coach">
      <InfoCallout tone="info">
        <div>{children}</div>
        <span className="ux-coach__actions">
          <button type="button" className="btn btn--sm btn--ghost" onClick={dismiss}>
            Got it
          </button>
        </span>
      </InfoCallout>
    </div>
  );
}
