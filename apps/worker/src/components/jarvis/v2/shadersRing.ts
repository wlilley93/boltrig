// The exterior: data rings, and the circuit shards riding the flow.
//
// "Audio-reactive exterior rings of data that circumscribed the hologram,
// evoking spinning hard drive platters and reel to reel data tape" -- Matt Ebb,
// who designed and animated it. The shards are the other half of the same
// identity: "angular shapes mimicking computer circuitry", which is what
// distinguishes Animal Logic's JARVIS from their deliberately organic Ultron.

import { FIELD_GLSL, FRINGE_GLSL, PROJECT_GLSL, PULSE_GLSL } from "../../canvas/glslCommon";
import { CLUMP_GLSL } from "./glslClump";

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
// x turns the wheels, y precesses the whole arrangement. Uniforms because "the
// crest should orbit SLOWLY" is a judgement made while watching it, and the
// rates were 0.16 + 0.09*ring with a 0.05 precession baked in.
uniform vec2 uRingSpin;
// Cycles per second for a crest's fade in and out. Its OWN uniform: see the
// note at the lifecycle below for why it stopped riding the precession rate.
uniform float uRingLife;
// x the innermost ring's radius, y the outermost. A uniform because where the
// wheels SIT is the difference between a body with rings inside it and a body
// wearing them: they were at 0.34 to 0.66 of the radius, which is under the
// shell at 0.88 to 0.98, so they were structure buried in the field rather than
// bands wrapping it.
uniform vec2 uRingRadius;
// x how many separate beams each wheel is broken into, y what fraction of the gap
// between them each beam actually fills. Together they are what stops a wheel
// being a wheel: a coverage of 1.0 closes the circumference back up.
uniform vec2 uRingArc;
// Half-width of a beam in clip space, before the perspective scale. This is the
// number that decides whether a beam reads as a hairline or as a bar.
uniform float uRingWidth;

out float vAmp;
// -1..1 across the beam, SIGNED. Signed because the two sides of a solid are not
// the same: one faces the light and one faces away, and an absolute value cannot
// tell them apart. Taking abs() here is what made these read as fat lines.
out float vAcross;
// 0..1 from one end of the beam to the other, for the end caps. A bar with no
// ends is a stroke; the caps are what give it extent rather than direction.
out float vAlong;
${FIELD_GLSL}
${PROJECT_GLSL}
${PULSE_GLSL}

