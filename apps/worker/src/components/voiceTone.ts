// Spectral shaping for spoken audio: what the voice needs, measured, plus what
// a character asks for, declared.
//
// TWO STAGES, AND THE SPLIT IS THE WHOLE DESIGN.
//
//   TILT is measured and automatic. Every voice out of this TTS is short of
//   high frequencies, and by wildly different amounts. Measured 2026-08-15,
//   5-8 kHz energy relative to the 300-1000 Hz body:
//
//       vera    -23.7 dB   (catalogue voice, not a clone)
//       joi     -26.6 dB   but -43.2 at 8-11k: a 16.6 dB cliff
//       jarvis  -34.3 dB
//       maya    -41.0 dB   seventeen dB duller than vera
//
//   A high shelf improved all four by ear, including the one that is not a
//   clone. So this is a property of the output, not a bad reference, and it
//   cannot be a per-voice table: VERA HAS NO BUNDLE. She is a name in the
//   runtime catalogue with nothing to declare on, and so is every voice a user
//   picks from it later. Configuration cannot reach her. Measurement can.
//
//   TONE is declared and optional. A character may ask for shaping that is
//   about who they are rather than about a deficiency -- presence for
//   consonant clarity, a cut where a voice sounds boxy. That is not derivable,
//   because it is a judgement rather than a defect, so the character brings it
//   and absence means none. It never substitutes: no declaration yields the
//   measured stages alone, exactly as for a catalogue voice.
//
// The corner frequency is why tilt cannot be one constant either. Vera's
// sibilance peaks at 6 kHz, so a 6 kHz shelf boosts her "sss" head-on while
// the same filter merely adds air to Maya. The corner is therefore placed
// ABOVE each utterance's own measured sibilance peak.
//
// This module is pure and knows nothing about Web Audio. It returns a
// description of a chain; the caller builds the nodes. That keeps it testable
// without a browser and keeps the policy in one readable place.

// TWO DEFICITS, NOT ONE, because voices fail in two different ways and a
// measure that sees only one is blind to half of them.
//
//   A CLIFF: sibilance present, nothing above it. Joi -- 5-8k at -26.6 but
//   8-11k at -43.2. The gap is the defect; her overall level is fine.
//
//   A DEFICIT: the whole top end low but evenly so. Maya -- 5-8k at -41.0,
//   seventeen dB below Vera, with a gap of only 1.3. Nothing wrong with her
//   shape; there is simply almost no high end to shape.
//
// An earlier version measured the cliff alone. It derived a correct +12 dB for
// Joi and NOTHING AT ALL for Maya and Vera -- two of the four voices a
// listening pass had just said were improved by a shelf. Whichever deficit
// asks for more gain wins.

/** Where a voice should sit: air within this of the sibilant band. */
export const TARGET_AIR_GAP_DB = 3;

/**
 * Sibilant-band level, relative to the body, that a voice should reach.
 *
 * From Vera, measured at -23.7 dB. She is the reference deliberately: she is
 * the only one of the four that is NOT a clone, she needed no correction by
 * ear, and she is what the engine sounds like before cloning takes the top end
 * off. Lifting the clones toward her is restoring what cloning removed rather
 * than inventing a house sound.
 */
export const TARGET_SIBILANT_DB = -24;

/**
 * Bounds on the automatic correction. It fixes a tilt; it is not an effect.
 *
 * Raised from 12 to 16 on 2026-08-15, by ear. At 12 both Maya and Joi sat ON
 * the clamp -- Maya's measured deficit is 17.0 dB -- so the ceiling was setting
 * their correction rather than the measurement, which is the wrong thing to be
 * in charge. Sixteen lets the measurement decide for every voice seen so far
 * except Maya, who remains one decibel short of what she asks for.
 *
 * It is not unbounded, and should not become so: past this a shelf amplifies
 * whatever noise sits above the sibilant band as much as any signal, and the
 * failure mode is hiss that no amount of level matching hides.
 */
export const MAX_TILT_GAIN_DB = 16;
export const MIN_TILT_GAIN_DB = 0;

