// @vitest-environment happy-dom

import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FamiliarStage } from "../src/components/familiar/FamiliarStage";
import { FamiliarBadge } from "../src/components/familiar/FamiliarBadge";
import {
  FAMILIAR_CANONICAL_BASE_HUE_DEGREES,
  familiarVisualIdentity,
  packFamiliarGenotype,
} from "../src/components/familiar/FamiliarGenotype";
import {
  familiarCompositionForMode,
  FamiliarWebGLRenderer,
} from "../src/components/familiar/FamiliarWebGLRenderer";
import {
  clampStageState,
  RESTING_STAGE_STATE,
} from "../src/components/familiar/FamiliarState";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

// happy-dom provides no WebGL2 context, which is exactly the environment the
// renderer ladder must survive: the Stage may never be blank, it degrades to
// the badge and keeps its accessible label.

describe("FamiliarStage fallback ladder", () => {
  it("reports pending until its first WebGL frame has actually painted", async () => {
    let nextFrame: FrameRequestCallback | null = null;
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback: FrameRequestCallback) => {
      nextFrame = callback;
      return 1;
    }));
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    const gl = {
      COLOR_BUFFER_BIT: 0x4000,
      COMPILE_STATUS: 0x8b81,
      FRAGMENT_SHADER: 0x8b30,
      LINK_STATUS: 0x8b82,
      TRIANGLES: 4,
      VERTEX_SHADER: 0x8b31,
      attachShader: vi.fn(),
      clear: vi.fn(),
      clearColor: vi.fn(),
      compileShader: vi.fn(),
      createProgram: vi.fn(() => ({})),
      createShader: vi.fn(() => ({})),
      deleteShader: vi.fn(),
      drawArrays: vi.fn(),
      getExtension: vi.fn(() => null),
      getProgramInfoLog: vi.fn(() => null),
      getProgramParameter: vi.fn(() => true),
      getShaderInfoLog: vi.fn(() => null),
      getShaderParameter: vi.fn(() => true),
      getUniformLocation: vi.fn((_program: object, name: string) => name),
      linkProgram: vi.fn(),
      shaderSource: vi.fn(),
      uniform1f: vi.fn(),
      uniform2f: vi.fn(),
      uniform4f: vi.fn(),
      uniform4fv: vi.fn(),
      useProgram: vi.fn(),
      viewport: vi.fn(),
    };
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
      gl as unknown as WebGL2RenderingContext,
    );

    render(<FamiliarStage mode="voice" state={RESTING_STAGE_STATE} />);
    const stage = screen.getByRole("img", { name: "Boltrig Familiar · ready" });
    expect(stage.dataset.renderer).toBe("pending");
    expect(stage.getAttribute("aria-busy")).toBe("true");

    await act(async () => {
      (nextFrame as FrameRequestCallback | null)?.(5_000);
    });

    expect(gl.drawArrays).toHaveBeenCalledTimes(1);
    expect(stage.dataset.renderer).toBe("webgl2");
    expect(stage.getAttribute("aria-busy")).toBeNull();
  });

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
    expect(document.querySelector(".familiar-stage .familiar-orb")).toBeTruthy();
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

  it("keeps the authoritative body when the premium renderer falls back", async () => {
    render(
      <FamiliarStage
        genotype={{
          source: "agent_capability.name.v1",
          seed: 42,
          body: "kepler",
          palette: ["#ede9fe", "#8b5cf6", "#2e1065"],
          markings: ["orbit"],
          accessories: ["antenna"],
        }}
        label="Noether"
        mode="voice"
        state={RESTING_STAGE_STATE}
      />,
    );
    await waitFor(() => {
      expect(screen.getByRole("img", { name: "Noether Familiar · ready" })
        .getAttribute("data-familiar-body")).toBe("kepler");
    });
  });
});

