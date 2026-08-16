#version 300 es
// =============================================================================
// jarvis.frag - the HUD instrument variant of the Familiar.
//
// A flat vector instrument, NOT a creature: concentric counter-rotating rings
// of dashes, gauges and irregular arc chunks around a hot white core, over a
// field of circuit traces. It is a sibling of familiar.frag (the volumetric
// being), not a replacement - the two share the state seam and nothing else.
//
// Everything is drawn analytically from the fragment's polar coordinates. There
// are no textures and no DOM: the state labels are rendered from a bit-packed
// 5x7 glyph atlas compiled into this file, so the desktop GLES host and the
// browser draw byte-identical frames.
//
// Four behaviours ride on top of the resting dial, crossfaded by weight so the
// instrument never snaps between modes:
//
//   SPEAKING   the core pulses on the voice; a band-driven hairline fan rises
//              between the iris and the mid ring; shock rings leave the core.
//   THINKING   the circuit field lights up - pulses run the traces of a board
//              that is only visible when current is flowing through it.
//   LISTENING  incoming mic amplitude is drawn as radial hairlines that
//              accumulate clockwise from 12 o'clock. When the head returns to
//              12 the whole trace clears and the sweep begins again.
//   WORKING    a bold dashed arc sweeps the gauge ring; the bottom label
//              becomes a live numeric readout.
//
// CONVENTIONS
//   p       fragment position, origin at the dial centre, normalised so that
//           one unit is the SHORT side of the viewport (so p.x spans -0.5..0.5
//           and, in portrait, p.y runs past it - that overspill is where the
//           circuit field lives).
//   turn    angle in TURNS, 0 at 12 o'clock, increasing CLOCKWISE. Every radius
//           and speed below is written in these units.
//   PX      one device pixel in p units. All antialiasing is derived from this
//           rather than fwidth(), because most of the drawing happens inside
//           hashed branches where derivatives are undefined.
// =============================================================================
precision highp float;
precision highp int;

out vec4 fragColor;

// --- host ------------------------------------------------------------------
uniform vec2  iResolution;
uniform float iTime;

// --- state weights (host-smoothed, 0..1, need not sum to 1) -----------------
uniform float uListening;
uniform float uThinking;
uniform float uWorking;
uniform float uSpeaking;

// --- drive ------------------------------------------------------------------
uniform float uLevel;       // 0..1 amplitude of whichever voice is live
uniform float uOnset;       // 0..1 spectral flux of the outgoing voice
uniform vec4  uBands[2];    // 8 log-spaced bands of the outgoing voice
uniform vec4  uWave[32];    // 128-sample circular buffer of incoming mic level
uniform float uWaveHead;    // 0..1 write cursor, in turns clockwise from 12
uniform float uReadout;     // number under the dial while WORKING
uniform float uReduced;     // 1 = prefers-reduced-motion: still frame, no drift

// --- identity ---------------------------------------------------------------
uniform vec3  uAccent;      // the instrument's colour; everything derives here
uniform float uScale;       // dial size multiplier (1.0 = the tuned default)

// --- the inner life ---------------------------------------------------------
// The server phenotype (decision 0013), 0..1 each, smoothed by the host. This
// is the whole point of the instrument: without it a HUD dial is decoration
// that spins at a constant rate no matter what the machine is doing.
//
// uPhenoFresh is 0 when the relay is absent or stale, and then every scalar
// below is at its neutral rest value. The dial must NOT invent a mood to fill
// the silence - that is exactly the lie this variant exists to avoid. It shows
// "no signal" instead (the outer ring falls away).
uniform float uValence;      // palette: sunk navy -> electric violet
uniform float uArousal;      // rotation rate (folded into uSpin by the host)
uniform float uIrritation;   // the one non-blue; also jags the arc chunks
uniform float uFatigue;      // dims, and slows (also folded into uSpin)
uniform float uAttention;    // contrast and the unbroken circle's authority
uniform float uLuminosity;   // core emission
uniform float uTension;      // gauge density and a fine nervous jitter
uniform float uPhenoFresh;   // 1 = a live relay is behind these numbers
//
// NOT here: social, attachment and buoyancy. They exist in the phenotype
// contract but the instrument has no honest reading for them, and a uniform
// that is uploaded every frame and read by nothing looks wired when it is not.
// Reserved should mean ABSENT. (Buoyancy is not unused - it is a bob applied as
// a CSS transform on the stage, because the SVG labels are registered to the
// dial centre and anything that moves the dial has to move the DOM with it.)

// --- real readings ----------------------------------------------------------
// Two of the tracks are gauges, not decoration: an arc that grows clockwise
// from 12 o'clock by a fraction of a real ceiling.
//
// `Known` is 0 when there is no ceiling or no current usage figure. Then the
// track draws as a dashed GHOST and no fill at all — a gauge resting at empty
// would be claiming "nothing spent", which is a different and more expensive
// claim than "no reading". Never let the fill through without the flag.
uniform float uBudgetFill;   // 0..1+ money against the binding money ceiling
uniform float uBudgetKnown;
uniform float uBudgetHard;   // 1 = crossing it actually stops work
uniform float uTokenFill;    // 0..1+ tokens against the binding token ceiling
uniform float uTokenKnown;

// --- live work ---------------------------------------------------------------
// How much of the agent's actual DAG is in flight (tools pending, subagents
// running, workflow steps running) and how much of it went wrong. This is what
// energises the circuit board. No work means a dark board - the load is never
// padded to make the instrument look busy.
uniform float uWorkLoad;
uniform float uWorkFail;

// Accumulated rotation phase, in the same units the ring speeds expect. The
// host integrates it (phase += dt * rate) rather than the shader deriving it
// from iTime * rate: rate moves with arousal and fatigue, and t * rate would
// make every mood shift jump or rewind the rings.
uniform float uSpin;

// How far the rotation phase advanced THIS frame. Used to smear rotating
// elements by the distance they actually travel, which is the only way thin
// lines can spin fast without strobing - see SMEAR below.
uniform float uSpinDelta;

// Pointer parallax, in p units. Applied ONLY to the circuit field.
//
// Parallaxing the dial itself would slide it out from under the SVG label
// overlay, which is registered to the dial centre — the same trap buoyancy hit.
// Moving only the background is also the more honest depth cue: the board is
// behind the instrument, so it is the thing that should shift.
uniform vec2 uParallax;

// 1 = this shader is feeding an offscreen bloom pipeline, so it must output
// LINEAR light and leave the grade to the composite pass. 0 = it is drawing
// straight to the screen and owns its own grade.
//
// The desktop GLES host has no framebuffers and always uses 0, which is why
// the single-pass grade below cannot simply be deleted.
uniform float uHDR;

