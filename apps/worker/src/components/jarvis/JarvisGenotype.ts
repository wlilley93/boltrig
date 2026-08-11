// Identity for the instrument.
//
// familiar.frag varies every instance from uGene, so no two creatures are the
// same object. Jarvis was one fixed dial — which means it is a skin, and a skin
// is exactly what anyone can copy. A genotype makes a given agent's instrument
// recognisably ITS instrument: same rings, different rhythm.
//
// The variation is deliberately narrow. These genes move counts, ratios and
// phase — never radii, never colour, never anything a reading depends on. An
// instrument you cannot read at a glance because it reshuffled its gauges is a
// worse instrument, however distinctive.

/** Eight genes, uploaded as vec4[2]. */
export const GENE_COUNT = 8;

export const GENE = {
  /** Iris segment count offset, -4..+4 on a base of 12. */
  irisSegments: 0,
  /** Second dashed ring count offset, -6..+6 on a base of 16. */
  dashSegments: 1,
  /** How full the first arc ring is, 0.42..0.68. */
  arc1Fill: 2,
  /** How full the second arc ring is, 0.36..0.62. */
  arc2Fill: 3,
  /** Rotation skew, 0.8..1.25. Applied to every ring, so counter-rotation holds. */
  speedSkew: 4,
  /** Chunk hash offset, 0..64. Re-rolls WHICH arcs exist without changing how many. */
  chunkSeed: 5,
  /** Gauge tick density offset, -18..+18 on a base of 90. */
  tickDensity: 6,
  /** Reserved. Present so the uniform shape does not change when it is claimed. */
  reserved: 7,
} as const;

/** The dial as tuned by hand — what an instrument with no identity shows. */
export const NEUTRAL_GENOTYPE: readonly number[] = [0, 0, 0.55, 0.50, 1, 0, 0, 0];

/**
 * FNV-1a. Chosen because it is stable across runs and platforms: a genotype
 * that changed between sessions would be worse than no genotype at all, since
 * the whole value is in recognising the same instrument again.
 */
function hash32(input: string, salt: number): number {
  let h = 0x811c9dc5 ^ salt;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0) / 0x100000000;
}

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

/**
 * Derives a stable genotype from an identity string (an agent capability name,
 * an org id — whatever the caller considers "who this is"). An empty or absent
 * identity returns the neutral dial rather than a random one: an unknown agent
 * should look like the instrument, not like some other agent.
 */
export function genotypeFrom(identity: string | null | undefined): Float32Array {
  const genes = new Float32Array(GENE_COUNT);
  if (!identity) {
    genes.set(NEUTRAL_GENOTYPE);
    return genes;
  }
  genes[GENE.irisSegments] = Math.round(lerp(-4, 4, hash32(identity, 1)));
  genes[GENE.dashSegments] = Math.round(lerp(-6, 6, hash32(identity, 2)));
  genes[GENE.arc1Fill] = lerp(0.42, 0.68, hash32(identity, 3));
  genes[GENE.arc2Fill] = lerp(0.36, 0.62, hash32(identity, 4));
  genes[GENE.speedSkew] = lerp(0.80, 1.25, hash32(identity, 5));
  genes[GENE.chunkSeed] = Math.round(lerp(0, 64, hash32(identity, 6)));
  genes[GENE.tickDensity] = Math.round(lerp(-18, 18, hash32(identity, 7)));
  genes[GENE.reserved] = 0;
  return genes;
}
