/**
 * Debris clustering — JARVIS-ONLY, and its home says so.
 *
 * It lived in canvas/glslCommon, and the Ultron bundle's uniform census globs
 * that module whole: every string export with a `uniform` in it counts as a
 * uniform his passes declare. `uClump` is a channel only Jarvis drives, so the
 * shared home made Ultron's census red for a chunk he never composes in. The
 * census is right that shared modules are part of every body that globs them;
 * the fix is that a one-body chunk does not belong in the shared module.
 *
 * The film's sphere is not statistically uniform -- it has clusters and voids
 * -- and no per-particle hash can produce that, because a hash has no
 * neighbourhoods. Two interfering low-frequency waves do: their product makes
 * blobs, and squaring sharpens the blobs into clumps. The weight is
 * renormalised so the MEAN brightness holds and only the variance rises --
 * uClump.x at zero is exactly the uniform body that ships.
 */
export const CLUMP_GLSL = `
uniform vec2 uClump;
float clumpOf(vec3 p) {
  // THREE waves, not two. The product of two plane waves is a stripe lattice
  // -- measured on the bench as pinwheel sectors, not clusters -- and the third
  // incommensurate axis breaks the stripes into isolated blobs.
  float n = sin(dot(p, vec3(1.7, 0.9, 1.3)) * uClump.y)
          * sin(dot(p, vec3(-0.8, 1.6, 1.1)) * uClump.y * 0.77)
          * sin(dot(p, vec3(1.1, -1.4, 0.6)) * uClump.y * 1.31);
  float w = 0.5 + 0.5 * n;
  return mix(1.0, w * w * 3.1, clamp(uClump.x, 0.0, 1.0));
}`;
