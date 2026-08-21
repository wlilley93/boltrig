/**
 * The Familiar's dials — every host-side number that decides how she moves.
 *
 * WHY THIS EXISTS AT ALL, when Jarvis and Ultron have one for a different
 * reason. Their tuning describes DRAW PASSES: how bright a ring is, how long a
 * trail runs. The Familiar's look is one vendored 2,000-line shader that must
 * not be edited here (it flows from boltrig-familiar, never the reverse), so
 * there is nothing of that kind to tune. What IS tunable is everything the HOST
 * decides before the uniforms are pushed: how a voice becomes movement, how
 * fast the inner life wanders, how far a mode lifts her.
 *
 * Those numbers were literals scattered across the renderer and the drive —
 * 0.09, 0.40, 0.35 + 0.55, 30_000..90_000 — and a literal in a frame loop is a
 * decision nobody can revisit by eye. Gathering them here is what puts the
 * Familiar in the shader bench beside the other two bodies, with the same
 * sliders and the same LFO sweeps, and it is the only way the speaking
 * behaviour was ever going to be judged rather than guessed.
 *
 * EVERY FIELD IS A NUMBER OR AN ARRAY OF NUMBERS. The bench generates its panel
 * from the struct, so a field of any other shape becomes a control it cannot
 * draw. That constraint is worth keeping: it also means a tuning is JSON, which
 * is what makes Copy settings and a shareable link possible.
 */

/** `base + perVoice * energy`, the same vocabulary the other two bodies use. */
export type VoiceRamp = readonly [base: number, perVoice: number];

