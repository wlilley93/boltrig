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

export interface JarvisTuning {
  /**
   * How fast the field turns over: the resting rate, and what a voice adds.
   *
   * This is what reads as SWIRL. Too high and it stops looking like a body
   * thinking and starts looking like a drink someone has stirred for a long
   * time -- pinned on an axis at high velocity rather than moving naturally.
   */
  swirl: EnergyRamp;
  /** The network. The BRIGHTEST of the three, and that is the whole fix. */
  linkGain: EnergyRamp;
  /**
   * How close two particles must be to count as connected.
   *
   * Widening this is what makes the graph DENSE; brightening a sparse graph
   * only gives brighter gaps.
   */
  linkRange: number;
  /** The filaments. */
  drawGain: EnergyRamp;
  /**
   * Streak length. Raised by the reciprocal when the advection rate was halved,
   * so the streaks kept their LENGTH and only the pace changed.
   */
  streak: EnergyRamp;
  /** The circuit quads. The DIMMEST of the three: they ride the field. */
  shardGain: EnergyRamp;
  shardSize: number;
  /** One shard per N particles. */
  shardStride: number;
  /** The heart at the centre. */
  core: EnergyRamp;
  /**
   * The anamorphic starburst, and it stays at zero for a hologram.
   *
   * A gaussian 4000 tight in y against 26 in x is a bar fifteen times wider
   * than tall in the hot colour, straight through the middle -- which is what
   * read as a white block shining through the iris. It belongs to Colossus,
   * whose CRT beam earns a horizontal streak.
   */
  starburst: number;
  /** The streaks' silhouette. An order of magnitude, not a factor of three. */
  drawLimb: LimbMix;
  /** The network's silhouette. Without it the web fills the see-through middle. */
  linkLimb: LimbMix;
}

export interface UltronTuning {
  /**
   * How fast the field turns over: the resting rate, and what a voice adds.
   *
   * This is what reads as SWIRL. Too high and it stops looking like a body
   * thinking and starts looking like a drink someone has stirred for a long
   * time -- pinned on an axis at high velocity rather than moving naturally.
   */
  swirl: EnergyRamp;
  /** The body he is MADE of. It leads, like Jarvis's network. */
  veinGain: EnergyRamp;
  /** Longer than Jarvis's streak: growth, not data in motion. */
  veinStreak: EnergyRamp;
  /** The jagged web. */
  crackGain: EnergyRamp;
  /** Tighter than it was: at 0.26 the web drew wires across the volume. */
  crackRange: number;
  /** The fracture shards. */
  facetGain: EnergyRamp;
  facetSize: number;
  /** The core glow. */
  core: EnergyRamp;
  /**
   * Three concentric clouds spread into arms. Jarvis leaves this at 0.
   *
   * 0.3, not 1.0. At 1.0 the arms reach far enough to read as flares around the
   * edge; at 0 he is Jarvis in blue, and the references separate the two by
   * silhouette as much as by colour.
   */
  petal: number;
  veinLimb: LimbMix;
  crackLimb: LimbMix;
  facetLimb: LimbMix;
}

/** What ships. The bench overrides a copy; nothing mutates this. */
export const JARVIS_TUNING: JarvisTuning = {
  swirl: [0.26, 0.40],
  linkGain: [0.30, 0.24],
  linkRange: 0.23,
  drawGain: [0.21, 0.19],
  streak: [0.051, 0.042],
  shardGain: [0.26, 0.20],
  shardSize: 0.014,
  shardStride: 11,
  core: [0.12, 0.16],
  starburst: 0.0,
  drawLimb: [0.12, 1.30],
  linkLimb: [0.25, 1.15],
};

export const ULTRON_TUNING: UltronTuning = {
  swirl: [0.26, 0.40],
  veinGain: [0.22, 0.20],
  veinStreak: [0.110, 0.085],
  crackGain: [0.34, 0.26],
  crackRange: 0.19,
  facetGain: [0.36, 0.26],
  facetSize: 0.020,
  core: [0.13, 0.17],
  petal: 0.3,
  veinLimb: [0.30, 0.95],
  crackLimb: [0.36, 0.88],
  facetLimb: [0.28, 0.95],
};

/** `base + perEnergy * energy`, the one place the ramp is evaluated. */
export function ramp(value: EnergyRamp, energy: number): number {
  return value[0] + value[1] * energy;
}
