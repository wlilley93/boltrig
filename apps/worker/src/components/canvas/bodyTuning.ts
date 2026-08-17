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
   * The distant outer sphere: radius, population fraction, brightness.
   *
   * Ultron's birth builds one -- the crystalline mass blooms and then the outer
   * circle takes shape around it, lighter and further out. Jarvis ships with the
   * fraction at ZERO, so his look is untouched until somebody decides where his
   * shells belong; the machinery is shared, the decision is not.
   */
  outerShell: readonly [radius: number, fraction: number, gain: number];
  /**
   * THE EXTERIOR WHEELS, and they were switched off.
   *
   * Both references ask for them -- Ebb's "audio-reactive exterior rings of data
   * that circumscribed the hologram, evoking spinning hard drive platters and
   * reel to reel data tape", Territory's rings rotating around a spherical base
   * with code moving between the layers -- and the reference frame reads them as
   * a feathered crest sweeping around the outside of the eye.
   *
   * They came off because bright arcs turning at the limb read as solar flares.
   * That was a GAIN and a SPEED problem, not a reason to have no crest: they are
   * back at a fraction of the brightness the field carries, turning slowly
   * enough to be an orbit rather than a spin.
   */
  ringGain: EnergyRamp;
  /** x turns the wheels, y precesses the arrangement. Slow is the whole point. */
  ringSpin: readonly [spin: number, precess: number];
  /**
   * Innermost and outermost ring radius, as a fraction of the body.
   *
   * They used to be fixed at 0.34 to 0.66 -- under a shell that sits at 0.88 to
   * 0.98, so the bands were buried in the field rather than wrapping it. The
   * reference has them sweeping the silhouette and reaching out to the faint
   * outer sphere, which is where they are now.
   */
  ringRadius: readonly [inner: number, outer: number];
  /** Beam cross-section as a fraction of each ring's radius. */
  ringBeam: number;
  /**
   * How often a crest fades in and out, in cycles per second.
   *
   * A knob of its own rather than a multiple of the precession rate, which is what
   * it was. Precession ships at 0.016, so "coming and going" had a period of about
   * a hundred seconds and read as a fixed arrangement. Around 0.09 gives an
   * eleven-second life, which is slow enough to feel like orbiting and quick
   * enough that the set of visible crests plainly changes while you watch.
   */
  ringLife: number;
  /**
   * How many separate beams each wheel is cut into, and how much of the gap
   * between them each one fills.
   *
   * A closed hoop reads as a mounted part. The reference has PIECES travelling
   * past each other, so a wheel is a few beams floating round the edge and the
   * circumference is deliberately incomplete. Coverage of 1.0 closes it back up,
   * which is the old look and is available if it turns out to be wanted.
   */
  ringArc: readonly [beams: number, coverage: number];
  /**
   * Half-width of a beam in clip space, before the perspective scale.
   *
   * The beams were LINES -- one pixel wide, whatever the comment beside them
   * called them -- so there was no across to shade and nothing could make them
   * read as three-dimensional. They are quads now and this is the number that
   * decides bar versus hairline.
   */
  ringWidth: number;
  /**
   * THE GLYPH RINGS, on a channel of their own.
   *
   * They used to ride the wheel pass, which is why they vanished when the wheels
   * became floating beams: one gain and one spin governing an object that moves and
   * an inscription that does not. Separating them is what makes both adjustable.
   *
   * The gap between layers is meant to be EMPTY -- the reference has almost nothing
   * between them but the glow of the layers themselves -- so these stay thin and
   * quiet, and nothing else should be added to fill that space.
   */
  /**
   * THE IRIS, which is what the centre is now made of.
   *
   * The neural links are still in the tree and still work, but they ship at zero:
   * they joined whichever particles the simulation happened to leave adjacent, so
   * their structure was wherever the field drifted rather than anywhere meaningful,
   * and over a bright centre that reads as clutter. Radial filaments point AT the
   * nucleus from every angle, which is what makes the figure an eye.
   */
  irisGain: EnergyRamp;
  /** Inner and outer edge of the iris. Inside the inner edge is the pupil. */
  irisRadius: readonly [inner: number, outer: number];
  /** How many filaments are lit, and how wide each is. */
  irisFil: readonly [lit: number, width: number];
  /** Outward flow speed, and how pronounced the travelling band is. */
  irisFlow: readonly [speed: number, contrast: number];
  glyphGain: EnergyRamp;
  /** Innermost and outermost layer radius. Concentric, not scattered. */
  glyphRadius: readonly [inner: number, outer: number];
  /** Mark height and width. Both small: inscriptions, not bars. */
  glyphSize: readonly [height: number, width: number];
  /** Rotation rate, and how much each layer counter-rotates against the last. */
  glyphSpin: readonly [speed: number, stagger: number];
  /** What fraction of the marks are lit, and how hard the lit ones vary. */
  glyphDensity: readonly [lit: number, variance: number];
  /** How many great circles. Six read as a sphere of wheels; three as a skirt. */
  rings: number;
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
  /**
   * How far a connection bows off the straight line, and how fast the bow
   * travels.
   *
   * The pathways were straight segments, which reads as wiring. A nervous system
   * wanders, so the middle of each connection is pushed off the chord by a curl
   * sample on its OWN clock -- a pathway's squiggle has nothing to do with how
   * fast the field is turning over, and tying them together made one of them
   * untunable.
   */
  linkBow: readonly [amount: number, speed: number];
  /**
   * How the voice reverberates: speed, echo spacing, decay, reflecting radius.
   *
   * Per mode, because a body that rings the same way when idle as when speaking is
   * not answering the voice -- standby wants a slow, almost-still swell and speech
   * wants the whole thing ringing. The reflecting radius is what the front bounces
   * off, so it should sit at or just past the silhouette.
   */
  reverb: readonly [speed: number, spacing: number, decay: number, reach: number];
  /** The filaments. */
  /**
   * The INNER layer: brightness, trail and silhouette of the core cloud.
   *
   * `drawGain`, `streak` and `drawLimb` keep their names because renaming them
   * would churn every preset and every saved bench state for no gain -- but they
   * describe the inner layer only. The outer shell has its own four fields below.
   */
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
  /**
   * THE OUTER LAYER, as its own set rather than a fraction of the inner one.
   *
   * `outerShell` still says WHERE it is and how many particles are on it; these
   * say what it LOOKS like. Sharing the interior's gain and streak was the reason
   * the shell never read as a distant surface: a surface further away is dimmer,
   * finer and shorter-trailed, and none of that was expressible.
   */
  outerGain: EnergyRamp;
  outerStreak: EnergyRamp;
  outerLimb: LimbMix;
  /**
   * How much slower the outer layer drifts, as an offset from 1.
   *
   * Negative is slower. It reaches the SIMULATION rather than the draw, because a
   * distant thing moving at the same rate as a near thing is the single strongest
   * cue that they are at the same distance -- and scaling it at draw time would
   * put the streaks off the path the particles actually take.
   */
  outerPace: number;
  starburst: number;
  /**
   * The eye, after familiar.frag's heart -- pupil, iris, and the lens ring.
   *
   * Two stacked gaussians were already here and they made a bright BLOB. What
   * familiar has and this did not is the third term: a thin ring at a fixed
   * radius, which she calls the pupil of the thing. That ring is what turns a
   * glow into an eye, because an eye is not a bright patch, it is a bright patch
   * with a boundary. Her ratio is also far wider than this pass had -- a broad
   * aura around a compact core rather than two nearly-equal lobes.
   *
   * x scales the pupil, y the iris aura, z is the lens ring's radius.
   */
  eye: readonly [pupil: number, iris: number, lens: number, auraWidth: number];
  /** The streaks' silhouette. An order of magnitude, not a factor of three. */
  drawLimb: LimbMix;
  /** The network's silhouette. Without it the web fills the see-through middle. */
  linkLimb: LimbMix;
}

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

