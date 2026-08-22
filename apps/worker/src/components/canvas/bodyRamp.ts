// The numbers that decide how a particle body LOOKS, in one place per body.
//
// WHY THEY LEFT THE PASS FILES. Every one of these was an inline literal inside
// a `setUniforms` call, and the tuning history says why that was expensive: the
// defect in both bodies was never a single value, it was the RATIO between three
// of them. Jarvis's circuit quads ran at three and a half times the filaments
// they ride on and Ultron's crack and facet passes at roughly six times the
// veins they crack, and neither is visible when the numbers are eighty lines
// apart in two files. Side by side, "which pass leads" is the thing you read
// first, because it is the thing that was wrong.
//
// THE SECOND REASON IS THE BENCH. tests/visual/shader-bench.html drives the real
// renderers with these values on sliders, so a change can be judged by eye at
// sixty frames a second instead of by a build and a static deploy. That only
// works if there is ONE struct to override -- a bench that reached into the
// passes would be a second copy of the numbers, which is the arrangement the
// shared GLSL chunks exist to avoid.
//
// EACH FIELD IS [base, perEnergy]. The rendered value is
// `base + perEnergy * energy`, where energy runs from about 0.22 at standby to
// 0.85 while speaking -- so the pair says both what the body looks like at rest
// and how much it answers to a voice. A single number would have to choose.

/** `base + perEnergy * energy`. */
export type EnergyRamp = readonly [base: number, perEnergy: number];

/** The silhouette: `x + y * limb(p)`, where limb is 1 at the rim, 0 face-on. */
export type LimbMix = readonly [base: number, rim: number];

// This file is the shared half of what was one 466-line bodyTuning.ts: the ramp
// vocabulary both bodies are written in, plus the two functions that evaluate
// it. Jarvis's numbers are in ./jarvisTuning.ts and Ultron's in
// ./ultronTuning.ts; bodyTuning.ts re-exports all of it, so no importer moved.

/**
 * The heart, OSCILLATING with the voice rather than merely scaled by it.
 *
 * `ramp` gives a core that rises while speaking and then sits there, which reads
 * as a lamp on a dimmer. The half that answers to energy is the half that should
 * MOVE, so it is modulated by the voice bands themselves -- the body pulses with
 * what is being said, rather than on a timer that happens to be running.
 *
 * The resting half is untouched. A silent body keeps exactly the heart its base
 * gives it; only the part a voice added is allowed to flicker.
 */
export function pulsedCore(core: EnergyRamp, energy: number, bands: Float32Array): number {
  // Weighted toward the LOW bands, which is where a voice's amplitude envelope
  // lives. Weighting the highs equally makes the heart chatter on sibilance,
  // which reads as a fault rather than as speech.
  const weights = [0.26, 0.22, 0.16, 0.12, 0.09, 0.07, 0.05, 0.03];
  let sum = 0;
  for (let i = 0; i < 8 && i < bands.length; i += 1) sum += bands[i] * weights[i];
  return core[0] + core[1] * energy * (0.45 + 0.85 * Math.min(1, sum));
}

/** `base + perEnergy * energy`, the one place the ramp is evaluated. */
export function ramp(value: EnergyRamp, energy: number): number {
  return value[0] + value[1] * energy;
}
