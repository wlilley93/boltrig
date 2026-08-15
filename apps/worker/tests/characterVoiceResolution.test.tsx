// @vitest-environment happy-dom

import { isValidElement, type ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { characterFor } from "../src/components/characters";
import { JarvisWebGLRenderer } from "../src/components/jarvis/JarvisRenderer";

afterEach(() => vi.unstubAllGlobals());

describe("full-window character resolution", () => {
  it("marks only Jarvis voice mode as a high-resolution Stage", () => {
    const character = characterFor("jarvis");
    const render = (mode: "conversation" | "voice") => character.render({
      budgets: null,
      input: {
        loading: false,
        hasLiveEvents: false,
        liveEnded: true,
        voiceSpeaking: false,
        voiceLevel: 0,
      },
      mode,
      phenotype: null,
      sensing: {},
    });
    const inline = render("conversation");
    const call = render("voice");
    expect(isValidElement(inline)).toBe(true);
    expect(isValidElement(call)).toBe(true);
    expect((inline as ReactElement<{ highResolution: boolean }>).props.highResolution)
      .toBe(false);
    expect((call as ReactElement<{ highResolution: boolean }>).props.highResolution)
      .toBe(true);
  });

  it("backs a full-window Jarvis canvas at 2x without exceeding the cap", () => {
    vi.stubGlobal("devicePixelRatio", 3);
    const canvas = document.createElement("canvas");
    Object.defineProperties(canvas, {
      clientWidth: { configurable: true, value: 480 },
      clientHeight: { configurable: true, value: 320 },
    });
    const renderer = new JarvisWebGLRenderer({ maxDevicePixelRatio: 2 });
    const internals = renderer as unknown as {
      canvas: HTMLCanvasElement;
      resizeCanvas(): void;
    };
    internals.canvas = canvas;
    internals.resizeCanvas();
    expect(canvas.width).toBe(960);
    expect(canvas.height).toBe(640);
  });
});
