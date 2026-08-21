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
  type FamiliarStageState,
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
      // The renderer links through canvas/glResources.createProgram rather than
      // a private copy, and that binds attribute location 0 before linking. A
      // fake missing it throws inside link() and the Stage falls back to the
      // badge -- which presents as "pending never resolves", not as a mock gap.
      bindAttribLocation: vi.fn(),
      clear: vi.fn(),
      clearColor: vi.fn(),
      compileShader: vi.fn(),
      createProgram: vi.fn(() => ({})),
      createShader: vi.fn(() => ({})),
      // The lattice deck owns programs and textures of its own and releases
      // them on destroy; a fake without the delete half throws in teardown and
      // poisons every later test in the file.
      createTexture: vi.fn(() => ({})),
      deleteProgram: vi.fn(),
      deleteShader: vi.fn(),
      deleteTexture: vi.fn(),
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
    const stage = screen.getByRole("img", { name: "Boltrig Familiar" });
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
        state={{ ...RESTING_STAGE_STATE, mode: "working" }}
      />,
    );
    await waitFor(() => {
      expect(screen.getByRole("img", { name: "Boltrig Familiar" })
        .getAttribute("data-renderer")).toBe("badge");
    });
    expect(document.querySelector(".familiar-stage .familiar-orb")).toBeTruthy();
  });

  // The name is the IDENTITY and the live region is the STATE. They were one
  // string, which meant the only channel carrying "she is working" was an
  // aria-label on a role="img" -- a NAME, read once when focus reaches it and
  // not re-announced when it changes. A body that is the surface's only
  // indicator has to say what it is doing somewhere a screen reader will
  // repeat, or it is not an indicator for everyone.
  it("says the mode in a live region beside the body, not in its name", async () => {
    const { rerender } = render(
      <FamiliarStage mode="hero" state={RESTING_STAGE_STATE} />,
    );
    await waitFor(() => {
      expect(screen.getByRole("img", { name: "Boltrig Familiar" })).toBeTruthy();
    });
    const status = document.querySelector(".familiar-stage-status");
    expect(status?.getAttribute("aria-live")).toBe("polite");
    expect(status?.textContent).toBe("Boltrig Familiar ready");

    for (const [mode, said] of [
      ["listening", "listening"],
      ["thinking", "thinking"],
      ["speaking", "speaking"],
      ["error", "disconnected"],
    ] as const) {
      rerender(
        <FamiliarStage mode="hero" state={{ ...RESTING_STAGE_STATE, mode }} />,
      );
      expect(document.querySelector(".familiar-stage-status")?.textContent)
        .toBe(`Boltrig Familiar ${said}`);
    }
  });

  // The live region cannot live INSIDE the body: role="img" replaces its own
  // subtree in the accessibility tree, so a nested one is never announced --
  // the version of this fix that looks right in the markup and does nothing.
  it("keeps the live region outside the role=img subtree", async () => {
    render(<FamiliarStage mode="hero" state={RESTING_STAGE_STATE} />);
    await waitFor(() => {
      expect(screen.getByRole("img", { name: "Boltrig Familiar" })).toBeTruthy();
    });
    const stage = screen.getByRole("img", { name: "Boltrig Familiar" });
    expect(stage.querySelector(".familiar-stage-status")).toBeNull();
    expect(document.querySelector(".familiar-stage-status")).toBeTruthy();
  });

  it("keeps accepting state updates after falling back", async () => {
    const { rerender } = render(
      <FamiliarStage mode="hero" state={RESTING_STAGE_STATE} />,
    );
    await waitFor(() => {
      expect(screen.getByRole("img", { name: "Boltrig Familiar" })
        .getAttribute("data-renderer")).toBe("badge");
    });
    rerender(
      <FamiliarStage
        mode="voice"
        state={{ mode: "speaking", level: 0.8 }}
      />,
    );
    expect(document.querySelector(".familiar-stage-status")?.textContent)
      .toBe("Boltrig Familiar speaking");
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
      expect(screen.getByRole("img", { name: "Noether Familiar" })
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

  /**
   * THE MODES, MEASURED AT THE UNIFORMS.
   *
   * The offscreen render harness reads brightness and saturation over the
   * middle of the frame, and it separates speaking and error from the rest
   * easily -- but listening differs from standby almost entirely in GAZE, which
   * moves a pupil rather than a histogram. Judging that change by whole-frame
   * statistics would report "no difference" about a difference that is the
   * whole point of the state, so it is checked where it actually happens.
   */
  it("gives each mode a different uniform recipe, gaze included", () => {
    vi.stubGlobal("requestAnimationFrame", vi.fn(() => 1));
    const dateNow = vi.spyOn(Date, "now")
      .mockReturnValue(new Date(2026, 7, 11, 15, 0, 0).getTime());

    const read = (mode: FamiliarStageState["mode"], micLevel = 0.8) => {
      const values = new Map<string, number>();
      const canvas = document.createElement("canvas");
      Object.defineProperty(canvas, "clientWidth", { configurable: true, value: 150 });
      const gl = {
        COLOR_BUFFER_BIT: 0x4000,
        TRIANGLES: 4,
        clear: vi.fn(),
        clearColor: vi.fn(),
        drawArrays: vi.fn(),
        getExtension: vi.fn(() => null),
        uniform1f: vi.fn((location: string, value: number) => values.set(location, value)),
        uniform2f: vi.fn(),
        uniform4f: vi.fn((location: string, x: number, y: number, z: number, w: number) => {
          values.set(`${location}.x`, x);
          values.set(`${location}.y`, y);
          values.set(`${location}.z`, z);
          values.set(`${location}.w`, w);
        }),
        viewport: vi.fn(),
      };
      const renderer = new FamiliarWebGLRenderer({ reducedMotion: false });
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
      internals.uniforms = new Proxy({}, { get: (_t, property) => String(property) });
      renderer.update({ mode, micLevel, level: 0.8, bands: [0.8, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2] });
      // Enough frames for the tuning ease to arrive: a mode change is a target
      // the body travels to, so reading one frame in reads the journey.
      for (let i = 1; i <= 400; i += 1) internals.frame(i * 16);
      renderer.destroy();
      return values;
    };

    const standby = read("standby");
    const listening = read("listening");
    const speaking = read("speaking");
    const failed = read("error");

    // LISTENING IS GAZE, not amplitude. She turns toward you and her attention
    // rises; what she does NOT do is move as though she were the one talking.
    expect(listening.get("uGaze")!).toBeGreaterThan(0.9);
    expect(standby.get("uGaze")!).toBeLessThan(0.2);
    expect(listening.get("uAttention")!).toBeGreaterThan(standby.get("uAttention")!);
    expect(listening.get("uAudio.x")!).toBeLessThan(speaking.get("uAudio.x")!);

    // SPEAKING drives all four channels from the spectrum.
    expect(speaking.get("uAudio.x")!).toBeGreaterThan(0.5);
    expect(speaking.get("uAudio.w")!).toBeGreaterThan(0);

    // ERROR is held tension and lost light, and it is NOT irritation: the one
    // colour term in the shader means she is annoyed WITH YOU, which a dropped
    // websocket is not. Getting that wrong makes an outage look like a mood.
    expect(failed.get("uTension")!).toBeGreaterThan(0.5);
    expect(failed.get("uLuminosity")!).toBeLessThan(standby.get("uLuminosity")!);
    expect(failed.get("uIrritation")).toBe(0);
    expect(failed.get("uGaze")!).toBeLessThan(0.3);

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
      mode: "standby", level: 0, bands: null, onset: 0, micLevel: 0,
    });
    expect(clampStageState({ level: 7, mode: "speaking" }).level).toBe(1);
    expect(clampStageState({ level: -3 }).level).toBe(0);
    expect(clampStageState({ level: Number.NaN }).level).toBe(0);
    expect(clampStageState({ level: Infinity }).level).toBe(0);
    expect(clampStageState({ micLevel: 3 }).micLevel).toBe(1);
  });

  // An unknown mode is a HOST that is ahead of this build, not a reason to
  // throw or to draw nothing: the calm default is the only safe way to be wrong.
  it("falls back to standby for a mode it does not know", () => {
    expect(clampStageState({ mode: "transcending" as never }).mode).toBe("standby");
  });
});

