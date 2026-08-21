import {
  JARVIS_TUNING, type JarvisTuning,
} from "./bodyTuning";
import { modeTuning, type BodyMode, type Pulse } from "./bodyModes";

/**
 * WHERE JARVIS ARRIVES FROM, and it is a place rather than a fade.
 *
 * A body that fades up from nothing tells you only that it is loading. The
 * reference does not do that: the hologram arrives as one wide bright hoop far
 * out with everything on the shell, and then draws IN, gathering into the thing
 * it is going to be. So this is a complete tuning like any other and the entry is
 * simply the ease from here to whatever mode he is in.
 *
 * Note the shell fraction falls from 2.2 to 0 on the way in. That is the draw:
 * the whole population starts out at twice the radius and migrates to the core.
 */
export const JARVIS_ARRIVAL: JarvisTuning = {
  outerShell: [2.2, 2.2, 2.2],
  ringGain: [0.86, 0.525],
  ringSpin: [0.174, 0.012],
  ringRadius: [2, 2],
  ringBeam: 0.27,
  ringLife: 0,
  ringArc: [1, 1],
  ringWidth: 0.11,
  // The iris opens as he draws in, so the eye is the last thing to arrive.
  irisGain: [0, 0],
  irisRadius: [0.1, 0.44],
  irisFil: [0.78, 0.006],
  irisFlow: [0.14, 0.65],
  glyphGain: [0, 0],
  glyphRadius: [0.62, 0.80],
  glyphSize: [0.055, 0.008],
  glyphSpin: [0.026, 0.55],
  glyphDensity: [0.72, 0.55],
  glyphBGain: [0, 0],
  glyphBRadius: [0.98, 1.16],
  glyphBSize: [0.055, 0.008],
  glyphBSpin: [0.026, 0.55],
  glyphBDensity: [0.72, 0.55],
  rings: 1,
  swirl: [0.105, 0],
  linkGain: [0, 0],
  // Still on arrival: the draw-in is the animation, and a wavefront crossing it
  // would compete with the gather.
  reverb: [0.9, 0.4, 1.2, 1.35],
  linkBow: [0.158, 0.2],
  linkRange: 0.6,
  drawGain: [1, 1],
  streak: [0.004, 0],
  shardGain: [1, 0.475],
  shardSize: 0.003,
  shardStride: 12,
  core: [1, 1],
  // ARRIVING, the shell is the whole body: outerShell population is 2.2, so every
  // particle is out there and the outer layer is what you see.
  outerGain: [1.1, 0.5],
  outerStreak: [0.004, 0],
  outerLimb: [3, 3],
  outerPace: 0,
  starburst: 0.32,
  eye: [0.35, 1.8, 0.62, 9],
  drawLimb: [3, 3],
  linkLimb: [3, 3],
  clump: [0, 2.6],
  focus: [0, 0],
  lattice: [0, 0],
  latticeBlur: 0,
  latticeSat: 1,
  latticeGlow: 0,
  latticeSpeed: 1,
  presence: 1,
};

/**
 * JARVIS PER MODE, as deltas rather than five whole tunings.
 *
 * Deltas because a mode should state what is DIFFERENT about it. Five complete
 * copies drift: a change to the settled look has to be made five times and the
 * fifth is the one somebody forgets, which is how a body ends up with one mode
 * that still looks like last month.
 */
