// Ultron's per-frame inputs: what the passes are handed, and in what colour.
//
// The same shape as jarvis/v2/jarvisDrive.ts and for the same reason -- pure
// arithmetic over state the renderer already holds, moved out of a class that
// was over the worker's 400-line floor with no debt entry the gate would accept.
// What differs between the two bodies is exactly what stayed behind in each: the
// energy floors, the onset caps, and the colour.

import { emotionColour, tint, type BodyPhenotype } from "../canvas/bodyEmotion";
import { BodyClock, type OnsetShape } from "../canvas/bodyClock";
import type { FloatUniforms } from "../canvas/glResources";
import type { UltronStageState } from "./UltronState";
import type { UltronDrive } from "./ultronPasses";
import type { UltronRendererOptions } from "./UltronRenderer";

/** Uncapped against Jarvis's 0.72: his ring is meant to be able to saturate. */
export const ULTRON_ONSET: OnsetShape = { first: 1, top: 1, gain: 0.6 };

/** What the passes are handed this frame. Advances `clock` as a side effect. */
export function ultronDrive(
  clock: BodyClock,
  nowMs: number,
  body: {
    reducedMotion: boolean;
    state: UltronStageState | null;
    pheno: BodyPhenotype;
    bands: Float32Array;
  },
): UltronDrive {
  const dt = clock.advance(nowMs, body.reducedMotion);

  const mode = body.state?.mode ?? "standby";
  const level = Math.min(1, Math.max(0, body.state?.level ?? 0));
  // A HIGHER FLOOR THAN JARVIS. Standby for an instrument is idling; standby
  // for Ultron is waiting, and waiting is not the same as resting.
  const base = mode === "speaking" ? 0.92 : mode === "working" ? 0.72
    : mode === "thinking" ? 0.58 : mode === "listening" ? 0.46 : 0.34;
  const energy = Math.min(1, base + level * 0.35 + body.pheno.arousal * 0.15);
  const aggression = Math.min(1,
    0.25 + level * 0.3 + body.pheno.irritation * 0.5 + body.pheno.tension * 0.25);

  return {
    time: clock.animClock,
    dt,
    energy,
    aggression,
    bands: body.bands,
    // Speaking is when the voice should move him. Idle drift stays idle drift
    // -- a body that pulsed to silence would be pulsing to nothing.
    voice: mode === "speaking" ? Math.max(0.35, level) : level * 0.35,
    waveT: clock.waveT,
    waveAmp: clock.waveAmp,
    radius: 1.0 - body.pheno.tension * 0.10,
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
export function ultronPalette(
  opts: UltronRendererOptions, pheno: BodyPhenotype,
): FloatUniforms {
  const warm = opts.warm ?? [0.02, 0.26, 0.98];
  const hot = opts.hot ?? [0.30, 0.86, 1.0];
  const fringe = opts.fringe ?? [0.03, 0.08, 0.34];
  // The WHOLE register. His colour answered to irritation alone, the same gap
  // Jarvis had -- nine scalars that could only make him brighter or dimmer.
  const c = emotionColour(pheno);
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
