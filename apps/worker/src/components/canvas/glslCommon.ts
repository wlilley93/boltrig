// The GLSL chunks every pass shares: the curl-noise field, the projection, and
// the fringe-colour rule.
//
// SHARED AS STRINGS, NOT COPY-PASTED. The simulation advects a particle along
// curl(p); the draw pass places the particle's TAIL by walking backwards along
// the same curl(p). If the two ever disagree -- one octave retuned, one
// frequency changed -- the streak stops lying on the path the particle is
// actually taking and the motion blur points the wrong way. It is a subtle,
// entirely silent defect, and it was live: this text existed twice, identically,
// with nothing keeping the copies in step.

/** Hash-based value noise plus curl. Prepend to any fragment/vertex shader. */
export const FIELD_GLSL = `
// Hash-based value noise. Cheap and adequate: curl only needs the FIELD to be
// smooth, not to be high quality, because the derivative is what is used.
float hash(vec3 p) {
  p = fract(p * 0.3183099 + vec3(0.1, 0.2, 0.3));
  p *= 17.0;
  return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}
float noise(vec3 x) {
  vec3 i = floor(x), f = fract(x);
  f = f * f * (3.0 - 2.0 * f);
  return mix(
    mix(mix(hash(i + vec3(0,0,0)), hash(i + vec3(1,0,0)), f.x),
        mix(hash(i + vec3(0,1,0)), hash(i + vec3(1,1,0)), f.x), f.y),
    mix(mix(hash(i + vec3(0,0,1)), hash(i + vec3(1,0,1)), f.x),
        mix(hash(i + vec3(0,1,1)), hash(i + vec3(1,1,1)), f.x), f.y), f.z);
}

// Two octaves. The frequencies are higher than the first cut used (1.5/3.1):
// at that scale the filaments bundled into a few thick ropes instead of reading
// as many fine fibres, which is most of why the first render looked like fog.
vec3 potential(vec3 p, float time) {
  float t = time * 0.08;
  return vec3(
    noise(p * 2.3 + vec3(0.0, t, 0.0)) + 0.5 * noise(p * 5.2 + vec3(5.2, t * 1.7, 1.3)),
    noise(p * 2.3 + vec3(4.7, 2.1, t)) + 0.5 * noise(p * 5.2 + vec3(1.9, t * 1.3, 8.4)),
    noise(p * 2.3 + vec3(t, 9.2, 3.8)) + 0.5 * noise(p * 5.2 + vec3(t * 1.1, 6.6, 2.2)));
}

// Curl by central differences on the potential. e is a compromise: smaller and
// the hash noise's own quantisation shows up as jitter in the curl.
vec3 curl(vec3 p, float time) {
  const float e = 0.08;
  vec3 dx = vec3(e, 0.0, 0.0), dy = vec3(0.0, e, 0.0), dz = vec3(0.0, 0.0, e);
  vec3 px0 = potential(p - dx, time), px1 = potential(p + dx, time);
  vec3 py0 = potential(p - dy, time), py1 = potential(p + dy, time);
  vec3 pz0 = potential(p - dz, time), pz1 = potential(p + dz, time);
  return vec3(
    (py1.z - py0.z) - (pz1.y - pz0.y),
    (pz1.x - pz0.x) - (px1.z - px0.z),
    (px1.y - px0.y) - (py1.x - py0.x)) / (2.0 * e);
}

// A particle's role and home radius, derived from its texel rather than stored.
//
// The simulation state is ONE RGBA32F texel per particle -- xyz position, w
// life -- and there is no room in it for a shell index. Deriving the role from
// a stable hash of the texel coordinate costs nothing, needs no second texture,
// and gives the same answer in the simulation and in every draw pass without
// them having to agree about a layout.
//
// Most particles live in the INTERIOR (r < 0.55): that is the "internal network
// of connections within the spherical centre". A minority MIGRATE out toward
// the ring band and back, which is the traffic between the layers.
// MOSTLY A SHELL. The film frame is a globe of orange lines that is BRIGHT AT
// THE LIMB and sparse through the middle -- which is what a shell does under
// projection, because the line of sight crosses far more of it at the edge than
// at the centre. An earlier cut put the whole field in the interior on the
// strength of Ebb's "internal network within the spherical centre" and it read
// as a dandelion: no silhouette, no limb, no globe. Both things are true, and
// the shell is the one that carries the shape.
float homeRadius(vec2 uv, float time) {
  float role = hash(vec3(uv * 57.3, 11.0));
  float jitter = hash(vec3(uv * 23.9, 3.0));
  if (role > 0.92) {
    float phase = hash(vec3(uv * 77.1, 5.0));
    // Cosine rather than a sawtooth: a migrating particle should ease out and
    // ease back, not snap home when its phase wraps.
    float s = 0.5 - 0.5 * cos(6.28318530718 * fract(time * 0.06 + phase));
    return mix(0.32, 1.0, s);
  }
  // The surface: a thin band, so the limb is a limb rather than a haze.
  if (role > 0.28) return 0.88 + 0.10 * jitter;
  // The interior network, kept sparse -- it should be visible THROUGH the shell,
  // not compete with it.
  return 0.24 + 0.46 * jitter;
}

/** True for the ~8% of particles that cross between the interior and the rings. */
bool isMigrating(vec2 uv) {
  return hash(vec3(uv * 57.3, 11.0)) > 0.92;
}
`;

