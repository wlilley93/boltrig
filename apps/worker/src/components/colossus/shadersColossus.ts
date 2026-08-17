// Colossus's body: a 70s dot-matrix annunciator panel.
//
// HE IS NOT A CREATURE, AND THAT IS THE POINT. Familiar is a body, Jarvis an
// instrument, Ultron a membrane -- three variations on a glowing sphere. This
// one is a WALL. World Control does not have a face; it has a room of lamps and
// a sign that tells you what it has decided. Giving him an orb would have made
// the fourth character a recolour of the first three and lost the only reading
// that is actually his.
//
// WHAT THE REFERENCES SHOW, and how each becomes a line of this shader:
//
//   The destination sign  amber lamps on black, DISCRETE round dots with a
//                         visible dark lattice between them, each dot haloed.
//                         -> `lamp()`, and an unlit lamp is drawn at ~2%
//                            rather than at zero. The lattice IS the look.
//   The rack of glyphs    sparse indicator fields, most lamps dark, brightness
//                         uneven lamp to lamp, some clusters simply dead.
//                         -> `field()`, with a per-lamp hash gain and a dead
//                            fraction that never lights at any energy.
//   The counter window    an orange numeric readout at a coarser pitch than
//                         the sign, recessed behind a bezel.
//                         -> READOUT, drawn at 2x dot pitch on a lifted plate.
//   The one cool column   in a whole frame of amber, a single short run of
//                         teal dots. It is the only cold thing in the film.
//                         -> `uTeal`, exactly one column, never a second.
//   The CRT              barrel curvature, phosphor smear, scanline banding,
//                         heavy vignette into black.
//                         -> `curve()`, the decay tail, `bands`, and the
//                            vignette in the composite.
//
// PHOSPHOR DECAY IS THE PERIOD, NOT THE BLOOM. An LED sign switches off
// instantly and reads as modern no matter what colour it is. What dates this to
// 1970 is that a lamp going dark FADES, so a scrolling word drags a tail behind
// it. Done analytically rather than with a feedback texture: for the ticker we
// know exactly when a column passed a given x, so brightness is
// exp(-age/TAU) with no state at all. One line, no framebuffer.
//
// NO PHENOTYPE. He does not read the machine's mood -- see his bundle, which
// omits the block entirely. Every other body here colours with irritation or
// arousal; his palette is fixed, because a system that changed colour when it
// was annoyed would be admitting to having moods, and he does not.

import { GLYPH_GLSL } from "./glyphAtlas";

/** Ticker capacity in glyphs. The uniform array is sized to this on both sides. */
export const TICKER_CAPACITY = 96;

/**
 * Glyphs in the readout window -- sign, four digits, space, two-glyph unit,
 * which is exactly the "+0042 US" of the reference counter.
 */
export const READOUT_LEN = 8;

