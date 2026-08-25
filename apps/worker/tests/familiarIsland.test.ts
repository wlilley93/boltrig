// @vitest-environment happy-dom

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  FamiliarIslandHost,
  type IslandClock,
  type IslandReport,
} from "../src/familiarIsland/islandHost";
import {
  applyState,
  DEFAULT_ISLAND_STATE,
  parseIslandState,
  type IslandState,
} from "../src/familiarIsland/islandState";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

const ISLAND_DIR = resolve(__dirname, "../../../ios/Boltrig/Resources/FamiliarIsland");
const FRAG = resolve(__dirname, "../src/bundles/familiar/familiar.frag");
const CHARACTER = resolve(__dirname, "../src/bundles/familiar/character.json");

// ---------------------------------------------------------------- the reducer

describe("applyState", () => {
  it("keeps every previous value a message does not carry", () => {
    const { state, effects } = applyState(DEFAULT_ISLAND_STATE, {});
    expect(state).toEqual(DEFAULT_ISLAND_STATE);
    expect(effects).toEqual({
      remount: false, presentationChanged: false, genotypeChanged: false, phenotypeChanged: false,
    });
    const first = applyState(DEFAULT_ISLAND_STATE, { presentation: "conversation" }).state;
    const second = applyState(first, { level: 0.5 }).state;
    expect(second.presentation).toBe("conversation");
    expect(second.level).toBe(0.5);
    expect(second.v).toBe(1);
  });

  // An unknown version is ignored WHOLE. Half-applying a v2 message would draw
  // whatever fields happened to keep their v1 names and silently drop the rest.
  it("ignores a message of another version and says so once per apply", () => {
    const { state, effects, warning } = applyState(DEFAULT_ISLAND_STATE, { v: 2, mode: "speaking" });
    expect(state).toBe(DEFAULT_ISLAND_STATE);
    expect(effects.presentationChanged).toBe(false);
    expect(warning).toMatch(/v2/);
    expect(applyState(DEFAULT_ISLAND_STATE, { v: 1, mode: "speaking" }).state.mode).toBe("speaking");
    expect(applyState(DEFAULT_ISLAND_STATE, { mode: "speaking" }).state.mode).toBe("speaking");
  });

  it("leaves the state alone for anything that is not an object", () => {
    for (const garbage of [null, 7, "speaking", [1, 2], undefined]) {
      const { state, warning } = applyState(DEFAULT_ISLAND_STATE, garbage);
      expect(state).toBe(DEFAULT_ISLAND_STATE);
      expect(warning).toBeTruthy();
    }
  });

  it("clamps through the Stage's own clamp and bounds its own numbers", () => {
    const { state } = applyState(DEFAULT_ISLAND_STATE, {
      mode: "transcending", level: 7, onset: -2, bands: [1, 2, 3], dprCap: 9,
    });
    expect(state.mode).toBe("standby");
    expect(state.level).toBe(1);
    expect(state.onset).toBe(0);
    expect(state.bands).toBeNull();
    expect(state.dprCap).toBe(2);
    expect(applyState(DEFAULT_ISLAND_STATE, { dprCap: 0.25 }).state.dprCap).toBe(1);
    expect(applyState(DEFAULT_ISLAND_STATE, { dprCap: Number.NaN }).state.dprCap).toBe(2);
    const eight = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 2];
    expect(applyState(DEFAULT_ISLAND_STATE, { bands: eight }).state.bands)
      .toEqual([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 1]);
  });

  it("keeps the previous value for a field of the wrong type", () => {
    const prev: IslandState = {
      ...DEFAULT_ISLAND_STATE, presentation: "conversation", reducedMotion: true, appearance: "light",
    };
    const { state } = applyState(prev, {
      presentation: "voice", reducedMotion: "yes", appearance: 3, phenotype: "warm", genotype: 4,
    });
    expect(state.presentation).toBe("conversation");
    expect(state.reducedMotion).toBe(true);
    expect(state.appearance).toBe("light");
    expect(state.phenotype).toBeNull();
    expect(state.genotype).toBeNull();
  });

  it("reports what the host has to do about a change, and only that", () => {
    const toConversation = applyState(DEFAULT_ISLAND_STATE, { presentation: "conversation" });
    expect(toConversation.effects.presentationChanged).toBe(true);
    expect(toConversation.effects.remount).toBe(false);

    const calm = applyState(DEFAULT_ISLAND_STATE, { reducedMotion: true });
    expect(calm.effects.remount).toBe(true);
    expect(applyState(calm.state, { reducedMotion: true }).effects.remount).toBe(false);
    expect(applyState(DEFAULT_ISLAND_STATE, { dprCap: 1 }).effects.remount).toBe(true);

    const genotype = { source: "agent_capability.name.v1", seed: 42, body: "kepler",
      palette: ["#ede9fe", "#8b5cf6", "#2e1065"], markings: ["orbit"], accessories: [] };
    const bound = applyState(DEFAULT_ISLAND_STATE, { genotype });
    expect(bound.effects.genotypeChanged).toBe(true);
    expect(bound.state.genotype).toEqual(genotype);
    expect(applyState(bound.state, { genotype }).effects.genotypeChanged).toBe(false);
    expect(applyState(bound.state, { genotype: null }).effects.genotypeChanged).toBe(true);
    // A wrong-typed field inside the identity is dropped before it can reach the shader.
    expect(applyState(DEFAULT_ISLAND_STATE, { genotype: { body: "kepler", palette: [1, 2] } })
      .state.genotype).toEqual({ body: "kepler" });

    const felt = applyState(DEFAULT_ISLAND_STATE, { phenotype: { valence: 0.7, label: "x", z: 1 } });
    expect(felt.effects.phenotypeChanged).toBe(true);
    expect(felt.state.phenotype).toEqual({ valence: 0.7, z: 1 });
    expect(applyState(felt.state, { phenotype: { z: 1, valence: 0.7 } }).effects.phenotypeChanged)
      .toBe(false);
    expect(applyState(felt.state, { phenotype: null }).state.phenotype).toBeNull();
  });
});

