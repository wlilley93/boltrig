// Ultron's body: a fracturing membrane, not an instrument.
//
// EVERY CHOICE HERE IS THE OPPOSITE OF JARVIS'S, on purpose. Animal Logic, who
// built both, coded JARVIS as "an orange glowing aura with angular shapes
// mimicking computer circuitry" and ULTRON as "a blue aura, organically
// designed" reading as the more advanced intelligence. Matt Ebb, who designed
// them, put it as a contrast he was aiming for: Ultron had to look "alive,
// constantly evolving and organic" against Jarvis's geometry.
//
// So Ultron gets NO data rings and NO circuit shards -- those are literally the
// other character's identity. He gets:
//
//   VEIN     the same curl-noise filaments, but longer and slower, so they read
//            as something growing rather than something computing
//   CRACK    a proximity web drawn as JAGGED polylines rather than straight
//            segments -- the shattered-membrane read, and the reason he looks
//            like breaking glass instead of a wireframe
//   FACET    triangular shards, drawn as outlines, catching light as they
//            separate from the surface
//
// AGGRESSION IS A UNIFORM, NOT A PALETTE. `uAggression` drives crack flare,
// facet separation and jitter. Making him "more aggressive" by simply turning
// everything brighter would have produced a louder Jarvis; what actually reads
// as aggression is instability -- things coming apart and re-forming faster
// than they settle.

import { FIELD_GLSL, FRINGE_GLSL, PROJECT_GLSL, PULSE_GLSL } from "../canvas/glslCommon";

/** The voice, as pressure on the membrane.
 *
 * Eight bands mapped over azimuth AND elevation, so the loud part of a syllable
 * pushes a REGION of the shell rather than a ring around its equator -- a ring
 * is Jarvis's shape and belongs to him. `uVoice` is the overall level, so a
 * silent body still holds together instead of collapsing to nothing. */
const VOICE_GLSL = `
uniform float uBands[8];
uniform float uVoice;

float bandAt(vec3 p) {
  vec3 n = normalize(p + 1e-5);
  float a = atan(n.y, n.x) / 6.28318530718 + 0.5;   // 0..1 around
  float e = n.z * 0.5 + 0.5;                        // 0..1 pole to pole
  int idx = int(mod(floor(a * 5.0 + e * 3.0), 8.0));
  return clamp(uBands[idx], 0.0, 1.0);
}
`;

/** Jagged cracks: three segments per link, so each has two kinked interior points. */
export const CRACK_SEGMENTS = 3;

/** One facet per 9 particles, each drawn as three line edges. Denser than
 *  Jarvis's shards -- a shattering surface is mostly shards, where a circuit
 *  board is mostly board. */
export const FACET_STRIDE = 9;

// -------------------------------------------------------------------- veins
//
// The same velocity-stretched streaks, given a longer tail and a slower ramp to
// the hot colour, so the filaments read as growth rather than as data in
// motion. Jarvis reserves white for the genuinely fast; Ultron lets more of the
// field reach the bright end, because he is supposed to look overloaded.
export const VEIN_VERT = `#version 300 es
precision highp float;

uniform sampler2D uState;
uniform float uTime;
uniform float uAspect;
uniform float uEnergy;
uniform float uStreak;
uniform int uGrid;

out float vFade;
out float vSpeed;
${FIELD_GLSL}
${PROJECT_GLSL}
${PULSE_GLSL}
${VOICE_GLSL}

void main() {
  int id = gl_VertexID >> 1;
  int tail = gl_VertexID & 1;
  ivec2 tc = ivec2(id % uGrid, id / uGrid);
  vec4 st = texelFetch(uState, tc, 0);

  vec3 p = st.xyz;
  vec3 v = flow(p, uTime, uEnergy);
  vSpeed = clamp(length(v) * 0.55, 0.0, 1.0);

  vFade = smoothstep(0.0, 0.18, st.w) * smoothstep(1.0, 0.72, st.w);
  vFade *= depthFade(p);
  // The same lit-normal body: a shell coming apart still needs to read as a
  // shell before it can read as coming apart.
  vFade *= 0.30 + 0.95 * limb(p);
  // Fades what has left the membrane, where it used to light it. See the
  // same inversion in Jarvis's field pass.
  vFade *= 1.0 - 0.85 * ember(p, 0.98);
  // The wavefront lights what it passes; a held note keeps a low swell under it.
  vFade *= 1.0 + 3.4 * pulse(p) + 0.55 * uSwell;

  // The voice, as pressure: this region of the shell swells and brightens on a
  // loud band and settles when it passes.
  float band = bandAt(p);
  p *= 1.0 + band * 0.10 * uVoice;
  vFade *= 0.72 + 0.55 * band * uVoice;

  p -= v * uStreak * (1.0 + band * 0.6) * float(tail);
  gl_Position = project(p, uAspect);
}`;

