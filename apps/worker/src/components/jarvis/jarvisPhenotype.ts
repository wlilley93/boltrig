/** The ten server phenotype scalars (decision 0013 + 0024's attachment). */
export const PHENO_KEYS = [
  "valence", "arousal", "irritation", "fatigue", "attention",
  "social", "buoyancy", "luminosity", "tension", "attachment",
] as const;
export type PhenoKey = (typeof PHENO_KEYS)[number];
export type Phenotype = Record<PhenoKey, number>;

/**
 * Rest values. Read them as "nothing is known", not "the agent is calm": the
 * instrument sits at neutral and drops its signal ring rather than performing a
 * mood it has not been told about.
 *
 * This is the one place the instrument deliberately diverges from the Familiar,
 * whose renderer WANDERS its mood when the relay is absent so the creature
 * still looks alive. A creature may idle plausibly; an instrument that invents
 * a reading is broken.
 */
export const RESTING_PHENOTYPE: Phenotype = {
  valence: 0.5, arousal: 0.28, irritation: 0, fatigue: 0, attention: 0.5,
  social: 0.5, buoyancy: 0.5, luminosity: 0.5, tension: 0, attachment: 0.5,
};

/** Phenotype crossfade time constant — mood morphs, it never snaps. */
export const PHENO_TAU = 2.0;

/** How long a phenotype sample stays usable before the dial drops to rest. */
export const PHENO_STALE_MS = 10_000;