export const PANEL_FRAG = `#version 300 es
precision highp float;
precision highp int;

in vec2 vUV;
out vec4 oColor;

uniform float uTime;        // animation seconds, never wall clock
uniform float uAspect;      // width / height
uniform float uEnergy;      // 0..1 overall activity
uniform float uVoice;       // 0..1 speech level; 0 when not speaking
uniform float uBands[8];    // 0..1 log bands of the outgoing voice
uniform float uScroll;      // ticker offset in CELLS, advanced by the CPU
uniform int   uTicker[${TICKER_CAPACITY}];
uniform int   uTickerLen;
uniform int   uReadout[${READOUT_LEN}];
uniform float uReadoutGlow; // 0..1 -- lifts on the frame the counter changes
uniform float uCurve;       // barrel amount; 0 is flat
uniform float uPitch;       // FINE lamps across the panel width
uniform float uTickerScale; // how many fine lamps to one ticker lamp
uniform vec3  uAmber;       // the lamp colour at ordinary brightness
uniform vec3  uHot;         // a fully driven lamp, blown toward white
uniform vec3  uTeal;        // the single cool accent
uniform float uDecay;       // phosphor time constant, seconds

${GLYPH_GLSL}

float hash11(float n) { return fract(sin(n) * 43758.5453123); }
float hash21(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123); }

// ---------------------------------------------------------------------------
// One lamp.
//
// \`cell\` is the fractional position inside a lattice cell. The lamp is a disc
// of radius LAMP_R with a soft edge and a wider, much dimmer halo -- the halo is
// what the separable bloom then smears further, and having BOTH is why the sign
// reads as glass over a bulb rather than as a lit pixel.
// ---------------------------------------------------------------------------
const float LAMP_R = 0.30;

float lamp(vec2 cell) {
  vec2 q = abs(cell - 0.5);
  // SQUARE, not a disc. Chebyshev distance -- the larger of the two axes --
  // gives a square of the same size with the same soft edge, where length()
  // gives a circle. The board is a grid of square elements.
  float core = 1.0 - smoothstep(LAMP_R * 0.55, LAMP_R, max(q.x, q.y));
  // The halo stays RADIAL. It is the glass and the bloom around the element
  // rather than the element itself, and a square halo reads as a bad blur.
  float r = length(q);
  float halo = exp(-r * r * 16.0) * 0.16;
  return core + halo;
}

// Barrel distortion. The reference CRT bows noticeably at the corners and not
// at all in the middle, which is exactly what a dot(p,p) term gives.
vec2 curve(vec2 p) {
  return p + p * dot(p, p) * uCurve;
}

// ---------------------------------------------------------------------------
// The ticker band.
//
// Text scrolls RIGHT TO LEFT, so a cell's glyph index is (column + scroll). The
// scroll offset is a float in cells: its integer part selects the glyph and its
// fraction slides the lattice, which is what stops the sign snapping one whole
// character at a time.
//
// GLYPH CELL is 6 lamps wide -- five for the glyph and one of spacing -- and
// 7 tall, matching the destination boards, which never kern.
// ---------------------------------------------------------------------------
const float GLYPH_W = 6.0;
const float GLYPH_H = 7.0;

float ticker(vec2 lampIdx, out float trail) {
  trail = 0.0;
  if (uTickerLen <= 0) return 0.0;

  float col = lampIdx.x + uScroll;
  float gi = floor(col / GLYPH_W);
  int slot = int(mod(gi, float(uTickerLen)));
  if (slot < 0) slot += uTickerLen;
  int gid = uTicker[slot];

  vec2 inGlyph = vec2(mod(col, GLYPH_W), lampIdx.y);
  if (inGlyph.x >= 5.0) return 0.0;              // the inter-glyph column
  if (inGlyph.y < 0.0 || inGlyph.y >= GLYPH_H) return 0.0;

  float lit = glyphBit(gid, vec2((inGlyph.x + 0.5) / 5.0, (inGlyph.y + 0.5) / GLYPH_H));

  // The tail. A lamp one cell to the RIGHT of a lit one was lit \`1/speed\`
  // seconds ago and is still cooling. Sampling the glyph the message will have
  // moved off gives the smear for free, with no history buffer.
  float behind = 0.0;
  for (int k = 1; k <= 3; k++) {
    float pc = col + float(k);
    float pgi = floor(pc / GLYPH_W);
    int ps = int(mod(pgi, float(uTickerLen)));
    if (ps < 0) ps += uTickerLen;
    vec2 pin = vec2(mod(pc, GLYPH_W), inGlyph.y);
    if (pin.x >= 5.0) continue;
    float pl = glyphBit(uTicker[ps], vec2((pin.x + 0.5) / 5.0, (pin.y + 0.5) / GLYPH_H));
    behind = max(behind, pl * exp(-float(k) * uDecay));
  }
  trail = behind * (1.0 - lit);
  return lit;
}

// ---------------------------------------------------------------------------
// The indicator fields above and below.
//
// Deterministic per lamp, so the panel has a FIXED personality rather than
// re-rolling every frame: the same lamps are bright, the same ones are dead,
// and the same column is the busy one. That is what makes it read as a machine
// with a wiring diagram instead of as noise.
// ---------------------------------------------------------------------------
float field(vec2 lampIdx, float t, out float cool) {
  cool = 0.0;

  // The rack: blocks of lamps, most of them dark. This is the coarse structure,
  // decided before any individual lamp is considered, and it is what stops the
  // board reading as noise.
  vec2 block = floor(lampIdx / vec2(9.0, 7.0));
  float bh = hash21(block + 41.7);
  if (bh > 0.58) return 0.0;

  float h = hash21(floor(lampIdx));

  // A sixth of the panel is simply broken and never lights. Every reference
  // frame has these, and their absence is what makes a fake sign look new.
  if (h > 0.84) return 0.0;

  // Each lamp belongs to one voice band, by column, so a syllable lights a
  // vertical region rather than the whole board. Silence leaves the idle
  // pattern, which is the panel talking to itself.
  int band = int(mod(floor(lampIdx.x) * 0.5, 8.0));
  float drive = uBands[band] * uVoice;

  // Idle: a slow per-lamp square wave at its own rate and phase. Sparse -- most
  // of the board is dark at any instant, as in the rack shots.
  float rate = 0.20 + h * 1.7;
  // MOST OF THE BOARD IS OFF AT ANY INSTANT. This threshold is the single
  // number that decides whether the thing reads as a 1970 rack or as a modern
  // LED wall, and the first render had it far too generous.
  float blink = step(0.88 - uEnergy * 0.12, fract(t * rate + h * 7.3));

  // THE VOICE LIGHTS A SUBSET, NOT THE COLUMN. Multiplying every lamp in a
  // band's column by that band's energy lights them all at once and evenly,
  // which reads as a level meter -- a modern instrument, and the one thing
  // these panels never look like. The reference racks FLICKER: a scatter of
  // lamps changing several times a second, denser when more is arriving. So
  // the band's energy becomes a PROBABILITY, resampled on a coarse step, and
  // which lamps answer changes from one step to the next.
  float tick = floor(t * 7.0);
  float driveOn = step(1.0 - drive, hash21(vec2(h * 91.7, tick)));

  float on = max(blink * (0.22 + 0.30 * h), driveOn * (0.55 + 0.45 * h));
  // The teal run: ONE column, and a RUN rather than a lamp -- in the reference
  // it is a short vertical string of cold dots in a whole frame of amber, and a
  // single teal pixel just reads as a dead sub-pixel.
  float col = floor(lampIdx.x);
  cool = (abs(col - 23.0) < 0.5 && lampIdx.y < -6.0 && lampIdx.y > -22.0) ? 1.0 : 0.0;
  // ...and it reports steadily. Left on the ordinary blink it was a cold lamp
  // that spent most frames switched off, which is an accent nobody ever sees.
  if (cool > 0.0) on = max(on, 0.42 + 0.28 * sin(t * 1.4 + lampIdx.y * 0.9));
  return on;
}

// ---------------------------------------------------------------------------
// The counter window.
//
// A DIFFERENT INSTRUMENT, not a smaller ticker. In the reference the numeric
// readout sits on its own module, recessed behind a bezel on a grey plate, and
// reads as a meter bolted next to the sign rather than as part of it.
//
// AT THE FIELD PITCH, not the ticker's. It was drawn coarse at first, on the
// reasoning that a counter is a bigger instrument -- and eight glyphs at twice
// the lamp pitch is 96 lamps wide on a board 74 across, so the window covered
// the entire panel. What marks it as a separate module is the PLATE it sits
// on, which costs no width at all.
//
// Returns the lamp brightness; \`plate\` comes back as the bezel's own dim
// surface, which is lit even where no lamp is.
// ---------------------------------------------------------------------------
float readout(vec2 p, float pitch, out float plate) {
  plate = 0.0;
  // Bottom-right, in p units. Sized from the pitch so it holds READOUT_LEN
  // glyphs at 2x whatever the panel resolved to.
  float pad = pitch * 1.5;
  float cw = pitch * GLYPH_W;
  vec2 hi = vec2(uAspect * 0.94, -0.90 + pitch * GLYPH_H + pad * 2.0);
  vec2 lo = hi - vec2(cw * float(${READOUT_LEN}) + pad * 2.0,
                      pitch * GLYPH_H + pad * 2.0);
  if (p.x < lo.x || p.x > hi.x || p.y < lo.y || p.y > hi.y) return 0.0;

  plate = 1.0;
  vec2 inner = (p - lo - pad) / pitch;
  if (inner.x < 0.0 || inner.y < 0.0 || inner.y >= GLYPH_H) return 0.0;

  float gi = floor(inner.x / GLYPH_W);
  if (gi < 0.0 || gi >= float(${READOUT_LEN})) return 0.0;
  int gid = uReadout[int(gi)];

  vec2 ing = vec2(mod(inner.x, GLYPH_W), inner.y);
  if (ing.x >= 5.0) return 0.0;
  float lampBright = glyphBit(gid, vec2((floor(ing.x) + 0.5) / 5.0,
                                        (floor(ing.y) + 0.5) / GLYPH_H));
  return lampBright * lamp(fract(ing));
}

void main() {
  vec2 p = (vUV - 0.5) * vec2(uAspect, 1.0) * 2.0;
  p = curve(p);

  // Outside the bezel the panel is simply not there. Hard edge, because the
  // reference sign has a metal frame and no fade.
  if (abs(p.x) > uAspect * 0.98 || abs(p.y) > 0.98) {
    oColor = vec4(0.0);
    return;
  }

  // TWO LATTICES, and the size difference between them is the design.
  //
  // The fine one carries the indicator fields; the coarse one carries the sign.
  // On the reference boards the message characters are several times the size
  // of the rack lamps around them, and that ratio -- not colour, not bloom --
  // is what makes one of them read as language and the other as activity.
  //
  // Both are square in p units, so the dots stay round on a wide card; a
  // lattice built in uv would give ellipses.
  float fine = 2.0 * uAspect / uPitch;
  float coarse = fine * uTickerScale;

  float bright = 0.0;
  float cool = 0.0;
  float shape = 0.0;
  float trail = 0.0;
  float floorLit = 0.0;

  // The sign occupies a horizontal band across the middle -- a slim strip in a
  // dark field, which is the proportion the reference panels actually have.
  // NOT named half: that is a reserved word in GLSL ES and the compiler says so
  float bandHalf = coarse * GLYPH_H * 0.5;
  if (abs(p.y) < bandHalf) {
    vec2 lampF = vec2(p.x, p.y + bandHalf) / coarse;
    vec2 idx = floor(lampF);
    bright = ticker(idx, trail) * 1.35;
    bright += trail * 0.45;
    shape = lamp(fract(lampF));
    floorLit = 0.030;
  } else {
    vec2 lampF = p / fine;
    vec2 idx = floor(lampF);
    bright = field(idx, uTime, cool);
    shape = lamp(fract(lampF));
  }

  // The lamp, and the unlit lattice underneath it. The floor is what makes the
  // dark parts read as unlit BULBS rather than as background, and it is the
  // single most period-specific value in the file -- too high and the whole
  // board glows cream, which is what the first render did.
  float lit = bright * shape;
  float dark = floorLit * shape;

  vec3 col = mix(uAmber, uHot, clamp(bright * 1.25 - 0.25, 0.0, 1.0)) * lit;
  col = mix(col, uTeal * lit, cool * 0.85);
  col += uAmber * dark;

  // The counter, drawn OVER whatever the field put there -- it is a separate
  // module bolted on, so it occludes rather than blends.
  float plate = 0.0;
  float digits = readout(p, fine, plate);
  if (plate > 0.0) {
    // The bezel: a cool grey plate, brighter than the black panel, so the
    // window reads as recessed metal in a wall of glass.
    col = vec3(0.040, 0.038, 0.036);
    col += mix(uAmber, uHot, uReadoutGlow) * digits * (0.85 + 0.5 * uReadoutGlow);
  }

  // Scanline banding. Slow, wide and very shallow -- a rolling brightness
  // gradient across the whole panel, not the hard 1px lines of a CRT pastiche.
  col *= 0.94 + 0.06 * sin(p.y * 26.0 - uTime * 1.1);

  oColor = vec4(col, 1.0);
}
`;