export interface FamiliarTuning {
  /**
   * uAudio.x — the overall drive. In the shader this pressurises the heart and
   * lifts the halo, so it is the channel a listener reads as "she is talking".
   */
  voiceLevel: VoiceRamp;
  /** uAudio.y — the lows. These pressurise the nucleus and drive the breath. */
  voiceLow: VoiceRamp;
  /** uAudio.z — the mids. These move the interior shells. */
  voiceMid: VoiceRamp;
  /**
   * uAudio.w — the highs. These light the SURFACE, which is why consonants
   * should reach here and not into the level channel: a sibilant that inflates
   * the nucleus reads as a shout.
   */
  voiceHigh: VoiceRamp;
  /**
   * The envelope, in seconds: attack then release.
   *
   * ASYMMETRIC ON PURPOSE and the asymmetry is the whole point — see
   * familiarDrive's header. Fast up keeps a syllable on time; slow down stops
   * the body flickering at the analyser's frame rate. A symmetric envelope slow
   * enough to be calm also arrives late, and a body moving after its own voice
   * is worse than one moving too much.
   */
  voiceEnv: readonly [attack: number, release: number];
  /**
   * The silence gate: below `floor` there is no voice, and `knee` is how far
   * above it the drive reaches full.
   *
   * MEASURED NEED, not a precaution. The playback analyser never reads zero —
   * room tone, an AEC residual and the codec's own noise floor all sit a few
   * percent above it — so without a gate the being twitches continuously
   * through every silence in a sentence, which reads as a nervous tic rather
   * than as speech. A gate rather than a subtraction because the quiet end is
   * where the twitch lives and the loud end must not be scaled at all.
   */
  voiceGate: readonly [floor: number, knee: number];
  /**
   * uBeat: the impulse channel. Gain, then decay in seconds.
   *
   * NOT SMOOTHED BY THE ENVELOPE, and not raw either. The shader multiplies
   * this hard in five places, so a raw spectral-flux value sampled at ~30Hz
   * strobes — the flux is a per-frame difference and it collapses to zero the
   * moment a syllable is sustained. Instant attack with an exponential tail
   * gives what a syllable actually looks like: it lands, then it rings out.
   */
  beat: readonly [gain: number, decay: number];
  /**
   * LISTENING, which is not quiet speaking.
   *
   * x is how far the incoming voice moves the body, y is how far attention
   * rises while someone is talking to her. The drive is deliberately a fraction
   * of the speaking one: she should visibly REGISTER you without appearing to
   * mouth your words, which is what happens if the mic is wired to uAudio at
   * anything like speaking gain.
   */
  listen: readonly [drive: number, attention: number];
  /**
   * uGaze at rest, and while engaged. 1 is watching, 0 is looked away.
   *
   * Two numbers rather than a boolean because the interesting question is how
   * present she is when nothing is happening, and that is a judgement made by
   * looking at her, not by reading the enum.
   */
  gaze: readonly [idle: number, engaged: number];
  /** How far a working turn and a spoken turn lift arousal above the baseline. */
  arousalLift: readonly [working: number, speaking: number];
  /**
   * The idle oscillator: depth and rate in Hz.
   *
   * What drives the body during a WORKING turn, where there is no voice to
   * follow. It is a stand-in for embodiment rather than embodiment, and it is a
   * dial so that the difference between "thinking" and "twitching" can be found
   * by eye instead of argued about.
   */
  idlePulse: readonly [depth: number, rate: number];
  /**
   * uScaleDock and uFitScale: how big she is in her porthole, and the largest
   * radius that porthole can show without clipping her halo and genotype
   * corners back into a circle.
   */
  composition: readonly [scaleDock: number, fitScale: number];
  /** uDay: the floor and span of the local-time warmth curve. */
  daylight: readonly [floor: number, span: number];
  /** The wander: ease time constant, and seconds between mood changes. */
  wander: readonly [tau: number, dwell: number];
  /** Seconds between ambient gestures, as a range. */
  gesture: readonly [gapMin: number, gapMax: number];
  /**
   * What a FAILURE looks like: tension, and how far the light drops.
   *
   * A body with no failure expression is the gap orb-ui names as an explicit
   * `error` state and every hand-rolled orb forgets. Worker maps a dropped call
   * to "not working any more", so before this the being simply went calm while
   * the page said the call had died — the one moment she must not look serene.
   */
  errorTone: readonly [tension: number, luminosity: number];
  /**
   * The baked orb layer: gain on a pre-rendered loop of her light — halos,
   * filaments, the hexagonal ghosts — RECOLOURED live by her mood, because her
   * colour is an emotion and footage cannot know tonight's. Second component
   * rides the voice. Zero ships. See canvas/latticeLayer.ts.
   */
  lattice: readonly [gain: number, byVoice: number];
  /** The video channel's effects rack, as on the others: blur / sat / glow. */
  latticeBlur: number;
  latticeSat: number;
  latticeGlow: number;
  /**
   * How big the whole composite sits in the frame: one scale on the live body
   * AND the baked layer together, so they never drift apart. 1 ships.
   */
  presence: number;
}

/**
 * THE SHIPPED NUMBERS: exactly what the Familiar did before she had dials.
 *
 * Every value here is lifted from the literal it replaced, so introducing the
 * struct changed nothing on screen — the same property every addition to a
 * shared body in this tree has had to have. The mode table in familiarPresets
 * is where the new behaviour lives, and it can be judged against this.
 */
export const FAMILIAR_TUNING: FamiliarTuning = {
  voiceLevel: [0, 1],
  voiceLow: [0, 1],
  voiceMid: [0, 1],
  voiceHigh: [0, 1],
  voiceEnv: [0.09, 0.40],
  // Floor at zero SHIPS THE OLD BEHAVIOUR, which is the point of this struct's
  // defaults. The gate is opened in the speaking preset, where it can be judged.
  voiceGate: [0, 0.02],
  beat: [1, 0.18],
  listen: [0.22, 0.9],
  gaze: [0, 1],
  arousalLift: [0.25, 0],
  idlePulse: [0.15, 0.49],
  composition: [0.34, 0.5],
  daylight: [0.15, 0.85],
  wander: [6, 32],
  gesture: [30, 90],
  errorTone: [0.75, 0.28],
  lattice: [0, 0],
  latticeBlur: 0,
  latticeSat: 1,
  latticeGlow: 0,
  presence: 1,
};