describe("parseIslandState", () => {
  it("returns the object for a JSON object and the reason for anything else", () => {
    expect(parseIslandState('{"v":1,"mode":"speaking"}')).toEqual({ v: 1, mode: "speaking" });
    for (const garbage of ["not json", "[]", "null", "42", '"speaking"', ""]) {
      expect(typeof parseIslandState(garbage)).toBe("string");
    }
  });
});

// -------------------------------------------------------------------- the host

/** A clock the test turns by hand: frames fire on tick(), timers when due. */
class ManualClock implements IslandClock {
  time = 0;
  private next = 1;
  private readonly frames = new Map<number, (now: number) => void>();
  private readonly waits = new Map<number, { at: number; callback: () => void }>();
  frame(callback: (now: number) => void): number {
    const handle = this.next++;
    this.frames.set(handle, callback);
    return handle;
  }
  cancelFrame(handle: number): void { this.frames.delete(handle); }
  wait(callback: () => void, ms: number): number {
    const handle = this.next++;
    this.waits.set(handle, { at: this.time + ms, callback });
    return handle;
  }
  cancelWait(handle: number): void { this.waits.delete(handle); }
  now(): number { return this.time; }
  pendingFrames(): number { return this.frames.size; }
  pendingWaits(): number { return this.waits.size; }
  /** One display refresh. */
  tick(ms = 16): void {
    this.time += ms;
    const due = [...this.frames.values()];
    this.frames.clear();
    for (const callback of due) callback(this.time);
    for (const [handle, timer] of [...this.waits]) {
      if (timer.at <= this.time) {
        this.waits.delete(handle);
        timer.callback();
      }
    }
  }
  run(ms: number, step = 16): void {
    for (let left = ms; left > 0; left -= step) this.tick(step);
  }
}

