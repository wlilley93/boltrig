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

// Split out of glslCommon.ts, which was 451 lines against the worker's 400-line
// floor and could not be pinned instead: the structure gate re-loads its
// baseline from Git and refuses a new debt entry. glslCommon re-exports this, so
// no importer changed -- and the re-export is load bearing, because
// ultronBundle.test.ts globs that module eagerly and censuses its string exports
// for declared uniforms.

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
  float t = time * 0.05;
  return vec3(
    noise(p * 2.3 + vec3(0.0, t, 0.0)) + 0.5 * noise(p * 5.2 + vec3(5.2, t * 1.7, 1.3)),
    noise(p * 2.3 + vec3(4.7, 2.1, t)) + 0.5 * noise(p * 5.2 + vec3(1.9, t * 1.3, 8.4)),
    noise(p * 2.3 + vec3(t, 9.2, 3.8)) + 0.5 * noise(p * 5.2 + vec3(t * 1.1, 6.6, 2.2)));
}

// THE ADVECTION RATE, in one place.
//
// It was written out four times -- the simulation and three draw passes -- and
// they have to agree: SIM moves the particle by curl(p)*flowSpeed(e)*dt, and
// each draw pass puts the streak's tail at p - curl(p)*flowSpeed(e)*uStreak. If
// the copies drift, the motion blur points somewhere the particle is not going,
// which is silent and looks like a bad noise field rather than like a bug.
//
// Roughly half the first cut's rate. At 0.55 + 0.85e the filaments whipped --
// read as solar flares rather than as a mind thinking -- and the reference
// hologram turns over slowly even while it is talking. The streaks keep their
// LENGTH because every call site raises uStreak by the reciprocal; only the
// pace changed.
// A UNIFORM, because "it is spinning far too fast" is a judgement nobody can
// make from a source file. x is the resting rate and y is what a voice adds, so
// a body that drifts at rest and boils while speaking is two numbers rather than
// one -- and both are on a slider in tests/visual/shader-bench.html.
//
// Shipped at 0.26 + 0.40, which is itself roughly half the first cut: at
// 0.55 + 0.85 the filaments whipped and read as solar flares rather than as a
// mind thinking. The streaks keep their LENGTH when this moves, because every
// draw pass multiplies the same rate by uStreak -- so slowing the swirl does not
// shorten the trails, which is the coupling that made this hard to tune blind.
uniform vec2 uSwirl;
// x inner layer, y outer layer -- offsets from 1, so unset means unchanged.
uniform vec2 uLayerPace;

float flowSpeed(float energy) { return uSwirl.x + uSwirl.y * energy; }

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

