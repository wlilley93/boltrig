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
import {
  RESTING_PHENOTYPE,
  readBodyPhenotype,
  ultronEmotion,
  emotionColour,
  tint,
  type BodyPhenotype,
} from "../canvas/bodyEmotion";
import { ULTRON_TUNING, type UltronTuning } from "../canvas/bodyTuning";
import {
  INTRO_SECONDS,
  applyPulses,
  easeFactor,
  easeTuning,
} from "../canvas/bodyModes";
import {
  ULTRON_ARRIVAL,
  ULTRON_PULSES,
  ultronModeTuning,
} from "../canvas/bodyPresets";
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
  private pheno: BodyPhenotype = RESTING_PHENOTYPE;
  private waveT = 10;
  private waveAmp = 0;
  private bands = new Float32Array(8);
  private _status: Status = { state: "idle" };
  /**
   * What is being DRAWN, which is not the same as what the mode asks for.
   *
   * It starts at the ARRIVAL tuning and eases toward the current mode's target,
   * so the body draws itself in on first load and then travels between modes by
   * the same arithmetic. Two behaviours, one mechanism, one place to be wrong.
   */
  /** Unclamped wall-clock seconds since the last frame, for the tuning ease. */
  private easeDt = 0;
  /**
   * Seconds of draw-in still to run.
   *
   * A COUNTDOWN rather than a flag, because "has it arrived yet" has no clean answer
   * when the target is a struct of twenty fields -- comparing them all for
   * near-equality is both slow and arbitrary about what near means. A duration says
   * exactly when the animation is over, and it is over at the same moment on every
   * machine, which a convergence test is not.
   */
  private introLeft = 0;
  private live: UltronTuning = ULTRON_ARRIVAL;
  /** A bench override. Null means follow the mode, which is the shipped path. */
  private tuning: UltronTuning | null = null;

  constructor(private readonly opts: UltronRendererOptions = {}) {}

  status(): Status { return this._status; }

  /** Replace the look, for tests/visual/shader-bench.html. See Jarvis's note. */
  setTuning(next: UltronTuning): void {
    // SNAPPED, not eased. A slider that took half a second to arrive would make
    // the bench feel broken, and worse, the panel and the picture would disagree
    // for as long as the ease lasted.
    this.tuning = next;
    this.live = next;
  }

  /** What it is currently drawing with, so a bench can seed its own controls. */
  currentTuning(): UltronTuning { return this.tuning ?? ULTRON_TUNING; }

  /**
   * Hand the body back to its own mode logic and draw it in again.
   *
   * The bench pins the tuning so a dragged slider is instant, and that pin also
   * defeats the entry ease -- so the draw-in was the one animation that could not
   * be watched in the place built for watching animations. This releases the pin
   * and puts the body back at its arrival state, which is exactly what happens on
   * a fresh mount.
   */
  replay(): void {
    this.tuning = null;
    this.live = ULTRON_ARRIVAL;
    this.introLeft = INTRO_SECONDS;
  }

  /**
   * Draw in from the arrival state WITHOUT giving up the current tuning.
   *
   * replay() hands the body back to its mode logic, which is right for watching what
   * a mode does. This is for the other case: a bench that has a look loaded -- maybe
   * a saved one -- and wants the entry animation to end on THAT rather than on the
   * shipped preset. Easing to the wrong destination and then jumping to the right one
   * when the first slider moved is the failure this avoids.
   */
  intro(): void {
    this.live = ULTRON_ARRIVAL;
    this.introLeft = INTRO_SECONDS;
  }


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
    // ALL TEN. Aggression is still where irritation and tension land -- that
    // part of the note above holds -- but seven other scalars were arriving and
    // being dropped while his bundle claimed he read them. See canvas/bodyEmotion.
    this.pheno = readBodyPhenotype(pheno);
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
    // The mode is the target and `live` chases it; the pulses then ride on top.
    // An explicit bench override replaces the target outright, which is why
    // dragging a slider is instant.
    const mode = this.state?.mode ?? "standby";
    let shown = this.live;
    if (this.introLeft > 0 && !this.reducedMotion) {
      // THE DRAW-IN, and it outranks a pinned tuning for as long as it lasts. The
      // destination is the pin when there is one, so a bench with a saved look
      // animates to that look rather than to the shipped preset.
      this.introLeft = Math.max(0, this.introLeft - this.easeDt);
      const target = this.tuning ?? ultronModeTuning(mode);
      this.live = easeTuning(this.live, target, easeFactor(this.easeDt));
      shown = this.live;
    } else if (this.tuning) {
      shown = this.tuning;
    } else {
      const target = ultronModeTuning(mode);
      // Reduced motion gets the destination and none of the journey: the entry
      // animation and the pulses are both motion, and neither is information.
      this.live = this.reducedMotion
        ? target
        : easeTuning(this.live, target, easeFactor(this.easeDt));
      shown = this.reducedMotion
        ? this.live
        : applyPulses(this.live, ULTRON_PULSES[mode], this.animClock);
    }
    passes.render(d, this.palette(), ultronEmotion(shown, this.pheno));
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
    // TWO dt's, and conflating them made the ease frame-rate-dependent again.
    //
    // The simulation's dt is clamped to 50ms because a longer step makes the
    // particle integrator overshoot and the field explodes -- on a slow frame the
    // right move is to advance the physics LESS than real time. The tuning ease
    // wants the opposite: it is a wall-clock animation, and clamping its dt on a
    // machine managing 7fps stretched a 1.6s ease into about 5s. Measured on
    // swiftshader, where the draw-in had not finished after eight seconds.
    const wall = Math.max(0.001, (nowMs - this.lastFrameAt) / 1000);
    const dt = Math.min(0.05, wall);
    this.easeDt = wall;
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
    // The WHOLE register. His colour answered to irritation alone, the same gap
    // Jarvis had -- nine scalars that could only make him brighter or dimmer.
    const c = emotionColour(this.pheno);
    const irr = this.pheno.irritation;
    void irr;
    return {
      // His channels are reversed against Jarvis's -- irritation eats the BLUE end
      // of a blue body, where it eats the blue end of an orange one too. Same
      // register, applied to a palette that starts somewhere else.
      uWarm: tint(warm, [c.warm[2], c.warm[1], c.warm[0]], c.desaturate),
      uHot: tint(hot, [c.hot[2], c.hot[1], c.hot[0]], c.desaturate),
      uFringe: tint(fringe, [c.fringe[2], c.fringe[1], c.fringe[0]], c.desaturate),
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
