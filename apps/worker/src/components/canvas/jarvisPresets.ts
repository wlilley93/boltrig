import {
  JARVIS_TUNING, type JarvisTuning,
} from "./bodyTuning";
import { modeTuning, type BodyMode, type Pulse } from "./bodyModes";

/**
 * WHERE JARVIS ARRIVES FROM.
 *
 * "Jarvis Final 1740" saved an arrival slot identical to its speaking look, so
 * the birth is now an ease from the spoken body to the standby one: the film
 * bright at 1.58-gain, shards up, interior draw dark — settling into the idle
 * breathing state over INTRO_SECONDS. The old wide-hoop draw-in belonged to the
 * particle-field look this canon replaced.
 */
export const JARVIS_ARRIVAL: JarvisTuning = {
  outerShell: [0.135144, 0, 0],
  ringGain: [0, 1],
  ringSpin: [0.4, 0.4],
  ringRadius: [2, 0.99],
  ringBeam: 0.01,
  ringLife: 0.4,
  ringArc: [9, 1],
  ringWidth: 0.002,
  irisGain: [0, 0],
  irisRadius: [0.02, 0.31],
  irisFil: [1, 1],
  irisFlow: [0.1, 0.1],
  glyphGain: [0, 1],
  glyphRadius: [1.16, 1.4],
  glyphSize: [0.16, 0.16],
  glyphSpin: [0.062, 0],
  glyphDensity: [1, 1],
  glyphBGain: [0, 0],
  glyphBRadius: [0.7, 0.95],
  glyphBSize: [0.03, 0.525],
  glyphBSpin: [0.19, 0.49],
  glyphBDensity: [0.57, 1],
  rings: 3,
  swirl: [0, 0.035],
  linkGain: [0, 0],
  reverb: [0.55, 0.04, 0.1, 0.4],
  linkBow: [0, 0],
  linkRange: 0.6,
  drawGain: [0, 0],
  streak: [0, 0.4],
  shardGain: [1, 0.25],
  shardSize: 0.0005,
  shardStride: 1,
  core: [0, 0],
  outerGain: [0, 0],
  outerStreak: [0.05, 0.05],
  outerLimb: [1, 0],
  outerPace: -0.48,
  starburst: 0,
  eye: [3.94, 0.62, 0, 15],
  drawLimb: [0, 0],
  linkLimb: [0.05, 0],
  clump: [1, 0.4],
  focus: [1.03, 0.675],
  lattice: [1.545, 1.21],
  latticeBlur: 0,
  latticeSat: 0.62,
  latticeGlow: 0.095,
  latticeSpeed: 0.6,
  presence: 0.55,
  bounce: [0.06, 0.1],
  bounceTrail: 0.55,
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
  // The base IS the standby slot of "Jarvis Final 1740", so idle changes nothing.
  standby: {},
  // Every particle to the shell, the interior dark, the debris clustered hard
  // (clump scale 8 is this mode's signature — nowhere else goes past 0.4) and
  // the shards at four times any other mode's gain. He turns himself outward.
  listening: {
    outerShell: [2.2, 2.2, 2.2],
    ringGain: [0, 1],
    swirl: [0, 0.035],
    drawGain: [0, 0],
    streak: [0, 0.4],
    shardGain: [4, 0.25],
    shardSize: 0.0005,
    outerGain: [3, 0],
    outerStreak: [0.05, 0.05],
    outerPace: -0.34,
    clump: [1, 8],
    drawLimb: [0, 0],
  },
  // The film races (latticeSpeed 4 against the idle 0.6) and the interior draw
  // comes back faintly with real swirl — the one mode where the field itself
  // visibly churns.
  thinking: {
    outerShell: [2.2, 2.2, 2.2],
    ringGain: [0, 1],
    swirl: [0.235, 0.035],
    drawGain: [0.32, 0.28],
    streak: [0.066, 0],
    shardGain: [1, 0.25],
    shardSize: 0.0005,
    outerGain: [3, 0],
    outerStreak: [0.05, 0.05],
    outerLimb: [1, 0],
    outerPace: -0.48,
    clump: [1, 0.4],
    latticeSpeed: 4,
    drawLimb: [0.71, 0.25],
  },
  // The heart comes on and rides the voice (core[1] carries the pulse table's
  // core sweep), and the iris aura opens to 4 — the working glow.
  working: {
    outerShell: [0.135144, 2.2, 2.2],
    ringGain: [0, 1],
    swirl: [0, 0.035],
    drawGain: [0, 0],
    streak: [0, 0.4],
    shardGain: [1, 0.25],
    shardSize: 0.0005,
    core: [0, 0.42],
    outerStreak: [0.05, 0.05],
    outerLimb: [1, 0],
    outerPace: -0.48,
    clump: [1, 0.4],
    eye: [3.94, 4, 0, 15],
    drawLimb: [0, 0],
  },
  // Nearly bare at rest — the SPEECH map is this mode's real body: every reach
  // in JARVIS_SPEECH blooms on the syllable envelope and settles back here in
  // the gaps between words.
  speaking: {
    outerShell: [0.135144, 0, 0],
    ringGain: [0, 1],
    swirl: [0, 0.035],
    drawGain: [0, 0],
    streak: [0, 0.4],
    shardGain: [1, 0.25],
    shardSize: 0.0005,
    outerStreak: [0.05, 0.05],
    outerLimb: [1, 0],
    outerPace: -0.48,
    clump: [1, 0.4],
    drawLimb: [0, 0],
  },
};

