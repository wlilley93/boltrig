// Dial geometry shared between the shader and any DOM drawn on top of it.
//
// These numbers are DUPLICATED in jarvis.frag, which cannot import anything.
// That duplication is the real cost of the SVG label overlay: the shader owns
// the rings, the DOM owns the words, and only this file's constants keep them
// on the same circle. Change a radius here and you must change it there.
//
// Units are the shader's `p` units: the origin is the dial centre and 1.0 is
// the SHORT side of the viewport. An SVG with
//
//     viewBox="-50 -50 100 100"  preserveAspectRatio="xMidYMid meet"
//
// reproduces that mapping exactly — its 100 units fit the short side and centre
// on the long one — so an SVG coordinate is just a shader coordinate x100.
// The one difference is handedness: SVG's y axis points DOWN.

/** Multiply a shader-space length by this to get SVG user units. */
export const SVG_UNITS = 100;

/** Outermost ring — the circle both label arcs sit on. */
export const R_OUTER = 0.403;

/** Cap height of the state labels. */
export const LABEL_CAP_H = 0.0125;

/** Gauge track radii. Must match R_G_BUDGET / R_G_TOKEN in jarvis.frag. */
export const GAUGE_RADII = {
  budget: 0.428,
  tokens: 0.238,
} as const;

/** Ring radii, for anything that needs to line up with the dial. */
export const RADII = {
  core: 0.019,
  iris: 0.100,
  fanIn: 0.119,
  fanOut: 0.192,
  dash2: 0.226,
  hairCircle: 0.250,
  gauge: 0.288,
  arc1: 0.322,
  arc2: 0.368,
  outer: R_OUTER,
} as const;

/** Shader-space length -> SVG user units. */
export const toSvg = (v: number): number => v * SVG_UNITS;