// THE FLOW, and every pass must ask for it through this function.
//
// curl() alone pushes a particle straight THROUGH the shell, and the radial
// spring in the simulation then hauls it back. So the net motion of a surface
// particle is already tangential, while the streak drawn for it points off the
// surface -- sixteen thousand tails all bristling outward, which is exactly why
// the render read as fur, or as fire, and never as a globe. The tail was
// pointing along a force rather than along the path.
//
// Removing the radial component for particles that are ON the shell is what
// draws great circles without any geometry: each streak lies along the sphere
// and wraps it. The reference frame is a globe of lines that go AROUND, and the
// alternative on the table -- generating actual great-circle geometry -- is a
// second body of code answering a question this projection already answers.
//
// The interior keeps the full 3D curl. The interior is a network rather than a
// surface, and flattening it onto anything would make it a second, smaller
// shell.
//
// SHARED, LIKE flowSpeed AND FOR THE SAME REASON. The simulation integrates
// this and every draw pass walks backwards along it; if the two ever disagree
// the motion blur points somewhere the particle is not going, which is silent
// and reads as a bad noise field rather than as a bug.
vec3 flow(vec3 p, float time, float energy) {
  vec3 v = curl(p, time) * flowSpeed(energy);
  vec3 n = normalize(p + 1e-5);
  float onShell = smoothstep(0.52, 0.80, length(p));
  return mix(v, v - n * dot(v, n), onShell);
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
#ifndef UOUTER_DECLARED
#define UOUTER_DECLARED
// THE DISTANT OUTER SPHERE. x its radius, y what fraction of the particles live
// on it, z how bright it is against the body.
//
// Guarded, because homeRadius needs it in FIELD_GLSL for the simulation and
// limbMix needs it in PROJECT_GLSL for the draws, and several shaders include
// both. A duplicate uniform declaration is a compile error, and on these
// SILENT -- the canvas is removed and the stage reads as a CSS problem.
uniform vec3 uOuter;
#endif

/**
 * IS THIS PARTICLE ON THE OUTER LAYER?
 *
 * Extracted so the simulation and every draw pass ask the SAME question. It was
 * an inline hash inside homeRadius, which was fine while only the simulation
 * cared -- but the moment the draws need to treat the two layers differently, an
 * inline copy is two expressions that have to stay identical, and the failure
 * mode is a particle the simulation puts on the shell and a draw pass colours as
 * interior. Half of each layer wearing the other's clothes, with nothing to grep.
 */
bool onOuterShell(vec2 uv) {
  return hash(vec3(uv * 91.3, 19.0)) < uOuter.y;
}

/**
 * Per-layer pace, as an OFFSET from 1 rather than a multiplier.
 *
 * x adjusts the inner layer and y the outer. Offsets because an unset uniform is
 * zero, and zero here means "no change" -- so a body that never sets this is
 * byte-identical to one compiled before it existed. A multiplier would read as 0
 * when unset and freeze the field solid, which is the same trap uEye sprang: a
 * shared shader gaining a uniform must not change any body that ignores it.
 */
float layerPace(vec2 uv) {
  return max(0.0, 1.0 + (onOuterShell(uv) ? uLayerPace.y : uLayerPace.x));
}

float homeRadius(vec2 uv, float time) {
  float role = hash(vec3(uv * 57.3, 11.0));
  float jitter = hash(vec3(uv * 23.9, 3.0));
  // THE OUTER SPHERE, taken from its OWN hash rather than from role.
  //
  // The reference builds one: the crystalline mass blooms and then "the outer
  // circle takes shape" around it, much lighter and much further out. Its own
  // hash so that setting the fraction to zero leaves the three bands below
  // byte-identical -- a body that does not want an outer sphere must be
  // unchanged by this existing, or the uniform is a behaviour change disguised
  // as an option.
  if (onOuterShell(uv)) {
    return uOuter.x * (0.94 + 0.10 * jitter);
  }
  if (role > 0.92) {
    float phase = hash(vec3(uv * 77.1, 5.0));
    // Cosine rather than a sawtooth: a migrating particle should ease out and
    // ease back, not snap home when its phase wraps.
    float s = 0.5 - 0.5 * cos(6.28318530718 * fract(time * 0.06 + phase));
    // Capped INSIDE the shell. It used to reach 1.0, which put migrating
    // particles out where the exterior rings were; with the rings gone that
    // is simply a minority orbiting outside the body.
    return mix(0.34, 0.90, s);
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

// THREE CONCENTRIC CLOUDS SPREAD INTO PETALS, when a character asks for it.
//
// petal 0 leaves homeRadius exactly as it was, which is what a plain shell
// body passes. Above 0 the particle is assigned to one of three bands and each
// band's radius is modulated BY DIRECTION, so it reaches far along a few axes
// and pulls in between them: spindly arms with dark gaps rather than a lumpy
// sphere. The high power on |cos| is what makes the arms narrow -- a low one
// gives a bumpy ball, which is the failure this exists to avoid. The bands are
// phase-offset from each other so the arms interleave instead of stacking.
/**
 * x how far the surface departs from a sphere, y how fast the shape churns.
 *
 * Zero leaves shapedRadius byte-identical, which is what keeps a body that wants
 * a sphere unchanged by this existing -- the same rule uOuter and uLayerPace were
 * added under.
 */
uniform vec2 uCloud;

/**
 * A CLOUD IS NOT A SPHERE WITH BUMPS, and the difference is where the noise is
 * sampled.
 *
 * Sampling on the particle's POSITION displaces each particle independently and
 * gives a fuzzy ball -- the silhouette stays round and only the surface gets
 * noisy. Sampling on the DIRECTION makes the displacement a property of where on
 * the surface you are, so every particle along one bearing moves together and the
 * outline itself grows lobes and hollows. That is the whole trick.
 *
 * Two octaves: the first carries the large lobes that give the mass its shape, the
 * second breaks their edges up so they do not read as three smooth balloons. The
 * clocks differ so the shape churns rather than rotating rigidly.
 */
float cloudy(vec3 n, float time) {
  vec3 broad = curl(n * 1.9, time * 0.05);
  vec3 fine = curl(n * 4.7 + vec3(11.0, 3.0, 7.0), time * 0.09);
  return clamp(broad.x * 0.72 + fine.y * 0.38, -1.0, 1.0);
}

float shapedRadius(vec2 uv, vec3 p, float time, float scale, float petal) {
  float base = homeRadius(uv, time) * scale;
  // Applied to the BASE, before the petal branch, so a cloud-formed body does not
  // have to take the petal arms as well: the two are independent shapes and a body
  // may want either, both or neither.
  if (uCloud.x > 0.0) {
    base *= 1.0 + uCloud.x * cloudy(normalize(p + 1e-5), time * uCloud.y);
  }
  if (petal <= 0.0) return base;

  float band = floor(hash(vec3(uv * 33.7, 4.0)) * 3.0);      // 0, 1 or 2
  float ring = (0.42 + 0.27 * band) * scale;

  vec3 n = normalize(p + 1e-5);
  float az = atan(n.y, n.x);
  float arms = 3.0 + band;                                    // 3, 4, 5 per band
  float phase = band * 1.1 + time * 0.05 * (band + 1.0);
  float lobe = pow(abs(cos(az * arms * 0.5 + phase)), 6.0);
  // Elevation narrows the arms toward the poles, so they read as petals round
  // an iris rather than as spikes on a sea urchin.
  lobe *= pow(1.0 - abs(n.z), 0.8);

  return mix(base, ring * (1.0 + 1.15 * lobe), petal);
}
`;
