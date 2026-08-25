// The GLSL chunks every pass shares. The curl-noise field itself lives in
// ./glslField.ts and is re-exported here, so importers and the eager-glob
// uniform census in ultronBundle.test.ts both still see it on this module.

export { FIELD_GLSL } from "./glslField";

// Debris clustering (CLUMP_GLSL) moved to jarvis/v2/glslClump.ts: it is a
// Jarvis-only chunk, and the Ultron bundle's uniform census counts every
// uniform declared in this module as one his passes must drive.

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

// THE BODY, after familiar.frag -- a lit normal and a fresnel rim, applied to
// particles rather than to a drawn sphere. She builds an orb from a ray-sphere
// gate, a lit normal and a fresnel term, with embers thrown off the rim; these
// two are not orbs, so they take the LIGHTING and leave the geometry.
//
// 1 at the silhouette, 0 facing the viewer. The edge of the body is bright and
// the middle is see-through, which is what gives a cloud of points a surface.
float limb(vec3 p) {
  vec3 n = normalize(p + 1e-5);
  return pow(1.0 - abs(n.z), 2.2);
}

// THE SILHOUETTE, as a uniform rather than two literals per pass.
//
// x is what a face-on particle keeps and y is what the rim adds, so the RATIO
// between them is how hard the body reads as a sphere. It was 0.34 + 0.90 --
// an edge only 3.6x the middle, which is not enough contrast to carve a sphere
// out of sixteen thousand streaks, and the render was fur. It wants an order of
// magnitude, and it wants to be adjustable while looking at it, which is why it
// is a uniform now: see tests/visual/shader-bench.html.
//
// Declared here beside limb() so every pass that includes PROJECT_GLSL gets it.
// setUniforms skips a uniform a program did not declare, so a pass that never
// calls limbMix costs nothing.
uniform vec2 uLimb;

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

// FAR AND FAINT, read from WHERE a particle is rather than which one it is.
//
// Anything past the body's own shell is the outer sphere by definition, so
// position is enough -- and taking it from position means this reaches every
// draw pass through limbMix, instead of threading a texel coordinate into four
// more shaders that never needed one.
float outerFade(vec3 p) {
  return mix(1.0, uOuter.z, smoothstep(1.02, max(1.05, uOuter.x * 0.92), length(p)));
}

float limbMix(vec3 p) { return (uLimb.x + uLimb.y * limb(p)) * outerFade(p); }


// How far outside its home shell a particle has drifted, 0..1. Familiar spawns
// embers as their own pass; here they are DERIVED, so the things that glint are
// exactly the things that have left the body.
float ember(vec3 p, float home) {
  return clamp((length(p) - home) * 3.2, 0.0, 1.0);
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

/** The voice, as a wavefront leaving the centre.
 *
 * Included by DRAW passes only -- SIM_FRAG declares these two itself, because it
 * uses the same numbers as a force rather than as light. `uWaveT` is seconds
 * since the last speech onset, so the front is at radius t*speed and the
 * gaussian makes it a narrow shell rather than a filled sphere. */
export const PULSE_GLSL = `
uniform float uWaveT;
uniform float uWaveAmp;
uniform float uSwell;

/**
 * x speed, y echo spacing in seconds, z decay rate, w the radius it reflects off.
 *
 * Self-contained rather than reading uOuter, because PULSE_GLSL is included by
 * shaders that do not include FIELD_GLSL -- depending on a uniform from another
 * chunk is how a pass ends up compiling everywhere and behaving correctly nowhere.
 */
uniform vec4 uReverb;

/**
 * THE VOICE, REVERBERATING, rather than one front leaving and never returning.
 *
 * It was a single narrow shell travelling outward at a fixed 1.35 and fading as it
 * went. That reads as a ping: something leaves the middle, crosses the body once,
 * and is gone. A voice in a cavity does not do that -- it reaches the wall, comes
 * BACK, and keeps doing so more quietly each time, which is the whole difference
 * between a body that pings when spoken to and a body that rings.
 *
 * Two mechanisms, and both matter:
 *
 *   THE BOUNCE. The front's position is a triangle wave rather than a ramp, so at
 *   the reflecting radius it turns around and travels inward again. One front
 *   therefore crosses the body many times. A ramp put the front outside the
 *   silhouette after about a second and everything went still while the voice was
 *   still going.
 *
 *   THE ECHOES. Three fronts, each starting a little later and at half the
 *   amplitude of the last. One bouncing front is a single ripple sloshing; three
 *   overlapping ones interfere, which is what fills the body with motion instead of
 *   sweeping a bright band across it.
 */
float pulse(vec3 p) {
  float r = length(p);
  // A floor on the reflecting radius: at zero the triangle wave collapses and every
  // front sits at the origin, which would put a static blob in the middle of any
  // body that had not set this yet.
  float reach = max(0.35, uReverb.w);
  float sum = 0.0;
  for (int i = 0; i < 3; i += 1) {
    float t = uWaveT - float(i) * uReverb.y;
    if (t <= 0.0) continue;
    float travel = mod(t * uReverb.x, 2.0 * reach);
    float front = travel > reach ? 2.0 * reach - travel : travel;
    float d = r - front;
    // Narrow, and it fades as it travels: a front as bright at the rim as at the
    // core reads as the whole body flashing rather than as something crossing it.
    sum += exp(-d * d * 22.0) * exp(-t * uReverb.z) * pow(0.5, float(i));
  }
  return sum * uWaveAmp;
}
`;
