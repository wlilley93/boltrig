// Ultron's neurons: nine pathways out of the centre, each branching to clusters.
//
// WHAT THE REFERENCE ACTUALLY DOES. His birth is not a cloud condensing. It is a
// TREE growing: sparks, then long branching filaments reaching out of a point,
// then tendrils converging on a nucleus, then detail. Read frame by frame the
// dominant shape is a dendrite -- a few thick trunks from the centre, each
// forking repeatedly into finer branches that end in bright clusters.
//
// WHY THE EXISTING PASSES CANNOT DO IT. CRACK draws one line between a particle
// and its TEXTURE neighbour, and texture neighbours are spatially unrelated by
// design -- that is what makes it flicker like a network finding and dropping
// connections. It can never grow a tree, because a tree needs to know its parent
// and the state texture has no room to say.
//
// SO THIS PASS CARRIES NO STATE AT ALL. A node's position is DERIVED from its
// index, by walking the path from the root: a binary-heap index's ancestors are
// its own bits read from the top, so the walk is a loop of at most DEPTH steps
// with no memory and no second texture. The whole tree is a function of
// (trunk, node, time), which is also why it costs 558 vertices instead of
// 32768 -- the field is the expensive thing here and this is not the field.
//
// IT IS DETERMINISTIC AND IT MOVES. Every hash is keyed on the node's own index,
// so a branch keeps its shape frame to frame rather than crawling; the movement
// comes from ONE curl sample per node, which bends the whole subtree below it
// because children are placed relative to their parent. That is what makes it
// breathe like something alive instead of vibrating like noise.

import { FIELD_GLSL, PROJECT_GLSL, PULSE_GLSL } from "../canvas/glslCommon";

/** Core pathways out of the centre. Nine, from the reference. */
export const DENDRITE_TRUNKS = 9;

/**
 * Branch levels. Five gives 31 segments a trunk, so 279 in total.
 *
 * Six would be 63 and read as a bush rather than a nervous system: the
 * reference's branches fork a handful of times and then END, in a cluster. The
 * ending is the point.
 */
export const DENDRITE_DEPTH = 5;

/** Segments per trunk: a full binary tree of DEPTH levels. */
export const DENDRITE_SEGMENTS = (1 << DENDRITE_DEPTH) - 1;

