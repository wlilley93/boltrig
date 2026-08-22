// The inner life: the wandering mood baseline, and the ambient gestures.
//
// SPLIT OUT ON THE SAME SEAM AS familiarDrive. The renderer owns WebGL — the
// context, the uniform locations, the frame loop. None of this touches any of
// that: it is a state machine over numbers, and it is the half that a person
// tuning the being by eye actually changes. Keeping it here also bought the
// renderer the room to grow a tuning seam without crossing its ratchet.
//
// WHY THERE IS A WANDER AT ALL. A body whose scalars are CONSTANT between
// events is a diagram. The desktop's emotion relay is the authoritative source
// when it is fresh (decision 0013, downstream-only), but it is absent most of
// the time, and an absent relay must look like a calm creature rather than a
// frozen one — so the baseline drifts on its own and stands down the moment a
// real reading arrives.

import type { FamiliarTuning } from "../canvas/familiarTuning";

export const MOOD_KEYS = [
  "valence", "arousal", "attention", "social", "buoyancy", "luminosity", "tension",
  "irritation", "fatigue",
] as const;

export type MoodKey = (typeof MOOD_KEYS)[number];
export type Mood = Record<MoodKey, number>;

const rand = (a: number, b: number) => a + Math.random() * (b - a);
const clamp01 = (v: number) => Math.min(1, Math.max(0, v));

/** The resting creature: awake, mildly attentive, untroubled. */
export const RESTING_MOOD: Mood = {
  valence: 0.5, arousal: 0.07, attention: 0.6, social: 0.5,
  buoyancy: 0.5, luminosity: 0.5, tension: 0, irritation: 0, fatigue: 0,
};

/**
 * How long a fresh server phenotype OWNS the mood, in milliseconds.
 *
 * After this it is stale and the wander resumes. Ten seconds is long enough
 * that a relay polling every few seconds never lets go, and short enough that a
 * relay which died does not leave the being wearing its last expression.
 */
const PHENOTYPE_FRESH_MS = 10_000;

/** Attack toward a real reading, in seconds. Faster than the wander's own tau:
 *  a measured mood is news, and the being should visibly receive it. */
const PHENOTYPE_TAU = 2;

/** The four moods it wanders between, as ranges rather than points so that no
 *  two visits to the same mood look identical. */
type Wander = Omit<Mood, "irritation" | "fatigue">;

function rollMood(): Wander {
  const roll = Math.random();
  if (roll < 0.25) {
    return { arousal: rand(0.5, 0.75), valence: rand(0.55, 0.9), attention: rand(0.75, 1),
      social: rand(0.65, 0.95), buoyancy: rand(0.6, 0.9), luminosity: rand(0.7, 1),
      tension: rand(0.05, 0.25) };
  }
  if (roll < 0.55) {
    return { arousal: rand(0.3, 0.55), valence: rand(0.6, 0.85), attention: rand(0.7, 0.95),
      social: rand(0.6, 0.9), buoyancy: rand(0.55, 0.85), luminosity: rand(0.6, 0.9),
      tension: rand(0.1, 0.3) };
  }
  if (roll < 0.8) {
    return { arousal: rand(0.05, 0.18), valence: rand(0.45, 0.6), attention: rand(0.3, 0.55),
      social: rand(0.35, 0.6), buoyancy: rand(0.45, 0.65), luminosity: rand(0.4, 0.6),
      tension: rand(0, 0.1) };
  }
  return { arousal: rand(0.3, 0.55), valence: rand(0.35, 0.55), attention: rand(0.6, 0.85),
    social: rand(0.4, 0.7), buoyancy: rand(0.4, 0.6), luminosity: rand(0.45, 0.65),
    tension: rand(0.3, 0.6) };
}

/** The nine scalars, eased toward whichever target currently owns them. */
export class FamiliarMood {
  readonly cur: Mood = { ...RESTING_MOOD };

  private tgt: Mood | null = null;
  private tau = 6;
  private lastT = 0;
  private nextSwitch = 0;
  private server: { at: number; scalars: Partial<Record<MoodKey, number>> } | null = null;

  /** Start the clock. Without this the first frame's delta is the whole
   *  lifetime of the page and the being snaps to its first target. */
  seed(now: number): void {
    this.lastT = now;
    this.nextSwitch = 0;
  }

  /**
   * A live reading from the server projection. While fresh it OWNS the target
   * and the wander stands down; null, or ten seconds of silence, hands control
   * back — so an absent relay is a calm being, never a broken one.
   */
  applyPhenotype(scalars: Partial<Record<MoodKey, number>> | null, now: number): void {
    this.server = scalars ? { at: now, scalars } : null;
  }

