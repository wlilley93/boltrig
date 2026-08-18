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

/**
 * EMOTION AS COLOURATION, not only as brightness.
 *
 * Irritation was the only scalar that touched colour -- everything else moved
 * gains and rates. That makes nine of the ten registers legible only as "more" or
 * "less" of the same look, and a mood you can only express by turning something up
 * is not really expression: it is a volume knob with ten inputs.
 *
 * Returned as MULTIPLIERS on whatever palette a body already has, so it composes
 * with Jarvis's orange and Ultron's blue rather than replacing either. A resting
 * phenotype returns exactly 1 everywhere, which is what keeps an unmeasured body
 * looking like itself -- the same guarantee the gain mappings make.
 *
 * The channels move independently and each one has a reason:
 *
 *   irritation  crushes green and blue hard -- toward blood. It was here already
 *               and it is the strongest colour term because anger should be the
 *               one mood nobody has to be told about.
 *   valence     lifts blue slightly when positive and crushes it when negative,
 *               which reads as warm/cold rather than as bright/dim.
 *   arousal     lifts the HOT end only. A roused body has a harder highlight; its
 *               resting colour is unchanged, so the change reads as intensity.
 *   fatigue     pulls every channel toward its own average -- desaturation. A
 *               tired thing loses colour before it loses light, which is why this
 *               is separate from the brightness term.
 *   tension     whitens the hot end by lifting green and blue together. Held
 *               tension reads as glare rather than as hue.
 *   attachment  warms the warm end a little, and only the warm end. Same logic as
 *               its heart term: a bond is a resting quality, not a reaction.
 */
export function emotionColour(pheno: BodyPhenotype): {
  warm: readonly [number, number, number];
  hot: readonly [number, number, number];
  fringe: readonly [number, number, number];
  /**
   * How far toward grey the palette should be pulled, 0..1.
   *
   * Separate from the multipliers because a MULTIPLIER CANNOT DESATURATE. An earlier
   * cut folded it in by pulling every channel's multiplier toward 1 -- but 1 is the
   * base palette, whose saturation is whatever it always was, so a fully fatigued
   * body measured 0.801 against 0.805: no change, under a comment claiming there was
   * one. Desaturating [1.0, 0.38, 0.04] means lifting green and blue toward red,
   * which takes multipliers above 1 whose size depends on the base. So the amount
   * travels as a number and `tint` -- which is handed the base -- applies it.
   */
  desaturate: number;
} {
  const irr = pheno.irritation;
  const val = pheno.valence;
  return {
    warm: [
      1 + 0.04 * pheno.attachment,
      (1 - irr * 0.55) * (1 + 0.05 * val),
      (1 - irr * 0.80) * (1 + 0.12 * val + 0.05 * pheno.attachment),
    ],
    hot: [
      1,
      (1 - irr * 0.35) * (1 + 0.10 * pheno.arousal + 0.10 * pheno.tension),
      (1 - irr * 0.60) * (1 + 0.06 * pheno.arousal + 0.18 * pheno.tension),
    ],
    fringe: [1, 1 - irr * 0.4, 1 - irr * 0.6],
    // A tired thing loses colour before it loses light, which is why this is a
    // separate term from the brightness one in shared().
    desaturate: pheno.fatigue * 0.55,
  };
}

/**
 * Apply a register to one palette colour: multiply, then pull toward grey.
 *
 * Toward the colour's OWN luminance rather than toward a fixed grey, so a warm body
 * fades to a warm grey and a cold one to a cold grey -- fading both to the same
 * neutral would make two different beings converge as they tired.
 */
export function tint(
  base: readonly number[],
  mul: readonly [number, number, number],
  desaturate = 0,
): [number, number, number] {
  const rgb: [number, number, number] = [
    base[0] * mul[0], base[1] * mul[1], base[2] * mul[2],
  ];
  if (desaturate <= 0) return rgb;
  const lum = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
  const k = Math.min(1, desaturate);
  return [
    rgb[0] + (lum - rgb[0]) * k,
    rgb[1] + (lum - rgb[1]) * k,
    rgb[2] + (lum - rgb[2]) * k,
  ];
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