/** A character's declared shaping may not exceed this in either direction. */
export const MAX_TONE_GAIN_DB = 12;

const BODY = [300, 1000] as const;
const SIBILANT = [5000, 8000] as const;
const AIR = [8000, 11000] as const;

/** Narrow bands the sibilance peak is searched over. */

import { bandDb, sibilancePeakHz } from "./voiceSpectrum";

export { bandDb, sibilancePeakHz };

export type FilterKind = "peaking" | "highshelf" | "lowshelf";

export interface FilterSpec {
  type: FilterKind;
  frequency: number;
  gainDb: number;
  q?: number;
  /** Why this filter exists. Required on declared tone; set by us on tilt. */
  reason: string;
}

const dB = (a: number): number => (a > 0 ? 20 * Math.log10(a) : Number.NEGATIVE_INFINITY);
const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));

/**
 * The automatic tilt correction for this audio, or null when none is wanted.
 *
 * Null rather than a 0 dB filter so the caller builds no node at all: a voice
 * that already has air should be left completely alone, not routed through an
 * identity filter that only adds a place for a bug to live.
 */
/**
 * Where the shelf corners, and the sentence saying why.
 *
 * THE CORNER FOLLOWS WHICH DEFICIT FIRED, and getting this wrong made the
 * correction incoherent in a way no unit test could see. An end-to-end run
 * caught it: the level deficit is MEASURED in the sibilant band, but the corner
 * was always placed above the sibilance peak -- so a dull voice was told it
 * needed 10 dB in 5-8 kHz and then given a shelf starting at 8 kHz, which
 * cannot lift that band at all. It measured a real problem and applied the fix
 * somewhere else.
 *
 *   CLIFF   sibilance is fine, the air above it is missing. Corner goes ABOVE
 *           the peak: cornering on it lifts the "sss" as much as the air, which
 *           is how a correction becomes a harshness.
 *   LEVEL   the whole top end is low, sibilant band included. Corner goes BELOW
 *           that band, so the shelf lifts what was measured as short.
 *
 * Split from the measurement above it because deciding the shape and deciding
 * that a shape is needed are two questions, and together they measured
 * complexity 18 against a ceiling of 15.
 */
function shelfShape(
  { fromLevel, fromGap, level, gap, peak, sampleRate }: {
    fromLevel: number; fromGap: number; level: number;
    gap: number; peak: number; sampleRate: number;
  },
): { corner: number; because: string } {
  const levelLed = fromLevel > fromGap;
  const corner = Math.min(
    levelLed ? SIBILANT[0] * 0.8 : peak * 1.35,
    sampleRate / 2 - 500,
  );
  const because = levelLed
    ? `top end ${(-level).toFixed(1)} dB under the body, ${fromLevel.toFixed(1)} short of `
      + `target; corner below the sibilant band so the shelf lifts it`
    : `air ${gap.toFixed(1)} dB below sibilance; corner above the `
      + `${Math.round(peak)} Hz peak so the shelf lifts the air, not the sss`;
  return { corner, because };
}

