// Client-side persistence for the Files panel Pinned and Recent sections
// (design brief sec 13.2). Pinned files are user-curated references; Recent is
// an auto-history of files seen across sessions. Both live in localStorage so
// the structure is genuine (not placeholder) and survives a reload, with no
// backend seam. Falls back to empty when storage is unavailable (private mode
// or quota), mirroring the defensive try/catch style of useStickyNotes.

import { useCallback, useEffect, useState } from "react";

const PINNED_KEY = "boltrig:pinned-files";
const RECENT_KEY = "boltrig:recent-files";

// Recent is a rolling window of the most recently seen files (brief sec 13.2).
const RECENT_CAP = 12;

const BLANK_PINNED: PinnedFile[] = [];
const BLANK_RECENT: RecentFile[] = [];

export interface PinnedFile {
  id: string;
  name: string;
  size: number;
  agent: string;
  pinnedAt: number;
}

export interface RecentFile {
  id: string;
  name: string;
  size: number;
  agent: string;
  seenAt: number;
}

// Minimal input shape for pin/trackRecent: callers supply the file identity and
// provenance; the hook stamps pinnedAt/seenAt itself.
export interface FileRef {
  id: string;
  name: string;
  size: number;
  agent: string;
}

export interface FilesStore {
  pinned: PinnedFile[];
  recent: RecentFile[];
  pin: (file: FileRef) => void;
  unpin: (id: string) => void;
  trackRecent: (file: FileRef) => void;
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null;
}

function isPinnedFile(v: unknown): v is PinnedFile {
  if (!isRecord(v)) return false;
  return (
    typeof v.id === "string" &&
    typeof v.name === "string" &&
    typeof v.size === "number" &&
    typeof v.agent === "string" &&
    typeof v.pinnedAt === "number"
  );
}

function isRecentFile(v: unknown): v is RecentFile {
  if (!isRecord(v)) return false;
  return (
    typeof v.id === "string" &&
    typeof v.name === "string" &&
    typeof v.size === "number" &&
    typeof v.agent === "string" &&
    typeof v.seenAt === "number"
  );
}

function readList<T>(key: string, guard: (v: unknown) => v is T, fallback: T[]): T[] {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return fallback;
    return parsed.filter(guard);
  } catch {
    return fallback;
  }
}

function writeList(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage full or disabled: keep the in-memory copy only.
  }
}

export function useFilesStore(): FilesStore {
  const [pinned, setPinned] = useState<PinnedFile[]>(() =>
    readList<PinnedFile>(PINNED_KEY, isPinnedFile, BLANK_PINNED),
  );
  const [recent, setRecent] = useState<RecentFile[]>(() =>
    readList<RecentFile>(RECENT_KEY, isRecentFile, BLANK_RECENT),
  );

  // Re-hydrate on mount in case another tab wrote while we were closed.
  useEffect(() => {
    setPinned(readList<PinnedFile>(PINNED_KEY, isPinnedFile, BLANK_PINNED));
    setRecent(readList<RecentFile>(RECENT_KEY, isRecentFile, BLANK_RECENT));
  }, []);

  const pin = useCallback((file: FileRef) => {
    setPinned((prev) => {
      if (prev.some((p) => p.id === file.id)) return prev;
      const next: PinnedFile[] = [{ ...file, pinnedAt: Date.now() }, ...prev];
      writeList(PINNED_KEY, next);
      return next;
    });
  }, []);

  const unpin = useCallback((id: string) => {
    setPinned((prev) => {
      const next = prev.filter((p) => p.id !== id);
      writeList(PINNED_KEY, next);
      return next;
    });
  }, []);

  const trackRecent = useCallback((file: FileRef) => {
    setRecent((prev) => {
      // Dedupe by id, newest first: a re-seen file bubbles to the top with a
      // fresh seenAt. Cap the rolling window at RECENT_CAP.
      const without = prev.filter((r) => r.id !== file.id);
      const next: RecentFile[] = [{ ...file, seenAt: Date.now() }, ...without].slice(0, RECENT_CAP);
      writeList(RECENT_KEY, next);
      return next;
    });
  }, []);

  return { pinned, recent, pin, unpin, trackRecent };
}
