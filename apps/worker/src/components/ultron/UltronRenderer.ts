// Ultron: a fracturing membrane in blue.
//
// WHO HE IS, and why he is not a recolour of Jarvis's neural field. Animal Logic
// built both consciousnesses for the Birth of Ultron sequence and coded them as
// opposites: JARVIS an orange aura of angular shapes mimicking computer
// circuitry, ULTRON a blue aura, organically designed, reading as the more
// advanced intelligence. Matt Ebb, who designed and animated them, described
// aiming for Ultron to look "alive, constantly evolving and organic" against
// Jarvis's geometry.
//
// So the gold hologram in components/jarvis/v2 is JARVIS'S look in that film,
// not Ultron's -- which is why its skin is called "Age of Ultron" and why this
// is a separate character rather than a third skin on him. He shares the
// substrate in components/canvas and nothing else: no data rings, no circuit
// shards, no orange.
//
// AGGRESSION IS INSTABILITY, NOT BRIGHTNESS. `aggression` drives how far the
// cracks kink off their chords, how often one arcs, and how far the shards lift
// off the surface. Turning the gain up instead would have produced a louder
// Jarvis; what reads as menace is a surface that will not hold together.

import { type FloatUniforms } from "../canvas/glResources";
import { UltronPasses, type UltronDrive } from "./ultronPasses";
import { ULTRON_TUNING, type UltronTuning } from "../canvas/bodyTuning";
import type { UltronStageState } from "./UltronState";

const SILENT_BANDS = new Float32Array(8);

export interface UltronRendererOptions {
  /** Deep blue base. */
  warm?: [number, number, number];
  /** Cyan-white hot end. */
  hot?: [number, number, number];
  /** The fringe band's colour -- see FRINGE_GLSL in components/canvas. */
  fringe?: [number, number, number];
  maxDevicePixelRatio?: number;
}

type Status = { state: "idle" | "running" | "failed"; reason?: string };

export class UltronRenderer {
  private host: HTMLElement | null = null;
  private canvas: HTMLCanvasElement | null = null;
  private gl: WebGL2RenderingContext | null = null;
  private passes: UltronPasses | null = null;
  private raf = 0;
  private lastFrameAt = 0;
  /** Animation seconds, summed from CLAMPED frame deltas -- never wall clock.
   *
   * A background tab stops delivering frames, so a wall-clock time advances by
   * the whole hidden duration in one frame and the field lurches on return. All
   * three of the other renderers carried this bug; it is not being written a
   * fourth time. */
  private animClock = 0;
  private suspended = false;
  private reducedMotion = false;
  private size: [number, number] = [0, 0];
  private state: UltronStageState | null = null;
  private pheno = { irritation: 0, arousal: 0, tension: 0 };
  private waveT = 10;
  private waveAmp = 0;
  private bands = new Float32Array(8);
  private _status: Status = { state: "idle" };
  private tuning: UltronTuning = ULTRON_TUNING;

  constructor(private readonly opts: UltronRendererOptions = {}) {}

  status(): Status { return this._status; }

  /** Replace the look, for tests/visual/shader-bench.html. See Jarvis's note. */
  setTuning(next: UltronTuning): void { this.tuning = next; }

  /** What it is currently drawing with, so a bench can seed its own controls. */
  currentTuning(): UltronTuning { return this.tuning; }

  mount(host: HTMLElement): void {
    this.host = host;
    const canvas = document.createElement("canvas");
    canvas.className = "ultron-canvas";
    host.appendChild(canvas);
    this.canvas = canvas;

    const gl = canvas.getContext("webgl2", {
      alpha: true, antialias: false, premultipliedAlpha: false,
    }) as WebGL2RenderingContext | null;
    if (!gl) { this.fail("webgl2 unavailable"); return; }
    this.gl = gl;

    // The float extension is the whole simulation, not a quality tier: without
    // it positions quantise and the membrane collapses into visible shells.
    if (!gl.getExtension("EXT_color_buffer_float")) {
      this.fail("EXT_color_buffer_float unavailable");
      return;
    }

    try {
      this.passes = new UltronPasses(gl);
      this.passes.init();
    } catch (err) {
      this.fail(String(err));
      return;
    }

    this.reducedMotion = typeof matchMedia === "function"
      && matchMedia("(prefers-reduced-motion: reduce)").matches;

    this.resize();
    this._status = { state: "running" };
    this.lastFrameAt = performance.now();
    this.loop();
  }

  destroy(): void {
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    this.passes?.destroy();
    this.passes = null;
    this.canvas?.remove();
    this.canvas = null;
    this.gl = null;
    this.host = null;
  }

  update(state: UltronStageState): void {
    const onset = typeof state.onset === "number" ? state.onset : 0;
    if (onset > 0.35 && this.waveT > 0.18) {
      this.waveT = 0;
      this.waveAmp = Math.min(1, onset);
    }
    const bands = state.bands;
    if (bands && bands.length === 8) {
      for (let i = 0; i < 8; i++) this.bands[i] = Math.min(1, Math.max(0, bands[i]));
    } else {
      this.bands.set(SILENT_BANDS);
    }
    this.state = state;
  }