/** What ships. The bench overrides a copy; nothing mutates this. */
export const JARVIS_TUNING: JarvisTuning = {
  outerShell: [1.45, 0.34, 0.46],
  ringGain: [0.8, 0.42],
  ringSpin: [0.016, 0.005],
  ringRadius: [1.02, 1.32],
  ringBeam: 0.085,
  ringLife: 0.05,
  ringArc: [1.3, 0.82],
  ringWidth: 0.145,
  irisGain: [0.85, 0.5],
  irisRadius: [0.05, 0.26],
  irisFil: [0.88, 0.005],
  irisFlow: [0.14, 0.65],
  // The links are superseded by the iris. Kept at zero rather than deleted: the
  // pass is sound and a network may be wanted on another body.
  glyphGain: [0.34, 0.22],
  glyphRadius: [0.66, 0.94],
  glyphSize: [0.055, 0.008],
  glyphSpin: [0.026, 0.55],
  glyphDensity: [0.72, 0.55],
  rings: 2,
  swirl: [0.115, 0],
  linkGain: [0, 0],
  reverb: [1.9, 0.22, 0.85, 1.35],
  linkBow: [0.158, 0.2],
  linkRange: 0.6,
  drawGain: [1, 1],
  streak: [0.004, 0],
  shardGain: [1, 0.475],
  shardSize: 0.003,
  shardStride: 12,
  core: [1, 1],
  outerGain: [1.15, 0.55],
  outerStreak: [0.0018, 0],
  outerLimb: [1.9, 2.3],
  outerPace: -0.55,
  starburst: 1,
  eye: [1, 1.5, 0.34, 15],
  drawLimb: [3, 3],
  linkLimb: [3, 3],
};

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
};

/**
 * The heart, OSCILLATING with the voice rather than merely scaled by it.
 *
 * `ramp` gives a core that rises while speaking and then sits there, which reads
 * as a lamp on a dimmer. The half that answers to energy is the half that should
 * MOVE, so it is modulated by the voice bands themselves -- the body pulses with
 * what is being said, rather than on a timer that happens to be running.
 *
 * The resting half is untouched. A silent body keeps exactly the heart its base
 * gives it; only the part a voice added is allowed to flicker.
 */
export function pulsedCore(core: EnergyRamp, energy: number, bands: Float32Array): number {
  // Weighted toward the LOW bands, which is where a voice's amplitude envelope
  // lives. Weighting the highs equally makes the heart chatter on sibilance,
  // which reads as a fault rather than as speech.
  const weights = [0.26, 0.22, 0.16, 0.12, 0.09, 0.07, 0.05, 0.03];
  let sum = 0;
  for (let i = 0; i < 8 && i < bands.length; i += 1) sum += bands[i] * weights[i];
  return core[0] + core[1] * energy * (0.45 + 0.85 * Math.min(1, sum));
}

/** `base + perEnergy * energy`, the one place the ramp is evaluated. */
export function ramp(value: EnergyRamp, energy: number): number {
  return value[0] + value[1] * energy;
}
