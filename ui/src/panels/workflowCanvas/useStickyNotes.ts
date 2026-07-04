// Persistence for canvas sticky notes (design brief sec 22.10). Notes are stored
// per-workflow in localStorage so documentation annotations survive a reload,
// without changing the backend workflow definition shape. Falls back to empty
// when storage is unavailable (private mode / quota).

import { useCallback, useEffect, useState } from "react";
import type { StickyNote } from "./StickyNotes";

const BLANK: StickyNote[] = [];

function storageKey(wfId: string): string {
  return `boltrig:wf-notes:${wfId}`;
}

function readNotes(wfId: string): StickyNote[] {
  if (!wfId) return BLANK;
  try {
    const raw = window.localStorage.getItem(storageKey(wfId));
    if (!raw) return BLANK;
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return BLANK;
    return parsed.filter(isStickyNote);
  } catch {
    return BLANK;
  }
}

function isStickyNote(v: unknown): v is StickyNote {
  if (!v || typeof v !== "object") return false;
  const n = v as Record<string, unknown>;
  return (
    typeof n.id === "string" &&
    typeof n.x === "number" &&
    typeof n.y === "number" &&
    typeof n.text === "string"
  );
}

export function useStickyNotes(wfId: string): [StickyNote[], (notes: StickyNote[]) => void] {
  const [notes, setNotes] = useState<StickyNote[]>(() => readNotes(wfId));

  useEffect(() => {
    setNotes(readNotes(wfId));
  }, [wfId]);

  const save = useCallback(
    (next: StickyNote[]) => {
      setNotes(next);
      if (!wfId) return;
      try {
        window.localStorage.setItem(storageKey(wfId), JSON.stringify(next));
      } catch {
        // Storage full or disabled: keep the in-memory copy only.
      }
    },
    [wfId],
  );

  return [notes, save];
}
