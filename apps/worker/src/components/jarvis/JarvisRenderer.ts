// The HUD instrument renderer: jarvis.frag on a WebGL2 canvas. It is a sibling
// of FamiliarWebGLRenderer, not a subclass; only the Stage lifecycle matches.
// Everything shown is a crossfaded mode weight or live voice, never invented
// mood. The shader remains the visual source of truth; this file decides WHEN.
// jarvis.frag lives in the character bundle and is byte-pinned by its manifest.
// jarvis-post.frag stays here as Boltrig rendering machinery: a bundle never
// carries a renderer.
import fragSrc from "../../bundles/jarvis/jarvis.frag?raw";
import postSrc from "./jarvis-post.frag?raw";
import {
  advanceSpin,
  approach,
  stepSweep,
  sweepPeriod,
  WAVE_SAMPLES,
} from "./JarvisMotion";
import { GENE, genotypeFrom } from "./JarvisGenotype";
import { NO_TELEMETRY, type JarvisTelemetry } from "./JarvisTelemetry";
import { NO_WORK, type JarvisWork } from "./JarvisWork";
import {
  clampJarvisState,
  labelsForMode,
  RESTING_JARVIS_STATE,
  type JarvisMode,
  type JarvisRendererStatus,
  type JarvisStageState,
} from "./JarvisState";
const VERT_SRC = `#version 300 es
void main() {
  vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
  gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}`;

// Exported for the canvas source. `uGene` is identity uploaded once at mount,
// not a per-frame channel, so it is deliberately absent from this list.
export const UNIFORMS = [
  "iResolution", "iTime", "uListening", "uThinking", "uWorking", "uSpeaking",
  "uLevel", "uOnset", "uBands", "uWave", "uWaveHead", "uReadout", "uReduced",
  "uAccent", "uScale", "uLabelTop", "uLabelBottom", "uLabelTopAmt",
  "uLabelBottomAmt", "uSpin", "uPhenoFresh",
  "uValence", "uArousal", "uIrritation", "uFatigue", "uAttention",
  "uLuminosity", "uTension",
  "uBudgetFill", "uBudgetKnown", "uBudgetHard", "uTokenFill", "uTokenKnown",
  "uWorkLoad", "uWorkFail", "uHDR", "uSpinDelta", "uParallax",
] as const;
type UniformName = (typeof UNIFORMS)[number];

/** The ten server phenotype scalars (decision 0013 + 0024's attachment). */
const PHENO_KEYS = [
  "valence", "arousal", "irritation", "fatigue", "attention",
  "social", "buoyancy", "luminosity", "tension", "attachment",
] as const;
type PhenoKey = (typeof PHENO_KEYS)[number];
type Phenotype = Record<PhenoKey, number>;

/**
 * Rest values. Read them as "nothing is known", not "the agent is calm": the
 * instrument sits at neutral and drops its signal ring rather than performing a
 * mood it has not been told about.
 *
 * This is the one place the instrument deliberately diverges from the Familiar,
 * whose renderer WANDERS its mood when the relay is absent so the creature
 * still looks alive. A creature may idle plausibly; an instrument that invents
 * a reading is broken.
 */
const RESTING_PHENOTYPE: Phenotype = {
  valence: 0.5, arousal: 0.28, irritation: 0, fatigue: 0, attention: 0.5,
  social: 0.5, buoyancy: 0.5, luminosity: 0.5, tension: 0, attachment: 0.5,
};

/** Phenotype crossfade time constant — mood morphs, it never snaps. */
const PHENO_TAU = 2.0;

/** How long a phenotype sample stays usable before the dial drops to rest. */
const PHENO_STALE_MS = 10_000;

/** Mode crossfade time constant. Slow enough to read as a morph, not a cut. */
const MODE_TAU = 0.18;

/** Work-load settle. Fast enough to feel causal, slow enough not to strobe. */
const WORK_TAU = 0.35;

const WEIGHTED_MODES = ["listening", "thinking", "working", "speaking"] as const;
type WeightedMode = (typeof WEIGHTED_MODES)[number];