// --- genotype ----------------------------------------------------------------
// Eight genes (see JarvisGenotype.ts). They move counts, ratios and phase so
// one agent's instrument is recognisably its own. They deliberately do NOT move
// radii or colour: a dial whose gauges wander is a worse dial, however
// distinctive. Absent (all zero except the fills and skew) is the hand-tuned
// instrument.
uniform vec4 uGene[2];
float gene(int i) { return uGene[i >> 2][i & 3]; }
const int G_IRIS_SEG  = 0;
const int G_DASH_SEG  = 1;
const int G_ARC1_FILL = 2;
const int G_ARC2_FILL = 3;
const int G_SPEED     = 4;
const int G_CHUNK     = 5;
const int G_TICKS     = 6;

const float PI  = 3.14159265359;
const float TAU = 6.28318530718;

// One device pixel in p units. Assigned once, at the top of main().
float PX;

// =============================================================================
// GLYPH ATLAS  (generated - see scripts/gen_font.py, do not hand-edit)
//
// 5x7 uppercase bitmap font, one uvec2 per glyph: .x holds rows 0..3 and .y
// rows 4..6, each row 5 bits with the MSB leftmost. Indices are the glyph ids
// the label tables below are written against:
//   0..25  A-Z      26..35  0-9      36 space   37 period   38 hyphen
// =============================================================================
const int GLYPH_COUNT = 39;
const uvec2 FONT[39] = uvec2[39](
    uvec2(0xFC62Eu, 0x4631u),  //  0  A
    uvec2(0xF463Eu, 0x7A31u),  //  1  B
    uvec2(0x8422Eu, 0x3A30u),  //  2  C
    uvec2(0x8C63Eu, 0x7A31u),  //  3  D
    uvec2(0xF421Fu, 0x7E10u),  //  4  E
    uvec2(0xF421Fu, 0x4210u),  //  5  F
    uvec2(0xBC22Eu, 0x3E31u),  //  6  G
    uvec2(0xFC631u, 0x4631u),  //  7  H
    uvec2(0x2108Eu, 0x3884u),  //  8  I
    uvec2(0x10847u, 0x3242u),  //  9  J
    uvec2(0xC5251u, 0x4654u),  // 10  K
    uvec2(0x84210u, 0x7E10u),  // 11  L
    uvec2(0xAD771u, 0x4631u),  // 12  M
    uvec2(0x9D731u, 0x4631u),  // 13  N
    uvec2(0x8C62Eu, 0x3A31u),  // 14  O
    uvec2(0xF463Eu, 0x4210u),  // 15  P
    uvec2(0x8C62Eu, 0x3655u),  // 16  Q
    uvec2(0xF463Eu, 0x4654u),  // 17  R
    uvec2(0x7420Fu, 0x7821u),  // 18  S
    uvec2(0x2109Fu, 0x1084u),  // 19  T
    uvec2(0x8C631u, 0x3A31u),  // 20  U
    uvec2(0x8C631u, 0x1151u),  // 21  V
    uvec2(0xAC631u, 0x4775u),  // 22  W
    uvec2(0x21151u, 0x4544u),  // 23  X
    uvec2(0x21151u, 0x1084u),  // 24  Y
    uvec2(0x2083Fu, 0x7E08u),  // 25  Z
    uvec2(0xACE2Eu, 0x3A39u),  // 26  0
    uvec2(0x21184u, 0x3884u),  // 27  1
    uvec2(0x1062Eu, 0x7D04u),  // 28  2
    uvec2(0x1105Fu, 0x3A21u),  // 29  3
    uvec2(0x928C2u, 0x085Fu),  // 30  4
    uvec2(0x0FA1Fu, 0x3A21u),  // 31  5
    uvec2(0xF4106u, 0x3A31u),  // 32  6
    uvec2(0x2083Fu, 0x2108u),  // 33  7
    uvec2(0x7462Eu, 0x3A31u),  // 34  8
    uvec2(0x7C62Eu, 0x3041u),  // 35  9
    uvec2(0x00000u, 0x0000u),  // 36  space
    uvec2(0x00000u, 0x3180u),  // 37  .
    uvec2(0x70000u, 0x0000u)   // 38  -
);

// Label ids. LABEL_NUM renders uReadout instead of a fixed string; LABEL_NONE
// draws nothing, which is how the host hides a line without a second uniform.
const int LABEL_SPEAKING  = 0;
const int LABEL_LISTENING = 1;
const int LABEL_THINKING  = 2;
const int LABEL_WORKING   = 3;
const int LABEL_STANDBY   = 4;
const int LABEL_YOURTURN  = 5;
const int LABEL_NUM       = 6;
const int LABEL_NONE      = 7;

uniform int uLabelTop;      // word on the upper arc
uniform int uLabelBottom;   // word (or readout) on the lower arc
uniform float uLabelTopAmt;
uniform float uLabelBottomAmt;

const int L_SPEAKING [8] = int[8](18,15, 4, 0,10, 8,13, 6);
const int L_LISTENING[9] = int[9](11, 8,18,19, 4,13, 8,13, 6);
const int L_THINKING [8] = int[8](19, 7, 8,13,10, 8,13, 6);
const int L_WORKING  [7] = int[7](22,14,17,10, 8,13, 6);
const int L_STANDBY  [7] = int[7](18,19, 0,13, 3, 1,24);
const int L_YOURTURN [9] = int[9](24,14,20,17,36,19,20,17,13);

// =============================================================================
// DIAL GEOMETRY
//
// Radii are in p units at uScale == 1. They were read off the reference frames
// rather than invented, which is why they are not evenly spaced: the eye reads
// an instrument by its irregular rhythm, and an even ladder looks like a
// target. Speeds are in turns/second; the SIGN is the whole point - adjacent
// rings must counter-rotate or the dial reads as one spinning wheel.
// =============================================================================
const float R_CORE      = 0.019;  // solid white centre
const float R_IRIS      = 0.100;  // chunky dashed ring hugging the core
const float R_FAN_IN    = 0.119;  // hairline fan, inner end
const float R_FAN_OUT   = 0.192;  // hairline fan, full-amplitude end
const float R_DASH2     = 0.226;  // second chunky dashed ring
const float R_HAIRCIRC  = 0.250;  // the one complete, unbroken circle
const float R_GAUGE     = 0.288;  // fine tick gauge + the working sweep
const float R_ARC1      = 0.322;
const float R_ARC2      = 0.368;
const float R_COIL_IN   = 0.296;  // arc-reactor coil pack, inner edge
const float R_COIL_OUT  = 0.318;  // arc-reactor coil pack, outer edge
const float R_CONTAIN   = 0.386;  // containment ring, between ARC2 and OUTER
const float R_OUTER     = 0.403;  // outermost ring; the labels sit on it
const float R_SWEEP_OUT = 0.462;  // the listening sweep runs PAST the outer ring
const float R_SPOKE_IN  = 0.258;  // resting long-spoke layer, inner end
const float R_G_BUDGET  = 0.428;  // gauge track: money. Outside everything, so
                                  // the headline reading owns the silhouette.
