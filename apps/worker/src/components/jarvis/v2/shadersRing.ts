// The exterior: data rings, and the circuit shards riding the flow.
//
// "Audio-reactive exterior rings of data that circumscribed the hologram,
// evoking spinning hard drive platters and reel to reel data tape" -- Matt Ebb,
// who designed and animated it. The shards are the other half of the same
// identity: "angular shapes mimicking computer circuitry", which is what
// distinguishes Animal Logic's JARVIS from their deliberately organic Ultron.

import { FIELD_GLSL, FRINGE_GLSL, PROJECT_GLSL, PULSE_GLSL } from "../../canvas/glslCommon";
import { CLUMP_GLSL } from "./glslClump";

/** Great circles of data. Six intersecting axes read as a sphere of wheels;
 *  three read as a hoop skirt, and a dozen turns the surface into a mesh. */
export const RINGS = 6;
/** Elements per beam. Higher than the old tick count because each one is now a
 *  scattered oblong inside a tube rather than a segment of a drawn circle: the
 *  beam's body has to be filled, not just its outline stepped around. */
export const RING_SEGMENTS = 420;
/** Beam cross-section, as a fraction of the ring's own radius. Thick enough to
 *  see the far wall through the near one, thin enough to stay a beam. */
export const BEAM_THICKNESS = 0.085;