const POST_UNIFORMS = [
  "uTex", "uScene", "uTexel", "uResolution", "uPass",
  "uThreshold", "uKnee", "uStrength", "uTime",
] as const;
type PostUniformName = (typeof POST_UNIFORMS)[number];

const PASS = { BRIGHT: 0, BLUR_H: 1, BLUR_V: 2, COMPOSITE: 3 } as const;

/** Bloom is gathered at quarter resolution; the blur is wide, the cost is not. */
const BLOOM_DIVISOR = 4;

// Tuned against the reference frames. The threshold sits just under the ring
// dashes so the housing contributes a little wash, while the core and the
// gauges — the things that are meant to read as raw light — carry most of it.
const BLOOM_THRESHOLD = 0.55;
const BLOOM_KNEE = 0.25;
const BLOOM_STRENGTH = 0.80;
interface RenderTarget {
  fbo: WebGLFramebuffer;
  tex: WebGLTexture;
  width: number;
  height: number;
}
export interface JarvisRendererOptions {
  reducedMotion?: boolean;
  maxDevicePixelRatio?: number;
  /** Linear RGB accent; defaults to the instrument's own violet. */
  accent?: readonly [number, number, number];
  /** Dial size multiplier; 1.0 is the tuned default. */
  scale?: number;
  /**
   * Who draws the state words. "shader" uses the built-in glyph atlas and is
   * the only option the desktop GLES host can honour; "none" stands the atlas
   * down so a DOM overlay can take over (see JarvisLabels).
   */
  labels?: "shader" | "none";
  /**
   * Offscreen bloom. Defaults on. Turning it off falls back to the single-pass
   * path the desktop host uses — the dial still draws, it just relies on the
   * per-element skirt instead of real image-wide glow.
   */
  bloom?: boolean;
  /**
   * Identity the dial derives its genotype from — an agent capability name, an
   * org id, whatever the caller considers "who this is". Absent gives the
   * hand-tuned neutral instrument, never a random one.
   */
  identity?: string | null;
  /**
   * "auto" (default) shrinks the dial when the stage slot is close to square,
   * so it keeps breathing room. "fixed" always honours `scale` exactly.
   */
  fit?: "auto" | "fixed";
}
export class JarvisWebGLRenderer {
  readonly kind = "webgl2" as const;

  private host: HTMLElement | null = null;
  private canvas: HTMLCanvasElement | null = null;
  private gl: WebGL2RenderingContext | null = null;
  private uniforms: Partial<Record<UniformName, WebGLUniformLocation | null>> = {};
  private raf = 0;
  private statusValue: JarvisRendererStatus = { kind: "webgl2", state: "mounted" };
  private startTime = 0;
  private lastFrameT = 0;
  private lastReducedFrame = -Infinity;

  private readonly reducedMotion: boolean;
  private readonly maxDevicePixelRatio: number;
  private accent: readonly [number, number, number];
  private scale: number;
  private readonly labels: "shader" | "none";
  private readonly wantBloom: boolean;
  private readonly genes: Float32Array;
  private geneLoc: WebGLUniformLocation | null = null;
  private genesDirty = false;
  private presence = 1;
  private bloomTuning: readonly [number, number, number] =
    [BLOOM_THRESHOLD, BLOOM_KNEE, BLOOM_STRENGTH];
  private readonly fit: "auto" | "fixed";

  private sceneProgram: WebGLProgram | null = null;
  private postProgram: WebGLProgram | null = null;
  private postUniforms: Partial<Record<PostUniformName, WebGLUniformLocation | null>> = {};
  private scene: RenderTarget | null = null;
  private bloomA: RenderTarget | null = null;
  private bloomB: RenderTarget | null = null;
  /** False when the context cannot give us render targets; falls back cleanly. */
  private bloomReady = false;
  private floatTargets = false;

  private state: JarvisStageState = RESTING_JARVIS_STATE;
  private weights: Record<WeightedMode, number> = {
    listening: 0, thinking: 0, working: 0, speaking: 0,
  };

  // The listening sweep. `head` is where the write cursor sits, in turns
  // clockwise from 12 o'clock; the buffer is wiped when it passes 12 again,
  // which is what makes the trace vanish rather than overwrite itself.
  private wave = new Float32Array(WAVE_SAMPLES);
  private waveHead = 0;
  /** How long the current listening spell has run; stretches the sweep period. */
  private listenSpell = 0;
  private bandScratch = new Float32Array(8);