const float R_G_TOKEN   = 0.238;  // gauge track: tokens

const float W_IRIS      =  0.030;
const float W_DASH2     = -0.022;
const float W_GAUGE     =  0.045;
const float W_ARC1      = -0.035;
const float W_ARC2      =  0.018;
const float W_OUTER     = -0.012;

// =============================================================================
// PRIMITIVES
// =============================================================================

float hash11(float n) { return fract(sin(n * 127.1) * 43758.5453123); }
float hash21(vec2 p)  { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123); }
vec2  hash22(vec2 p)  {
    return fract(sin(vec2(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3))))
                 * 43758.5453123);
}

// A line of half-width halfW centred on d == 0. Sub-pixel lines are widened to
// one pixel and dimmed by the same factor instead of being allowed to alias in
// and out of existence - this dial is almost entirely sub-pixel hairlines, so
// without the energy term the fine gauges shimmer as they rotate.
//
// smoothstep's edges are always passed low-then-high: GLSL leaves the result
// undefined when edge0 >= edge1, so the usual reversed-edge shorthand is a
// driver-dependent coin flip rather than a shortcut.
// Arc length the element being drawn travels in one frame, at its own radius.
// Set before each rotating ring and reset to 0 for anything static.
float SMEAR;

float lineAA(float d, float halfW) {
    // Two independent coverage problems, one term. A line thinner than a pixel
    // covers only part of it; a line that moves covers a band wider than
    // itself for only part of the frame. Widening to whichever is larger and
    // dimming by the same ratio conserves energy in both cases - which is what
    // stops a fast ring from strobing into a wagon-wheel at high arousal, and
    // stops a fine gauge from shimmering when it is still.
    float w = max(halfW + SMEAR * 0.5, PX * 0.5);
    float m = 1.0 - smoothstep(w - PX * 0.7, w + PX * 0.7, abs(d));
    return m * min(1.0, halfW / w);
}

/** Arc length per frame for a ring of angular speed `w` at radius `r`. */
float smearAt(float w, float r) { return abs(w * uSpinDelta) * TAU * r; }

// 1 inside [lo, hi], antialiased on both edges.
float bandAA(float x, float lo, float hi) {
    return smoothstep(lo - PX * 0.7, lo + PX * 0.7, x)
         * (1.0 - smoothstep(hi - PX * 0.7, hi + PX * 0.7, x));
}

// Per-element near-field skirt. It widens each stroke individually, which is
// NOT bloom - light never crosses between elements, so a dense cluster glows no
// more than a lone hairline. When the real bloom pipeline is running it does
// that job properly, and this is pulled back to a tight core glow so the two
// do not stack into mush. SKIRT is set once, at the top of main().
float SKIRT;
float soft(float d, float falloff) {
    return exp(-abs(d) / max(falloff, 1e-5)) * SKIRT;
}

float segDist(vec2 p, vec2 a, vec2 b, out float along) {
    vec2 pa = p - a, ba = b - a;
    float h = clamp(dot(pa, ba) / max(dot(ba, ba), 1e-9), 0.0, 1.0);
    along = h;
    return length(pa - ba * h);
}

float bandAt(int i) { return uBands[i >> 2][i & 3]; }

// The wave buffer is 128 floats packed as 32 vec4s: sample i lives in
// component (i & 3) of vec4 (i >> 2).
float waveSample(int i) {
    i = clamp(i, 0, 127);
    return uWave[i >> 2][i & 3];
}

// =============================================================================
// RING PATTERNS
//
// Each returns a 0..1 mask for the ANGULAR pattern only; the caller multiplies
// by its own radial mask. Angular distances are converted to arc length before
// antialiasing so a dash on the outer ring gets the same edge softness as one
// near the core, and so nothing blows up at the 12 o'clock seam the way an
// fwidth() of a wrapped angle does.
// =============================================================================

// Evenly spaced dashes: n slots, `duty` of each slot lit.
float dashRing(float turn, float t, float r, float n, float duty, float speed) {
    float rot  = turn - t * speed;
    float u    = abs(fract(rot * n) - 0.5) / n;   // distance from slot centre, in turns
    float edge = duty * 0.5 / n;
    return lineAA(u * TAU * r, edge * TAU * r);
}

// Irregular arcs: most slots are empty and the survivors differ in length and
// brightness. This is what separates an instrument from a wheel of dashes.
float chunkRing(float turn, float t, float r, float n, float speed, float seed,
                float fill) {
    float rot  = turn - t * speed;
    float slot = floor(rot * n);
    float h0   = hash11(slot * 1.37 + seed);
    if (h0 > fill) return 0.0;

    float duty = mix(0.20, 0.94, hash11(slot * 2.11 + seed + 5.0));
    float u    = abs(fract(rot * n) - 0.5) / n;
    float edge = duty * 0.5 / n;
    float m    = lineAA(u * TAU * r, edge * TAU * r);
    return m * mix(0.22, 1.0, hash11(slot * 3.71 + seed + 17.0));
}

// A gauge of short radial ticks standing on radius r0.
float tickRing(float turn, float r, float t, float r0, float len, float n,
               float speed, float halfW) {
    float rot = turn - t * speed;
    float u   = abs(fract(rot * n) - 0.5) / n;
    return lineAA(u * TAU * r, halfW) * bandAA(r, r0, r0 + len);
}

// Arc-reactor coil packs: n winding blocks standing in a radial band.
//
// The striation across the band is the whole point. A block of solid colour at
// this radius is just a fat dash; ribbed across its width it reads as wound
// wire, which is the one detail that makes the dial an arc reactor rather than
// another ring of arcs.
float coilPack(float turn, float r, float t, float rIn, float rOut, float n,
               float speed, float duty) {
    float rot  = turn - t * speed;
    float u    = abs(fract(rot * n) - 0.5) / n;
    float edge = duty * 0.5 / n;
    float body = lineAA(u * TAU * r, edge * TAU * r) * bandAA(r, rIn, rOut);
    float span = max(rOut - rIn, 1e-4);
    float wind = 0.5 + 0.5 * cos((r - rIn) / span * TAU * 6.0);
    return body * mix(0.42, 1.0, wind);
}

