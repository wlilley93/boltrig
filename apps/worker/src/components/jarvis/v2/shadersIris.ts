import { FIELD_GLSL, PROJECT_GLSL, PULSE_GLSL } from "../../canvas/glslCommon";

/**
 * THE IRIS, which replaces the neural pathways at the centre.
 *
 * The links were particle-to-particle connections: whatever two neighbours the
 * simulation happened to put beside each other, joined by a bowed line. That is a
 * NETWORK, and a network drawn over a bright centre reads as clutter, because its
 * structure is wherever the particles drifted rather than anywhere meaningful. No
 * amount of bowing or dimming fixed that, because the problem was never the line's
 * shape -- it was that the lines did not point at anything.
 *
 * An iris does. Every filament runs radially out from the nucleus, so the structure
 * says "this is the centre" from any angle, and the whole figure reads as an eye
 * rather than as a tangle with a lamp behind it. It is taken from familiar.frag,
 * whose iris is screen-polar with filaments FLOWING OUTWARD from the nucleus -- the
 * flow is what stops it looking engraved.
 *
 * Screen-polar on purpose, like the glyph layers and unlike the wheels: an iris
 * belongs to the plane you look at it in. Filaments tumbling through 3D
 * orientations would read as spokes on a wheel, which is the wheels' job.
 */

/** Filaments. Enough that the eye reads texture rather than counting spokes. */
export const IRIS_FILAMENTS = 132;
/** Segments along each filament, so the travelling band has somewhere to travel. */
export const IRIS_SEGMENTS = 7;
/** Six vertices per segment: each is a quad with a width to shade. */
export const IRIS_VERTS = IRIS_FILAMENTS * IRIS_SEGMENTS * 6;

export const IRIS_VERT = `#version 300 es
precision highp float;

uniform float uTime;
uniform float uAspect;
uniform float uEnergy;
uniform float uRadius;
uniform float uBands[8];
/** x inner edge of the iris, y outer edge. The pupil is the hole inside x. */
uniform vec2 uIrisRadius;
/** x how many filaments are lit, y how wide each one is in clip space. */
uniform vec2 uIrisFil;
/** x outward flow SPEED, y how pronounced the travelling band is. */
uniform vec2 uIrisFlow;

out float vAmp;
out vec2 vCell;
${FIELD_GLSL}
${PROJECT_GLSL}
${PULSE_GLSL}

const int FILAMENTS = ${IRIS_FILAMENTS};
const int SEGMENTS = ${IRIS_SEGMENTS};

void main() {
  const float ALONG[6]  = float[6](0.0,  1.0,  0.0,  0.0,  1.0, 1.0);
  const float ACROSS[6] = float[6](-1.0, -1.0, 1.0,  1.0, -1.0, 1.0);
  int v = gl_VertexID;
  int corner = v % 6;
  int idx = v / 6;
  int seg = idx % SEGMENTS;
  int fil = idx / SEGMENTS;
  float along = ALONG[corner];
  float across = ACROSS[corner];
  float ffil = float(fil);

  float tau = 6.28318530718;
  float seed = hash(vec3(ffil * 0.137, 3.1, 0.0));
  if (seed > clamp(uIrisFil.x, 0.0, 1.0)) {
    vAmp = 0.0;
    vCell = vec2(0.0);
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    return;
  }

  // ANGULAR JITTER. Evenly spaced filaments read as a machined gear; a small
  // per-filament offset is the difference between a fan and a cog.
  float jitter = (hash(vec3(ffil * 0.71, 9.0, 0.0)) - 0.5) * (tau / float(FILAMENTS)) * 1.6;
  float a = (ffil / float(FILAMENTS)) * tau + jitter;

  // Each filament reaches a different distance, so the outer edge is ragged rather
  // than a drawn circle -- a hard outer boundary would fight the lens ring.
  float reach = 0.55 + 0.45 * hash(vec3(ffil * 0.31, 5.0, 0.0));
  float inner = uIrisRadius.x;
  float outer = mix(uIrisRadius.x, uIrisRadius.y, reach);
  float t0 = float(seg) / float(SEGMENTS);
  float t1 = float(seg + 1) / float(SEGMENTS);
  float t = mix(t0, t1, along);
  float r = mix(inner, outer, t) * uRadius;

  vec2 radial = vec2(cos(a), sin(a));
  vec2 tangent = vec2(-radial.y, radial.x);
  vec2 p2 = radial * r + tangent * across * uIrisFil.y * 0.5;
  vec3 q = vec3(p2, 0.0);

  int band = fil % 8;
  vAmp = 0.55 + 0.45 * clamp(uBands[band], 0.0, 1.0);

  // THE OUTWARD FLOW, which is what makes it alive rather than engraved. A band of
  // brightness travels from the nucleus to the rim; its phase is offset per filament
  // so they do not pulse in unison, which would read as one blinking ring.
  float phase = fract(t - uTime * uIrisFlow.x + hash(vec3(ffil * 0.53, 1.0, 0.0)));
  float band_ = 0.5 + 0.5 * cos(tau * phase);
  vAmp *= mix(1.0, band_, clamp(uIrisFlow.y, 0.0, 1.0));

  // Fade at both ends: a filament that stops dead at the pupil looks cut, and one
  // that stops dead at the rim draws a circle.
  vAmp *= smoothstep(0.0, 0.22, t) * smoothstep(1.0, 0.55, t);
  vAmp *= 0.66 + 0.34 * uEnergy;
  vAmp *= 1.0 + 2.6 * pulse(q) + 0.35 * uSwell;

  vCell = vec2(t, across);
  gl_Position = project(q, uAspect);
}`;

export const IRIS_FRAG = `#version 300 es
precision highp float;
in float vAmp;
in vec2 vCell;
out vec4 oColor;
uniform vec3 uWarm;
uniform vec3 uHot;
uniform float uGain;

void main() {
  float across = clamp(abs(vCell.y), 0.0, 1.0);
  float stroke = 1.0 - across * across;
  // Hotter at the pupil and cooler toward the rim, so the eye has a temperature
  // gradient outward rather than being one flat colour with a hole in it.
  vec3 c = mix(uHot, uWarm, clamp(vCell.x, 0.0, 1.0));
  oColor = vec4(c * vAmp * stroke * uGain, 1.0);
}`;