// Shared by every pass that puts a 3D point on screen. The reference is a
// hologram seen head-on, so this is orthographic with only a gentle divide --
// a real perspective would fight the front-on framing.
export const PROJECT_GLSL = `
float depthOf(vec3 p) { return 1.0 / (1.9 - p.z * 0.42); }

vec4 project(vec3 p, float aspect) {
  vec2 xy = p.xy * depthOf(p);
  xy.x /= max(aspect, 0.001);
  return vec4(xy, 0.0, 1.0);
}

// Cheap fake occlusion, and the only depth cue additive blending allows: the
// far side of the sphere falls to 0.18 so the near side reads as in front of it.
float depthFade(vec3 p) {
  return mix(0.18, 1.0, clamp(depthOf(p) * 1.35 - 0.28, 0.0, 1.0));
}
`;

// FRINGE LIGHTS, after Schrade, Fraboni & Vergne, "Fringe Lights: Colored
// Penumbra in Glimpse" (SIGGRAPH Asia 2024), used on Netflix's Leo.
//
// Their problem is not ours -- they colour the penumbra of a shadow -- but the
// STRUCTURE is exactly what this renderer needs. They split one light into an
// outer source that sets the extent of the transition and an inner source that
// sets the core, related by a scale factor m, giving three regions shaded
// independently: outside both, nothing; between them, a fringe colour; inside
// both, the ordinary light. The point is that the TRANSITION BAND GETS ITS OWN
// COLOUR while the lit and unlit parts are left alone.
//
// WHY THIS FIXES THE DEFECT THIS RENDERER ACTUALLY HAD. Every earlier version
// shaded the whole falloff with one warm->hot ramp scaled by intensity, so a
// dim particle contributed the same hue as a bright one. Sixteen thousand of
// those blended additively climb that single ramp together and the middle of
// the frame saturates to white -- which is what two rounds of colour tuning
// were fighting. A fringe colour that is NOT on the ramp does not accumulate
// toward the core colour, so overlapping dim contributions stay saturated
// instead of washing out.
//
// The mapping is honest but not identical to the paper: our continuous quantity
// is the particle's own contribution weight rather than light-source
// visibility, and m scales the fringe band's width via outer = inner / m. m >= 1
// is the useful range, as it is for them.
export const FRINGE_GLSL = `
uniform vec3 uFringe;
uniform float uFringeGain;
uniform float uInner;
uniform float uFringeScale;

vec3 fringeShade(float a, vec3 core) {
  float inner = uInner;
  float outer = inner / max(uFringeScale, 1.0);
  // step, not smoothstep, on the outer edge: below it the paper's region (a) is
  // *unlit*, not dimly lit, and letting it fade in is how the wash comes back.
  float visible = step(outer, a);
  float lit = smoothstep(outer, inner, a);
  return mix(uFringe * uFringeGain, core, lit) * visible;
}
`;