export const JARVIS_MODES: Record<BodyMode, Partial<JarvisTuning>> = {
  // IDLE, AND IT BREATHES. Not "everything turned down": a body that is merely dim
  // when idle reads as switched off, and the pulse table below gives this mode more
  // simultaneous motion than any other precisely because there is nothing else
  // happening to look at. The rings turn slowest here and take longest to come and
  // go, so the silhouette changes over twenty seconds rather than five.
  standby: {
    swirl: [0.05, 0],
    ringGain: [0.58, 0.2],
    ringSpin: [0.008, 0.003],
    ringLife: 0.028,
    ringArc: [1.15, 0.74],
    ringWidth: 0.125,
    irisGain: [0.5, 0.2],
    irisFlow: [0.05, 0.45],
    glyphGain: [0.16, 0.1],
    glyphBGain: [0.16, 0.1],
    glyphDensity: [0.42, 0.62],
    glyphBDensity: [0.42, 0.62],
    outerGain: [0.62, 0.24],
    outerPace: -0.72,
    core: [0.55, 0.3],
    shardGain: [0.42, 0.16],
    // A slow, wide swell rather than a ring: the front barely outruns the body, so
    // an idle pulse reads as the whole thing breathing.
    reverb: [0.85, 0.42, 0.5, 1.3],
  },
  // Turned toward you. The iris opens first -- that is the part of him that looks
  // at things -- and the rings pick up a little without hurrying.
  listening: {
    swirl: [0.075, 0],
    ringGain: [0.7, 0.3],
    ringSpin: [0.013, 0.004],
    ringLife: 0.04,
    ringArc: [1.25, 0.78],
    irisGain: [0.95, 0.55],
    irisRadius: [0.05, 0.3],
    irisFil: [0.92, 0.005],
    irisFlow: [0.1, 0.6],
    glyphGain: [0.26, 0.16],
    glyphBGain: [0.26, 0.16],
    glyphDensity: [0.6, 0.55],
    glyphBDensity: [0.6, 0.55],
    outerGain: [0.85, 0.4],
    outerPace: -0.62,
    core: [0.75, 0.48],
    shardGain: [0.5, 0.24],
    reverb: [1.25, 0.34, 0.68, 1.34],
  },
  // The inscriptions and the iris do the work: this is the mode that is reading
  // something. The flow through the iris quickens and more marks light.
  thinking: {
    swirl: [0.115, 0],
    ringGain: [0.92, 0.55],
    ringSpin: [0.022, 0.007],
    ringLife: 0.062,
    ringArc: [1.35, 0.84],
    ringWidth: 0.155,
    irisGain: [1.1, 0.7],
    irisFlow: [0.18, 0.72],
    glyphGain: [0.4, 0.3],
    glyphBGain: [0.4, 0.3],
    glyphDensity: [0.78, 0.5],
    glyphBDensity: [0.78, 0.5],
    outerGain: [1.2, 0.62],
    outerPace: -0.44,
    core: [1, 1],
    shardGain: [1, 0.475],
    reverb: [2.2, 0.26, 0.44, 1.52],
  },
  // Circuitry in transit. The shards lead, the rings turn like platters and come
  // and go fastest, and the outer shell keeps closer to the interior's pace.
  working: {
    swirl: [0.14, 0],
    ringGain: [0.86, 0.46],
    ringSpin: [0.034, 0.011],
    ringLife: 0.085,
    ringArc: [1.6, 0.86],
    ringWidth: 0.16,
    irisGain: [0.9, 0.5],
    irisFlow: [0.2, 0.62],
    glyphGain: [0.42, 0.28],
    glyphBGain: [0.42, 0.28],
    glyphSpin: [0.042, 0.6],
    glyphBSpin: [0.042, 0.6],
    outerGain: [1.15, 0.55],
    outerPace: -0.34,
    shardGain: [1.18, 0.6],
    shardStride: 9,
    core: [0.9, 0.72],
    reverb: [2.1, 0.24, 0.88, 1.36],
  },
  // SPEAKING, AND IT REVERBERATES. The distinguishing setting is not brightness --
  // it is the reverb's DECAY, at 0.4 against standby's 0.5 and working's 0.88. A
  // slow decay means each front survives several reflections, so a syllable is
  // still crossing the body when the next one arrives and the whole thing rings
  // rather than pinging. The reach is pushed past the silhouette so the front turns
  // around out at the shell and comes back through everything.
  speaking: {
    swirl: [0.115, 0],
    ringGain: [0.92, 0.55],
    ringSpin: [0.022, 0.007],
    ringLife: 0.062,
    ringArc: [1.35, 0.84],
    ringWidth: 0.155,
    irisGain: [1.1, 0.7],
    irisFlow: [0.18, 0.72],
    glyphGain: [0.4, 0.3],
    glyphBGain: [0.4, 0.3],
    glyphDensity: [0.78, 0.5],
    glyphBDensity: [0.78, 0.5],
    outerGain: [1.2, 0.62],
    outerPace: -0.44,
    core: [1, 1],
    shardGain: [1, 0.475],
    reverb: [2.2, 0.26, 0.44, 1.52],
  },
};