export function tiltCorrection(samples: Float32Array,
                               sampleRate: number): FilterSpec | null {
  if (samples.length === 0) return null;
  const body = bandDb(samples, sampleRate, BODY[0], BODY[1]);
  const sibilant = bandDb(samples, sampleRate, SIBILANT[0], SIBILANT[1]);
  const air = bandDb(samples, sampleRate, AIR[0], AIR[1]);
  if (![body, sibilant, air].every(Number.isFinite)) return null;

  // Both deficits are measured RELATIVE to the body band, never against a
  // fixed dBFS figure, so a quiet utterance is never mistaken for a dull one.
  // Loudness is a separate stage and must not leak into this one.
  const gap = sibilant - air;                 // the cliff  (Joi's failure)
  const level = sibilant - body;              // the deficit (Maya's failure)
  const fromGap = gap - TARGET_AIR_GAP_DB;
  const fromLevel = TARGET_SIBILANT_DB - level;
  const wanted = clamp(Math.max(fromGap, fromLevel),
                       MIN_TILT_GAIN_DB, MAX_TILT_GAIN_DB);
  if (wanted <= 0.5) return null;

  // THE CORNER FOLLOWS WHICH DEFICIT FIRED, and getting this wrong made the
  // correction incoherent in a way no unit test could see. An end-to-end run
  // caught it: the level deficit is MEASURED in the sibilant band, but the
  // corner was always placed above the sibilance peak -- so a dull voice was
  // told it needed 10 dB in 5-8 kHz and then given a shelf starting at 8 kHz,
  // which cannot lift that band at all. It measured a real problem and applied
  // the fix somewhere else.
  //
  //   CLIFF   sibilance is fine, the air above it is missing. Corner goes
  //           ABOVE the peak: cornering on it lifts the "sss" as much as the
  //           air, which is how a correction becomes a harshness.
  //   LEVEL   the whole top end is low, sibilant band included. Corner goes
  //           BELOW that band, so the shelf lifts what was measured as short.
  const peak = sibilancePeakHz(samples, sampleRate);
  const { corner, because } = shelfShape({ fromLevel, fromGap, level, gap, peak, sampleRate });
  return {
    type: "highshelf",
    frequency: Math.round(corner),
    gainDb: Number(wanted.toFixed(2)),
    reason: because,
  };
}

/**
 * A character's declared tone, validated.
 *
 * Untrusted input: a bundle is authored elsewhere and travels between installs,
 * so every field is checked and anything malformed is DROPPED rather than
 * throwing. One bad entry must not silence a character -- the same rule the
 * voice-id map already follows.
 */
export function toneFilters(declared: unknown): FilterSpec[] {
  if (!Array.isArray(declared)) return [];
  const out: FilterSpec[] = [];
  for (const raw of declared) {
    const filter = parseToneFilter(raw);
    if (filter) out.push(filter);
  }
  return out;
}

/**
 * One declared filter, or null if any field is wrong.
 *
 * Split from the loop above rather than inlined, because validating an entry
 * and collecting the survivors are two jobs and together they measured
 * complexity 20 against a ceiling of 15. Every guard is still a guard: nothing
 * was relaxed to shorten it.
 */
/** A finite number inside an inclusive range, or null. Repeated three times below. */
function inRange(value: unknown, lo: number, hi: number): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return value >= lo && value <= hi ? value : null;
}

function parseToneFilter(raw: unknown): FilterSpec | null {
  if (!raw || typeof raw !== "object") return null;
  const entry = raw as Record<string, unknown>;
  const { type, reason } = entry;
  if (type !== "peaking" && type !== "highshelf" && type !== "lowshelf") return null;
  const frequency = inRange(entry.frequency, 20, 20000);
  const gainDb = inRange(entry.gainDb, -MAX_TONE_GAIN_DB, MAX_TONE_GAIN_DB);
  if (frequency === null || gainDb === null) return null;
  // A declared filter with no stated why is how a measured correction rots
  // into an undocumented fudge. Required, and enforced here as well as in
  // the schema, because the schema does not run in the player.
  if (typeof reason !== "string" || !reason.trim()) return null;
  // CLAMPED, not dropped, which is the original behaviour: an out-of-range Q is
  // a bad number rather than a missing one, and silently falling back to the
  // default would make a declared filter narrower or wider than anything asked
  // for. inRange is used only for its type check here.
  const rawQ = inRange(entry.q, Number.NEGATIVE_INFINITY, Number.POSITIVE_INFINITY);
  const q = rawQ === null ? undefined : clamp(rawQ, 0.1, 10);
  return { type, frequency, gainDb, reason: reason.trim(), ...(q ? { q } : {}) };
}

/**
 * The full shaping chain for one utterance: measured tilt, then declared tone.
 *
 * Order matters. Tilt corrects what the engine failed to produce; tone shapes
 * what the character wants on top of a corrected signal. Reversing them would
 * make a character's declaration depend on how dull that day's render was.
 */
export function shapingChain(samples: Float32Array, sampleRate: number,
                             declaredTone?: unknown): FilterSpec[] {
  const tilt = tiltCorrection(samples, sampleRate);
  return [...(tilt ? [tilt] : []), ...toneFilters(declaredTone)];
}