  /** Advance one frame. Returns the frame delta in seconds, capped, so the
   *  voice envelopes smooth against exactly the same dt this used. */
  tick(now: number, tuning: FamiliarTuning): number {
    const fresh = this.server && now - this.server.at < PHENOTYPE_FRESH_MS
      ? this.server
      : null;
    if (fresh) this.takeServerTarget(fresh.scalars, now);
    else if (!this.tgt || now >= this.nextSwitch) this.wanderTo(now, tuning);

    const dt = Math.min(0.5, (now - this.lastT) / 1000);
    this.lastT = now;
    const tgt = this.tgt;
    if (!tgt) return dt;
    const k = 1 - Math.exp(-dt / Math.max(0.05, this.tau));
    for (const key of MOOD_KEYS) this.cur[key] += (tgt[key] - this.cur[key]) * k;
    return dt;
  }

  /**
   * Lay a mode's colouring over the current mood, without disturbing the
   * wander underneath it.
   *
   * Applied to a COPY on the way to the uniforms rather than written into
   * `cur`, because an overlay written back would be eased toward on the next
   * frame and then eased toward again — a state that compounds every frame and
   * saturates. The error tone in particular has to be able to lift clean off.
   */
  withOverlay(overlay: Partial<Mood>): Mood {
    const out = { ...this.cur };
    for (const key of MOOD_KEYS) {
      const value = overlay[key];
      if (typeof value === "number" && Number.isFinite(value)) out[key] = clamp01(value);
    }
    return out;
  }

  private takeServerTarget(scalars: Partial<Record<MoodKey, number>>, now: number): void {
    const target: Mood = { ...(this.tgt ?? this.cur) };
    for (const key of MOOD_KEYS) {
      const value = scalars[key];
      if (typeof value === "number" && Number.isFinite(value)) target[key] = clamp01(value);
    }
    this.tgt = target;
    this.tau = PHENOTYPE_TAU;
    this.nextSwitch = now + 60_000;
  }

  private wanderTo(now: number, tuning: FamiliarTuning): void {
    this.tgt = { ...rollMood(), irritation: 0, fatigue: 0 };
    const [tau, dwell] = tuning.wander;
    // Both are tunable but still jittered around the dial: four identical
    // dwells in a row read as a cycle, which is the thing a wander exists to
    // avoid. +/-25% is enough to break the pattern without making the dial lie.
    this.tau = rand(tau * 0.75, tau * 1.25);
    this.nextSwitch = now + rand(dwell * 0.75, dwell * 1.25) * 1000;
  }
}

/**
 * The gesture ids the shader's enum uses. Positional, and they must stay in
 * step with FamiliarGesture in the web SDK — the shader reads an int.
 */
export const GESTURE = {
  none: 0, look: 1, pulse: 2, flinch: 3, celebrate: 4,
  greet: 5, nod: 6, recoil: 7, preen: 8,
} as const;

/** Mostly subtle. Celebrate is drawn separately and rarely. */
const AMBIENT = [GESTURE.look, GESTURE.nod, GESTURE.preen, GESTURE.pulse];

/** How long a gesture runs, and how long its attack is, in milliseconds. */
const GESTURE_TTL = 2000;
const GESTURE_RISE = 150;

/**
 * Voluntary movement: the occasional look, nod or preen that makes the being
 * read as something with its own business rather than as a reactive surface.
 *
 * `fire` is the deliberate half of the same mechanism. A gesture the host
 * chooses — the recoil on a failure — must use the same envelope as an ambient
 * one, or the two would be two implementations of "a gesture" and the second
 * one would be the one that is wrong.
 */
export class AmbientGesture {
  id = 0;
  amt = 0;

  private start = 0;
  private ttl = GESTURE_TTL;
  private nextAt = 0;

  seed(now: number, tuning: FamiliarTuning): void {
    this.nextAt = now + this.gap(tuning);
  }

  /** Play one now, interrupting whatever was running. */
  fire(id: number, now: number, ttl = GESTURE_TTL): void {
    this.id = id;
    this.start = now;
    this.ttl = ttl;
    this.amt = 0;
  }

  tick(now: number, tuning: FamiliarTuning): void {
    if (this.id === GESTURE.none) {
      this.amt = 0;
      if (now < this.nextAt) return;
      this.fire(
        Math.random() < 0.1
          ? GESTURE.celebrate
          : AMBIENT[(Math.random() * AMBIENT.length) | 0],
        now,
      );
    }
    const elapsed = now - this.start;
    if (elapsed >= this.ttl) {
      this.id = GESTURE.none;
      this.amt = 0;
      this.nextAt = now + this.gap(tuning);
      return;
    }
    this.amt = elapsed < GESTURE_RISE
      ? elapsed / GESTURE_RISE
      : 1 - (elapsed - GESTURE_RISE) / (this.ttl - GESTURE_RISE);
  }

  private gap(tuning: FamiliarTuning): number {
    const [min, max] = tuning.gesture;
    return rand(Math.min(min, max), Math.max(min, max)) * 1000;
  }
}
