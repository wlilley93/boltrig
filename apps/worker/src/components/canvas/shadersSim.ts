// The simulation pass, and the fullscreen vertex shader every post pass uses.
//
// One texel per particle: xyz position, w life. Life runs 1 -> 0 and respawns,
// so the cloud is always partly rebuilding and never settles into a fixed shape.

import { FIELD_GLSL } from "./glslCommon";

export const QUAD_VERT = `#version 300 es
in vec2 aPos;
out vec2 vUV;
void main() {
  vUV = aPos * 0.5 + 0.5;
  gl_Position = vec4(aPos, 0.0, 1.0);
}`;

// ---------------------------------------------------------------- simulation
//
// One texel per particle: xyz position, w life. Life runs 1 -> 0 and respawns,
// so the cloud is always partly rebuilding and never settles into a fixed shape.
export const SIM_FRAG = `#version 300 es
precision highp float;
in vec2 vUV;
out vec4 oColor;

uniform sampler2D uState;
uniform float uTime;
uniform float uDt;
uniform float uEnergy;    // 0..1, drives speed and lifetime
uniform float uRadius;    // overall scale on every particle's home radius
uniform float uWaveT;     // seconds since the last speech onset
uniform float uWaveAmp;   // 0 when not speaking
uniform float uPetal;     // 0 = plain shell (Jarvis); >0 = concentric petals
${FIELD_GLSL}

// A seeded point at the particle's own home radius, so respawns land where that
// particle belongs rather than all on one shell.
vec3 spawn(vec2 uv, float t) {
  float a = hash(vec3(uv * 91.7, t)) * 6.28318530718;
  float z = hash(vec3(uv * 43.3, t + 7.0)) * 2.0 - 1.0;
  float r = sqrt(max(0.0, 1.0 - z * z));
  return vec3(r * cos(a), r * sin(a), z) * homeRadius(uv, t) * uRadius;
}

void main() {
  vec4 st = texture(uState, vUV);
  vec3 p = st.xyz;
  float life = st.w;

  if (life <= 0.0) {
    oColor = vec4(spawn(vUV, uTime), 1.0);
    return;
  }

  vec3 v = curl(p, uTime) * flowSpeed(uEnergy);

  // Soft radial constraint toward this particle's own home radius. Weak enough
  // that particles overshoot, which is what keeps the surface broken rather
  // than reading as a drawn sphere.
  float d = length(p);
  vec3 outward = normalize(p + 1e-5);
  v += outward * (shapedRadius(vUV, p, uTime, uRadius, uPetal) - d) * 3.0;

  // THE SPEECH WAVE. An onset starts an impulse at the centre which travels
  // outward at a fixed speed, so a syllable visibly CROSSES the body instead of
  // lighting all of it at once. This is Animal Logic's "segments react in
  // accordance to the animation of surrounding geometry" -- cause and effect
  // transferred through the form -- and it costs two lines because the phase is
  // just time minus distance over speed.
  float phase = uWaveT - d * 0.9;
  v += outward * uWaveAmp * exp(-phase * phase * 30.0) * 4.0;

  p += v * uDt;
  life -= uDt * mix(0.16, 0.34, uEnergy);
  oColor = vec4(p, life);
}`;
