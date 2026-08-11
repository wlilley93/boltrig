import type { FamiliarGenotype } from "@wlilley93/boltrig-web-sdk";

/**
 * The capability contract owns Familiar identity. These are the values emitted
 * by boltrig.models.familiar; unknown future values deliberately degrade to the
 * neutral body instead of being guessed into an existing family.
 */
export const FAMILIAR_BODIES = ["cassini", "kepler", "pioneer", "voyager"] as const;
export const FAMILIAR_MARKINGS = ["arc", "constellation", "halo", "orbit"] as const;
export const FAMILIAR_ACCESSORIES = ["antenna", "orbit-ring", "signal-pin"] as const;

export type FamiliarBody = (typeof FAMILIAR_BODIES)[number] | "neutral";
export type FamiliarMarking = (typeof FAMILIAR_MARKINGS)[number];
export type FamiliarAccessory = (typeof FAMILIAR_ACCESSORIES)[number];

const GENOTYPE_SOURCE = "agent_capability.name.v1";
const NEUTRAL_PALETTE = ["#dbeafe", "#3b82f6", "#172554"] as const;
export const FAMILIAR_CANONICAL_BASE_HUE_DEGREES = 214;

export interface FamiliarVisualIdentity {
  bound: boolean;
  source: typeof GENOTYPE_SOURCE | "unbound";
  seed: number;
  body: FamiliarBody;
  palette: [string, string, string];
  markings: FamiliarMarking[];
  accessories: FamiliarAccessory[];
}

export function familiarVisualIdentity(
  genotype?: FamiliarGenotype | null,
): FamiliarVisualIdentity {
  const bound = genotype?.source === GENOTYPE_SOURCE;
  const body = bound && isMember(FAMILIAR_BODIES, genotype.body)
    ? genotype.body
    : "neutral";
  const palette = bound ? validPalette(genotype.palette) : null;
  return {
    bound,
    source: bound ? GENOTYPE_SOURCE : "unbound",
    seed: bound && typeof genotype.seed === "number" && Number.isFinite(genotype.seed)
      ? genotype.seed >>> 0
      : 0,
    body,
    palette: palette ?? [...NEUTRAL_PALETTE],
    markings: bound
      ? members(FAMILIAR_MARKINGS, genotype.markings)
      : [],
    accessories: bound
      ? members(FAMILIAR_ACCESSORIES, genotype.accessories)
      : [],
  };
}

/**
 * uGene is positional in familiar.frag. Defaults reproduce the neutral circle;
 * the authoritative body selects a family, the stable seed only varies inside
 * it, and palette/marking/accessory fields tune their corresponding channels.
 */
