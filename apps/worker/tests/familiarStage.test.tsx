// @vitest-environment happy-dom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { FamiliarStage } from "../src/components/familiar/FamiliarStage";
import { FamiliarWebGLRenderer } from "../src/components/familiar/FamiliarWebGLRenderer";
import {
  clampStageState,
  RESTING_STAGE_STATE,
} from "../src/components/familiar/FamiliarState";

afterEach(cleanup);

// happy-dom provides no WebGL2 context, which is exactly the environment the
// renderer ladder must survive: the Stage may never be blank, it degrades to
// the badge and keeps its accessible label.

describe("FamiliarStage fallback ladder", () => {
  it("falls back to the badge when WebGL2 is unavailable, keeping the label", async () => {
    render(
      <FamiliarStage
        mode="hero"
        state={{ ...RESTING_STAGE_STATE, working: true }}
      />,
    );
    await waitFor(() => {
      expect(screen.getByRole("img", { name: "Boltrig Familiar · working" })
        .getAttribute("data-renderer")).toBe("badge");
    });
    expect(screen.getByRole("img", { name: "Boltrig activity · working" })).toBeTruthy();
  });

  it("keeps accepting state updates after falling back", async () => {
    const { rerender } = render(
      <FamiliarStage mode="hero" state={RESTING_STAGE_STATE} />,
    );
    await waitFor(() => {
      expect(screen.getByRole("img", { name: "Boltrig Familiar · ready" })
        .getAttribute("data-renderer")).toBe("badge");
    });
    rerender(
      <FamiliarStage
        mode="voice"
        state={{ working: false, speaking: true, level: 0.8 }}
      />,
    );
    expect(screen.getByRole("img", { name: "Boltrig Familiar · working" })).toBeTruthy();
  });
});

describe("FamiliarWebGLRenderer lifecycle", () => {
  it("reports failed (not blank) without WebGL2 and removes its canvas", () => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const renderer = new FamiliarWebGLRenderer({ reducedMotion: false });
    renderer.mount(host);
    const status = renderer.status();
    expect(status.state).toBe("failed");
    expect(status.reason).toBeTruthy();
    expect(host.querySelector("canvas")).toBeNull();
    renderer.destroy();
    expect(renderer.status().state).toBe("destroyed");
  });

  it("suspend/resume are inert once failed — no zombie frame loop", () => {
    const renderer = new FamiliarWebGLRenderer({ reducedMotion: true });
    const host = document.createElement("div");
    renderer.mount(host);
    renderer.setMode("minimised");
    renderer.resume();
    expect(renderer.status().state).toBe("failed");
  });
});

describe("clampStageState", () => {
  it("bounds and defaults every field", () => {
    expect(clampStageState({})).toEqual({ working: false, speaking: false, level: 0 });
    expect(clampStageState({ level: 7, speaking: true }).level).toBe(1);
    expect(clampStageState({ level: -3 }).level).toBe(0);
    expect(clampStageState({ level: Number.NaN }).level).toBe(0);
    expect(clampStageState({ level: Infinity }).level).toBe(0);
  });
});

describe("familiarStateFromTurn", () => {
  it("derives working from loading or an unfinished live turn", async () => {
    const { familiarStateFromTurn } = await import("../src/components/familiar/FamiliarState");
    const base = { loading: false, hasLiveEvents: false, liveEnded: false, voiceSpeaking: false, voiceLevel: 0 };
    expect(familiarStateFromTurn(base).working).toBe(false);
    expect(familiarStateFromTurn({ ...base, loading: true }).working).toBe(true);
    expect(familiarStateFromTurn({ ...base, hasLiveEvents: true }).working).toBe(true);
    expect(familiarStateFromTurn({ ...base, hasLiveEvents: true, liveEnded: true }).working).toBe(false);
    const speaking = familiarStateFromTurn({ ...base, voiceSpeaking: true, voiceLevel: 2 });
    expect(speaking.speaking).toBe(true);
    expect(speaking.level).toBe(1);
  });
});
