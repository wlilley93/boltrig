import type { FamiliarTuning, JarvisTuning, UltronTuning } from "./bodyTuning";

/** The five presentation states every animated body is driven through. */
export type BodyMode = "standby" | "listening" | "thinking" | "working" | "speaking";

export const BODY_MODES: readonly BodyMode[] = [
  "standby", "listening", "thinking", "working", "speaking",
];

/** Any body's numbers. The machinery here is deliberately shape-agnostic --
 *  which is what let the Familiar join without a line of it changing, even
 *  though her fields describe a uniform recipe rather than draw passes. */
export type AnyTuning = FamiliarTuning | JarvisTuning | UltronTuning;

/**
 * One field oscillating gently around whatever the mode set it to.
 *
 * A body whose numbers are CONSTANT between mode changes is a diagram. The brief
 * was that many things move at once, none of them far -- which is what makes a
 * thing read as alive rather than as a rendering of a thing. So each mode carries
 * a handful of these and they run continuously.
 *
 * `depth` is a FRACTION of the value, not an absolute. Absolute depths have to be
 * retuned every time a base changes, and the one that gets forgotten is the one
 * that ends up swinging a 0.02 value by 0.3.
 */
export interface Pulse {
  /** Field name on the tuning struct. */
  field: string;
  /** Which component of a pair/triple. 0 for a plain number. */
  index: number;
  /** Swing as a fraction of the base, so 0.08 is +/- 8%. */
  depth: number;
  /** Hz. These are slow: 0.05 is a twenty-second cycle. */
  rate: number;
  /**
   * Phase offset in turns. DELIBERATELY IRREGULAR across a mode's pulses -- if
   * they share a phase they crest together and the whole body throbs as one
   * object, which is the opposite of the intended read.
   */
  phase: number;
}

/**
 * Ease every field of a tuning toward another.
 *
 * ONE EASE FOR BOTH JOBS. Drawing a body in from its arrival state and changing
 * its mode are the same operation -- a target moved, and the body has to get
 * there -- so there is one mechanism and one place for it to be wrong. A separate
 * entry animation would be a second implementation of this that runs once, which
 * is the copy nobody notices has broken.
 *
 * Counts and strides SNAP instead of easing: 3.7 rings is not a state between
 * three and four, it is a draw call for three and a bit.
 */
export function easeTuning<T extends AnyTuning>(from: T, to: T, k: number): T {
  const out = { ...from } as Record<string, unknown>;
  for (const [key, target] of Object.entries(to as unknown as Record<string, unknown>)) {
    const current = (from as unknown as Record<string, unknown>)[key];
    if (typeof target === "number" && typeof current === "number") {
      out[key] = SNAP.has(key) ? target : current + (target - current) * k;
    } else if (Array.isArray(target) && Array.isArray(current)) {
      out[key] = (target as number[]).map((value, i) => {
        const was = (current as number[])[i] ?? value;
        return was + (value - was) * k;
      });
    } else {
      out[key] = target;
    }
  }
  return out as T;
}

/** Fields where an intermediate value is nonsense rather than a halfway state. */
const SNAP = new Set(["rings", "shardStride"]);

/**
 * Ride a mode's pulses on top of the eased tuning.
 *
 * Applied AFTER the ease, never folded into it. Folding them in would make the
 * ease chase a moving target and it would never arrive -- the body would appear
 * to settle and then keep drifting, which is a bug that looks like a feature for
 * about a week.
 */
export function applyPulses<T extends AnyTuning>(
  tuning: T, pulses: readonly Pulse[], seconds: number,
): T {
  if (pulses.length === 0) return tuning;
  const out = { ...tuning } as Record<string, unknown>;
  for (const pulse of pulses) {
    const current = out[pulse.field];
    const wave = Math.sin(2 * Math.PI * (seconds * pulse.rate + pulse.phase));
    const scale = 1 + pulse.depth * wave;
    if (typeof current === "number") {
      out[pulse.field] = current * scale;
    } else if (Array.isArray(current)) {
      const next = (current as number[]).slice();
      const at = next[pulse.index];
      if (typeof at === "number") next[pulse.index] = at * scale;
      out[pulse.field] = next;
    }
  }
  return out as T;
}

/** A mode's target: the settled look with that mode's deltas laid over it. */
export function modeTuning<T extends AnyTuning>(
  base: T, modes: Record<BodyMode, Partial<T>>, mode: BodyMode,
): T {
  return { ...base, ...modes[mode] };
}

/**
 * How fast a body travels to a new target, as a time constant in seconds.
 *
 * Time-constant easing rather than a fixed per-frame step, so the arrival takes
 * the same wall-clock time on a machine managing 12fps as on one managing 120.
 * A fixed step ties the animation's speed to the frame rate, which is how an
 * entry animation ends up instant on the developer's machine and glacial on a
 * laptop with a browser full of tabs.
 *
 * THERE ARE TWO TIMESCALES HERE AND ONLY ONE OF THEM IS THIS NUMBER. The tuning
 * eases in the time constant below; the PARTICLES then have to physically travel
 * to the homes the new tuning gives them, and that is the simulation's own spring,
 * measured at several seconds when the arrival state parks the whole population at
 * 2.2x radius. At 0.55s the numbers arrived almost immediately and the field spent
 * the next four seconds visibly catching up -- which read as a snap followed by a
 * drift rather than as a body drawing itself in. Slowing the numbers to roughly
 * the field's own settling time is what makes the two look like one movement.
 */
export const EASE_SECONDS = 1.6;

/**
 * How long a draw-in runs for.
 *
 * Comfortably longer than EASE_SECONDS, because the tuning arriving is only half of
 * it: the PARTICLES then travel to the homes the new numbers give them under the
 * simulation's own spring, and from the arrival state that means crossing from 2.2x
 * radius. Ending the animation when the numbers land would cut it off mid-gather.
 */
export const INTRO_SECONDS = 4.5;

/**
 * How long a change of MODE takes, as distinct from an arrival.
 *
 * Much shorter than the intro: arriving is an event and changing mode is a
 * response, so a mode change that took four and a half seconds would still be
 * finishing by the time the state it was heading for had passed.
 */
export const TRANSITION_SECONDS = 1.5;

/** The per-frame blend factor for a time-constant ease. */
export function easeFactor(dt: number): number {
  return 1 - Math.exp(-Math.max(0, dt) / EASE_SECONDS);
}