// --------------------------------------------------------- data rings (RING)
//
// "Audio-reactive exterior rings of data that circumscribed the hologram,
// evoking spinning hard drive platters and reel to reel data tape."
//
// These are NOT particles. They are flat annuli of tick marks with their own
// trivial vertex maths, which is why they cost almost nothing -- three rings of
// 168 segments is 1008 vertices against the field's 32768 -- and they are the
// part of the design a viewer actually recognises.
//
// Each ring counter-rotates against its neighbour, because two rings turning
// the same way read as one thick ring.
export const RING_VERT = `#version 300 es
precision highp float;

uniform float uTime;
uniform float uAspect;
uniform float uEnergy;
uniform float uRadius;
uniform int uSegments;
uniform int uRings;
uniform float uBeam;
uniform float uBands[8];
// x turns the wheels, y precesses the whole arrangement. Uniforms because "the
// crest should orbit SLOWLY" is a judgement made while watching it, and the
// rates were 0.16 + 0.09*ring with a 0.05 precession baked in.
uniform vec2 uRingSpin;
// Cycles per second for a crest's fade in and out. Its OWN uniform: see the
// note at the lifecycle below for why it stopped riding the precession rate.
uniform float uRingLife;
// x the innermost ring's radius, y the outermost. A uniform because where the
// wheels SIT is the difference between a body with rings inside it and a body
// wearing them: they were at 0.34 to 0.66 of the radius, which is under the
// shell at 0.88 to 0.98, so they were structure buried in the field rather than
// bands wrapping it.
uniform vec2 uRingRadius;
// x how many separate beams each wheel is broken into, y what fraction of the gap
// between them each beam actually fills. Together they are what stops a wheel
// being a wheel: a coverage of 1.0 closes the circumference back up.
uniform vec2 uRingArc;
// Half-width of a beam in clip space, before the perspective scale. This is the
// number that decides whether a beam reads as a hairline or as a bar.
uniform float uRingWidth;

out float vAmp;
// -1..1 across the beam, SIGNED. Signed because the two sides of a solid are not
// the same: one faces the light and one faces away, and an absolute value cannot
// tell them apart. Taking abs() here is what made these read as fat lines.
out float vAcross;
// 0..1 from one end of the beam to the other, for the end caps. A bar with no
// ends is a stroke; the caps are what give it extent rather than direction.
out float vAlong;
${FIELD_GLSL}
${PROJECT_GLSL}
${PULSE_GLSL}

void main() {
  // SIX VERTICES PER BEAM SEGMENT, not two.
  //
  // These were LINES, and a line is one pixel wide however much the comment
  // beside it called the element an oblong. A one-pixel element cannot read as a
  // three-dimensional bar no matter what it is shaded -- there is no across to
  // shade. So each segment is now a quad, expanded perpendicular to its own
  // direction ON SCREEN, which is what keeps it facing the viewer at every
  // orientation a great circle puts it through.
  const float ALONG[6]  = float[6](0.0,  1.0,  0.0,  0.0,  1.0, 1.0);
  const float ACROSS[6] = float[6](-1.0, -1.0, 1.0,  1.0, -1.0, 1.0);
  int v = gl_VertexID;
  int corner = v % 6;
  int idx = v / 6;
  int seg = idx % uSegments;
  int ring = idx / uSegments;
  float fring = float(ring);
  float along = ALONG[corner];
  float across = ACROSS[corner];

  float tau = 6.28318530718;
  float span = tau / float(uSegments);
  float spin = uTime * uRingSpin.x * (1.0 + 0.56 * fring)
             * (mod(fring, 2.0) < 0.5 ? 1.0 : -1.0);

  // NO FULL CIRCUMFERENCE. The wheels are cut into a few separate beams that
  // float round the edge, because a closed hoop reads as a mounted part and the
  // reference has pieces travelling past each other at different rates.
  //
  // Each beam also drifts on its OWN clock on top of the wheel's spin, so they
  // separate and re-converge instead of holding formation. Beams locked to the
  // wheel looked like a dashed line, which is a hoop with holes in it rather than
  // several objects.
  // FRACTIONAL, not floored. Flooring made this an integer dial that jumped, and
  // it also made easing between modes step rather than glide -- a mode change from
  // three beams to five visibly snapped through four. A fractional count leaves the
  // last slot partial, which shows up as one irregular gap and reads as natural
  // rather than as an artefact.
  float beams = max(0.25, uRingArc.x);
  float u = float(seg) / float(uSegments);
  float slot = u * beams;
  float bi = floor(slot);
  float within = fract(slot);
  float drift = uTime * uRingSpin.x * 0.55
              * (hash(vec3(bi * 3.7, fring * 1.9, 0.0)) - 0.5);
  if (within > clamp(uRingArc.y, 0.0, 1.0)) {
    // Off-screen and unlit. Discarding in the vertex stage costs nothing and
    // keeps the gap a real gap rather than a very dim beam.
    vAmp = 0.0;
    vAcross = 0.0;
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    return;
  }

  float seed = hash(vec3(float(seg) * 0.071, fring * 2.3, 0.0));
  // Just enough overlap to hide the seams, no more. At 1.35 + 0.5 the segments
  // piled up into one long smear and the arc read as a drawn stroke; a bar wants
  // to be an OBJECT with a length you can see the end of.
  float lenScale = 1.06 + 0.06 * seed;
  float a0 = float(seg) * span + spin + drift;
  float a1 = a0 + span * lenScale;

  // GREAT CIRCLES ON DIFFERENT AXES, not parallel platters. The film's hologram,
  // and the ophanim imagery it borrows from -- wheels within wheels at every
  // orientation around a central eye -- is not three tilted hoops on nearby
  // planes. Each wheel takes its own axis so they intersect rather than nest,
  // which is what makes a sphere of wheels read as a sphere.
  float radius = mix(uRingRadius.x, uRingRadius.y,
                     hash(vec3(fring * 5.1, 0.0, 0.0))) * uRadius;

  // A FIBONACCI SPHERE, not a hash, for the axes. Six hashed directions came back
  // visibly clustered -- all six leaning the same way, which reads as one wobbly
  // hoop. Points spaced by the golden angle are as far apart as points on a sphere
  // get, and they are deterministic, so the arrangement is designed.
  float k = (fring + 0.5) / float(uRings);
  float az = 1.0 - 2.0 * k;
  float ar = sqrt(max(0.0, 1.0 - az * az));
  float aphi = fring * 2.39996323;
  vec3 axis = normalize(vec3(ar * cos(aphi), ar * sin(aphi), az) + vec3(1e-4));
  vec3 seedv = abs(axis.z) > 0.9 ? vec3(1.0, 0.0, 0.0) : vec3(0.0, 0.0, 1.0);
  vec3 bu = normalize(cross(axis, seedv));
  vec3 bv = cross(axis, bu);

  // A slow precession, so the arrangement never settles into a fixed lattice.
  float pr = uTime * uRingSpin.y * (0.6 + 0.3 * fring);
  mat2 prec = mat2(cos(pr), -sin(pr), sin(pr), cos(pr));

  // BOTH ENDS, in world space. The screen-space width needs the direction the
  // segment actually runs in, and one endpoint cannot say what that is.
  vec3 pa = (cos(a0) * bu + sin(a0) * bv) * radius;
  vec3 pb = (cos(a1) * bu + sin(a1) * bv) * radius;
  pa.xz = prec * pa.xz;
  pb.xz = prec * pb.xz;
  vec3 q = mix(pa, pb, along);

  vec4 ca = project(pa, uAspect);
  vec4 cb = project(pb, uAspect);
  vec2 dir = cb.xy - ca.xy;
  // A degenerate segment -- both ends on the same pixel -- has no direction to be
  // perpendicular to, and normalize() of it is a NaN that takes the whole beam
  // with it. This is the guard that keeps a wheel edge-on from vanishing.
  dir = length(dir) > 1e-6 ? normalize(dir) : vec2(1.0, 0.0);
  vec2 perp = vec2(-dir.y, dir.x);
  // Thickness follows perspective, so a beam on the near side is visibly fatter
  // than the same beam behind the body. A constant width flattened the sphere.
  float halfW = uRingWidth * (0.55 + 0.9 * depthOf(q)) * (0.75 + 0.5 * seed);
  vec4 clip = mix(ca, cb, along);
  clip.xy += perp * across * halfW;

  // AUDIO REACTIVITY. Beams map to bands by position, so different arcs answer to
  // different parts of the voice and the wheel never pulses as a block.
  int band = (int(bi) + ring * 3) % 8;
  // A floor well above zero: a silent wheel must still be a wheel. The voice
  // modulates the beams, it does not switch them on.
  vAmp = 0.55 + 0.45 * clamp(uBands[band], 0.0, 1.0);

  // ITS OWN RATE, and it used to ride the precession. The argument for coupling
  // them was that both describe how slowly the arrangement changes. What it
  // produced was the opposite failure: precession ships at 0.016, so the lifecycle
  // period came out at 1.0 / (0.016 * 0.62) -- about 101 SECONDS. The beams never
  // came and went, they sat in whatever state the page loaded into and drifted over
  // minutes. Measured as brightness variance that made two samples of the same body
  // a minute apart differ by a factor of two.
  float lifePhase = fract(uTime * uRingLife
                        + hash(vec3(fring * 7.7, 1.7, 0.0)) + bi * 0.31);
  vAmp *= smoothstep(0.0, 0.16, lifePhase) * smoothstep(1.0, 0.70, lifePhase);

  // Radial striation along the beam, stable per segment so a bright stretch stays
  // put while the beam travels rather than strobing.
  vAmp *= 0.78 + 0.22 * step(0.5, fract(float(seg) * 0.25));
  vAmp *= 0.62 + 0.38 * uEnergy;
  vAmp *= depthFade(q);
  // The beams flare as the front reaches them, which is what makes the pulse read
  // as leaving the body rather than happening inside it.
  vAmp *= 1.0 + 2.9 * pulse(q) + 0.3 * uSwell;

  vAcross = across;
  // Where this segment sits along its own beam, so the fragment can cap the ends.
  vAlong = clamp(within / max(0.02, clamp(uRingArc.y, 0.0, 1.0)), 0.0, 1.0);
  gl_Position = clip;
}`;