export const VEIN_FRAG = `#version 300 es
precision highp float;
in float vFade;
in float vSpeed;
out vec4 oColor;

uniform vec3 uWarm;
uniform vec3 uHot;
uniform float uGain;
${FRINGE_GLSL}

void main() {
  // speed^1.6 rather than Jarvis's speed^3: more of the field reaches the hot
  // end, which is what makes him look lit from inside rather than instrumented.
  vec3 core = mix(uWarm, uHot, pow(vSpeed, 1.6));
  oColor = vec4(fringeShade(vFade, core) * vFade * uGain, 1.0);
}`;

// ------------------------------------------------------------------- cracks
//
// The shattered membrane, and the pass that carries his silhouette.
//
// WHY JAGGED AND NOT STRAIGHT. Jarvis's LINK pass draws a straight segment
// between two near particles, which reads as a wireframe -- something
// constructed. A crack is not straight: it deviates, and the deviation is what
// the eye recognises as a fracture rather than a line. Each pair here is drawn
// as three segments whose interior points are pushed off the chord by the same
// curl field the particles move through, so the kink is consistent with the
// motion instead of being noise sprinkled on top.
//
// Only genuinely close pairs qualify, as in LINK, so the web thins and thickens
// as the field moves -- a membrane under stress rather than a fixed lattice.
export const CRACK_VERT = `#version 300 es
precision highp float;

uniform sampler2D uState;
uniform float uTime;
uniform float uAspect;
uniform int uGrid;
uniform int uSegments;
uniform float uLinkRange;
uniform float uAggression;

out float vFade;
out float vFlare;
${FIELD_GLSL}
${PROJECT_GLSL}
${PULSE_GLSL}
${VOICE_GLSL}

void main() {
  int vert = gl_VertexID;
  int seg = (vert >> 1) % uSegments;
  int id = (vert >> 1) / uSegments;
  int end = vert & 1;

  ivec2 tc = ivec2(id % uGrid, id / uGrid);
  ivec2 nc = ivec2((tc.x + 1) % uGrid, tc.y);
  vec4 a = texelFetch(uState, tc, 0);
  vec4 b = texelFetch(uState, nc, 0);

  // Parametric position along the crack, in [0,1].
  float t = (float(seg) + float(end)) / float(uSegments);
  vec3 p = mix(a.xyz, b.xyz, t);

  // The kink. Interior points only -- the ends must stay welded to their
  // particles or the crack detaches and floats.
  float interior = sin(t * 3.14159265);
  // A loud band kinks its cracks harder: the membrane is under more stress
  // exactly where the voice is loudest.
  float band = bandAt(p);
  p += curl(p * 2.1 + vec3(7.3), uTime * 1.6) * 0.045 * interior
     * (1.0 + uAggression * 1.5 + band * uVoice * 1.2);
  p *= 1.0 + band * 0.10 * uVoice;

  float d = length(a.xyz - b.xyz);
  vFade = smoothstep(uLinkRange, uLinkRange * 0.25, d);
  vFade *= 0.70 + 0.60 * band * uVoice;
  // Cracks brighten toward the silhouette too, so the fracture wraps a surface.
  vFade *= 0.36 + 0.88 * limb(p);
  // A crack lights up as the wave crosses it: the fracture transmits the voice.
  vFade *= 1.0 + 4.2 * pulse(p) + 0.5 * uSwell;
  vFade *= min(smoothstep(0.0, 0.2, a.w), smoothstep(0.0, 0.2, b.w));
  vFade *= depthFade(p);

  // Arcing. A small, changing minority of cracks flare hard -- the thing that
  // makes him read as unstable rather than merely blue. Stable per crack for
  // the length of a flare, so a segment does not strobe against its neighbours.
  float roll = hash(vec3(float(id) * 0.017, floor(uTime * 2.5), 0.0));
  vFlare = roll > (0.985 - uAggression * 0.02) ? 1.0 : 0.0;

  gl_Position = project(p, uAspect);
}`;