  private pheno: Phenotype = { ...RESTING_PHENOTYPE };
  private phenoFresh = 0;
  private serverPheno: { at: number; scalars: Partial<Phenotype> } | null = null;

  /**
   * Integrated rotation phase. Arousal and fatigue move the rate, so the phase
   * has to be accumulated rather than computed as time x rate — otherwise every
   * mood shift would jump the rings to a new position.
   */
  private spin = 0;
  private spinDelta = 0;

  /**
   * Pointer parallax for the circuit field, smoothed. Depth is the one cue a
   * flat dial cannot fake, and the board is the only layer that can carry it
   * without desyncing the DOM labels pinned to the dial centre.
   */
  private parallax = { x: 0, y: 0, targetX: 0, targetY: 0 };
  private onPointer: ((event: PointerEvent) => void) | null = null;

  /** Real readings. Absent until the host supplies them — never faked. */
  private telemetry: JarvisTelemetry = NO_TELEMETRY;

  /**
   * Live DAG load. Smoothed toward its target rather than applied raw: tool
   * calls settle in bursts, and an unsmoothed load makes the board strobe.
   */
  private work: JarvisWork = NO_WORK;
  private workLoad = 0;
  private workFail = 0;

  /**
   * Buoyancy is the one phenotype scalar that is NOT a uniform. It lifts the
   * whole instrument, and the SVG labels are registered to the dial centre —
   * so moving the dial inside the shader would slide it out from under its own
   * words. It is published as a CSS custom property on the stage element
   * instead, which moves canvas and DOM as one.
   *
   * Written only when it moves materially: a style write every frame would
   * invalidate layout 60 times a second for a value nobody can see change
   * that fast.
   */
  private publishedBob = -1;

  constructor(options?: JarvisRendererOptions) {
    this.reducedMotion = options?.reducedMotion
      ?? (typeof window !== "undefined"
        && typeof window.matchMedia === "function"
        && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    this.accent = options?.accent ?? [0.478, 0.365, 0.878];
    this.maxDevicePixelRatio = Math.max(1, Math.min(2, options?.maxDevicePixelRatio ?? 1.25));
    this.scale = options?.scale ?? 1;
    this.labels = options?.labels ?? "shader";
    this.wantBloom = options?.bloom ?? true;
    this.genes = genotypeFrom(options?.identity);
    this.fit = options?.fit ?? "auto";
  }

  mount(container: HTMLElement): void {
    this.host = container;
    // Reduced motion gets no parallax at all: it is decorative depth, and it
    // moves with the pointer, which is exactly the kind of motion the setting
    // is asking us to stop.
    if (!this.reducedMotion) {
      this.onPointer = (event: PointerEvent) => {
        const box = container.getBoundingClientRect();
        if (!box.width || !box.height) return;
        // -1..1 from the centre, then a few thousandths of a p unit: enough to
        // read as depth, far too little to look like the background sliding.
        const nx = (event.clientX - box.left) / box.width * 2 - 1;
        const ny = (event.clientY - box.top) / box.height * 2 - 1;
        this.parallax.targetX = -nx * 0.016;
        this.parallax.targetY = ny * 0.016;
      };
      container.addEventListener("pointermove", this.onPointer);
      container.addEventListener("pointerleave", () => {
        this.parallax.targetX = 0;
        this.parallax.targetY = 0;
      });
    }
    const canvas = document.createElement("canvas");
    canvas.className = "jarvis-stage-canvas";
    container.appendChild(canvas);
    this.canvas = canvas;

    const gl = canvas.getContext("webgl2", { alpha: false, antialias: false });
    if (!gl) {
      this.fail("WebGL2 context unavailable");
      return;
    }
    this.gl = gl;

    try {
      const vs = this.compile(gl.VERTEX_SHADER, VERT_SRC);
      const fs = this.compile(gl.FRAGMENT_SHADER, fragSrc);
      const prog = gl.createProgram();
      if (!prog) throw new Error("createProgram returned null");
      gl.attachShader(prog, vs);
      gl.attachShader(prog, fs);
      gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
        throw new Error(gl.getProgramInfoLog(prog) ?? "unknown link error");
      }
      gl.deleteShader(vs);
      gl.deleteShader(fs);
      gl.useProgram(prog);
      this.sceneProgram = prog;
      // Genotype is identity, not state: uploaded once at mount rather than
      // every frame, and changing it rebuilds the renderer.
      const geneLoc = gl.getUniformLocation(prog, "uGene")
        ?? gl.getUniformLocation(prog, "uGene[0]");
      this.geneLoc = geneLoc;
      if (geneLoc) gl.uniform4fv(geneLoc, this.genes);
      // Array uniforms answer to "name[0]" on some drivers and bare "name" on
      // others; ask for both rather than silently binding to null.
      for (const name of UNIFORMS) {
        this.uniforms[name] = gl.getUniformLocation(prog, name)
          ?? gl.getUniformLocation(prog, `${name}[0]`);
      }
    } catch (error) {
      // Per the design brief: never rewrite the look to survive a failure —
      // report it and let the Stage fall back.
      this.fail(error instanceof Error ? error.message : String(error));
      return;
    }

    if (this.wantBloom) this.setUpBloom(gl);

    this.startTime = performance.now();
    this.lastFrameT = this.startTime;
    this.statusValue = { kind: "webgl2", state: "running" };
    this.raf = requestAnimationFrame(this.frame);
  }

