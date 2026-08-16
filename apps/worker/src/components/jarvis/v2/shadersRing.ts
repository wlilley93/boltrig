// The exterior: data rings, and the circuit shards riding the flow.
//
// "Audio-reactive exterior rings of data that circumscribed the hologram,
// evoking spinning hard drive platters and reel to reel data tape" -- Matt Ebb,
// who designed and animated it. The shards are the other half of the same
// identity: "angular shapes mimicking computer circuitry", which is what
// distinguishes Animal Logic's JARVIS from their deliberately organic Ultron.

import { FIELD_GLSL, FRINGE_GLSL, PROJECT_GLSL, PULSE_GLSL } from "../../canvas/glslCommon";

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

out float vAmp;
${FIELD_GLSL}
${PROJECT_GLSL}
${PULSE_GLSL}

void main() {
  int v = gl_VertexID;
  int end = v & 1;
  int idx = v >> 1;
  int seg = idx % uSegments;
  int ring = idx / uSegments;
  float fring = float(ring);

  float tau = 6.28318530718;
  float span = tau / float(uSegments);
  float spin = uTime * (0.16 + 0.09 * fring) * (mod(fring, 2.0) < 0.5 ? 1.0 : -1.0);
  // Each element is an OBLONG stretched along the tangent, not a tick: the beam
  // flows round the circle instead of being beads threaded on it. Length varies
  // per element so the wall never reads as a repeating pattern.
  float seed = hash(vec3(float(seg) * 0.071, fring * 2.3, 0.0));
  float lenScale = 0.55 + 1.9 * seed;
  float a = float(seg) * span + spin + span * lenScale * float(end);

  // GREAT CIRCLES ON DIFFERENT AXES, not parallel platters.
  //
  // The film's hologram, and the ophanim imagery it borrows from -- wheels
  // within wheels at every orientation around a central eye -- are the same
  // structure, and it is not three tilted hoops on nearby planes. Each ring
  // here gets its own axis from a hash, so they intersect rather than nest,
  // which is what makes a sphere of rings read as a sphere at all.
  //
  // BETWEEN A THIRD AND TWO THIRDS of the body. Hooped outside everything the
  // wheels read as an orb with rings parked around it; inside the halo and
  // around the core they read as structure belonging to one being.
  float radius = (0.34 + 0.32 * hash(vec3(fring * 5.1, 0.0, 0.0))) * uRadius;

  // A FIBONACCI SPHERE, not a hash, for the axes. Six hashed directions came
  // back visibly clustered -- all six wheels leaning the same way, which reads
  // as one wobbly hoop rather than as wheels within wheels. Six points spaced
  // by the golden angle are as far apart as six points on a sphere get, and
  // they are deterministic, so the arrangement is designed rather than drawn.
  float k = (fring + 0.5) / float(uRings);
  float az = 1.0 - 2.0 * k;
  float ar = sqrt(max(0.0, 1.0 - az * az));
  float aphi = fring * 2.39996323;
  vec3 axis = normalize(vec3(ar * cos(aphi), ar * sin(aphi), az) + vec3(1e-4));
  // Any vector not parallel to the axis will do for the first basis leg; the
  // fallback covers the case where the axis happens to be near +Z.
  vec3 seedv = abs(axis.z) > 0.9 ? vec3(1.0, 0.0, 0.0) : vec3(0.0, 0.0, 1.0);
  vec3 bu = normalize(cross(axis, seedv));
  vec3 bv = cross(axis, bu);
  vec3 centre = cos(a) * bu + sin(a) * bv;
  // THE TUBE. Scatter this element inside a disc perpendicular to the
  // centreline, so the beam has a cross-section you can see through rather than
  // an infinitely thin wall. Polar-disc sampling (sqrt on the radius) keeps the
  // fill even instead of crowding the axis.
  vec3 tangent = -sin(a) * bu + cos(a) * bv;
  vec3 outward = normalize(centre + 1e-5);
  vec3 side = normalize(cross(tangent, outward) + 1e-5);
  float ta = hash(vec3(float(seg) * 0.19, fring, 1.0)) * tau;
  float tr = sqrt(hash(vec3(float(seg) * 0.37, fring, 2.0))) * uBeam * radius;
  vec3 q = centre * radius + (cos(ta) * outward + sin(ta) * side) * tr;

  // A slow precession, so the arrangement never settles into a fixed lattice.
  float pr = uTime * 0.05 * (0.6 + 0.3 * fring);
  q = vec3(q.x * cos(pr) - q.z * sin(pr), q.y, q.x * sin(pr) + q.z * cos(pr));

  // AUDIO REACTIVITY, which is the adjective the reference uses. Segments map
  // to bands by position around the ring, so different arcs answer to different
  // parts of the voice and the platter never pulses as a block.
  int band = (seg + ring * 3) % 8;
  // A floor well above zero: a silent ring must still be a ring. The voice
  // modulates the platters, it does not switch them on.
  vAmp = 0.55 + 0.45 * clamp(uBands[band], 0.0, 1.0);

  // Dropped sectors and radial striation -- the reel-to-reel read. Stable per
  // segment, so a gap stays a gap while the ring turns rather than strobing.
  float glitch = hash(vec3(float(seg) * 0.13, fring * 3.7, 0.0));
  if (glitch < 0.09) vAmp = 0.0;
  vAmp *= 0.72 + 0.28 * step(0.5, fract(float(seg) * 0.25));
  vAmp *= 0.62 + 0.38 * uEnergy;
  vAmp *= depthFade(q);
  // The rings flare as the front reaches them, which is what makes the pulse
  // read as leaving the body rather than happening inside it.
  vAmp *= 1.0 + 4.5 * pulse(q) + 0.4 * uSwell;

  gl_Position = project(q, uAspect);
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
out vec4 oColor;
uniform vec3 uWarm;
uniform vec3 uHot;
uniform float uGain;

void main() {
  vec3 c = mix(uWarm, uHot, vAmp * vAmp);
  oColor = vec4(c * vAmp * uGain, 1.0);
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

out vec2 vLocal;
out float vFade;
out float vGlyph;
${FIELD_GLSL}
${PROJECT_GLSL}
${PULSE_GLSL}

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
  vec3 v = curl(p, uTime) * (0.55 + 0.85 * uEnergy);

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
  vFade *= 1.0 + 3.0 * pulse(p) + 0.5 * uSwell;

  float size = uSize * (0.6 + 0.8 * hash(vec3(uv * 11.1, 9.0)));
  vec2 offset = (dir * vLocal.x * 2.0 + perp * vLocal.y) * size;
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
