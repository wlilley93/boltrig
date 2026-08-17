// The universal Stage renderer (ADR 0025): the production Familiar shader on a
// WebGL2 canvas. Host logic is ported from boltrig-familiar-web's main.js — the
// companion/aperture uniform recipe, wandering mood baseline, ambient gesture
// envelope and reduced-motion behaviour are kept, so the creature here is the
// same being as the proven web port. The shader itself is vendored verbatim
// (familiar.frag); visual changes flow from boltrig-familiar, never start here.
import fragSrc from "../../bundles/familiar/familiar.frag?raw";
import type { FamiliarGenotype } from "@wlilley93/boltrig-web-sdk";
import { packFamiliarGenotype } from "./FamiliarGenotype";
import { VoiceEnvelope, dayWarmth, familiarDrive, type FamiliarDrive } from "./familiarDrive";
import {
  clampStageState,
  RESTING_STAGE_STATE,
  type FamiliarPresentationMode,
  type FamiliarRendererStatus,
  type FamiliarStageState,
} from "./FamiliarState";

const VERT_SRC = `#version 300 es
void main() {
  vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
  gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}`;

export const UNIFORMS = [
  "iTime", "iResolution", "uAudio", "uBeat", "uMouse", "uDay",
  "uValence", "uArousal", "uIrritation", "uFatigue", "uAttention",
  "uSocial", "uBuoyancy", "uLuminosity", "uTension", "uGesture",
  "uGestureAmt", "uPresence", "uCentreDock", "uScaleDock", "uFitScale",
  "uGaze", "uWorldRes", "uOrigin", "uPxScale", "uFill", "uPortWide",
  "uHover", "uCompanion", "uAperture",
  "uGene",
] as const;

type UniformName = (typeof UNIFORMS)[number];

const MOOD_KEYS = [
  "valence", "arousal", "attention", "social", "buoyancy", "luminosity", "tension",
  "irritation", "fatigue",
] as const;
type MoodKey = (typeof MOOD_KEYS)[number];
type Mood = Record<MoodKey, number>;

const rand = (a: number, b: number) => a + Math.random() * (b - a);

// Ambient voluntary gestures: mostly subtle (look, nod, preen, pulse), rarely
// celebrate. Ids match the shader's gesture enum.
const GESTURES_COMMON = [1, 6, 8, 2];

/** Voice owns a portrait, not the compact companion porthole used elsewhere. */
export function familiarCompositionForMode(mode: FamiliarPresentationMode): {
  fitScale: number;
  scaleDock: number;
} {
  return mode === "voice"
    ? { scaleDock: 0.45, fitScale: 0.62 }
    : { scaleDock: 0.34, fitScale: 0.5 };
}

/** One frame's worth of derived values, handed to the uniform push as a single
 *  argument. A bag rather than five positional parameters: they are all numbers
 *  of the same type, so a transposed pair would compile and simply draw wrong. */
interface FrameShot {
  w: number;
  h: number;
  t: number;
  now: number;
  drive: FamiliarDrive;
}

export class FamiliarWebGLRenderer {
  readonly kind = "webgl2" as const;

  private canvas: HTMLCanvasElement | null = null;
  private gl: WebGL2RenderingContext | null = null;
  private uniforms: Partial<Record<UniformName, WebGLUniformLocation | null>> = {};
  private raf = 0;
  private statusValue: FamiliarRendererStatus = { kind: "webgl2", state: "mounted" };
  private startTime = 0;
  private lastReducedFrame = -Infinity;
  private readonly reducedMotion: boolean;
  private readonly onFirstPaint?: () => void;
  private painted = false;
  private mode: FamiliarPresentationMode = "hero";

  private state: FamiliarStageState = RESTING_STAGE_STATE;

  // Inner life: the resting baseline wanders so the being is alive between
  // events (ported from boltrig-familiar-web; the desktop's emotion relay is
  // the eventual authoritative source through FamiliarState v2).
  private mood: { cur: Mood; tgt: Mood | null; tau: number; lastT: number; nextSwitch: number } = {
    cur: {
      valence: 0.5, arousal: 0.07, attention: 0.6, social: 0.5,
      buoyancy: 0.5, luminosity: 0.5, tension: 0, irritation: 0, fatigue: 0,
    },
    tgt: null,
    tau: 6,
    lastT: 0,
    nextSwitch: 0,
  };

