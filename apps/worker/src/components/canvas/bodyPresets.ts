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
    glyphDensity: [0.42, 0.62],
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
    glyphDensity: [0.6, 0.55],
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
    glyphDensity: [0.78, 0.5],
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
    glyphSpin: [0.042, 0.6],
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
    glyphDensity: [0.78, 0.5],
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
  bead: [4.0, 0.04],
  signal: [1.8, 3.4, 8.0],
  arc: [0.82, 2.5, 0.42, 0.0],
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
  reverb: [0.9, 0.4, 1.2, 1.4],
  irisGain: [0, 0],
  irisRadius: [0.04, 0.19],
  irisFil: [0.8, 0.004],
  irisFlow: [0.16, 0.7],
  cloud: [0.62, 1.6],
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
  // IDLE, AND IT BREATHES -- the same principle as Jarvis, in his own vocabulary.
  // The crystal barely turns, the neurons are quiet, and the pulse table carries
  // eight shallow terms so that a body nobody is talking to is still plainly alive.
  standby: {
    dendriteGain: [0.75, 0.3],
    dendrite: [0.30, 0.46, 0.78, 0.016],
    bead: [7.0, 0.10],
    signal: [0.22, 2.4, 7.0],
    swirl: [0.08, 0.1],
    facetSpin: [0.04, 0.12],
    veinGain: [0.11, 0.1],
    crackGain: [0.16, 0.12],
    facetGain: [0.2, 0.14],
    core: [0.07, 0.09],
    outerShell: [1.45, 0.2, 0.2],
    reverb: [0.8, 0.44, 0.48, 1.34],
    irisGain: [0.3, 0.14],
    irisFlow: [0.06, 0.5],
    cloud: [0.3, 0.7],
  },
  listening: {
    dendriteGain: [1.05, 0.5],
    dendrite: [0.33, 0.5, 0.78, 0.024],
    bead: [8.0, 0.13],
    signal: [0.4, 2.4, 6.2],
    swirl: [0.15, 0.22],
    facetSpin: [0.08, 0.24],
    veinGain: [0.18, 0.16],
    crackGain: [0.26, 0.2],
    facetGain: [0.3, 0.22],
    core: [0.1, 0.13],
    outerShell: [1.45, 0.22, 0.34],
    reverb: [1.2, 0.36, 0.66, 1.36],
    irisGain: [0.46, 0.28],
    irisFlow: [0.12, 0.62],
    cloud: [0.32, 0.9],
  },
  // THE BUSIEST STATE. Every pass is up, the crystal turns fastest, the pathways
  // reach furthest and wander widest, the fracture lines spread.
  thinking: {
    dendriteGain: [1.35, 0.7],
    dendrite: [0.34, 0.52, 0.78, 0.026],
    bead: [9.0, 0.16],
    signal: [0.6, 2.2, 5.2],
    swirl: [0.19, 0.28],
    facetSpin: [0.1, 0.32],
    veinGain: [0.22, 0.2],
    crackGain: [0.34, 0.26],
    facetGain: [0.36, 0.26],
    core: [0.16, 0.24],
    reverb: [2.35, 0.16, 0.42, 1.54],
    irisGain: [0.6, 0.4],
    irisFlow: [0.18, 0.7],
    cloud: [0.36, 1.1],
  },
  // Executing rather than searching: facets and fractures lead, the neurons hold.
  working: {
    dendriteGain: [1.25, 0.62],
    dendrite: [0.36, 0.52, 0.76, 0.03],
    bead: [11.0, 0.18],
    signal: [0.85, 2.8, 4.8],
    swirl: [0.25, 0.38],
    facetSpin: [0.14, 0.42],
    veinGain: [0.26, 0.22],
    crackGain: [0.4, 0.3],
    facetGain: [0.42, 0.3],
    facetSize: 0.024,
    core: [0.14, 0.18],
    reverb: [2.05, 0.26, 0.86, 1.38],
    irisGain: [0.55, 0.34],
    irisFlow: [0.2, 0.72],
    cloud: [0.38, 1.2],
  },
  // STRUCTURED, AND RINGING. Calmer in its parts than thinking -- an even bead
  // train, a steady crystal -- while the reverb's slow decay carries the voice
  // through the whole body. Something that thrashes while it talks reads as
  // agitated; Ultron talks like he already knows the answer.
  speaking: {
    dendriteGain: [1.35, 0.7],
    dendrite: [0.34, 0.52, 0.78, 0.026],
    bead: [9.0, 0.16],
    signal: [0.6, 2.2, 5.2],
    swirl: [0.19, 0.28],
    facetSpin: [0.1, 0.32],
    veinGain: [0.22, 0.2],
    crackGain: [0.34, 0.26],
    facetGain: [0.36, 0.26],
    core: [0.16, 0.24],
    reverb: [2.35, 0.16, 0.42, 1.54],
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
    { field: "dendriteGain", index: 0, depth: 0.12, rate: 0.023, phase: 0.00 },
    { field: "facetGain", index: 0, depth: 0.10, rate: 0.017, phase: 0.19 },
    { field: "crackGain", index: 0, depth: 0.09, rate: 0.031, phase: 0.36 },
    { field: "core", index: 0, depth: 0.11, rate: 0.013, phase: 0.54 },
    { field: "bead", index: 1, depth: 0.09, rate: 0.037, phase: 0.69 },
    { field: "outerShell", index: 2, depth: 0.10, rate: 0.019, phase: 0.83 },
    { field: "veinGain", index: 0, depth: 0.08, rate: 0.027, phase: 0.96 },
    { field: "swirl", index: 0, depth: 0.04, rate: 0.021, phase: 0.42 },
  ],
  listening: [
    { field: "dendriteGain", index: 0, depth: 0.13, rate: 0.047, phase: 0.00 },
    { field: "crackGain", index: 0, depth: 0.11, rate: 0.037, phase: 0.18 },
    { field: "facetGain", index: 0, depth: 0.10, rate: 0.059, phase: 0.34 },
    { field: "core", index: 0, depth: 0.12, rate: 0.026, phase: 0.51 },
    { field: "outerShell", index: 2, depth: 0.13, rate: 0.031, phase: 0.67 },
    { field: "bead", index: 0, depth: 0.08, rate: 0.043, phase: 0.82 },
    { field: "veinGain", index: 0, depth: 0.09, rate: 0.053, phase: 0.95 },
    { field: "swirl", index: 0, depth: 0.04, rate: 0.029, phase: 0.40 },
  ],
  thinking: [
    { field: "dendriteGain", index: 0, depth: 0.17, rate: 0.097, phase: 0.00 },
    { field: "dendrite", index: 1, depth: 0.10, rate: 0.071, phase: 0.16 },
    { field: "dendrite", index: 3, depth: 0.08, rate: 0.113, phase: 0.31 },
    { field: "crackGain", index: 0, depth: 0.15, rate: 0.083, phase: 0.45 },
    { field: "crackRange", index: 0, depth: 0.11, rate: 0.059, phase: 0.59 },
    { field: "facetGain", index: 0, depth: 0.13, rate: 0.101, phase: 0.72 },
    { field: "veinGain", index: 0, depth: 0.14, rate: 0.067, phase: 0.85 },
    { field: "core", index: 0, depth: 0.12, rate: 0.043, phase: 0.97 },
    { field: "bead", index: 0, depth: 0.09, rate: 0.089, phase: 0.24 },
  ],
  working: [
    { field: "facetGain", index: 0, depth: 0.14, rate: 0.109, phase: 0.00 },
    { field: "crackGain", index: 0, depth: 0.12, rate: 0.079, phase: 0.21 },
    { field: "facetSpin", index: 0, depth: 0.04, rate: 0.061, phase: 0.39 },
    { field: "dendriteGain", index: 0, depth: 0.10, rate: 0.091, phase: 0.56 },
    { field: "bead", index: 0, depth: 0.12, rate: 0.127, phase: 0.71 },
    { field: "core", index: 0, depth: 0.09, rate: 0.047, phase: 0.85 },
    { field: "veinStreak", index: 0, depth: 0.11, rate: 0.071, phase: 0.98 },
    { field: "facetSize", index: 0, depth: 0.08, rate: 0.053, phase: 0.32 },
  ],
  // Shallow, because the reverb is what carries speech through him.
  speaking: [
    { field: "dendriteGain", index: 0, depth: 0.09, rate: 0.061, phase: 0.00 },
    { field: "facetGain", index: 0, depth: 0.08, rate: 0.047, phase: 0.28 },
    { field: "crackGain", index: 0, depth: 0.08, rate: 0.053, phase: 0.52 },
    { field: "veinGain", index: 0, depth: 0.09, rate: 0.037, phase: 0.7 },
    { field: "bead", index: 1, depth: 0.07, rate: 0.079, phase: 0.86 },
    { field: "outerShell", index: 2, depth: 0.08, rate: 0.029, phase: 0.1 },
    { field: "core", index: 0, depth: 0.07, rate: 0.043, phase: 0.63 },
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
