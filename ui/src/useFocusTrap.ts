// Accessible modal plumbing shared by the Run drawer and the Command palette.
// On open it moves focus into the container and remembers what was focused
// before; while open it keeps Tab / Shift-Tab inside the container (so keyboard
// users can't tab out to the page behind the modal); on close it restores focus
// to the element that opened it. Pass `active` so the same hook can guard a
// modal that mounts conditionally vs one that is always mounted.

import { RefObject, useEffect } from "react";

const FOCUSABLE =
  'a[href],area[href],button:not([disabled]),input:not([disabled]),' +
  'select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

function focusable(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) => el.offsetParent !== null || el === document.activeElement,
  );
}

export function useFocusTrap(
  ref: RefObject<HTMLElement>,
  active: boolean = true,
): void {
  useEffect(() => {
    if (!active) return;
    const container = ref.current;
    if (!container) return;

    const previouslyFocused = document.activeElement as HTMLElement | null;

    // Move focus inside: the first focusable child, else the container itself.
    const first = focusable(container)[0];
    (first ?? container).focus();

    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== "Tab") return;
      const items = focusable(container as HTMLElement);
      if (items.length === 0) {
        e.preventDefault(); // nothing to move to - stay put
        return;
      }
      const firstEl = items[0];
      const lastEl = items[items.length - 1];
      const activeEl = document.activeElement;
      if (e.shiftKey && (activeEl === firstEl || !container!.contains(activeEl))) {
        e.preventDefault();
        lastEl.focus();
      } else if (!e.shiftKey && activeEl === lastEl) {
        e.preventDefault();
        firstEl.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      // Restore focus to the opener if it is still in the document.
      if (previouslyFocused && document.contains(previouslyFocused)) {
        previouslyFocused.focus();
      }
    };
  }, [ref, active]);
}
