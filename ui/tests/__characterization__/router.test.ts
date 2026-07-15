import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { closeRun, openRun, useRoute } from "@/router";

function move(hash: string) {
  window.location.hash = hash;
  window.dispatchEvent(new Event("hashchange"));
}

describe("run routes", () => {
  beforeEach(() => move("#/home"));

  it("closes a canonical run deep link onto the Runs explorer", () => {
    const { result } = renderHook(() => useRoute());
    act(() => move("#/runs/run-123"));
    expect(result.current.runId).toBe("run-123");
    act(() => closeRun());
    expect(window.location.hash).toBe("#/runs");
  });

  it("preserves the current surface for an ordinary run overlay", () => {
    renderHook(() => useRoute());
    act(() => move("#/home"));
    act(() => openRun("run-456"));
    expect(window.location.hash).toBe("#/home?run=run-456");
  });
});