// The same fake the Stage test mounts against: enough of WebGL2 for the
// renderer to link, and for the lattice deck to release what it made.
function fakeGl() {
  return {
    COLOR_BUFFER_BIT: 0x4000,
    COMPILE_STATUS: 0x8b81,
    FRAGMENT_SHADER: 0x8b30,
    LINK_STATUS: 0x8b82,
    TRIANGLES: 4,
    VERTEX_SHADER: 0x8b31,
    attachShader: vi.fn(),
    bindAttribLocation: vi.fn(),
    clear: vi.fn(),
    clearColor: vi.fn(),
    compileShader: vi.fn(),
    createProgram: vi.fn(() => ({})),
    createShader: vi.fn(() => ({})),
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
}

function bootHost(clock: ManualClock, first?: Record<string, unknown>) {
  const reports: IslandReport[] = [];
  const element = document.createElement("div");
  document.body.appendChild(element);
  const host = new FamiliarIslandHost(clock);
  if (first) host.apply(first);
  host.boot(element, (report) => reports.push(report));
  return { host, reports, element, kinds: () => reports.map((report) => report.type) };
}

describe("FamiliarIslandHost", () => {
  it("posts fallback, not a blank page, when WebGL2 is unavailable", () => {
    const clock = new ManualClock();
    const { reports, element, host } = bootHost(clock);
    expect(reports).toEqual([{ type: "fallback", reason: "WebGL2 context unavailable" }]);
    expect(element.querySelector("canvas")).toBeNull();
    expect(clock.pendingFrames() + clock.pendingWaits()).toBe(0);
    // It says so ONCE, and keeps taking state for the day WebGL comes back.
    host.apply({ mode: "speaking" });
    expect(reports).toHaveLength(1);
    expect(host.current().mode).toBe("speaking");
    host.destroy();
  });

  it("stubs the renderer's loop, posts ready on the first stepped frame, then fps every 2 s", () => {
    const gl = fakeGl();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext")
      .mockReturnValue(gl as unknown as WebGL2RenderingContext);
    const clock = new ManualClock();
    const { reports, host, kinds } = bootHost(clock);

    // Nothing has painted yet and the renderer's own loop cannot: rAF is a stub.
    expect(reports).toEqual([]);
    expect(gl.drawArrays).not.toHaveBeenCalled();
    expect(window.requestAnimationFrame(() => undefined)).toBe(0);
    expect(clock.pendingFrames()).toBe(1);

    clock.tick();
    expect(gl.drawArrays).toHaveBeenCalledTimes(1);
    expect(reports[0]).toEqual({ type: "ready", renderer: "webgl2", presentation: "hero" });

    clock.run(2100);
    const frame = reports.find((report) => report.type === "frame");
    expect(frame).toBeTruthy();
    if (frame?.type === "frame") {
      expect(frame.fps).toBeGreaterThanOrEqual(55);
      expect(frame.fps).toBeLessThanOrEqual(65);
      expect(frame.frameMs).toBeGreaterThanOrEqual(0);
    }
    expect(kinds().filter((kind) => kind === "ready")).toHaveLength(1);
    host.destroy();
  });

  it("stops stepping frames while minimised and resumes for hero", () => {
    const gl = fakeGl();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext")
      .mockReturnValue(gl as unknown as WebGL2RenderingContext);
    const clock = new ManualClock();
    const { reports, host } = bootHost(clock);
    clock.run(160);
    const drawn = gl.drawArrays.mock.calls.length;
    expect(drawn).toBeGreaterThan(5);

    host.apply({ presentation: "minimised" });
    expect(clock.pendingFrames() + clock.pendingWaits()).toBe(0);
    const before = reports.length;
    clock.run(3000);
    expect(gl.drawArrays).toHaveBeenCalledTimes(drawn);
    // No frame reports while nothing is drawn.
    expect(reports.length).toBe(before);

    host.apply({ presentation: "hero" });
    expect(clock.pendingFrames()).toBe(1);
    clock.tick();
    expect(gl.drawArrays).toHaveBeenCalledTimes(drawn + 1);
    host.destroy();
  });

  it("caps conversation at 30 fps and reduced motion at one frame a second on a timer", () => {
    const gl = fakeGl();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext")
      .mockReturnValue(gl as unknown as WebGL2RenderingContext);
    const clock = new ManualClock();
    const { reports, host } = bootHost(clock, { presentation: "conversation" });
    clock.run(2200);
    const frame = reports.find((report) => report.type === "frame");
    expect(frame?.type).toBe("frame");
    if (frame?.type === "frame") {
      expect(frame.fps).toBeGreaterThanOrEqual(28);
      expect(frame.fps).toBeLessThanOrEqual(34);
    }

    // Reduced motion rebuilds the renderer (it reads the preference once) and
    // sleeps on a timer between frames rather than polling the display.
    host.apply({ reducedMotion: true });
    expect(clock.pendingFrames()).toBe(0);
    expect(clock.pendingWaits()).toBe(1);
    const drawn = gl.drawArrays.mock.calls.length;
    clock.run(2100);
    const slowFrames = gl.drawArrays.mock.calls.length - drawn;
    expect(slowFrames).toBeGreaterThanOrEqual(2);
    expect(slowFrames).toBeLessThanOrEqual(3);
    // The rebuilt renderer paints again; ready is posted on CHANGE, so once.
    expect(reports.filter((report) => report.type === "ready")).toHaveLength(1);
    host.destroy();
  });

  it("pauses while the document is hidden and restarts when it is shown", () => {
    const gl = fakeGl();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext")
      .mockReturnValue(gl as unknown as WebGL2RenderingContext);
    const clock = new ManualClock();
    const { host } = bootHost(clock);
    clock.run(64);
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(clock.pendingFrames() + clock.pendingWaits()).toBe(0);
    const drawn = gl.drawArrays.mock.calls.length;
    clock.run(160);
    expect(gl.drawArrays).toHaveBeenCalledTimes(drawn);
    hidden.mockReturnValue(false);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(clock.pendingFrames()).toBe(1);
    clock.tick();
    expect(gl.drawArrays).toHaveBeenCalledTimes(drawn + 1);
    host.destroy();
  });

  it("turns a frame that throws into fallback and stops the loop", () => {
    const gl = fakeGl();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext")
      .mockReturnValue(gl as unknown as WebGL2RenderingContext);
    const clock = new ManualClock();
    const { reports, host } = bootHost(clock);
    clock.tick();
    gl.viewport.mockImplementationOnce(() => { throw new Error("context lost"); });
    clock.tick();
    expect(reports.at(-1)).toEqual({ type: "fallback", reason: "context lost" });
    expect(clock.pendingFrames() + clock.pendingWaits()).toBe(0);
    host.destroy();
  });

  it("reports each distinct bad message once and keeps rendering", () => {
    const gl = fakeGl();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext")
      .mockReturnValue(gl as unknown as WebGL2RenderingContext);
    const clock = new ManualClock();
    const { reports, host, kinds } = bootHost(clock);
    host.apply({ v: 3 });
    host.apply({ v: 3 });
    host.apply("nope");
    expect(kinds().filter((kind) => kind === "error")).toHaveLength(2);
    expect(reports[0]).toMatchObject({ type: "error", message: expect.stringContaining("v3") });
    clock.tick();
    expect(gl.drawArrays).toHaveBeenCalledTimes(1);
    host.destroy();
  });
});

// ---------------------------------------------------------- the shipped page

describe("the committed Familiar island page", () => {
  const html = readFileSync(resolve(ISLAND_DIR, "familiar-island.html"), "utf8");
  const manifest = JSON.parse(readFileSync(resolve(ISLAND_DIR, "familiar-island.manifest.json"), "utf8")) as {
    v: number; sourceCommit: string; fragSha256: string; htmlBytes: number;
  };

  it("carries exactly the pinned shader", () => {
    const fragSha = createHash("sha256").update(readFileSync(FRAG)).digest("hex");
    const character = JSON.parse(readFileSync(CHARACTER, "utf8")) as {
      visual: { fragment: { sha256: string } };
    };
    expect(manifest.v).toBe(1);
    expect(manifest.fragSha256).toBe(fragSha);
    expect(manifest.fragSha256).toBe(character.visual.fragment.sha256);
    expect(manifest.sourceCommit).toMatch(/^[0-9a-f]{40}$/);
  });

  it("is one small self-contained file", () => {
    expect(Buffer.byteLength(html, "utf8")).toBe(manifest.htmlBytes);
    expect(manifest.htmlBytes).toBeLessThan(200 * 1024);
    expect(html).not.toMatch(/<script\b[^>]*\bsrc=/);
    expect(html).not.toContain("<link");
    expect(html).toContain('<div id="familiar"></div>');
  });

  // The pin IS the policy: a page whose CSP hash did not match its own script
  // would load a blank web view with one console line nobody reads.
  it("pins its inline script by the hash its CSP names", () => {
    const csp = /content="default-src 'none'; script-src 'sha256-([A-Za-z0-9+/=]+)'; style-src 'unsafe-inline'; img-src data:"/
      .exec(html);
    expect(csp).toBeTruthy();
    const script = /<script>([\s\S]*?)<\/script>\s*<\/body>/.exec(html);
    expect(script).toBeTruthy();
    const hash = createHash("sha256").update(script![1]!, "utf8").digest("base64");
    expect(hash).toBe(csp![1]);
    expect(html).not.toContain("connect-src");
  });

  it("names no other companion", () => {
    const lower = html.toLowerCase();
    for (const name of ["jarvis", "ultron", "colossus"]) expect(lower).not.toContain(name);
  });
});