  /**
   * The machine's measured mood. Ultron reads it like the others, but it lands
   * on AGGRESSION rather than on colour: irritation and tension make the
   * membrane come apart faster, which is what he does with a bad mood.
   */
  applyPhenotype(pheno: Record<string, unknown> | null): void {
    const read = (key: string): number => {
      const v = pheno?.[key];
      return typeof v === "number" && Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : 0;
    };
    this.pheno = {
      irritation: read("irritation"),
      arousal: read("arousal"),
      tension: read("tension"),
    };
  }

  suspend(): void { this.suspended = true; }
  resume(): void {
    if (!this.suspended) return;
    this.suspended = false;
    this.lastFrameAt = performance.now();
  }

  /** Render one frame. Public so a still can be taken without a rAF loop. */
  frame(nowMs: number): void {
    const passes = this.passes;
    if (!passes || !this.canvas) return;
    this.resize();
    const d = this.drive(nowMs);
    passes.render(d, this.palette(), this.tuning);
  }

  // ------------------------------------------------------------------ internals

  private fail(reason: string): void {
    this._status = { state: "failed", reason };
    this.canvas?.remove();
    this.canvas = null;
    this.gl = null;
  }

  private resize(): void {
    const canvas = this.canvas;
    const host = this.host;
    if (!canvas || !host || !this.passes) return;
    const dpr = Math.min(window.devicePixelRatio || 1, this.opts.maxDevicePixelRatio ?? 1.5);
    const w = Math.max(1, Math.round(host.clientWidth * dpr));
    const h = Math.max(1, Math.round(host.clientHeight * dpr));
    if (w === this.size[0] && h === this.size[1]) return;
    this.size = [w, h];
    canvas.width = w;
    canvas.height = h;
    this.passes.resize(w, h);
  }

  private drive(nowMs: number): UltronDrive {
    const dt = Math.min(0.05, Math.max(0.001, (nowMs - this.lastFrameAt) / 1000));
    this.lastFrameAt = nowMs;
    if (!this.reducedMotion) this.animClock += dt;

    this.waveT += dt;
    this.waveAmp *= Math.exp(-dt * 2.2);

    const mode = this.state?.mode ?? "standby";
    const level = Math.min(1, Math.max(0, this.state?.level ?? 0));
    // A HIGHER FLOOR THAN JARVIS. Standby for an instrument is idling; standby
    // for Ultron is waiting, and waiting is not the same as resting.
    const base = mode === "speaking" ? 0.92 : mode === "working" ? 0.72
      : mode === "thinking" ? 0.58 : mode === "listening" ? 0.46 : 0.34;
    const energy = Math.min(1, base + level * 0.35 + this.pheno.arousal * 0.15);
    const aggression = Math.min(1,
      0.25 + level * 0.3 + this.pheno.irritation * 0.5 + this.pheno.tension * 0.25);

    return {
      time: this.animClock,
      dt,
      energy,
      aggression,
      bands: this.bands,
      // Speaking is when the voice should move him. Idle drift stays idle drift
      // -- a body that pulsed to silence would be pulsing to nothing.
      voice: mode === "speaking" ? Math.max(0.35, level) : level * 0.35,
      waveT: this.waveT,
      waveAmp: this.waveAmp,
      radius: 1.0 - this.pheno.tension * 0.10,
      // Speaking breathes between onsets; a body that only moved on a hard
      // consonant reads as flinching rather than talking.
      swell: mode === "speaking" ? Math.max(0.25, level) : 0,
    };
  }

  /**
   * Blue, and it stays blue. The palette is the character's identity here, not
   * a theme: the whole reason he is a separate body from Jarvis's gold one is
   * that the two were deliberately coded as opposites. Irritation pushes him
   * COLDER and harder rather than toward red, because red is the other one.
   */
  private palette(): FloatUniforms {
    const warm = this.opts.warm ?? [0.02, 0.26, 0.98];
    const hot = this.opts.hot ?? [0.30, 0.86, 1.0];
    const fringe = this.opts.fringe ?? [0.03, 0.08, 0.34];
    const irr = this.pheno.irritation;
    return {
      uWarm: [warm[0] * (1 - irr * 0.6), warm[1] * (1 - irr * 0.35), warm[2]],
      uHot: [hot[0] * (1 - irr * 0.4), hot[1] * (1 - irr * 0.12), hot[2]],
      uFringe: fringe,
      uInner: 0.50,
      uFringeScale: 2.2,
      uFringeGain: 1.2,
    };
  }

  private loop = (): void => {
    this.raf = requestAnimationFrame(this.loop);
    if (this.suspended || (typeof document !== "undefined" && document.hidden)) {
      this.lastFrameAt = performance.now();
      return;
    }
    this.frame(performance.now());
  };
}
