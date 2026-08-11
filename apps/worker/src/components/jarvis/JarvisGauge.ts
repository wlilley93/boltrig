// The gauge's fill -> arc mapping, extracted so it can be tested.
//
// It lived only in GLSL, where it cannot be exercised: the rule that an overrun
// occupies a SECOND lap rather than pinning the first at full is the thing that
// makes 114% distinguishable from 100%, and it was previously guarded by
// nothing but a screenshot I happened to zoom into.
//
// The shader still draws; these functions define what it draws. jarvisGauge
// tests assert that the shader's own constants still agree with the ones here.

/** Fill at which the arc starts breaking into dashes — the non-colour warning. */
export const WARN_FROM = 0.85;
/** Fill at which that warning is fully applied. */
export const WARN_TO = 1.0;

export interface GaugeArcs {
  /** 0..1 of the first lap that is lit. */
  lap1: number;
  /** 0..1 of the overrun lap, drawn on its own track outside the first. */
  lap2: number;
  /** 0..1 how strongly the dash-break warning applies. */
  warn: number;
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

function smoothstep(edge0: number, edge1: number, x: number): number {
  const t = clamp((x - edge0) / (edge1 - edge0), 0, 1);
  return t * t * (3 - 2 * t);
}

/**
 * Splits a fill into the arcs the shader draws.
 *
 * An unknown reading produces no arcs at all — not a zero-length one. The
 * caller must draw a ghost track instead; a gauge sitting at empty claims
 * "nothing spent", which is a different and more expensive claim than "no
 * reading".
 */
export function gaugeArcs(fill: number, known: boolean): GaugeArcs {
  if (!known || !Number.isFinite(fill)) return { lap1: 0, lap2: 0, warn: 0 };
  const value = Math.max(0, fill);
  return {
    lap1: Math.min(value, 1),
    // Clamped at one full extra lap: past 200% the dial cannot say more than
    // "very over", and a third lap would collide with the tracks either side.
    lap2: clamp(value - 1, 0, 1),
    warn: smoothstep(WARN_FROM, WARN_TO, value),
  };
}
