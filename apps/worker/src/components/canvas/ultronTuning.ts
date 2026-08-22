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
  /** A slight bounce of the whole composite: amplitude (UV) and speed (Hz),
   *  with trails as ghost taps of where the body just was. [0,0] and 0 ship:
   *  perfectly still until raised. */
  bounce: readonly [amount: number, speed: number];
  bounceTrail: number;
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
  /**
   * The azimuthal anchoring pull, dissolving the vein-density combs.
   *
   * The radial spring fixes only |p|; nothing restored a particle's BEARING, so
   * the on-shell tangential flow (compressible on the sphere) random-walked the
   * density into bright vertically-striated knots that survived facets=0 and
   * petal=0 -- they were particle mass, not a pass. Each particle now feels a
   * gentle tangential pull toward its own hashed bearing; the curl still swirls
   * everything locally, but coverage is uniform at equilibrium. Zero is the
   * pre-dial body, byte for byte.
   */
  homePull: number;
  /**
   * Pre-knee highlight compression at the composite, 0 = identity.
   *
   * Wherever thousands of additive streaks stack, the filmic knee saturates and
   * the hue is gone -- a knot reads as a white slab. Reinhard on the linear
   * scene keeps dense regions blue and graded while thin filaments pass nearly
   * untouched.
   */
  knee: number;
  /** The membrane's brightness: base, and what a voice adds. */
  membraneGain: readonly [base: number, perVoice: number];
  /**
   * The analytic shell itself: radius as a scale on the body radius, the
   * silhouette feather, and the interior veil.
   *
   * The volumetric surface the reference has and line passes cannot make: bright
   * at the limb by chord length, faint through the middle, silhouette displaced
   * by the same cloudy() lobes that shape the particle mass. The veil is the
   * through-the-body glow -- too high and he is fog again, which is the failure
   * this whole program exists to end, so it starts low.
   */
  membrane: readonly [radius: number, feather: number, veil: number];
}

/**
 * What ships: "Ultron final 1800" — the look mixed and saved on the character
 * bench (2026-08-21, all seven slots), standby slot verbatim.
 *
 * Unlike Jarvis's canon this one runs NO continuous sweeps: the bench rack was
 * empty when it was saved, so the living motion is the membrane film (lattice
 * 2.2 with the deck's per-mode loops), the bounce, and ULTRON_SPEECH riding
 * the voice. The veins, cracks and heart sit at zero at rest and bloom only
 * on a syllable.
 */
export const ULTRON_TUNING: UltronTuning = {
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
  petal: 0,
  cloud: [0.3, 0.7],
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
  bounce: [0.037, 0.35],
  bounceTrail: 0,
};