describe("familiarStateFromTurn", () => {
  const base = {
    loading: false, hasLiveEvents: false, liveEnded: false,
    voiceSpeaking: false, voiceLevel: 0,
  };

  it("tells thinking from working, and standby from both", async () => {
    const { familiarStateFromTurn } = await import("../src/components/familiar/FamiliarState");
    expect(familiarStateFromTurn(base).mode).toBe("standby");
    // Loading with nothing streaming yet is "I heard you"; live events are
    // "I am doing it". They were one state, and the difference is the one a
    // person waiting on a reply actually reads.
    expect(familiarStateFromTurn({ ...base, loading: true }).mode).toBe("thinking");
    expect(familiarStateFromTurn({ ...base, hasLiveEvents: true }).mode).toBe("working");
    expect(familiarStateFromTurn({ ...base, hasLiveEvents: true, liveEnded: true }).mode)
      .toBe("standby");
  });

  it("reads a live microphone as listening, and carries its level", async () => {
    const { familiarStateFromTurn } = await import("../src/components/familiar/FamiliarState");
    const heard = familiarStateFromTurn({ ...base, micActive: true, micLevel: 0.6 });
    expect(heard.mode).toBe("listening");
    expect(heard.micLevel).toBe(0.6);
    // The level channel follows whichever voice is live, so a body with no mic
    // wiring of its own still animates to the person talking to it.
    expect(heard.level).toBe(0.6);
  });

  it("orders speaking over listening, and failure over everything", async () => {
    const { familiarStateFromTurn } = await import("../src/components/familiar/FamiliarState");
    const speaking = familiarStateFromTurn({
      ...base, voiceSpeaking: true, voiceLevel: 2, micActive: true,
    });
    expect(speaking.mode).toBe("speaking");
    expect(speaking.level).toBe(1);
    // A dropped call is not less important than the turn that was streaming
    // when it dropped, which is the whole reason failure sits at the top.
    expect(familiarStateFromTurn({
      ...base, failed: true, voiceSpeaking: true, hasLiveEvents: true, micActive: true,
    }).mode).toBe("error");
  });
});
