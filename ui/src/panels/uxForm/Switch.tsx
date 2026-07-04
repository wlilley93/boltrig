import { useCallback, useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";

// --- N1 Switch: instant-apply boolean (P2). ---------------------------------
// Only for settings where both states are safe and the write applies at once;
// booleans with governance weight stay SegmentedV2 inside a saved form. The
// caller owns the instant-apply contract (optimistic set, busy while
// persisting, revert + faithful error on failure); this renders the states.
export function Switch({
  checked,
  onChange,
  label,
  hint,
  disabled = false,
  busy = false,
  wisp,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: ReactNode;
  hint?: ReactNode;
  disabled?: boolean;
  busy?: boolean;
  // the useSavedWisp node, rendered beside the control on successful persist
  wisp?: ReactNode;
}) {
  const labelId = useId();
  const hintId = useId();
  return (
    <div className={`ux-switch ${busy ? "ux-switch--busy" : ""}`}>
      <span className="ux-switch__text">
        <span className="ux-switch__label" id={labelId}>
          {label}
        </span>
        {hint != null && (
          <span className="ux-switch__hint" id={hintId}>
            {hint}
          </span>
        )}
      </span>
      {wisp}
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={labelId}
        aria-describedby={hint != null ? hintId : undefined}
        aria-busy={busy || undefined}
        className="ux-switch__ctl"
        disabled={disabled || busy}
        onClick={() => onChange(!checked)}
      >
        <span className="ux-switch__thumb" aria-hidden="true" />
      </button>
    </div>
  );
}

// --- N1 companion: the transient "Saved" wisp (P16 autosave affirmation). ---
// Returns [node, trigger]. Render the node where the confirmation should
// appear (e.g. the Switch wisp slot) and call trigger() after a successful
// persist. Fade uses a transition only, so the global reduce-motion rules
// quiet it; the timer (not the animation) removes the text, so the wisp still
// clears when motion is zeroed.
export function useSavedWisp(text: string = "Saved"): [ReactNode, () => void] {
  const [shown, setShown] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const trigger = useCallback(() => {
    setShown(true);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setShown(false), 1800);
  }, []);
  const node = (
    <span className={`ux-wisp ${shown ? "ux-wisp--on" : ""}`} role="status">
      {shown ? text : ""}
    </span>
  );
  return [node, trigger];
}