  update(next: Partial<JarvisStageState>): void {
    this.state = clampJarvisState(next);
  }

  /**
   * Live phenotype from the server projection. While fresh it OWNS the dial's
   * colour, rate, contrast and gauge density; when it goes null or stale the
   * instrument eases back to rest and drops its signal ring. Same seam and same
   * staleness rule as FamiliarWebGLRenderer.applyPhenotype, so both bodies read
   * one inner life.
   */
  applyPhenotype(scalars: Partial<Record<PhenoKey, number>> | null): void {
    this.serverPheno = scalars ? { at: performance.now(), scalars } : null;
  }

  /**
   * Real gauge readings, from GET /v1/budgets via telemetryFromBudgets. Pass
   * null to clear: the tracks fall back to ghosts, which is the honest
   * rendering of "no reading" and is NOT the same as a gauge at zero.
   */
  /**
   * THE BENCH'S LIVE KNOBS: identity genes, accent, scale, bloom -- the
   * honest set this renderer can change without a remount. Genes re-upload
   * on the next frame, where the scene program is bound; unknown fields are
   * ignored so the tuning object can grow without breaking this renderer.
   */
  setTuning(next: Partial<{
    presence: number;
    accent: readonly [number, number, number];
    scale: number;
    bloom: readonly [number, number, number];
  }> & Partial<Record<keyof typeof GENE, number>>): void {
    if (typeof next.presence === "number" && Number.isFinite(next.presence)) {
      this.presence = Math.min(2.5, Math.max(0.2, next.presence));
    }
    if (Array.isArray(next.accent) && next.accent.length === 3) {
      this.accent = [next.accent[0], next.accent[1], next.accent[2]];
    }
    if (typeof next.scale === "number" && Number.isFinite(next.scale)) this.scale = next.scale;
    if (Array.isArray(next.bloom) && next.bloom.length === 3) {
      this.bloomTuning = [next.bloom[0], next.bloom[1], next.bloom[2]];
    }
    for (const [field, index] of Object.entries(GENE)) {
      const value = (next as Record<string, unknown>)[field];
      if (typeof value === "number" && Number.isFinite(value)) {
        this.genes[index] = value;
        this.genesDirty = true;
      }
    }
  }

  applyTelemetry(next: JarvisTelemetry | null): void {
    this.telemetry = next ?? NO_TELEMETRY;
  }

  /**
   * Live work from the turn being streamed (see workFromTurn). Pass null when
   * no turn is in flight — a dark board is the honest rendering of no work.
   */
  applyWork(next: JarvisWork | null): void {
    this.work = next ?? NO_WORK;
  }

