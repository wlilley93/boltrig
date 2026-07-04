import { useLayoutEffect, useRef, useState } from "react";

import { getRoute } from "@/router";
import {
  FADE_MS,
  SLIDE_MS,
  findCell,
  motionOff,
  type DeckRow,
  type Dir,
} from "@/deck/types";
import { useDeckSettle } from "./useDeckSettle";

type MutableRefObject<T> = React.MutableRefObject<T>;

export function useDeckTransition({
  rows,
  activeKey,
  tx,
  ty,
  planeRef,
  deckRef,
  frames,
}: {
  rows: DeckRow[];
  activeKey: string;
  tx: number;
  ty: number;
  planeRef: MutableRefObject<HTMLDivElement | null>;
  deckRef: MutableRefObject<HTMLDivElement | null>;
  frames: MutableRefObject<Map<string, HTMLDivElement>>;
}) {
  const [moving, setMoving] = useState(false);
  const [settledKey, setSettledKey] = useState(activeKey);
  const prevPos = useRef<{ key: string; x: number; y: number } | null>(null);

  const { finishMove, armSettle, settleCleanup } = useDeckSettle({
    activeKey,
    planeRef,
    frames,
    deckRef,
    setMoving,
    setSettledKey,
  });

  useLayoutEffect(() => {
    const plane = planeRef.current;
    const target = findCell(rows, activeKey);
    if (!plane || !target) return;
    const apply = () => {
      plane.style.setProperty("--deck-x", String(tx));
      plane.style.setProperty("--deck-y", String(ty));
    };
    const snap = () => {
      plane.style.transition = "none";
      apply();
      void plane.offsetWidth; // flush so restoring the transition does not animate
      plane.style.transition = "";
    };
    const prev = prevPos.current;
    prevPos.current = { key: activeKey, x: tx, y: ty };

    if (!prev) {
      // first paint - position without animating
      snap();
      return;
    }
    if (prev.key === activeKey) {
      // same cell whose indices shifted (a column list changed): re-derive the
      // transform for the same key with the transition suppressed - no lurch.
      if (prev.x !== tx || prev.y !== ty) snap();
      return;
    }
    const dist = Math.abs(tx - prev.x) + Math.abs(ty - prev.y);
    // Unknown tabs and #/runs deep links resolve to the chat anchor with NO
    // animation: a route whose first segment matches no deck cell is one of those.
    const route = getRoute();
    const known = rows.some((r) =>
      r.cols.some((c) => c.path.split("/").filter(Boolean)[0] === route.tab),
    );
    if (dist === 0 || !known || document.visibilityState !== "visible" || (dist > 1 && motionOff())) {
      settleCleanup.current?.();
      snap();
      finishMove();
      return;
    }
    setMoving(true);
    plane.style.willChange = "transform";
    if (dist === 1) {
      plane.style.transition = "";
      apply();
      armSettle(plane, SLIDE_MS, finishMove);
    } else {
      // far or diagonal move: fade the plane out, jump the transform, fade back
      settleCleanup.current?.();
      plane.classList.add("deck__plane--faded");
      const t1 = window.setTimeout(() => {
        snap();
        plane.classList.remove("deck__plane--faded");
        const t2 = window.setTimeout(() => {
          settleCleanup.current = null;
          finishMove();
        }, FADE_MS);
        settleCleanup.current = () => {
          window.clearTimeout(t2);
          settleCleanup.current = null;
        };
      }, FADE_MS);
      settleCleanup.current = () => {
        window.clearTimeout(t1);
        plane.classList.remove("deck__plane--faded");
        settleCleanup.current = null;
      };
    }
    // finishMove and rows are read through refs / only on a keyed move
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeKey, tx, ty]);

  // Boundary feedback: nudge the plane a few px toward the attempted direction.
  // The keyframe folds the base translate back in, so nothing jumps.
  const bump = (dir: Dir) => {
    const plane = planeRef.current;
    if (!plane) return;
    const horizontal = dir === "left" || dir === "right";
    const px = dir === "right" || dir === "down" ? -10 : 10;
    plane.style.setProperty("--deck-bump", `${px}px`);
    const cls = horizontal ? "deck__plane--bump-h" : "deck__plane--bump-v";
    plane.classList.remove("deck__plane--bump-h", "deck__plane--bump-v");
    void plane.offsetWidth; // restart the animation when bumping twice in a row
    plane.classList.add(cls);
    window.setTimeout(() => plane.classList.remove(cls), 260);
  };

  return { moving, settledKey, bump };
}
