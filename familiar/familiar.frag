#version 300 es
// familiar.frag - "a cool mind with a warm center"
// Port of the approved WebGL redesign into the familiar host contract, then rebuilt toward
// AMBITION.md: a 4K, photoreal, non-human eye.
//
// The optical architecture (the load-bearing part):
//   * CORNEAL REFRACTION - the iris is BEHIND the sphere's surface, seen through a curved lens
//     (eta 1/1.376). Two stroma storeys at different depths get their own refracted hit points,
//     so inter-layer parallax and limb distortion are geometry, not painting.
//   * A NON-HUMAN APERTURE - a tilted superellipse whose exponent AND aspect ride the dilation:
//     constricted, a narrow oblique lens; dilated, a rounded-square bloom. Shape change, not scale.
//   * A TAPETUM - eyeshine deep behind the aperture when the geometry faces you and it is looking.
//
// What the interior now is (vs the pale marble):
//   * a genuinely DARK body - near-black navy; bright structure burns against it
//   * a screen-polar IRIS whose filaments FLOW OUTWARD from the nucleus (their phase
//     drifts with radius), so the face reads as a slow spiral of thought leaving the core
//   * five concentric SHELLS sampled with smooth penetration weights, each rotating at its
//     own rate and turning toward the cursor, so near structure slides across far - real
//     parallax without a march
//   * a wandering NUCLEUS: it tracks the cursor with uAttention but also drifts on its
//     own - the centre is not fixed
//   * THOUGHT SPARKS: seven small glints that form near the core, travel outward along the
//     filaments, and fade; hash-driven, nearly free
//   * WARMTH: the one deliberate palette departure. The core carries a faint warm ember -
//     cool analytic surface, warm intent held inside. Set WARMTH to 0.0 for the strict
//     blue-only family the brief demands.
//
// Anti-pattern compliance (see DESIGN-BRIEF.md section 9): silhouette analytic (1); body
// dark, brightness sparse (2); no broad gloss, tight glints only (3); shell twist varies
// with height+position, never radius alone (4); iris built from screen-polar coords,
// constant along the view ray (5).
//
// Cost: ~20 vnoise calls per covered pixel (the old interior marched ~110). No secondary
// rays. Measure with familiar-bench before trusting any change.
precision highp float;
out vec4 fragColor;

uniform float iTime;
uniform vec2  iResolution;
uniform vec4  uAudio;        // x=overall y=bass z=mid w=treble
uniform float uBeat;
uniform vec2  uMouse;        // 0..1, origin bottom-left
uniform float uDay;
uniform float uValence;
uniform float uArousal;
uniform float uIrritation;
uniform float uFatigue;
uniform float uAttention;
uniform float uSocial;
uniform float uBuoyancy;
uniform float uLuminosity;
uniform float uTension;
uniform float uGesture;
uniform float uGestureAmt;
uniform float uPresence;     // 1 = bare desktop, take the screen; 0 = withdraw to the bar
uniform vec2  uCentreDock;   // the bead's real centre in uv space, handed down by the host
uniform float uScaleDock;    // the being's uv radius when fully docked
uniform float uFitScale;     // the largest uv radius the porthole can show without clipping
uniform float uGaze;         // 1 = your cursor is live and it is watching it; 0 = it has looked away
uniform vec2  uWorldRes;
uniform vec2  uOrigin;
uniform float uPxScale;
uniform float uFill;         // 1 = this is the porthole on the bar
uniform float uPortWide;     // 1 = migration porthole; its rectangle already bounds the journey
uniform float uHover;        // 1 = pointer is over the clockbar summon point
uniform float uCompanion;    // 1 = large centred companion orb is showing (not the docked doughnut)
uniform float uAperture;     // 0..1 black-hole aperture; drives companion entrance/exit

const int   SHELLS = 5;
const int   SPARKS = 7;
const int   EMBERS = 12;   // particles thrown off the rim
const float RADIUS = 1.0;
const float WARMTH = 0.35;   // 0.0 = strict blue family; >0 = the ember at the core.
// DEAD IN THE SHIPPED THEME. Grep says WARMTH appears only here and in two comments; theme 2
// carries its own vWARMTH below, which is the one the heart actually reads. A warmth gene was
// briefly attached HERE and measured byte-identical across a 3x sweep - a gene wired to a
// constant nothing consumes. Left in place for theme 0, and named as dead so the next reader
// does not spend the same afternoon.

// THEME. Bodies inside the same crystal ball, sharing every mood scalar and the host contract:
//   0 = the photoreal non-human eye (AMBITION.md): iris, aperture, tapetum, corneal refraction.
//   1 = a formless voice-agent orb: a luminous, audio-reactive plasma (hand-built, first pass).
//   2 = "silk" voice body: imported from the Claude Design project (familiar-voice.frag /
//       familiar-voice-preview.html) - smooth liquid blue silk over a luminous heart, built for
//       conversation. Local edits vs the import: the concentric voice rings (interior ripple +
//       corona sonar) are removed and the body SWELLS on voice instead; the screen-edge frame
//       furniture is dropped to match this desktop's no-border preference. Theme 2 replaces the
//       whole main() body (autonomous gaze, its own corona); it does not use the IRIS toggle.
// Change this line, then hot-reload (systemctl --user kill -s USR1 familiar.service). The host
// keeps the previous program if the new one fails to compile, so a typo cannot black the screen.
#define FAMILIAR_THEME 2

// Within the eye (THEME 0): 1 = the full iris (the radial filament fan, the collarette, the
// limbal ring - the parts that say "eyeball"); 0 = NO iris. Drops just those, keeping the eye's
// crisp core, aperture, flame licks, layered interior mist and glass shell - the eye's rendering
// quality, but formless: a dark crystal ball with a living light in it, no recognisable eye.
#define FAMILIAR_IRIS 1

// THE REALM (theme 2): which room the being floats in. 1 = the transit chamber (warp-tunnel
// spokes + ribs around a distant black hole; the default). Further variants live in their own
// #if FAMILIAR_REALM branches in main(); each is a self-contained room that assigns `bg`.
// Swap live with ./use-realm.sh N (edits the installed shader + SIGUSR1), or change this line
// and make install.
#define FAMILIAR_REALM 1

// ---------------------------------------------------------------------------
float hash13(vec3 p){
  p = fract(p*0.1031);
  p += dot(p, p.zyx + 31.32);
  return fract((p.x + p.y)*p.z);
}
float vnoise(vec3 x){
  vec3 i = floor(x), f = fract(x);
  f = f*f*(3.0-2.0*f);
  return mix(mix(mix(hash13(i+vec3(0,0,0)), hash13(i+vec3(1,0,0)), f.x),
                 mix(hash13(i+vec3(0,1,0)), hash13(i+vec3(1,1,0)), f.x), f.y),
             mix(mix(hash13(i+vec3(0,0,1)), hash13(i+vec3(1,0,1)), f.x),
                 mix(hash13(i+vec3(0,1,1)), hash13(i+vec3(1,1,1)), f.x), f.y), f.z);
}
// Ridged noise. Plain value noise is smooth and gives soft, aurora-like sheets; folding it about
// its midpoint gives thin CREASES, and raising those to a power leaves only the crease - a bright
// filament with darkness either side. That is the difference between a glow and a bolt.
float ridge(vec3 p){ return 1.0 - abs(vnoise(p)*2.0 - 1.0); }
mat2 rot2(float a){ float c=cos(a), s=sin(a); return mat2(c,-s,s,c); }
vec3 aces(vec3 x){ return clamp((x*(2.51*x+0.03))/(x*(2.43*x+0.59)+0.14), 0.0, 1.0); }


// ---------------------------------------------------------------------------
// GENOTYPE (GENOTYPE.md). uGene carries the parameters that say what this being
// IS, as opposed to the uValence..uTension block which says how it FEELS. Read
// from ~/.config/familiar/genotype.json by the host; ABSENT IS A CIRCLE, so a
// missing or malformed file degrades to exactly the old body rather than to a
// black screen (WL-2).
//   [0] = shape family, blend, focal(a), cassini b
//   [1] = lobe balance, superM, superN1, superN2
//   [2] = superN3, superA, superB, aspect
//   [3] = rotation, twist, paletteHueRotation, paletteSaturation
//   [4] = warmth, breathDepth, bumpAmp, silkChurn
//   [5] = specSharp, haloReach, specGain, fresnelGain
//   [6] = tempoBase, bodyScale, haloGain, irritationGain
//   [7] = lightAzimuth, bumpScale, paletteLightness, (reserved)
uniform vec4 uGene[8];   // 32 slots, 31 of them claimed. Slot 31 remains RESERVED.
// moteGain and ejectRate were wired here and REMOVED before shipping: both feed `moteA`, which
// only reaches `cover`, and cover is discarded wherever uPresence is 1. Swept across the moods
// that produce motes and ejecta, neither changed a single pixel in any configuration that could
// be measured. A gene that cannot be shown to do something is the warmth defect again.
//
// EVERY gene below is wired in BOTH theme branches, and both are measured: the bench reads the
// shader as a file, so `sed 's/FAMILIAR_THEME 2/FAMILIAR_THEME 0/'` into a copy renders the
// other theme with no rebuild. Wiring a theme nobody can render would be a claim, not a gene.

// --- Cassini oval, polar form -----------------------------------------------
// Implicit: |p-f1| * |p-f2| = b^2, foci at (+/-a, 0). Solving for r at angle th:
//     r^2 = a^2*cos(2th) +/- sqrt(b^4 - a^4*sin^2(2th))
// The discriminant goes NEGATIVE past the lobe tips, where that angle has no
// boundary at all. Returns BOTH roots. The outer one is the silhouette; the inner one only exists when
// a > b, and it is the hole in the middle - the gap that makes two separate lobes two
// separate lobes. An earlier cut of this returned the + root alone, which is correct
// for a <= b and quietly WRONG above it: the waist filled in and every "split" case
// rendered as a solid bowtie. Measured, not reasoned - a scanline through the centre
// reported inside=True at a=1.40, where the figure should have been empty.
vec2 cassiniRoots(float th, float a, float b) {
  float a2 = a*a, a4 = a2*a2;
  float b4 = b*b*b*b;
  float s = sin(2.0*th);
  float disc = b4 - a4*s*s;
  if (disc < 0.0) return vec2(0.0);    // no boundary at this angle: past the lobe tips
  float k = a2*cos(2.0*th);
  float root = sqrt(disc);
  float r2o = k + root;                // outer boundary
  float r2i = k - root;                // inner boundary; <= 0 means no hole
  return vec2(r2o <= 0.0 ? 0.0 : sqrt(r2o),
              r2i <= 0.0 ? 0.0 : sqrt(r2i));
}

// --- Superformula (Gielis) --------------------------------------------------
//     r(th) = ( |cos(m*th/4)/A|^n2 + |sin(m*th/4)/B|^n3 ) ^ (-1/n1)
// The exponents are guarded away from zero: n1 near 0 sends the reciprocal to
// infinity, and pow() of a negative base is undefined behaviour on real drivers -
// the same class of UB already guarded elsewhere in this shader.
float superR(float th, float m, float n1, float n2, float n3, float A, float B) {
  float mm = m*th*0.25;
  float ca = abs(cos(mm)/max(A, 1e-3));
  float sa = abs(sin(mm)/max(B, 1e-3));
  float t1 = pow(max(ca, 1e-6), max(n2, 1e-3));
  float t2 = pow(max(sa, 1e-6), max(n3, 1e-3));
  float sum = max(t1 + t2, 1e-6);
  return pow(sum, -1.0/max(n1, 1e-3));
}

// --- The dispatcher ---------------------------------------------------------
// p        offset from the body centre, in the same units familiar.frag uses for uv
// gShape   0 = circle (identity: byte-for-byte the old behaviour), 1 = cassini,
//          2 = superformula, 3 = blend of 1 and 2
// gBlend   crossfade for mode 3
// Returns the normalised distance described in the contract above.
float shapeDist(vec2 p,
                float gShape, float gBlend,
                float gFocal, float gCassB, float gLobe,
                float gM, float gN1, float gN2, float gN3, float gSA, float gSB,
                float gAspect, float gRot, float gTwist,
                float gScale) {
  // Aspect and rotation are applied to the SAMPLE, not the formula, so they compose
  // with every family for free.
  float rl = length(p);
  float ct = cos(-gRot), st = sin(-gRot);
  vec2 q = vec2(p.x*ct - p.y*st, p.x*st + p.y*ct);
  q.x /= max(gAspect, 1e-3);
  q.y *= max(gAspect, 1e-3);

  // Twist: orientation that varies with radius, which shears lobes into a spiral.
  float th = atan(q.y, q.x) + gTwist*rl;

  // Lobe balance: bias one half of the figure larger. Applied as an angular gain so
  // a figure-of-8 can have a big head and a small tail.
  float bal = 1.0 + gLobe*0.45*cos(th);

  float r = 1.0;
  float rInner = 0.0;
  if (gShape < 0.5) {
    r = 1.0;                                            // circle - the identity case
  } else if (gShape < 1.5) {
    vec2 cr = cassiniRoots(th, gFocal, gCassB);
    r = cr.x; rInner = cr.y;
  } else if (gShape < 2.5) {
    r = superR(th, gM, gN1, gN2, gN3, gSA, gSB);
  } else {
    vec2 cr = cassiniRoots(th, gFocal, gCassB);
    float rs = superR(th, gM, gN1, gN2, gN3, gSA, gSB);
    float bl = clamp(gBlend, 0.0, 1.0);
    r = mix(cr.x, rs, bl);
    rInner = cr.y*(1.0 - bl);                           // the hole fades out as we blend away
  }
  r *= bal;
  rInner *= bal;

  // r == 0 means "this angle is outside the figure entirely" (a parted Cassini). A
  // huge distance puts it firmly outside every downstream test, which is what a gap
  // should look like. Without this the divide would produce inf/NaN and the driver
  // would paint whatever fell out of it.
  if (r <= 1e-4) return 1e4;
  float lq = length(q);

  // A PARTED BODY HAS NO CENTRE, so it cannot be measured from one.
  //
  // Measured before this branch existed: a genotype past the split rendered at 5.9% lit with
  // a peak of 39/255, and the bench called it SUSPECT (flat/black). The silhouette was right -
  // the lobes exist within +/-20.5 degrees and span r 0.616..1.351 - but every downstream
  // consumer measures depth as distance from the figure's centre, and the figure's centre is
  // the empty gap between the lobes. Each lobe rendered as the outer rind of a sphere whose
  // glowing middle had been cut out.
  //
  // So when the body is parted, depth is measured across the LOBE's own thickness instead:
  // 0 on its radial mid-line, 1 at both of its boundaries. That preserves the contract exactly
  // (1.0 on the silhouette, <1 inside, >1 outside), so the ~20 `scale`-relative comparisons
  // downstream keep their meaning, while giving the interior a core to build light around.
  //
  // Only when parted. For rInner == 0 the same formula would read 1.0 at the body's CENTRE,
  // which would invert every unparted familiar - so the unparted path is untouched and stays
  // pixel-identical to what is already verified.
  if (rInner > 1e-4) {
    // UNITS. The contract is not "1.0 on the silhouette" as the header above once said - it is
    // that the returned value equals `scale` there, because every downstream test compares it
    // against `scale`. The unparted `lq/r` satisfies that because the boundary sits at
    // lq = r*scale. A first cut of this branch returned a dimensionless 0..1 and the body
    // vanished completely: rendered, measured 5.8% lit, and the image was pure background.
    //
    // So the lobe's mid-line has to be located in the SAME units as lq, which means knowing
    // `scale`. It is threaded in rather than guessed, and it is used ONLY here.
    float midUv  = (rInner + r)*0.5*gScale;   // the lobe's radial centre, in uv
    // Guarded: at the lobe TIPS the two boundaries meet, the half-thickness goes to zero, and
    // an unguarded divide would send the tips to infinity - a body with its points snipped off.
    float halfT  = max((r - rInner)*0.5, 1e-4);
    if (lq < rInner*gScale) return 1e4;       // the gap between the lobes: outside the body
    return abs(lq - midUv)/halfT;
  }
  return lq/r;
}

// --- GENOTYPE HUE ------------------------------------------------------------
// Rotates a colour about the achromatic axis. The YIQ form is used rather than a
// full RGB->HSV->RGB trip because it is three dot products and this runs per pixel
// per frame for every familiar on the page.
//
// APPLIED TO THE BODY PALETTE ONLY, AND BEFORE IRRITATION'S MAGENTA IS MIXED IN.
// That placement is the whole design. Magenta is the shader's single exception in a
// blue field and the phenotype spends it on exactly one state - a failed run. If a
// per-agent hue rotated it too, "magenta means failed" would become "some colour
// means failed, depending on which agent you are looking at", and the most valuable
// signal on the screen would stop being learnable. So identity tints the being and
// never touches the alarm.
vec3 hueRotate(vec3 c, float a) {
  float u = cos(a), w = sin(a);
  return clamp(mat3(0.299 + 0.701*u + 0.168*w, 0.587 - 0.587*u + 0.330*w, 0.114 - 0.114*u - 0.497*w,
                    0.299 - 0.299*u - 0.328*w, 0.587 + 0.413*u + 0.035*w, 0.114 - 0.114*u + 0.292*w,
                    0.299 - 0.300*u + 1.250*w, 0.587 - 0.588*u - 1.050*w, 0.114 + 0.886*u - 0.203*w) * c,
               0.0, 1.0);
}

// Saturation about luma. Kept narrow at the call site: a familiar desaturated to grey
// stops reading as alive, and one oversaturated stops reading as the same species.
vec3 saturate3(vec3 c, float k) {
  float l = dot(c, vec3(0.299, 0.587, 0.114));
  return clamp(mix(vec3(l), c, k), 0.0, 1.0);
}

