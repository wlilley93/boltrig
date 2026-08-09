// The universal Stage renderer (ADR 0025): the production Familiar shader on a
// WebGL2 canvas. Host logic is ported from boltrig-familiar-web's main.js — the
// companion/aperture uniform recipe, wandering mood baseline, ambient gesture
// envelope and reduced-motion behaviour are kept, so the creature here is the
// same being as the proven web port. The shader itself is vendored verbatim
// (familiar.frag); visual changes flow from boltrig-familiar, never start here.
import fragSrc from "./familiar.frag?raw";
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

const UNIFORMS = [
  "iTime", "iResolution", "uAudio", "uBeat", "uMouse", "uDay",
  "uValence", "uArousal", "uIrritation", "uFatigue", "uAttention",
  "uSocial", "uBuoyancy", "uLuminosity", "uTension", "uGesture",
  "uGestureAmt", "uPresence", "uCentreDock", "uScaleDock", "uFitScale",
  "uGaze", "uWorldRes", "uOrigin", "uPxScale", "uFill", "uPortWide",
  "uHover", "uCompanion", "uAperture",
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
  private aperture = { value: 0, from: 0, to: 1, start: 0, dur: 1400 };

  constructor(options?: { reducedMotion?: boolean }) {
    this.reducedMotion = options?.reducedMotion
      ?? (typeof window !== "undefined"
        && typeof window.matchMedia === "function"
        && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
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
    if (this.reducedMotion) this.aperture.value = 1; // no entrance animation
    this.statusValue = { kind: "webgl2", state: "running" };
    this.raf = requestAnimationFrame(this.frame);
  }

  update(next: Partial<FamiliarStageState>): void {
    this.state = clampStageState(next);
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

  private apertureNow(now: number): number {
    const a = this.aperture;
    const t = Math.min(1, (now - a.start) / a.dur);
    const e = t * t * (3 - 2 * t);
    a.value = a.from + (a.to - a.from) * e;
    return a.value;
  }

  private resizeCanvas(): void {
    const canvas = this.canvas;
    if (!canvas) return;
    const css = canvas.clientWidth || 1;
    const scale = Math.min(window.devicePixelRatio || 1, 1.25);
    const size = Math.max(1, Math.round(css * scale));
    if (canvas.width !== size || canvas.height !== size) {
      canvas.width = size;
      canvas.height = size;
    }
  }

  /** 0..1 warmth from local time, peaking mid-afternoon. */
  private dayWarmth(): number {
    const d = new Date();
    const h = d.getHours() + d.getMinutes() / 60;
    return 0.15 + 0.85 * Math.max(0, Math.sin(((h - 9) / 12) * Math.PI));
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

    const t = (now - this.startTime) / 1000;
    if (!this.reducedMotion) {
      this.moodTick(now);
      this.gestureTick(now);
    }

    // Drive from Worker state: a working turn pulses the body; speaking
    // articulates it harder, scaled by the reported level. This is the seam
    // FamiliarState v2 (8-band voice features) will replace.
    let ax = 0;
    let ay = 0;
    const { working, speaking, level } = this.state;
    if (speaking) {
      const amp = 0.35 + 0.55 * (level || 0.5);
      ax = amp * (0.75 + 0.25 * Math.sin(t * 3.1));
      ay = amp * (0.6 + 0.4 * Math.sin(t * 2.2 + 1.3));
    } else if (working) {
      ax = 0.45 + 0.15 * Math.sin(t * 3.1);
      ay = 0.4 + 0.2 * Math.sin(t * 2.2 + 1.3);
    }

    const u = this.uniforms;
    const f = (name: UniformName, value: number) => gl.uniform1f(u[name] ?? null, value);
    f("iTime", t);
    gl.uniform2f(u.iResolution ?? null, w, h);
    gl.uniform2f(u.uWorldRes ?? null, w, h);
    f("uPxScale", 1);
    gl.uniform2f(u.uOrigin ?? null, 0, 0);

    // Companion recipe from boltrig-familiar-web: the orb renders through the
    // porthole path, born out of its black-hole aperture.
    f("uFill", 1);
    f("uCompanion", 1);
    f("uPresence", 0);
    f("uAperture", this.apertureNow(now));
    gl.uniform2f(u.uCentreDock ?? null, 0, 0);
    f("uScaleDock", 0.4);
    f("uFitScale", 0.5);

    gl.uniform2f(u.uMouse ?? null, 0.5, 0.5);
    f("uGaze", 0); // autonomous gaze; cursor tracking is a later, deliberate step
    f("uDay", this.dayWarmth());

    const m = this.mood.cur;
    f("uValence", m.valence);
    f("uArousal", Math.min(1, m.arousal + (working ? 0.25 : 0)));
    f("uIrritation", m.irritation);
    f("uFatigue", m.fatigue);
    f("uAttention", m.attention);
    f("uSocial", m.social);
    f("uBuoyancy", m.buoyancy);
    f("uLuminosity", m.luminosity);
    f("uTension", m.tension);

    f("uGesture", this.gesture.id);
    f("uGestureAmt", this.gesture.amt);
    gl.uniform4f(u.uAudio ?? null, ax, ay, 0, 0);
    f("uBeat", 0);
    f("uPortWide", 0);
    f("uHover", 0);

    gl.drawArrays(gl.TRIANGLES, 0, 3);
  };
}
