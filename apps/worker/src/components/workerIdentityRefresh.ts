import { useEffect } from "react";

/** Keep shell authority current when another authenticated session changes it. */
export function useIdentityRefreshLifecycle(
  refreshIdentity: () => Promise<void>,
  changedEvent: string,
) {
  useEffect(() => {
    const refresh = () => {
      void refreshIdentity();
    };
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") refresh();
    };

    refresh();
    window.addEventListener(changedEvent, refresh);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      window.removeEventListener(changedEvent, refresh);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [changedEvent, refreshIdentity]);
}
