// ---------------------------------------------------------------------------
// THE SILHOUETTE - the one structural change the genotype needs (GENOTYPE.md s1).
//
// Before this, familiar.frag:231 read:
//
//     float dScreen = length(uv - centre);
//
// That single call is why every familiar was a circle. `length()` IS a circle;
// RADIUS and the swell terms only scale it. Figures-of-8, bowties and lobed forms
// are not reachable by tuning - the distance function itself has to change.
//
// CONTRACT. `shapeDist` returns a distance that equals `scale` ON THE SILHOUETTE (NOT 1.0 -
// that wording cost a rewrite; see the parted branch), <scale inside, >scale outside.
// Historically stated as: a NORMALISED radial distance, 1.0 exactly on the
// silhouette, <1 inside, >1 outside, for every shape. That is deliberate and it is
// what makes this a drop-in: every downstream comparison in familiar.frag is written
// against `scale` (`dScreen < scale*1.58`, `smoothstep(scale*0.985, scale*1.010, ...)`,
// the halo falloff, the mote and ember bounds). Multiply the normalised distance by
// `scale` and all of them keep their exact meaning on a bowtie that they had on a
// circle. A shape function that returned true euclidean distance would silently
// change the meaning of ~20 call sites.
//
// Two families, because neither covers the ask alone:
//   * CASSINI walks circle -> egg -> peanut -> figure-of-8 -> two lobes on ONE
//     parameter. It is the only cheap closed form that passes through the true
//     lemniscate, which is the shape "figure of 8" actually means.
//   * SUPERFORMULA gives the angular families Cassini cannot reach at all: bowties,
//     triangles, stars, flowers, gears.
// ---------------------------------------------------------------------------

// --- Cassini oval, polar form -----------------------------------------------
// Implicit: |p-f1| * |p-f2| = b^2, foci at (+/-a, 0). Solving for r at angle th:
//     r^2 = a^2*cos(2th) +/- sqrt(b^4 - a^4*sin^2(2th))
// The discriminant goes NEGATIVE past the lobe tips, where that angle has no
// boundary at all. Returns BOTH roots. The outer one is the silhouette; the inner one only exists when
// a > b, and it is the hole in the middle - the gap that makes two separate lobes two
// separate lobes. An earlier cut of this returned the + root alone, which is correct
// for a <= b and quietly WRONG above it: the waist filled in and every "split" case
// rendered as a solid bowtie. Measured, not reasoned - a scanline through the centre
// reported inside=True at a=1.40, where the figure should have been empty.
vec2 cassiniRoots(float th, float a, float b) {
  float a2 = a*a, a4 = a2*a2;
  float b4 = b*b*b*b;
  float s = sin(2.0*th);
  float disc = b4 - a4*s*s;
  if (disc < 0.0) return vec2(0.0);    // no boundary at this angle: past the lobe tips
  float k = a2*cos(2.0*th);
  float root = sqrt(disc);
  float r2o = k + root;                // outer boundary
  float r2i = k - root;                // inner boundary; <= 0 means no hole
  return vec2(r2o <= 0.0 ? 0.0 : sqrt(r2o),
              r2i <= 0.0 ? 0.0 : sqrt(r2i));
}

// --- Superformula (Gielis) --------------------------------------------------
//     r(th) = ( |cos(m*th/4)/A|^n2 + |sin(m*th/4)/B|^n3 ) ^ (-1/n1)
// The exponents are guarded away from zero: n1 near 0 sends the reciprocal to
// infinity, and pow() of a negative base is undefined behaviour on real drivers -
// the same class of UB already guarded elsewhere in this shader.
float superR(float th, float m, float n1, float n2, float n3, float A, float B) {
  float mm = m*th*0.25;
  float ca = abs(cos(mm)/max(A, 1e-3));
  float sa = abs(sin(mm)/max(B, 1e-3));
  float t1 = pow(max(ca, 1e-6), max(n2, 1e-3));
  float t2 = pow(max(sa, 1e-6), max(n3, 1e-3));
  float sum = max(t1 + t2, 1e-6);
  return pow(sum, -1.0/max(n1, 1e-3));
}