// =============================================================================
// GAUGES
//
// A track with an origin tick at 12 o'clock and an arc that grows clockwise.
// The arc does NOT rotate - a gauge that drifts is not a gauge - which is why
// this takes `turn` directly and never `spin`.
//
// Over-ceiling is drawn rather than clamped: the arc wraps past 12 and overdraws
// in red, so 103% looks different from 100%. Hiding an overrun in a pinned
// full circle is the one failure mode that would make the reading worthless.
// =============================================================================
vec3 gauge(float turn, float r, float radius, float fill, float known,
           float hard, vec3 accent, float t) {
    // Cheap reject. This bound must cover EVERY track this function draws, not
    // just the main one: rejecting on the main track alone silently made the
    // overrun lap at radius + 0.019 unreachable, so an over-ceiling gauge
    // rendered identically to a full one.
    if (r < radius - 0.016 || r > radius + 0.032) return vec3(0.0);

    float track = bandAA(r, radius - 0.0035, radius + 0.0035);
    vec3 acc = vec3(0.0);

    // Ghost track: dashed and dim, always present so the gauge is legible AS a
    // gauge even at zero, and so "no reading" still shows where the reading
    // would be.
    float ghostDash = dashRing(turn, 0.0, radius, 60.0, 0.45, 0.0);
    acc += accent * track * ghostDash * mix(0.14, 0.10, known);

    // Origin tick at 12 o'clock: without it a part-filled arc has no datum and
    // the eye cannot tell a 10% fill from a 90% one that started elsewhere.
    float atTop = 1.0 - smoothstep(0.0, 0.010, min(turn, 1.0 - turn));
    acc += mix(accent, vec3(1.0), 0.6)
         * bandAA(r, radius - 0.008, radius + 0.008) * atTop * 0.55;

    if (known < 0.5) return acc;

    // Lap 1: 0..100%.
    float lit = 1.0 - smoothstep(0.0, 0.004, turn - min(fill, 1.0));

    // Colour is the first warning channel, and a SHAPE change is the second:
    // past 85% the solid arc breaks into dashes that tighten as the ceiling
    // approaches. Irritation-magenta, budget-red and failure-red can all be on
    // screen at once, so a warning that is only a hue collapses into the rest
    // of the palette - and is invisible to a red-blind reader either way.
    float warn = smoothstep(0.85, 1.0, fill);
    float broken = mix(1.0, dashRing(turn, 0.0, radius, mix(40.0, 90.0, warn), 0.55, 0.0),
                       step(0.001, warn));
    lit *= mix(1.0, broken, warn);

    vec3 hot = mix(vec3(1.0), vec3(1.0, 0.35, 0.22), smoothstep(0.7, 1.0, fill));
    acc += hot * track * lit * 0.85;
    acc += hot * soft(r - radius, 0.010) * lit * 0.18;

    // Lap 2: the overrun, on its OWN track just outside the first. Drawing it
    // over lap 1 was not enough - at 114% the arc is already red and closed, so
    // the overrun read as a full gauge and the difference that matters was the
    // one thing invisible. Stacked outward it is unmistakably off the end of
    // the scale, and it pulses, because an overrun should nag.
    if (fill > 1.0) {
        float overR = radius + 0.019;
        float overTrack = bandAA(r, overR - 0.0028, overR + 0.0028);
        float over = 1.0 - smoothstep(0.0, 0.004, turn - min(fill - 1.0, 1.0));
        vec3 red = vec3(1.0, 0.18, 0.16);
        acc += red * overTrack * over * (0.9 + 0.35 * sin(t * 6.0));
        acc += red * soft(r - overR, 0.011) * over * 0.34;
    }

    // A hard stop is a wall: a bright bar across the track at the ceiling.
    // A soft ceiling gets no bar, because nothing actually stops there.
    if (hard > 0.5) {
        acc += vec3(1.0) * bandAA(r, radius - 0.011, radius + 0.011) * atTop * 0.8;
    }
    return acc;
}

// =============================================================================
// TEXT
//
// Straight-line layout in an unrolled (arc length, radius) frame. At a 7px cap
// height on a 0.4 radius the curvature across one glyph is far below a pixel,
// so no per-glyph rotation is needed. `flip` mirrors both axes for the lower
// arc, which is what keeps bottom labels upright instead of upside down.
// =============================================================================

float glyphMask(int gid, vec2 uv) {
    if (gid < 0 || gid >= GLYPH_COUNT) return 0.0;
    if (uv.x < 0.0 || uv.x >= 1.0 || uv.y < 0.0 || uv.y >= 1.0) return 0.0;
    int cx = int(uv.x * 5.0);
    int ry = 6 - int(uv.y * 7.0);          // row 0 is the TOP row
    uvec2 g = FONT[gid];
    uint bits = (ry < 4) ? (g.x >> uint(5 * ry)) : (g.y >> uint(5 * (ry - 4)));
    bits &= 31u;
    return float((bits >> uint(4 - cx)) & 1u);
}

int labelLen(int lab) {
    if (lab == LABEL_SPEAKING)  return 8;
    if (lab == LABEL_LISTENING) return 9;
    if (lab == LABEL_THINKING)  return 8;
    if (lab == LABEL_WORKING)   return 7;
    if (lab == LABEL_STANDBY)   return 7;
    if (lab == LABEL_YOURTURN)  return 9;
    if (lab == LABEL_NUM)       return 4;   // "N.NN"
    return 0;
}

int labelGlyph(int lab, int i) {
    if (lab == LABEL_SPEAKING)  return L_SPEAKING [i];
    if (lab == LABEL_LISTENING) return L_LISTENING[i];
    if (lab == LABEL_THINKING)  return L_THINKING [i];
    if (lab == LABEL_WORKING)   return L_WORKING  [i];
    if (lab == LABEL_STANDBY)   return L_STANDBY  [i];
    if (lab == LABEL_YOURTURN)  return L_YOURTURN [i];
    if (lab == LABEL_NUM) {
        float v = clamp(uReadout, 0.0, 9.99);
        int ones  = int(floor(v));
        int tenth = int(floor(fract(v) * 10.0));
        int hund  = int(floor(fract(v * 10.0) * 10.0));
        if (i == 0) return 26 + ones;
        if (i == 1) return 37;              // period
        if (i == 2) return 26 + tenth;
        return 26 + hund;
    }
    return 36;
}

