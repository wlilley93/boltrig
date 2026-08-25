import { FIELD_GLSL, PROJECT_GLSL, PULSE_GLSL } from "../../canvas/glslCommon";

/**
 * THE GLYPH RINGS, back and on a channel of their own.
 *
 * They were folded into the wheel pass, which is why they went when the wheels
 * were cut into floating beams: one gain, one spin, one lifecycle governing two
 * things that are not the same thing. A wheel is a moving object; a glyph ring is
 * a fixed inscription that the object passes. Sharing a channel meant every
 * adjustment to one silently moved the other, and the only way to get the beams
 * right was to lose the inscriptions.
 *
 * The reference is specific about the relationship, and it is the whole reason
 * this is a separate pass: BETWEEN the glyph layers there is almost nothing --
 * just the glow of the layers themselves. So the rings are thin, dense, concentric
 * and quiet, and the space between them is left empty rather than filled with more
 * particles. Anything that fills those gaps is working against the read.
 */

/** Marks per ring. Dense enough to read as text rather than as ticks. */
export const GLYPH_MARKS = 96;
/** Concentric layers PER BAND. The four rings became two independent bands of
 *  two — inner and outer inscriptions, each with its own channel on the desk —
 *  because four rings driven by one set of dials read as two layers that
 *  cannot be told apart. The pass draws twice; uGlyphBase names the band. */
export const GLYPH_RINGS = 2;
/** Six vertices: each mark is a quad, so it has a width to shade. */
export const GLYPH_VERTS = GLYPH_MARKS * GLYPH_RINGS * 6;

export const GLYPH_VERT = `#version 300 es
precision highp float;

uniform float uTime;
uniform float uAspect;
uniform float uEnergy;
uniform float uRadius;
uniform float uBands[8];
// uSwell, uWaveT and uWaveAmp come from PULSE_GLSL. Declaring them here as well is
// a COMPILE ERROR -- "'uSwell' : redefinition" -- and a pass whose program fails to
// build takes the whole renderer down, so the symptom is a blank stage rather than
// a missing pass. Include the chunk, do not re-declare what it brings.
/** x innermost layer radius, y outermost. Concentric, not scattered. */
uniform vec2 uGlyphRadius;
/** Which band this draw is: 0 for the inner pair, 2 for the outer. Folded
 *  into the GLOBAL layer index so counter-rotation and per-mark seeds are
 *  unchanged from the four-ring original. */
uniform float uGlyphBase;
/** x mark height, y mark width. Both tiny: these are inscriptions, not bars. */
uniform vec2 uGlyphSize;
/** x rotation SPEED, y how much each layer counter-rotates against the last. */
uniform vec2 uGlyphSpin;
/** x how many of the marks are lit at all, y how hard the lit ones vary. */
uniform vec2 uGlyphDensity;

out float vAmp;
out vec2 vCell;
${FIELD_GLSL}
${PROJECT_GLSL}
${PULSE_GLSL}

const int MARKS = ${GLYPH_MARKS};

void main() {
  const float ALONG[6]  = float[6](0.0,  1.0,  0.0,  0.0,  1.0, 1.0);
  const float ACROSS[6] = float[6](-1.0, -1.0, 1.0,  1.0, -1.0, 1.0);
  int v = gl_VertexID;
  int corner = v % 6;
  int idx = v / 6;
  int mark = idx % MARKS;
  int layer = idx / MARKS;
  float flayer = float(layer) + uGlyphBase;
  float along = ALONG[corner];
  float across = ACROSS[corner];

  float tau = 6.28318530718;
  // COUNTER-ROTATING LAYERS. Concentric rings all turning the same way read as one
  // rigid disc; alternating the direction is what makes them separate sheets.
  float dir = mod(flayer, 2.0) < 0.5 ? 1.0 : -1.0;
  float spin = uTime * uGlyphSpin.x * dir * (1.0 + uGlyphSpin.y * flayer);
  float a = (float(mark) / float(MARKS)) * tau + spin;

  // SCREEN-POLAR, not a great circle. This is the one place these differ from the
  // wheels on purpose: an inscription belongs to the plane you are reading it in,
  // so the layers sit flat and face you rather than tumbling through orientations.
  // A tumbling glyph ring reads as debris.
  // LOCAL t across this band's own radius pair — the band owns its span.
  float radius = mix(uGlyphRadius.x, uGlyphRadius.y,
                     float(layer) / max(1.0, ${GLYPH_RINGS}.0 - 1.0)) * uRadius;

  // Which marks are lit. Stable per mark so an inscription stays put while the
  // layer turns -- a re-rolled mask strobes and reads as noise.
  float seed = hash(vec3(float(mark) * 0.117, flayer * 3.1, 0.0));
  if (seed > clamp(uGlyphDensity.x, 0.0, 1.0)) {
    vAmp = 0.0;
    vCell = vec2(0.0);
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    return;
  }

  // Height varies per mark, which is what makes a row of them read as writing
  // rather than as a dashed line.
  float tall = 0.45 + 1.55 * hash(vec3(float(mark) * 0.31, flayer, 4.0));
  vec2 radial = vec2(cos(a), sin(a));
  vec2 tangent = vec2(-radial.y, radial.x);
  // along runs across the ring (the mark's height), across runs along it (width).
  vec2 p2 = radial * (radius + (along - 0.5) * uGlyphSize.x * tall)
          + tangent * across * uGlyphSize.y * 0.5;

  // A z of 0 keeps them on the reading plane; the wave still reaches them so a
  // pulse crossing the body crosses the inscriptions too.
  vec3 q = vec3(p2, 0.0);

  int band = (mark + layer * 2) % 8;
  vAmp = 0.62 + 0.38 * clamp(uBands[band], 0.0, 1.0);
  // How hard the lit marks vary from each other. At 0 they are a uniform ring; the
  // reference has some far brighter than their neighbours, which is what stops it
  // looking printed.
  vAmp *= 1.0 - uGlyphDensity.y * hash(vec3(float(mark) * 0.53, flayer, 7.0));
  vAmp *= 0.70 + 0.30 * uEnergy;
  vAmp *= 1.0 + 2.3 * pulse(q) + 0.28 * uSwell;

  vCell = vec2(along, across);
  gl_Position = project(q, uAspect);
}`;

export const GLYPH_FRAG = `#version 300 es
precision highp float;
in float vAmp;
in vec2 vCell;
out vec4 oColor;
uniform vec3 uWarm;
uniform vec3 uHot;
uniform float uGain;

void main() {
  // Soft along the mark's width and hard across its height, so it reads as a
  // stroke with ends rather than as a dot.
  float across = clamp(abs(vCell.y), 0.0, 1.0);
  float stroke = 1.0 - across * across;
  vec3 c = mix(uWarm, uHot, clamp(vAmp * 0.55, 0.0, 1.0));
  oColor = vec4(c * vAmp * stroke * uGain, 1.0);
}`;
