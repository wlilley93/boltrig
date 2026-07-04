/* ArmConfirm (N14, P27): two-step arm-confirm, in place.
 * - L4: amber (--color-consequence-high) only where the kernel gate is in play
 *   (PendingHumanCard, the governed SaveBar foreshadow, the consequence tone).
 * - P27/P36: arm-confirm swaps in place; disarms on Escape / Cancel / blur-away
 *   / slide navigation; Enter confirms only on the focused confirm button.
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { useSlideActive } from "@/deck/context";
import { apiReason } from "@/panels/shared";
import { InfoCallout } from "@/panels/ux";

export type ArmTone = "danger" | "warn" | "consequence";

export interface UseArmConfirm {
  armed: boolean;
  busy: boolean;
  // the faithful failure reason of the last confirm attempt (P15); armed stays
  error: string | null;
  arm: () => void;
  disarm: () => void;
  confirm: () => void;
  // Spread onto the element wrapping the armed controls so Escape and
  // blur-away disarm work in row-embedded custom layouts.
  containerProps: {
    ref: (el: HTMLElement | null) => void;
    tabIndex: number;
    onKeyDown: (e: KeyboardEvent<HTMLElement>) => void;
    onBlur: () => void;
  };
}

function useArmConfirmContainer(disarm: () => void, armed: boolean) {
  const elRef = useRef<HTMLElement | null>(null);

  // Focus the container (not the confirm button) so Escape works immediately
  // and Enter cannot land on confirm by default (P36: no default-Enter
  // destruction; Enter confirms only once confirm itself is focused).
  useEffect(() => {
    if (armed) elRef.current?.focus();
  }, [armed]);

  const onKeyDown = useCallback(
    (e: KeyboardEvent<HTMLElement>) => {
      if (e.key === "Escape") {
        e.stopPropagation(); // consumed here; must not also close a drawer
        disarm();
      }
    },
    [disarm],
  );

  // Blur-away disarm, deferred: activeElement settles after the blur event.
  // tabIndex -1 on the container keeps clicks on its own text inside focus.
  const onBlur = useCallback(() => {
    window.setTimeout(() => {
      const el = elRef.current;
      if (el && !el.contains(document.activeElement)) disarm();
    }, 0);
  }, [disarm]);

  const setEl = useCallback((el: HTMLElement | null) => {
    elRef.current = el;
  }, []);

  return { containerProps: { ref: setEl, tabIndex: -1, onKeyDown, onBlur } };
}

export function useArmConfirm(onConfirm: () => Promise<void>): UseArmConfirm {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const busyRef = useRef(false);
  const slideActive = useSlideActive();

  const disarm = useCallback(() => {
    // an in-flight confirm is never yanked out from under the caller
    if (busyRef.current) return;
    setArmed(false);
    setError(null);
  }, []);

  // P27: slide navigation disarms.
  useEffect(() => {
    if (!slideActive) disarm();
  }, [slideActive, disarm]);

  const arm = useCallback(() => {
    setError(null);
    setArmed(true);
  }, []);

  const confirm = useCallback(() => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    onConfirm().then(
      () => {
        busyRef.current = false;
        setBusy(false);
        setArmed(false);
      },
      (err: unknown) => {
        busyRef.current = false;
        setBusy(false);
        setError(apiReason(err));
      },
    );
  }, [onConfirm]);

  const { containerProps } = useArmConfirmContainer(disarm, armed);

  return { armed, busy, error, arm, disarm, confirm, containerProps };
}

export function ArmConfirm({
  label,
  armLabel,
  confirmLabel,
  tone,
  busyLabel,
  onConfirm,
  disabled,
}: {
  label: ReactNode; // rest state: a plain button that states the act
  armLabel: ReactNode; // the restatement sentence (object + effect)
  confirmLabel: ReactNode;
  tone: ArmTone; // danger = local destructive; consequence = kernel-governed
  busyLabel: ReactNode;
  onConfirm: () => Promise<void>;
  disabled?: boolean;
}) {
  const ac = useArmConfirm(onConfirm);
  if (!ac.armed) {
    return (
      <button type="button" className="btn" disabled={disabled} onClick={ac.arm}>
        {label}
      </button>
    );
  }
  return (
    <div className="ux-arm" {...ac.containerProps}>
      <InfoCallout tone={tone === "consequence" ? "consequence" : "warn"}>
        <span>{armLabel}</span>
        {ac.error && (
          <span className="ux-arm__error" role="alert">
            {ac.error}
          </span>
        )}
        <span className="ux-arm__actions">
          <button
            type="button"
            className={`btn ux-btn--${tone}`}
            disabled={ac.busy}
            onClick={ac.confirm}
          >
            {ac.busy ? busyLabel : confirmLabel}
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            disabled={ac.busy}
            onClick={ac.disarm}
          >
            Cancel
          </button>
        </span>
      </InfoCallout>
    </div>
  );
}
