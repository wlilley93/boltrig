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
import { UltronPasses } from "./ultronPasses";
import { BodyClock } from "../canvas/bodyClock";
import { ULTRON_ONSET, ultronDrive, ultronPalette } from "./ultronDrive";
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
  TRANSITION_SECONDS,
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
  private latticeSource: string | Partial<Record<string, string>> | null = null;
  private raf = 0;
  /** The frame clock and the speech ring, shared with JarvisNeuralRenderer. */
  private readonly clock = new BodyClock();
  private suspended = false;
  reducedMotion = false;
  private size: [number, number] = [0, 0];
  state: UltronStageState | null = null;
  pheno: BodyPhenotype = RESTING_PHENOTYPE;
  readonly bands = new Float32Array(8);
  private _status: Status = { state: "idle" };
  /**
   * What is being DRAWN, which is not the same as what the mode asks for.
   *
   * It starts at the ARRIVAL tuning and eases toward the current mode's target,
   * so the body draws itself in on first load and then travels between modes by
   * the same arithmetic. Two behaviours, one mechanism, one place to be wrong.
   */
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

  /** Mount (or clear) the baked membrane loops. See canvas/latticeLayer.ts. */
  setLatticeVideo(source: string | Partial<Record<string, string>> | null): void {
    this.latticeSource = source;
    this.passes?.latticeDeck()?.setSource(source);
  }

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

  /** Ease to a new look without replaying the arrival. See the Jarvis twin. */
  transitionTo(next: UltronTuning, seconds = TRANSITION_SECONDS): void {
    this.tuning = next;
    this.introLeft = Math.max(this.introLeft, seconds);
  }


  mount(host: HTMLElement): void {
    this.host = host;
    const canvas = document.createElement("canvas");
    canvas.className = "ultron-canvas";
    host.appendChild(canvas);
    this.canvas = canvas;

    const gl = canvas.getContext("webgl2", {
      // premultipliedAlpha TRUE, matching familiar's renderer, because the
      // composite now premultiplies. Left false with a premultiplied buffer the
      // browser would multiply a second time and the body would go dark.
      alpha: true, antialias: false, premultipliedAlpha: true,
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
      this.passes.latticeDeck()?.setSource(this.latticeSource);
    } catch (err) {
      this.fail(String(err));
      return;
    }

    this.reducedMotion = typeof matchMedia === "function"
      && matchMedia("(prefers-reduced-motion: reduce)").matches;

    this.resize();
    this._status = { state: "running" };
    this.clock.markIdle();
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
    this.clock.onset(
      typeof state.onset === "number" ? state.onset : 0, ULTRON_ONSET,
    );
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
    this.clock.markIdle();
  }

  /** Render one frame. Public so a still can be taken without a rAF loop. */
  frame(nowMs: number): void {
    const passes = this.passes;
    if (!passes || !this.canvas) return;
    this.resize();
    const d = ultronDrive(this.clock, nowMs, this);
    // The mode is the target and `live` chases it; the pulses then ride on top.
    // An explicit bench override replaces the target outright, which is why
    // dragging a slider is instant.
    const mode = this.state?.mode ?? "standby";
    let shown = this.live;
    if (this.introLeft > 0 && !this.reducedMotion) {
      // THE DRAW-IN, and it outranks a pinned tuning for as long as it lasts. The
      // destination is the pin when there is one, so a bench with a saved look
      // animates to that look rather than to the shipped preset.
      this.introLeft = Math.max(0, this.introLeft - this.clock.easeDt);
      const target = this.tuning ?? ultronModeTuning(mode);
      this.live = easeTuning(this.live, target, easeFactor(this.clock.easeDt));
      shown = this.live;
    } else if (this.tuning) {
      shown = this.tuning;
      // KEEP `live` ON WHAT IS ACTUALLY DRAWN while pinned. Otherwise it holds
      // whatever it was when the last ease finished, and the next transition starts
      // from that stale value rather than from the look on screen -- so a change of
      // mode would jump backwards before travelling forwards.
      this.live = this.tuning;
    } else {
      const target = ultronModeTuning(mode);
      // Reduced motion gets the destination and none of the journey: the entry
      // animation and the pulses are both motion, and neither is information.
      this.live = this.reducedMotion
        ? target
        : easeTuning(this.live, target, easeFactor(this.clock.easeDt));
      shown = this.reducedMotion
        ? this.live
        : applyPulses(this.live, ULTRON_PULSES[mode], this.clock.animClock);
    }
    passes.latticeDeck()?.tick(this.state?.mode ?? "standby", this.clock.easeDt);
    passes.render(d, ultronPalette(this.opts, this.pheno), ultronEmotion(shown, this.pheno));
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



  private loop = (): void => {
    this.raf = requestAnimationFrame(this.loop);
    if (this.suspended || (typeof document !== "undefined" && document.hidden)) {
      this.clock.markIdle();
      return;
    }
    this.frame(performance.now());
  };
}
