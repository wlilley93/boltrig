// The circuit shards riding the flow, split from the rings so each file
// stays within its structural budget. Same identity, same authorship note
// as shadersRing.ts: "angular shapes mimicking computer circuitry".

import { FIELD_GLSL, PROJECT_GLSL, PULSE_GLSL } from "../../canvas/glslCommon";
import { CLUMP_GLSL } from "./glslClump";

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
