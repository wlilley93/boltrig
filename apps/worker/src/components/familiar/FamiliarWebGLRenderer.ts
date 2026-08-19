// The universal Stage renderer (ADR 0025): the production Familiar shader on a
// WebGL2 canvas. Host logic is ported from boltrig-familiar-web's main.js — the
// companion/aperture uniform recipe, wandering mood baseline, ambient gesture
// envelope and reduced-motion behaviour are kept, so the creature here is the
// same being as the proven web port. The shader itself is vendored verbatim
// (familiar.frag); visual changes flow from boltrig-familiar, never start here.
//
// WHICH IS WHY THE TUNING SEAM IS HERE AND NOT IN GLSL. Everything a person
// wants to change about how she MOVES — how a voice becomes drive, how fast the
// inner life wanders, what a mode does to her — is decided on this side of the
// uniform push. Gathering those into canvas/familiarTuning and accepting a
// setTuning override is what lets tests/visual/shader-bench.html drive this
// renderer itself, on sliders, without a single line of the vendored shader
// moving. A bench that rebuilt the recipe would drift from it, and then it
// would be tuning something nobody ships.
import fragSrc from "../../bundles/familiar/familiar.frag?raw";
import type { FamiliarGenotype } from "@wlilley93/boltrig-web-sdk";
import { easeFactor, easeTuning, TRANSITION_SECONDS, INTRO_SECONDS } from "../canvas/bodyModes";
import { createProgram } from "../canvas/glResources";
import { FAMILIAR_TUNING, type FamiliarTuning } from "../canvas/familiarTuning";
import { FAMILIAR_ARRIVAL, familiarModeTuning } from "../canvas/familiarPresets";
import { packFamiliarGenotype } from "./FamiliarGenotype";
import { BeatImpulse, VoiceEnvelope, familiarDrive } from "./familiarDrive";
import { AmbientGesture, FamiliarMood, GESTURE, type Mood, type MoodKey } from "./familiarMood";
import {
  pushFamiliarUniforms,
  UNIFORMS,
  type UniformMap,
} from "./familiarUniforms";
import {
  clampStageState,
  RESTING_STAGE_STATE,
  type FamiliarMode,
  type FamiliarPresentationMode,
  type FamiliarRendererStatus,
  type FamiliarStageState,
} from "./FamiliarState";

const VERT_SRC = `#version 300 es
void main() {
  vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
  gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}`;

/** Re-exported so every existing importer -- characters.ts's manifest check and
 *  the bundle tests -- is untouched by the uniform push moving to its own file. */
export { UNIFORMS, familiarCompositionForMode } from "./familiarUniforms";

export class FamiliarWebGLRenderer {
  readonly kind = "webgl2" as const;

  private canvas: HTMLCanvasElement | null = null;
  private gl: WebGL2RenderingContext | null = null;
  private uniforms: UniformMap = {};
  private raf = 0;
  private statusValue: FamiliarRendererStatus = { kind: "webgl2", state: "mounted" };
  private startTime = 0;
  private lastReducedFrame = -Infinity;
  private readonly reducedMotion: boolean;
  private readonly onFirstPaint?: () => void;
  private painted = false;
  private mode: FamiliarPresentationMode = "hero";

  private state: FamiliarStageState = RESTING_STAGE_STATE;
  /** What the last frame was told, so a CHANGE of mode can be an event. */
  private lastMode: FamiliarMode = "standby";

  /** Inner life: the resting baseline wanders so the being is alive between
   *  events. See familiarMood.ts. */
  private readonly mood = new FamiliarMood();
  private readonly gesture = new AmbientGesture();

  /** The voice smoothers, kept as one bag so they are handed to the drive
   *  together and keep their history across frames. See familiarDrive.ts for
   *  why the two are shaped differently. */
  private readonly smoothers = { env: new VoiceEnvelope(), beat: new BeatImpulse() };

  /** What is actually being drawn with; it chases the mode's target. */
  private live: FamiliarTuning = FAMILIAR_TUNING;
  /** A bench override. Null means follow the mode, which is the shipped path. */
  private pinned: FamiliarTuning | null = null;
  private introLeft = 0;

  private packedGenotype = packFamiliarGenotype(null);