// --- The dispatcher ---------------------------------------------------------
// p        offset from the body centre, in the same units familiar.frag uses for uv
// gShape   0 = circle (identity: byte-for-byte the old behaviour), 1 = cassini,
//          2 = superformula, 3 = blend of 1 and 2
// gBlend   crossfade for mode 3
// Returns the normalised distance described in the contract above.
float shapeDist(vec2 p,
                float gShape, float gBlend,
                float gFocal, float gCassB, float gLobe,
                float gM, float gN1, float gN2, float gN3, float gSA, float gSB,
                float gAspect, float gRot, float gTwist,
                float gScale) {
  // Aspect and rotation are applied to the SAMPLE, not the formula, so they compose
  // with every family for free.
  float rl = length(p);
  float ct = cos(-gRot), st = sin(-gRot);
  vec2 q = vec2(p.x*ct - p.y*st, p.x*st + p.y*ct);
  q.x /= max(gAspect, 1e-3);
  q.y *= max(gAspect, 1e-3);

  // Twist: orientation that varies with radius, which shears lobes into a spiral.
  float th = atan(q.y, q.x) + gTwist*rl;

  // Lobe balance: bias one half of the figure larger. Applied as an angular gain so
  // a figure-of-8 can have a big head and a small tail.
  float bal = 1.0 + gLobe*0.45*cos(th);

  float r = 1.0;
  float rInner = 0.0;
  if (gShape < 0.5) {
    r = 1.0;                                            // circle - the identity case
  } else if (gShape < 1.5) {
    vec2 cr = cassiniRoots(th, gFocal, gCassB);
    r = cr.x; rInner = cr.y;
  } else if (gShape < 2.5) {
    r = superR(th, gM, gN1, gN2, gN3, gSA, gSB);
  } else {
    vec2 cr = cassiniRoots(th, gFocal, gCassB);
    float rs = superR(th, gM, gN1, gN2, gN3, gSA, gSB);
    float bl = clamp(gBlend, 0.0, 1.0);
    r = mix(cr.x, rs, bl);
    rInner = cr.y*(1.0 - bl);                           // the hole fades out as we blend away
  }
  r *= bal;
  rInner *= bal;

  // r == 0 means "this angle is outside the figure entirely" (a parted Cassini). A
  // huge distance puts it firmly outside every downstream test, which is what a gap
  // should look like. Without this the divide would produce inf/NaN and the driver
  // would paint whatever fell out of it.
  if (r <= 1e-4) return 1e4;
  float lq = length(q);

  // A PARTED BODY HAS NO CENTRE, so it cannot be measured from one.
  //
  // Measured before this branch existed: a genotype past the split rendered at 5.9% lit with
  // a peak of 39/255, and the bench called it SUSPECT (flat/black). The silhouette was right -
  // the lobes exist within +/-20.5 degrees and span r 0.616..1.351 - but every downstream
  // consumer measures depth as distance from the figure's centre, and the figure's centre is
  // the empty gap between the lobes. Each lobe rendered as the outer rind of a sphere whose
  // glowing middle had been cut out.
  //
  // So when the body is parted, depth is measured across the LOBE's own thickness instead:
  // 0 on its radial mid-line, 1 at both of its boundaries. That preserves the contract exactly
  // (1.0 on the silhouette, <1 inside, >1 outside), so the ~20 `scale`-relative comparisons
  // downstream keep their meaning, while giving the interior a core to build light around.
  //
  // Only when parted. For rInner == 0 the same formula would read 1.0 at the body's CENTRE,
  // which would invert every unparted familiar - so the unparted path is untouched and stays
  // pixel-identical to what is already verified.
  if (rInner > 1e-4) {
    // UNITS. The contract is not "1.0 on the silhouette" as the header above once said - it is
    // that the returned value equals `scale` there, because every downstream test compares it
    // against `scale`. The unparted `lq/r` satisfies that because the boundary sits at
    // lq = r*scale. A first cut of this branch returned a dimensionless 0..1 and the body
    // vanished completely: rendered, measured 5.8% lit, and the image was pure background.
    //
    // So the lobe's mid-line has to be located in the SAME units as lq, which means knowing
    // `scale`. It is threaded in rather than guessed, and it is used ONLY here.
    float midUv  = (rInner + r)*0.5*gScale;   // the lobe's radial centre, in uv
    // Guarded: at the lobe TIPS the two boundaries meet, the half-thickness goes to zero, and
    // an unguarded divide would send the tips to infinity - a body with its points snipped off.
    float halfT  = max((r - rInner)*0.5, 1e-4);
    if (lq < rInner*gScale) return 1e4;       // the gap between the lobes: outside the body
    return abs(lq - midUv)/halfT;
  }
  return lq/r;
}
