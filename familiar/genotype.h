/* The genotype's key names and defaults, in ONE place.
 *
 * Two programs read a genotype: familiar-bg (from ~/.config/familiar/genotype.json) and
 * familiar-bench (from $BENCH_GENE, so a shape can be rendered with no compositor). They
 * must agree on every name and every default, or the bench draws a shape the desktop does
 * not - which is the worst kind of preview, because it is confidently wrong.
 *
 * Two lists that must stay equal are a defect waiting to happen, so there is one list. The
 * order IS the uniform layout: index i lands in uGene[i/4][i%4], and the shader reads those
 * slots positionally. Appending is safe; reordering silently re-labels every gene.
 *
 * The defaults are the CIRCLE. That matters beyond tidiness: a missing, truncated or
 * malformed genotype leaves them in place, so the familiar degrades to exactly the body it
 * had before the genotype existed rather than to a black screen.
 */
#ifndef FAMILIAR_GENOTYPE_H
#define FAMILIAR_GENOTYPE_H

#define GENOTYPE_SLOTS 32
/* Derived, never restated. The uniform is `vec4 uGene[GENOTYPE_VEC4S]` and both binaries pass
 * this same count to glUniform4fv. It was a literal `4` in three places while the array was
 * vec4[4]; growing the array would have left two of them uploading a prefix of the genes and
 * the rest reading whatever was in the uniform before - a silent, per-call-site partial
 * upload. One definition cannot disagree with itself. */
#define GENOTYPE_VEC4S (GENOTYPE_SLOTS / 4)

/* 31 of 32 slots claimed. The first sixteen carry the silhouette and the identity tint (hue
 * and saturation took the last two of those on 2026-07-27: identity had shape but no colour,
 * so every familiar in the fleet was the same blue and the strongest distinguishing channel a
 * screen has was going unused). The rest tune the interior, the surface, the light and the
 * motion. Every one defaults to a no-op, so absent is still the old body in the old colour.
 *
 * The array grows in whole vec4s and only ever at the END. Appending is safe; reordering
 * silently re-labels every gene in every genotype.json already on disk. */
static const char *const GENOTYPE_KEYS[GENOTYPE_SLOTS] = {
    "shape",       "blend",   "focal",   "cassiniB",
    "lobeBalance", "superM",  "superN1", "superN2",
    "superN3",     "superA",  "superB",  "aspect",
    "rotation",    "twist",   "hue",     "saturation",
    /* Interior tuning. All MULTIPLIERS defaulting to 1.0, so an absent genotype reproduces the
     * body that shipped before they existed, exactly. An additive gene would default to 0 and
     * every site would then carry its own "what was the old constant" arithmetic inline. */
    "warmth",      "breathDepth", "bumpAmp", "silkChurn",
    "specSharp",   "haloReach",   "specGain", "fresnelGain",
    /* Motion and emission. Multipliers again, same reason. */
    "tempoBase",   "bodyScale",   "haloGain", "irritationGain",
    /* Light and surface frequency. lightAzimuth is the one ADDITIVE gene in this block: it is
     * an angle in radians and its identity value is 0, not 1. The rest stay multipliers. */
    /* paletteLightness claimed slot 30 on 2026-08-14, when the shader began reading uGene[7].z as
     * material exposure. It is a MULTIPLIER-shaped 0..1 authored lightness, not a mood: it is what
     * keeps a navy identity navy instead of letting the electric-blue ramp lift it. Naming it here
     * is what makes it reachable from genotype.json at all - the shader read the slot either way,
     * and an unnamed slot is the "gene wired to a constant" defect familiar.frag names twice. */
    "lightAzimuth", "bumpScale",  "paletteLightness", NULL,
};

static const float GENOTYPE_DEFAULTS[GENOTYPE_SLOTS] = {
    /* shape=0 is the circle: the identity case, byte-for-byte the pre-genotype body */
    0.0f, 0.0f, 0.0f, 0.75f,
    0.0f, 4.0f, 1.0f, 1.0f,
    1.0f, 1.0f, 1.0f, 1.0f,
    0.0f, 0.0f, 0.0f, 0.0f,   /* rotation, twist, hue (radians), saturation (delta)  */
    1.0f, 1.0f, 1.0f, 1.0f,   /* warmth, breathDepth, bumpAmp, silkChurn               */
    1.0f, 1.0f, 1.0f, 1.0f,   /* specSharp, haloReach, specGain, fresnelGain          */
    1.0f, 1.0f, 1.0f, 1.0f,   /* tempoBase, bodyScale, haloGain, irritationGain       */
    0.0f, 1.0f, 1.0f, 1.0f,   /* lightAzimuth (RADIANS, so 0), bumpScale, paletteLightness, resvd */
};

#endif /* FAMILIAR_GENOTYPE_H */
