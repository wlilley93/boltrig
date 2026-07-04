import { describe, expect, it, beforeEach } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useStickyNotes } from "@/panels/workflowCanvas/useStickyNotes";
import type { StickyNote } from "@/panels/workflowCanvas/StickyNotes";

const note = (id: string, text: string, x = 10, y = 20): StickyNote => ({
  id,
  text,
  x,
  y,
});

describe("useStickyNotes", () => {
  beforeEach(() => window.localStorage.clear());

  it("returns empty when nothing is stored", () => {
    const { result } = renderHook(() => useStickyNotes("wf-a"));
    expect(result.current[0]).toEqual([]);
  });

  it("round-trips notes through localStorage", () => {
    const { result, rerender } = renderHook(() => useStickyNotes("wf-a"));
    act(() => result.current[1]([note("n1", "ship it")]));
    expect(result.current[0]).toHaveLength(1);

    // A fresh hook for the same workflow id rehydrates the saved notes.
    const { result: again } = renderHook(() => useStickyNotes("wf-a"));
    expect(again.current[0]).toEqual([note("n1", "ship it")]);
    void rerender;
  });

  it("isolates notes per workflow id", () => {
    const { result: a } = renderHook(() => useStickyNotes("wf-a"));
    act(() => a.current[1]([note("a1", "A")]));
    const { result: b } = renderHook(() => useStickyNotes("wf-b"));
    expect(b.current[0]).toEqual([]);
  });

  it("ignores malformed stored data", () => {
    window.localStorage.setItem("boltrig:wf-notes:wf-x", "{not json");
    const { result } = renderHook(() => useStickyNotes("wf-x"));
    expect(result.current[0]).toEqual([]);
  });
});