// NO FRINGE ON THE RINGS, deliberately.
//
// The fringe rule exists because sixteen thousand additive particles overlap
// each other and climb one colour ramp together until the middle of the frame
// goes white. A thousand ring vertices barely overlap at all, so they cannot
// cause that -- and applying the rule to them anyway put most segments below
// the outer threshold and drew them as nothing. The rings went invisible, which
// is how the first render of this pass came back with no rings in it despite
// drawing 1008 vertices of them.
//
// Fix the defect where the defect is. Structure that does not stack does not
// need a fringe.
export const RING_FRAG = `#version 300 es
precision highp float;
in float vAmp;
in float vAcross;
// Every vertex-stage output needs its matching input here. A missing one is a LINK
// error, and a pass whose program fails to build takes the whole renderer down --
// so the symptom is a blank stage, not a beam without end caps.
in float vAlong;
out vec4 oColor;
uniform vec3 uWarm;
uniform vec3 uHot;
uniform float uGain;

void main() {
  // A SOLID, not a thick line, and the difference is four things.
  //
  // The previous version faded symmetrically from the centre to both edges. That
  // is exactly what a soft line looks like -- the eye has nothing to tell it which
  // way the object faces, so it reads the quad as a stroke however wide it is
  // drawn. A bar needs a side that catches light and a side that does not.
  float across = clamp(vAcross, -1.0, 1.0);
  float a = abs(across);

  // 1. A HARD SILHOUETTE. A feathered edge is a glow; an edge that arrives in the
  //    last fifth of the width is a boundary, and a boundary is what makes a shape
  //    look like it displaces space.
  float edge = smoothstep(1.0, 0.80, a);

  // 2. A LIT FACE AND A DARK FACE. Signed across, so one side of every beam is in
  //    shadow. This is the term that does most of the work: it is the only one that
  //    says the object has an orientation.
  float face = mix(0.30, 1.0, 0.5 + 0.5 * across);

  // 3. A SPECULAR BAND, offset toward the lit side rather than centred. Centred, it
  //    is a spine and reads as a filament down the middle of a flat ribbon; offset,
  //    it reads as light grazing a curved surface.
  float spec = exp(-pow((across - 0.42) * 3.2, 2.0));

  // 4. END CAPS. Without them a beam has direction but no extent, and the arc reads
  //    as one continuous stroke rather than as several separate objects.
  float cap = smoothstep(0.0, 0.05, vAlong) * smoothstep(1.0, 0.95, vAlong);

  float shape = edge * cap * (face * 0.68 + spec * 0.85);
  // The highlight runs hotter than the body, which is how a lit edge reads on a
  // warm object.
  vec3 c = mix(uWarm, uHot, clamp(vAmp * vAmp * 0.45 + spec * 0.75, 0.0, 1.0));
  oColor = vec4(c * vAmp * shape * uGain, 1.0);
}`;

