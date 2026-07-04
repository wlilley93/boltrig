import { useEffect, useRef } from "react";

import { getRoute, navigate } from "@/router";
import { editingContext, navTarget, type DeckRow, type Dir } from "@/deck/types";

const DIRS: Record<string, Dir> = {
  ArrowLeft: "left",
  ArrowRight: "right",
  ArrowUp: "up",
  ArrowDown: "down",
};

export function useDeckNavigation(rows: DeckRow[], activeKey: string, bump: (dir: Dir) => void) {
  // latest props for window-level handlers and late settle callbacks
  const latest = useRef({ rows, activeKey });
  latest.current = { rows, activeKey };

  const tryMove = (dir: Dir) => {
    const { rows: rs, activeKey: key } = latest.current;
    const t = navTarget(rs, key, dir);
    if (t) navigate(t.path);
    else bump(dir);
  };

  // Deck keys: Ctrl+Alt+Arrow (Cmd+Alt on mac). Plain Alt+Arrow stays with the
  // browser so history back / forward keeps working (and animates via the route).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const dir = DIRS[e.key];
      if (!dir) return;
      if (!e.altKey || !(e.ctrlKey || e.metaKey)) return;
      if (e.defaultPrevented) return;
      if (editingContext()) return;
      if (document.querySelector(".cmdk-overlay")) return; // command palette open
      if (getRoute().runId) return; // run drawer open
      e.preventDefault();
      tryMove(dir);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // tryMove reads only refs, so the mount-time closure stays correct
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { tryMove };
}