void main() {
  // SIX VERTICES PER BEAM SEGMENT, not two.
  //
  // These were LINES, and a line is one pixel wide however much the comment
  // beside it called the element an oblong. A one-pixel element cannot read as a
  // three-dimensional bar no matter what it is shaded -- there is no across to
  // shade. So each segment is now a quad, expanded perpendicular to its own
  // direction ON SCREEN, which is what keeps it facing the viewer at every
  // orientation a great circle puts it through.
  const float ALONG[6]  = float[6](0.0,  1.0,  0.0,  0.0,  1.0, 1.0);
  const float ACROSS[6] = float[6](-1.0, -1.0, 1.0,  1.0, -1.0, 1.0);
  int v = gl_VertexID;
  int corner = v % 6;
  int idx = v / 6;
  int seg = idx % uSegments;
  int ring = idx / uSegments;
  float fring = float(ring);
  float along = ALONG[corner];
  float across = ACROSS[corner];

  float tau = 6.28318530718;
  float span = tau / float(uSegments);
  float spin = uTime * uRingSpin.x * (1.0 + 0.56 * fring)
             * (mod(fring, 2.0) < 0.5 ? 1.0 : -1.0);

  // NO FULL CIRCUMFERENCE. The wheels are cut into a few separate beams that
  // float round the edge, because a closed hoop reads as a mounted part and the
  // reference has pieces travelling past each other at different rates.
  //
  // Each beam also drifts on its OWN clock on top of the wheel's spin, so they
  // separate and re-converge instead of holding formation. Beams locked to the
  // wheel looked like a dashed line, which is a hoop with holes in it rather than
  // several objects.
  // FRACTIONAL, not floored. Flooring made this an integer dial that jumped, and
  // it also made easing between modes step rather than glide -- a mode change from
  // three beams to five visibly snapped through four. A fractional count leaves the
  // last slot partial, which shows up as one irregular gap and reads as natural
  // rather than as an artefact.
  float beams = max(0.25, uRingArc.x);
  float u = float(seg) / float(uSegments);
  float slot = u * beams;
  float bi = floor(slot);
  float within = fract(slot);
  float drift = uTime * uRingSpin.x * 0.55
              * (hash(vec3(bi * 3.7, fring * 1.9, 0.0)) - 0.5);
  if (within > clamp(uRingArc.y, 0.0, 1.0)) {
    // Off-screen and unlit. Discarding in the vertex stage costs nothing and
    // keeps the gap a real gap rather than a very dim beam.
    vAmp = 0.0;
    vAcross = 0.0;
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    return;
  }

  float seed = hash(vec3(float(seg) * 0.071, fring * 2.3, 0.0));
  // Just enough overlap to hide the seams, no more. At 1.35 + 0.5 the segments
  // piled up into one long smear and the arc read as a drawn stroke; a bar wants
  // to be an OBJECT with a length you can see the end of.
  float lenScale = 1.06 + 0.06 * seed;
  float a0 = float(seg) * span + spin + drift;
  float a1 = a0 + span * lenScale;

  // GREAT CIRCLES ON DIFFERENT AXES, not parallel platters. The film's hologram,
  // and the ophanim imagery it borrows from -- wheels within wheels at every
  // orientation around a central eye -- is not three tilted hoops on nearby
  // planes. Each wheel takes its own axis so they intersect rather than nest,
  // which is what makes a sphere of wheels read as a sphere.
  float radius = mix(uRingRadius.x, uRingRadius.y,
                     hash(vec3(fring * 5.1, 0.0, 0.0))) * uRadius;

  // A FIBONACCI SPHERE, not a hash, for the axes. Six hashed directions came back
  // visibly clustered -- all six leaning the same way, which reads as one wobbly
  // hoop. Points spaced by the golden angle are as far apart as points on a sphere
  // get, and they are deterministic, so the arrangement is designed.
  float k = (fring + 0.5) / float(uRings);
  float az = 1.0 - 2.0 * k;
  float ar = sqrt(max(0.0, 1.0 - az * az));
  float aphi = fring * 2.39996323;
  vec3 axis = normalize(vec3(ar * cos(aphi), ar * sin(aphi), az) + vec3(1e-4));
  vec3 seedv = abs(axis.z) > 0.9 ? vec3(1.0, 0.0, 0.0) : vec3(0.0, 0.0, 1.0);
  vec3 bu = normalize(cross(axis, seedv));
  vec3 bv = cross(axis, bu);

  // A slow precession, so the arrangement never settles into a fixed lattice.
  float pr = uTime * uRingSpin.y * (0.6 + 0.3 * fring);
  mat2 prec = mat2(cos(pr), -sin(pr), sin(pr), cos(pr));

  // BOTH ENDS, in world space. The screen-space width needs the direction the
  // segment actually runs in, and one endpoint cannot say what that is.
  vec3 pa = (cos(a0) * bu + sin(a0) * bv) * radius;
  vec3 pb = (cos(a1) * bu + sin(a1) * bv) * radius;
  pa.xz = prec * pa.xz;
  pb.xz = prec * pb.xz;
  vec3 q = mix(pa, pb, along);

  vec4 ca = project(pa, uAspect);
  vec4 cb = project(pb, uAspect);
  vec2 dir = cb.xy - ca.xy;
  // A degenerate segment -- both ends on the same pixel -- has no direction to be
  // perpendicular to, and normalize() of it is a NaN that takes the whole beam
  // with it. This is the guard that keeps a wheel edge-on from vanishing.
  dir = length(dir) > 1e-6 ? normalize(dir) : vec2(1.0, 0.0);
  vec2 perp = vec2(-dir.y, dir.x);
  // Thickness follows perspective, so a beam on the near side is visibly fatter
  // than the same beam behind the body. A constant width flattened the sphere.
  float halfW = uRingWidth * (0.55 + 0.9 * depthOf(q)) * (0.75 + 0.5 * seed);
  vec4 clip = mix(ca, cb, along);
  clip.xy += perp * across * halfW;

  // AUDIO REACTIVITY. Beams map to bands by position, so different arcs answer to
  // different parts of the voice and the wheel never pulses as a block.
  int band = (int(bi) + ring * 3) % 8;
  // A floor well above zero: a silent wheel must still be a wheel. The voice
  // modulates the beams, it does not switch them on.
  vAmp = 0.55 + 0.45 * clamp(uBands[band], 0.0, 1.0);

  // ITS OWN RATE, and it used to ride the precession. The argument for coupling
  // them was that both describe how slowly the arrangement changes. What it
  // produced was the opposite failure: precession ships at 0.016, so the lifecycle
  // period came out at 1.0 / (0.016 * 0.62) -- about 101 SECONDS. The beams never
  // came and went, they sat in whatever state the page loaded into and drifted over
  // minutes. Measured as brightness variance that made two samples of the same body
  // a minute apart differ by a factor of two.
  float lifePhase = fract(uTime * uRingLife
                        + hash(vec3(fring * 7.7, 1.7, 0.0)) + bi * 0.31);
  vAmp *= smoothstep(0.0, 0.16, lifePhase) * smoothstep(1.0, 0.70, lifePhase);

  // Radial striation along the beam, stable per segment so a bright stretch stays
  // put while the beam travels rather than strobing.
  vAmp *= 0.78 + 0.22 * step(0.5, fract(float(seg) * 0.25));
  vAmp *= 0.62 + 0.38 * uEnergy;
  vAmp *= depthFade(q);
  // The beams flare as the front reaches them, which is what makes the pulse read
  // as leaving the body rather than happening inside it.
  vAmp *= 1.0 + 2.9 * pulse(q) + 0.3 * uSwell;

  vAcross = across;
  // Where this segment sits along its own beam, so the fragment can cap the ends.
  vAlong = clamp(within / max(0.02, clamp(uRingArc.y, 0.0, 1.0)), 0.0, 1.0);
  gl_Position = clip;
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
in float vAcross;
// Every vertex-stage output needs its matching input here. A missing one is a LINK
// error, and a pass whose program fails to build takes the whole renderer down --
// so the symptom is a blank stage, not a beam without end caps.
in float vAlong;
out vec4 oColor;
uniform vec3 uWarm;
uniform vec3 uHot;
uniform float uGain;

void main() {
  // A SOLID, not a thick line, and the difference is four things.
  //
  // The previous version faded symmetrically from the centre to both edges. That
  // is exactly what a soft line looks like -- the eye has nothing to tell it which
  // way the object faces, so it reads the quad as a stroke however wide it is
  // drawn. A bar needs a side that catches light and a side that does not.
  float across = clamp(vAcross, -1.0, 1.0);
  float a = abs(across);

  // 1. A HARD SILHOUETTE. A feathered edge is a glow; an edge that arrives in the
  //    last fifth of the width is a boundary, and a boundary is what makes a shape
  //    look like it displaces space.
  float edge = smoothstep(1.0, 0.80, a);

  // 2. A LIT FACE AND A DARK FACE. Signed across, so one side of every beam is in
  //    shadow. This is the term that does most of the work: it is the only one that
  //    says the object has an orientation.
  float face = mix(0.30, 1.0, 0.5 + 0.5 * across);

  // 3. A SPECULAR BAND, offset toward the lit side rather than centred. Centred, it
  //    is a spine and reads as a filament down the middle of a flat ribbon; offset,
  //    it reads as light grazing a curved surface.
  float spec = exp(-pow((across - 0.42) * 3.2, 2.0));

  // 4. END CAPS. Without them a beam has direction but no extent, and the arc reads
  //    as one continuous stroke rather than as several separate objects.
  float cap = smoothstep(0.0, 0.05, vAlong) * smoothstep(1.0, 0.95, vAlong);

  float shape = edge * cap * (face * 0.68 + spec * 0.85);
  // The highlight runs hotter than the body, which is how a lit edge reads on a
  // warm object.
  vec3 c = mix(uWarm, uHot, clamp(vAmp * vAmp * 0.45 + spec * 0.75, 0.0, 1.0));
  oColor = vec4(c * vAmp * shape * uGain, 1.0);
}`;

// ------------------------------------------------------ circuit shards (SHARD)
//
// "Angular shapes mimicking computer circuitry" is half of what distinguishes
// Animal Logic's JARVIS from their Ultron, who is deliberately organic. So
// these are hard-edged by construction -- every boundary is a step(), never a
// smoothstep() -- because a soft glint would read as fire and the whole point
// is that this is DATA.
//