  private gesture = { id: 0, amt: 0, start: 0, ttl: 2000, nextAt: 0 };
  private serverPhenotype:
    | { at: number; scalars: Partial<Record<MoodKey, number>> }
    | null = null;
  /** APERTURE HELD OPEN: Familiar does not arrive, she is there. She used to be
   *  born out of a black-hole aperture over 1400ms, inherited from the porthole
   *  path the summoned companions use. 1 is fully open and the shader's own hole
   *  gate -- 4a(1-a) -- is zero there. Kept as a field because uAperture is still
   *  uploaded and the companion path still means something by it. */
  private aperture = { value: 1, from: 1, to: 1, start: 0, dur: 0 };
  private packedGenotype = packFamiliarGenotype(null);

  constructor(options?: { reducedMotion?: boolean; onFirstPaint?: () => void }) {
    this.reducedMotion = options?.reducedMotion
      ?? (typeof window !== "undefined"
        && ((typeof window.matchMedia === "function"
          && window.matchMedia("(prefers-reduced-motion: reduce)").matches)
          || document.documentElement.classList.contains("reduce-motion")));
    this.onFirstPaint = options?.onFirstPaint;
  }

  mount(container: HTMLElement): void {
    const canvas = document.createElement("canvas");
    canvas.className = "familiar-stage-canvas";
    container.appendChild(canvas);
    this.canvas = canvas;

    const gl = canvas.getContext("webgl2", { alpha: true, antialias: false });
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
      for (const name of UNIFORMS) this.uniforms[name] = gl.getUniformLocation(prog, name);

      // GENOTYPE. The shader's 32 positional slots are packed from the
      // authoritative capability identity. Missing identity stays the exact
      // neutral defaults, including multiplier defaults in reserved slots.
      gl.uniform4fv(this.uniforms.uGene ?? null, this.packedGenotype);

    } catch (error) {
      // Per the design brief: never rewrite the look to survive a failure —
      // report it and let the Stage fall back to the badge.
      this.fail(error instanceof Error ? error.message : String(error));
      return;
    }

