import {
  ULTRON_TUNING, type UltronTuning,
} from "./bodyTuning";
import { modeTuning, type BodyMode, type Pulse } from "./bodyModes";
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
  dendriteGain: [4.14, 1.44],
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
  veinGain: [0.0, 0.0],
  veinStreak: [0.110, 0.085],
  crackGain: [0.0, 0.0],
  crackRange: 0.19,
  facetGain: [0.0, 0.0],
  facetSize: 0.020,
  core: [0.101, 0.202],
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
  veinLimb: [0.26, 1.35],
  crackLimb: [0.22, 1.0],
  facetLimb: [0.22, 1.05],
  // Coverage does not matter while the body is sparks: let the birth swirl free.
  homePull: 0.0,
  knee: 0.5,
  // No membrane at birth -- the crystalline mass BLOOMS into one as the ease
  // carries these toward the settled tuning.
  membraneGain: [0.0, 0.0],
  membrane: [0.98, 0.10, 0.16],
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
  // The bases were near-black in practice -- measured (render harness,
  // 2026-08-20) at centre value 0.009 with 12% coverage, i.e. an empty
  // preview. Same principle as Jarvis's standby: quiet lives in the MOTION
  // dials (signal pace, swirl, spin), while the light holds high enough that
  // the membrane, the sparks and the ember core read at rest.
  standby: {
    dendriteGain: [3.8, 1.08],
    dendrite: [0.30, 0.46, 0.78, 0.020],
    bead: [7.0, 0.30],
    signal: [0.22, 2.4, 7.0],
    swirl: [0.06, 0.08],
    facetSpin: [0.04, 0.12],
    veinGain: [0.74, 0.36],
    crackGain: [0.46, 0.34],
    facetGain: [0.44, 0.32],
    core: [0.88, 0.5],
    outerShell: [1.45, 0.28, 0.85],
    reverb: [0.8, 0.44, 0.48, 1.34],
    irisGain: [0.42, 0.14],
    irisFlow: [0.06, 0.5],
    cloud: [0.3, 0.6],
    // The shell rests visible: at rest he IS the membrane, structure asleep.
    membraneGain: [0.38, 0.12],
  },
  listening: {
    dendriteGain: [3.78, 1.8],
    dendrite: [0.33, 0.5, 0.78, 0.024],
    bead: [8.0, 0.13],
    signal: [0.4, 2.4, 6.2],
    swirl: [0.12, 0.18],
    facetSpin: [0.08, 0.24],
    veinGain: [0.84, 0.69],
    crackGain: [0.66, 0.5],
    facetGain: [0.7, 0.52],
    core: [0.63, 0.78],
    outerShell: [1.45, 0.28, 0.58],
    reverb: [1.2, 0.36, 0.66, 1.36],
    irisGain: [0.46, 0.28],
    irisFlow: [0.12, 0.62],
    cloud: [0.32, 0.9],
    // LISTENING IS SURFACE. The skin brightens toward whoever is talking while
    // the interior stays quiet -- receiving, not computing.
    membraneGain: [0.52, 0.30],
  },
  // THE BUSIEST STATE. Every pass is up, the crystal turns fastest, the pathways
  // reach furthest and wander widest, the fracture lines spread.
  thinking: {
    dendriteGain: [4.86, 2.52],
    dendrite: [0.34, 0.52, 0.78, 0.026],
    bead: [9.0, 0.16],
    signal: [0.6, 2.2, 5.2],
    swirl: [0.15, 0.22],
    facetSpin: [0.1, 0.32],
    veinGain: [1.03, 0.86],
    crackGain: [0.86, 0.66],
    facetGain: [0.84, 0.61],
    core: [1.0, 1.35],
    reverb: [2.35, 0.16, 0.42, 1.54],
    irisGain: [0.6, 0.4],
    irisFlow: [0.18, 0.7],
    cloud: [0.36, 1.1],
    // THINKING IS INTERIOR. The shell thins so the churn reads through it; the
    // busiest state is inside him, not on him.
    membraneGain: [0.34, 0.18],
  },
  // Executing rather than searching: facets and fractures lead, the neurons hold.
  working: {
    dendriteGain: [4.5, 2.232],
    dendrite: [0.36, 0.52, 0.76, 0.03],
    bead: [11.0, 0.18],
    signal: [0.85, 2.8, 4.8],
    swirl: [0.2, 0.3],
    facetSpin: [0.14, 0.42],
    veinGain: [1.15, 0.95],
    crackGain: [1.0, 0.76],
    facetGain: [0.98, 0.7],
    facetSize: 0.019,
    core: [0.88, 1.05],
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
    dendriteGain: [4.86, 2.52],
    dendrite: [0.34, 0.52, 0.78, 0.026],
    bead: [9.0, 0.16],
    signal: [0.6, 2.2, 5.2],
    swirl: [0.15, 0.22],
    facetSpin: [0.1, 0.32],
    veinGain: [1.03, 0.86],
    crackGain: [0.95, 0.7],
    facetGain: [0.84, 0.61],
    core: [1.0, 1.35],
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

/** Ultron's target for a mode. */
export function ultronModeTuning(mode: BodyMode): UltronTuning {
  return modeTuning(ULTRON_TUNING, ULTRON_MODES, mode);
}