export const DENDRITE_VERT = `#version 300 es
precision highp float;

uniform float uTime;
uniform float uAspect;
uniform float uEnergy;
uniform float uRadius;
/** x root length, y fork angle, z per-level taper, w wander amplitude. */
uniform vec4 uDend;
/** x cluster glow at the tips, y how much a voice grows the tree. */
uniform vec2 uDendTip;

out float vFade;
out float vAlong;
out float vDepth;
${FIELD_GLSL}
${PROJECT_GLSL}
${PULSE_GLSL}

const int TRUNKS = ${DENDRITE_TRUNKS};
const int DEPTH = ${DENDRITE_DEPTH};
const int SEGS = ${DENDRITE_SEGMENTS};

/** Rodrigues, for bending a direction around an axis by an angle. */
vec3 turn(vec3 v, vec3 axis, float a) {
  float c = cos(a), s = sin(a);
  return v * c + cross(axis, v) * s + axis * dot(axis, v) * (1.0 - c);
}

/**
 * The nine trunk directions, on a Fibonacci sphere.
 *
 * Hashed directions came back visibly clustered when the ring pass tried it --
 * nine points spaced by the golden angle are as far apart as nine points on a
 * sphere get, and they are deterministic, so the arrangement is designed rather
 * than drawn.
 */
vec3 trunkDir(int trunk) {
  float k = (float(trunk) + 0.5) / float(TRUNKS);
  float z = 1.0 - 2.0 * k;
  float r = sqrt(max(0.0, 1.0 - z * z));
  float phi = float(trunk) * 2.39996323;
  return normalize(vec3(r * cos(phi), r * sin(phi), z) + vec3(1e-4));
}

void main() {
  int seg = gl_VertexID >> 1;
  int end = gl_VertexID & 1;
  int trunk = seg / SEGS;
  // 1-based heap index: 1 is the root, node n's parent is n >> 1, and the bits
  // of n read from the top ARE the path down to it.
  int node = seg % SEGS + 1;

  int d = 0;
  for (int m = node; m > 1; m >>= 1) d++;

  // GROWTH. A voice extends the tree rather than brightening it, which is the
  // difference between something reacting and something growing.
  float grow = 1.0 + uDendTip.y * uEnergy;

  vec3 pos = vec3(0.0);
  vec3 dir = trunkDir(trunk);
  vec3 parent = pos;
  float len = uDend.x * uRadius * grow;

  for (int i = 1; i <= DEPTH; i++) {
    if (i > d) break;
    int anc = node >> (d - i);
    // Which side of its parent this ancestor is: its lowest bit.
    float side = float(anc & 1) * 2.0 - 1.0;
    float h = hash(vec3(float(anc) * 0.37, float(trunk) * 1.7, 3.0));
    vec3 axis = normalize(vec3(
      hash(vec3(float(anc) * 0.11, float(trunk), 7.0)) - 0.5,
      hash(vec3(float(anc) * 0.19, float(trunk), 11.0)) - 0.5,
      hash(vec3(float(anc) * 0.29, float(trunk), 13.0)) - 0.5) + vec3(1e-4));
    dir = normalize(turn(dir, axis, uDend.y * side * (0.55 + 0.9 * h)));
    parent = pos;
    pos += dir * len;
    // ONE curl sample per node, applied AFTER the step, so the whole subtree
    // below inherits the bend. A per-vertex wobble would shear every segment
    // independently and read as noise on a wire rather than as a limb moving.
    pos += curl(pos * 1.7 + vec3(float(trunk)), uTime * 0.35) * uDend.w;
    len *= uDend.z;
  }

  vec3 p = end == 0 ? parent : pos;

  vAlong = float(end);
  vDepth = float(d) / float(DEPTH);
  // Thinner and dimmer with depth, then a CLUSTER at the tips: the reference's
  // branches end in a bright knot, and without it the tree just fades out.
  vFade = mix(1.0, 0.45, vDepth);
  if (d >= DEPTH) vFade *= 1.0 + uDendTip.x;
  vFade *= depthFade(p);
  // NO LIMB TERM. limbMix darkens whatever faces the viewer so a SHELL reads as
  // a sphere, and this is not a shell -- it is the armature at the centre, which
  // in the reference is the brightest thing there is. Applying it made the tree
  // three tenths of its brightness exactly where it should be strongest.
  //
  // outerFade still applies: a branch that reaches past the body belongs to the
  // distant outer sphere and should dim like everything else out there.
  vFade *= outerFade(p);
  vFade *= 1.0 + 3.2 * pulse(p) + 0.5 * uSwell;

  gl_Position = project(p, uAspect);
}`;

export const DENDRITE_FRAG = `#version 300 es
precision highp float;
in float vFade;
in float vAlong;
in float vDepth;
out vec4 oColor;

uniform vec3 uWarm;
uniform vec3 uHot;
uniform float uGain;
/** x beads per segment, y how much of each bead is lit. */
uniform vec2 uBead;

void main() {
  // BEADED, NOT SMOOTH. Close up, the reference's filaments are not lines: they
  // are runs of small bright marks with brighter knots between them -- data on a
  // wire. A solid line at this brightness reads as a laser, which is the one
  // thing it must not look like.
  float bead = step(fract(vAlong * uBead.x), uBead.y);
  if (bead < 0.5) discard;
  // Tips run hot. The trunks are the deep blue he sits in; the far ends are where
  // the light is, which is what gives the tree a direction to grow in.
  // BIASED HOT FROM THE ROOT. uWarm is near-navy -- 0.02, 0.26, 0.98 -- so a
  // trunk shaded with it is almost black in two channels, and the tree read as a
  // dark scribble however high the gain went. In the reference the filaments are
  // bright along their whole length and brighter still at the nodes; the ramp
  // says which END is hotter, not whether the thing is lit at all.
  vec3 c = mix(uWarm, uHot, 0.55 + 0.45 * vDepth);
  // NO FRINGE, for the reason the ring pass gives. The fringe rule exists
  // because sixteen thousand additive particles climb one colour ramp together
  // until the middle of the frame goes white. 279 segments do not stack, so they
  // cannot cause that -- and applying it anyway puts most of them below the
  // outer threshold and draws them as NOTHING. That is not a theory: it is what
  // happened on the first render of this pass, and it is what happened to the
  // rings before it. Fix the defect where the defect is.
  oColor = vec4(c * vFade * uGain, 1.0);
}`;