describe("authoritative Familiar genotype", () => {
  const genotype = {
    source: "agent_capability.name.v1" as const,
    seed: 898153330,
    body: "cassini",
    palette: ["#ffedd5", "#f97316", "#7c2d12"],
    markings: ["orbit"],
    accessories: ["antenna"],
  };

  it("gives every canonical body a distinct shader silhouette", () => {
    const signatures = new Set(
      ["cassini", "kepler", "pioneer", "voyager"].map((body) => (
        Array.from(packFamiliarGenotype({ ...genotype, body }).slice(0, 14)).join(",")
      )),
    );
    expect(signatures.size).toBe(4);
  });

  it("uses palette, markings and accessories in the packed shader identity", () => {
    const plain = packFamiliarGenotype({ ...genotype, markings: [], accessories: [] });
    const authored = packFamiliarGenotype(genotype);
    expect(plain[12]).toBeCloseTo(Math.PI / 2);
    expect(authored[12]).not.toBe(plain[12]);
    expect(authored[13]).not.toBe(plain[13]);
    expect(authored[28]).not.toBe(plain[28]);
    // Orange is more than 180 degrees behind the canonical blue, so the
    // shortest signed rotation wraps forward instead.
    expect(authored[14]).toBeCloseTo(2.9772088, 6);
    expect(authored[14]).toBeLessThan(Math.PI);
  });

  it("keeps the navy Call fixture on its authored hue and lightness", () => {
    const callFixture = packFamiliarGenotype({
      ...genotype,
      palette: ["#4b78ae", "#18304a", "#f0c37b"],
    });
    const rotation = callFixture[14]!;
    const resultingHue = (
      FAMILIAR_CANONICAL_BASE_HUE_DEGREES
      + rotation * 180 / Math.PI
      + 360
    ) % 360;

    expect(rotation).toBeCloseTo(-0.04886922, 7);
    expect(resultingHue).toBeCloseTo(211.2, 5);
    expect(callFixture[30]).toBeCloseTo(0.19215687, 7);
    expect(callFixture[30]).toBeLessThan(packFamiliarGenotype(genotype)[30]!);
  });

  it("binds authored lightness and the warm heart to the shader material", () => {
    const shader = readFileSync(
      resolve(__dirname, "../src/bundles/familiar/familiar.frag"),
      "utf8",
    );
    expect(shader).toContain(
      "float materialExposure = mix(0.12, 0.78, paletteLightness);",
    );
    expect(shader).toContain("float vWARMTH = uGene[4].x;");
    expect(shader).toContain(
      "vec3 heartC = mix(vec3(0.90,0.95,1.00), vec3(1.00,0.48,0.12)",
    );
    expect(shader).toContain(
      "heartAura*(0.08 + 0.09*lum) + heartCore*(0.58 + 0.40*lum)",
    );
  });

  it("renders a flat body, marking and accessory without a generic orb", () => {
    render(<FamiliarBadge genotype={genotype} label="Lyell" state="ready" />);
    const badge = screen.getByRole("img", { name: "Lyell Familiar · ready" });
    expect(badge.getAttribute("data-familiar-body")).toBe("cassini");
    expect(badge.getAttribute("data-familiar-markings")).toBe("orbit");
    expect(badge.getAttribute("data-familiar-accessories")).toBe("antenna");
    expect(badge.querySelector(".familiar-badge-body path")).toBeTruthy();
    expect(badge.querySelector(".familiar-badge-markings ellipse")).toBeTruthy();
    expect(badge.querySelector(".familiar-badge-accessories circle")).toBeTruthy();
    expect(badge.getAttribute("style")).toContain("#ffedd5");
    expect(badge.getAttribute("style")).toContain("#7c2d12");
  });

  it("does not guess an unknown authoritative body", () => {
    expect(familiarVisualIdentity({ ...genotype, body: "future-body" }).body).toBe("neutral");
    expect(packFamiliarGenotype({ ...genotype, body: "future-body" })[0]).toBe(0);
  });
});

describe("FamiliarWebGLRenderer lifecycle", () => {
  it("gives Voice the full portrait scale without changing compact modes", () => {
    expect(familiarCompositionForMode("voice")).toEqual({
      scaleDock: 0.45,
      fitScale: 0.62,
    });
    for (const mode of ["hero", "conversation", "minimised"] as const) {
      expect(familiarCompositionForMode(mode)).toEqual({
        scaleDock: 0.34,
        fitScale: 0.5,
      });
    }
  });

  it("uploads the Voice portrait scale on a deterministic reduced-motion frame", () => {
    vi.stubGlobal("requestAnimationFrame", vi.fn(() => 1));
    vi.stubGlobal("devicePixelRatio", 2);
    const frozenAfternoon = new Date(2026, 7, 11, 15, 0, 0).getTime();
    const dateNow = vi.spyOn(Date, "now").mockReturnValue(frozenAfternoon);
    const onFirstPaint = vi.fn();
    const values = new Map<string, number>();
    const canvas = document.createElement("canvas");
    Object.defineProperty(canvas, "clientWidth", { configurable: true, value: 150 });
    document.body.appendChild(canvas);
    const gl = {
      COLOR_BUFFER_BIT: 0x4000,
      TRIANGLES: 4,
      clear: vi.fn(),
      clearColor: vi.fn(),
      drawArrays: vi.fn(),
      getExtension: vi.fn(() => null),
      uniform1f: vi.fn((location: string, value: number) => values.set(location, value)),
      uniform2f: vi.fn(),
      uniform4f: vi.fn(),
      viewport: vi.fn(),
    };
    const renderer = new FamiliarWebGLRenderer({ reducedMotion: true, onFirstPaint });
    renderer.setMode("voice");
    const internals = renderer as unknown as {
      canvas: HTMLCanvasElement;
      frame(now: number): void;
      gl: typeof gl;
      statusValue: { kind: "webgl2"; state: "running" };
      uniforms: Record<string, string>;
    };
    internals.canvas = canvas;
    internals.gl = gl;
    internals.statusValue = { kind: "webgl2", state: "running" };
    internals.uniforms = new Proxy({}, {
      get: (_target, property) => String(property),
    });

    internals.frame(5_000);

    expect(values.get("uScaleDock")).toBe(0.45);
    expect(values.get("uFitScale")).toBe(0.62);
    expect(values.get("uAperture")).toBe(1);
    expect(values.get("iTime")).toBe(0);
    expect(values.get("uDay")).toBe(1);
    expect(canvas.width).toBe(300);
    expect(canvas.height).toBe(300);
    expect(onFirstPaint).toHaveBeenCalledTimes(1);
    internals.frame(5_100);
    expect(onFirstPaint).toHaveBeenCalledTimes(1);
    renderer.destroy();
    dateNow.mockRestore();
  });

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
    expect(clampStageState({})).toEqual({
      working: false, speaking: false, level: 0, bands: null, onset: 0,
    });
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