  private phenoTick(now: number, dt: number): void {
    const live = this.serverPheno && now - this.serverPheno.at < PHENO_STALE_MS
      ? this.serverPheno
      : null;

    for (const key of PHENO_KEYS) {
      const raw = live?.scalars[key];
      const target = typeof raw === "number" && Number.isFinite(raw)
        ? Math.min(1, Math.max(0, raw))
        : RESTING_PHENOTYPE[key];
      this.pheno[key] = approach(this.pheno[key], target, dt, PHENO_TAU);
    }
    // Crossfaded too, so losing the relay fades the signal ring out instead of
    // snapping it off.
    this.phenoFresh = approach(this.phenoFresh, live ? 1 : 0, dt, PHENO_TAU);
  }

  suspend(): void {
    if (this.statusValue.state !== "running") return;
    cancelAnimationFrame(this.raf);
    this.statusValue = { kind: "webgl2", state: "suspended" };
  }

  resume(): void {
    if (this.statusValue.state !== "suspended") return;
    this.statusValue = { kind: "webgl2", state: "running" };
    this.lastFrameT = performance.now();
    this.raf = requestAnimationFrame(this.frame);
  }

  status(): JarvisRendererStatus {
    return this.statusValue;
  }

  destroy(): void {
    cancelAnimationFrame(this.raf);
    const gl = this.gl;
    if (gl) {
      this.dropTarget(gl, this.scene);
      this.dropTarget(gl, this.bloomA);
      this.dropTarget(gl, this.bloomB);
      this.scene = this.bloomA = this.bloomB = null;
    }
    this.gl?.getExtension("WEBGL_lose_context")?.loseContext();
    if (this.host && this.onPointer) {
      this.host.removeEventListener("pointermove", this.onPointer);
    }
    this.onPointer = null;
    this.canvas?.remove();
    this.canvas = null;
    this.gl = null;
    this.host = null;
    this.statusValue = { kind: "webgl2", state: "destroyed" };
  }

