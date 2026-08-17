import {
  JARVIS_TUNING, ULTRON_TUNING, type JarvisTuning, type UltronTuning,
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
  glyphRadius: [0.62, 1.16],
  glyphSize: [0.055, 0.008],
  glyphSpin: [0.026, 0.55],
  glyphDensity: [0.72, 0.55],
  rings: 1,
  swirl: [0.105, 0],
  linkGain: [0, 0],
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
  // Ticking over. Rings nearly still, network quiet, heart low. A waiting
  // instrument should look like it could wait all day.
  standby: {
    swirl: [0.055, 0],
    ringGain: [0.42, 0.20],
    ringSpin: [0.018, 0.006],
    ringLife: 0.045,
    ringArc: [3, 0.36],
    irisGain: [0.4, 0.22],
    irisFlow: [0.07, 0.5],
    glyphGain: [0.2, 0.12],
    glyphDensity: [0.5, 0.6],
    linkGain: [0, 0],
    core: [0.55, 0.30],
    shardGain: [0.55, 0.20],
    outerGain: [0.7, 0.3],
    outerPace: -0.68,
  },
  // Turned toward you: rings pick up, the network opens and reaches further,
  // but nothing is being computed yet so the shards stay down.
  listening: {
    swirl: [0.085, 0],
    ringGain: [0.58, 0.34],
    ringSpin: [0.032, 0.009],
    ringLife: 0.075,
    ringArc: [4, 0.42],
    irisGain: [0.58, 0.34],
    irisFlow: [0.11, 0.6],
    glyphGain: [0.3, 0.2],
    glyphDensity: [0.66, 0.55],
    linkGain: [0, 0],
    linkRange: 0.72,
    core: [0.78, 0.50],
    shardGain: [0.65, 0.30],
    outerGain: [0.95, 0.45],
    outerPace: -0.6,
  },
  // The network is the point. Pathways brighten and WANDER further -- the one
  // mode where the bow is doing visible work.
  thinking: {
    swirl: [0.125, 0],
    linkGain: [0, 0],
    linkBow: [0.235, 0.31],
    linkRange: 0.80,
    ringGain: [0.55, 0.32],
    ringSpin: [0.040, 0.012],
    ringLife: 0.10,
    outerGain: [1.1, 0.5],
    outerPace: -0.48,
    ringArc: [4, 0.48],
    irisGain: [0.72, 0.46],
    irisFil: [0.92, 0.006],
    irisFlow: [0.22, 0.75],
    glyphGain: [0.46, 0.3],
    glyphSpin: [0.05, 0.7],
    glyphDensity: [0.88, 0.45],
    core: [0.88, 0.70],
  },
  // Circuitry in transit: the shards lead and the rings turn like platters.
  working: {
    swirl: [0.16, 0],
    ringGain: [0.72, 0.44],
    ringSpin: [0.075, 0.020],
    ringLife: 0.14,
    ringArc: [5, 0.54],
    irisGain: [0.66, 0.4],
    irisFlow: [0.18, 0.7],
    glyphGain: [0.42, 0.28],
    glyphSpin: [0.042, 0.6],
    glyphDensity: [0.8, 0.5],
    ringWidth: 0.072,
    shardGain: [1.18, 0.60],
    shardStride: 9,
    outerGain: [1.25, 0.6],
    outerPace: -0.4,
    linkGain: [0, 0],
  },
  // Everything present and the HEART is what moves: pulsedCore oscillates the
  // energy half against the voice bands rather than merely raising it.
  speaking: {
    swirl: [0.135, 0],
    ringGain: [0.78, 0.52],
    ringSpin: [0.055, 0.016],
    ringLife: 0.11,
    ringArc: [4, 0.5],
    irisGain: [0.7, 0.48],
    irisFlow: [0.15, 0.68],
    glyphGain: [0.36, 0.26],
    glyphDensity: [0.74, 0.52],
    ringWidth: 0.068,
    linkGain: [0, 0],
    core: [1, 1],
    shardGain: [1, 0.475],
    outerGain: [1.2, 0.58],
    outerPace: -0.5,
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
  standby: [
    { field: "ringGain", index: 0, depth: 0.10, rate: 0.041, phase: 0.00 },
    { field: "core", index: 0, depth: 0.07, rate: 0.029, phase: 0.31 },
    { field: "swirl", index: 0, depth: 0.04, rate: 0.023, phase: 0.62 },
    { field: "ringBeam", index: 0, depth: 0.08, rate: 0.037, phase: 0.17 },
  ],
  listening: [
    { field: "ringGain", index: 0, depth: 0.09, rate: 0.067, phase: 0.00 },
    { field: "linkGain", index: 0, depth: 0.14, rate: 0.053, phase: 0.27 },
    { field: "core", index: 0, depth: 0.08, rate: 0.043, phase: 0.55 },
    { field: "linkRange", index: 0, depth: 0.06, rate: 0.031, phase: 0.79 },
    { field: "ringSpin", index: 0, depth: 0.04, rate: 0.049, phase: 0.13 },
  ],
  thinking: [
    { field: "linkGain", index: 0, depth: 0.18, rate: 0.089, phase: 0.00 },
    { field: "linkBow", index: 0, depth: 0.16, rate: 0.061, phase: 0.23 },
    { field: "linkRange", index: 0, depth: 0.09, rate: 0.047, phase: 0.48 },
    { field: "ringGain", index: 0, depth: 0.10, rate: 0.073, phase: 0.66 },
    { field: "core", index: 0, depth: 0.09, rate: 0.037, phase: 0.84 },
    { field: "swirl", index: 0, depth: 0.04, rate: 0.029, phase: 0.09 },
  ],
  working: [
    { field: "shardGain", index: 0, depth: 0.13, rate: 0.113, phase: 0.00 },
    { field: "ringSpin", index: 0, depth: 0.04, rate: 0.071, phase: 0.35 },
    { field: "ringGain", index: 0, depth: 0.08, rate: 0.091, phase: 0.58 },
    { field: "swirl", index: 0, depth: 0.04, rate: 0.043, phase: 0.72 },
    { field: "linkGain", index: 0, depth: 0.10, rate: 0.059, phase: 0.19 },
  ],
  speaking: [
    { field: "ringGain", index: 0, depth: 0.08, rate: 0.079, phase: 0.00 },
    { field: "ringBeam", index: 0, depth: 0.07, rate: 0.053, phase: 0.29 },
    { field: "linkGain", index: 0, depth: 0.11, rate: 0.067, phase: 0.51 },
    { field: "swirl", index: 0, depth: 0.04, rate: 0.037, phase: 0.74 },
  ],
};

/**
 * WHERE ULTRON ARRIVES FROM: the birth sequence, in one tuning.
 *
 * Sparks first, then the neurons build. So the dendrites are the ONLY thing
 * present here -- long, spiky, sparsely beaded so they read as travelling
 * sparks rather than as finished filaments -- while the veins, cracks and facets
 * are at zero and the heart is barely a point. The shell sits at twice the radius
 * and almost invisible: the "much lighter and distant outer sphere".
 *
 * Easing to the settled look then performs the rest of the sequence on its own:
 * the crystalline cloud blooms, the outer circle takes shape and closes in, and
 * the central piece globs up out of nothing.
 */
export const ULTRON_ARRIVAL: UltronTuning = {
  dendriteGain: [1.15, 0.40],
  // Long roots, a NARROW fork and heavy taper: that combination reads as sparks
  // shooting outward. Widening the fork here turned it into a firework.
  dendrite: [0.62, 0.30, 0.95, 0.10],
  dendriteTip: [1.50, 0.90],
  // Few, long beads. A dense bead train looks like a finished wire; a sparse one
  // looks like something travelling along it.
  bead: [3.0, 0.85],
  outerShell: [2.2, 0.90, 0.10],
  facetSpin: [0.05, 0.10],
  swirl: [0.05, 0],
  veinGain: [0, 0],
  veinStreak: [0.110, 0.085],
  crackGain: [0, 0],
  crackRange: 0.19,
  facetGain: [0, 0],
  facetSize: 0.020,
  core: [0.02, 0.04],
  // No iris, ever: his brief is a crystalline cloud. Width 60 is the pre-eye
  // value, so his centre is exactly what it was.
  eye: [1, 1, 0, 60],
  petal: 0.3,
  veinLimb: [0.30, 0.95],
  crackLimb: [0.36, 0.88],
  facetLimb: [0.28, 0.95],
};

/**
 * ULTRON PER MODE.
 *
 * The brief set the shape of this directly: thinking carries the most activity,
 * standby the least, and speaking is STRUCTURED rather than frantic. That last
 * one is the interesting constraint -- the intuitive move is to make speech the
 * busiest state, and it is wrong. Something that thrashes while it talks reads as
 * agitated. Ultron talks like he already knows the answer.
 */
export const ULTRON_MODES: Record<BodyMode, Partial<UltronTuning>> = {
  // The least exciting state, and deliberately so. The crystal is nearly still,
  // the pathways dim, the heart a low ember.
  standby: {
    dendriteGain: [0.34, 0.20],
    dendrite: [0.30, 0.46, 0.78, 0.018],
    bead: [6.0, 0.42],
    swirl: [0.09, 0.12],
    facetSpin: [0.05, 0.14],
    veinGain: [0.11, 0.10],
    crackGain: [0.16, 0.12],
    facetGain: [0.20, 0.14],
    core: [0.07, 0.09],
    outerShell: [1.45, 0.20, 0.22],
  },
  // Attending. The shell brightens -- he is listening with the whole surface --
  // and the pathways open, but the interior stays composed.
  listening: {
    dendriteGain: [0.52, 0.36],
    dendrite: [0.33, 0.50, 0.78, 0.026],
    bead: [6.5, 0.50],
    swirl: [0.16, 0.24],
    facetSpin: [0.09, 0.26],
    veinGain: [0.18, 0.16],
    crackGain: [0.26, 0.20],
    facetGain: [0.30, 0.22],
    core: [0.10, 0.13],
    outerShell: [1.45, 0.22, 0.36],
  },
  // THE BUSIEST STATE. Every pass is up, the crystal turns fastest, the pathways
  // reach their longest and wander their widest, and the fracture lines spread.
  thinking: {
    dendriteGain: [0.86, 0.62],
    dendrite: [0.42, 0.58, 0.72, 0.058],
    dendriteTip: [1.10, 0.34],
    bead: [8.5, 0.62],
    swirl: [0.34, 0.52],
    facetSpin: [0.19, 0.52],
    veinGain: [0.30, 0.26],
    veinStreak: [0.135, 0.100],
    crackGain: [0.44, 0.32],
    crackRange: 0.26,
    facetGain: [0.46, 0.32],
    core: [0.17, 0.22],
  },
  // Processing rather than reasoning: the facets and fracture lines lead, the
  // dendrites hold steady. Busy, but ordered -- it is executing, not searching.
  working: {
    dendriteGain: [0.66, 0.46],
    dendrite: [0.36, 0.52, 0.76, 0.032],
    bead: [9.5, 0.58],
    swirl: [0.26, 0.40],
    facetSpin: [0.15, 0.44],
    veinGain: [0.26, 0.22],
    crackGain: [0.40, 0.30],
    facetGain: [0.42, 0.30],
    facetSize: 0.024,
    core: [0.14, 0.18],
  },
  // Structured, not crazy. Deliberately CALMER than thinking: the pathways settle
  // into an even bead train, the crystal turns steadily, and the heart is the only
  // thing really moving -- pulsedCore drives it from the voice bands.
  speaking: {
    dendriteGain: [0.62, 0.48],
    dendrite: [0.34, 0.52, 0.78, 0.028],
    bead: [7.0, 0.55],
    swirl: [0.20, 0.30],
    facetSpin: [0.11, 0.34],
    veinGain: [0.22, 0.20],
    crackGain: [0.34, 0.26],
    facetGain: [0.36, 0.26],
    core: [0.16, 0.24],
  },
};

/**
 * Ultron's continuous modulation, and there is MORE of it than Jarvis has.
 *
 * Jarvis is an instrument, so his modulation is a needle drifting. Ultron is
 * something growing, so more of him moves at once -- but each pulse is still
 * shallow. The whole point of "many things, none of them far" is that no single
 * parameter draws attention to itself as an animation; the body just never quite
 * repeats.
 */
export const ULTRON_PULSES: Record<BodyMode, readonly Pulse[]> = {
  standby: [
    { field: "dendriteGain", index: 0, depth: 0.11, rate: 0.031, phase: 0.00 },
    { field: "facetGain", index: 0, depth: 0.09, rate: 0.023, phase: 0.28 },
    { field: "core", index: 0, depth: 0.10, rate: 0.019, phase: 0.53 },
    { field: "bead", index: 1, depth: 0.08, rate: 0.043, phase: 0.71 },
    { field: "outerShell", index: 2, depth: 0.09, rate: 0.017, phase: 0.14 },
  ],
  listening: [
    { field: "dendriteGain", index: 0, depth: 0.12, rate: 0.053, phase: 0.00 },
    { field: "crackGain", index: 0, depth: 0.10, rate: 0.041, phase: 0.22 },
    { field: "facetGain", index: 0, depth: 0.09, rate: 0.061, phase: 0.44 },
    { field: "core", index: 0, depth: 0.11, rate: 0.029, phase: 0.63 },
    { field: "outerShell", index: 2, depth: 0.12, rate: 0.037, phase: 0.81 },
    { field: "bead", index: 0, depth: 0.07, rate: 0.047, phase: 0.11 },
  ],
  thinking: [
    { field: "dendriteGain", index: 0, depth: 0.17, rate: 0.097, phase: 0.00 },
    { field: "dendrite", index: 1, depth: 0.10, rate: 0.071, phase: 0.19 },
    { field: "dendrite", index: 3, depth: 0.08, rate: 0.113, phase: 0.37 },
    { field: "crackGain", index: 0, depth: 0.15, rate: 0.083, phase: 0.52 },
    { field: "crackRange", index: 0, depth: 0.11, rate: 0.059, phase: 0.68 },
    { field: "facetGain", index: 0, depth: 0.13, rate: 0.101, phase: 0.79 },
    { field: "veinGain", index: 0, depth: 0.14, rate: 0.067, phase: 0.91 },
    { field: "core", index: 0, depth: 0.12, rate: 0.043, phase: 0.07 },
    { field: "bead", index: 0, depth: 0.09, rate: 0.089, phase: 0.26 },
  ],
  working: [
    { field: "facetGain", index: 0, depth: 0.13, rate: 0.109, phase: 0.00 },
    { field: "crackGain", index: 0, depth: 0.12, rate: 0.079, phase: 0.24 },
    { field: "facetSpin", index: 0, depth: 0.04, rate: 0.061, phase: 0.46 },
    { field: "dendriteGain", index: 0, depth: 0.09, rate: 0.091, phase: 0.61 },
    { field: "bead", index: 0, depth: 0.11, rate: 0.127, phase: 0.77 },
    { field: "core", index: 0, depth: 0.08, rate: 0.047, phase: 0.93 },
    { field: "veinStreak", index: 0, depth: 0.10, rate: 0.071, phase: 0.15 },
  ],
  speaking: [
    { field: "dendriteGain", index: 0, depth: 0.09, rate: 0.067, phase: 0.00 },
    { field: "facetGain", index: 0, depth: 0.08, rate: 0.049, phase: 0.31 },
    { field: "crackGain", index: 0, depth: 0.08, rate: 0.057, phase: 0.57 },
    { field: "veinGain", index: 0, depth: 0.09, rate: 0.039, phase: 0.72 },
    { field: "bead", index: 1, depth: 0.07, rate: 0.083, phase: 0.88 },
    { field: "outerShell", index: 2, depth: 0.07, rate: 0.029, phase: 0.12 },
  ],
};

/** Jarvis's target for a mode. */
export function jarvisModeTuning(mode: BodyMode): JarvisTuning {
  return modeTuning(JARVIS_TUNING, JARVIS_MODES, mode);
}

/** Ultron's target for a mode. */
export function ultronModeTuning(mode: BodyMode): UltronTuning {
  return modeTuning(ULTRON_TUNING, ULTRON_MODES, mode);
}