/**
 * Jarvis's continuous modulation. Small, many at once, and never in step.
 *
 * DEPTHS ARE NOT COMPARABLE ACROSS FIELDS. A gain is re-read every frame, so its
 * depth is what you see. `swirl`, `ringSpin` and `facetSpin` are RATES integrated
 * into particle positions, so a pulse on one keeps displacing the distribution for
 * as long as it is applied rather than acting and being done. They are held at
 * 0.04 or below on that reasoning.
 *
 * It is reasoning, NOT a measurement, and the measurement that looked like it
 * confirmed it did not: a 0.075 brightness drift first read as a 30% swing caused
 * by these, but against a pinned control the same body drifted 0.097 with every
 * number held constant. The drift is the RING LIFECYCLE fading crests in and out,
 * and the pulses add nothing on top of it. So the cap is cheap insurance and the
 * real headroom is untested -- raising these is defensible, and doing it needs the
 * pinned-control comparison rather than a look at a still frame.
 *
 * The rates are chosen to be mutually irrational-ish rather than tidy multiples.
 * Tidy multiples re-align on a short cycle and the body visibly repeats itself,
 * which is worse than not moving at all.
 */
export const JARVIS_PULSES: Record<BodyMode, readonly Pulse[]> = {
  // THE MOST CROWDED TABLE, deliberately. Idle is the mode a person actually looks
  // at for minutes at a time, so it needs the most things moving and the least
  // amplitude in any of them: eight terms between 4% and 12%, on rates from a
  // sixty-second cycle down to a twenty-second one. Nothing here is fast enough to
  // catch the eye on its own, which is the entire point.
  standby: [
    { field: "ringGain", index: 0, depth: 0.12, rate: 0.023, phase: 0.00 },
    { field: "ringWidth", index: 0, depth: 0.10, rate: 0.017, phase: 0.21 },
    { field: "irisGain", index: 0, depth: 0.11, rate: 0.031, phase: 0.38 },
    { field: "irisFlow", index: 0, depth: 0.09, rate: 0.019, phase: 0.57 },
    { field: "core", index: 0, depth: 0.08, rate: 0.029, phase: 0.72 },
    { field: "outerGain", index: 0, depth: 0.10, rate: 0.013, phase: 0.86 },
    { field: "glyphDensity", index: 0, depth: 0.09, rate: 0.037, phase: 0.11 },
    { field: "swirl", index: 0, depth: 0.04, rate: 0.021, phase: 0.64 },
  ],
  listening: [
    { field: "irisGain", index: 0, depth: 0.12, rate: 0.053, phase: 0.00 },
    { field: "irisFlow", index: 0, depth: 0.14, rate: 0.037, phase: 0.19 },
    { field: "ringGain", index: 0, depth: 0.09, rate: 0.043, phase: 0.35 },
    { field: "core", index: 0, depth: 0.09, rate: 0.029, phase: 0.52 },
    { field: "outerGain", index: 0, depth: 0.11, rate: 0.023, phase: 0.68 },
    { field: "glyphDensity", index: 0, depth: 0.10, rate: 0.061, phase: 0.81 },
    { field: "ringWidth", index: 0, depth: 0.07, rate: 0.031, phase: 0.94 },
    { field: "swirl", index: 0, depth: 0.04, rate: 0.027, phase: 0.44 },
  ],
  thinking: [
    { field: "glyphDensity", index: 0, depth: 0.16, rate: 0.089, phase: 0.00 },
    { field: "irisFlow", index: 0, depth: 0.18, rate: 0.071, phase: 0.17 },
    { field: "irisGain", index: 0, depth: 0.12, rate: 0.047, phase: 0.31 },
    { field: "glyphGain", index: 0, depth: 0.14, rate: 0.101, phase: 0.46 },
    { field: "ringGain", index: 0, depth: 0.09, rate: 0.059, phase: 0.63 },
    { field: "core", index: 0, depth: 0.11, rate: 0.037, phase: 0.77 },
    { field: "outerGain", index: 0, depth: 0.10, rate: 0.029, phase: 0.90 },
    { field: "shardGain", index: 0, depth: 0.12, rate: 0.113, phase: 0.08 },
    { field: "swirl", index: 0, depth: 0.04, rate: 0.041, phase: 0.55 },
  ],
  working: [
    { field: "shardGain", index: 0, depth: 0.15, rate: 0.127, phase: 0.00 },
    { field: "ringGain", index: 0, depth: 0.11, rate: 0.083, phase: 0.22 },
    { field: "ringWidth", index: 0, depth: 0.10, rate: 0.061, phase: 0.41 },
    { field: "glyphGain", index: 0, depth: 0.12, rate: 0.109, phase: 0.58 },
    { field: "irisFlow", index: 0, depth: 0.13, rate: 0.091, phase: 0.73 },
    { field: "outerGain", index: 0, depth: 0.11, rate: 0.047, phase: 0.87 },
    { field: "core", index: 0, depth: 0.09, rate: 0.067, phase: 0.13 },
    { field: "ringSpin", index: 0, depth: 0.04, rate: 0.053, phase: 0.36 },
  ],
  // Shallower than the others, and that is not an oversight. While he is speaking
  // the REVERB is what moves the body, and a pulse table competing with it makes
  // both read as noise. These keep the parts the wavefront does not reach alive.
  speaking: [
    { field: "outerPace", index: 0, depth: 0.16, rate: 0.041, phase: 0.13 },
    { field: "ringWidth", index: 0, depth: 0.08, rate: 0.073, phase: 0.00 },
    { field: "ringGain", index: 0, depth: 0.07, rate: 0.049, phase: 0.27 },
    { field: "irisGain", index: 0, depth: 0.09, rate: 0.061, phase: 0.48 },
    { field: "glyphDensity", index: 0, depth: 0.08, rate: 0.037, phase: 0.66 },
    { field: "outerGain", index: 0, depth: 0.08, rate: 0.029, phase: 0.83 },
    { field: "irisFlow", index: 0, depth: 0.10, rate: 0.083, phase: 0.05 },
    { field: "swirl", index: 0, depth: 0.03, rate: 0.031, phase: 0.59 },
  ],
};