export function packFamiliarGenotype(
  genotype?: FamiliarGenotype | null,
): Float32Array {
  const identity = familiarVisualIdentity(genotype);
  const genes = new Float32Array([
    0, 0, 0, 0.75,
    0, 4, 1, 1,
    1, 1, 1, 1,
    0, 0, 0, 0,
    1, 1, 1, 1,
    1, 1, 1, 1,
    1, 1, 1, 1,
    0, 1, 1, 1,
  ]);
  if (!identity.bound || identity.body === "neutral") return genes;

  const random = seededStream(identity.seed);
  if (identity.body === "cassini") {
    genes[0] = 1;
    genes[2] = between(0.48, 0.66, random());
    genes[3] = between(0.88, 0.98, random());
    // Cassini is authored vertically in the canonical flat identity. The
    // shader's native Cassini axis is horizontal, so rotate its camera-space
    // genotype once here and keep every Stage/Badge presentation consistent.
    genes[12] = Math.PI / 2;
    genes[4] = between(0.08, 0.28, random());
    genes[11] = between(0.94, 1.12, random());
  } else if (identity.body === "kepler") {
    genes[0] = 2;
    genes[5] = 5;
    genes[6] = between(0.35, 0.5, random());
    genes[7] = between(1.5, 1.9, random());
    genes[8] = between(1.5, 1.9, random());
    genes[12] = between(0, 1.05, random());
  } else if (identity.body === "pioneer") {
    genes[0] = 2;
    genes[5] = random() < 0.5 ? 7 : 8;
    genes[6] = between(4.5, 7, random());
    genes[7] = between(9, 13, random());
    genes[8] = between(9, 13, random());
    genes[11] = between(0.96, 1.04, random());
  } else if (identity.body === "voyager") {
    genes[0] = 2;
    genes[5] = 3;
    genes[6] = between(0.45, 0.62, random());
    genes[7] = between(0.9, 1.1, random());
    genes[8] = between(0.9, 1.1, random());
    genes[12] = between(0.44, 0.6, random());
  }

  const palette = rgbToHsl(identity.palette[1]);
  if (palette) {
    // The shader consumes this slot as a rotation of its canonical blue, not
    // as an absolute hue. Keep the signed shortest turn so nearby authored
    // blues stay nearby instead of making an almost-full revolution into green.
    const hueDelta = (
      (palette.h - FAMILIAR_CANONICAL_BASE_HUE_DEGREES + 540) % 360
    ) - 180;
    genes[14] = hueDelta / 180 * Math.PI;
    genes[15] = clamp((palette.s - 55) / 100, -0.18, 0.25);
    // Hue alone cannot preserve an authored navy: the previous packer rotated
    // the canonical electric-blue ramp to the right colour family, but threw
    // away the palette's lightness and therefore rendered a pale cyan body.
    // Slot 30 is reserved by the shader contract, so use it for the middle
    // palette colour's normalised lightness. Shape and phenotype stay intact;
    // this only restores the value component of the identity already supplied
    // by the capability API.
    genes[30] = palette.l / 100;
  }

  for (const marking of identity.markings) {
    if (marking === "arc") genes[13] += 0.25;
    if (marking === "constellation") {
      genes[18] *= 1.18;
      genes[29] *= 1.25;
    }
    if (marking === "halo") {
      genes[21] *= 1.25;
      genes[26] *= 1.15;
    }
    if (marking === "orbit") {
      genes[12] += 0.15;
      genes[13] += 0.45;
    }
  }
  for (const accessory of identity.accessories) {
    if (accessory === "antenna") genes[28] += 0.35;
    if (accessory === "orbit-ring") {
      genes[21] *= 1.32;
      genes[26] *= 1.18;
    }
    if (accessory === "signal-pin") {
      genes[22] *= 1.2;
      genes[23] *= 1.12;
    }
  }
  return genes;
}

function validPalette(values?: string[] | null): [string, string, string] | null {
  if (!Array.isArray(values) || values.length < 3) return null;
  const colors = values.slice(0, 3);
  if (!colors.every((value) => /^#[0-9a-f]{6}$/i.test(value))) return null;
  return [colors[0]!, colors[1]!, colors[2]!];
}

function isMember<const T extends readonly string[]>(
  allowed: T,
  value: unknown,
): value is T[number] {
  return typeof value === "string" && (allowed as readonly string[]).includes(value);
}

function members<const T extends readonly string[]>(
  allowed: T,
  values?: string[] | null,
): T[number][] {
  return (values ?? []).filter((value): value is T[number] => isMember(allowed, value));
}

function seededStream(seed: number): () => number {
  let value = seed || 0x6d2b79f5;
  return () => {
    value ^= value << 13;
    value ^= value >>> 17;
    value ^= value << 5;
    value >>>= 0;
    return value / 0x1_0000_0000;
  };
}

function between(min: number, max: number, position: number): number {
  return min + (max - min) * position;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function rgbToHsl(hex: string): { h: number; s: number; l: number } | null {
  const match = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
  if (!match) return null;
  const [red, green, blue] = match.slice(1).map((value) => Number.parseInt(value!, 16) / 255);
  const max = Math.max(red!, green!, blue!);
  const min = Math.min(red!, green!, blue!);
  const delta = max - min;
  const light = (max + min) / 2;
  let hue = 0;
  if (delta !== 0) {
    if (max === red) hue = ((green! - blue!) / delta) % 6;
    else if (max === green) hue = (blue! - red!) / delta + 2;
    else hue = (red! - green!) / delta + 4;
    hue *= 60;
    if (hue < 0) hue += 360;
  }
  const saturation = delta === 0 ? 0 : delta / (1 - Math.abs(2 * light - 1));
  return { h: hue, s: saturation * 100, l: light * 100 };
}