// ------------------------------------------------------ circuit shards (SHARD)
//
// "Angular shapes mimicking computer circuitry" is half of what distinguishes
// Animal Logic's JARVIS from their Ultron, who is deliberately organic. So
// these are hard-edged by construction -- every boundary is a step(), never a
// smoothstep() -- because a soft glint would read as fire and the whole point
// is that this is DATA.
//
// One quad per shard, oriented in SCREEN space along the projected velocity.
// Orienting in screen space rather than building a 3D basis is both cheaper and
// more correct here: the shard should face the viewer, and this is a hologram
// seen front-on.
export const SHARD_VERT = `#version 300 es
precision highp float;

uniform sampler2D uState;
uniform float uTime;
uniform float uAspect;
uniform float uEnergy;
uniform int uGrid;
uniform int uStride;
uniform float uSize;
// x how much a far-side chip swells, y how much it dims. Together they are a
// fake depth of field: a defocused element covers more screen with less light,
// and that trade is nearly all a viewer reads of real defocus.
uniform vec2 uFocus;

out vec2 vLocal;
out float vFade;
out float vGlyph;
${FIELD_GLSL}
${PROJECT_GLSL}
${PULSE_GLSL}
${CLUMP_GLSL}

const vec2 CORNER[6] = vec2[6](
  vec2(-1.0, -1.0), vec2(1.0, -1.0), vec2(1.0, 1.0),
  vec2(-1.0, -1.0), vec2(1.0, 1.0), vec2(-1.0, 1.0));

void main() {
  int shard = gl_VertexID / 6;
  int corner = gl_VertexID % 6;
  int id = shard * uStride;
  ivec2 tc = ivec2(id % uGrid, id / uGrid);
  vec4 st = texelFetch(uState, tc, 0);
  vec2 uv = (vec2(tc) + 0.5) / float(uGrid);

  vec3 p = st.xyz;
  vec3 v = flow(p, uTime, uEnergy);

  vec4 head = project(p, uAspect);
  vec4 ahead = project(p + v * 0.04, uAspect);
  vec2 dir = ahead.xy - head.xy;
  dir = length(dir) > 1e-5 ? normalize(dir) : vec2(1.0, 0.0);
  vec2 perp = vec2(-dir.y, dir.x);

  vLocal = CORNER[corner];
  vGlyph = hash(vec3(uv * 31.7, 2.0));

  // ANTI-MATTERING, not fading. A smooth envelope reads as dimming; circuitry
  // is not there, then it IS, holds, and is gone. So this is a hard gate with a
  // bright overshoot at each switch -- a flash as it condenses out of nothing
  // and a flash as it annihilates, and flat brightness in between.
  float phase = fract(uTime * 0.35 + hash(vec3(uv * 19.3, 6.0)));
  float on = step(0.10, phase) * step(phase, 0.74);
  float birth = exp(-pow((phase - 0.10) * 42.0, 2.0));
  float death = exp(-pow((phase - 0.74) * 42.0, 2.0));
  float alive = on + 2.6 * (birth + death);

  vFade = alive * smoothstep(0.0, 0.2, st.w) * depthFade(p);
  // The data in transit gets the circuitry: migrating particles carry brighter
  // shards than the resident interior does.
  vFade *= isMigrating(uv) ? 1.0 : 0.45;
  vFade *= clumpOf(p);
  vFade *= 1.0 + 2.2 * pulse(p) + 0.35 * uSwell;

  // FILM DEBRIS IS NOT ONE STAMP. The reference chips vary in scale, in aspect
  // and in set angle; a fleet of identical 2:1 quads reads as confetti. Size
  // spreads wider than before, the aspect runs squat to slab, and each chip
  // takes its own tilt off the flow direction -- velocity still leads, so the
  // debris keeps reading as riding the field rather than sprayed at random.
  float size = uSize * (0.45 + 1.15 * hash(vec3(uv * 11.1, 9.0)));
  float chipAspect = mix(1.1, 3.0, hash(vec3(uv * 23.9, 4.0)));
  float tilt = (hash(vec3(uv * 17.3, 8.0)) - 0.5) * 1.15;
  float tc_ = cos(tilt);
  float ts_ = sin(tilt);
  dir = mat2(tc_, -ts_, ts_, tc_) * dir;
  perp = vec2(-dir.y, dir.x);
  // The far hemisphere falls out of focus: swollen and dimmed, never culled.
  float behind = clamp(1.0 - depthOf(p), 0.0, 1.0);
  size *= 1.0 + uFocus.x * behind;
  vFade *= 1.0 - clamp(uFocus.y * behind, 0.0, 0.9);
  vec2 offset = (dir * vLocal.x * chipAspect + perp * vLocal.y) * size;
  offset.x /= max(uAspect, 0.001);
  gl_Position = vec4(head.xy + offset, 0.0, 1.0);
}`;

