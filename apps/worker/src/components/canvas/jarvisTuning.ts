import type { EnergyRamp, LimbMix } from "./bodyRamp";

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
  /** The OUTER inscription band. The four glyph rings split into two
   *  independent pairs — these dials own rings 2 and 3, the glyph* dials own
   *  0 and 1 — because one bank driving four rings read as two layers that
   *  could not be told apart on the desk. */
  glyphBGain: EnergyRamp;
  glyphBRadius: readonly [inner: number, outer: number];
  glyphBSize: readonly [height: number, width: number];
  glyphBSpin: readonly [speed: number, stagger: number];
  glyphBDensity: readonly [lit: number, variance: number];
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
   * Debris clustering: x blends between the uniform body and one with clumps
   * and voids, y is the cluster scale. Zero ships: the film's sphere is
   * clustered, the product's default body stays the even one it always was.
   */
  clump: readonly [strength: number, scale: number];
  /**
   * Fake depth of field on the circuit shards: x how much a far-side chip
   * swells, y how much it dims. Zero ships.
   */
  focus: readonly [farSwell: number, farDim: number];
  /**
   * The baked lattice layer: gain on a pre-rendered hubs-and-spokes loop
   * composited additively UNDER the live passes, with the second component
   * riding the voice like every other gain. The loop carries film-density
   * structure no real-time pass can afford; the live body carries the pulse.
   * Zero ships: without a video loaded the layer draws nothing regardless.
   */
  lattice: EnergyRamp;
  /** The video channel's effects rack: motion blur (a tangential smear along
   *  the footage's own travel), saturation, and a four-tap glow. 0/1/0 ships:
   *  neutral until the bench decides otherwise. */
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
  // The old four-ring span was [0.66, 0.94]; each band keeps its two rings
  // exactly where they were: A at 0.66/0.753, B at 0.847/0.94.
  glyphRadius: [0.66, 0.753],
  glyphSize: [0.055, 0.008],
  glyphSpin: [0.026, 0.55],
  glyphDensity: [0.72, 0.55],
  glyphBGain: [0.34, 0.22],
  glyphBRadius: [0.847, 0.94],
  glyphBSize: [0.055, 0.008],
  glyphBSpin: [0.026, 0.55],
  glyphBDensity: [0.72, 0.55],
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
  clump: [0, 2.6],
  focus: [0, 0],
  lattice: [0, 0],
  latticeBlur: 0,
  latticeSat: 1,
  latticeGlow: 0,
  latticeSpeed: 1,
  presence: 1,
  eye: [1, 1.5, 0.34, 15],
  drawLimb: [3, 3],
  linkLimb: [3, 3],
};
