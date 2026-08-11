// The instrument's host-side maths, extracted so it has exactly one definition
// and can be tested without a GPU.
//
// This existed twice: once in JarvisRenderer and once, hand-copied, in the
// preview harness used to tune the look. Two implementations of the smoothing
// and the sweep means tuning against a copy that has quietly drifted from the
// thing that ships — the worst kind of drift, because every frame still looks
// plausible.

/** Exponential approach to a target. Frame-rate independent by construction. */
export function approach(current: number, target: number, dt: number, tau: number): number {
  if (tau <= 0) return target;
  return current + (target - current) * (1 - Math.exp(-dt / tau));
}

/**
 * Rotation rate in the units the ring speeds expect. Arousal drives the dial;
 * fatigue drags on it. Never multiply this by absolute time — integrate it (see
 * `advanceSpin`), because the rate itself moves with the mood and `t * rate`
 * would jump or rewind every ring whenever it changed.
 */
export function spinRate(arousal: number, fatigue: number): number {
  return (0.55 + 1.35 * clamp01(arousal)) * (1 - 0.45 * clamp01(fatigue));
}

export function advanceSpin(spin: number, dt: number, arousal: number, fatigue: number): number {
  return spin + dt * spinRate(arousal, fatigue);
}

export function clamp01(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.min(1, Math.max(0, value))
    : 0;
}

/** Samples in the listening ring buffer. Must match `uWave` (vec4[32]). */
export const WAVE_SAMPLES = 128;

/** Seconds for the listening sweep to travel once around the dial. */
export const REVOLUTION_SECONDS = 6;

export interface SweepStep {
  head: number;
  /** True when the head passed 12 o'clock this step and the buffer was wiped. */
  wrapped: boolean;
}

/** Shortest revolution — a brief "yes" still draws a readable arc. */
export const SWEEP_MIN_SECONDS = 6;
/** Longest revolution, so a long sentence does not lose its own opening. */
export const SWEEP_MAX_SECONDS = 20;

/**
 * How long one revolution should take, given how long this listening spell has
 * already run. A fixed period meant a long utterance wrapped and erased its own
 * beginning mid-sentence; the sweep now stretches as you keep talking, so one
 * revolution stays "this utterance" rather than "the last six seconds".
 */
export function sweepPeriod(spellSeconds: number): number {
  const t = Math.min(1, Math.max(0, spellSeconds / SWEEP_MAX_SECONDS));
  return SWEEP_MIN_SECONDS + (SWEEP_MAX_SECONDS - SWEEP_MIN_SECONDS) * t;
}

/**
 * Advances the listening sweep by `dt` and writes `level` into every slot the
 * head crossed.
 *
 * The head is INTEGRATED, not computed as `t % period`, for the same reason the
 * rotation phase is: the period now changes with utterance length, and deriving
 * the head from absolute time would jump it backwards the moment the period
 * stretched — erasing part of the trace mid-sweep.
 *
 * Writing only the slot under the head would leave a comb of gaps on a slow
 * frame; filling the crossed span keeps the trace continuous at any frame rate.
 * Passing 12 o'clock wipes the buffer, which is what makes the trace vanish and
 * start again rather than overwrite itself in place.
 */
export function stepSweep(
  wave: Float32Array,
  prevHead: number,
  dt: number,
  level: number,
  period = SWEEP_MIN_SECONDS,
): SweepStep {
  const advanced = prevHead + dt / Math.max(period, 0.001);
  const wrapped = advanced >= 1;
  const head = wrapped ? advanced % 1 : advanced;
  if (wrapped) wave.fill(0);

  const from = Math.floor((wrapped ? 0 : prevHead) * WAVE_SAMPLES);
  const to = Math.min(WAVE_SAMPLES - 1, Math.floor(head * WAVE_SAMPLES));
  const value = clamp01(level);
  for (let i = from; i <= to; i++) wave[i] = value;

  return { head, wrapped };
}
