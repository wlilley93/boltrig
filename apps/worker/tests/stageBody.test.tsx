// @vitest-environment happy-dom
import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  budgets: vi.fn(),
}));

vi.mock("../src/client", () => ({ client: api }));

import { StageBody, type StageTurnInput } from "../src/components/StageBody";
import { saveCharacterLocal } from "../src/character";

// StageBody is the one place that decides which body is on the Stage, so it is
// the one place where "the setting actually changes what you see" can be
// proven. happy-dom has no WebGL, so both renderers fail to acquire a context
// and fall back — which is fine and is itself worth pinning: the choice must
// still be visible in the DOM, and a missing GPU must never blank the Stage.

const INPUT: StageTurnInput = {
  loading: false,
  hasLiveEvents: false,
  liveEnded: true,
  voiceSpeaking: false,
  voiceLevel: 0,
};

beforeEach(() => {
  localStorage.clear();
  api.budgets.mockResolvedValue({ budgets: [] });
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.clearAllMocks();
});

describe("the Stage body switch", () => {
  it("shows the Familiar by default, so an existing install is unchanged", () => {
    const { container } = render(<StageBody input={INPUT} mode="conversation" />);
    expect(container.querySelector(".familiar-stage")).toBeTruthy();
    expect(container.querySelector(".jarvis-stage")).toBeNull();
  });

  it("shows Jarvis when the Companion setting selects it", () => {
    saveCharacterLocal("jarvis");
    const { container } = render(<StageBody input={INPUT} mode="conversation" />);
    expect(container.querySelector(".jarvis-stage")).toBeTruthy();
    expect(container.querySelector(".familiar-stage")).toBeNull();
  });

  // The setting is changed in Settings, which is a different subtree — the
  // Stage has to hear about it without a remount or a page reload.
  it("swaps live when the setting changes elsewhere in the app", async () => {
    const { container } = render(<StageBody input={INPUT} mode="conversation" />);
    expect(container.querySelector(".familiar-stage")).toBeTruthy();

    saveCharacterLocal("jarvis");
    await waitFor(() => {
      expect(container.querySelector(".jarvis-stage")).toBeTruthy();
    });
    expect(container.querySelector(".familiar-stage")).toBeNull();

    saveCharacterLocal("familiar");
    await waitFor(() => {
      expect(container.querySelector(".familiar-stage")).toBeTruthy();
    });
  });

  // Both bodies read the same turn facts. Neither may ever be handed something
  // the other is not — that is what keeps them two depictions of one truth.
  it("depicts a working turn in whichever body is chosen", () => {
    const working: StageTurnInput = { ...INPUT, loading: true, liveEnded: false };

    const familiar = render(<StageBody input={working} mode="conversation" />);
    expect(familiar.container.querySelector(".familiar-stage")).toBeTruthy();
    cleanup();

    saveCharacterLocal("jarvis");
    const jarvis = render(<StageBody input={working} mode="conversation" />);
    const stage = jarvis.container.querySelector(".jarvis-stage");
    expect(stage).toBeTruthy();
    // The instrument names its own mode in the DOM, so the depiction is
    // checkable without a GPU.
    expect(stage?.getAttribute("data-mode")).toBe("thinking");
  });
});
