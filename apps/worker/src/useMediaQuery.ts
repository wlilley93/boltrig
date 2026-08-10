import { useEffect, useState } from "react";
import { flushSync } from "react-dom";

// Extracted from ChatView so App can read a breakpoint without importing the
// chat surface. Importing it from ChatView made every test that mocks ChatView
// fail on a missing export, which is a coupling the hook never needed.
export function useMediaQuery(query: string): boolean {
  const matches = () => (
    typeof window !== "undefined"
    && typeof window.matchMedia === "function"
    && window.matchMedia(query).matches
  );
  const [matched, setMatched] = useState(matches);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(query);
    // Commit breakpoint flips synchronously inside the media-change event.
    // A deferred commit leaves a window where the layout has crossed the
    // breakpoint but the old surface is still mounted; anything measuring
    // the page across that window (assistive tech re-querying, the browser
    // acceptance suite's geometry checks) can catch a control mid-detach.
    const onChange = (event: MediaQueryListEvent) => flushSync(() => setMatched(event.matches));
    setMatched(media.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [query]);

  return matched;
}
