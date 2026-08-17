// Jarvis V2: the neural field. A GPU particle system, not a vector instrument.
//
// V1 (jarvis.frag) is a flat dial of rings and gauges. V2 answers the same
// question a completely different way, and the shape it answers with is not
// invented here. Two teams described the same object independently:
//
//   Matt Ebb, who designed and animated the JARVIS hologram at Animal Logic --
//   "an internal network of connections within the spherical centre", plus
//   "audio-reactive exterior rings of data that circumscribed the hologram,
//   evoking spinning hard drive platters and reel to reel data tape".
//
//   Territory Studio, who made the film's screen graphics -- a spherical base
//   with a central heart and rings rotating around it, with code and data
//   moving between the different ring layers.
//
// So: an interior network (LINK), exterior data rings (RING), a heart
// (COMPOSITE), and traffic between them (the migrating particles in
// components/canvas/glslCommon). An undifferentiated ball of filaments is NOT this design, and
// two rounds of colour tuning against one went nowhere -- worth recording,
// because when this reads wrong the tempting next move is always another
// colour tweak, and twice now that was the wrong move.
//
// PALETTE IS IDENTITY, NOT DECORATION. Animal Logic coded JARVIS orange with
// angular circuitry and ULTRON blue and organic; Territory colour-coded every
// character the same way. So this body is orange and V1 stays cyan, and if
// Ultron is ever built he is a different colour and a different silhouette --
// not a recolour of this file.
//
// WHY IT LIVES HERE AND NOT IN THE BUNDLE. jarvis-post.frag set the precedent:
// a character bundle carries the character's shader, byte-pinned by its
// manifest; Boltrig's rendering machinery stays in components/jarvis. V2 is
// machinery -- a simulation, five draw passes and a compositor -- so pinning it
// as character data would mean re-digesting six files every time a blur radius
// changes.
//
// THE MECHANISMS, and why each is there rather than something simpler:
//
//   CURL NOISE       velocity is curl(noise(p)), divergence-free by
//                    construction, so particles never bunch into blobs or drain
//                    into points. Plain noise gives fog; curl gives fibre.
//
//   STATELESS SPEED  velocity is not stored. It is recomputed from position
//                    every frame, so the simulation needs ONE ping-ponged
//                    texture instead of two, and every draw pass derives the
//                    same direction without reading a second texture.
//
//   LINE STREAKS     each particle is a GL_LINES pair -- head at p, tail at
//                    p - v*k. That is motion blur as geometry. Points would
//                    give a starfield.
//
//   AUDIO DRIVE      the rings answer to the eight voice bands, and an onset
//                    sends a wave travelling outward through the field. That is
//                    how Animal Logic drove theirs: "drive the effect's
//                    animation with audio signals and have segments react in
//                    accordance to the animation of surrounding geometry".
//
//   BLOOM            bright-pass then a separable Gaussian at half resolution.
//                    Additive lines alone are thin and mean.

import {
  RESTING_PHENOTYPE,
  jarvisEmotion,
  readBodyPhenotype,
  emotionColour,
  tint,
  type BodyPhenotype,
} from "../../canvas/bodyEmotion";
import { JARVIS_TUNING, type JarvisTuning } from "../../canvas/bodyTuning";
import {
  INTRO_SECONDS,
  applyPulses,
  easeFactor,
  easeTuning,
} from "../../canvas/bodyModes";
import {
  JARVIS_ARRIVAL,
  JARVIS_PULSES,
  jarvisModeTuning,
} from "../../canvas/bodyPresets";
import type { JarvisStageState } from "../JarvisState";
import type { FloatUniforms } from "../../canvas/glResources";
import { NeuralPasses, type Drive } from "./neuralPasses";

/** Eight zeroes, reused rather than reallocated every frame. */
const SILENT_BANDS = new Float32Array(8);

export interface NeuralRendererOptions {
  /** Base warm colour. Defaults to the JARVIS orange. */
  warm?: [number, number, number];
  /** Hot core colour. */
  hot?: [number, number, number];
  /** The fringe band's colour -- see FRINGE_GLSL in glslCommon.ts. */
  fringe?: [number, number, number];
  maxDevicePixelRatio?: number;
}