export const CRACK_FRAG = `#version 300 es
precision highp float;
in float vFade;
in float vFlare;
out vec4 oColor;
uniform vec3 uWarm;
uniform vec3 uHot;
uniform float uGain;

void main() {
  // No fringe on the cracks, for the reason the rings have none: they are
  // structure and they do not stack sixteen thousand deep, so the rule that
  // stops additive wash would only dim them below visibility.
  vec3 c = mix(uWarm, uHot, vFade * 0.7 + vFlare * 0.6);
  oColor = vec4(c * vFade * uGain * (1.0 + vFlare * 3.5), 1.0);
}`;

// ------------------------------------------------------------------- facets
//
// Triangular shards, drawn as OUTLINES rather than filled: a filled triangle
// reads as a solid chip, and the reference is glass -- you see the edges and
// through the middle. They lift off the surface as aggression rises, which is
// the shattering, and they are the one place his geometry is angular at all.
export const FACET_VERT = `#version 300 es
precision highp float;

uniform sampler2D uState;
uniform float uTime;
uniform float uAspect;
uniform int uGrid;
uniform int uStride;
uniform float uSize;
uniform float uAggression;

out float vFade;
${FIELD_GLSL}
${PROJECT_GLSL}
${PULSE_GLSL}

// AN OPEN SLIVER: two segments meeting at a corner, four vertices, no closed
// shape. Three edges made a triangle, and the eye recognises a closed polygon at
// any size -- shrinking them only produced smaller triangles. Broken glass is a
// bent edge catching light with the rest of the fracture lost in the dark.
const vec2 CORNER[4] = vec2[4](
  vec2(0.05, 1.0), vec2(-0.70, -0.35),
  vec2(-0.70, -0.35), vec2(0.90, -0.12));

void main() {
  int facet = gl_VertexID / 4;
  int corner = gl_VertexID % 4;
  int id = facet * uStride;
  ivec2 tc = ivec2(id % uGrid, id / uGrid);
  vec4 st = texelFetch(uState, tc, 0);
  vec2 uv = (vec2(tc) + 0.5) / float(uGrid);

  // SEPARATION. The shard drifts outward as aggression rises, so the surface
  // comes apart rather than merely flickering. Its own phase, so they do not
  // all leave together.
  float phase = fract(uTime * 0.22 + hash(vec3(uv * 19.3, 6.0)));
  vec3 p = st.xyz * (1.0 + phase * 0.22 * uAggression);

  vec4 head = project(p, uAspect);
  float spin = uTime * (0.4 + hash(vec3(uv * 5.7, 1.0)) * 1.2);
  float c = cos(spin), sn = sin(spin);
  // Each shard is squashed on its own axis, so no two are the same triangle and
  // none of them is equilateral. Cheaper and more effective than more glyphs.
  vec2 local = CORNER[corner];
  local.x *= 0.45 + 1.15 * hash(vec3(uv * 7.7, 4.0));
  local.y *= 0.45 + 1.15 * hash(vec3(uv * 13.3, 8.0));

  // SIZE VARIES MUCH HARDER, and mostly downward. A uniform equilateral at one
  // size reads as a triangle; a scatter of mostly-small irregular slivers reads
  // as broken glass, which is the thing. The square makes small the common case.
  float sv = hash(vec3(uv * 11.1, 9.0));
  float size = uSize * (0.22 + 1.5 * sv * sv);
  vec2 offset = vec2(local.x * c - local.y * sn, local.x * sn + local.y * c) * size;
  offset.x /= max(uAspect, 0.001);

  // Brightest as it leaves, gone as it drifts: a shard catches the light once,
  // rather than accumulating into a permanent halo.
  vFade = smoothstep(0.0, 0.1, phase) * smoothstep(1.0, 0.45, phase);
  vFade *= smoothstep(0.0, 0.2, st.w) * depthFade(p);
  // Shards belong to the surface: bright at the limb, quiet through the middle.
  vFade *= 0.28 + 0.95 * limb(p);
  vFade *= 1.0 + 3.0 * pulse(p) + 0.5 * uSwell;
  gl_Position = vec4(head.xy + offset, 0.0, 1.0);
}`;

export const FACET_FRAG = `#version 300 es
precision highp float;
in float vFade;
out vec4 oColor;

uniform vec3 uWarm;
uniform vec3 uHot;
uniform float uGain;

void main() {
  // Shards are the brightest thing he has: glass catching light, at the hot end
  // of the ramp rather than the deep blue the membrane sits in.
  vec3 c = mix(uWarm, uHot, 0.8);
  oColor = vec4(c * vFade * uGain, 1.0);
}`;
