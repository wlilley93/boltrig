// The interior: velocity-stretched streaks, and the connections between them.
//
// Ebb's JARVIS has "an internal network of connections within the spherical
// centre". Streaks alone are smoke; the LINK pass is what makes it a network.

import { FIELD_GLSL, FRINGE_GLSL, PROJECT_GLSL, PULSE_GLSL } from "../../canvas/glslCommon";

/**
 * Segments per connection. Six is the fewest that reads as a CURVE.
 *
 * A straight line between two particles is a wire, and a nervous system is not
 * wired -- its pathways wander. Four segments still read as a bent stick; six
 * carry an S-bend, which is what makes them look grown rather than routed.
 *
 * It multiplies the pass's vertex count by six, and it is still the cheap pass:
 * two texel fetches per vertex and no state of its own.
 */
export const LINK_SEGMENTS = 6;

// ------------------------------------------------------------ streaks (DRAW)
//
// Two vertices per particle. gl_VertexID even = head, odd = tail. The tail is
// displaced backwards along the SAME curl field the simulation used, so the
// streak lies exactly on the path the particle is taking.
export const DRAW_VERT = `#version 300 es
precision highp float;

uniform sampler2D uState;
uniform float uTime;
uniform float uAspect;
uniform float uEnergy;
uniform float uStreak;
uniform int uGrid;

out float vFade;
out float vSpeed;
${FIELD_GLSL}
${PROJECT_GLSL}
${PULSE_GLSL}

void main() {
  int id = gl_VertexID >> 1;
  int tail = gl_VertexID & 1;
  ivec2 tc = ivec2(id % uGrid, id / uGrid);
  vec4 st = texelFetch(uState, tc, 0);

  vec3 p = st.xyz;
  vec3 v = flow(p, uTime, uEnergy);
  vSpeed = clamp(length(v) * 0.55, 0.0, 1.0);

  // Fade in and out at the ends of life, so particles never pop.
  vFade = smoothstep(0.0, 0.18, st.w) * smoothstep(1.0, 0.72, st.w);
  vFade *= depthFade(p);
  // THE LIMB IS THE SILHOUETTE, and it has to be a hard one.
  //
  // At 0.34 + 0.90 * limb the edge was only 3.6x the middle, which is not
  // enough contrast to carve a sphere out of sixteen thousand streaks: the
  // render read as fur, or as fire, and never as a globe. The reference frame
  // is a shell -- bright all round its edge and see-through through its
  // centre, because the line of sight crosses far more of a shell at the rim
  // than at the middle -- so the ratio wants to be an order of magnitude, not a
  // factor of three.
  //
  // Cheaper and truer than adding geometry. The alternative on the table was
  // drawing actual great circles, which is a second body of code answering a
  // question this one line already answers.
  vFade *= limbMix(p);
  // Embers: what has left the body glints. Everything still in it does not.
  // What has LEFT the body fades out of it. This deliberately brightened
  // escapees, which made the few particles outside the shell the most
  // visible things on screen -- the flares around the edge.
  vFade *= 1.0 - 0.85 * ember(p, 0.98);
  // The wavefront lights what it passes, and a held note keeps a low swell.
  vFade *= 1.0 + 3.2 * pulse(p) + 0.55 * uSwell;

  p -= v * uStreak * float(tail);
  gl_Position = project(p, uAspect);
}`;

// Orange. Hot core to deep amber by speed cubed, so white is reserved for the
// genuinely fast -- and everything below the fringe threshold takes the fringe
// colour instead of a dimmer version of the same hue.
export const DRAW_FRAG = `#version 300 es
precision highp float;
in float vFade;
in float vSpeed;
out vec4 oColor;

uniform vec3 uWarm;
uniform vec3 uHot;
uniform float uGain;
${FRINGE_GLSL}

void main() {
  vec3 core = mix(uWarm, uHot, vSpeed * vSpeed * vSpeed);
  oColor = vec4(fringeShade(vFade, core) * vFade * uGain, 1.0);
}`;

// ------------------------------------------------------------ network (LINK)
//
// Connections are what distinguish a brain from smoke, and the interior had
// none: it was sixteen thousand independent streaks that never touched.
//
// HOW A PROXIMITY GRAPH IS AFFORDABLE HERE. There is no spatial index and there
// is not going to be one. Each particle proposes exactly ONE candidate -- its
// neighbour in the state texture -- and the link is faded out by distance, so a
// pair that happens to be far apart contributes nothing rather than drawing a
// wire across the volume. Texture neighbours are spatially unrelated, so which
// pairs qualify changes constantly as the field moves them, which is precisely
// the flicker of a network finding and dropping connections.
export const LINK_VERT = `#version 300 es
precision highp float;

uniform sampler2D uState;
uniform float uAspect;
uniform int uGrid;
uniform float uLinkRange;
uniform float uTime;
/** x how far the path bows off the straight line, y how fast the bow travels. */
uniform vec2 uLinkBow;

out float vFade;
${FIELD_GLSL}
${PROJECT_GLSL}
${PULSE_GLSL}

const int SEGMENTS = ${LINK_SEGMENTS};

void main() {
  // Six segments per connection, so a pathway can bend. The vertex id now
  // carries three things: which link, which segment of it, and which end of that
  // segment.
  int v = gl_VertexID;
  int id = v / (SEGMENTS * 2);
  int seg = (v % (SEGMENTS * 2)) >> 1;
  int far = v & 1;
  ivec2 tc = ivec2(id % uGrid, id / uGrid);
  ivec2 nc = ivec2((tc.x + 1) % uGrid, tc.y);

  vec4 a = texelFetch(uState, tc, 0);
  vec4 b = texelFetch(uState, nc, 0);

  // Where along the connection this vertex sits, 0 at one particle and 1 at the
  // other.
  float t = float(seg + far) / float(SEGMENTS);
  vec3 straight = mix(a.xyz, b.xyz, t);

  // THE BOW. A curl sample bends the middle of the path while sin(pi*t) pins
  // both ENDS to their particles -- a pathway that let go of its endpoints would
  // read as loose string rather than as a connection between two things. The
  // sample moves with its own clock, so the pathways wander at a rate that is
  // nothing to do with how fast the field is turning over.
  float bow = sin(3.14159265 * t);
  vec3 p = straight
         + curl(straight * 2.3 + vec3(float(id) * 0.017), uTime * uLinkBow.y)
           * uLinkBow.x * bow;

  float d = length(a.xyz - b.xyz);
  // Only genuinely close pairs are a connection. Beyond the range this goes to
  // zero rather than the line being clipped, so nothing pops at the boundary.
  vFade = smoothstep(uLinkRange, uLinkRange * 0.25, d);
  vFade *= min(smoothstep(0.0, 0.2, a.w), smoothstep(0.0, 0.2, b.w));
  vFade *= depthFade(p);
  // The network takes the same silhouette as the streaks. Without this the web
  // was the one pass with no limb, so it filled the see-through middle that
  // every other pass had just been made to leave empty -- and a shell with a
  // solid interior is a ball, not a globe.
  vFade *= limbMix(p);
  vFade *= 1.0 + 3.6 * pulse(p) + 0.5 * uSwell;
  gl_Position = project(p, uAspect);
}`;

export const LINK_FRAG = `#version 300 es
precision highp float;
in float vFade;
out vec4 oColor;
uniform vec3 uWarm;
uniform float uGain;

void main() {
  // Links are structure, not sparks: they stay at the warm end and never reach
  // the hot colour, so the network reads behind the streaks rather than
  // competing with them.
  oColor = vec4(uWarm * vFade * uGain, 1.0);
}`;
