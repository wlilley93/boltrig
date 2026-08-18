// Jarvis's per-frame inputs: what the passes are handed, and in what colour.
//
// Pure arithmetic over state the renderer already holds -- no canvas, no GL, no
// requestAnimationFrame -- so it sits out here where it can be read and tested on
// its own, and JarvisNeuralRenderer is left owning a surface. It left because
// the renderer was 481 lines against the worker's 400-line floor, which cannot
// be pinned instead: the structure gate refuses a new debt entry.

import { emotionColour, tint, type BodyPhenotype } from "../../canvas/bodyEmotion";
import { BodyClock, type OnsetShape } from "../../canvas/bodyClock";
import type { FloatUniforms } from "../../canvas/glResources";
import type { JarvisStageState } from "../JarvisState";
import type { Drive } from "./neuralPasses";
import type { NeuralRendererOptions } from "./JarvisNeuralRenderer";

/** Capped below full: a fast run of syllables kept topping the ring to 1 and
 *  holding it there, which is the heave rather than the ring. */
export const JARVIS_ONSET: OnsetShape = { first: 0.85, top: 0.72, gain: 0.4 };

/** What the passes are handed this frame. Advances `clock` as a side effect. */
export function jarvisDrive(
  clock: BodyClock,
  nowMs: number,
  body: {
    reducedMotion: boolean;
    state: JarvisStageState | null;
    pheno: BodyPhenotype;
    bands: Float32Array;
  },
): Drive {
  const dt = clock.advance(nowMs, body.reducedMotion);

  const mode = body.state?.mode ?? "standby";
  const level = Math.min(1, Math.max(0, body.state?.level ?? 0));
  // Energy is what the whole look keys off: standby drifts, speaking boils.
  const base = mode === "speaking" ? 0.85 : mode === "working" ? 0.6
    : mode === "thinking" ? 0.45 : mode === "listening" ? 0.35 : 0.22;
  const energy = Math.min(1, base + level * 0.35 + body.pheno.arousal * 0.15);

  return {
    time: clock.animClock,
    dt,
    energy,
    bands: body.bands,
    waveT: clock.waveT,
    waveAmp: clock.waveAmp,
    // Tension tightens the whole field toward its centre.
    radius: 1.0 - body.pheno.tension * 0.14,
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
export function jarvisPalette(
  opts: NeuralRendererOptions, pheno: BodyPhenotype,
): FloatUniforms {
  const warm = opts.warm ?? [1.0, 0.38, 0.04];
  const hot = opts.hot ?? [1.0, 0.74, 0.32];
  const fringe = opts.fringe ?? [0.42, 0.09, 0.02];
  // The WHOLE register, not just irritation. Nine of the ten scalars used to
  // reach colour not at all, so a mood could only ever make him brighter.
  const c = emotionColour(pheno);
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