// gene: lightAzimuth. The key light turns about the VIEW axis, so the highlight walks around
// the limb and can never end up behind the body. At 0 it is upper-left, where it has always
// been. Only x and y rotate: the light's angle TO the camera is therefore fixed, so the gene
// changes where the light comes from and never how much of it there is. Both themes call this
// rather than each spelling the constant out, so the identity cannot differ between them.
vec3 keyLight(float az) {
  const vec2 b = vec2(-0.50, 0.62);
  return normalize(vec3(b.x*cos(az) - b.y*sin(az), b.x*sin(az) + b.y*cos(az), -0.60));
}

// Convenience wrapper: unpacks uGene so call sites stay readable.
float bodyDist(vec2 p, float s) {
  return shapeDist(p,
    uGene[0].x, uGene[0].y, uGene[0].z, uGene[0].w,
    uGene[1].x, uGene[1].y, uGene[1].z, uGene[1].w,
    uGene[2].x, uGene[2].y, uGene[2].z, uGene[2].w,
    uGene[3].x, uGene[3].y, s);
}

void main(){
#if FAMILIAR_THEME == 2
  // ==========================================================================
  // THEME 2 - "silk" voice-agent body (imported design; helpers/uniforms shared
  // with the eye above). Autonomous gaze, no cursor tracking. Voice = swell +
  // brighten (the concentric ring systems from the import were removed).
  // ==========================================================================
  vec2 world = gl_FragCoord.xy*uPxScale + uOrigin;
  vec2 res = uWorldRes;
  vec2 uv  = (world - 0.5*res)/res.y;

  float fatigue = clamp(uFatigue, 0.0, 1.0);
  float lum     = clamp(uLuminosity, 0.0, 1.0);
  float irr     = clamp(uIrritation, 0.0, 1.0);
  float arousal = clamp(uArousal, 0.0, 1.0);
  float ten     = clamp(uTension, 0.0, 1.0);
  float att     = clamp(uAttention, 0.0, 1.0);
  float soc     = clamp(uSocial, 0.0, 1.0);
  float buo     = clamp(uBuoyancy, 0.0, 1.0);
  float voice   = clamp(uAudio.x, 0.0, 1.0);
  float vWARMTH = uGene[4].x;        // gene: warmth. The warm breath in the heart, and
                                    // the value theme 2 actually consumes (see WARMTH above).
  float tempo   = (0.26*uGene[6].x + 0.85*clamp(uArousal,0.0,1.0))*(1.0 - 0.45*fatigue);
  // The master clock IS an emotion readout: it runs at tempo, not wall speed. With no phenotype
  // published the host feeds the resting baseline (arousal ~0.07), so the being drifts at roughly
  // a sixth of its old fixed rate - an animated idle, not a canned loop racing through its moves.
  // When boltrig's emotion relay is live, arousal/fatigue speed and slow the whole world directly.
  float t       = iTime*0.40*tempo;

  int   gid = int(uGesture + 0.5);
  float ga  = clamp(uGestureAmt, 0.0, 1.0);
  float gSwell = 0.0, gBright = 0.0, gChurn = 0.0, gLean = 0.0, gWarm = 0.0;
  if (ga > 0.001) {
    if      (gid == 1) { gLean  += ga*0.9; }
    else if (gid == 2) { gBright+= ga*0.9;  gSwell += ga*0.03; }
    else if (gid == 3) { gSwell -= ga*0.09; gChurn += ga*1.3; }
    else if (gid == 4) { gSwell += ga*0.08; gBright+= ga*0.7; gWarm += ga*0.6; }
    else if (gid == 5) { gSwell += ga*0.04; gLean  += ga*0.4; }
    else if (gid == 6) { gLean  += sin(iTime*2.5)*ga*0.2; }
    else if (gid == 7) { gSwell -= ga*0.08; gLean  -= ga*0.7; gChurn += ga*0.9; }
    else if (gid == 8) { gBright+= ga*0.35*(0.6+0.4*sin(iTime*1.5)); }
  }

  float pres = smoothstep(0.0, 1.0, clamp(uPresence, 0.0, 1.0));
  // The wallpaper is retired, so the main pass stays hidden. The companion entrance uses the
  // black-hole aperture: fullHole opens with uAperture inside the companion porthole, the orb
  // scales up out of it, and realm-1's transit chamber becomes visible around the opening.
  float fullPhase = smoothstep(0.48, 0.98, pres);
  float dockPhase = 0.0;
  float fullHole = (uCompanion > 0.5) ? uAperture : 0.0;
  float dockHole = 0.0;
  float portalEnergy = max(fullHole, dockHole);
  float bodyPhase = max(fullPhase, dockPhase);
  float growP = fullPhase;
  // Bead pass: docked doughnut is always fully shown. Companion orb grows out of the aperture
  // as it opens (scale and fade follow uAperture) and realm-1 fades in behind it.
  if (uFill > 0.5 && uCompanion > 0.5) {
    pres = 1.0;
    fullPhase = uAperture;
    dockPhase = uAperture;
    growP = 0.0;
  }
  // the voice SWELLS the whole body - this is now its primary voice tell (rings removed).
  float breathe = 1.0 + (0.010 + 0.012*tempo)*sin(iTime*0.9) + 0.030*uAudio.y + 0.02*uBeat + 0.090*voice*uGene[4].y;          // gene: breathDepth
  float voiceScale = 1.0 + 0.10*voice;
  float scaleFull = 0.265*uGene[6].y*breathe*voiceScale*(1.0 + gSwell)*(1.0 - 0.05*fatigue)*(1.0 + 0.025*soc);
  float scaleDock = uScaleDock*breathe*(1.0 + gSwell*0.5)*(1.0 + 0.012*soc);
  // There is no travelling seed in the void. The old 0.0035-radius remnant was still visible as a
  // bright pixel and its interpolated centre made the supposed teleport read as physical movement.
  float scale = max(scaleDock*dockPhase + scaleFull*growP, 0.00001);

  vec2  m = (uMouse - 0.5)*vec2(res.x/res.y, 1.0)*2.0;
  // autonomous gaze: it looks around on its own; the cursor is not consulted
  vec2  gaze = vec2(sin(t*0.21 + sin(t*0.089)*2.1), cos(t*0.157 + sin(t*0.061)))*att;
  vec2  centreFull = gaze*0.030 + vec2(gLean*0.03, 0.0)
                   + vec2(0.0, (buo - 0.5)*0.028 + sin(t*0.9)*0.022*buo);
  vec2  centreDock = uCentreDock + gaze*0.005
                   + vec2(0.0, (buo - 0.5)*0.0018 + sin(t*0.9)*0.003*buo);
  // portalPos is kept as a PLACE for the realms (realm 1's room is oriented around it); the
  // being itself no longer travels from it - the entrance is a fade at the resting centre.
  vec2  portalPos = vec2(-0.03, 0.02);  // slightly off-centre, close to the orb's centre
  vec2 centre = (uFill > 0.5) ? centreDock : centreFull;

  // THE GENOTYPE RESHAPES THE BODY, NOT JUST ITS OUTLINE.
  //
  // A first cut changed only `dScreen` (the rim and the halo). It compiled, the uniform
  // demonstrably reached the shader, and it was still wrong: the contact sheet showed a
  // star-shaped WIRE around a perfectly circular ball, because the interior never asked
  // the genotype anything. Compiling is not rendering, and rendering is not looking.
  //
  // The fix is one definition rather than one per call site. `ro.xy` is remapped so its
  // LENGTH is the normalised shape distance (1.0 exactly on the silhouette) with its
  // DIRECTION untouched. Every consumer below is already written against that length -
  // the ray-sphere gate (disc = 1 - |ro.xy|^2), the lit normal, and the interior's own
  // sr0/chord - so all of them follow the shape from here, and none of them can drift
  // out of agreement with the rim, because there is only one answer to "how far out am I".
  //
  // For a circle bodyDist() returns length(), so rn == length(rxy), the remap is the
  // identity, and the pre-genotype body is preserved exactly.
  float dScreen = bodyDist(uv - centre, scale);
  vec2  rxy = (uv - centre)/scale;
  float rn  = dScreen/max(scale, 1e-6);
  float rl0 = length(rxy);
  vec3 ro = vec3(rl0 > 1e-6 ? rxy*(rn/rl0) : rxy, -3.0);
  vec3 rd = vec3(0.0, 0.0, 1.0);

  float b = dot(ro, rd);
  float c = dot(ro, ro) - RADIUS*RADIUS;
  float disc = b*b - c;

  // Keep the lows genuinely dark. The previous silk palette lifted every band toward
  // powder-blue, which erased both depth and fine structure after tonemapping.
  vec3 navy    = vec3(0.006,0.018,0.082);
  vec3 blue    = vec3(0.022,0.145,0.620);
  vec3 azure   = vec3(0.055,0.355,0.960);
  vec3 sky     = vec3(0.175,0.620,1.000);
  vec3 magenta = vec3(0.820,0.180,0.620);
  float val = clamp(uValence,0.0,1.0);
  // The genotype's middle palette colour is the body colour. Hue and
  // saturation are applied above; its authored lightness controls material
  // exposure here so a navy identity stays navy instead of being lifted into
  // the canonical electric-blue ramp. This is identity, not mood: phenotype
  // still changes structure and intensity downstream.
  float paletteLightness = clamp(uGene[7].z, 0.0, 1.0);
  float materialExposure = mix(0.12, 0.78, paletteLightness);
  vec3 base = mix(mix(navy, blue, smoothstep(0.00,0.55,val)),
                  mix(azure, sky, smoothstep(0.55,1.00,val)),
                  smoothstep(0.40,0.80,val));
  base = mix(base, sky,     clamp(gWarm,0.0,1.0)*0.6);
  // Identity tint. Slots 14/15 of the genotype, applied here and nowhere else.
  base = saturate3(hueRotate(base, uGene[3].z), 1.0 + uGene[3].w);
  base = mix(base, magenta, clamp(irr*0.70*uGene[6].w, 0.0, 1.0));   // gene: irritationGain
  base *= mix(vec3(0.90,0.94,1.12), vec3(1.02,0.98,1.06), clamp(uDay,0.0,1.0));
  base *= materialExposure;
  vec3 materialSky = vec3(0.45,0.75,1.00)*materialExposure;
  vec3 hot = mix(base, materialSky, 0.40 + 0.18*lum);
  hot = mix(hot, vec3(1.00,0.30,0.70), irr*0.75);   // irritation floods the highlights too

  vec3 col = vec3(0.0);
  float alpha = 0.0;
  // dScreen is computed once, above, where the body's ray origin is derived from it.
  // Two calls would be two chances to disagree.
  vec3  L = keyLight(uGene[7].x);                              // gene: lightAzimuth
  float excite = clamp(val*clamp(uArousal,0.0,1.0)*1.8 - 0.15, 0.0, 1.0);

  float near = 0.0;   // cursor proximity drives nothing here

  if (disc > 0.0) {
    float sq = sqrt(disc);
    float t0 = -b - sq;

    vec3  n    = normalize(ro + rd*t0);
    float ndl  = dot(n, L);
    float diff = clamp(ndl*0.80 + 0.22, 0.0, 1.0);
    float face = clamp(dot(n, -rd), 0.0, 1.0);
    float limb = pow(face, 0.55);

    vec3  bq = n*3.4*uGene[7].y + vec3(0.0, -t*0.30, 0.0);   // gene: bumpScale (frequency, not amplitude)
    float be = 0.40;
    vec3  bump = vec3(vnoise(bq + vec3(be,0,0)) - vnoise(bq - vec3(be,0,0)),
                      vnoise(bq + vec3(0,be,0)) - vnoise(bq - vec3(0,be,0)),
                      vnoise(bq + vec3(0,0,be)) - vnoise(bq - vec3(0,0,be)));
    vec3  nb = normalize(n + bump*(0.25 + 0.30*ten)*uGene[4].z);

    // ==================== INTERIOR: silk ====================
    vec2  sp    = ro.xy;
    float sr0   = length(sp);
    float chord = sqrt(max(1.0 - sr0*sr0, 0.0));

    float puls = 0.5 + 0.5*sin(t*0.90);

    vec2 nuc = gaze*0.10 + vec2(0.0, -0.22*fatigue);
    float nucD = length(sp - nuc);

    // BREATHING WARP (technique from MilkDrop 2's warp field, BSD - reimplemented with our
    // own constants): sin/cos pairs whose SPATIAL frequencies themselves drift over time,
    // applied as a domain distortion of the silk sampling coords only. The interior sways
    // with the bass; sp itself (nucleus, arcs, particles) and the silhouette stay put.
    // At rest the amplitude gates to zero and the silk samples exactly where it always did.
    vec2 warpV = vec2(0.0);
    float wAmp = 0.030*clamp(0.70*uAudio.y + 0.35*arousal + 0.45*uBeat, 0.0, 1.0)
               *(1.0 - 0.6*fatigue);
    if (wAmp > 0.002) {
      float wt = t*0.6;
      float wf0 =  9.3 + 3.2*cos(wt*1.31 + 8.0);
      float wf1 =  7.1 + 2.6*cos(wt*1.09 + 5.5);
      float wf2 =  8.6 + 2.8*cos(wt*1.19 + 2.6);
      float wf3 = 10.2 + 3.5*cos(wt*0.87 + 4.4);
      warpV = wAmp*vec2(sin(wt*0.34 + sp.x*wf0 - sp.y*wf3) + cos(wt*0.71 - sp.x*wf1 + sp.y*wf2),
                        cos(wt*0.39 - sp.x*wf2 - sp.y*wf1) + sin(wt*0.82 + sp.x*wf0 + sp.y*wf3));
    }

    float edge0 = mix(0.34, 0.45, ten);   // tension crispens the silk
    float edge1 = mix(0.76, 0.57, ten);
    float vortK  = 0.7 + 1.7*excite - 0.35*fatigue;
    vec3  aniso  = mix(vec3(1.05, 2.0, 1.05),
                       vec3(1.85, 1.35, 1.85),
                       max(excite*0.55, irr));
    vec3 deepTone = mix(navy*0.5, base*0.18, 0.5);
    deepTone = mix(deepTone, magenta*0.45, irr*0.8);
    vec3 liteTone = hot;
    vec3 inner = vec3(0.0);
    for (int j = 0; j < 2; j++) {
      float side = float(j)*2.0 - 1.0;               // -1 back, +1 front
      vec3 q = vec3(sp + warpV, side*chord*0.5);
      q.xz = rot2( gaze.x*0.25)*q.xz;
      q.yz = rot2(-gaze.y*0.20)*q.yz;
      float vort = exp(-nucD*nucD*2.5)*(1.10 + 0.25*side)*vortK*(0.70 + 0.30*sin(t*0.23));
      q.xy = rot2(vort)*q.xy;
      float rotA = t*(0.05 + 0.03*float(j)) + q.y*0.35
                 + sin(iTime*0.9 + q.y*2.0)*(0.20*irr + gChurn*0.15);
      q.xy = rot2(rotA)*q.xy;
      vec3 w = q*aniso*(1.0 + 0.5*ten)*mix(0.78, 1.22, val) + vec3(0.0, -t*0.09 + 0.30*fatigue, 0.0);
      float w1 = vnoise(w*1.1 + 3.7);
      float w2 = vnoise(w*1.7 + vec3(w1*2.2, 0.0, 0.0) - vec3(0.0, t*0.07, 0.0) + 9.1);
      float silk = vnoise(w*1.5 + vec3(w1, w2, w1)*(1.9 + 0.8*irr)*uGene[4].w);
      // (voice ripple removed - the orb swells on voice instead of ringing)
      silk += (vnoise(w*5.5 + vec3(0.0, iTime*1.2, 0.0)) - 0.5)*irr*0.55;   // anger: jagged chop
      float band = smoothstep(edge0, edge1, silk);
      band *= band;                               // more dark field, less milky midtone
      vec3 liteT = mix(liteTone, vec3(0.30,0.80,1.00)*materialExposure, w2*0.6*(1.0 - irr*0.8));
      float silkExposure = paletteLightness;
      vec3 lc = deepTone*(0.42 + 0.26*w1)
              + liteT*band*(0.48 + 0.38*lum)*silkExposure;
      float ribbon = pow(band*(1.0-band)*4.0, 2.0);
      lc += mix(sky, vec3(0.55,0.90,1.00), w1)*materialExposure*silkExposure*ribbon*(0.45 + 0.55*lum + 0.9*voice + 0.5*excite);
      // Fibre-level creases are what make the material survive a 4K close look. Two differently
      // scaled ridges prevent them reading as a single procedural grid; tension narrows and
      // brightens them, while fatigue lets them recede. These are emissive detail, not silhouette
      // displacement, so the sphere remains perfectly stable.
      float fibreA = pow(ridge(w*4.7 + vec3(w2*2.1, -t*0.11, w1*1.7)), 7.0 + 8.0*ten);
      float fibreB = pow(ridge(w.yzx*8.9 + vec3(13.7, t*0.07, -4.2)), 13.0 + 9.0*ten);
      float fibres = clamp(fibreA*0.72 + fibreB*0.42, 0.0, 1.0);
      fibres *= smoothstep(0.02, 0.35, chord)*(1.0 - 0.72*fatigue);
      lc += mix(hot, vec3(0.62,0.88,1.00)*materialExposure, 0.55)*fibres
          *(0.13 + 0.34*lum + 0.30*ten + 0.18*excite)*silkExposure;
      lc = mix(lc, magenta, irr*ribbon*0.5);
      lc += liteT*vort*0.12*excite;
      inner = mix(inner, lc, (j == 0) ? 1.0 : 0.55);
    }
    inner *= chord*(0.38 + 0.40*lum);

    // A compact resolved heart inside a much dimmer aura. The old single broad Gaussian occupied
    // most of the sphere and made an otherwise detailed body look out of focus.
    float heartBreath = 0.30 + 0.22*puls + 0.12*val + 0.10*arousal + 0.80*voice + 0.5*uBeat;
    heartBreath *= 1.0 - fatigue*0.12*(0.5 + 0.5*sin(iTime*2.0 + sin(iTime*0.6)));
    float heartAura = exp(-nucD*nucD*(10.5 - 2.5*lum))*heartBreath;
    float heartCore = exp(-nucD*nucD*(78.0 - 18.0*lum))*heartBreath;
    vec3 heartC = mix(vec3(0.90,0.95,1.00), vec3(1.00,0.48,0.12), clamp(vWARMTH,0.0,1.0));
    heartC = mix(heartC, vec3(1.00,0.40,0.70), irr*0.6);
    inner += heartC*(heartAura*(0.08 + 0.09*lum) + heartCore*(0.58 + 0.40*lum));
    inner += base*exp(-nucD*nucD*3.4)*0.12*(0.4 + 0.6*lum);

    // AURORA ARCS: slow luminous ring-segments sweeping the interior
    vec2  relA = sp - nuc;
    float iaA  = atan(relA.y, relA.x + 1e-6);
    float arcs = 0.0;
    for (int k = 0; k < 2; k++) {
      float aa = t*(0.06 + 0.045*float(k)) + float(k)*2.7;
      float win = pow(max(cos(iaA - aa), 0.0), 6.0);
      arcs += exp(-pow(nucD - (0.42 + 0.18*float(k)), 2.0)/0.005)*win;
    }
    inner += mix(hot, vec3(0.55,0.90,1.00), 0.5)*arcs*(0.10 + 0.18*lum + 0.25*excite + 0.15*arousal + 0.12*soc);

    // LENS RING: a faint refractive rim around the heart - the pupil of the thing
    inner += hot*exp(-pow(nucD - 0.34, 2.0)/0.0016)*(0.10 + 0.18*lum)*(1.0 - 0.5*fatigue);

    // METEOR: a rare bright streak crossing the interior
    float mCyc  = t*0.045*(1.0 + excite);
    float mSeed = floor(mCyc);
    float mProg = fract(mCyc);
    float mAng  = hash13(vec3(mSeed, 3.1, 7.7))*6.28318;
    vec2  mDir  = vec2(cos(mAng), sin(mAng));
    float mu = dot(sp - nuc, mDir), mv = dot(sp - nuc, vec2(-mDir.y, mDir.x));
    float mc = -0.9 + 1.8*mProg;
    float head = exp(-mv*mv/0.0007)*exp(-pow(max(mu - mc, 0.0), 2.0)/0.004)
               *exp(-max(mc - mu, 0.0)*6.0);
    float mAmp = smoothstep(0.0, 0.1, mProg)*smoothstep(1.0, 0.85, mProg)
               *(0.18 + 0.55*excite + 0.45*max(arousal, irr) + 1.2*uBeat);
    inner += mix(vec3(0.80,0.94,1.00), heartC, 0.4)*head*mAmp*1.6;

    // PARTICLES: mood-driven embers. The being is never fully still: a quiet drift always
    // breathes inside it, and each mood shapes that drift - calm floats upward, irritation
    // spits red embers, arousal brightens and speeds the swarm, social widens the reach.
    float mood = max(arousal, max(soc, lum*0.45));
    float pAmt = max(0.055*mood + 0.035*(1.0 - fatigue),
                     max(excite, irr)*(1.0 - 0.9*fatigue));
    if (pAmt > 0.001) {
      vec3 partCol = vec3(0.0);
      int pCount = 8 + int(clamp(float(arousal + soc + excite), 0.0, 1.0)*8.0);
      for (int k = 0; k < pCount; k++) {
        float seed = float(k)*7.31 + 2.7;
        float rnd  = hash13(vec3(seed, seed*1.7, seed*2.3));
        float rate = (0.040 + rnd*0.030)*(1.0 + 1.2*arousal + 2.0*irr)*(1.0 - 0.5*fatigue);
        float cyc  = t*rate + rnd*9.0;
        float prog = fract(cyc);
        float gen  = floor(cyc);
        float ang  = hash13(vec3(seed, gen, seed + gen*0.61))*6.28318;
        float curl = mix(prog*2.2, sin(prog*12.0)*0.9, irr)*(1.0 - 0.5*fatigue);
        float reach = 0.15 + prog*(0.52 + 0.35*soc + 0.40*arousal + 0.45*irr);
        float rise  = (1.0 - irr)*prog*0.16 + irr*sin(prog*8.0)*0.10;
        vec2  pp   = nuc + vec2(cos(ang + curl), sin(ang + curl))*reach
                   + vec2(0.0, rise);
        float fade = smoothstep(0.0, 0.12, prog)*smoothstep(1.0, 0.55, prog);
        float twk  = 0.7 + 0.3*sin(iTime*3.0 + seed*2.0);
        float pd   = length(sp - pp);
        vec3 calmC  = vec3(0.75,0.92,1.00)*1.8;
        vec3 socC   = mix(vec3(1.00,0.82,0.55), vec3(0.85,0.95,1.00), 0.5)*2.0;
        vec3 irrC   = vec3(1.00,0.30,0.55)*2.4;
        vec3 pc    = mix(mix(calmC, socC, soc*0.7), irrC, irr);
        pc = mix(pc, vec3(0.55,0.90,1.00)*2.2, excite*0.6*(1.0 - irr));
        float sharp = max(irr, arousal*0.5);
        float pGlow = exp(-pd*pd/mix(0.00065, 0.00038, sharp));
        float pCore = exp(-pd*pd/mix(0.000045, 0.000022, sharp));
        partCol   += pc*(pGlow*0.22 + pCore*1.65)*fade*twk;
      }
      inner += partCol*pAmt*(0.35 + 0.65*lum);
    }

    // ==================== SPECTRAL FILAMENT SHELL (V2 phase 1) ====================
    // A thin shell of radial fibres riding just under the skin. Screen-polar on purpose
    // (anti-pattern 5: structure that must stay sharp varies in screen space), and built
    // on sp, whose LENGTH is already the normalised shape distance - so the shell follows
    // the genotype silhouette for free and is faded out before it can ever touch the rim
    // (anti-pattern 1: the outline stays analytic; this is emission only).
    //
    // The behaviour, not just the look: calm = almost invisible. Voice and arousal EXTEND
    // the fibres inward from the skin; treble lights the fine second octave; tension pulls
    // the whole shell into thin needles; the beat and the churn gestures shake its twist
    // briefly; fatigue lets it recede. Fixed relationships for now - the modulation-matrix
    // config is a later phase.
    float filDrive = clamp(0.55*voice + 0.45*arousal + 0.35*uAudio.w + 0.30*ga + 0.25*excite,
                           0.0, 1.0)*(1.0 - 0.75*fatigue);
    if (filDrive > 0.02 && sr0 > 0.30) {
      // reach: how deep below the skin the fibres extend. The window grows inward as the
      // being speaks or activates; the outer edge dies at 0.975 so the silhouette is never
      // consulted, let alone disturbed.
      float reachIn = 0.10 + 0.42*filDrive + 0.10*soc;
      float rimIn   = 1.0 - reachIn;
      float filWin  = smoothstep(rimIn, min(rimIn + 0.22, 0.99), sr0)
                    * smoothstep(1.0, 0.975, sr0);
      if (filWin > 0.001) {
        vec2 fdir = sp/max(sr0, 1e-4);
        // spiral flow: fibre phase drifts with radius (thought leaving the core), and the
        // beat jolts the twist rather than the brightness - a shiver, not a strobe.
        float swirl = 0.55*sr0 + t*0.18 + 0.25*uBeat*sin(iTime*7.0) + 0.30*gChurn*sin(iTime*5.0);
        vec2 fd2 = rot2(swirl)*fdir;
        // Radially-elongated ridged noise: fast along the angle (the unit direction scaled
        // hard), slow along the radius - that anisotropy is what reads as fibres rather
        // than froth. Two octaves on different orientations so it never reads as one grid;
        // treble owns the fine octave. Sampling the unit direction keeps it seamless at pi.
        float sharp = 6.0 + 18.0*ten;
        float fibA = pow(ridge(vec3(fd2*13.0, sr0*3.0 - t*0.55)), sharp);
        float fibB = pow(ridge(vec3(fd2.yx*29.0, sr0*4.5 + t*0.35 + 7.3)), sharp*1.4);
        float fil = clamp(fibA*0.85 + fibB*0.55*(0.35 + 0.65*uAudio.w), 0.0, 1.0);
        fil *= filWin*(0.35 + 0.65*diff);          // concentrated on the lit side

        // HERO STREAMERS. The wash above gives density; these give individuals. Technique
        // from the plasma-globe family (reimplemented from scratch in 2D polar - the classic
        // implementations are non-libre, the idea is not): each of eight filaments has a
        // hashed home angle, a centreline that WANDERS with radius on its own noise, a
        // length owned by one audio band (bass-anchored streamers are long and slow, treble
        // ones short and flickery), and its own twinkle. They ride the same swirl as the
        // wash, so the two layers read as one combed material, not two effects.
        float angF = atan(fd2.y, fd2.x);
        float hero = 0.0;
        for (int i = 0; i < 8; i++) {
          float fi = float(i);
          float a0 = hash13(vec3(fi*3.17, 11.3, 5.9))*6.28318 + t*0.11;
          float bandMix = fi*0.1429;               // 0..1 across the eight streamers
          float bandE = mix(mix(uAudio.y, uAudio.z, smoothstep(0.0, 0.5, bandMix)),
                            uAudio.w, smoothstep(0.5, 1.0, bandMix));
          float wander = (vnoise(vec3(sr0*2.6 - t*0.7, fi*7.7, 3.3)) - 0.5)*0.55;
          float dAng = mod(angF - a0 - wander + 3.14159, 6.28318) - 3.14159;
          // reach: how deep this streamer dives below the skin - its band's energy decides
          float reachI = reachIn*(0.35 + 0.65*bandE);
          float winI = smoothstep(1.0 - reachI, min(1.0 - reachI + 0.12, 0.99), sr0)
                     * smoothstep(1.0, 0.975, sr0);
          float flick = 0.55 + 0.45*hash13(vec3(fi, floor(iTime*5.0), 2.2));
          hero += exp(-dAng*dAng*sr0*sr0/0.0011)*winI*flick*(0.25 + 0.75*bandE);
        }
        hero = min(hero, 1.5);

    vec3 filC = mix(hot, vec3(0.62,0.88,1.00)*materialExposure, 0.5);
        filC = mix(filC, magenta, irr*0.55);       // irritation stains the needles
        inner += filC*fil*filDrive*(0.50 + 0.70*lum + 0.45*ten);
        inner += filC*hero*filDrive*(0.55 + 0.60*lum)*(0.35 + 0.65*diff);
      }
    }
    // ==================== end filament shell ====================

    float fatigueDim = mix(1.0, 0.45, fatigue);
    col = inner*fatigueDim;
    col *= 1.0 + near*0.15;
    alpha = clamp(chord*1.8, 0.0, 1.0);
    // ==================== end interior ====================

    col *= (0.72 + 0.45*diff)*mix(1.0, limb, 0.28);
    col = mix(col, col*vec3(0.45,0.70,1.30), pow(1.0 - face, 2.0)*0.45);   // limb dispersion
    col += hot*exp(-dScreen*dScreen/(scale*scale*0.16))*(0.05 + 0.16*lum)*(1.0 - 0.5*fatigue)*diff;

    float fres  = pow(1.0 - face, 3.2);
    float spec  = pow(max(dot(reflect(rd, nb), L), 0.0), 34.0*uGene[5].x);
    float glint = pow(max(dot(reflect(rd, nb), L), 0.0), 140.0);
    col += base*fres*(0.16 + 0.34*lum + 0.22*soc)*(0.30 + 0.70*diff)*uGene[5].w;          // gene: fresnelGain
    col += vec3(0.80,0.85,1.00)*spec*(0.10 + 0.18*lum)*(1.0 - 0.5*fatigue)*uGene[5].z;   // gene: specGain
    col += vec3(0.92,0.94,1.00)*glint*(0.5 + 0.8*lum)*(1.0 - 0.6*fatigue);
    vec3  L2 = normalize(vec3(0.55,-0.30,-0.60));
    float glint2 = pow(max(dot(reflect(rd, nb), L2), 0.0), 180.0);
    col += vec3(0.85,0.92,1.00)*glint2*(0.20 + 0.35*lum)*(1.0 - 0.6*fatigue);   // second catchlight
    alpha = max(alpha, fres*0.5);
  }

  col *= (1.0 - 0.42*fatigue);
  col *= (1.0 + gBright);
  // THE FADE: one envelope drives every visible term. It spans the whole migration so the being
  // reads as slowly materialising where it sits - no hot-birth boost, no steep ramp, no portal.
  float fade = smoothstep(0.02, 0.92, fullPhase);
  col *= fade;

  // corona: tight; social widens it; the voice makes it shimmer (but no concentric rings)
  float haloK = (34.0 - 16.0*soc)*uGene[5].y;                  // gene: haloReach
  float outside = smoothstep(scale*0.985, scale*1.010, dScreen);
  float halo = exp(-max(dScreen - scale, 0.0)*haloK/max(scale,0.02))*outside;
  halo *= smoothstep(scale*1.75, scale*1.02, dScreen);
  halo *= fade;
  float sonar = 0.0;   // concentric voice sonar rings removed; voice = swell + brighten only
  // Resolved orbital motes: a sub-pixel-hot core and a restrained glow, instead of the old
  // 10px blur blobs. Social moods hold a calm constellation; excited/irritated moods wake it up.
  float moteGlow = 0.0, moteCore = 0.0;
  float moteMood = clamp(soc*soc + 0.30*max(excite, irr) + 0.30*ga, 0.0, 1.0);
  if (moteMood > 0.38 && dScreen < scale*1.58) {
    for (int k = 0; k < 6; k++) {
      float fk = float(k);
      float ma2 = t*(0.13 + 0.028*fk)*(k == 1 || k == 4 ? -1.0 : 1.0) + fk*2.399;
      float orbit = 1.12 + 0.055*fk + 0.055*sin(t*0.31 + fk*1.7);
      vec2  mp  = centre + vec2(cos(ma2), sin(ma2))*scale*orbit;
      vec2  md  = uv - mp;
      moteGlow += exp(-dot(md,md)/(scale*scale*0.00038));
      moteCore += exp(-dot(md,md)/(scale*scale*0.000022));
    }
  }
  moteGlow *= moteMood*(0.3 + 0.7*pres);
  moteCore *= moteMood*(0.3 + 0.7*pres);
  moteGlow *= fade;
  moteCore *= fade;

  // Rim ejecta are a separate particle language from the orderly social motes: buoyant blue
  // thought-sparks at high arousal, tightening into fast magenta embers with irritation.
  float ejectGlow = 0.0, ejectCore = 0.0;
  float ejectAmt = clamp(max(smoothstep(0.35,0.85,excite)*0.75, irr) + 0.35*gChurn, 0.0, 1.0)
                 *(1.0 - 0.86*fatigue);
  // Below this threshold the odd barely-visible ember costs more than it communicates; reserve
  // ejecta for a clearly activated/irritated state and keep ordinary moods spatially quiet.
  if (ejectAmt > 0.08 && dScreen < scale*1.86) {
    for (int k = 0; k < EMBERS; k++) {
      float seed = float(k)*5.173 + 1.9;
      float rnd  = hash13(vec3(seed, seed*1.31, seed*2.07));
      float cyc  = t*(0.050 + 0.060*rnd)*(1.0 + 1.8*irr) + rnd*13.0;
      float prog = fract(cyc), gen = floor(cyc);
      float ea   = hash13(vec3(seed, gen, 8.4))*6.28318 + prog*(1.2 - irr);
      vec2 edir  = vec2(cos(ea), sin(ea));
      vec2 ep    = centre + edir*scale*(0.94 + prog*(0.36 + 0.38*irr))
                 + vec2(-edir.y, edir.x)*scale*sin(prog*3.14159)*0.10*(1.0 - irr)
                 + vec2(0.0, scale*prog*0.20*(1.0 - irr));
      float efade = smoothstep(0.0,0.12,prog)*smoothstep(1.0,0.58,prog);
      vec2 ed = uv - ep;
      ejectGlow += exp(-dot(ed,ed)/(scale*scale*mix(0.00025,0.00013,irr)))*efade;
      ejectCore += exp(-dot(ed,ed)/(scale*scale*mix(0.000018,0.000010,irr)))*efade;
    }
  }
  ejectGlow *= ejectAmt;
  ejectCore *= ejectAmt;
  ejectGlow *= fade;
  ejectCore *= fade;
  float moteA = clamp(moteGlow*0.30 + moteCore + ejectGlow*0.35 + ejectCore, 0.0, 1.0);
  vec3 particleC = mix(vec3(0.55,0.84,1.00), vec3(1.00,0.18,0.55), irr);
  vec3 outCol = col + base*halo*(0.22 + 0.45*lum + 0.6*uBeat + 0.5*voice + 0.32*portalEnergy)*(1.0 - 0.4*fatigue)*uGene[6].z   // gene: haloGain
              + base*sonar*(0.5 + 0.5*lum)
              + mix(base, vec3(0.75,0.92,1.00), 0.6)*(moteGlow*0.18 + moteCore*1.35)*(0.8 + 0.4*lum)
              + particleC*(ejectGlow*0.22 + ejectCore*1.55)*(0.7 + 0.5*lum);

  outCol = aces(outCol);
  outCol = pow(outCol, vec3(0.4545));

  // THE REALM: the room the being floats in. Variants are compiled in below and selected with
  // FAMILIAR_REALM (see the defines at the top of the file); swap with use-realm.sh N + SIGUSR1.
  // Each variant is self-contained: it must ASSIGN bg (the room colour, visibility included) and
  // nothing else. The contract they all share:
  //   - roomVis: 0 when docked/absent, 1 at full presence; held up by the aperture's energy so
  //     the room can answer the entrance before it has fully faded in. Variants may skip all
  //     work when roomVis <= 0.001.
  //   - portalPos/fullHole: portalPos orients the room; fullHole opens with uAperture in the
  //     summoned companion and is 0 otherwise.
  //   - mood: the nine phenotype scalars (val/irr/lum/ten/soc/buo/fatigue/att + arousal in tempo)
  //     drive every colour and motion decision; t is the emotion-scaled clock. Nothing snaps.
  //   - cheap: no marching, a handful of hashes/exps per pixel at most; it is background
  //     furniture sharing the GPU with real work (budget: the whole shader ~4 ms at 1080p).
  float realmOn = smoothstep(0.45, 1.0, pres)*(1.0 - step(0.5, uFill));
  float roomVis = max(realmOn, fullHole*0.9);
  vec3 bg = vec3(0.0);
#if FAMILIAR_REALM == 1
  // REALM 1 - THE TRANSIT CHAMBER (the default; reads as a distant black hole in a machine room).
  // The whole room is oriented around the portal's off-centre place, because that is where the
  // being comes from. Glacial warp-tunnel spokes stream toward the vanishing point; two vast
  // segmented ribs counter-rotate; while the aperture is open the room bends toward it, one
  // shockwave leaving it as the being emerges.
  if (roomVis > 0.001) {
    // Gravitational bend: while the aperture is open, the room's sampling position is pulled
    // toward it. Pure realm-side warp - the being itself is never distorted.
    vec2 suck = portalPos - uv;
    float sr2 = dot(suck, suck);
    vec2 realmUv = uv + suck*(fullHole*0.30/(1.0 + sr2*22.0));
    vec2 realmP = realmUv + vec2(t*0.0017, -t*0.0009);
    float dust = 0.50
               + 0.21*sin(dot(realmP,vec2(1.37, 2.11)) + t*0.004)
               + 0.16*sin(dot(realmP,vec2(-2.83,1.19)) - t*0.0027
                         + sin(realmP.y*1.71)*0.65)
               + 0.09*sin(dot(realmP,vec2(4.17,-3.23)) + 1.7);
    dust = smoothstep(0.35, 0.79, dust);

    // The chamber is oriented on the BEING'S resting place (screen centre), not the retired
    // portal's: when the room was centred on portalPos its ambient pool sat there as a glowing
    // oval with nothing in it - it read as a second orb and a leftover of the portal animation.
    vec2 rp = realmUv;
    float rr = max(length(rp), 0.015);
    float ra = atan(rp.y, rp.x);
    // The shockwave: born at the aperture while it is fully open, expanding as the hole closes.
    float wave = exp(-pow((rr - (1.0 - fullHole)*0.85)/0.035, 2.0))*fullHole;

    // Warp-tunnel spokes: hashed angular sectors, each a full-length streak with brightness bands
    // sliding slowly toward the vanishing point - the classic tunnel rush, but glacial.
    float spokeSector = floor((ra/6.28318 + 0.5)*18.0);
    float spokeSeed = hash13(vec3(spokeSector, 7.7, 3.1));
    // Soft sector edges: hard angular cuts read as crude blocks, a feathered beam reads as light.
    float spokeF = fract((ra/6.28318 + 0.5)*18.0);
    float spokeEdge = smoothstep(0.00, 0.22, spokeF)*smoothstep(1.00, 0.78, spokeF);
    float band = pow(0.5 + 0.5*sin(log(rr)*9.0 - t*(0.9 + 1.3*spokeSeed) + spokeSeed*37.0), 3.0);
    float spokes = band*step(0.50, spokeSeed)*spokeEdge
                 * smoothstep(0.03, 0.12, rr)*smoothstep(1.30, 0.55, rr);

    // Ribs: two vast segmented arcs, counter-rotating so slowly the room reads as machinery.
    float rib1 = exp(-pow((rr - 0.42 - 0.020*sin(ra*3.0 + t*0.021))/0.014, 2.0))
               * smoothstep(0.2, 0.8, 0.5 + 0.5*sin(ra*7.0 + 1.3));
    float rib2 = exp(-pow((rr - 0.71 - 0.030*sin(ra*5.0 - t*0.013))/0.024, 2.0))
               * smoothstep(0.3, 0.9, 0.5 + 0.5*sin(ra*4.0 - 0.6));

    // NOTE the weights: realmC/ribC are tiny bases, so the multipliers are correspondingly large -
    // bg is added AFTER gamma, so what you see is what these numbers say.
    vec3 realmC = mix(vec3(0.008,0.045,0.095), vec3(0.115,0.012,0.090), irr*0.22);
    vec3 ribC   = mix(vec3(0.020,0.100,0.160), vec3(0.130,0.010,0.080), irr*0.30);
    bg = vec3(0.0030,0.0045,0.0105);
    bg += realmC*dust*(0.30 + 0.30*lum);
    // A sourceless ambience pooled around the vanishing point, so the chamber reads as a volume
    // even between its structures.
    bg += realmC*smoothstep(1.25, 0.15, rr)*(0.60 + 0.50*lum);
    bg += realmC*spokes*(1.10 + 0.80*lum);
    bg += ribC*(rib1*1.30 + rib2*0.90)*(0.40 + 0.60*lum)*(0.35 + 0.65*dust);
    bg += mix(realmC, vec3(0.55,0.85,1.00), 0.5)*wave*0.80;

    // The Familiar illuminates its surroundings without creating a flat circular spotlight. Offset
    // ellipses make the light directional, as though suspended in a larger volume rather than
    // pasted over a black card.
    vec2 backD = (uv - centre - vec2(-0.08,0.055)*scale)/(scale*vec2(2.7,2.15));
    float backLight = smoothstep(1.0, 0.0, dot(backD,backD))*(0.18 + 0.40*lum)*(1.0 - 0.45*fatigue);
    vec2 castD = (uv - centre - vec2(0.48,-0.20)*scale)/(scale*vec2(3.4,1.35));
    float castLight = smoothstep(1.0, 0.0, dot(castD,castD))*(0.08 + 0.16*lum + 0.10*soc);
    bg += realmC*(backLight*0.22 + castLight*0.12);

    // Stars, lensed with the room: sparse resolved cores, icy and far away, twinkling on
    // incommensurate rates, with a restrained skirt rather than a bloom blob.
    vec2 starQ = (realmUv + vec2(0.91,0.47))*78.0;
    vec2 starCell = floor(starQ), starF = fract(starQ);
    float starSeed = hash13(vec3(starCell, 5.7));
    float starCore = 0.0, starSkirt = 0.0;
    if (starSeed > 0.994) {
      vec2 starPos = vec2(hash13(vec3(starCell,17.3)), hash13(vec3(starCell.yx,41.9)));
      float starD = length(starF - starPos);
      float starGate = smoothstep(0.994, 0.9995, starSeed);
      float twinkle = 0.58 + 0.42*sin(iTime*(0.31 + 0.37*starSeed) + starSeed*91.0);
      starCore = exp(-starD*starD/0.0018)*starGate*twinkle;
      starSkirt = exp(-starD*starD/0.012)*starGate*twinkle;
    }
    bg += vec3(0.42,0.68,1.00)*(starCore*0.48 + starSkirt*0.035)*(0.65 + 0.35*lum);
    bg *= roomVis;
  }
#elif FAMILIAR_REALM == 2
  // REALM 2 - THE CYLINDER. The being floats at mid-shaft inside a vertical cylinder so vast
  // that both directions along the axis dissolve into black. Nothing is marched: the screen is
  // mapped straight onto wall coordinates (azimuth across, height along the shaft) and every
  // cue - curvature, recession, plates, windows - is shading on that one map. An early flat
  // version (no azimuth warp, uniform light) read as a corridor wall; the tan-warp plus the
  // cosine limb falloff is what finally says "curved surface seen from inside".
  if (roomVis > 0.001) {
    // Azimuth. tan() crowds the vertical seams toward the limbs (grazing foreshortening) and
    // the light dies with the cosine: the facing wall carries the detail, the flanks curve
    // away. Both are needed - the warp without the falloff reads as a fisheye photograph.
    float az   = clamp(uv.x*1.10, -1.30, 1.30);
    float sX   = tan(az)*2.6;
    float limb = cos(az*1.12);
    limb = max(limb, 0.08);                 // the flanks never quite vanish: the wall continues
    limb *= limb;

    // Height along the shaft. The being hangs just below mid-shaft; dep measures axial
    // distance from that band and both directions recede: panels crowd with depth and the
    // wall dies to black past dep ~ 0.7 - the far reaches, where nothing is lit at all.
    float hgt  = uv.y + 0.03;
    float dep  = abs(hgt)*1.45;
    // The barrel term is the strongest cylinder cue in the whole room: deck rings above the
    // mid-band arc downward at the flanks, rings below arc upward - the way hoops of a real
    // silo bend when seen from inside. Without it the seams are ruled lines and the room
    // reads as a flat tiled wall; at 0.55 it overshot into fisheye and the room read as an
    // eyeball. 0.22 is where the hoops bend without the corners pinching shut - and the term
    // is damped at the mid-band, where undamped arcs from above and below pinched to a point
    // at the flanks and the wall read as an iris again.
    float sY   = hgt*(8.0 + dep*10.0) + sign(hgt)*sX*sX*0.27*smoothstep(0.02, 0.18, dep);
    float farK = exp(-dep*dep*3.8);

    // Wall plates: hashed cells with dark seams (bright seams read as neon; dark seams read
    // as joints between plates). Some plates sit recessed, some split into sub-panels - that
    // irregularity is the difference between "greeble" and "grid".
    vec2  wq    = vec2(sX*2.4, sY*1.25);
    vec2  wcell = floor(wq);
    vec2  wfr   = fract(wq);
    float wr    = hash13(vec3(wcell, 3.7));
    float wr2   = hash13(vec3(wcell, 9.1));
    float seamX = smoothstep(0.000, 0.050, wfr.x)*smoothstep(1.000, 0.950, wfr.x);
    float seamY = smoothstep(0.000, 0.065, wfr.y)*smoothstep(1.000, 0.935, wfr.y);
    float plate = 0.18 + 0.82*wr;
    plate *= mix(1.0, 0.30, step(0.78, wr2));                       // a fifth sit recessed
    plate *= 1.0 - step(0.55, wr2)*smoothstep(0.030, 0.0, abs(wfr.y - 0.5) - 0.015)*0.45;
    // Cross-splits on a different hash, so the subdivision never reads as one regular pattern.
    float wr4 = hash13(vec3(wcell, 27.1));
    plate *= 1.0 - step(0.62, wr4)*smoothstep(0.025, 0.0, abs(wfr.x - 0.5) - 0.012)*0.38;
    float wallM = plate*seamX*seamY;

    // Deck ribs: a broad horizontal band every seventh plate course - the structural rhythm
    // that sells "silo" over "wallpaper pattern".
    float rib = exp(-pow((fract(sY*0.1428) - 0.5)*7.0/0.42, 2.0));

    // Sparse lit windows: rare cells carry one tiny resolved lamp. Cool blue at rest,
    // magenta only under irritation; twinkling on incommensurate rates so nothing loops.
    float wr3 = hash13(vec3(wcell, 17.3));
    float win = 0.0;
    if (wr3 > 0.980) {
      vec2  wpos = vec2(hash13(vec3(wcell, 23.9)), hash13(vec3(wcell.yx, 31.7)))*0.55 + 0.22;
      float wd2  = dot(wfr - wpos, wfr - wpos);
      win = exp(-wd2/0.006)*smoothstep(0.980, 0.993, wr3)
          *(0.55 + 0.45*sin(iTime*(0.23 + 0.71*wr3) + wr3*57.0));
    }

    // The palette: the wall lives deep in the blue family and valence walks it along the same
    // ramp as the body; irritation stains the plates toward magenta, never the air itself.
    vec3 wallC = mix(vec3(0.022,0.058,0.135), vec3(0.060,0.185,0.410), val);
    wallC = mix(wallC, magenta*0.30, irr*0.35);
    vec3 winC = mix(vec3(0.45,0.72,1.00), vec3(1.00,0.22,0.60), irr);

    // NOTE the weights: wallC is a tiny base, so the multipliers are correspondingly large -
    // bg is added AFTER gamma, so what you see is what these numbers say. At the bench's
    // resting phenotype (lum 0, val 0) the facing wall should sit around 0.04-0.08: present,
    // but never contesting the corona.
    float lumK = 0.45 + 0.55*lum;
    float fatK = 1.0 - 0.55*fatigue;
    bg  = vec3(0.0022,0.0034,0.0080);
    bg += wallC*wallM*(limb*0.90 + 0.10)*farK*lumK*fatK*1.55;
    bg += mix(wallC, azure*0.5, 0.35)*rib*(limb*0.80 + 0.20)*farK*(0.45 + 0.55*lum)*1.15;
    bg += winC*win*limb*farK*(0.40 + 0.60*lum)*fatK*1.60;
    // Sourceless ambience pooled on the facing wall at mid-shaft, so the shaft reads as a
    // volume between its structures and not a textured card.
    bg += wallC*limb*farK*(0.35 + 0.45*lum);

    // The being's own light on the wall: an offset ellipse behind it, directional rather than
    // a flat spotlight, so it reads as suspended IN the shaft (same trick as realm 1 uses).
    vec2  backD = (uv - centre - vec2(-0.07,0.05)*scale)/(scale*vec2(3.1,2.4));
    float backL = smoothstep(1.0, 0.0, dot(backD,backD))*(0.16 + 0.38*lum)*(1.0 - 0.45*fatigue);
    bg += mix(wallC, base*0.6, 0.5)*backL*0.30;

    // The entrance: while the aperture is open a single slow shockwave leaves its place and
    // runs across the plates - the room answering the arrival before the being has grown.
    vec2  pp = uv - portalPos;
    float wave = exp(-pow((length(pp) - (1.0 - fullHole)*0.9)/0.045, 2.0))*fullHole;
    bg += mix(wallC, vec3(0.50,0.80,1.00), 0.5)*wave*0.55;

    // DRIFTERS. Two parallax layers of mood-coloured motes sharing the shaft's volume. The
    // near layer is a 3x3 cell search so sparks cross cell borders without popping; the far
    // layer is a single gated hash, dust so fine it only reads as grain in the light. Drift
    // is glacial on the emotion clock; irritation stirs it into rising embers, and the beat
    // breathes a little turbulence through the whole volume.
    vec3 sparkC = mix(mix(azure, sky, 0.4), vec3(0.60,0.86,1.00), 0.35);
    sparkC = mix(sparkC, vec3(1.00,0.20,0.58), irr);
    float stir = 1.0 + 1.6*irr + 0.9*uBeat + 0.6*uAudio.y;
    vec2  pvel = vec2(0.022, mix(0.009, 0.042, irr))*stir;
    vec2  pq = uv*22.0 + pvel*t;
    vec2  pc = floor(pq), pf = fract(pq);
    vec2  vhat = pvel/max(length(pvel), 1e-4);
    float nearGlow = 0.0, nearCore = 0.0, nearTrail = 0.0;
    for (int i = -1; i <= 1; i++)
    for (int j = -1; j <= 1; j++) {
      vec2  o  = vec2(float(i), float(j));
      vec2  cc = pc + o;
      float h1 = hash13(vec3(cc, 5.3));
      if (h1 < 0.72) continue;              // most cells stay empty: the volume is sparse
      float h2 = hash13(vec3(cc, 8.9));
      vec2  sd = (o + vec2(h1, h2)*0.8 + 0.1 - pf)/22.0;   // pixel-to-spark, in uv
      float d2 = dot(sd, sd);
      float tw = 0.45 + 0.55*sin(iTime*(0.2 + 0.9*h2) + h1*43.0);
      float bright = (h1 - 0.72)/0.28;
      nearGlow += exp(-d2/0.00008)*tw*(0.30 + 0.70*bright);
      if (bright > 0.60) nearCore += exp(-d2/0.00003)*tw;
      if (bright > 0.80) {
        // A faint comet tail behind the drift direction, only on the brightest sparks: the
        // one cheap cue that turns "floating dots" into "things that are going somewhere".
        float along = dot(sd, vhat), perp = dot(sd, vec2(-vhat.y, vhat.x));
        nearTrail += exp(-perp*perp/0.000012)*smoothstep(0.0, -0.004, along)
                    *smoothstep(-0.050, -0.015, along)*tw;
      }
    }
    // Far dust: one hash, one gate, one resolved grain. No neighbourhood search - at this
    // size a border pop is invisible, and the layer is only there to fill the light.
    vec2  fq = uv*95.0 + vec2(-0.012, 0.008)*t*stir;
    vec2  fc = floor(fq);
    float fh = hash13(vec3(fc, 12.1));
    float fdust = 0.0;
    if (fh > 0.975) {
      vec2  fpos = vec2(hash13(vec3(fc, 14.7)), hash13(vec3(fc.yx, 19.3)));
      float fd2  = dot(fract(fq) - fpos, fract(fq) - fpos);
      fdust = exp(-fd2/0.002)*smoothstep(0.975, 0.995, fh)
            *(0.5 + 0.5*sin(iTime*(0.3 + 0.5*fh) + fh*91.0));
    }
    float sparkAmt = (0.45 + 0.55*lum)*fatK*(1.0 + 0.5*uBeat);
    bg += sparkC*(nearGlow*0.10 + nearCore*0.30 + nearTrail*0.16)*sparkAmt;
    bg += sparkC*fdust*0.085*sparkAmt*(0.4 + 0.6*farK);

    bg *= roomVis;
  }
#elif FAMILIAR_REALM == 3
  // REALM 3 - EMBERFIELD. No architecture, no tunnel, no arcs: the room is only depth,
  // darkness and drifting fire. Three parallax layers of sparks hang in a near-featureless
  // expanse (near embers larger and sharper, far ones a dim fine grain), plus a sparse field
  // of bright flares that ignite and decay on their own incommensurate cycles, plus one very
  // light nebula banked in the deep back-left. It is the cheapest and quietest of the realms
  // on purpose - the being is the fire's subject, the field is only its weather, and the far
  // reaches fall to black. (Second tuning pass: the first read as "off" rather than "calm",
  // so the floor, drift and twinkle are all lifted about a third - still a restful field.)
  if (roomVis > 0.001) {
    // One audio read for the whole field: voice and beat STIR the embers (wider twinkle,
    // faster drift) rather than flashing them. A flash reads as a strobe; a stir reads as
    // wind moving through the room.
    float stir = 1.0 + 0.8*clamp(uAudio.x, 0.0, 1.0) + 0.5*uBeat;
    // Every motion rides t, the emotion-scaled clock. A wall-clock term here would keep the
    // room hurrying while the being rests; on t, a tired being dozes in a slow field.
    float dim = (0.60 + 0.75*lum)*(1.0 - 0.50*fatigue);
    // base already walks navy->sky with valence and floods magenta with irritation, so the
    // field inherits the mood for free; only a cool lean is added so the embers read as
    // light, not as paint.
    vec3 emberC = mix(base, vec3(0.45,0.75,1.00), 0.25);

    // The drift is ADDED TO THE CELL COORDS, so each layer slides bodily across the screen
    // at its own rate - that differential slide is the parallax; nothing else fakes depth.
    // Gate thresholds double as the spark's personality seed, so a brighter-gated spark also
    // twinkles on its own rate and phase.
    float sparks = 0.0;   // resolved cores, all layers
    float skirts = 0.0;   // a restrained halo, near layer only (far sparks carry no bloom)
    const float cellSz[3] = float[3](0.30, 0.16, 0.085);  // uv units: near cells are vast
    const float sig[3]    = float[3](0.0060, 0.0034, 0.0021);
    const float dens[3]   = float[3](0.45, 0.25, 0.18);   // gate: higher = fewer sparks
    const float layDim[3] = float[3](1.00, 0.62, 0.38);
    const float drift[3]  = float[3](0.022, 0.013, 0.007);
    for (int l = 0; l < 3; l++) {
      float fl = float(l);
      vec2 q = uv/cellSz[l] + vec2(fl*17.31, fl*9.17)
             + vec2(t*drift[l], -t*drift[l]*0.6)*stir;
      vec2 g0 = floor(q);
      // 2x2 neighbourhood: near embers are wide enough that a spark near a cell border
      // would pop in and out of existence with a single-cell lookup.
      for (int i = 0; i <= 1; i++)
      for (int j = 0; j <= 1; j++) {
        vec2 cell = g0 + vec2(float(i), float(j));
        float gate = hash13(vec3(cell, fl*3.71 + 1.3));
        if (gate > dens[l]) {
          vec2 sp = vec2(hash13(vec3(cell, fl*5.13 + 7.7)),
                         hash13(vec3(cell.yx, fl*4.37 + 2.9)));
          vec2 dd = (q - (cell + sp))*cellSz[l];   // back to uv units for a round spark
          float r2 = dot(dd, dd);
          // Twinkle never reaches zero: a spark that vanishes outright reads as a rendering
          // pop when it returns; a breath down to a fifth of peak reads as life.
          float tw = 0.60 + 0.40*sin(t*(0.45 + 1.0*gate)*stir*0.5 + gate*91.0);
          sparks += exp(-r2/(sig[l]*sig[l]))*max(tw, 0.0)*layDim[l];
          if (l == 0) skirts += exp(-r2/(sig[l]*sig[l]*16.0))*max(tw, 0.0)*0.18;
        }
      }
    }

    // The farthest reach is not resolved sparks but a fine dim GRAIN, a single cell lookup
    // at a scale where individual motes are a couple of pixels: at that depth a grain reads
    // as more distant than any discrete spark could, and it costs almost nothing.
    float grain = 0.0;
    {
      vec2 gq = uv*46.0 + vec2(t*0.05, -t*0.03)*stir;
      vec2 gcell = floor(gq);
      float gr = hash13(vec3(gcell, 11.7));
      if (gr > 0.72) {
        vec2 gf = fract(gq) - vec2(hash13(vec3(gcell, 12.9)), hash13(vec3(gcell.yx, 13.3)));
        float gtw = 0.5 + 0.5*sin(t*(0.5 + gr)*0.7 + gr*57.0);
        grain = exp(-dot(gf,gf)/0.02)*gtw;
      }
    }

    // FLARES: a sparse field of brighter sparks that ignite and decay on their own cycles -
    // a fast attack and a long exponential fall, the one event this quiet room allows
    // itself. Flare positions are kept to the middle of their cells, so a single-cell
    // lookup cannot clip the halo. Drift follows the far wind: flares are far-away things.
    float flare = 0.0;
    {
      vec2 fq = uv/0.42 + vec2(t*0.006, t*0.004)*stir;
      vec2 fcell = floor(fq);
      float fr = hash13(vec3(fcell, 23.3));
      if (fr > 0.72) {
        vec2 fp = 0.30 + 0.40*vec2(hash13(vec3(fcell, 24.1)), hash13(vec3(fcell.yx, 25.9)));
        vec2 fd = (fq - (fcell + fp))*0.42;
        float prog = fract(t*(0.020 + 0.045*fr) + fr*47.0);
        float env = smoothstep(0.0, 0.04, prog)*exp(-prog*5.5);
        flare = env*(exp(-dot(fd,fd)/0.00012) + 0.20*exp(-dot(fd,fd)/0.0035));
      }
    }

    // The field steps aside for the being: bg is composited UNDER the body, so without this
    // mask the near embers would shine through its dark limb and read as painted on it.
    float bodyMask = smoothstep(scale*0.85, scale*1.45, dScreen);
    // THE NEBULA: one very light cloud banked in the deep back-left, the field's only fixed
    // landmark. Two warped octaves of slow noise inside a radial falloff, kept under the
    // embers' brightness so it reads as distance haze rather than a second subject. It drifts
    // on t like everything else; irritation bruises it violet. Masked from the body's disc
    // like the embers, for the same reason.
    vec2 nebOff = uv - vec2(-0.58, 0.30);
    vec2 nebP = uv*1.35 + vec2(t*0.004, t*0.0025);
    float nebWarp = vnoise(vec3(nebP*1.7 + vec2(4.2, 1.3), t*0.010));
    float nebW = vnoise(vec3(nebP + 0.35*nebWarp, t*0.006));
    float nebula = smoothstep(0.42, 0.85, nebW)*exp(-dot(nebOff,nebOff)/0.22)*bodyMask;
    // The aperture stirs the field it opens into: while the hole is open, embers near it
    // burn briefly brighter, then settle - the room noticing the entrance, once.
    vec2 pd = uv - portalPos;
    float portalStir = 1.0 + fullHole*2.2*exp(-dot(pd,pd)/0.06);
    // The far reaches go to black. Without the vignette the expanse reads as a flat star
    // field wallpaper; falling to black at the edges is what makes it a PLACE with depth.
    float vig = smoothstep(1.25, 0.35, length(uv*vec2(0.95, 1.20)));

    // A near-black floor rather than a true void: the faintest blue wash keeps the expanse
    // present between the embers (and gives the dither something to hide in).
    bg = vec3(0.0012, 0.0020, 0.0048)*(0.55 + 0.60*lum)*vig;
    vec3 nebCol = mix(vec3(0.045, 0.10, 0.22), vec3(0.10, 0.05, 0.20), irr*0.6);
    bg += nebCol*nebula*(0.55 + 0.45*lum)*dim*vig;
    bg += emberC*(sparks*0.48 + skirts*0.16 + grain*0.20)*dim*bodyMask*portalStir*vig;
    bg += mix(hot, vec3(1.0), 0.30)*flare*0.60*dim*bodyMask*portalStir*vig;
    bg *= roomVis;
  }
#elif FAMILIAR_REALM == 4
  // REALM 4 - THE ABYSS: a flooded vertical shaft, dark water overhead and darker water below.
  // There is no floor, no wall, no surface to measure against - only a column of weight, and the
  // being hanging in it like a lantern someone lowered and forgot. The light comes from BELOW:
  // faint god-ray shafts climb out of a depth that should hold none (the trench light was chosen
  // deliberately - ceiling shafts made it a cave; up-light from nowhere is what reads as wrong).
  // Bioluminescent motes climb with it; heavy particulate sinks. Everything else drowns.
  if (roomVis > 0.001) {
    // Column-relative vertical: 0 at screen centre, +1 at the bottom. Every depth decision keys
    // off this so the haze, the shafts and the drift all agree about which way is down.
    float depth = 0.5 - uv.y;

    // THE DROWNING: the far reaches fall to black. The exponential (rather than a smoothstep) was
    // the difference between "gradient on a backdrop" and "attenuation through a medium" - below
    // the being the falloff is near-total, above it a cold residue survives so the top of the
    // frame is not a dead band.
    vec3 waterC = mix(vec3(0.020,0.048,0.088), vec3(0.105,0.020,0.090), irr*0.30);
    vec3 glowC  = mix(vec3(0.020,0.075,0.130), vec3(0.150,0.018,0.120), irr*0.35);
    float haze = exp(-max(depth, 0.0)*1.9)*smoothstep(1.7, 0.55, depth);
    bg = waterC*(0.55 + 0.45*lum)*haze;

    // The far source: a broad, sourceless wash climbing from the bottom of the frame. No core, no
    // rim - a visible emitter would make it geography. Valence cools it (happy abyss = glacial
    // teal, low valence = dead indigo); luminosity feeds it; fatigue starves it.
    vec3 shaftC = mix(vec3(0.016,0.070,0.120), vec3(0.120,0.016,0.095), irr*0.40);
    shaftC = mix(shaftC, shaftC*vec3(0.75,0.90,1.25), clamp(-uValence, 0.0, 1.0)*0.5);
    shaftC = mix(shaftC, shaftC*vec3(0.90,1.10,0.95), clamp( uValence, 0.0, 1.0)*0.35);
    float source = smoothstep(0.42, 1.45, depth);
    bg += glowC*source*(1.10 + 0.70*lum)*(1.0 - 0.55*fatigue);

    // GOD-RAY SHAFTS: angular fans converging far below the frame, sampled by ray-angle in shaft
    // space so they shear sideways as they climb. Angular sectors keep crisp silhouettes at every
    // radius; a vertical stripe field read as wallpaper. t crawls here - at idle the shimmer is
    // almost geological, which is the point: nothing down there is in a hurry.
    vec2 shaftOrg = vec2(0.12*sin(t*0.006), -1.55);
    vec2 sv = uv - shaftOrg;
    // Angle from straight-up (the +Y spoke of shaft space). Measured off +Y, not -Y: the first
    // version used atan(sv.x, -sv.y), which put the whole screen past |sa| = PI/2 and the fan's
    // own angular gate quietly killed every shaft it drew.
    float sa = atan(sv.x, sv.y);           // 0 = straight up from the source
    float sFade = smoothstep(0.95, 0.30, abs(sa))          // the fan dies toward the horizontal
               * smoothstep(0.05, 0.45, length(sv));       // no hot spot at the origin
    float shafts = 0.0;
    for (int k = 0; k < 3; k++) {
      float fk = float(k);
      // Sectors are counted PER RADIAN, not per revolution: the screen only ever shows a ~1.4
      // rad wedge of the fan, and revolution-counted sectors left two or three hashed gates to
      // decide the whole room - some frames had no beams at all.
      float sec = floor(sa*(7.0 + 3.0*fk));
      float sSeed = hash13(vec3(sec, fk*7.31, 2.9));
      float sFrac = fract(sa*(7.0 + 3.0*fk));
      float sEdge = smoothstep(0.0, 0.30, sFrac)*smoothstep(1.0, 0.70, sFrac);
      float breathe = 0.62 + 0.38*sin(t*(0.014 + 0.011*sSeed) + sSeed*41.0);
      // Each beam drowns at its own height - a shared horizontal cutoff drew a hard line across
      // the fan; staggered tops read as water of uneven density.
      float sTop = smoothstep(0.02 + 0.30*sSeed, -0.45, uv.y);
      shafts += step(0.55, sSeed)*sEdge*breathe*sTop/(1.0 + fk*0.7);
    }
    // Kept faint on purpose: at full gain the beams competed with the corona and the room stopped
    // being background. The being hangs just ABOVE the lit wedge, its own light the nearer one.
    bg += shaftC*shafts*sFade*(1.5 + 0.9*lum)*(1.0 - 0.45*fatigue);

    // THE BEING'S LIGHT: it is the only honest light in the column, so the water near it carries
    // its colour - a tall soft halo, weighted below the body as if its glow sinks. Kept well under
    // the corona's brightness; at 0.03-0.06 it tints the water without declaring a spotlight.
    vec2 backD = (uv - centre - vec2(-0.06,-0.10)*scale)/(scale*vec2(3.0,3.6));
    float backLight = smoothstep(1.0, 0.0, dot(backD,backD))*(0.20 + 0.45*lum)*(1.0 - 0.45*fatigue);
    bg += glowC*backLight*0.45;

    // MOTES: the living layer. Sparse cells, one resident each, climbing very slowly on the same
    // current the shafts imply, pulsing on private clocks like signalling plankton. Rising was
    // chosen over falling for the bright population - falling sparks read as ash, and this room
    // already has a sinking population for that. Two near layers at different cell scales are
    // enough to fake parallax; a third added shimmer, not depth.
    float motes = 0.0;
    for (int k = 0; k < 2; k++) {
      float fk = float(k);
      vec2 mq = (uv + vec2(0.0, t*(0.0022 + 0.0009*fk)))*(30.0 + 17.0*fk);
      vec2 mCell = floor(mq), mF = fract(mq);
      float mSeed = hash13(vec3(mCell, 3.3 + fk*9.1));
      if (mSeed > 0.945) {
        vec2 mPos = vec2(hash13(vec3(mCell, 17.3 + fk)), hash13(vec3(mCell.yx, 41.9 + fk)));
        // A slow private orbit so the climb is not a rail.
        mPos += 0.18*vec2(sin(t*0.020 + mSeed*37.0), cos(t*0.016 + mSeed*53.0));
        float mD = length(mF - mPos);
        float pulse = 0.35 + 0.65*pow(0.5 + 0.5*sin(t*(0.05 + 0.09*fract(mSeed*7.7)) + mSeed*91.0), 3.0);
        motes += exp(-mD*mD/0.006)*smoothstep(0.945, 0.975, mSeed)*pulse/(1.0 + fk*0.9);
      }
    }
    // Motes drown with everything else - glowing brightest just above the source, fading upward.
    bg += mix(vec3(0.35,0.80,1.00), magenta, irr*0.55)*motes
        * (0.18 + 0.16*lum)*(0.35 + 0.65*source)*(1.0 - 0.5*fatigue);

    // MARINE SNOW: the counter-current. Finer, dimmer, much denser cells drifting DOWN past
    // everything, twinkling only as they cross the being's light and the source wash. Kept faint:
    // at full brightness it read as static; the eye should find it only when it looks for it.
    vec2 nq = (uv + vec2(0.0, -t*0.0016))*95.0;
    vec2 nCell = floor(nq), nF = fract(nq);
    float nSeed = hash13(vec3(nCell, 8.9));
    float snow = 0.0;
    if (nSeed > 0.955) {
      vec2 nPos = vec2(hash13(vec3(nCell, 23.7)), hash13(vec3(nCell.yx, 55.1)));
      float nD = length(nF - nPos);
      float nTw = 0.5 + 0.5*sin(t*0.03 + nSeed*77.0);
      snow = exp(-nD*nD/0.006)*smoothstep(0.955, 0.985, nSeed)*nTw;
    }
    bg += vec3(0.20,0.42,0.62)*snow*0.10*(0.40 + 0.60*clamp(source + backLight, 0.0, 1.0));

    // THE ENTRANCE: while the aperture is open the column notices - one slow pressure ring rolling
    // downward off the portal, as if its opening displaced the water. No space-bending here: the
    // transit chamber warps because it is machinery; water answers with a wave.
    float pR = length(uv - portalPos);
    float pWave = exp(-pow((pR - (1.0 - fullHole)*0.9)/0.05, 2.0))*fullHole;
    bg += mix(glowC, vec3(0.45,0.80,1.00), 0.5)*pWave*0.35;

    bg *= roomVis;
  }
#endif
  outCol = bg + (1.0 - bg)*outCol;

  // THE BLACK HOLE APERTURE. Active only in the summoned companion (fullHole = uAperture);
  // the docked doughnut has no aperture (dockHole = 0). The spatial gate keeps the cost low
  // when the hole is closed or far from the current fragment.
  float coreF = 0.0, coreD = 0.0, ringF = 0.0, ringD = 0.0, lensF = 0.0, lensD = 0.0;
  // Transition-only gate: the black hole is strongest mid-opening/closing and disappears once
  // the companion has fully arrived, so the orb owns the centre instead of a lingering void.
  float holeGate = (uCompanion > 0.5) ? clamp(4.0*uAperture*(1.0-uAperture), 0.0, 1.0) : 0.0;
  // Uniform-coherent phase gate plus a spatial gate: settled frames do not even calculate portal
  // coordinates, and transition frames evaluate exponentials only near the two apertures.
  if (portalEnergy > 0.001) {
    vec2 hf = uv - portalPos;   // the full aperture lives at its own off-centre place, not under the body
    vec2 hd = uv - centreDock;
    float rf = length(hf), rdock = length(hd);
    if (rf < 0.18 || rdock < 0.065) {
      float af = atan(hf.y,hf.x), ad = atan(hd.y,hd.x);
      float holeRF = mix(0.032,0.058,fullHole);
      float holeRD = mix(0.009,0.019,dockHole);
      coreF = smoothstep(holeRF*1.02,holeRF*0.56,rf)*holeGate;
      coreD = smoothstep(holeRD*1.02,holeRD*0.52,rdock)*dockHole;
      ringF = exp(-pow((rf-holeRF)/0.0045,2.0))*holeGate
             *(0.64 + 0.36*sin(af*3.0 - iTime*4.1));
      ringD = exp(-pow((rdock-holeRD)/0.0023,2.0))*dockHole
             *(0.66 + 0.34*sin(ad*3.0 + iTime*5.3));
      lensF = exp(-pow((rf-holeRF*1.24)/0.008,2.0))*holeGate;
      lensD = exp(-pow((rdock-holeRD*1.26)/0.004,2.0))*dockHole;
    }
  }
  float holeCore = clamp(max(coreF,coreD),0.0,1.0);
  float portalCover = clamp(coreF + coreD + ringF + ringD + lensF*0.35 + lensD*0.35,0.0,1.0);
  vec3 portalC = mix(vec3(0.22,0.56,1.00),vec3(1.00,0.16,0.58),irr*0.62);
  outCol *= 1.0 - holeCore*0.985;
  outCol += portalC*(ringF*0.78 + ringD*0.92 + lensF*0.10 + lensD*0.14)
           *(0.65 + 0.35*lum);
  outCol *= 1.0 - 0.30*smoothstep(0.35, 1.15, length(uv))*mix(0.25, 1.0, pres)*(1.0 - step(0.5, uFill));

  // (screen-edge frame + rim line dropped - this desktop keeps no border, matching the eye)

  float g = hash13(vec3(gl_FragCoord.xy, fract(iTime)*91.0));
  outCol += (g - 0.5)*0.010*smoothstep(0.45, 1.0, pres);
  outCol += (hash13(vec3(gl_FragCoord.xy, 0.37)) - 0.5)/255.0*smoothstep(0.45, 1.0, pres);

  // CLOCKBAR SUMMON. Hover mist disabled: the blue cloud in the top-left was visually
  // intrusive and competed with the orb. barMistA stays zero so it contributes nothing to
  // coverage or colour, but the variable is preserved so later composition stays valid.
  float barMistA = 0.0;

  float cover = clamp(alpha + halo*0.9 + sonar*0.6 + moteA + portalCover + barMistA, 0.0, 1.0);
  float a = mix(cover, 1.0, smoothstep(0.45, 1.0, pres));
  float reach = length(centre - centreDock) + scale;
  if (uFill > 0.5) {
    if (uCompanion > 0.5) {
      // Companion: show the full being, then feather the square porthole edge.
      a = cover;
      float edgeBand = min(uFitScale * 0.35, 0.04);
      float edgeFade = smoothstep(uFitScale, uFitScale - edgeBand, dScreen);
      a *= edgeFade;
    } else {
      // Docked clockbar indicator: a simple white doughnut that swells slightly on hover.
      vec2 d = uv - centreDock;
      float r = length(d);
      float outer = uScaleDock * 0.85 * (1.0 + uHover * 0.12);
      float inner = outer * 0.55;
      float w = 0.0025;
      float ring = smoothstep(outer + w, outer - w, r) * smoothstep(inner - w, inner + w, r);
      float glow = exp(-r * r / (outer * outer * 0.55)) * (0.12 + 0.28 * uHover);
      outCol = vec3(0.92, 0.95, 1.0) * (0.82 + 0.18 * uHover);
      a = clamp(ring + glow, 0.0, 1.0);
    }
  }
  outCol = clamp(outCol, 0.0, 1.0);
  // Slight translucency for the summoned companion so the desktop never fully disappears.
  if (uCompanion > 0.5) a *= 0.88;
  fragColor = vec4(outCol*a, a);
#else
  vec2 world = gl_FragCoord.xy*uPxScale + uOrigin;
  vec2 res = uWorldRes;
  vec2 uv  = (world - 0.5*res)/res.y;

  float fatigue = clamp(uFatigue, 0.0, 1.0);
  float lum     = clamp(uLuminosity, 0.0, 1.0);
  float irr     = clamp(uIrritation, 0.0, 1.0);
  float ten     = clamp(uTension, 0.0, 1.0);
  float att     = clamp(uAttention, 0.0, 1.0);
  float soc     = clamp(uSocial, 0.0, 1.0);
  // STIR: how activated the being actually is. Slowing the clock alone was not enough - at rest it
  // still did everything, just slightly slower. This scales the AMPLITUDES too, so an idle mind is
  // nearly still: it breathes, it drifts, and that is all. Everything that twitches, sparks, flares
  // or crackles is gated behind it, and only real mood opens the gate.
  float stir    = clamp(1.15*clamp(uArousal,0.0,1.0) + 0.9*irr + 0.6*ten
                    + 1.2*clamp(uGestureAmt,0.0,1.0), 0.0, 1.0);
  float speed   = (0.22 + 1.35*clamp(uArousal,0.0,1.0))*(1.0 - 0.45*fatigue);
  float t       = iTime*speed;

  // --- voluntary gesture (WL-3): a transient act layered over the mood ---
  int   gid = int(uGesture + 0.5);
  float ga  = clamp(uGestureAmt, 0.0, 1.0);
  float gSwell = 0.0, gBright = 0.0, gChurn = 0.0, gLean = 0.0, gWarm = 0.0;
  if (ga > 0.001) {
    if      (gid == 1) { gLean  += ga*0.9; }
    else if (gid == 2) { gBright+= ga*0.9;  gSwell += ga*0.03; }
    else if (gid == 3) { gSwell -= ga*0.09; gChurn += ga*1.3; }
    else if (gid == 4) { gSwell += ga*0.08; gBright+= ga*0.7; gWarm += ga*0.6; }
    else if (gid == 5) { gSwell += ga*0.04; gLean  += ga*0.4; }
    else if (gid == 6) { gLean  += sin(iTime*2.5)*ga*0.2; }
    else if (gid == 7) { gSwell -= ga*0.08; gLean  -= ga*0.7; gChurn += ga*0.9; }
    else if (gid == 8) { gBright+= ga*0.35*(0.6+0.4*sin(iTime*1.5)); }
  }

  // --- presence: bare desktop vs bead in the bar (unchanged host choreography) ---
  float pres = smoothstep(0.0, 1.0, clamp(uPresence, 0.0, 1.0));
  float moveP = smoothstep(0.03, 0.62, pres);
  float growP = smoothstep(0.40, 0.97, pres);
  float travelP = sin(moveP*3.14159265)*(1.0 - growP);
  float breathe = 1.0 + 0.018*sin(t*0.9) + 0.030*uAudio.y + 0.02*uBeat;
  float scaleFull = 0.275*breathe*(1.0 + gSwell)*(1.0 - 0.05*fatigue);
  float scaleDock = uScaleDock*breathe*(1.0 + gSwell*0.5)
                  * (1.0 + 0.045*sin(t*0.83 + 2.2)*clamp(uBuoyancy,0.0,1.0));
  float scale = mix(scaleDock, scaleFull, growP) + travelP*0.018;

  // THE MOUSE, MEASURED FROM THE BEING - not from screen centre. This is the fix for "when it moves
  // to the corner it still follows the mouse as if it were centred": every gaze/lean/turn keys off
  // `m`, and `m` used to be (cursor - screen-centre), which only pointed the right way while the eye
  // happened to sit in the middle. Now it is (cursor - the being's home), so it looks at your cursor
  // wherever it lives. `home` is the base position before the tiny lean/bob, which breaks the old
  // circular dependency (m fed the lean fed centre fed... ). The *2.0 keeps the full-screen feel
  // byte-for-byte identical to before, since home is ~0 there.
  vec2  cursorUV = (uMouse - 0.5)*vec2(res.x/res.y, 1.0);
  vec2  journey = -uCentreDock;
  float journeyLen = max(length(journey), 1e-4);
  vec2  journeyPerp = vec2(-journey.y, journey.x)/journeyLen;
  vec2  home = mix(uCentreDock, vec2(0.0), moveP)
             + journeyPerp*min(journeyLen*0.055, 0.048)*sin(moveP*3.14159265);
  vec2  m = (cursorUV - home)*2.0;

  // Resting-place movement. At 30 px a subtle drift is invisible, so it moves on THREE
  // incommensurate rates at once rather than bobbing like a metronome: a quick vertical bob, a
  // slower lateral sway (which makes it trace a lazy figure-eight rather than a line), and a slow
  // swell that is out of phase with both. Bounded so it stays inside its small porthole.
  float buo = clamp(uBuoyancy,0.0,1.0);
  float dockBob   = sin(t*(0.85 + 0.9*stir))*0.0060*buo + sin(t*2.17 + 1.1)*0.0016*buo*stir;
  float dockSway  = sin(t*0.61 + 0.7)*0.0034*buo + sin(t*0.29)*0.0012;
  vec2  lean = m*mix(0.004, 0.035, pres)*(att + gLean);
  vec2  bob  = vec2(dockSway*(1.0 - pres),
                    mix(dockBob, sin(t*0.55)*0.012*buo, pres));
  vec2  centre = home + lean + bob;

  // Orthographic rays: the silhouette stays an exact circle on screen.
  vec3 ro = vec3((uv - centre)/scale, -3.0);
  vec3 rd = vec3(0.0, 0.0, 1.0);

  float b = dot(ro, rd);
  float c = dot(ro, ro) - RADIUS*RADIUS;
  float disc = b*b - c;

  // --- palette: BLUE over black. Valence walks navy -> blue -> cerulean -> electric sky.
  // Magenta is irritation's single exception. WARMTH tints only the core's ember. ---
  vec3 navy    = vec3(0.014,0.040,0.150);
  vec3 blue    = vec3(0.040,0.215,0.760);
  vec3 azure   = vec3(0.090,0.430,0.980);
  vec3 sky     = vec3(0.220,0.650,1.000);
  vec3 magenta = vec3(0.820,0.180,0.620);
  float val = clamp(uValence,0.0,1.0);
  float paletteLightness = clamp(uGene[7].z, 0.0, 1.0);
  float materialExposure = mix(0.12, 0.78, paletteLightness);
  vec3 base = mix(mix(navy, blue, smoothstep(0.00,0.55,val)),
                  mix(azure, sky, smoothstep(0.55,1.00,val)),
                  smoothstep(0.40,0.80,val));
  base = mix(base, sky,     clamp(gWarm,0.0,1.0)*0.6);
  // Identity tint. Slots 14/15 of the genotype, applied here and nowhere else.
  base = saturate3(hueRotate(base, uGene[3].z), 1.0 + uGene[3].w);
  base = mix(base, magenta, clamp(irr*0.70*uGene[6].w, 0.0, 1.0));   // gene: irritationGain
  base *= materialExposure;
  // (The time-of-day tint is gone: colour belongs to boltrig's emotion engine alone. uDay stays in
  // the contract but paints nothing.)
  vec3 hot   = mix(base, vec3(0.40,0.64,1.00)*materialExposure, 0.26 + 0.16*lum);   // moonlit, not lit
  vec3 ember = mix(hot, vec3(1.00,0.60,0.36), WARMTH);   // the warm heart

  vec3 col = vec3(0.0);
  float alpha = 0.0;
  float dScreen = bodyDist(uv - centre, scale);
  vec3  L = keyLight(uGene[7].x);                              // gene: lightAzimuth

  // curiosity: it notices when your cursor comes near, and leans in. "Near" is measured in BODY
  // RADII, not screen units - docked in the bar it is a 36 px bead, and a fixed screen threshold
  // would have it reacting to a cursor seven body-lengths away. Now the cursor has to genuinely
  // approach it wherever it is, and the pupil's constriction (dilAmt's -0.45*focus) reads the same
  // at both sizes: the black centre visibly narrows as you close in, opens again as you leave.
  float near = smoothstep(8.0, 2.2, length(cursorUV - centre)/max(scale, 1e-3))*att;
  // FOCUS: how close your cursor is to the being. As you approach, the pupil tightens, the filaments
  // sharpen, the flame stands up and the whole eye burns harder. It is the difference between being
  // looked at and being LOOKED AT.
  float focus = clamp(near, 0.0, 1.0);

  if (disc > 0.0) {
    float sq = sqrt(disc);
    float t0 = -b - sq;

    // --- SURFACE: what makes it a ball, not a sticker (kept from the old body) ---
    vec3  n    = normalize(ro + rd*t0);
    float ndl  = dot(n, L);
    float diff = clamp(ndl*0.80 + 0.22, 0.0, 1.0);
    float face = clamp(dot(n, -rd), 0.0, 1.0);
    float limb = pow(face, 0.55);

    vec3  bq = n*3.4*uGene[7].y + vec3(0.0, -t*0.30, 0.0);   // gene: bumpScale (frequency, not amplitude)
    float be = 0.40;
    vec3  bump = vec3(vnoise(bq + vec3(be,0,0)) - vnoise(bq - vec3(be,0,0)),
                      vnoise(bq + vec3(0,be,0)) - vnoise(bq - vec3(0,be,0)),
                      vnoise(bq + vec3(0,0,be)) - vnoise(bq - vec3(0,0,be)));
    vec3  nb = normalize(n + bump*(0.30 + 0.35*ten));

    // ==================== INTERIOR (rebuilt) ====================
    vec2  sp    = ro.xy;                          // unit-sphere screen coords
    float sr0   = length(sp);
    float chord = sqrt(max(1.0 - sr0*sr0, 0.0));  // path thickness: free limb darkening

    // pulse rates deliberately incommensurate so nothing visibly loops
    float puls  = 0.5 + 0.5*sin(t*0.90);
    float puls2 = 0.5 + 0.5*sin(t*0.62 + 1.3);

    // NUCLEUS - the pupil. It looks AT your cursor while the cursor is alive, and when you stop
    // moving it (or take it to the other machine, which parks it against the screen edge) it gives
    // up on you and lets its eye drift on its own. uGaze is the host's judgement of which, smoothed.
    float gz = clamp(uGaze, 0.0, 1.0);

#if FAMILIAR_THEME == 0
    // It does not drift when it has nothing to watch - it SEARCHES. Saccades: it darts to a new
    // point of interest, then holds it and stares, then darts again. The hold is most of the cycle;
    // the dart itself is over in a fifth of a second, which is what makes it read as intent rather
    // than as floating.
    float sacT = t*(0.09 + 0.52*stir);   // idle: it holds a look for many seconds
    float seg  = floor(sacT), fr = fract(sacT);
    vec2  pA = vec2(hash13(vec3(seg,      3.1, 7.7)), hash13(vec3(seg,      11.3, 5.9)))*2.0 - 1.0;
    vec2  pB = vec2(hash13(vec3(seg+1.0,  3.1, 7.7)), hash13(vec3(seg+1.0,  11.3, 5.9)))*2.0 - 1.0;
    float dart = smoothstep(0.0, 0.16, fr);
    vec2 wander = mix(pA, pB, dart)*0.26;

    // Locked on, it swings hard and holds - a bigger throw than a polite glance, plus a fine tremor
    // so the stare is never quite still. Arousal makes the tremor sharper.
    vec2 tremor = vec2(sin(t*9.1 + 0.7), cos(t*11.7))*0.0075*(0.06 + 0.94*stir);
    // The pupil offset toward the cursor, capped so it never leaves the iris when the cursor is far
    // (docked, m can be large - the cursor may be most of a screen away from the bead).
    vec2  look = m*0.55;
    float ll   = length(look);
    look *= (ll > 0.62) ? 0.62/ll : 1.0;
    vec2 nuc = mix(wander, look*att, gz) + tremor*(0.5 + 0.5*gz);
    nuc.y -= 0.18*fatigue;

    // ---- CORNEAL REFRACTION: the single biggest realism gain (AMBITION.md section 3.1). ----
    // The iris is not ON the sphere, it is BEHIND it, seen through a curved fluid lens. So: refract
    // the view ray at the corneal surface (eta = 1/1.376, the real aqueous figure), then intersect
    // the iris plane sitting inside the sphere. Everything downstream keys off that hit point, which
    // buys, for the price of one refract() and a plane intersection: central magnification, features
    // sliding with viewing angle, and increasing distortion toward the limb - the exact cues that
    // said "pattern painted on a ball" before. A second, deeper plane gives the stroma a lower
    // storey; the parallax between the two storeys is genuine, not simulated.
    vec3  p0  = ro + rd*t0;
    vec3  rr  = refract(rd, n, 0.7267);          // into the denser medium; never a TIR case
    float rz  = max(rr.z, 1e-4);
    float sI  = (-0.58 - p0.z)/rz;               // upper stroma storey
    float sI2 = (-0.50 - p0.z)/rz;               // lower storey, 0.08 deeper
    vec2  ip  = p0.xy + rr.xy*sI;
    vec2  ip2 = p0.xy + rr.xy*sI2;
    vec2  rel  = ip  - nuc;
    vec2  rel2 = ip2 - nuc;
    float ia    = atan(rel.y, rel.x + 1e-6);
    float idist = length(rel) + 1e-6;

    // IRIS: filaments flow OUTWARD from the core - sentences leaving.
    // Screen-polar, so they stay razor-sharp (anti-pattern 5). Tension sharpens; a fine
    // nervous jitter rides on top of high tension.
    float aN = vnoise(vec3(sin(ia)*2.0, cos(ia)*2.0, idist*3.0 + t*0.05))*0.4;
    float ma = ia + aN + ten*ten*sin(t*12.0 + idist*24.0)*0.05;
    // A LARGER exponent makes pow(|sin|,shp) THINNER, not fatter - this was inverted, so tension
    // and focus were bloating the filaments into broad pale lobes and washing the whole midfield
    // white. Tension and focus both sharpen: thin bright creases on dark tissue.
    float shp = (2.0 + 3.5*ten)*mix(1.0, 1.9, focus);
    float flow = 1.0 + 0.9*clamp(uArousal,0.0,1.0) + 0.6*irr;
    float irs = pow(abs(sin(ma*4.0            + idist*2.0 - t*0.52*flow)), shp     )*0.5
              + pow(abs(sin(ma*6.5  + 1.9     + idist*3.5 - t*0.81*flow)), shp*1.15)*0.3
              + pow(abs(sin(ma*10.5 + 3.3     + idist*5.0 - t*0.37*flow)), shp*1.4 )*0.2;
    // A fine fourth octave that only resolves at 4K - fibre-level texture, so the eye survives being
    // zoomed instead of dissolving into gradients.
    irs += pow(abs(sin(ma*23.0 + 5.1 + idist*7.5 - t*0.21*flow)), shp*2.2)*0.14;
    // They belong to the iris, so they start just outside the pupil and are spent well before the
    // rim - they used to reach almost all the way across, which read as scratches rather than an eye.
    irs *= smoothstep(0.050, 0.115, idist)*smoothstep(0.96, 0.42, idist);

    // THE LOWER STOREY. Same fibrous language sampled at the deeper plane's own hit point, so it
    // slides against the upper storey with true parallax as the eye turns. The upper fibres cast a
    // contact shadow onto it, offset toward the light - occlusion is most of what makes stacked
    // tissue read as stacked rather than double-exposed.
    float ia2 = atan(rel2.y, rel2.x + 1e-6);
    float id2 = length(rel2) + 1e-6;
    float aN2 = vnoise(vec3(sin(ia2)*2.0, cos(ia2)*2.0, id2*3.0 - t*0.04))*0.4;
    float ma2 = ia2 + aN2;
    float irs2 = pow(abs(sin(ma2*7.0  + 0.8 + id2*2.6 - t*0.44*flow)), shp*1.2)*0.55
               + pow(abs(sin(ma2*15.0 + 2.6 + id2*4.4 - t*0.23*flow)), shp*1.7)*0.25;
    irs2 *= smoothstep(0.050, 0.115, id2)*smoothstep(0.96, 0.42, id2);
    {   vec2  shO = rel2 - normalize(L.xy)*0.045;
        float shA = atan(shO.y, shO.x + 1e-6), shD = length(shO) + 1e-6;
        float occ = pow(abs(sin((shA + aN)*4.0 + shD*2.0 - t*0.52*flow)), shp)
                  * smoothstep(0.05, 0.115, shD);
        irs2 *= 1.0 - 0.62*clamp(occ, 0.0, 1.0);
    }
    // Pigment grain: static per-position speckle ATTACHED TO THE TISSUE (it is keyed to rel, so it
    // moves with the iris, not with the screen). +-10%, invisible at a glance, felt at 200%.
    float grain = hash13(vec3(floor(rel*300.0), 17.0));

    // IRIS DETAIL. A real iris is not a smooth fan of filaments: it has crypts (irregular pits and
    // ridges near the pupil), a COLLARETTE - the raised ring about a third of the way out where the
    // pupillary zone meets the ciliary zone, the most recognisable landmark in an eye - and a dark
    // LIMBAL RING at the outer boundary. Those three are most of what makes an iris read as tissue
    // rather than as a graphic.
    float crypt  = ridge(vec3(cos(ia)*7.0, sin(ia)*7.0, idist*9.0 + t*0.05));
    crypt = pow(crypt, 3.0)*smoothstep(0.42, 0.13, idist);
    float collR  = 0.30 + 0.04*sin(t*0.3) + 0.05*(1.0 - lum);
    float coll   = exp(-pow((idist - collR)/0.045, 2.0));          // the raised ring itself
    float collSh = exp(-pow((idist - collR*1.32)/0.075, 2.0));     // and the shadow just outside it
    float limbal = smoothstep(0.62, 0.90, idist);                  // the dark outer boundary

    // directional light on the interior mass
    float litFace = dot(normalize(sp + 1e-6), L.xy)*0.5 + 0.5;

    // SHELLS: layered machinery. Smooth penetration weights (no ring artefacts), each
    // shell rotates at its own rate - twist varies with height AND position
    // (anti-pattern 4) - and the whole interior turns toward the cursor.
    float irisN = 0.0;
    vec3  layerCol = vec3(0.0);
    // The interior is never at rest. Its tempo is the mood itself: arousal drives the whole
    // machine, irritation makes it churn, tension winds it tighter. Even at zero arousal the shells
    // keep turning - a mind that has stopped moving is not thinking.
    // Slow at rest, quick when roused. The base rate is deliberately low so that a calm mind barely
    // stirs; almost all of the motion you see at speed is the mood, not the clock.
    float churn = 0.42 + 2.1*clamp(uArousal,0.0,1.0) + 1.4*irr + 0.6*ten + gChurn;
    for (int j = 0; j < SHELLS; j++) {
      // The shells used to stop at 0.87 of the radius with a hard 0.08-wide boundary, which drew a
      // visible inner circle: the mist ended in mid-air instead of thinning out. They now reach the
      // limb, and the boundary is soft enough that no single shell announces itself.
      float shellR = 0.16 + float(j)*0.21;
      float pen = clamp((shellR - sr0)/0.16, 0.0, 1.0);
      if (pen < 0.001) continue;
      float z = sqrt(max(shellR*shellR - sr0*sr0, 1e-4));
      vec3 hp = vec3(sp, z);
      hp.xz = rot2( m.x*att*0.30*gz)*hp.xz;       // interior faces the cursor
      hp.yz = rot2(-m.y*att*0.25*gz)*hp.yz;
      float spd = (0.048 + float(j)*0.034)*churn; // differential rotation: inner faster
      float rotA = t*spd + hp.y*2.0 + hp.x*0.5;
      vec3 rp = hp;
      rp.xz = rot2(rotA)*rp.xz;
      rp.yz = rot2(t*spd*0.55 + hp.z*0.7)*rp.yz;
      float n1 = vnoise(rp*(4.0 + float(j)*1.5) + vec3(0.0, 0.0, t*0.038*churn));
      float n2 = vnoise(rp*(8.0 + float(j))     + vec3(7.0, 0.0, t*0.052*churn));
      irisN += n1*(0.15 + float(j)*0.10)*pen;
      float layerD = (smoothstep(0.45,0.75,n1)*0.30 + smoothstep(0.50,0.80,n2)*0.15)*pen;
      // ...and it fades with the chord, so where the ray only clips the edge of the sphere there is
      // barely any mist to see. That is what makes it thin toward the rim instead of being cut off.
      layerCol += mix(base*0.70, hot, float(j)/4.0*0.5)*layerD*0.145
                * mix(0.4,1.0,litFace)*mix(0.06, 1.0, chord);
    }
    irisN = clamp(irisN, 0.0, 1.0);

    // BODY: genuinely dark. Most of the sphere is near-black navy; contrast is the game.
    vec3 bodyCol = navy*0.35*mix(0.25, 1.0, litFace)*chord*(0.15 + 0.85*lum);

    // The filaments are modulated by the crypts and interrupted by the collarette, then the whole
    // iris is darkened toward the limbus.
    float irisBright = irs*(0.05 + 0.95*max(irisN, 0.15))*(0.10 + 0.90*chord)
                     * (1.0 + 0.55*crypt - 0.30*collSh)
                     * (1.0 - 0.55*limbal)
                     * (0.90 + 0.20*grain);
    vec3 irisCol = hot*irisBright*2.45;   // audio no longer tints the iris - mood only
    // the lower storey is dimmer and cooler - light has been through more tissue to reach it
    float deep = irs2*(0.05 + 0.95*max(irisN, 0.15))*(0.10 + 0.90*chord)*(1.0 - 0.55*limbal);
    irisCol += mix(base, hot, 0.40)*deep*1.05;
    // subsurface scatter: thin fibres glow at their edges where light leaks THROUGH the stroma
    // rather than off it - strongest on the side away from the key light.
    float sss = pow(clamp(irs, 0.0, 1.0), 0.6)*(1.0 - clamp(irs, 0.0, 1.0))*(1.0 - litFace);
    irisCol += mix(hot, ember, 0.35)*sss*0.50*chord;
    irisCol += hot*coll*0.55*(0.25 + 0.75*lum)*chord*(0.6 + 0.4*irisN);   // the collarette catches light
    irisCol = mix(irisCol, magenta*irisBright*2.2, irr);
    irisCol += magenta*vnoise(vec3(sp*10.0, t*0.4))*irr*chord*0.4;   // agitation
#if FAMILIAR_IRIS == 0
    // no iris: drop the whole fibre fan / collarette / limbal contribution. The shells (layerCol),
    // the nucleus, the wreath flame, the aperture, the tapetum and the glass all remain.
    irisCol = vec3(0.0);
#endif

    // NUCLEUS: a pale mind with a warm ember inside
    float nucD    = length(rel);
    float flare   = 1.0 + 0.55*gz + 0.45*exp(-fr*7.0)*(1.0 - gz) + 0.85*focus;
    float nucCore = exp(-nucD*nucD/mix(0.0052, 0.0024, focus))*(0.60 + 0.40*puls)*flare;
    float nucMid  = exp(-nucD*nucD/0.015)*(0.40 + 0.30*puls)*flare;
    float nucGlow = exp(-nucD*nucD/0.030)*(0.30 + 0.30*puls2);
    vec3 coreC = mix(vec3(0.92,0.95,1.00), vec3(1.00,0.72,0.45), WARMTH*(0.5 + 0.25*puls));
    // The mind-light no longer washes the iris: the core blaze is mostly confined to the aperture
    // (it reads as light coming from INSIDE the head), and only a modest halo touches the tissue.
    vec3 nucCol = coreC*nucCore*3.0*lum
                + ember*nucMid*0.75*lum
                + mix(hot, ember, 0.3)*nucGlow*0.95;

    // WREATHED IN FLAME. Licks of fire standing off the pupil: high-frequency angular tongues whose
    // phase scrolls outward, turbulence-warped so they writhe rather than rotate, and flickering on
    // their own fast clock. They live in the mood's colour - blue normally, magenta when it is
    // irritated, with the ember's warmth closest to the core. Two noise calls, no march.
    float fTurb = vnoise(vec3(cos(ia)*2.3, sin(ia)*2.3, t*0.85 + idist*1.5));
    float fAng  = ia*7.0 + fTurb*3.4 + ten*sin(t*7.0)*0.4;
    float arcs  = pow(ridge(vec3(cos(ia)*4.0, sin(ia)*4.0,
                                 idist*7.0 - t*2.4*(1.0 + 0.8*clamp(uArousal,0.0,1.0)))), 11.0);
    float lick  = pow(abs(sin(fAng - idist*5.2 - t*1.9*(1.0 + 0.7*clamp(uArousal,0.0,1.0)))), 5.0)*0.55
                + arcs*1.5;
    float flick = 0.72 + 0.28*vnoise(vec3(ia*1.7, t*3.1, idist*2.0));
    float wreath = lick*flick
                 * smoothstep(0.055, 0.115, idist)        // clear of the pupil itself
                 * smoothstep(0.60, 0.12, idist)          // and spent close to the pupil
                 * (0.55 + 0.75*focus) * (0.45 + 0.55*lum) * (1.0 - 0.75*fatigue) * chord
                 * (0.16 + 0.84*stir);
    vec3 flameCol = mix(mix(hot, ember, 0.45*smoothstep(0.30, 0.05, idist)), magenta, irr*0.85);
    vec3 wreathCol = flameCol*wreath*1.10;

    // THOUGHT SPARKS: form near the core, travel outward, fade
    vec3 sparkCol = vec3(0.0);
    for (int k = 0; k < SPARKS; k++) {
      float seed = float(k)*13.7 + 1.3;
      float rnd  = hash13(vec3(seed, seed*1.7, seed*2.3));
      float cyc  = t*(0.05 + rnd*0.06) + rnd*7.0;
      float prog = fract(cyc);
      float gen  = floor(cyc);
      float ang  = hash13(vec3(seed, gen, seed + gen*0.37))*6.28318;
      vec2  spk  = nuc + vec2(cos(ang), sin(ang))*(0.12 + prog*0.72);
      float fade = smoothstep(0.0, 0.18, prog)*smoothstep(1.0, 0.55, prog);
      float sd   = length(sp - spk);
      sparkCol  += mix(hot*2.0, ember*2.5, 0.5)*exp(-sd*sd/0.0018)*fade;
    }
    sparkCol *= (0.10 + 0.90*stir)*(0.40 + 0.60*lum)*(1.0 - 0.90*fatigue);

    // THE APERTURE (non-human, by design - AMBITION.md section 2). Not a circle and not a cat slit:
    // a superellipse whose EXPONENT and ASPECT both ride the dilation, so dilation is a change of
    // SHAPE, not a scale factor. Constricted it is a narrow oblique lens with soft cusps; dilated it
    // blooms into a rounded-square bloom no Earth animal carries. The 0.24 rad tilt is fixed -
    // invented anatomy must keep its own rules, and a wandering tilt would read as noise. A slow
    // ripple breathes along the rim: living tissue, never a die-cut.
    // (The old screen-space parallax hack - pupC = nuc + n.xy*0.085 - is gone: the aperture lives on
    // the refracted plane now, so its displacement against the surface is real, not simulated.)
    float dilAmt = clamp(0.60*(1.0 - lum) + 0.35*clamp(uArousal,0.0,1.0) - 0.45*focus, 0.0, 1.0);
    float pupR   = 0.050*(1.0 + 1.10*dilAmt);
    float mexp   = mix(1.30, 3.40, dilAmt);      // lens-with-cusps -> rounded square
    float ax     = mix(0.46, 1.00, dilAmt);      // narrow when constricted
    vec2  q      = rot2(0.24)*rel;
    float thp    = atan(q.y, q.x + 1e-6);
    float rippL  = vnoise(vec3(cos(thp)*4.0, sin(thp)*4.0, t*0.22)) - 0.5;
    float Rr     = pupR*(1.0 + 0.045*rippL);
    vec2  qq     = vec2(q.x/(Rr*ax), q.y/Rr);
    float fAp    = pow(pow(abs(qq.x), mexp) + pow(abs(qq.y), mexp), 1.0/mexp) - 1.0;
    float pupil  = smoothstep(0.14, -0.10, fAp);
    float iShade = smoothstep(1.40, 0.06, fAp);   // iris folding into the aperture
    // THE CATCHLIGHT BELONGS TO THE SURFACE, NOT THE PUPIL. It was glued at a fixed offset from the
    // aperture, so it travelled with the gaze and never moved with the light - which is exactly why
    // the eye looked indifferent to being lit. A corneal reflection is a mirror image of the light
    // source ON the sphere: it stays where the geometry puts it while the pupil roams beneath it.
    float corneal = pow(max(dot(reflect(rd, n), L), 0.0), 110.0);      // hard, tiny, fixed by the light
    float sheen   = pow(max(dot(reflect(rd, n), L), 0.0), 34.0);       // its falloff, tight
    // The aperture is not a void either: wet tissue picks up a little of whatever is lighting it,
    // and more of it on the lit side of the sphere.
    float pupSheen = sheen*0.20 + 0.05*clamp(ndl, 0.0, 1.0);

    // composite the interior
    float fatigueDim = mix(1.0, 0.40, fatigue);
    col = bodyCol*fatigueDim
        + wreathCol*fatigueDim
        + (irisCol + layerCol)*(0.30 + 0.70*lum)*fatigueDim
        + nucCol*fatigueDim
        + sparkCol;
    col *= 1.0 - 0.45*iShade;                            // the iris darkens as it folds inward
    col *= 1.0 - 0.994*pupil;                            // and the aperture swallows the light
    // Inside the aperture it is not uniformly black: there is a faint gradient (darkest dead centre,
    // where you are looking furthest in) and a thin bright edge where the iris rim catches light.
    float pupInner = pupil*smoothstep(-0.95, -0.05, fAp);
    float pupEdge  = exp(-pow((fAp - 0.02)/0.11, 2.0));
    // TAPETUM. Eyeshine: a reflective layer deep behind the aperture, the way a cat's eye flares in
    // headlights. It only lights when the geometry faces you (pow(face)) and mostly when it is
    // actually looking at you - the single most animal, least human thing an eye can do.
    float tape = pupil*pow(face, 5.0)*(0.30 + 0.55*lum)*(0.55 + 0.45*puls2)*(0.35 + 0.65*gz);
    col += hot*pupil*pupSheen*0.45*(0.35 + 0.65*lum);    // ...but wet tissue still catches the light
    col += hot*pupInner*0.028*(0.3 + 0.7*lum);           // the gradient inside the aperture
    col += mix(hot, vec3(0.95,0.97,1.00), 0.4)*pupEdge*0.30*(0.35 + 0.65*lum)*(0.4 + 0.6*diff);
    col += vec3(0.42,0.72,1.00)*tape*0.22;               // the eyeshine itself
    // Anisotropic stroma sheen: fibrous tissue stretches its highlight along the fibre direction,
    // so the sheen runs where the radial fibres align with the light instead of pooling in a disc.
    float anis = pow(abs(dot(normalize(rel + 1e-5), normalize(L.xy))), 3.0);
    col += hot*sheen*anis*0.14*chord;
    col += vec3(0.92,0.96,1.00)*corneal*(1.25 + 0.9*lum)*(0.35 + 0.65*diff)   // the corneal glint
         + vec3(0.70,0.82,1.00)*sheen*0.085*(0.3 + 0.7*lum)*diff;             // and its sheen
    col *= 1.0 + near*0.18;              // leaning in
    alpha = clamp(chord*1.8, 0.0, 1.0);  // the body's own coverage (docked transparency)
    // ==================== end interior ====================
#else
    // ==================== INTERIOR (voice-agent orb) ====================
    // No iris, no pupil: a formless luminous plasma suspended in the crystal ball. Slow
    // domain-warped flow gives the liquid-light swirl of a voice avatar; a soft heart breathes
    // and throws concentric rings when it hears sound. The same nine mood scalars drive palette,
    // tempo, veining and brightness - only the body is formless, and it is calm at rest.

    // It does not track the cursor at all: this body is self-contained, a light living in the
    // ball on its own terms. (The presence/dock choreography still applies - it just never gazes.)
    vec2  sw  = sp;
    float r   = length(sw);
    // The orb ALWAYS flows, even at rest: a voice avatar idles by breathing, it never freezes.
    // This is its own clock with a healthy floor, decoupled from the mood `speed` that nearly
    // stops the eye at rest. Arousal, irritation and tension only make it flow FASTER, never stop.
    float orbT = iTime*(0.45 + 1.10*clamp(uArousal,0.0,1.0) + 0.60*irr + 0.35*ten) + gChurn*iTime*0.30;
    float aud  = clamp(uAudio.x*1.10 + uAudio.z*0.55 + uBeat*0.45, 0.0, 1.3);

    // DOMAIN-WARPED FLOW: fbm warped by fbm folds the plasma over itself instead of scrolling.
    // Both the warp field and the flow field advance on orbT, so the whole body is in gentle,
    // continuous motion at rest; `stir` widens the warp so a roused mind boils rather than drifts.
    vec3  wq   = vec3(sw*2.3, orbT*0.60);
    vec2  warp = vec2(vnoise(wq), vnoise(wq*2.0 + 17.0))*(0.45 + 0.65*stir);
    vec3  fq   = vec3(sw*2.6 + warp, orbT*0.80);
    // Five octaves, the top two only resolving under the 200% supersample - fine filigree that
    // survives zoom instead of dissolving into a soft gradient. Contrast is pushed so structure
    // reads crisply rather than as haze.
    float flow = 0.46*vnoise(fq)
               + 0.24*vnoise(fq*2.1 + 3.0)
               + 0.15*vnoise(fq*4.3 + 7.0)
               + 0.09*vnoise(fq*8.9 + 13.0)
               + 0.05*vnoise(fq*17.3 + 23.0);
    flow = clamp((flow - 0.5)*1.28 + 0.5 + 0.09*aud, 0.0, 1.0);   // crisper, higher-contrast body

    // ---- CRISP STRUCTURE: what makes it read HD instead of fuzzy ----
    // Smooth fbm is a haze by nature - on its own it can only ever blur, and no supersampling
    // sharpens an image that has no hard edges in it. What the eye reads as resolution is EDGES,
    // so the detail here is built from RIDGED noise (thin creases with darkness either side),
    // domain-warped and stacked across octaves into a formless caustic WEB: the sharp
    // light-network you see inside a crystal, with no iris pattern to it. Tension sharpens it.
    float wS   = 3.5 + 4.0*ten;                                        // crease sharpness
    float web1 = pow(ridge(vec3(sw*4.2  + warp,     orbT*0.55)),        wS);
    float web2 = pow(ridge(vec3(sw*8.8  + warp*1.3, orbT*0.75 + 3.0)),  wS*1.15);
    float web3 = pow(ridge(vec3(sw*17.5 - warp*0.7, orbT*0.45 + 9.0)),  wS*1.35);
    float web4 = pow(ridge(vec3(sw*33.0 + warp*0.5, orbT*0.95 + 17.0)), wS*1.75);   // 4K octave
    float web  = web1*0.55 + web2*0.85 + web3*0.72 + web4*0.48;
    // fine caustic cells: a ridge driven by the web gives sharp cellular boundaries - crystal.
    float cau  = pow(ridge(vec3(sw*11.0 + web*0.35, orbT*0.50 + 21.0)), 8.0);
    // twinkling micro-glints: hard hash-thresholded points that pop in and out - tiny specular
    // hits, the crispest possible detail and nearly free. They ride the plasma, so they drift.
    vec2  gcell = floor(sw*46.0 + warp);
    float gh    = hash13(vec3(gcell, floor(orbT*1.3)));
    float twink = smoothstep(0.88, 0.995, gh)
                * pow(0.5 + 0.5*sin(orbT*6.0 + gh*40.0), 10.0);

    // COLOUR is allowed to be soft (a gradient through the blue family); STRUCTURE is all edges.
    vec3 orbCol = mix(navy, blue, smoothstep(0.12, 0.48, flow));
    orbCol = mix(orbCol, azure, smoothstep(0.42, 0.74, flow));
    orbCol = mix(orbCol, sky,   smoothstep(0.68, 0.96, flow));
    orbCol = mix(orbCol, base, 0.30);
    vec3 webCol = mix(mix(azure, sky, 0.5), vec3(0.93,0.97,1.00), 0.35);
    webCol = mix(webCol, mix(hot, ember, WARMTH), 0.20);

    // the luminous heart: a soft core that breathes on the clock and swells when it hears sound.
    float coreR = 0.30*(1.0 + 0.20*aud + 0.09*sin(iTime*0.9) + 0.35*gSwell);
    float core  = exp(-r*r/(coreR*coreR));
    vec3  heart = mix(vec3(0.86,0.93,1.00), ember, WARMTH*(0.55 + 0.20*sin(iTime*0.7)));

    // sound rings: concentric waves that travel outward while it listens or speaks. On iTime, so
    // they always travel at a readable pace even when the mood is calm.
    float ringP = pow(0.5 + 0.5*sin(r*22.0 - iTime*2.4 - uBeat*3.0), 6.0);
    float rings = ringP*aud*smoothstep(0.95, 0.15, r)*chord;

    // Composite: a DIM soft underglow for the body, the crisp web dominant on top, then the sharp
    // caustic cells, the heart, the rings and the hard glints. Weighting the edged web over the
    // smooth haze - not adding more noise - is the whole fix for "fuzzy".
    col  = orbCol*(0.10 + 0.34*flow)*(0.25 + 0.60*lum)*chord;       // dim soft underglow only
    col += webCol*web*(0.55 + 0.55*lum)*chord;                      // the crisp web (dominant)
    col += vec3(0.86,0.93,1.00)*cau*(0.28 + 0.48*lum)*chord*0.7;    // sharp caustic cells
    col += heart*core*(1.05 + 2.0*lum)*(0.55 + 0.65*aud);          // the heart
    col += mix(sky, heart, 0.5)*rings*0.55;                         // the rings
    col += vec3(0.95,0.98,1.00)*twink*(0.6 + 0.8*lum)*chord;       // hard twinkles
    col  = mix(col, magenta*(0.40 + 0.8*web)*chord, irr*0.6);       // irritation

    // thought sparks still rise slowly from the heart - activity without a face. Gated behind
    // `stir`, so at rest there are almost none.
    for (int k = 0; k < SPARKS; k++) {
      float seed = float(k)*13.7 + 1.3;
      float rnd  = hash13(vec3(seed, seed*1.7, seed*2.3));
      float cyc  = iTime*(0.05 + rnd*0.05) + rnd*7.0;
      float prog = fract(cyc);
      float ang  = hash13(vec3(seed, floor(cyc), seed + 0.37))*6.28318;
      vec2  spk  = vec2(cos(ang), sin(ang))*(0.05 + prog*0.80);
      float sd   = length(sw - spk);
      col += mix(hot*2.0, ember*2.5, 0.5)*exp(-sd*sd/0.0016)
           * smoothstep(0.0,0.18,prog)*smoothstep(1.0,0.5,prog)
           * (0.08 + 0.72*stir)*(0.4 + 0.6*lum)*(1.0 - 0.9*fatigue);
    }

    col *= mix(1.0, 0.42, fatigue);   // fatigue dims the whole body
    alpha = clamp(chord*1.8, 0.0, 1.0);
    // ==================== end interior (orb) ====================
#endif

    // shade by the surface lighting -> a ball, not a sticker
    col *= (0.70 + 0.50*diff)*mix(1.0, limb, 0.30);

    // a modest deep core light
    col += hot*exp(-dScreen*dScreen/(scale*scale*0.16))*(0.03 + 0.11*lum)*(1.0 - 0.5*fatigue)*diff;

    // glass rim: fresnel + tight glints only (anti-pattern 3)
    // Chromatic dispersion at the limb: glass splits light at a grazing angle, so the very edge of
    // the sphere is fractionally bluer than the body. A tiny effect, and one of those the eye reads
    // as "real material" without ever being able to name it.
    float disp  = pow(1.0 - face, 7.0);
    col += vec3(-0.25, 0.05, 0.55)*disp*0.16*(0.4 + 0.6*lum);
    float fres  = pow(1.0 - face, 3.2);
    float spec  = pow(max(dot(reflect(rd, nb), L), 0.0), 34.0*uGene[5].x);
    float glint = pow(max(dot(reflect(rd, nb), L), 0.0), 140.0);
    col += base*fres*(0.03 + 0.07*lum + 0.05*soc)*(0.30 + 0.70*diff)*uGene[5].w;   // limb, not an outline; gene: fresnelGain
    col += vec3(0.80,0.85,1.00)*spec*(0.10 + 0.18*lum)*(1.0 - 0.5*fatigue)*uGene[5].z;   // gene: specGain
    col += vec3(0.92,0.94,1.00)*glint*(0.5 + 0.8*lum)*(1.0 - 0.6*fatigue);
    alpha = max(alpha, fres*0.5);
  }

  col *= (1.0 - 0.42*fatigue);
  col *= (1.0 + gBright);
  col *= mix(1.12, 1.0, pres);   // docked it burns only slightly brighter: 1.55 blew it to white

  // --- corona OUTSIDE the rim only; a tight soft halo, social widens it ---
  float haloK = (34.0 - 16.0*soc)*uGene[5].y;                  // gene: haloReach
  float outside = smoothstep(scale*0.985, scale*1.010, dScreen);
  float halo = exp(-max(dScreen - scale, 0.0)*haloK/max(scale,0.02))*outside;
  halo *= smoothstep(scale*1.75, scale*1.02, dScreen);
  vec3 outCol = col + base*halo*(0.22 + 0.45*lum)*(1.0 - 0.4*fatigue)*(1.0 + near*0.3)*uGene[6].z;   // gene: haloGain

  // --- FLAME OFF THE RIM, INTO THE VOID ---
  // Actual particles, not a modulated glow: embers are born ON the silhouette at a random angle,
  // drift outward, swell and fade. Angular noise alone gave fat radial bars - discrete sprites are
  // what read as fire coming off the edge. Bounded to a thin annulus, so it costs nothing for the
  // vast majority of the screen, and short-lived so it never becomes a halo.
  float dOut = dScreen - scale;
  if (dOut > 0.0 && dOut < scale*0.66) {
    vec3 fire = vec3(0.0);
    // EPISODIC. The full discharge running permanently was too much - it is a display, not a state.
    // At rest there is only a faint shimmer; every so often (roughly a third of nine-second epochs,
    // on a hash) it flares for a couple of seconds and dies away. Strong emotion overrides the
    // clock: irritation, tension or high arousal keep it lit, because then it IS a state. Epochs run
    // on wall-clock iTime, not mood-scaled t, so a calm mind does not stretch the calendar.
    float ep    = floor(iTime/9.0);
    float epF   = fract(iTime/9.0);
    float burst = smoothstep(0.60, 0.95, hash13(vec3(ep, 4.2, 9.7)))
                * smoothstep(0.00, 0.06, epF)*smoothstep(0.30, 0.16, epF);
    float agit  = clamp(0.9*irr + 0.7*ten + 0.6*clamp(uArousal,0.0,1.0) - 0.35, 0.0, 1.0);
    float dischg = (0.045 + 0.955*max(burst*(0.30 + 0.70*stir), agit*0.85))
                 + clamp(gBright, 0.0, 1.0)*0.5;
    float heat = (0.40 + 0.90*clamp(uArousal,0.0,1.0))*dischg
               * (1.0 - 0.75*fatigue) * (0.5 + 0.7*lum) * (1.0 + 0.7*focus);
    if (dOut < scale*0.36)                       // embers stay close; bolts reach further
    for (int k = 0; k < EMBERS; k++) {
      float sd  = float(k)*7.31 + 2.17;
      float cyc = t*(0.42 + hash13(vec3(sd, 1.3, 2.7))*0.55) + hash13(vec3(sd, 3.9, 4.1))*11.0;
      float pr  = fract(cyc), gen = floor(cyc);
      float ang = hash13(vec3(sd, gen, 5.3))*6.28318;
      float wob = (hash13(vec3(sd, gen, 8.1)) - 0.5)*0.5*pr;      // it curls as it rises
      vec2  pos = centre + vec2(cos(ang + wob), sin(ang + wob))*scale*(1.0 + pr*0.30);
      vec2  dp  = uv - pos;
      float sz  = scale*scale*(0.00035 + 0.0022*pr*pr);           // swells as it cools
      fire += exp(-dot(dp, dp)/sz)*(1.0 - pr)*(1.0 - pr);
    }
    // ARCS. Smooth angular tongues came out looking like an aurora - soft sheets, no violence. These
    // are ridged noise instead, so each filament is a thin bright crease with darkness either side,
    // scrolling outward fast. Two octaves: a fat body arc and a fine crackle over it.
    vec2  relO = uv - centre;
    float oa   = atan(relO.y, relO.x + 1e-6);
    float rn   = dOut/max(scale, 1e-4);                 // 0 at the rim, 1 a radius out
    float boltT = t*2.2*(1.0 + 0.8*clamp(uArousal,0.0,1.0));
    // A bolt is thin in ANGLE and long along the RADIUS. Sampling the ridge with a strong radial
    // term made it vary in both directions, which draws closed contours - cracked mud, not lightning.
    // So the ridge is driven almost entirely by angle, with just enough radial drift to keep it from
    // being a perfect ray, plus a kink that grows with distance so the bolt forks away as it travels.
    float kink = (vnoise(vec3(cos(oa)*3.0, sin(oa)*3.0, rn*3.5 + boltT*0.5)) - 0.5)*0.55*rn;
    float ka   = oa + kink;
    float a1 = pow(ridge(vec3(cos(ka)*5.0,  sin(ka)*5.0,  boltT*0.55 + rn*0.55)),       12.0);
    float a2 = pow(ridge(vec3(cos(ka)*13.0, sin(ka)*13.0, boltT*0.95 + rn*1.10 + 7.0)), 20.0);
    // Lightning is intermittent. Each angular sector strikes on its own clock, so bolts flash into
    // existence and are gone - a continuously-lit filament is a wire, not a discharge.
    // Discrete angular sectors left visible straight-edged wedges around the rim - a fan, not a
    // discharge. The mask is smooth in ANGLE (so there are no seams) and discrete in TIME (so it
    // still flashes): a noise field that is re-rolled every strike, not a set of pie slices.
    float strikeGen = floor(boltT*0.9);
    float strike = smoothstep(0.30, 0.80,
        vnoise(vec3(cos(oa)*2.2, sin(oa)*2.2, strikeGen*4.7)));
    float bolt = (a1*0.85 + a2*1.35)*mix(0.10, 1.0, strike)*exp(-rn*3.6);
    // Per-angle length noise on top, so the reach is ragged rather than an even fringe.
    float ampN = 0.30 + 1.20*vnoise(vec3(cos(oa)*5.0, sin(oa)*5.0, t*0.42));
    bolt *= mix(0.45, 1.35, ampN*0.6);
    float lick = clamp(fire.x, 0.0, 1.6)*1.05 + bolt*1.6*dischg;
    // The annulus this is computed in has to end somewhere; fade to nothing BEFORE that edge, or the
    // cutoff draws a faint circle in the void.
    lick *= smoothstep(0.66, 0.44, rn);   // fade out well before the annulus edge
    lick *= heat;
    // A discharge has a near-white core and a coloured sheath; without the white core it reads as
    // paint rather than as something too bright to look at.
    vec3 lickCol = mix(mix(hot, base, 0.30), magenta, irr*0.9);
    outCol += lickCol*lick*0.85 + vec3(0.85,0.92,1.00)*pow(clamp(lick,0.0,2.0), 2.2)*0.30;
    halo    = clamp(halo + lick*0.6, 0.0, 1.0);   // so it carries alpha over the desktop too
  }

  // --- composite over the void (unchanged wallpaper furniture) ---
  outCol = aces(outCol);
  outCol = pow(outCol, vec3(0.4545));
  vec3 bg = vec3(0.0196, 0.0196, 0.0235)*smoothstep(0.45, 1.0, pres)*(1.0 - step(0.5, uFill));
  outCol = bg + (1.0 - bg)*outCol;
  outCol *= 1.0 - 0.30*smoothstep(0.35, 1.15, length(uv))*mix(0.25, 1.0, pres)*(1.0 - step(0.5, uFill));

  // (The inset frame and lit rim line that used to be drawn around the screen edge are gone: they
  // were furniture, and they read as a blue border on the desktop.)

  float g = hash13(vec3(gl_FragCoord.xy, fract(iTime)*91.0));
  outCol += (g - 0.5)*0.010*smoothstep(0.45, 1.0, pres);
  outCol += (hash13(vec3(gl_FragCoord.xy, 0.37)) - 0.5)/255.0*smoothstep(0.45, 1.0, pres);

  // premultiplied alpha; porthole containment gate (unchanged)
  float cover = clamp(alpha + halo*0.9, 0.0, 1.0);
  float a = mix(cover, 1.0, smoothstep(0.45, 1.0, pres));
  float reach = length(centre - uCentreDock) + scale;
  if (uFill > 0.5) {
    float contained = mix(1.0 - smoothstep(uFitScale*0.70, uFitScale, reach), 1.0,
                          step(0.5, uPortWide));
    a = cover*contained;
  }
  outCol = clamp(outCol, 0.0, 1.0);
  fragColor = vec4(outCol*a, a);
#endif
}
