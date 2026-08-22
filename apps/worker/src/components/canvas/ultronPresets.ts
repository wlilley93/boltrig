import {
  ULTRON_TUNING, type UltronTuning,
} from "./bodyTuning";
import { modeTuning, type BodyMode, type Pulse } from "./bodyModes";
/**
 * WHERE ULTRON ARRIVES FROM.
 *
 * "Ultron final 1800" saved an arrival slot identical to its standby look bar
 * the bounce (0.012 against 0.037), so the birth is now a settle rather than a
 * spark sequence: the membrane film is already up and the ease mostly brings
 * the bob in. The old dendrites-first birth belonged to the particle look this
 * canon replaced.
 */
export const ULTRON_ARRIVAL: UltronTuning = {
  dendriteGain: [0.945, 0.75],
  dendrite: [0.28, 0.52, 0.78, 0],
  dendriteTip: [1.14, 1.26],
  bead: [10, 21],
  signal: [0.22, 2.4, 7],
  arc: [0.82, 2.5, 0.42, 0.85],
  outerShell: [0.57, 2.2, 2.2],
  facetSpin: [1, 0],
  swirl: [0, 0],
  veinGain: [0, 0],
  veinStreak: [0, 0],
  crackGain: [0, 0],
  crackRange: 0.02,
  facetGain: [3, 3],
  facetSize: 0.002,
  core: [0, 0],
  eye: [0, 0, 0, 4],
  reverb: [0.8, 0.44, 0.48, 1.34],
  irisGain: [3, 3],
  irisRadius: [1.2, 1.2],
  irisFil: [1, 1],
  irisFlow: [0.8, 0.8],
  cloud: [0.3, 0.7],
  petal: 0,
  veinLimb: [0, 0],
  crackLimb: [0, 0],
  facetLimb: [0.08, 0.08],
  // Main's live-membrane mechanics, carried for the type but OFF: the canon
  // ("Ultron final 1800") was authored on the film deck — lattice IS his
  // membrane — and every one of these zeros is that mechanism's documented
  // identity value.
  homePull: 0.0,
  knee: 0,
  membraneGain: [0.0, 0.0],
  membrane: [0.98, 0.10, 0.12],
  lattice: [2.2, 0],
  latticeBlur: 0,
  latticeSat: 0.5,
  latticeGlow: 0,
  latticeSpeed: 1.2,
  presence: 0.6,
  bounce: [0.012, 0.35],
  bounceTrail: 0,
};

/**
 * ULTRON PER MODE — the per-state diffs of "Ultron final 1800".
 *
 * Far leaner than they used to be: the canon keeps one body across states and
 * spends its differences on the heart, the eye, the film's pace and the bob.
 * Listening and working switch the heart ON (core 0→3) — attention is when he
 * warms — and thinking is the one state that changes the crystal itself.
 */
export const ULTRON_MODES: Record<BodyMode, Partial<UltronTuning>> = {
  // The base IS the standby slot, so idle changes nothing.
  standby: {},
  listening: {
    core: [3, 3],
    eye: [4, 0.18, 0, 4],
    bounce: [0.033, 0.35],
  },
  // Every particle to the shell, the facets counter-spin and coarsen, and the
  // membrane film races (latticeSpeed 4 against the idle 1.2) while the bob
  // stops dead — he holds still to think.
  thinking: {
    outerShell: [2.2, 2.2, 2.2],
    facetSpin: [1, 1],
    facetSize: 0.008,
    facetLimb: [0.28, 0.08],
    latticeSpeed: 4,
    bounce: [0, 0.35],
  },
  working: {
    core: [3, 3],
    // LFO centre: the eye's aura sweeps 0..0.84 at 0.15Hz — the ONE sweep the
    // canon carries, and it is per-state. See ULTRON_PULSES.
    eye: [0.3, 0.42, 0, 4],
    bounce: [0.06, 0.35],
  },
  // Nearly the resting body — ULTRON_SPEECH is what speaking looks like, with
  // every reach blooming on the syllable envelope and settling back here.
  speaking: {
    bounce: [0.012, 0.35],
  },
};