type Status = { state: "idle" | "running" | "failed"; reason?: string };

export class JarvisNeuralRenderer {
  private host: HTMLElement | null = null;
  private canvas: HTMLCanvasElement | null = null;
  private gl: WebGL2RenderingContext | null = null;
  private passes: NeuralPasses | null = null;
  private raf = 0;
  private lastFrameAt = 0;
  /** Animation seconds, summed from CLAMPED frame deltas.
   *
   * NOT wall clock. A background tab stops delivering frames, so a wall-clock
   * `t` advances by the whole hidden duration and the field lurches on return
   * -- the same defect FamiliarWebGLRenderer and JarvisRenderer both carried.
   * Summing the deltas actually drawn means hiding the tab pauses the animation
   * and showing it resumes, which is what a viewer expects. */
  private animClock = 0;
  private suspended = false;
  private reducedMotion = false;
  private size: [number, number] = [0, 0];
  private state: JarvisStageState | null = null;
  private pheno: BodyPhenotype = RESTING_PHENOTYPE;
  /** Seconds since the last speech onset, for the travelling wave. */
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
  private live: JarvisTuning = JARVIS_ARRIVAL;
  /** A bench override. Null means follow the mode, which is the shipped path. */
  private tuning: JarvisTuning | null = null;

  constructor(private readonly opts: NeuralRendererOptions = {}) {}

  status(): Status { return this._status; }

  /**
   * Replace the look, for tests/visual/shader-bench.html.
   *
   * Public for the same reason `frame` is: judging this body needs it driven
   * from outside the rAF loop, and the alternative was a bench that rebuilt the
   * pass sequence and drifted from it. Nothing in the product calls this, and
   * the field defaults to what ships.
   */
  setTuning(next: JarvisTuning): void {
    // SNAPPED, not eased. A slider that took half a second to arrive would make
    // the bench feel broken, and worse, the panel and the picture would disagree
    // for as long as the ease lasted.
    this.tuning = next;
    this.live = next;
  }

