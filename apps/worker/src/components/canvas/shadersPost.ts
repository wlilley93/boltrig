// Bloom and the final composite.


/** A finite ceiling, well above anything the tone curve can distinguish.
 *
 * THE SCENE BUFFER IS RGBA16F, so it saturates at 65504 and anything past that
 * is INFINITY. The passes are additive and the middle of the frame is where they
 * all stack, so at high gains the core plus the starburst plus a few thousand
 * particles genuinely reach it.
 *
 * An Inf then does two things, and the second is the visible one. The separable
 * Gaussian below spreads it nine taps across and then nine taps down, which
 * turns a point into an AXIS-ALIGNED SQUARE of Inf -- the shape is the proof of
 * the mechanism, because nothing else in this pipeline draws a centred box. Then
 * the composite's tone curve evaluates Inf / (Inf + 1.5), which is NaN, and NaN
 * renders BLACK. Hence "every now and then a black square renders for about a
 * frame": it appears exactly on the frames where the accumulation crosses 65504.
 *
 * Clamping on READ rather than trying to cap the accumulation: the passes are
 * additive with blending in the GPU, so there is no point at which the sum can
 * be limited without changing what blending means. 1e3 is chosen because the
 * curve maps it to 0.9985 against 0.999975 for the half-float maximum -- the two
 * are indistinguishable, so nothing that was legitimately bright gets dimmer.
 *
 * The scene can hold Inf but never NaN, because every pass only ever ADDS a
 * non-negative colour. That is what makes min() a sufficient guard here; against
 * a NaN it would not be, since min(NaN, x) is undefined in GLSL.
 */
const FINITE_CEILING = "const vec3 CEIL = vec3(1e3);\n";

/** The BLOOM's ceiling, and it has to be far tighter than the composite's.
 *
 * Clamping the Inf turned the black square white, which proved the mechanism and
 * fixed only half of it. The other half is that a blur SPREADS whatever it is
 * handed over a fixed support, and this one is nine taps across and nine down --
 * a square. Its smallest tap weight is 0.0162, so any input above about 62 makes
 * even the OUTERMOST tap brighter than white. Every tap inside the kernel then
 * clips to the same value, the Gaussian falloff becomes invisible, and what is
 * left is the shape of the support: an axis-aligned box with hard edges.
 *
 * So the fix is not a bigger clamp, it is a SMALLER one, and only here. 6.0
 * keeps the centre firmly white -- the tone curve takes 6 plus its bloom well
 * past 0.8, and the core lobes are added after this -- while leaving the outer
 * taps at 0.0162 * 6 = 0.097, which is a falloff you can see rather than a
 * plateau. The composite keeps the loose ceiling because it samples one texel
 * per pixel and spreads nothing, so a very large value there is just a white
 * pixel where a white pixel belongs.
 */
const BLOOM_CEILING = "const vec3 BLOOM_CEIL = vec3(6.0);\n";

export const BLOOM_FRAG = `#version 300 es
precision highp float;
in vec2 vUV;
out vec4 oColor;
uniform sampler2D uSrc;
uniform vec2 uDir;        // texel-space blur direction
uniform float uThreshold; // <0 disables the bright-pass (second axis)
${BLOOM_CEILING}
vec3 tap(vec2 uv) { return min(texture(uSrc, uv).rgb, BLOOM_CEIL); }

void main() {
  // Nine taps, Gaussian-ish weights. Separable, so this runs twice.
  float w[5];
  w[0] = 0.227027; w[1] = 0.194594; w[2] = 0.121621; w[3] = 0.054054; w[4] = 0.016216;
  vec3 sum = tap(vUV) * w[0];
  for (int i = 1; i < 5; i++) {
    vec2 o = uDir * float(i);
    sum += tap(vUV + o) * w[i];
    sum += tap(vUV - o) * w[i];
  }
  if (uThreshold >= 0.0) sum = max(sum - uThreshold, vec3(0.0));
  oColor = vec4(sum, 1.0);
}`;

export const COMPOSITE_FRAG = `#version 300 es
precision highp float;
in vec2 vUV;
out vec4 oColor;
uniform sampler2D uScene;
uniform sampler2D uBloom;
uniform float uBloomGain;
uniform float uAspect;
uniform vec3 uWarm;
uniform vec3 uHot;
uniform float uCore;
uniform float uStarburst;
${FINITE_CEILING}
void main() {
  // Clamped on read, for the reason FINITE_CEILING gives: an Inf reaching the
  // tone curve below becomes NaN, and NaN is a black hole in the middle of the
  // frame rather than a bright spot.
  vec3 c = min(texture(uScene, vUV).rgb, CEIL)
         + min(texture(uBloom, vUV).rgb, CEIL) * uBloomGain;

  vec2 d = (vUV - 0.5) * vec2(max(uAspect, 0.001), 1.0);
  float r = length(d);

  // THE CENTRAL HEART. Both references put one at the middle -- Territory call
  // it the central heart, Ebb the spherical centre the network lives in -- and
  // without it the field reads as debris rather than as a mind with a centre.
  // Two lobes: a wide halo and a tight point, so it has a falloff rather than
  // being a disc.
  // BOTH LOBES SIT AT THE WARM END. The tight one used uHot at 2.4x, which
  // put the middle of the frame above what the knee below can represent -- and
  // anything above the knee is white whatever hue arrived there. The heart in
  // the reference frames is brighter than what surrounds it and still plainly
  // orange; it is never a white spot.
  c += uWarm * uCore * exp(-r * r * 60.0) * 1.1;
  c += mix(uWarm, uHot, 0.35) * uCore * exp(-r * r * 900.0) * 1.2;

  // Anamorphic starburst, and it is OFF for the two hologram bodies. Read at
  // the sizes these stages actually draw at, exp(-y*y*4000) * exp(-x*x*26) is a
  // bar fifteen times wider than it is tall laid across the middle in the hot
  // colour -- which is the "white hot block shining through the iris". The
  // reference hologram has no lens flare on it. It stays in the shader because
  // Colossus is a CRT, where a horizontal streak off the beam is correct.
  //
  // The cheap cousin of Animal Logic's physically based
  // lens flare (DigiPro 2019, after Hullin et al.) -- a real lens simulation is
  // not happening in a fragment shader, and this does not pretend to be one. It
  // is a horizontal streak off the core, which is the part of a flare the eye
  // actually reads as "bright light through glass".
  float streak = exp(-d.y * d.y * 4000.0) * exp(-d.x * d.x * 26.0);
  c += uHot * streak * uStarburst;

  // Filmic-ish knee. The denominator is well above 1 deliberately: at 0.85 the
  // curve compressed everything toward white, which was half of the saturation
  // problem the fringe colour fixes the other half of.
  c = c / (c + vec3(1.5));
  c = pow(c, vec3(0.86));
  // ALPHA FOLLOWS LUMINANCE. Writing 1.0 made every one of these bodies an
  // opaque black rectangle, so no amount of CSS could stop the stage reading as
  // a tile pasted onto the step. The context is already premultipliedAlpha
  // false, and the composite runs with blending disabled, so this value reaches
  // the compositor intact and the dark parts of the body let the page through.
  oColor = vec4(c, clamp(max(c.r, max(c.g, c.b)) * 1.35, 0.0, 1.0));
}`;