// Cap height 7 units; glyphs are 5 wide with an advance of 9, which is the wide
// letter-spacing the reference labels have. 2x2 supersampled - the glyphs are
// hard-edged bitmaps, and at this size nothing cheaper is legible.
float arcText(float r, float turn, int lab, float radius, float centreTurn,
              float capH, bool flip) {
    int n = labelLen(lab);
    if (n == 0) return 0.0;

    float unit  = capH / 7.0;
    float adv   = 9.0 * unit;
    float width = float(n) * adv;

    // Unroll to a local frame in world units.
    float dTurn = turn - centreTurn;
    dTurn -= floor(dTurn + 0.5);            // wrap to -0.5..0.5, seam-safe
    float x = dTurn * TAU * radius;
    float y = r - radius;
    if (flip) { x = -x; y = -y; }

    x += width * 0.5;                       // left edge of the run
    if (x < -adv || x > width + adv) return 0.0;
    if (abs(y) > capH) return 0.0;

    int   gi = int(floor(x / adv));
    if (gi < 0 || gi >= n) return 0.0;
    float gx = (x - float(gi) * adv) / (5.0 * unit);
    float gy = (y + capH * 0.5) / capH;
    int   gid = labelGlyph(lab, gi);

    float sx = PX / (5.0 * unit) * 0.35;
    float sy = PX / capH * 0.35;
    float acc = glyphMask(gid, vec2(gx - sx, gy - sy))
              + glyphMask(gid, vec2(gx + sx, gy - sy))
              + glyphMask(gid, vec2(gx - sx, gy + sy))
              + glyphMask(gid, vec2(gx + sx, gy + sy));
    return acc * 0.25;
}

// =============================================================================
// CIRCUIT FIELD
//
// The board is always there and almost invisible; THINKING is current flowing
// through it. Each cell holds a two-segment polyline whose first leg points
// along the radial direction snapped to the nearest of eight compass headings,
// then elbows 45 degrees - that snap is what makes the traces radiate from the
// dial like a die shot rather than scatter like noise.
// =============================================================================
// `energy` is how much of the board is live (0..1) and `fail` how much of that
// work went wrong. Energy GATES which traces light rather than just brightening
// all of them: each cell has a stable hash, and a cell energises only when its
// hash falls under the load. So traces switch on one at a time as concurrency
// climbs, and the same trace lights for the same work every time - the board
// looks like a board being used, not a board being dimmed up and down.
vec3 circuitField(vec2 p, float t, float energy, float fail, vec3 accent) {
    const float CELL = 0.160;
    vec3 acc = vec3(0.0);
    vec2 g   = p / CELL;
    vec2 id0 = floor(g);

    for (int j = -1; j <= 1; j++) {
        for (int i = -1; i <= 1; i++) {
            vec2 id = id0 + vec2(float(i), float(j));
            float h = hash21(id);
            if (h < 0.34) continue;                       // sparse board

            vec2 c = (id + 0.5 + (hash22(id + 3.3) - 0.5) * 0.7) * CELL;
            if (dot(c, c) < 1e-8) continue;
            vec2 rad = normalize(c);

            float ang  = atan(rad.y, rad.x);
            float snap = floor(ang / (PI * 0.25) + 0.5) * (PI * 0.25);
            vec2  d1   = vec2(cos(snap), sin(snap));
            float l1   = CELL * mix(0.55, 1.70, hash21(id + 7.3));

            float sgn  = hash21(id + 3.1) < 0.5 ? -1.0 : 1.0;
            float ang2 = snap + sgn * PI * 0.25;
            vec2  d2   = vec2(cos(ang2), sin(ang2));
            float l2   = CELL * mix(0.25, 0.95, hash21(id + 11.7));

            vec2 a = c, b = c + d1 * l1, e = b + d2 * l2;

            float h1, h2;
            float dA = segDist(p, a, b, h1);
            float dB = segDist(p, b, e, h2);

            float total = l1 + l2;
            float mine  = lineAA(dA, 0.0009);
            float mineB = lineAA(dB, 0.0009);

            // Where along the whole polyline this fragment sits, so a pulse can
            // run the trace end to end without a seam at the elbow.
            float sA = h1 * l1;
            float sB = l1 + h2 * l2;

            // Two pulses per trace at different rates: one alone reads as a
            // marquee, two reads as traffic.
            float seed = hash21(id + 5.5);
            float headA = fract(t * 0.33 + seed) * total;
            float headB = fract(t * 0.19 + seed * 3.1) * total;
            float pA = exp(-abs(sA - headA) * 11.0 / CELL)
                     + exp(-abs(sA - headB) * 11.0 / CELL) * 0.6;
            float pB = exp(-abs(sB - headA) * 11.0 / CELL)
                     + exp(-abs(sB - headB) * 11.0 / CELL) * 0.6;

            // Does THIS trace carry current? A stable per-cell hash under the
            // load, so cells switch on individually as concurrency climbs.
            float cellH = hash21(id + 41.7);
            float live = step(cellH, energy);

            // A share of the live traces carry failed work and run red.
            float bad = live * step(hash21(id + 57.3), fail);

            // A dark trace lit by a near-white pulse: the board is accent
            // coloured at rest, but current running through it is white - and
            // red where that current is a failure.
            float base = 0.075 * mix(0.5, 1.0, hash21(id + 19.1));
            vec3 lit = mix(mix(accent, vec3(1.0), 0.65), vec3(1.0, 0.22, 0.18), bad);
            acc += accent * (mine + mineB) * base
                 // A live trace is steadily ON, not merely visited by a pulse.
                 // Without this the load is unreadable: at low concurrency the
                 // few energised traces are dark between pulses, so one tool in
                 // flight looks identical to six.
                 + lit * (mine + mineB) * live * 0.30
                 + lit * (mine * pA + mineB * pB) * 1.50 * live;

            // Vias: a node at the elbow and at the terminus.
            float nd = 1.0 - smoothstep(0.0020, 0.0038, length(p - b));
            float ne = 1.0 - smoothstep(0.0017, 0.0033, length(p - e));
            float nodeLit = 0.16 + 1.30 * live * exp(-abs(total - headA) * 9.0 / CELL);
            acc += mix(accent, vec3(1.0), 0.55) * (nd + ne) * nodeLit * 0.60;
        }
    }
    return acc;
}