    this.startTime = performance.now();
    const now = this.startTime;
    this.mood.lastT = now;
    this.gesture.nextAt = now + rand(30_000, 90_000);
    this.aperture.start = now;
    this.statusValue = { kind: "webgl2", state: "running" };
    this.raf = requestAnimationFrame(this.frame);
  }

  update(next: Partial<FamiliarStageState>): void {
    this.state = clampStageState(next);
  }

  setGenotype(genotype?: FamiliarGenotype | null): void {
    this.packedGenotype = packFamiliarGenotype(genotype);
    if (this.gl) this.gl.uniform4fv(this.uniforms.uGene ?? null, this.packedGenotype);
  }

  /**
   * Live phenotype from the server projection (A3). While fresh it OWNS the
   * mood targets (the wandering baseline stands down); when it goes null or
   * stale the inner life resumes wandering, so an absent relay looks like a
   * calm being, never a broken one.
   */
  applyPhenotype(scalars: Partial<Record<MoodKey, number>> | null): void {
    this.serverPhenotype = scalars
      ? { at: performance.now(), scalars }
      : null;
  }

  setMode(mode: FamiliarPresentationMode): void {
    this.mode = mode;
    if (mode === "minimised") this.suspend();
    else this.resume();
  }

  suspend(): void {
    if (this.statusValue.state !== "running") return;
    cancelAnimationFrame(this.raf);
    this.statusValue = { kind: "webgl2", state: "suspended" };
  }

  resume(): void {
    if (this.statusValue.state !== "suspended") return;
    this.statusValue = { kind: "webgl2", state: "running" };
    this.raf = requestAnimationFrame(this.frame);
  }

  status(): FamiliarRendererStatus {
    return this.statusValue;
  }

  destroy(): void {
    cancelAnimationFrame(this.raf);
    this.gl?.getExtension("WEBGL_lose_context")?.loseContext();
    this.canvas?.remove();
    this.canvas = null;
    this.gl = null;
    this.statusValue = { kind: "webgl2", state: "destroyed" };
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

  private pickMood(now: number): void {
    const roll = Math.random();
    let m: Omit<Mood, "irritation" | "fatigue">;
    if (roll < 0.25) {
      m = { arousal: rand(0.5, 0.75), valence: rand(0.55, 0.9), attention: rand(0.75, 1),
        social: rand(0.65, 0.95), buoyancy: rand(0.6, 0.9), luminosity: rand(0.7, 1),
        tension: rand(0.05, 0.25) };
    } else if (roll < 0.55) {
      m = { arousal: rand(0.3, 0.55), valence: rand(0.6, 0.85), attention: rand(0.7, 0.95),
        social: rand(0.6, 0.9), buoyancy: rand(0.55, 0.85), luminosity: rand(0.6, 0.9),
        tension: rand(0.1, 0.3) };
    } else if (roll < 0.8) {
      m = { arousal: rand(0.05, 0.18), valence: rand(0.45, 0.6), attention: rand(0.3, 0.55),
        social: rand(0.35, 0.6), buoyancy: rand(0.45, 0.65), luminosity: rand(0.4, 0.6),
        tension: rand(0, 0.1) };
    } else {
      m = { arousal: rand(0.3, 0.55), valence: rand(0.35, 0.55), attention: rand(0.6, 0.85),
        social: rand(0.4, 0.7), buoyancy: rand(0.4, 0.6), luminosity: rand(0.45, 0.65),
        tension: rand(0.3, 0.6) };
    }
    this.mood.tgt = { ...m, irritation: 0, fatigue: 0 };
    this.mood.tau = rand(4, 8);
    this.mood.nextSwitch = now + rand(20_000, 45_000);
  }

  private moodTick(now: number): void {
    const server = this.serverPhenotype
      && now - this.serverPhenotype.at < 10_000
      ? this.serverPhenotype
      : null;
    if (server) {
      const target: Mood = { ...(this.mood.tgt ?? this.mood.cur) };
      for (const key of MOOD_KEYS) {
        const value = server.scalars[key];
        if (typeof value === "number" && Number.isFinite(value)) {
          target[key] = Math.min(1, Math.max(0, value));
        }
      }
      this.mood.tgt = target;
      this.mood.tau = 2; // explicit attack/release toward the real inner life
      this.mood.nextSwitch = now + 60_000;
    } else if (!this.mood.tgt || now >= this.mood.nextSwitch) this.pickMood(now);
    const dt = Math.min(0.5, (now - this.mood.lastT) / 1000);
    this.mood.lastT = now;
    // Published for the voice envelope: one frame delta, computed once, so the
    // two smoothers cannot disagree about how long the frame was.
    this.lastDt = dt;
    const k = 1 - Math.exp(-dt / this.mood.tau);
    const tgt = this.mood.tgt;
    if (!tgt) return;
    for (const key of MOOD_KEYS) this.mood.cur[key] += (tgt[key] - this.mood.cur[key]) * k;
  }

  private gestureTick(now: number): void {
    const g = this.gesture;
    if (g.id === 0) {
      g.amt = 0;
      if (now < g.nextAt) return;
      g.id = Math.random() < 0.1 ? 4 : GESTURES_COMMON[(Math.random() * GESTURES_COMMON.length) | 0];
      g.start = now;
    }
    const elapsed = now - g.start;
    if (elapsed >= g.ttl) {
      g.id = 0;
      g.amt = 0;
      g.nextAt = now + rand(30_000, 90_000);
      return;
    }
    const rise = 150;
    g.amt = elapsed < rise ? elapsed / rise : 1 - (elapsed - rise) / (g.ttl - rise);
  }

  /** The voice envelopes. See familiarDrive.ts for why they are asymmetric. */
  private readonly voiceEnv = new VoiceEnvelope();

  /** Seconds since the previous frame, published by the mood tick. Seeded to
   *  a nominal 60fps so the first frame smooths rather than dividing by zero. */
  private lastDt = 1 / 60;

  private apertureNow(_now: number): number {
    // Always fully open: there is no entrance to animate. This also removes the
    // timing dependence that made visual captures replay the aperture once per
    // throttled frame, which reduced motion used to dodge on its own.
    return 1;
  }

  private resizeCanvas(): void {
    const canvas = this.canvas;
    if (!canvas) return;
    const css = canvas.clientWidth || 1;
    const scale = Math.min(window.devicePixelRatio || 1, this.mode === "voice" ? 2 : 1.25);
    const size = Math.max(1, Math.round(css * scale));
    if (canvas.width !== size || canvas.height !== size) {
      canvas.width = size;
      canvas.height = size;
    }
  }

  private frame = (now: number): void => {
    if (this.statusValue.state !== "running") return;
    this.raf = requestAnimationFrame(this.frame);
    const gl = this.gl;
    const canvas = this.canvas;
    if (!gl || !canvas || document.hidden) return;

    // Reduced motion: a calm creature — one frame per second, inner life frozen.
    if (this.reducedMotion) {
      if (now - this.lastReducedFrame < 1000) return;
      this.lastReducedFrame = now;
    }

    this.resizeCanvas();
    const w = canvas.width;
    const h = canvas.height;
    gl.viewport(0, 0, w, h);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);

    const t = this.reducedMotion ? 0 : (now - this.startTime) / 1000;
    if (!this.reducedMotion) {
      this.moodTick(now);
      this.gestureTick(now);
    }

    const drive = familiarDrive(this.state, this.voiceEnv, this.lastDt, t);
    this.pushUniforms({ w, h, t, now, drive });

    gl.drawArrays(gl.TRIANGLES, 0, 3);
    if (!this.painted) {
      this.painted = true;
      this.onFirstPaint?.();
    }
  };

  /** Every uniform the shader reads, in one place.
   *
   * Separated from frame() because they are different jobs: frame decides
   * WHETHER and WHEN to draw -- reduced motion, a hidden tab, a lost context --
   * and this decides WHAT the shader is told. Reading a missing uniform's
   * location as null is deliberate throughout: a shader recompiled without one
   * should draw without it, not throw on the next frame. */
  private pushUniforms({ w, h, t, now, drive }: FrameShot): void {
    const gl = this.gl;
    if (!gl) return;
    const u = this.uniforms;
    const f = (name: UniformName, value: number) => gl.uniform1f(u[name] ?? null, value);
    f("iTime", t);
    gl.uniform2f(u.iResolution ?? null, w, h);
    gl.uniform2f(u.uWorldRes ?? null, w, h);
    f("uPxScale", 1);
    gl.uniform2f(u.uOrigin ?? null, 0, 0);

    // Companion recipe from boltrig-familiar-web: the orb renders through the
    // porthole path, with the aperture pinned open (see apertureNow).
    f("uFill", 1);
    f("uCompanion", 1);
    f("uPresence", 0);
    f("uAperture", this.apertureNow(now));
    gl.uniform2f(u.uCentreDock ?? null, 0, 0);
    // Compact modes keep the measured porthole recipe. Voice uses the full
    // portrait radius from the Call design; the larger fit boundary preserves
    // genotype corners and halo instead of cropping them back into a circle.
    const composition = familiarCompositionForMode(this.mode);
    f("uScaleDock", composition.scaleDock);
    f("uFitScale", composition.fitScale);

    gl.uniform2f(u.uMouse ?? null, 0.5, 0.5);
    f("uGaze", 0); // autonomous gaze; cursor tracking is a later, deliberate step
    f("uDay", dayWarmth());

    const m = this.mood.cur;
    f("uValence", m.valence);
    f("uArousal", Math.min(1, m.arousal + (this.state.working ? 0.25 : 0)));
    f("uIrritation", m.irritation);
    f("uFatigue", m.fatigue);
    f("uAttention", m.attention);
    f("uSocial", m.social);
    f("uBuoyancy", m.buoyancy);
    f("uLuminosity", m.luminosity);
    f("uTension", m.tension);

    f("uGesture", this.gesture.id);
    f("uGestureAmt", this.gesture.amt);
    gl.uniform4f(u.uAudio ?? null, drive.ax, drive.ay, drive.az, drive.aw);
    f("uBeat", drive.beat);
    f("uPortWide", 0);
    f("uHover", 0);
  }
}