/**
 * Ultron's continuous modulation: ONE sweep, in one state.
 *
 * "Ultron final 1800" saved an empty LFO rack in six of its seven slots — the
 * living motion is the membrane film, the bob, and ULTRON_SPEECH riding the
 * voice, and a pulse layered on top of the film reads as flicker rather than
 * life. WORKING is the exception: its eye aura breathes 0..0.84 at 0.15Hz,
 * which is why that state has an eye at all.
 *
 * Translated the same way as Jarvis's rack — the base carries the sweep's
 * centre and the pulse carries depth = half-range/centre with the phase
 * shifted back a quarter turn. Depth 1 is deliberate: the sweep bottoms at
 * zero, so the aura goes fully dark at the trough.
 */
const NO_PULSES: readonly Pulse[] = [];

export const ULTRON_PULSES: Record<BodyMode, readonly Pulse[]> = {
  standby: NO_PULSES,
  listening: NO_PULSES,
  thinking: NO_PULSES,
  working: [{ field: "eye", index: 1, depth: 1, rate: 0.15, phase: 0.00 }],
  speaking: NO_PULSES,
};

/**
 * WHAT A SYLLABLE DOES TO THE BODY — the bench's speech-reach map, verbatim
 * from the speaking slot of "Ultron final 1800" (every slot saved the same
 * map, so there is exactly one voice).
 *
 * Each entry is "field:index" → the value that dial holds at full syllable;
 * the renderer lerps from the mode's value toward it on the voice envelope.
 * The body he keeps dark at rest is all in here: veins, cracks and the heart
 * light on a vowel (core 0→3 through its [1] ramp), the dendrites fire
 * (dendriteGain 0.945→2.55), the membrane film surges (lattice 2.2→3 at
 * latticeSpeed 1.2→4), and it settles back through the gaps between words.
 */
export const ULTRON_SPEECH: Readonly<Record<string, number>> = {
  "arc:0": 0.42,
  "arc:1": 0.32,
  "arc:2": 3.2,
  "arc:3": 3.2,
  "bead:0": 24,
  "bead:1": 3,
  "core:0": 0.12,
  "core:1": 3,
  "crackGain:0": 0.74,
  "crackGain:1": 0.54,
  "crackLimb:0": 1.27,
  "crackLimb:1": 1.05,
  "crackRange:0": 0.065,
  "dendrite:0": 0.01,
  "dendrite:1": 0.11,
  "dendrite:2": 0.08,
  "dendrite:3": 0.11,
  "dendriteGain:0": 2.55,
  "dendriteGain:1": 2,
  "dendriteTip:0": 1.08,
  "dendriteTip:1": 0.2,
  "eye:0": 0.22,
  "eye:1": 0.2,
  "eye:2": 0.14,
  "facetGain:0": 0.72,
  "facetGain:1": 3,
  "facetLimb:0": 2.25,
  "facetLimb:1": 3,
  "facetSize:0": 0.004,
  "facetSpin:0": 0.17,
  "facetSpin:1": 0.35,
  "lattice:0": 3,
  "latticeGlow:0": 0.01,
  "latticeSpeed:0": 4,
  "outerShell:0": 0.57,
  "outerShell:1": 0.02,
  "outerShell:2": 1.28,
  "signal:0": 3,
  "signal:1": 0.82,
  "signal:2": 1.58,
  "swirl:1": 0.395,
  "veinGain:0": 0.1,
  "veinGain:1": 0.06,
  "veinLimb:0": 3,
  "veinLimb:1": 3,
  "veinStreak:0": 0.002,
  "veinStreak:1": 0.13,
};

/** Jarvis's target for a mode. */

/** Ultron's target for a mode. */
export function ultronModeTuning(mode: BodyMode): UltronTuning {
  return modeTuning(ULTRON_TUNING, ULTRON_MODES, mode);
}