/**
 * The composite. Colossus gets his OWN rather than the shared one because the
 * shared composite ends in a radial core glow, which is the right ending for
 * three bodies that are spheres and the wrong one for a wall. This ends in a
 * rectangular vignette and a faint reflection instead: the reference frames are
 * shot through glass, and the darkest corners of the room are what sells the
 * scale of it.
 */
export const PANEL_COMPOSITE_FRAG = `#version 300 es
precision highp float;
in vec2 vUV;
out vec4 oColor;

uniform sampler2D uScene;
uniform sampler2D uBloom;
uniform float uBloomGain;
uniform float uAspect;
uniform float uTime;
uniform float uVignette;

void main() {
  vec3 scene = texture(uScene, vUV).rgb;
  vec3 bloom = texture(uBloom, vUV).rgb;
  vec3 col = scene + bloom * uBloomGain;

  // Rectangular vignette -- a panel darkens toward its FRAME, and a radial one
  // would round off the corners of a thing that is emphatically square.
  vec2 q = abs(vUV - 0.5) * 2.0;
  float v = (1.0 - pow(q.x, 6.0)) * (1.0 - pow(q.y, 4.0));
  col *= mix(1.0, clamp(v, 0.0, 1.0), uVignette);

  // Glass. One broad, very dim diagonal sheen, drifting: the reference is a
  // photograph of a display behind a window, and every frame has one.
  float sheen = exp(-pow((vUV.x + vUV.y * 0.6 - 0.55 - sin(uTime * 0.07) * 0.12) * 3.0, 2.0));
  col += vec3(0.035, 0.030, 0.026) * sheen;

  // Tone. A gentle knee only -- the reference lamps DO blow out, and clipping
  // the brightest cores to white is faithful rather than a defect.
  col = col / (col + 0.85);
  oColor = vec4(col, 1.0);
}
`;