/** Jarvis's target for a mode. */
export function jarvisModeTuning(mode: BodyMode): JarvisTuning {
  return modeTuning(JARVIS_TUNING, JARVIS_MODES, mode);
}

/**
 * JARVIS V1 -- the original dial. Its tunable surface is what the renderer
 * can honestly change live: the seven identity genes (counts, ratios,
 * phase -- never radii, never anything a reading depends on), the accent,
 * the scale, and the bloom triplet. Same format as V2 above: a shipped
 * base, a per-mode function, nothing mutated in place. The dial never had
 * mode presets -- one register -- so every mode ships the base and the
 * bench's per-state saves diverge from there.
 */
export interface Jarvis1Tuning {
  accent: readonly [r: number, g: number, b: number];
  scale: number;
  bloom: readonly [threshold: number, knee: number, strength: number];
  irisSegments: number;
  dashSegments: number;
  arc1Fill: number;
  arc2Fill: number;
  speedSkew: number;
  chunkSeed: number;
  tickDensity: number;
}

/** What ships: the hand-tuned neutral instrument. */
export const JARVIS1_TUNING: Jarvis1Tuning = {
  accent: [0.478, 0.365, 0.878],
  scale: 1,
  bloom: [0.55, 0.25, 0.80],
  irisSegments: 0,
  dashSegments: 0,
  arc1Fill: 0.55,
  arc2Fill: 0.50,
  speedSkew: 1,
  chunkSeed: 0,
  tickDensity: 0,
};

export function jarvis1ModeTuning(_mode: BodyMode): Jarvis1Tuning {
  return { ...JARVIS1_TUNING };
}