  /**
   * Builds the offscreen chain. Any failure here is NOT fatal: bloomReady stays
   * false and the renderer draws straight to the screen with the shader's own
   * grade, which is exactly what the desktop host does. A missing float
   * extension should cost glow, never the instrument.
   */
  private setUpBloom(gl: WebGL2RenderingContext): void {
    try {
      const vs = this.compile(gl.VERTEX_SHADER, VERT_SRC);
      const fs = this.compile(gl.FRAGMENT_SHADER, postSrc);
      const prog = gl.createProgram();
      if (!prog) throw new Error("createProgram returned null");
      gl.attachShader(prog, vs);
      gl.attachShader(prog, fs);
      gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
        throw new Error(gl.getProgramInfoLog(prog) ?? "post link failed");
      }
      gl.deleteShader(vs);
      gl.deleteShader(fs);
      this.postProgram = prog;
      for (const name of POST_UNIFORMS) {
        this.postUniforms[name] = gl.getUniformLocation(prog, name);
      }
      // Half-float render targets keep highlights above 1.0 so the bright pass
      // has something to find. Without the extension we still bloom, just from
      // clamped light — visibly weaker, and worth not pretending otherwise.
      this.floatTargets = gl.getExtension("EXT_color_buffer_float") !== null;
      this.bloomReady = true;
    } catch {
      this.bloomReady = false;
    }
  }

  private makeTarget(
    gl: WebGL2RenderingContext, width: number, height: number,
  ): RenderTarget | null {
    const tex = gl.createTexture();
    const fbo = gl.createFramebuffer();
    if (!tex || !fbo) return null;
    gl.bindTexture(gl.TEXTURE_2D, tex);
    const internal = this.floatTargets ? gl.RGBA16F : gl.RGBA8;
    const type = this.floatTargets ? gl.HALF_FLOAT : gl.UNSIGNED_BYTE;
    gl.texImage2D(gl.TEXTURE_2D, 0, internal, width, height, 0, gl.RGBA, type, null);
    // CLAMP_TO_EDGE matters: the blur reads past the edge, and REPEAT would
    // wrap the core's glow around to the opposite side of the dial.
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
    gl.framebufferTexture2D(
      gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0,
    );
    const ok = gl.checkFramebufferStatus(gl.FRAMEBUFFER) === gl.FRAMEBUFFER_COMPLETE;
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    if (!ok) {
      gl.deleteTexture(tex);
      gl.deleteFramebuffer(fbo);
      return null;
    }
    return { fbo, tex, width, height };
  }

  private dropTarget(gl: WebGL2RenderingContext, target: RenderTarget | null): void {
    if (!target) return;
    gl.deleteTexture(target.tex);
    gl.deleteFramebuffer(target.fbo);
  }

  /** Rebuilds the chain when the canvas size changes. */
  private sizeTargets(gl: WebGL2RenderingContext, w: number, h: number): void {
    if (!this.bloomReady) return;
    if (this.scene && this.scene.width === w && this.scene.height === h) return;
    this.dropTarget(gl, this.scene);
    this.dropTarget(gl, this.bloomA);
    this.dropTarget(gl, this.bloomB);
    const bw = Math.max(1, Math.floor(w / BLOOM_DIVISOR));
    const bh = Math.max(1, Math.floor(h / BLOOM_DIVISOR));
    this.scene = this.makeTarget(gl, w, h);
    this.bloomA = this.makeTarget(gl, bw, bh);
    this.bloomB = this.makeTarget(gl, bw, bh);
    if (!this.scene || !this.bloomA || !this.bloomB) this.bloomReady = false;
  }

  private postPass(
    gl: WebGL2RenderingContext,
    pass: number,
    source: RenderTarget,
    into: RenderTarget | null,
    t: number,
  ): void {
    const u = this.postUniforms;
    const width = into?.width ?? gl.drawingBufferWidth;
    const height = into?.height ?? gl.drawingBufferHeight;
    gl.bindFramebuffer(gl.FRAMEBUFFER, into?.fbo ?? null);
    gl.viewport(0, 0, width, height);
    gl.uniform1i(u.uPass ?? null, pass);
    gl.uniform2f(u.uResolution ?? null, width, height);
    gl.uniform2f(u.uTexel ?? null, 1 / source.width, 1 / source.height);
    gl.uniform1f(u.uTime ?? null, t);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, source.tex);
    gl.uniform1i(u.uTex ?? null, 0);
    if (pass === PASS.COMPOSITE && this.scene) {
      gl.activeTexture(gl.TEXTURE1);
      gl.bindTexture(gl.TEXTURE_2D, this.scene.tex);
      gl.uniform1i(u.uScene ?? null, 1);
    }
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  private fail(reason: string): void {
    this.canvas?.remove();
    this.canvas = null;
    this.gl = null;
    this.statusValue = { kind: "webgl2", state: "failed", reason };
  }

  private compile(type: number, src: string): WebGLShader {
    const gl = this.gl;
    if (!gl) throw new Error("no context");
    const shader = gl.createShader(type);
    if (!shader) throw new Error("createShader returned null");
    gl.shaderSource(shader, src);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      const log = gl.getShaderInfoLog(shader);
      gl.deleteShader(shader);
      throw new Error(log ?? "unknown shader compile error");
    }
    return shader;
  }

  /** Buoyancy -> a CSS bob amplitude in px on the stage element. */
  private publishBob(): void {
    const bob = this.pheno.buoyancy;
    if (Math.abs(bob - this.publishedBob) < 0.02) return;
    this.publishedBob = bob;
    // 0.5 is neutral, so a resting instrument does not drift upward.
    this.host?.style.setProperty("--jarvis-bob", `${(bob * 10).toFixed(1)}px`);
  }

  /**
   * The dial is sized off the SHORT side, so in a near-square slot it fills the
   * long side too and reads as crowded. This gives it margin back without
   * changing any radius — the alternative would be moving geometry per aspect,
   * which would break the SVG label overlay's fixed mapping.
   */
  private fitScale(w: number, h: number): number {
    if (this.fit === "fixed") return 1;
    const aspect = Math.max(w, h) / Math.max(1, Math.min(w, h));
    // 1.0 (square) -> 0.82; 1.5 or wider -> 1.0.
    const t = Math.min(1, Math.max(0, (aspect - 1) / 0.5));
    return 0.82 + 0.18 * t;
  }

  private resizeCanvas(): void {
    const canvas = this.canvas;
    if (!canvas) return;
    const scale = Math.min(window.devicePixelRatio || 1, this.maxDevicePixelRatio);
    const w = Math.max(1, Math.round((canvas.clientWidth || 1) * scale));
    const h = Math.max(1, Math.round((canvas.clientHeight || 1) * scale));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
  }

  private modeTick(dt: number, mode: JarvisMode): void {
    for (const key of WEIGHTED_MODES) {
      this.weights[key] = approach(this.weights[key], mode === key ? 1 : 0, dt, MODE_TAU);
    }
  }

  /**
   * Advances the listening sweep and writes the current microphone level into
   * every slot the head crossed this frame, so a slow frame leaves a continuous
   * trace instead of a comb of gaps.
   */
  private waveTick(dt: number, listening: boolean, micLevel: number): void {
    if (!listening) {
      if (this.waveHead !== 0 || this.listenSpell !== 0) {
        this.wave.fill(0);
        this.waveHead = 0;
        this.listenSpell = 0;
      }
      return;
    }
    this.listenSpell += dt;
    this.waveHead = stepSweep(
      this.wave, this.waveHead, dt, micLevel, sweepPeriod(this.listenSpell),
    ).head;
  }

  private frame = (now: number): void => {
    if (this.statusValue.state !== "running") return;
    this.raf = requestAnimationFrame(this.frame);
    const gl = this.gl;
    const canvas = this.canvas;
    if (!gl || !canvas || document.hidden) return;

    // Reduced motion: a still instrument — one frame per second, no drift.
    if (this.reducedMotion) {
      if (now - this.lastReducedFrame < 1000) return;
      this.lastReducedFrame = now;
    }

    this.resizeCanvas();
    const w = canvas.width;
    const h = canvas.height;
    this.sizeTargets(gl, w, h);
    const offscreen = this.bloomReady && this.scene && this.bloomA && this.bloomB;

    if (this.sceneProgram) gl.useProgram(this.sceneProgram);
    gl.bindFramebuffer(gl.FRAMEBUFFER, offscreen ? this.scene!.fbo : null);
    gl.viewport(0, 0, w, h);

    const t = (now - this.startTime) / 1000;
    const dt = Math.min(0.25, Math.max(0, (now - this.lastFrameT) / 1000));
    this.lastFrameT = now;

    const { mode, level, bands, onset, micLevel, readout } = this.state;

    // Reduced motion means DO NOT ANIMATE. It does not mean do not inform.
    //
    // These ticks all used to sit behind `if (!this.reducedMotion)`, which
    // froze the instrument's mind as well as its movement: the mode never
    // crossfaded off standby, the phenotype never arrived and the work load
    // never moved — while the gauges kept updating, because they are read
    // straight from telemetry at upload. A user who asked not to be made dizzy
    // was given a dial that lied about what the agent was doing.
    //
    // So state always ticks. What reduced motion suppresses is MOTION: the
    // rotation phase stops advancing (below) and the shader's own `uReduced`
    // freezes its internal time, which is where the drift, breathing and pulse
    // animation live.
    this.modeTick(dt, mode);
    this.phenoTick(now, dt);
    this.waveTick(dt, mode === "listening", micLevel ?? 0);

    // ~0.35s to settle: fast enough to feel causal when a tool fires, slow
    // enough that a burst of results does not strobe the board.
    this.workLoad = approach(this.workLoad, this.work.load, dt, WORK_TAU);
    this.workFail = approach(this.workFail, this.work.fail, dt, WORK_TAU);

    if (!this.reducedMotion) {
      // Arousal drives the dial's rate; fatigue drags on it. Integrated, never
      // derived from t — see the `spin` field.
      const before = this.spin;
      this.spin = advanceSpin(this.spin, dt, this.pheno.arousal, this.pheno.fatigue);
      // How far the rings turned this frame. The shader smears each rotating
      // element by exactly this much at its own radius, which is what lets a
      // hairline spin fast without strobing.
      this.spinDelta = this.spin - before;
      this.publishBob();
      this.parallax.x = approach(this.parallax.x, this.parallax.targetX, dt, 0.28);
      this.parallax.y = approach(this.parallax.y, this.parallax.targetY, dt, 0.28);
    }

    if (bands && bands.length === 8) this.bandScratch.set(bands);
    else if (mode === "speaking") {
      // No spectrum available: a plausible envelope beats a dead fan.
      const amp = 0.35 + 0.55 * (level || 0.5);
      for (let i = 0; i < 8; i++) {
        this.bandScratch[i] = Math.max(
          0,
          amp * (0.9 - i * 0.07) * (0.6 + 0.4 * Math.sin(t * (2.2 + i * 0.4) + i)),
        );
      }
    } else this.bandScratch.fill(0);

    const u = this.uniforms;
    const f = (name: UniformName, value: number) => gl.uniform1f(u[name] ?? null, value);
    const i1 = (name: UniformName, value: number) => gl.uniform1i(u[name] ?? null, value);

    gl.uniform2f(u.iResolution ?? null, w, h);
    f("iTime", t);
    f("uListening", this.weights.listening);
    f("uThinking", this.weights.thinking);
    f("uWorking", this.weights.working);
    f("uSpeaking", this.weights.speaking);
    f("uLevel", level);
    f("uOnset", onset ?? 0);
    gl.uniform4fv(u.uBands ?? null, this.bandScratch);
    gl.uniform4fv(u.uWave ?? null, this.wave);
    f("uWaveHead", this.waveHead);
    f("uReadout", readout ?? 0);
    f("uReduced", this.reducedMotion ? 1 : 0);
    gl.uniform3f(u.uAccent ?? null, this.accent[0], this.accent[1], this.accent[2]);
    f("uScale", this.scale * this.presence * this.fitScale(w, h));
    if (this.genesDirty && this.geneLoc) {
      // The scene program is bound here, which is where uGene lives.
      gl.uniform4fv(this.geneLoc, this.genes);
      this.genesDirty = false;
    }

    f("uSpin", this.spin);
    f("uSpinDelta", this.spinDelta);
    gl.uniform2f(u.uParallax ?? null, this.parallax.x, this.parallax.y);
    f("uPhenoFresh", this.phenoFresh);
    f("uValence", this.pheno.valence);
    f("uArousal", this.pheno.arousal);
    f("uIrritation", this.pheno.irritation);
    f("uFatigue", this.pheno.fatigue);
    f("uAttention", this.pheno.attention);
    f("uLuminosity", this.pheno.luminosity);
    f("uTension", this.pheno.tension);

    const { budget, tokens } = this.telemetry;
    f("uBudgetFill", budget.fill);
    f("uBudgetKnown", budget.known ? 1 : 0);
    f("uBudgetHard", budget.hard ? 1 : 0);
    f("uTokenFill", tokens.fill);
    f("uTokenKnown", tokens.known ? 1 : 0);

    f("uWorkLoad", this.workLoad);
    f("uWorkFail", this.workFail);

    const labels = labelsForMode(mode);
    const labelGain = this.labels === "shader" ? 1 : 0;
    i1("uLabelTop", labels.top);
    i1("uLabelBottom", labels.bottom);
    f("uLabelTopAmt", labels.topAmt * labelGain);
    f("uLabelBottomAmt", labels.bottomAmt * labelGain);

    f("uHDR", offscreen ? 1 : 0);
    gl.drawArrays(gl.TRIANGLES, 0, 3);

    if (!offscreen || !this.postProgram) return;

    // Bright-pass and downsample, blur on each axis, then composite back over
    // the untouched scene. Ping-pong between the two quarter-res targets so no
    // pass ever reads the target it is writing.
    gl.useProgram(this.postProgram);
    const pu = this.postUniforms;
    gl.uniform1f(pu.uThreshold ?? null, this.bloomTuning[0]);
    gl.uniform1f(pu.uKnee ?? null, this.bloomTuning[1]);
    gl.uniform1f(pu.uStrength ?? null, this.bloomTuning[2]);
    this.postPass(gl, PASS.BRIGHT, this.scene!, this.bloomA!, t);
    this.postPass(gl, PASS.BLUR_H, this.bloomA!, this.bloomB!, t);
    this.postPass(gl, PASS.BLUR_V, this.bloomB!, this.bloomA!, t);
    this.postPass(gl, PASS.COMPOSITE, this.bloomA!, null, t);
  };
}
