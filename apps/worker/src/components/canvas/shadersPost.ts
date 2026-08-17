// Bloom and the final composite.


export const BLOOM_FRAG = `#version 300 es
precision highp float;
in vec2 vUV;
out vec4 oColor;
uniform sampler2D uSrc;
uniform vec2 uDir;        // texel-space blur direction
uniform float uThreshold; // <0 disables the bright-pass (second axis)

void main() {
  // Nine taps, Gaussian-ish weights. Separable, so this runs twice.
  float w[5];
  w[0] = 0.227027; w[1] = 0.194594; w[2] = 0.121621; w[3] = 0.054054; w[4] = 0.016216;
  vec3 sum = texture(uSrc, vUV).rgb * w[0];
  for (int i = 1; i < 5; i++) {
    vec2 o = uDir * float(i);
    sum += texture(uSrc, vUV + o).rgb * w[i];
    sum += texture(uSrc, vUV - o).rgb * w[i];
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

void main() {
  vec3 c = texture(uScene, vUV).rgb + texture(uBloom, vUV).rgb * uBloomGain;

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
  oColor = vec4(c, 1.0);
}`;
