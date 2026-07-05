// 📖 Docs: obsidian/frontend/components/common.md
"use client";

import { useEffect, useRef } from "react";

// ESC closes; lock Lenis scroll while open; restore focus to the opener.
export function useModalDismiss(
  open: boolean,
  closeModal: () => void,
  stopScroll: () => void,
  startScroll: () => void,
) {
  const triggerRef = useRef<Element | null>(null);

  useEffect(() => {
    if (!open) return;
    triggerRef.current = document.activeElement;
    stopScroll();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeModal();
    };
    window.addEventListener("keydown", onKey);

    return () => {
      window.removeEventListener("keydown", onKey);
      startScroll();
      const t = triggerRef.current as HTMLElement | null;
      if (t && typeof t.focus === "function") t.focus();
    };
  }, [open, closeModal, stopScroll, startScroll]);
}
