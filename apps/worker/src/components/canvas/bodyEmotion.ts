// The measured inner life, as something the particle bodies actually show.
//
// TEN SCALARS ARRIVE AND THREE WERE BEING READ. Jarvis V2 and Ultron each took
// irritation, arousal and tension and dropped the other seven on the floor --
// so a body that was told the machine was exhausted, unfocused, dim or fond of
// you displayed none of it, while `readsPhenotype: true` claimed otherwise. That
// is the same shape of defect as a manifest that over-counts its clones: a
// declaration nothing downstream honours.
//
// EVERY SCALAR MOVES SOMETHING, AND ONLY ONE THING. A scalar wired into four
// places at once cannot be judged by eye -- turning it up changes the whole
// frame and you learn nothing about which effect you are looking at. So each
// gets one job, chosen to match what the word means rather than to spread the
// influence evenly.
//
// THE PALETTE IS IDENTITY AND STAYS OUT OF THIS. Jarvis is orange and Ultron is
// blue because Animal Logic coded them that way, so nothing here rotates a hue.
// Irritation already drags the warm toward red inside each renderer's palette();
// mood is expressed in BRIGHTNESS, REACH and PACE instead, which is what a body
// made of filaments can say without becoming a different character.

import type { EnergyRamp, JarvisTuning, UltronTuning } from "./bodyTuning";

/** Decision 0013's nine, plus 0024's attachment. */
export const PHENOTYPE_SCALARS = [
  "valence", "arousal", "irritation", "fatigue", "attention",
  "social", "buoyancy", "luminosity", "tension", "attachment",
] as const;

export type PhenotypeScalar = (typeof PHENOTYPE_SCALARS)[number];
export type BodyPhenotype = Record<PhenotypeScalar, number>;

/**
 * Rest is ZERO, and it means "nothing is known" rather than "the machine is
 * calm". Every mapping below is written so that all-zero leaves the shipped
 * tuning untouched -- a body with no reading must look exactly like a body
 * nobody has measured, or the absence of the relay becomes a mood.
 */
export const RESTING_PHENOTYPE: BodyPhenotype = Object.freeze(
  Object.fromEntries(PHENOTYPE_SCALARS.map((key) => [key, 0])),
) as BodyPhenotype;

/** Clamp what the server sent; a missing or non-finite scalar rests at zero. */
export function readBodyPhenotype(raw: Record<string, unknown> | null): BodyPhenotype {
  const out = { ...RESTING_PHENOTYPE };
  if (!raw) return out;
  for (const key of PHENOTYPE_SCALARS) {
    const value = raw[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      out[key] = Math.min(1, Math.max(0, value));
    }
  }
  return out;
}

const scale = (ramp: EnergyRamp, by: number): EnergyRamp => [ramp[0] * by, ramp[1] * by];
/** Lift the RESTING half only, leaving how much a voice adds alone. */
const lift = (ramp: EnergyRamp, by: number): EnergyRamp => [ramp[0] + by, ramp[1]];

/**
 * What the four shared scalars do, in one place so the two bodies agree.
 *
 *   luminosity  overall brightness. The most literal one there is.
 *   fatigue     dims AND slows. Tiredness is not just a dimmer: a tired field
 *               turning over at full pace reads as wired rather than weary.
 *   valence     lifts the heart. Low valence is not a colour change -- see the
 *               header -- it is a body whose centre has gone quiet.
 *   buoyancy    lifts the heart too, and deliberately: they are different
 *               causes of the same visible thing, and inventing a second
 *               unrelated effect to keep them distinguishable would be
 *               decoration rather than expression.
 *   attachment  lifts the heart's RESTING half only, never its response to a
 *               voice, so a long bond reads as a steady warmth rather than as
 *               something that answers when spoken to.
 */
function shared(pheno: BodyPhenotype): {
  brightness: number; pace: number; heart: number; reach: number; rim: number;
} {
  return {
    brightness: (0.85 + 0.30 * pheno.luminosity) * (1 - 0.35 * pheno.fatigue),
    pace: 1 - 0.55 * pheno.fatigue,
    heart: 0.10 * pheno.valence + 0.08 * pheno.buoyancy,
    // Attention is the web's reach: a focused mind holds more connections open.
    reach: 1 + 0.45 * pheno.attention,
    // Social is being turned toward you, which for a shell body is its
    // silhouette -- the rim is the part of it that faces outward.
    rim: 1 + 0.25 * pheno.social,
  };
}

export function jarvisEmotion(tuning: JarvisTuning, pheno: BodyPhenotype): JarvisTuning {
  const s = shared(pheno);
  return {
    ...tuning,
    swirl: scale(tuning.swirl, s.pace),
    linkGain: scale(tuning.linkGain, s.brightness * (1 + 0.35 * pheno.attention)),
    linkRange: tuning.linkRange * s.reach,
    drawGain: scale(tuning.drawGain, s.brightness),
    shardGain: scale(tuning.shardGain, s.brightness),
    core: lift(scale(tuning.core, s.brightness), s.heart + 0.12 * pheno.attachment),
    linkLimb: [tuning.linkLimb[0], tuning.linkLimb[1] * s.rim],
    drawLimb: [tuning.drawLimb[0], tuning.drawLimb[1] * s.rim],
  };
}

export function ultronEmotion(tuning: UltronTuning, pheno: BodyPhenotype): UltronTuning {
  const s = shared(pheno);
  return {
    ...tuning,
    swirl: scale(tuning.swirl, s.pace),
    veinGain: scale(tuning.veinGain, s.brightness),
    crackGain: scale(tuning.crackGain, s.brightness * (1 + 0.35 * pheno.attention)),
    crackRange: tuning.crackRange * s.reach,
    facetGain: scale(tuning.facetGain, s.brightness),
    core: lift(scale(tuning.core, s.brightness), s.heart + 0.12 * pheno.attachment),
    veinLimb: [tuning.veinLimb[0], tuning.veinLimb[1] * s.rim],
    crackLimb: [tuning.crackLimb[0], tuning.crackLimb[1] * s.rim],
    facetLimb: [tuning.facetLimb[0], tuning.facetLimb[1] * s.rim],
  };
}