export const SHARD_FRAG = `#version 300 es
precision highp float;
in vec2 vLocal;
in float vFade;
in float vGlyph;
out vec4 oColor;

uniform vec3 uWarm;
uniform vec3 uHot;
uniform float uGain;

// Three glyphs, all built from step() so every edge is hard. A right-angled
// trace, a three-sided bracket, and a tick.
float glyph(vec2 q, float pick) {
  vec2 a = abs(q);
  if (pick < 0.34) {
    // L-shaped trace: a horizontal arm and a vertical arm meeting at a corner.
    float arm = step(a.y, 0.22) * step(q.x, 0.35);
    float leg = step(a.x - 0.35, 0.22) * step(-0.1, q.y);
    return max(arm, leg);
  }
  if (pick < 0.67) {
    // Bracket: an outline with one side missing, so it never closes into a box.
    float outline = step(0.62, max(a.x, a.y)) * step(max(a.x, a.y), 1.0);
    float gap = step(0.55, q.x) * step(a.y, 0.55);
    return outline * (1.0 - gap);
  }
  // Tick: a thin bar with a shorter cap, the reel-to-reel mark.
  float bar = step(a.y, 0.14) * step(a.x, 0.9);
  float cap = step(a.y, 0.5) * step(0.72, a.x) * step(a.x, 0.9);
  return max(bar, cap);
}

void main() {
  float mask = glyph(vLocal, vGlyph);
  if (mask < 0.5) discard;
  vec3 c = mix(uWarm, uHot, vGlyph * 0.6);
  oColor = vec4(c * vFade * uGain, 1.0);
}`;
