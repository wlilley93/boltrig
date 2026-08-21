import type { EnergyRamp, LimbMix } from "./bodyRamp";

export interface UltronTuning {
  /**
   * THE NEURONS: nine pathways out of the centre, each forking to a cluster.
   *
   * His birth is a tree growing, not a cloud condensing, and none of his three
   * existing passes can draw one -- CRACK connects TEXTURE neighbours, which are
   * spatially unrelated by design, so it can flicker a web but never grow a
   * branch. See ultron/shadersDendrite.
   */
  dendriteGain: EnergyRamp;
  /** Root segment length, fork angle, per-level taper, per-node wander. */
  dendrite: readonly [rootLength: number, fork: number, taper: number, wander: number];
  /** Cluster glow at the tips, and how much a voice GROWS the tree. */
  dendriteTip: readonly [cluster: number, growth: number];
  /**
   * x signal marks along a whole filament, y how brightly the filament sits
   * between signals.
   *
   * The second half used to be a duty cycle on a static bead pattern. Beads that
   * never move are anatomy; what the brief asks for is the movement of signals
   * THROUGH the neurons, so it is now the resting glow a filament keeps when
   * nothing is firing along it -- at 0 the tree vanishes between pulses.
   */
  bead: readonly [marks: number, resting: number];
  /**
   * The travelling signals: speed outward, per-trunk phase spread, tail decay.
   *
   * Speed is in filament-lengths per second, so it does not have to be retuned
   * when the tree grows. The spread is what stops four pathways firing in unison,
   * which reads as one object flashing rather than as four carrying traffic.
   */
  signal: readonly [speed: number, spread: number, tail: number];
  /**
   * The four terminal arcs: hub distance, sweep in radians, radius, and how
   * strongly the tips are pulled onto them.
   *
   * The last one at 0 restores the old scattered tip knot exactly, which is the
   * property every addition to a shared shader in here has had to have.
   */
  arc: readonly [hub: number, sweep: number, radius: number, pull: number];
  /**
   * The distant outer sphere: radius, population fraction, brightness.
   *
   * Ultron's birth builds one -- the crystalline mass blooms and then the outer
   * circle takes shape around it, lighter and further out. Jarvis ships with the
   * fraction at ZERO, so his look is untouched until somebody decides where his
   * shells belong; the machinery is shared, the decision is not.
   */
  outerShell: readonly [radius: number, fraction: number, gain: number];
  /**
   * How fast each fracture sliver turns on its own axis: base, plus a per-shard
   * spread.
   *
   * Shipped at a third of what it was. The slivers are two line segments meeting
   * at a corner, and a large one turning at 1.6 rad/s reads as a clock hand
   * sweeping the body rather than as glass catching light -- which is exactly
   * what it was doing.
   */
  facetSpin: readonly [base: number, spread: number];
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
   * NOT an eye, deliberately, and that is why he has this field at all.
   *
   * The composite is shared with Jarvis, so Ultron has to say what he wants from
   * it. His brief is a crystalline cloud with no iris, so the lens radius is 0 and
   * the aura width is the pre-eye value of 60 -- which reproduces exactly the
   * centre he had before the eye existed.
   */
  eye: readonly [pupil: number, iris: number, lens: number, auraWidth: number];
  /**
   * The baked membrane layer: gain on a pre-rendered loop of the organic
   * outer mass — membranes, crust plates, heavy slow structure — composited
   * additively under the live passes, voice on the second component. Zero
   * ships. See canvas/latticeLayer.ts.
   */
  lattice: EnergyRamp;
  /** The video channel's effects rack, as on Jarvis: blur / sat / glow. */
  latticeBlur: number;
  latticeSat: number;
  latticeGlow: number;
  /** Playback speed of the footage itself. 1 ships. */
  latticeSpeed: number;
  /**
   * How big the whole composite sits in the frame: one scale on the live body
   * AND the baked layer together, so they never drift apart. 1 ships.
   */
  presence: number;
  /**
   * Three concentric clouds spread into arms. Jarvis leaves this at 0.
   *
   * 0.3, not 1.0. At 1.0 the arms reach far enough to read as flares around the
   * edge; at 0 he is Jarvis in blue, and the references separate the two by
   * silhouette as much as by colour.
   */
  /** How the voice reverberates. See JarvisTuning.reverb. */
  reverb: readonly [speed: number, spacing: number, decay: number, reach: number];
  /** The iris at the heart of the cloud. See JarvisTuning.irisGain. */
  irisGain: EnergyRamp;
  irisRadius: readonly [inner: number, outer: number];
  irisFil: readonly [lit: number, width: number];
  irisFlow: readonly [speed: number, contrast: number];
  /**
   * How far the three bands reach along their own axes.
   *
   * 0.3, not 1.0. At 1.0 the arms reach far enough to read as flares around the
   * edge; at 0 he is Jarvis in blue, and the references separate the two by
   * silhouette as much as by colour.
   */
  petal: number;
  /**
   * How far the mass departs from a sphere, and how fast that shape churns.
   *
   * The reference is not an orb: it is a sprawling irregular cloud with lobes and
   * voids, and a spherical silhouette is the single thing that most makes a body
   * read as a ball of particles rather than as a mind. Held apart from `petal`
   * because they are different shapes -- petal grows regular arms round an iris,
   * this makes the outline itself irregular.
   */
  cloud: readonly [amount: number, churn: number];
  veinLimb: LimbMix;
  crackLimb: LimbMix;
  facetLimb: LimbMix;
}

export const ULTRON_TUNING: UltronTuning = {
  dendriteGain: [4.86, 2.52],
  dendrite: [0.34, 0.52, 0.78, 0.035],
  dendriteTip: [0.9, 0.22],
  bead: [9.0, 0.16],
  signal: [0.55, 2.4, 5.5],
  arc: [0.82, 2.5, 0.42, 0.85],
  outerShell: [1.45, 0.20, 0.30],
  facetSpin: [0.13, 0.40],
  swirl: [0.26, 0.40],
  veinGain: [0.792, 0.72],
  veinStreak: [0.110, 0.085],
  crackGain: [1.224, 0.936],
  crackRange: 0.19,
  facetGain: [1.296, 0.936],
  facetSize: 0.020,
  core: [0.655, 0.857],
  eye: [1, 1, 0, 60],
  reverb: [1.7, 0.26, 0.8, 1.4],
  // Tighter than Jarvis's and dimmer: his is the subject of the frame, this is the
  // thing at the middle of a much larger mass.
  irisGain: [0.5, 0.32],
  irisRadius: [0.04, 0.19],
  irisFil: [0.8, 0.004],
  irisFlow: [0.16, 0.7],
  petal: 0.3,
  cloud: [0.34, 1.0],
  veinLimb: [0.30, 0.95],
  crackLimb: [0.36, 0.88],
  facetLimb: [0.28, 0.95],
  lattice: [0, 0],
  latticeBlur: 0,
  latticeSat: 1,
  latticeGlow: 0,
  latticeSpeed: 1,
  presence: 1,
};