  /** Seconds since the previous frame, published by the mood tick. Seeded to
   *  a nominal 60fps so the first frame smooths rather than dividing by zero. */
  private lastDt = 1 / 60;

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
      this.link(gl);
    } catch (error) {
      // Per the design brief: never rewrite the look to survive a failure —
      // report it and let the Stage fall back to the badge.
      this.fail(error instanceof Error ? error.message : String(error));
      return;
    }

    this.startTime = performance.now();
    const now = this.startTime;
    this.mood.seed(now);
    this.gesture.seed(now, this.tuningNow());
    this.statusValue = { kind: "webgl2", state: "running" };
    this.raf = requestAnimationFrame(this.loop);
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
    this.mood.applyPhenotype(scalars, performance.now());
  }

  setMode(mode: FamiliarPresentationMode): void {
    this.mode = mode;
    if (mode === "minimised") this.suspend();
    else this.resume();
  }

  /** Replace the look, for tests/visual/shader-bench.html. Snapped, not eased:
   *  a slider that took half a second to arrive would leave the panel and the
   *  picture disagreeing for as long as the ease lasted. */
  setTuning(next: FamiliarTuning): void {
    this.pinned = next;
    this.live = next;
  }

  /** What it is currently drawing with, so a bench can seed its own controls. */
  currentTuning(): FamiliarTuning {
    return this.pinned ?? this.live;
  }

  /** Hand the body back to its own mode logic and settle it in again. */
  replay(): void {
    this.pinned = null;
    this.live = FAMILIAR_ARRIVAL;
    this.introLeft = INTRO_SECONDS;
  }

  /** Settle in from the arrival state WITHOUT giving up the current tuning, so
   *  a bench holding a saved look animates to THAT rather than to the shipped
   *  preset and then jumping when the first slider moves. */
  intro(): void {
    this.live = FAMILIAR_ARRIVAL;
    this.introLeft = INTRO_SECONDS;
  }

  /** Ease to a new look without replaying the arrival. */
  transitionTo(next: FamiliarTuning, seconds = TRANSITION_SECONDS): void {
    this.pinned = next;
    this.introLeft = Math.max(this.introLeft, seconds);
  }

  suspend(): void {
    if (this.statusValue.state !== "running") return;
    cancelAnimationFrame(this.raf);
    this.statusValue = { kind: "webgl2", state: "suspended" };
  }

  resume(): void {
    if (this.statusValue.state !== "suspended") return;
    this.statusValue = { kind: "webgl2", state: "running" };
    this.raf = requestAnimationFrame(this.loop);
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

  /**
   * Render one frame. Public so a still can be taken, and so the shader bench
   * can step the body itself: readPixels in a later task reads a drawing buffer
   * the compositor has already cleared, so the draw and the read have to happen
   * in one task and the loop cannot be ours.
   */
  frame(now: number): void {
    const gl = this.gl;
    const canvas = this.canvas;
    if (!gl || !canvas) return;

    this.resizeCanvas();
    const w = canvas.width;
    const h = canvas.height;
    gl.viewport(0, 0, w, h);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);

    const t = this.reducedMotion ? 0 : (now - this.startTime) / 1000;
    const tuning = this.tick(now);
    const drive = familiarDrive(this.state, this.smoothers, this.lastDt, t, tuning);
    pushFamiliarUniforms(gl, this.uniforms, {
      w, h, t, drive, tuning,
      mood: this.shownMood(tuning),
      mode: this.state.mode,
      presentation: this.mode,
      gesture: { id: this.gesture.id, amt: this.gesture.amt },
    });

    gl.drawArrays(gl.TRIANGLES, 0, 3);
    if (!this.painted) {
      this.painted = true;
      this.onFirstPaint?.();
    }
  }

  // ------------------------------------------------------------------ internals

  /**
   * Advance the inner life and settle the tuning, returning what to draw with.
   *
   * The mode is the target and `live` chases it; an explicit bench override
   * replaces the target outright, which is why dragging a slider is instant.
   */
  private tick(now: number): FamiliarTuning {
    if (this.reducedMotion) return this.tuningNow();

    this.lastDt = this.mood.tick(now, this.tuningNow());
    this.gesture.tick(now, this.tuningNow());
    // A CHANGE INTO error IS AN EVENT. The held pose that follows is the
    // consequence; arriving at it with no movement reads as a rendering bug
    // rather than as something having gone wrong.
    if (this.state.mode !== this.lastMode) {
      if (this.state.mode === "error") this.gesture.fire(GESTURE.recoil, now, 1400);
      this.lastMode = this.state.mode;
    }

    const target = this.pinned ?? familiarModeTuning(this.state.mode);
    if (this.introLeft > 0) {
      this.introLeft = Math.max(0, this.introLeft - this.lastDt);
      this.live = easeTuning(this.live, target, easeFactor(this.lastDt));
    } else if (this.pinned) {
      // KEEP `live` ON WHAT IS DRAWN while pinned, or the next transition starts
      // from a stale value and the body jumps backwards before travelling.
      this.live = this.pinned;
    } else {
      this.live = easeTuning(this.live, target, easeFactor(this.lastDt));
    }
    return this.live;
  }

  private tuningNow(): FamiliarTuning {
    return this.pinned ?? this.live;
  }

  /** The wander, with the current mode's colouring laid over it. */
  private shownMood(tuning: FamiliarTuning): Mood {
    if (this.state.mode !== "error") return this.mood.cur;
    const [tension, luminosity] = tuning.errorTone;
    return this.mood.withOverlay({ tension, luminosity });
  }

  private loop = (now: number): void => {
    if (this.statusValue.state !== "running") return;
    this.raf = requestAnimationFrame(this.loop);
    if (!this.gl || !this.canvas || document.hidden) return;

    // Reduced motion: a calm creature — one frame per second, inner life frozen.
    if (this.reducedMotion) {
      if (now - this.lastReducedFrame < 1000) return;
      this.lastReducedFrame = now;
    }
    this.frame(now);
  };

  private fail(reason: string): void {
    this.canvas?.remove();
    this.canvas = null;
    this.gl = null;
    this.statusValue = { kind: "webgl2", state: "failed", reason };
  }

  private link(gl: WebGL2RenderingContext): void {
    // The tree's own program builder rather than a private copy: a second
    // compile/link path is a second place for a shader error to be reported
    // differently, and this one already throws with the info log attached.
    const prog = createProgram(gl, VERT_SRC, fragSrc);
    gl.useProgram(prog);
    for (const name of UNIFORMS) this.uniforms[name] = gl.getUniformLocation(prog, name);

    // GENOTYPE. The shader's 32 positional slots are packed from the
    // authoritative capability identity. Missing identity stays the exact
    // neutral defaults, including multiplier defaults in reserved slots.
    gl.uniform4fv(this.uniforms.uGene ?? null, this.packedGenotype);
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
}