  /** What it is currently drawing with, so a bench can seed its own controls. */
  currentTuning(): JarvisTuning { return this.tuning ?? JARVIS_TUNING; }

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
    this.live = JARVIS_ARRIVAL;
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
    this.live = JARVIS_ARRIVAL;
    this.introLeft = INTRO_SECONDS;
  }


  mount(host: HTMLElement): void {
    this.host = host;
    const canvas = document.createElement("canvas");
    canvas.className = "jarvis-neural-canvas";
    host.appendChild(canvas);
    this.canvas = canvas;

    const gl = canvas.getContext("webgl2", {
      alpha: true, antialias: false, premultipliedAlpha: false,
    }) as WebGL2RenderingContext | null;
    if (!gl) { this.fail("webgl2 unavailable"); return; }
    this.gl = gl;

    // RGBA32F render targets are the whole simulation. Without the float
    // extension the positions quantise and the cloud collapses into bands, so
    // this is a hard requirement rather than a quality tier.
    if (!gl.getExtension("EXT_color_buffer_float")) {
      this.fail("EXT_color_buffer_float unavailable");
      return;
    }

    try {
      this.passes = new NeuralPasses(gl);
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

  update(state: JarvisStageState): void {
    // An onset RESTARTS the travelling wave rather than adding to it: two
    // syllables close together should send two waves, not one twice as strong.
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
   * The machine's measured mood, as V1 reads it. A body that ignored the
   * phenotype while V1 displays it would make the skin choice a change of
   * subject rather than a change of clothes.
   */
  applyPhenotype(pheno: Record<string, unknown> | null): void {
    // ALL TEN, not the three this used to keep. See canvas/bodyEmotion: seven
    // scalars were arriving and being dropped while the bundle claimed he read
    // them, so a machine that was exhausted or unfocused showed neither.
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
    // NO LENS FLARE ON A HOLOGRAM, AND A WARM HEART. Three things stacked at the
    // centre: the field converges there, the composite adds two gaussians on top
    // of it, and the starburst laid a hot bar fifteen times wider than it was
    // tall straight across the middle. That bar is what read as a white block
    // shining through the iris. It is off here -- it belongs to Colossus, whose
    // CRT beam earns a horizontal streak -- and the lobes now sit at the warm
    // end, so the heart stays bright without leaving the orange.
    // The mood is applied to a COPY per frame rather than stored, so `tuning`
    // stays exactly what the bench set and what Copy settings would print. A
    // phenotype folded into the stored value would slowly rewrite the look
    // being tuned, which is the one thing a bench must not do.
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
      const target = this.tuning ?? jarvisModeTuning(mode);
      this.live = easeTuning(this.live, target, easeFactor(this.easeDt));
      shown = this.live;
    } else if (this.tuning) {
      shown = this.tuning;
    } else {
      const target = jarvisModeTuning(mode);
      // Reduced motion gets the destination and none of the journey: the entry
      // animation and the pulses are both motion, and neither is information.
      this.live = this.reducedMotion
        ? target
        : easeTuning(this.live, target, easeFactor(this.easeDt));
      shown = this.reducedMotion
        ? this.live
        : applyPulses(this.live, JARVIS_PULSES[mode], this.animClock);
    }
    passes.render(d, this.palette(), jarvisEmotion(shown, this.pheno));
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

  /** What the frame is driven by, derived once and shared by every pass. */
  private drive(nowMs: number): Drive {
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
    // The wave decays rather than being switched off, so the last syllable of a
    // sentence finishes crossing the body.
    this.waveAmp *= Math.exp(-dt * 2.2);

    const mode = this.state?.mode ?? "standby";
    const level = Math.min(1, Math.max(0, this.state?.level ?? 0));
    // Energy is what the whole look keys off: standby drifts, speaking boils.
    const base = mode === "speaking" ? 0.85 : mode === "working" ? 0.6
      : mode === "thinking" ? 0.45 : mode === "listening" ? 0.35 : 0.22;
    const energy = Math.min(1, base + level * 0.35 + this.pheno.arousal * 0.15);

    return {
      time: this.animClock,
      dt,
      energy,
      bands: this.bands,
      waveT: this.waveT,
      waveAmp: this.waveAmp,
      // Tension tightens the whole field toward its centre.
      radius: 1.0 - this.pheno.tension * 0.14,
      // Speaking breathes even between onsets. A body that only moved on a hard
      // consonant reads as flinching rather than talking.
      swell: mode === "speaking" ? Math.max(0.25, level) : 0,
    };
  }

  /**
   * Colour, after the phenotype has had its say. Irritation drags the orange
   * toward red -- the same move V1 makes, and one non-orange frame says more
   * than any amount of extra brightness.
   */
  private palette(): FloatUniforms {
    const warm = this.opts.warm ?? [1.0, 0.38, 0.04];
    const hot = this.opts.hot ?? [1.0, 0.74, 0.32];
    const fringe = this.opts.fringe ?? [0.42, 0.09, 0.02];
    // The WHOLE register, not just irritation. Nine of the ten scalars used to
    // reach colour not at all, so a mood could only ever make him brighter.
    const c = emotionColour(this.pheno);
    return {
      uWarm: tint(warm, c.warm, c.desaturate),
      uHot: tint(hot, c.hot, c.desaturate),
      uFringe: tint(fringe, c.fringe, c.desaturate),
      // The fringe band. See FRINGE_GLSL: outer = inner / scale, and everything
      // below outer draws nothing at all.
      uInner: 0.52,
      uFringeScale: 2.4,
      uFringeGain: 1.15,
    };
  }

  private loop = (): void => {
    this.raf = requestAnimationFrame(this.loop);
    // A hidden tab stops delivering frames. Keeping the delta origin current
    // means the first frame back is a normal frame rather than one carrying the
    // whole hidden duration -- without this the field visibly catches up.
    if (this.suspended || (typeof document !== "undefined" && document.hidden)) {
      this.lastFrameAt = performance.now();
      return;
    }
    this.frame(performance.now());
  };
}
