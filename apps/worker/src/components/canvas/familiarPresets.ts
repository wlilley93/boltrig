import { FAMILIAR_TUNING, type FamiliarTuning } from "./familiarTuning";
import type { FamiliarMode } from "../familiar/FamiliarState";

/**
 * WHERE THE FAMILIAR ARRIVES FROM — and it is deliberately almost nothing.
 *
 * Jarvis and Ultron are born: a field condenses, a tree grows. She is NOT, and
 * that is a decision already taken in the renderer, where the aperture is
 * pinned open with the note "Familiar does not arrive, she is there". Giving
 * her a dramatic draw-in here would quietly reverse that by the back door.
 *
 * So the arrival is a settling rather than a birth: a fraction smaller, a shade
 * dimmer, gaze away, and the inner life not yet wandering. Easing from it looks
 * like a creature noticing it is being looked at. It stays a real preset rather
 * than a copy of standby because the bench's Play draw-in has to have something
 * to ease FROM, and a slot that is secretly the same as another slot is a
 * control that appears to do nothing.
 */
export const FAMILIAR_ARRIVAL: FamiliarTuning = {
  ...FAMILIAR_TUNING,
  composition: [0.30, 0.5],
  gaze: [0, 1],
  arousalLift: [0, 0],
  idlePulse: [0, 0.49],
  daylight: [0.10, 0.60],
  // Long tau, long dwell: the wander has not started yet, so the first mood
  // arrives as a drift rather than as a jump on the first frame.
  wander: [9, 40],
  gesture: [40, 120],
  lattice: [0, 0],
  latticeBlur: 0,
  latticeSat: 1,
  latticeGlow: 0,
  presence: 1,
};

/**
 * THE FAMILIAR PER MODE.
 *
 * Two constraints shaped this table and they pull against each other.
 *
 * The first is that these five states have to be TOLD APART at a glance, in a
 * porthole 96 pixels across, by someone who is reading text and not looking at
 * her. That argues for making each one loud.
 *
 * The second is that she is one creature. Jarvis can put four words on an arc
 * and change what the machine is doing in type; she has no labels at all, so
 * every state has to be legible as a change of BEHAVIOUR — where she is
 * looking, how fast she breathes, whether she is following something. Loudness
 * spent on brightness alone would give five versions of the same being turned
 * up and down, which is the failure bodyEmotion's header names.
 *
 * So the differences here are mostly in gaze, pace and what drives the body,
 * and only incidentally in level.
 */
export const FAMILIAR_MODES: Record<FamiliarMode, Partial<FamiliarTuning>> = {
  /**
   * IDLE, AND IT HAS ITS OWN BUSINESS. Gaze away, the slowest wander, gestures
   * at the shipped rate. Nothing drives the body but its own inner life, which
   * is the state she spends almost all of her time in and therefore the one
   * worth protecting from every clever idea about the other four.
   */
  standby: {
    gaze: [0, 1],
    arousalLift: [0, 0],
    idlePulse: [0, 0.49],
  },

  /**
   * LISTENING: turned toward you, and following your voice at a fraction of
   * speaking gain.
   *
   * The gain is the whole judgement here. Wired at speaking levels the mic
   * makes her mouth your words back at you, which is uncanny in the bad way;
   * wired at zero she is indistinguishable from idle while you are talking to
   * her, which was the actual shipped behaviour and the gap this closes. A
   * fifth of the drive, with attention nearly full, reads as attending.
   *
   * The gestures are pulled in close: a creature being spoken to nods and
   * looks, and the thirty-to-ninety-second ambient rate is far too sparse to
   * land inside one sentence.
   */
  listening: {
    gaze: [1, 1],
    listen: [0.22, 0.92],
    arousalLift: [0.10, 0],
    idlePulse: [0, 0.49],
    wander: [4, 20],
    gesture: [6, 16],
  },

  /**
   * THINKING: inward. Gaze off you, the pulse slow and deep, the light down.
   *
   * The distinction from working is the one users actually need — thinking
   * means "your input landed and I am on it", working means "I am doing the
   * thing" — and it is drawn here as INWARD vs OUTWARD rather than as slow vs
   * fast, because two speeds of the same pulse are not a distinction anybody
   * reads at porthole size.
   */
  thinking: {
    gaze: [0.15, 1],
    arousalLift: [0.12, 0],
    idlePulse: [0.22, 0.22],
    daylight: [0.12, 0.62],
    wander: [7, 40],
    gesture: [45, 120],
  },

  /**
   * WORKING: outward and busy, the shipped oscillator.
   *
   * This is the state the old code produced for every non-speaking turn, so
   * these are the shipped numbers exactly. It keeps the whole table honest: one
   * preset here reproduces what shipped, and the others can be judged against
   * it rather than against memory.
   */
  working: {
    gaze: [0.4, 1],
    arousalLift: [0.25, 0],
    idlePulse: [0.15, 0.49],
    gesture: [20, 60],
  },

  /**
   * SPEAKING: the voice drives everything, and the gate is open.
   *
   * THE HIGHS ARE LIFTED AND THE LEVEL IS NOT. Consonants belong on the surface
   * — that is what the shader does with uAudio.w — and letting them into the
   * level channel instead is what made every sibilant read as a shout. The lows
   * are pulled back a touch for the same reason from the other end: at unity
   * they pressurise the nucleus so hard that a normal speaking voice sits at
   * the top of the range with nowhere left to go when she raises it.
   *
   * The gate's floor is the number that stops the twitching between words. It
   * is set from the measured inter-word floor of the playback analyser rather
   * than by taste; the knee above it is taste.
   */
  speaking: {
    voiceLevel: [0, 0.95],
    voiceLow: [0, 0.85],
    voiceMid: [0, 1],
    voiceHigh: [0, 1.15],
    voiceEnv: [0.07, 0.34],
    voiceGate: [0.06, 0.10],
    beat: [1.15, 0.16],
    gaze: [1, 1],
    arousalLift: [0, 0.22],
    idlePulse: [0, 0.49],
    gesture: [25, 70],
  },

  /**
   * ERROR: the call dropped, or the turn failed.
   *
   * Held tension, the light down, and gaze off — a creature that has just been
   * cut off, not a serene one. The renderer fires a single recoil into it, so
   * the transition is an event and the state that follows is the consequence;
   * a held pose with no movement into it reads as a rendering bug.
   *
   * Nothing here is red. Irritation is the shader's one colour term and it
   * means the being is annoyed WITH YOU, which is not what a dropped websocket
   * is. Getting that wrong would make an infrastructure failure look like a
   * mood.
   */
  error: {
    gaze: [0, 0.2],
    arousalLift: [0, 0],
    idlePulse: [0.05, 0.14],
    daylight: [0.08, 0.35],
    wander: [3, 25],
    gesture: [10, 30],
    errorTone: [0.75, 0.28],
  },
};

/** A mode's target: the settled look with that mode's deltas laid over it. */
export function familiarModeTuning(mode: FamiliarMode): FamiliarTuning {
  return { ...FAMILIAR_TUNING, ...FAMILIAR_MODES[mode] };
}
