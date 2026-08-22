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
// AZIMUTHAL ANCHORING, and the clumping it exists to stop. The radial spring
// below fixes only |p|: nothing restores a particle's DIRECTION, so under the
// on-shell tangential flow (which is compressible on the sphere -- flow()
// removes the radial component, and a projected curl field is no longer
// divergence-free) the azimuthal density random-walks into convergence combs
// and parks there for as long as the slowly-evolving field holds its shape.
// Measured on Ultron 2026-08-20: bright vertically-striated knots that survive
// facets=0, arcs=0 and petal=0, because they are particle DENSITY, not a pass.
// Each particle gets a hashed home DIRECTION and a gentle tangential pull
// toward it -- uniform coverage guaranteed at the equilibrium, while the curl
// still swirls everything locally. Zero (the unset default) is byte-identical,
// the same rule uOuter, uLayerPace and uCloud were added under.
uniform float uHomePull;
${FIELD_GLSL}

// A seeded point at the particle's own home radius, so respawns land where that
// particle belongs rather than all on one shell.
vec3 spawn(vec2 uv, float t) {
  float a = hash(vec3(uv * 91.7, t)) * 6.28318530718;
  float z = hash(vec3(uv * 43.3, t + 7.0)) * 2.0 - 1.0;
  float r = sqrt(max(0.0, 1.0 - z * z));
  return vec3(r * cos(a), r * sin(a), z) * homeRadius(uv, t) * uRadius;
}

// The particle's own bearing, stable for its lifetime. Uniform on the sphere
// via the same area-preserving construction spawn() uses, from its own seeds.
vec3 homeDir(vec2 uv) {
  float a = hash(vec3(uv * 71.9, 23.0)) * 6.28318530718;
  float z = hash(vec3(uv * 37.7, 29.0)) * 2.0 - 1.0;
  float r = sqrt(max(0.0, 1.0 - z * z));
  return vec3(r * cos(a), r * sin(a), z);
}

void main() {
  vec4 st = texture(uState, vUV);
  vec3 p = st.xyz;
  float life = st.w;

  if (life <= 0.0) {
    oColor = vec4(spawn(vUV, uTime), 1.0);
    return;
  }

  // The outer layer may drift at its own rate. Applied HERE, in the simulation,
  // so the positions themselves are slower -- scaling it in the draw would move
  // the streaks off the path the particle is actually taking.
  vec3 v = flow(p, uTime, uEnergy) * layerPace(vUV);

  // Radial constraint toward this particle's own home radius. It was weak on
  // purpose, so particles overshoot and the surface stays broken rather than
  // reading as a drawn sphere -- but overshoot is also exactly what throws
  // material past the silhouette, and a contained node sphere is what is
  // wanted. Tightened, and the broken surface now comes from the curl field
  // rather than from particles escaping.
  float d = length(p);
  vec3 outward = normalize(p + 1e-5);
  v += outward * (shapedRadius(vUV, p, uTime, uRadius, uPetal) - d) * 6.0;

  // The anchoring pull, tangential ONLY -- projected off the radial axis so it
  // can never fight the spring above. Its magnitude is sin(angle to home), so a
  // particle near its bearing feels almost nothing and one halfway round feels
  // the most; scaled by d so the interior is freer than the shell.
  vec3 home = homeDir(vUV);
  vec3 toHome = home - outward * dot(home, outward);
  v += toHome * uHomePull * d;

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