/**
 * Jarvis's continuous modulation — the bench LFO rack of "Jarvis Final 1740",
 * translated exactly.
 *
 * The bench swept these fields with raised-cosine LFOs over absolute min..max
 * ranges, overriding the dial; a Pulse is a sine FRACTION of the base. The two
 * meet where the base carries the sweep's centre (JARVIS_TUNING does, see its
 * doc) and the pulse carries depth = half-range/centre with the phase shifted
 * back a quarter turn (0.5 - 0.5·cos(2πx) = 0.5 + 0.5·sin(2π(x - 0.25))). A
 * depth of 1 is therefore deliberate, not a typo: those sweeps bottom at zero.
 *
 * The canon ran ONE rack in every state, so four of the five tables are the
 * same six sweeps; working adds the heart (core[1] 0..0.84 at 0.15Hz), which
 * is the only per-state LFO the canon carries.
 */
const FINAL_1740_SWEEPS: readonly Pulse[] = [
  // irisFlow both components 0..0.2 at 0.15Hz, a quarter turn apart.
  { field: "irisFlow", index: 0, depth: 1, rate: 0.15, phase: 0.75 },
  { field: "irisFlow", index: 1, depth: 1, rate: 0.15, phase: 0.00 },
  // focus[0] 0.53..1.53, focus[1] 0.425..0.925 — the shard depth-of-field
  // slowly racks in and out.
  { field: "focus", index: 0, depth: 0.4854, rate: 0.15, phase: 0.75 },
  { field: "focus", index: 1, depth: 0.3704, rate: 0.19, phase: 0.00 },
  // The film breathes: lattice gain 0.9..2.19 over ten seconds.
  { field: "lattice", index: 0, depth: 0.4175, rate: 0.10, phase: 0.75 },
  // Its glow 0..0.19 in step with the iris.
  { field: "latticeGlow", index: 0, depth: 1, rate: 0.15, phase: 0.75 },
];

export const JARVIS_PULSES: Record<BodyMode, readonly Pulse[]> = {
  standby: FINAL_1740_SWEEPS,
  listening: FINAL_1740_SWEEPS,
  thinking: FINAL_1740_SWEEPS,
  working: [
    ...FINAL_1740_SWEEPS,
    { field: "core", index: 1, depth: 1, rate: 0.15, phase: 0.00 },
  ],
  speaking: FINAL_1740_SWEEPS,
};

/**
 * WHAT A SYLLABLE DOES TO THE BODY — the bench's speech-reach map, verbatim
 * from the speaking slot of "Jarvis Final 1740".
 *
 * Each entry is "field:index" → the value that dial holds at full syllable;
 * the renderer lerps from the mode's value toward it on the voice envelope, so
 * the whole body blooms on a vowel and settles home through the gaps between
 * words. This map, not the speaking deltas above, is most of what speaking
 * LOOKS like: the interior draw (0→3), the outer shell population (0→0.93),
 * the wheels (ringGain 0→1.76), the lens ring (eye[2] 0→0.37) and the film's
 * pace (0.6→1.3) all live here.
 *
 * The canon saved near-identical maps on every slot (standby differs in five
 * entries, thinking in three); the speaking slot's is the one shipped because
 * speech is when the envelope actually runs.
 */
export const JARVIS_SPEECH: Readonly<Record<string, number>> = {
  "clump:0": 0.12,
  "clump:1": 0.55,
  "core:0": 0.02,
  "core:1": 0.6,
  "drawGain:0": 3,
  "drawGain:1": 0.22,
  "drawLimb:1": 0.67,
  "eye:0": 4,
  "eye:1": 0.48,
  "eye:2": 0.37,
  "glyphBDensity:1": 0.09,
  "glyphBGain:0": 0.1,
  "glyphBGain:1": 0.39,
  "glyphBSize:1": 0.635,
  "glyphGain:0": 0.04,
  "glyphGain:1": 0.2,
  "glyphRadius:0": 1.28,
  "irisFil:0": 0.12,
  "irisFil:1": 1,
  "irisFlow:0": 0.14,
  "irisFlow:1": 0.425,
  "irisGain:0": 0.22,
  "irisGain:1": 0.02,
  "irisRadius:0": 0.06,
  "irisRadius:1": 0.04,
  "lattice:0": 2,
  "latticeBlur:0": 0,
  "latticeSat:0": 0.84,
  "latticeSpeed:0": 1.3,
  "linkBow:0": 0.04,
  "linkBow:1": 0.002,
  "linkGain:0": 0.28,
  "linkGain:1": 0.04,
  "linkLimb:0": 2.71,
  "linkRange:0": 0.365,
  "outerGain:0": 1.6,
  "outerGain:1": 0.92,
  "outerLimb:0": 0.15,
  "outerLimb:1": 0.375,
  "outerPace:0": 0.46,
  "outerShell:0": 0.68,
  "outerShell:1": 0.93,
  "outerShell:2": 2.2,
  "outerStreak:0": 0.041,
  "outerStreak:1": 0.05,
  "ringBeam:0": 0.055,
  "ringGain:0": 1.76,
  "ringLife:0": 0.255,
  "ringWidth:0": 0.008,
  "shardGain:0": 3.2,
  "shardGain:1": 0.24,
  "shardSize:0": 0.0007,
  "shardStride:0": 3,
  "starburst:0": 0.21,
  "streak:0": 0.088,
  "streak:1": 0.4,
  "swirl:1": 0.04,
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
  /** Radius multiplier -- how much space the dial takes, same meaning as V2. */
  presence: number;
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
  presence: 1,
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
