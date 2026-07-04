import { describe, expect, it, beforeEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useFilesStore } from "@/panels/chat/useFilesStore";
import type { FileRef } from "@/panels/chat/useFilesStore";

const ref = (id: string, name = `${id}.md`, size = 100, agent = "Bolt"): FileRef => ({
  id,
  name,
  size,
  agent,
});

describe("useFilesStore", () => {
  beforeEach(() => window.localStorage.clear());

  it("returns empty pinned and recent when nothing is stored", () => {
    const { result } = renderHook(() => useFilesStore());
    expect(result.current.pinned).toEqual([]);
    expect(result.current.recent).toEqual([]);
  });

  it("round-trips a pinned file through localStorage", () => {
    const { result } = renderHook(() => useFilesStore());
    act(() => result.current.pin(ref("a1", "arch.md", 1024)));

    expect(result.current.pinned).toHaveLength(1);
    expect(result.current.pinned[0].name).toBe("arch.md");
    expect(result.current.pinned[0].pinnedAt).toBeTypeOf("number");

    // A fresh hook rehydrates the pinned file from localStorage.
    const { result: again } = renderHook(() => useFilesStore());
    expect(again.current.pinned).toHaveLength(1);
    expect(again.current.pinned[0].name).toBe("arch.md");
  });

  it("unpins by id and persists the change", () => {
    const { result } = renderHook(() => useFilesStore());
    act(() => result.current.pin(ref("a1")));
    act(() => result.current.pin(ref("a2")));
    act(() => result.current.unpin("a1"));

    expect(result.current.pinned.map((p) => p.id)).toEqual(["a2"]);

    const { result: again } = renderHook(() => useFilesStore());
    expect(again.current.pinned.map((p) => p.id)).toEqual(["a2"]);
  });

  it("does not duplicate a pinned file (dedupe by id)", () => {
    const { result } = renderHook(() => useFilesStore());
    act(() => result.current.pin(ref("a1", "x.md", 10)));
    act(() => result.current.pin(ref("a1", "x.md", 10)));

    expect(result.current.pinned).toHaveLength(1);
  });

  it("tracks recent newest-first and dedupes by id", () => {
    const { result } = renderHook(() => useFilesStore());
    act(() => result.current.trackRecent(ref("r1")));
    act(() => result.current.trackRecent(ref("r2")));
    act(() => result.current.trackRecent(ref("r1"))); // bubbles r1 back to top

    expect(result.current.recent.map((r) => r.id)).toEqual(["r1", "r2"]);
    expect(result.current.recent[0].seenAt).toBeTypeOf("number");
  });

  it("round-trips recent through localStorage", () => {
    const { result } = renderHook(() => useFilesStore());
    act(() => result.current.trackRecent(ref("r1", "old.md", 2048)));

    const { result: again } = renderHook(() => useFilesStore());
    expect(again.current.recent).toHaveLength(1);
    expect(again.current.recent[0].id).toBe("r1");
    expect(again.current.recent[0].name).toBe("old.md");
  });

  it("caps recent at twelve entries (oldest evicted)", () => {
    const { result } = renderHook(() => useFilesStore());
    for (let i = 0; i < 15; i++) {
      act(() => result.current.trackRecent(ref(`r${i}`)));
    }

    expect(result.current.recent).toHaveLength(12);
    expect(result.current.recent[0].id).toBe("r14");
    expect(result.current.recent[11].id).toBe("r3");
  });

  it("isolates pinned and recent (same id, different stores)", () => {
    const { result } = renderHook(() => useFilesStore());
    act(() => result.current.pin(ref("shared")));
    act(() => result.current.trackRecent(ref("shared")));

    expect(result.current.pinned).toHaveLength(1);
    expect(result.current.recent).toHaveLength(1);
  });

  it("ignores malformed stored data (bad json and bad shapes)", () => {
    window.localStorage.setItem("boltrig:pinned-files", "{not json");
    window.localStorage.setItem("boltrig:recent-files", JSON.stringify([1, 2, { id: "x" }]));

    const { result } = renderHook(() => useFilesStore());
    expect(result.current.pinned).toEqual([]);
    expect(result.current.recent).toEqual([]);
  });
});
