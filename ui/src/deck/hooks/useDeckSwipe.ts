import { useRef } from "react";

import { type Dir } from "@/deck/types";

interface SwipeState {
  id: number;
  startX: number;
  startY: number;
  scrollables: HTMLElement[];
}

export function useDeckSwipe(tryMove: (dir: Dir) => void) {
  // Touch swipe: pointerType touch only, claimed only when clearly horizontal
  // and no element under the finger can scroll that way. No wheel hijack ever.
  const swipe = useRef<SwipeState | null>(null);

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.pointerType !== "touch") return;
    // leave the OS edge (back) gesture alone
    if (e.clientX <= 24 || e.clientX >= window.innerWidth - 24) return;
    const deck = e.currentTarget as HTMLDivElement;
    const path = e.nativeEvent.composedPath();
    const scrollables: HTMLElement[] = [];
    for (const t of path) {
      if (!(t instanceof HTMLElement)) continue;
      if (t === deck) break;
      const tag = t.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (t.isContentEditable) return;
      if (t.classList.contains("react-flow")) return;
      if (t.scrollWidth > t.clientWidth + 1) scrollables.push(t);
    }
    swipe.current = { id: e.pointerId, startX: e.clientX, startY: e.clientY, scrollables };
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const s = swipe.current;
    if (!s || e.pointerId !== s.id) return;
    const dx = e.clientX - s.startX;
    const dy = e.clientY - s.startY;
    if (Math.abs(dx) <= 48 || Math.abs(dx) <= 2 * Math.abs(dy)) return;
    swipe.current = null; // decided: claim or yield exactly once per gesture
    for (const el of s.scrollables) {
      const room =
        dx < 0 ? el.scrollLeft + el.clientWidth < el.scrollWidth - 1 : el.scrollLeft > 0;
      if (room) return; // the content still has scroll room - not our gesture
    }
    tryMove(dx < 0 ? "right" : "left");
  };

  const onPointerEnd = (e: React.PointerEvent) => {
    if (swipe.current && e.pointerId === swipe.current.id) swipe.current = null;
  };

  return {
    onPointerDown,
    onPointerMove,
    onPointerUp: onPointerEnd,
    onPointerCancel: onPointerEnd,
  };
}