// =============================================================================
void main() {
    vec2 res = iResolution;
    float m  = min(res.x, res.y);
    PX = 1.0 / m;

    // Origin at the centre of the viewport, y up.
    vec2 p = (gl_FragCoord.xy - 0.5 * res) / m;
    p /= max(uScale, 0.001);
    PX /= max(uScale, 0.001);

    float r    = length(p);
    float turn = fract(atan(p.x, p.y) / TAU);   // 0 at 12 o'clock, clockwise
    float t    = uReduced > 0.5 ? 0.0 : iTime;
    SKIRT      = mix(1.0, 0.45, clamp(uHDR, 0.0, 1.0));

    float speak  = clamp(uSpeaking,  0.0, 1.0);
    float listen = clamp(uListening, 0.0, 1.0);
    float think  = clamp(uThinking,  0.0, 1.0);
    float work   = clamp(uWorking,   0.0, 1.0);
    float busy   = clamp(speak + work + listen + think, 0.0, 1.0);
    float level  = clamp(uLevel, 0.0, 1.0);

    // One skew across every ring, so the counter-rotation the design depends on
    // survives: relative directions and ratios are preserved, only the pace
    // changes.
    float spin = uSpin * (gene(G_SPEED) > 0.01 ? gene(G_SPEED) : 1.0);
    float chunkSeed = gene(G_CHUNK);

    // ---- the inner life, resolved into drawing terms ----------------------
    // Valence ramps the accent from a sunk navy to an electric violet, and
    // irritation drags it off the blue family entirely - one non-blue is worth
    // more than any amount of extra brightness, because it is the only change
    // the eye reads as a change of KIND rather than of degree.
    vec3 cold  = vec3(0.10, 0.13, 0.42);
    vec3 warm  = vec3(0.55, 0.45, 1.00);
    vec3 angry = vec3(0.95, 0.20, 0.55);
    vec3 accent = mix(mix(cold, warm, uValence), uAccent, 0.45);
    accent = mix(accent, angry, uIrritation * 0.80);
    vec3 accHi = mix(accent, vec3(1.0), 0.45);

    // Fatigue dims everything; luminosity and attention lift it. Attention is
    // deliberately contrast, not brightness: a focused instrument gets crisper,
    // it does not get louder.
    float dim      = mix(1.0, 0.52, uFatigue);
    float lumGain  = mix(0.75, 1.45, uLuminosity);
    float focus    = mix(0.80, 1.25, uAttention);

    // Tension shows up as a denser gauge and a fine jitter on the outer rings -
    // the instrument's hands are not quite steady.
    float gaugeN = max(24.0, 90.0 + gene(G_TICKS) + 70.0 * uTension);
    float jitter = uTension * 0.0016
                 * sin(turn * TAU * 37.0 + t * 23.0)
                 * (0.5 + 0.5 * sin(t * 11.0));

    vec3 col = vec3(0.0);

    // -- circuit board, behind everything and only outside the dial ----------
    float outside = smoothstep(R_OUTER * 1.00, R_OUTER * 1.10, r);
    if (outside > 0.001) {
        // Thinking alone lights a little of the board (the agent is reasoning
        // before it has called anything); real concurrent work lights the rest.
        float energy = clamp(think * 0.35 + uWorkLoad, 0.0, 1.0);
        col += circuitField(p + uParallax, t, energy, clamp(uWorkFail, 0.0, 1.0), accent)
             * outside;
    }

    // -- breathing: the whole dial swells a little when it is busy -----------
    float breath = 1.0 + 0.012 * sin(t * 1.1) + 0.020 * level * speak;
    float rr = r / breath;
    // Only the outer rings carry the tension jitter. Jittering the core too
    // would read as a broken render rather than as a nervous instrument.
    float rrJ = rr + jitter;
    SMEAR = 0.0;   // static unless a rotating ring says otherwise

    // -- iris: chunky dashes hugging the core --------------------------------
    {
        float thick = 0.020 + 0.006 * level * speak;
        SMEAR       = smearAt(W_IRIS, R_IRIS);
        float rad   = bandAA(rr, R_IRIS - thick * 0.5, R_IRIS + thick * 0.5);
        float ang   = dashRing(turn, spin, R_IRIS, max(6.0, 12.0 + gene(G_IRIS_SEG)), 0.62, W_IRIS);
        col += accent * rad * ang * (0.85 + 0.5 * level * speak);
        col += accent * soft(rr - R_IRIS, 0.022) * ang * 0.22;
    }

    // -- second chunky ring ---------------------------------------------------
    {
        float thick = 0.016;
        SMEAR       = smearAt(W_DASH2, R_DASH2);
        float rad   = bandAA(rr, R_DASH2 - thick * 0.5, R_DASH2 + thick * 0.5);
        float ang   = dashRing(turn, spin, R_DASH2, max(8.0, 16.0 + gene(G_DASH_SEG)), 0.58, W_DASH2);
        col += accent * rad * ang * 0.80;
        col += accent * soft(rr - R_DASH2, 0.020) * ang * 0.20;
    }

    // -- the one unbroken circle ---------------------------------------------
    SMEAR = 0.0;
    col += accHi * lineAA(rr - R_HAIRCIRC, 0.0009) * (0.55 + 0.45 * busy) * focus;
    col += accHi * soft(rr - R_HAIRCIRC, 0.014) * (0.10 + 0.10 * busy) * focus;

    // -- resting long spokes --------------------------------------------------
    // The reference's dominant texture: sparse hairlines running from the
    // unbroken circle out past the outer ring, at hashed lengths. They are what
    // gives the dial its depth - without them the space between the rings is
    // dead, and the whole thing reads as a few concentric circles.
    {
        const float NSPOKE = 64.0;
        float slotf = turn * NSPOKE;
        float slot  = floor(slotf);
        float h     = hash11(slot * 1.7 + 31.0);
        float len   = mix(0.055, 0.215, hash11(slot * 2.3 + 7.0));
        float u     = abs(fract(slotf) - 0.5) / NSPOKE;
        float m     = lineAA(u * TAU * rr, 0.00065)
                    * bandAA(rr, R_SPOKE_IN, R_SPOKE_IN + len)
                    * step(0.34, h);
        col += accent * m * mix(0.16, 0.48, hash11(slot * 3.9 + 13.0));
    }

    // -- fine tick gauge ------------------------------------------------------
    SMEAR = smearAt(W_GAUGE, R_GAUGE);
    col += accent * tickRing(turn, rr, spin, R_GAUGE, 0.014, gaugeN, W_GAUGE, 0.0007) * 0.45;

    // A resting gauge inside the fan band. Without it the annulus the fan lives
    // in is empty whenever nobody is talking, and the dial looks unfinished
    // rather than idle.
    SMEAR = smearAt(-0.020, R_FAN_OUT);
    col += accent * tickRing(turn, rr, spin, R_FAN_OUT - 0.026, 0.017, 120.0, -0.020, 0.0006)
                  * (0.22 - 0.14 * max(speak, listen));

    // -- irregular arc rings --------------------------------------------------
    // A few arcs are struck in white rather than accent. The reference does
    // this too and it is what stops the rings reading as one flat material.
    SMEAR = smearAt(W_ARC1, R_ARC1);
    float hi1 = step(0.72, hash11(floor((turn - spin * W_ARC1) * 14.0) * 1.37 + 1.0 + chunkSeed));
    float hi2 = step(0.80, hash11(floor((turn - spin * W_ARC2) * 18.0) * 1.37 + 2.0 + chunkSeed));
    col += mix(accent, vec3(1.0), hi1 * 0.7) * bandAA(rrJ, R_ARC1 - 0.005, R_ARC1 + 0.005)
                  * chunkRing(turn, spin, R_ARC1, 14.0, W_ARC1, 1.0 + chunkSeed,
                              gene(G_ARC1_FILL) > 0.01 ? gene(G_ARC1_FILL) : 0.55) * 0.75;
    SMEAR = smearAt(W_ARC2, R_ARC2);
    col += mix(accent, vec3(1.0), hi2 * 0.7) * bandAA(rrJ, R_ARC2 - 0.004, R_ARC2 + 0.004)
                  * chunkRing(turn, spin, R_ARC2, 18.0, W_ARC2, 2.0 + chunkSeed,
                              gene(G_ARC2_FILL) > 0.01 ? gene(G_ARC2_FILL) : 0.50) * 0.65;

    // -- arc-reactor coil packs ----------------------------------------------
    // Ten blocks in the gap the gauge and the first arc ring leave. They turn
    // at half the first arc ring's rate, so the dial gains a layer that is
    // clearly geared to the others rather than drifting on its own.
    SMEAR = smearAt(W_ARC1 * 0.5, R_COIL_IN);
    float coil = coilPack(turn, rrJ, spin, R_COIL_IN, R_COIL_OUT, 10.0,
                          W_ARC1 * 0.5, 0.54);
    col += mix(accent, accHi, 0.30) * coil * 0.42 * (0.72 + 0.50 * level);

    // -- core halo -------------------------------------------------------------
    // The reference's centre is its brightest point; this dial's was not. Three
    // hairlines rather than a glow, because a bloom here would wash the iris.
    float halo = lineAA(rrJ - 0.038, 0.0012)
               + lineAA(rrJ - 0.058, 0.0011) * 0.72
               + lineAA(rrJ - 0.078, 0.0010) * 0.48;
    col += mix(accent, vec3(1.0), 0.55) * halo * 0.30 * (0.60 + 0.60 * level);

    // The outermost ring is the "signal" ring: with no live relay behind the
    // phenotype it falls away to almost nothing, so an unfed instrument looks
    // unfed rather than calm.
    SMEAR = smearAt(W_OUTER, R_OUTER);
    float sig = mix(0.28, 1.0, uPhenoFresh);
    col += accent * lineAA(rrJ - R_OUTER, 0.0007) * 0.28 * sig;
    col += accent * bandAA(rrJ, R_OUTER - 0.004, R_OUTER + 0.004)
                  * chunkRing(turn, spin, R_OUTER, 22.0, W_OUTER, 3.0 + chunkSeed, 0.42) * 0.55 * sig;

    // -- containment ring ------------------------------------------------------
    // Fine and dense, sitting between the second arc ring and the outer one. It
    // carries `sig` deliberately: an instrument with no live phenotype behind it
    // should lose its containment too, not keep a full reactor shell.
    SMEAR = smearAt(W_OUTER * 0.4, R_CONTAIN);
    col += accent * bandAA(rrJ, R_CONTAIN - 0.005, R_CONTAIN + 0.005)
                  * dashRing(turn, spin, R_CONTAIN, 44.0, 0.70, W_OUTER * 0.4)
                  * 0.26 * sig;

    // -- sparse long markers on the outer ring --------------------------------
    col += accent * tickRing(turn, rrJ, spin, R_ARC2 + 0.012, 0.022, 24.0, W_ARC2, 0.0008)
                  * 0.35;

    SMEAR = 0.0;   // gauges never rotate; a drifting gauge is not a gauge
    // -- the two real readings ------------------------------------------------
    // Deliberately NOT dimmed by fatigue below: a mood may not be allowed to
    // hide a spend figure. See the `dim` application at the end of main.
    vec3 gauges = gauge(turn, rr, R_G_BUDGET, uBudgetFill, uBudgetKnown, uBudgetHard, accent, t)
                + gauge(turn, rr, R_G_TOKEN,  uTokenFill,  uTokenKnown,  0.0,         accent, t);

    // =========================================================================
    // SPEAKING - band-driven fan, core pulse, shock rings
    // =========================================================================
    if (speak > 0.001) {
        // Fan slots. The band index is mirrored about the vertical axis so the
        // spectrum reads outward from 12 o'clock on both sides; a per-slot hash
        // knocks a few lines out so it breathes instead of strobing.
        const float NFAN = 72.0;
        float slotf = turn * NFAN;
        float slot  = floor(slotf);
        float bpos  = abs(fract(turn) - 0.5) * 2.0 * 7.0;
        int   b0    = int(floor(bpos));
        float bf    = fract(bpos);
        float amp   = mix(bandAt(min(b0, 7)), bandAt(min(b0 + 1, 7)), bf);
        amp = clamp(amp * (0.75 + 0.45 * hash11(slot * 1.7)), 0.0, 1.0);
        amp = mix(amp, amp * 0.25, step(hash11(slot * 4.3 + 9.0), 0.12));

        float u    = abs(fract(slotf) - 0.5) / NFAN;
        float len  = mix(0.10, 1.0, amp);
        float mask = lineAA(u * TAU * rr, 0.00090)
                   * bandAA(rr, R_FAN_IN, R_FAN_IN + (R_FAN_OUT - R_FAN_IN) * len);
        // Near-white, not accent: in the reference the fan is the one element
        // that reads as raw light rather than as instrument housing.
        vec3 fanCol = mix(accent, vec3(1.0), 0.75);
        col += fanCol * mask * speak * (0.80 + 0.95 * level);
        col += fanCol * soft(u * TAU * rr, 0.0032)
                      * bandAA(rr, R_FAN_IN, R_FAN_IN + (R_FAN_OUT - R_FAN_IN) * len)
                      * speak * (0.18 + 0.22 * level);

        // Shock rings leaving the core on the voice.
        for (int k = 0; k < 3; k++) {
            float ph  = fract(t * 0.55 + float(k) / 3.0);
            float rad = mix(R_CORE, R_ARC1, ph);
            float a   = (1.0 - ph) * (1.0 - ph) * (0.35 + 0.65 * level);
            col += accHi * lineAA(rr - rad, 0.0011) * a * speak * 0.9;
        }
        // Onset kicks a brighter, faster ring.
        float oph = fract(t * 1.6);
        col += vec3(1.0) * lineAA(rr - mix(R_CORE, R_GAUGE, oph), 0.0009)
                         * (1.0 - oph) * uOnset * speak * 0.8;
    }

    // =========================================================================
    // LISTENING - the incoming wave, drawn as radial hairlines that accumulate
    // clockwise from 12 o'clock and clear when the head gets back there.
    // =========================================================================
    if (listen > 0.001) {
        const float NW = 128.0;
        float head = clamp(uWaveHead, 0.0, 1.0);

        float slotf = turn * NW;
        int   idx   = int(floor(slotf));
        float amp   = waveSample(idx);

        // Only the swept arc exists. The tail fades over the last stretch of
        // the revolution so the wipe at 12 reads as a wipe, not a dropped frame.
        float written = step(turn, head);
        float clearing = 1.0 - smoothstep(0.94, 1.0, head);

        // The sweep is the loudest thing on the dial: its spokes start at the
        // iris and run PAST the outer ring, so a loud room visibly overruns the
        // instrument's own housing.
        float u    = abs(fract(slotf) - 0.5) / NW;
        float len  = mix(0.06, 1.0, clamp(amp, 0.0, 1.0));
        float tipR = R_FAN_IN + (R_SWEEP_OUT - R_FAN_IN) * len;
        float mask = lineAA(u * TAU * rr, 0.00075) * bandAA(rr, R_FAN_IN, tipR);
        col += accHi * mask * written * clearing * listen * 0.95;
        col += accHi * soft(u * TAU * rr, 0.0035) * bandAA(rr, R_FAN_IN, tipR)
                     * written * clearing * listen * 0.20;

        // The leading edge: a bright cursor at the write head.
        float dHead = turn - head;
        dHead -= floor(dHead + 0.5);
        float cursor = exp(-abs(dHead) * 260.0) * clearing;
        col += vec3(1.0) * cursor * bandAA(rr, R_FAN_IN, R_FAN_OUT + 0.010)
                         * listen * 0.55;
    }

    // =========================================================================
    // WORKING - a bold dashed arc sweeping the gauge ring
    // =========================================================================
    if (work > 0.001) {
        float sweep = fract(spin * 0.13);
        float d = turn - sweep;
        d -= floor(d + 0.5);
        // A 100-degree run of heavy dashes.
        float within = 1.0 - smoothstep(0.12, 0.145, abs(d));
        float dash   = dashRing(turn, spin, R_GAUGE, 30.0, 0.55, 0.13);
        float rad    = bandAA(rr, R_GAUGE - 0.006, R_GAUGE + 0.006);
        col += vec3(1.0) * rad * dash * within * work * 0.9;
    }

    // =========================================================================
    // CORE
    // =========================================================================
    {
        // The core is the focal point and was the least-crafted thing on the
        // dial: a disc plus one gaussian, which reads as a blurred dot rather
        // than as a source. It is now built like an aperture — a hot centre, a
        // bright rim where the light meets its housing, and a short falloff —
        // and the WIDE glow is left to the bloom pass, which is what stops it
        // blowing out into a featureless blob.
        float pulse = 1.0 + 0.35 * level * speak + 0.10 * sin(t * 2.3);
        float cr    = R_CORE * pulse;

        // Hot centre, slightly overdriven so the bloom pass has something to
        // find, but small enough that the disc keeps a visible edge.
        float disc = 1.0 - smoothstep(cr - PX * 1.2, cr + PX * 1.2, rr);
        col += vec3(1.0) * disc * (1.25 + 0.55 * level * speak) * lumGain;

        // The rim: a thin brighter ring exactly at the aperture edge. This is
        // the detail that makes it read as an opening with light behind it
        // rather than as a painted dot.
        col += mix(accent, vec3(1.0), 0.85)
             * lineAA(rr - cr * 1.18, 0.0016) * (0.9 + 0.6 * level * speak) * lumGain;

        // Short falloff only. Anything wider is the bloom pass's job now.
        col += mix(accent, vec3(1.0), 0.55)
             * exp(-rr / (0.020 + 0.006 * level * speak)) * 0.75 * lumGain;
        col += accent * exp(-rr / 0.062) * 0.30 * lumGain;
    }

    // =========================================================================
    // LABELS
    // =========================================================================
    {
        float capH = 0.0125;
        float top = arcText(rr, turn, uLabelTop, R_OUTER, 0.0, capH, false);
        col += mix(accHi, vec3(1.0), 0.7) * top * clamp(uLabelTopAmt, 0.0, 1.0);

        float bot = arcText(rr, turn, uLabelBottom, R_OUTER, 0.5, capH, true);
        col += accent * bot * clamp(uLabelBottomAmt, 0.0, 1.0) * 0.85;
    }

    // =========================================================================
    // GRADE
    // =========================================================================
    // Fatigue is applied to the whole instrument at once, AFTER everything has
    // been drawn and before the background: a tired dial is uniformly dimmer,
    // not selectively missing parts.
    col *= dim;

    // The gauges are added AFTER the fatigue dim, and so are never attenuated by
    // it. The inner life is allowed to change how the instrument feels; it is
    // not allowed to make a real reading harder to see.
    col += gauges;

    vec3 bg = vec3(0.020, 0.020, 0.030);
    col += bg;
    col = max(col, vec3(0.0));

    if (uHDR > 0.5) {
        // Hand linear light to the bloom pipeline. Vignette, grain and the tone
        // curve all belong to the composite pass: bloom has to be gathered
        // BEFORE the shoulder, or the tone curve crushes the highlights the
        // bloom exists to spread.
        fragColor = vec4(col, 1.0);
        return;
    }

    // Single-pass grade, for a host that cannot do offscreen work.
    col *= 1.0 - 0.22 * smoothstep(0.55, 1.30, length(p));
    col += (hash21(gl_FragCoord.xy + fract(t) * 91.7) - 0.5) * 0.008;
    col = max(col, vec3(0.0));
    col = col / (1.0 + col * 0.22);          // gentle shoulder, keeps cores white
    fragColor = vec4(col, 1.0);
}
