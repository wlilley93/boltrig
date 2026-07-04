import { useCallback, useEffect, useRef } from "react";

type MutableRefObject<T> = React.MutableRefObject<T>;

export function useDeckSettle({
  activeKey,
  planeRef,
  frames,
  deckRef,
  setMoving,
  setSettledKey,
}: {
  activeKey: string;
  planeRef: MutableRefObject<HTMLDivElement | null>;
  frames: MutableRefObject<Map<string, HTMLDivElement>>;
  deckRef: MutableRefObject<HTMLDivElement | null>;
  setMoving: (v: boolean) => void;
  setSettledKey: (v: string) => void;
}) {
  const settleCleanup = useRef<(() => void) | null>(null);

  const finishMove = useCallback(() => {
    setMoving(false);
    setSettledKey(activeKey);
    const plane = planeRef.current;
    if (plane) plane.style.willChange = "";
    // focus first; the outgoing slide only goes inert on the re-render that
    // follows (React batches the state writes above until this handler exits).
    // Guard: only claim focus when it is not parked somewhere outside the deck
    // (e.g. a sidebar item mid keyboard navigation).
    const frame = frames.current.get(activeKey);
    const ae = document.activeElement;
    const deck = deckRef.current;
    if (frame && (!ae || ae === document.body || (deck && deck.contains(ae)))) {
      frame.focus({ preventScroll: true });
    }
  }, [activeKey, planeRef, frames, deckRef, setMoving, setSettledKey]);

  const armSettle = useCallback((plane: HTMLElement, ms: number, done: () => void) => {
    const wasPending = settleCleanup.current !== null;
    settleCleanup.current?.();
    let fired = false;
    let skipCancel = wasPending;
    const cleanup = () => {
      plane.removeEventListener("transitionend", onEnd);
      plane.removeEventListener("transitioncancel", onEnd);
      window.clearTimeout(timer);
    };
    const finish = () => {
      if (fired) return;
      fired = true;
      cleanup();
      settleCleanup.current = null;
      done();
    };
    const onEnd = (ev: TransitionEvent) => {
      if (ev.target !== plane || ev.propertyName !== "transform") return;
      if (ev.type === "transitioncancel" && skipCancel) {
        skipCancel = false;
        return;
      }
      finish();
    };
    const timer = window.setTimeout(finish, ms + 80);
    plane.addEventListener("transitionend", onEnd);
    plane.addEventListener("transitioncancel", onEnd);
    settleCleanup.current = () => {
      cleanup();
      settleCleanup.current = null;
    };
  }, []);

  // cancel any pending settle on unmount
  useEffect(() => () => settleCleanup.current?.(), []);

  return { finishMove, armSettle, settleCleanup };
}
