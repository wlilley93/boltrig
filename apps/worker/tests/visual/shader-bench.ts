// The bodies on sliders, at sixty frames a second.
//
// AFTER THE VOICE MIXER, deliberately. `me-lora/tools/voice-mixer/mixer.html`
// settled Colossus by ear: four channels, every parameter live, and a **Copy
// settings** button whose JSON the running service consumes VERBATIM — because a
// transcription step between the thing that was heard and the thing that runs is
// where "why does it sound different now" comes from. This is the same
// arrangement for the eye. What was tuned here was tuned while looking at it,
// and the numbers it exports are the literal contents of `canvas/bodyTuning.ts`.
//
// IT DRIVES THE REAL RENDERERS. Not a copy of the pass sequence, not shaders
// lifted out with a regex — `JarvisNeuralRenderer` and `UltronRenderer`
// themselves, through the `setTuning` seam. A bench that rebuilt the passes would
// drift from them, and then it would be tuning something nobody ships.
//
// THE MEASUREMENT SITS BESIDE THE PICTURE, which is the other thing the mixer
// got right. `white` is the fraction of the middle of the frame with every
// channel above 0.92 — the centre-burning-white defect that cost three tuning
// rounds before anybody measured it. Watching it while dragging a gain is the
// difference between "that looks brighter" and "that is clipping".
//
// WHY THE rAF LOOP IS OURS. Each renderer starts its own on mount, and
// `readPixels` in a later task reads a drawing buffer the compositor has already
// consumed and cleared — it returns an empty frame while the canvas plainly is
// not. So rAF is stubbed before mount and this file steps each frame and reads
// the pixels in the same task. Reproducible, not flaky; measured on the beelink.

import {
  FAMILIAR_TUNING,
  JARVIS_TUNING,
  ULTRON_TUNING,
  type FamiliarTuning,
  type JarvisTuning,
  type UltronTuning,
} from "../../src/components/canvas/bodyTuning";
import { BODY_MODES, type BodyMode } from "../../src/components/canvas/bodyModes";
import {
  PHENOTYPE_SCALARS,
  RESTING_PHENOTYPE,
  type BodyPhenotype,
} from "../../src/components/canvas/bodyEmotion";
import {
  FAMILIAR_ARRIVAL,
  JARVIS_ARRIVAL,
  ULTRON_ARRIVAL,
  familiarModeTuning,
  jarvisModeTuning,
  ultronModeTuning,
} from "../../src/components/canvas/bodyPresets";
import { FamiliarWebGLRenderer } from "../../src/components/familiar/FamiliarWebGLRenderer";
import { FAMILIAR_MODES } from "../../src/components/familiar/FamiliarState";
import { JarvisNeuralRenderer } from "../../src/components/jarvis/v2/JarvisNeuralRenderer";
import { UltronRenderer } from "../../src/components/ultron/UltronRenderer";

type Tuning = FamiliarTuning | JarvisTuning | UltronTuning;
type Mode = "standby" | "listening" | "thinking" | "working" | "speaking" | "error";

/**
 * WHICH BODIES THIS BENCH DRIVES.
 *
 * The Familiar joined last and she is a different KIND of body, which is worth
 * stating because it decides what her sliders are. Jarvis and Ultron are drawn
 * by passes this repository owns, so their tuning describes brightness, radius
 * and pace. She is one vendored 2,000-line shader that must not be edited here
 * -- it flows from boltrig-familiar, never the reverse -- so there is nothing of
 * that kind to turn. What IS hers is the HOST recipe: how a voice becomes
 * movement, how the inner life wanders, what each mode does to her. Those were
 * literals in a frame loop until they became canvas/familiarTuning, and this is
 * the place they were made for.
 *
 * Her `error` mode is hers alone. Adding it to the shared BodyMode would have
 * forced an entry into the other two preset tables, and an empty entry there is
 * a state the enum claims and the body does not honour.
 */
type Body = "familiar" | "jarvis" | "ultron";
const FAMILIAR_ONLY_MODES = new Set<string>(["error"]);

/**
 * WHAT EACH SLIDER IN A ROW ACTUALLY IS.
 *
 * Every pair used to be legended `base / xenergy`, which is true of a ramp and a
 * LIE about the rest. `linkBow` is amount/speed and `ringSpin` is spin/precession
 * -- so the speed dials this bench grew were sitting there labelled as energy
 * dials, and the complaint "I still do not see a speed control" was correct about
 * the label and wrong only about the code. The names here mirror the tuple labels
 * in bodyTuning.ts; if a field is missing it falls back to the ramp legend, which
 * is the common case.
 */
const LEGEND: Record<string, readonly string[]> = {
  // ---- The baked layer's effects rack ------------------------------------
  latticeBlur: ["amount"],
  latticeSat: ["level"],
  latticeGlow: ["amount"],
  latticeSpeed: ["×realtime"],
  // ---- Jarvis: the wheels -------------------------------------------------
  ringGain: ["brightness", "×voice"],
  ringSpin: ["spin SPEED", "precess SPEED"],
  ringRadius: ["innermost wheel", "outermost wheel"],
  ringBeam: ["radial spread"],
  ringLife: ["come-and-go SPEED"],
  ringArc: ["beams per wheel", "arc length"],
  ringWidth: ["beam thickness"],
  rings: ["how many wheels"],
  // ---- Jarvis: the iris ---------------------------------------------------
  irisGain: ["iris brightness", "×voice"],
  irisRadius: ["pupil edge", "iris edge"],
  irisFil: ["fraction lit", "filament width"],
  irisFlow: ["outward flow SPEED", "flow contrast"],
  // ---- Jarvis: the glyph layers -------------------------------------------
  glyphGain: ["glyph brightness", "×voice"],
  glyphRadius: ["innermost layer", "outermost layer"],
  glyphSize: ["mark height", "mark width"],
  glyphSpin: ["rotation SPEED", "layer counter-spin"],
  glyphDensity: ["fraction lit", "brightness variance"],
  glyphBGain: ["sigil brightness", "×voice"],
  glyphBRadius: ["innermost layer", "outermost layer"],
  glyphBSize: ["mark height", "mark width"],
  glyphBSpin: ["rotation SPEED", "layer counter-spin"],
  glyphBDensity: ["fraction lit", "brightness variance"],
  // ---- Jarvis: the field --------------------------------------------------
  outerShell: ["radius", "population", "brightness"],
  swirl: ["flow SPEED", "×voice"],
  drawGain: ["particle brightness", "×voice"],
  streak: ["particle trail length", "×voice"],
  drawLimb: ["face-on keep", "rim boost"],
  // ---- Jarvis: the outer particle layer -----------------------------------
  outerGain: ["shell brightness", "×voice"],
  outerStreak: ["shell trail length", "×voice"],
  outerLimb: ["face-on keep", "rim boost"],
  outerPace: ["drift vs the inner layer"],
  // ---- Jarvis: the pathways ----------------------------------------------
  linkGain: ["pathway brightness", "×voice"],
  linkBow: ["bow amount", "bow SPEED"],
  linkRange: ["max pathway length"],
  linkLimb: ["face-on keep", "rim boost"],
  // ---- Jarvis: the circuitry ---------------------------------------------
  shardGain: ["shard brightness", "×voice"],
  shardSize: ["shard size"],
  shardStride: ["1 in N particles"],
  clump: ["strength", "cluster scale"],
  lattice: ["gain", "×voice"],
  presence: ["scale"],
  focus: ["far swell", "far dim"],
  // ---- The eye ------------------------------------------------------------
  core: ["heart brightness", "×voice"],
  eye: ["pupil", "iris aura", "lens ring radius", "aura width"],
  reverb: ["front SPEED", "echo spacing", "decay", "reflect radius"],
  starburst: ["horizontal flare"],
  // ---- Ultron: the neurons ------------------------------------------------
  dendriteGain: ["pathway brightness", "×voice"],
  dendrite: ["root length", "fork angle", "taper", "wander"],
  dendriteTip: ["cluster size", "growth"],
  bead: ["signal marks", "resting glow"],
  signal: ["travel SPEED", "phase spread", "tail decay"],
  arc: ["hub distance", "sweep (rad)", "arc radius", "pull onto arc"],
  // ---- Ultron: the crystal ------------------------------------------------
  facetSpin: ["spin SPEED", "spread"],
  facetGain: ["facet brightness", "×voice"],
  facetSize: ["facet size"],
  facetLimb: ["face-on keep", "rim boost"],
  // ---- Ultron: the veins and cracks --------------------------------------
  veinGain: ["vein brightness", "×voice"],
  veinStreak: ["vein length", "×voice"],
  veinLimb: ["face-on keep", "rim boost"],
  crackGain: ["crack brightness", "×voice"],
  crackRange: ["max crack length"],
  crackLimb: ["face-on keep", "rim boost"],
  petal: ["bloom lobes"],
  cloud: ["how un-spherical", "shape churn SPEED"],
  // ---- The Familiar: her host recipe, not draw passes ---------------------
  voiceLevel: ["base", "\u00d7voice"],
  voiceLow: ["base", "\u00d7voice"],
  voiceMid: ["base", "\u00d7voice"],
  voiceHigh: ["base", "\u00d7voice"],
  voiceEnv: ["attack SECONDS", "release SECONDS"],
  voiceGate: ["silence floor", "knee width"],
  beat: ["impulse gain", "decay SECONDS"],
  listen: ["mic \u2192 body", "mic \u2192 attention"],
  gaze: ["looking away", "watching you"],
  arousalLift: ["while working", "while speaking"],
  idlePulse: ["depth", "rate Hz"],
  composition: ["her size", "porthole fit"],
  daylight: ["night floor", "midday span"],
  wander: ["ease SECONDS", "dwell SECONDS"],
  gesture: ["min gap SECONDS", "max gap SECONDS"],
  errorTone: ["tension", "light left"],
  ...Object.fromEntries(PHENOTYPE_SCALARS
    .map((k) => [`pheno.${k}`, ["0 = none, 1 = full"]])),
};

/**
 * Ranges for a SINGLE COMPONENT, where a field's halves are different kinds of
 * number. Keyed `field:index`, and it beats RANGE when present.
 *
 * `ringArc` is why this exists: beams per wheel and how much of the gap each fills
 * are not the same kind of number, and one shared entry gave coverage a step of 1
 * and a floor of 1 -- which silently closes every wheel back into a full hoop, the
 * exact look the arc gating exists to break, and unreachable from the panel.
 */
const RANGE_AT: Record<string, [number, number, number]> = {
  "clump:1": [0.4, 8, 0.05],
  "focus:0": [0, 2, 0.01],
  // Fractional on purpose: an integer dial jumped, and easing between modes
  // stepped through the counts in between instead of gliding.
  "ringArc:0": [0.25, 9, 0.05],
  "ringArc:1": [0.04, 1, 0.02],
  // The neurons are the point of this body, and a ceiling of 1 meant the
  // gain that makes them lead was not reachable from the panel at all.
  "dendriteGain:0": [0, 3, 0.05],
  "dendriteGain:1": [0, 2, 0.05],
  "eye:2": [0, 1.2, 0.01],
  // An EXPONENT, not a gain: 60 is tight and 8 is broad, so it needs a range of
  // its own or the slider tops out an order of magnitude below anything useful.
  "eye:3": [4, 90, 1],
  // Spacing and decay are seconds and per-second, not gains.
  "reverb:1": [0.04, 1.2, 0.02],
  "reverb:2": [0.1, 3, 0.02],
  "reverb:3": [0.4, 2.4, 0.02],
};

/** Slider ranges. A number with no entry gets 0..1, which is right for a gain. */
const RANGE: Record<string, [number, number, number]> = {
  linkRange: [0.02, 0.60, 0.005],
  crackRange: [0.02, 0.60, 0.005],
  shardSize: [0.002, 0.06, 0.001],
  facetSize: [0.002, 0.06, 0.001],
  shardStride: [1, 64, 1],
  clump: [0, 1, 0.005],
  lattice: [0, 2, 0.01],
  latticeBlur: [0, 1, 0.01],
  latticeSat: [0, 2, 0.01],
  latticeGlow: [0, 1, 0.01],
  latticeSpeed: [0.25, 4, 0.05],
  presence: [0.4, 1.8, 0.005],
  focus: [0, 1, 0.005],
  petal: [0, 1, 0.01],
  cloud: [0, 1.2, 0.02],
  // Down to a standstill, because the complaint was that it is far too fast and
  // the shipped value is 0.26 -- a slider starting at 0.2 could not answer it.
  swirl: [0, 1.2, 0.005],
  // amount / speed. The speed is deliberately its own dial: how much a pathway
  // wanders and how fast it wanders are different judgements.
  linkBow: [0, 0.4, 0.002],
  // The crests own pace, separate from the fields. It has to reach a crawl:
  // "orbiting slowly" is the whole brief, and the old baked rate was 0.16.
  ringSpin: [0, 0.4, 0.002],
  ringRadius: [0.1, 2.0, 0.01],
  ringBeam: [0.01, 0.3, 0.005],
  // 0 holds every crest lit, which is what the arrival state wants.
  ringLife: [0, 0.4, 0.005],
  ringWidth: [0.002, 0.18, 0.002],
  eye: [0, 2.2, 0.02],
  reverb: [0, 4, 0.05],
  irisRadius: [0.02, 1.2, 0.01],
  irisFil: [0, 1, 0.02],
  irisFlow: [0, 0.8, 0.005],
  // Negative is slower than the inner layer; -1 holds the shell still.
  outerPace: [-1, 1, 0.02],
  outerStreak: [0, 0.05, 0.0005],
  glyphRadius: [0.2, 2.0, 0.02],
  glyphSize: [0.002, 0.16, 0.002],
  glyphSpin: [0, 0.3, 0.002],
  glyphDensity: [0, 1, 0.02],
  rings: [1, 12, 1],
  // Up to about 1.6 rad/s was what swept the fracture slivers around like clock
  // hands, so this needs to go well below its old base of 0.4.
  facetSpin: [0, 1.0, 0.005],
  // radius / population / brightness. The population reaching 0 matters: that is
  // how a body says it does not want an outer sphere at all.
  outerShell: [0, 2.2, 0.01],
  // root length / fork angle / taper / wander. The fork angle is the one that
  // decides whether it reads as a nervous system or as a firework.
  dendrite: [0, 1.2, 0.01],
  dendriteTip: [0, 2.0, 0.02],
  bead: [1, 24, 0.5],
  signal: [0, 3, 0.02],
  arc: [0, 3.2, 0.02],
  starburst: [0, 1, 0.01],
  streak: [0, 0.4, 0.002],
  veinStreak: [0, 0.4, 0.002],
  // The limb pair wants headroom: the fix for "it reads as fur" was taking the
  // rim term past 1.0 while pulling the base down, so a 0..1 slider could not
  // have found it.
  drawLimb: [0, 3, 0.01],
  linkLimb: [0, 3, 0.01],
  veinLimb: [0, 3, 0.01],
  crackLimb: [0, 3, 0.01],
  facetLimb: [0, 3, 0.01],
  // ---- The Familiar -------------------------------------------------------
  // SECONDS, not gains. The attack has to reach a few milliseconds to find where
  // a syllable starts arriving late, and the release has to reach a second to
  // find where a held note stops decaying and starts smearing.
  voiceEnv: [0.005, 1.0, 0.005],
  // The gate lives entirely in the quiet end -- the whole point is that it never
  // touches a loud frame -- so a 0..1 slider would spend 90% of its travel doing
  // nothing at all.
  voiceGate: [0, 0.3, 0.005],
  // Impulse gain past 1 on purpose: uBeat is multiplied hard in five places, so
  // the interesting question is how much OVER unity a syllable can land.
  beat: [0, 2, 0.02],
  // Ratios of the voice drive, and the ceiling matters: the failure being tuned
  // away from is her mouthing your words back, which lives above about 0.5.
  listen: [0, 1, 0.01],
  // A body twice its porthole is a crop, not a composition; below a third of it
  // she is a dot. The shipped pair sits in the middle of both.
  composition: [0.1, 1.2, 0.01],
  // Depth is a fraction of full drive and rate is in Hz; both need to reach zero,
  // which is how a mode says "nothing moves her but her own inner life".
  idlePulse: [0, 1, 0.005],
  // Seconds, and long: a wander that turns over in under a second is a tremor.
  wander: [0.5, 60, 0.5],
  // Seconds between gestures. It has to reach a few seconds to be judged inside
  // one sentence, and two minutes to be judged as ambient.
  gesture: [2, 150, 1],
  daylight: [0, 1.2, 0.01],
  errorTone: [0, 1, 0.01],
  arousalLift: [0, 1, 0.01],
  gaze: [0, 1, 0.01],
};

const $ = <T extends HTMLElement>(id: string): T => document.getElementById(id) as T;

/**
 * An LFO bound to one slider, after the voice mixer's `ex.lfo`.
 *
 * That control settled Colossus, and the reason it worked is worth restating:
 * a value you can only set STILL is a value you judge from memory. Sweeping it
 * slowly between two bounds while you watch tells you where it stops being
 * right in one pass, and it tells you what the body looks like while the value
 * is moving -- which for a living thing is most of the time.
 *
 * min and max rather than centre and depth, because the useful question is "how
 * far either way is still acceptable", and that is two numbers you read off the
 * slider you were already dragging.
 */
interface Lfo {
  on: boolean;
  /** Hz. Slow: this is a body breathing, not a tremolo. */
  rate: number;
  min: number;
  max: number;
  /** Phase offset in turns, so two bound sliders need not move together. */
  phase: number;
}

/** Keyed `field:componentIndex`, since a pair has two independent sliders. */
type LfoMap = Record<string, Lfo>;
let lfos: LfoMap = {};
const lfoKey = (field: string, index: number): string => `${field}:${index}`;
/** The DOM the LFO has to move, so a swept value is visible and not just felt. */
const sliderDom: Record<string, { input: HTMLInputElement; out: HTMLElement }> = {};

/**
 * A tuning survives a reload, and can be handed to someone else as a link.
 *
 * NOT A CONVENIENCE. A look arrived at by dragging twelve sliders for twenty
 * minutes is real work, and losing it to a dev-server restart -- which is what
 * happened -- is the same class of loss as a voice pick that was never written
 * down. The mixer learned this too: its picks are saved.
 *
 * Merged OVER what ships rather than replacing it, so a state saved before a
 * field existed still loads: `swirl` was added after the first states were
 * saved, and a replace would have left it undefined and turned every arithmetic
 * result into NaN.
 */
const storageKey = (name: string): string => `boltrig.shaderBench.${name}`;

/** The newest saved version for a store key, or null. History loads async, so
 *  before the fetch lands this answers null and the caller falls through. */
function storeNewest(key: string): SavedVersion | null {
  const versions = history[key]?.versions ?? [];
  return versions.length > 0 ? versions[versions.length - 1] : null;
}

/**
 * Where a look comes from, in order: a link's URL, this browser's edits, the
 * store's newest saved version, the body's saved baseline, and only then the
 * shipped table. The store steps make "Save preset" the publishing act: what
 * was last locked in is what a fresh browser opens on, without a force-URL.
 */
function saved(name: string, shipped: Tuning): Tuning {
  const fromUrl = new URLSearchParams(location.search).get(name);
  const raw = fromUrl ?? localStorage.getItem(storageKey(name));
  if (raw) {
    try {
      return { ...clone(shipped), ...JSON.parse(raw) } as Tuning;
    } catch {
      return clone(shipped);
    }
  }
  const version = storeNewest(name);
  if (version?.tuning) return { ...clone(shipped), ...version.tuning } as Tuning;
  const which = name.slice(0, name.indexOf("."));
  const base = storeNewest(`${which}.baseline`);
  if (base?.tuning) return { ...clone(shipped), ...base.tuning } as Tuning;
  return clone(shipped);
}

function rememberLfos(): void {
  try {
    localStorage.setItem(storageKey(`${slotKey(body, slot)}.lfo`), JSON.stringify(lfos));
  } catch {
    // A full or blocked store is not a reason to stop rendering.
  }
}

function savedLfos(name: string): LfoMap {
  const fromUrl = new URLSearchParams(location.search).get(`${name}.lfo`);
  const raw = fromUrl ?? localStorage.getItem(storageKey(`${name}.lfo`));
  if (raw) {
    try {
      return JSON.parse(raw) as LfoMap;
    } catch {
      return {};
    }
  }
  // The oscillators travel with the look: same chain as saved().
  const version = storeNewest(name);
  if (version) return { ...(version.lfos ?? {}) };
  const which = name.slice(0, name.indexOf("."));
  const base = storeNewest(`${which}.baseline`);
  return { ...(base?.lfos ?? {}) };
}

/**
 * SPEECH REACH. Where each dial travels at full syllable, keyed like the LFOs
 * (`field:index`). The saved value is the END of the journey; the dial's own
 * setting is the start. Applied monitor-side on the voice envelope, so the
 * numbers underneath never move — the body pulses to the line being spoken
 * and settles back to exactly what was tuned.
 */
let speech: Record<string, number> = {};
/** Smoothed syllable envelope, 0..1 — fast up, slow down, like a VU needle. */
let speechEnv = 0;
let speechShown = 0;
let reachArming: { id: string; from: number } | null = null;

function rememberSpeech(): void {
  try {
    localStorage.setItem(storageKey(`${slotKey(body, slot)}.speech`), JSON.stringify(speech));
  } catch {
    // A full or blocked store is not a reason to stop rendering.
  }
}

function savedSpeech(name: string): Record<string, number> {
  const raw = localStorage.getItem(storageKey(`${name}.speech`));
  if (raw) {
    try {
      return JSON.parse(raw) as Record<string, number>;
    } catch {
      return {};
    }
  }
  // The reach travels with the look: same chain as saved() and savedLfos().
  const version = storeNewest(name) as { speech?: Record<string, number> } | undefined;
  if (version) return { ...(version.speech ?? {}) };
  const which = name.slice(0, name.indexOf("."));
  const base = storeNewest(`${which}.baseline`) as { speech?: Record<string, number> } | undefined;
  return { ...(base?.speech ?? {}) };
}

function remember(name: string, value: Tuning): void {
  try {
    localStorage.setItem(storageKey(name), JSON.stringify(value));
  } catch {
    // A full or blocked store is not a reason to stop rendering.
  }
}

/** A link that reproduces exactly what is on screen. */
function shareLink(): string {
  const url = new URL(location.href);
  url.search = "";
  url.searchParams.set(slotKey(body, slot), JSON.stringify(tuning));
  if (Object.keys(lfos).length > 0) {
    url.searchParams.set(`${slotKey(body, slot)}.lfo`, JSON.stringify(lfos));
  }
  url.searchParams.set("mode", slot);
  url.searchParams.set("level", ($("level") as HTMLInputElement).value);
  return url.toString();
}

/**
 * WHICH PRESET IS BEING EDITED.
 *
 * `arrival` is a slot like any other. It is where the body is drawn IN from, so
 * it has to be tunable by eye the same way the modes are -- and treating it as a
 * special case would have meant a second editing path for the one preset nobody
 * can check without watching it happen.
 */
type Slot = "arrival" | Mode;
const SLOTS: readonly Slot[] = ["arrival", ...BODY_MODES, "error"];
let slot: Slot = "standby";

/** The slots a body actually has. Only the Familiar answers for a failure. */
function slotsFor(which: Body): readonly Slot[] {
  return which === "familiar"
    ? ["arrival", ...FAMILIAR_MODES]
    : ["arrival", ...BODY_MODES];
}

/** The states the transport offers. `speaking` is deliberately absent: he only
 *  ever speaks FROM STANDBY — the player carries the voice, standby carries
 *  the body — so a speaking tab would be a second place to tune the same
 *  thing. The slot still exists, the app still renders it, and Apply to all
 *  states still writes it. */
function transportSlots(): readonly Slot[] {
  return slotsFor(body).filter((at) => at !== "speaking");
}

/** The shipped numbers for a body and slot, before any local edit. */
function shippedFor(which: Body, at: Slot): Tuning {
  if (at === "arrival") {
    if (which === "familiar") return FAMILIAR_ARRIVAL;
    return which === "jarvis" ? JARVIS_ARRIVAL : ULTRON_ARRIVAL;
  }
  if (which === "familiar") return familiarModeTuning(at);
  // The other two have no error preset, and must not be asked for one: standby
  // is the honest stand-in rather than an empty delta pretending to be a state.
  const shared = (FAMILIAR_ONLY_MODES.has(at) ? "standby" : at) as BodyMode;
  return which === "jarvis" ? jarvisModeTuning(shared) : ultronModeTuning(shared);
}

/**
 * The render mode for a slot.
 *
 * Arrival has no render mode of its own -- it is a starting position, not a state
 * the body sits in -- so it is shown against standby, which is the quietest
 * backdrop and therefore the one that hides the least.
 */
function renderMode(at: Slot): Mode {
  return at === "arrival" ? "standby" : at;
}

/** Storage and save key. Per body AND slot: six presets, six sets of numbers. */
const slotKey = (which: string, at: Slot): string => `${which}.${at}`;

let renderer: FamiliarWebGLRenderer | JarvisNeuralRenderer | UltronRenderer | null = null;
/** Whether the arrival has already been shown this page load. */
let introPlayed = false;
let tuning: Tuning = clone(JARVIS_TUNING);
let shipped: Tuning = JARVIS_TUNING;
let body: Body = "jarvis";
let raf = 0;
let frames = 0;

function clone<T extends Tuning>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

/**
 * REDUCED MOTION IS FORCED OFF for the Familiar here, and only here.
 *
 * She is the one body that honours the OS preference by dropping to one frame a
 * second with her inner life frozen -- correct in the app, and in a bench built
 * for watching motion it is indistinguishable from a hung renderer. Whoever is
 * tuning her has asked to see her move by opening this page.
 */
function newRenderer(): FamiliarWebGLRenderer | JarvisNeuralRenderer | UltronRenderer {
  if (body === "familiar") return new FamiliarWebGLRenderer({ reducedMotion: false });
  return body === "jarvis"
    ? new JarvisNeuralRenderer({ maxDevicePixelRatio: 1 })
    : new UltronRenderer({ maxDevicePixelRatio: 1 });
}

/** Rebuild the mode select for the body on stage, keeping the slot if it has
 *  one. Switching from the Familiar's `error` to a body without it must land
 *  somewhere real rather than leaving a select showing a slot nothing renders. */
function paintModes(): void {
  const bar = $("states");
  const available = transportSlots();
  if (!available.includes(slot)) slot = "standby";
  bar.innerHTML = "";
  for (const at of available) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.state = at;
    const name = document.createElement("span");
    name.textContent = at === "arrival" ? "arrival ↘" : at;
    button.appendChild(name);
    const badge = document.createElement("span");
    badge.className = "sbadge";
    button.appendChild(badge);
    button.classList.toggle("on", at === slot);
    button.addEventListener("click", () => setState(at));
    bar.appendChild(button);
  }
}

/** How far each state's SAVED look sits from the ground — the journey's
 *  spread, readable off the transport without visiting every state. */
function stateDrift(at: Slot): number {
  if (!baseline) return 0;
  const look = saved(slotKey(body, at), shippedFor(body, at)) as unknown as
    Record<string, number | number[]>;
  const ground = baseline.tuning as unknown as Record<string, number | number[]>;
  let count = 0;
  for (const [field, value] of Object.entries(look)) {
    if (HIDDEN_FIELDS.has(field)) continue;
    const was = ground[field];
    if (was === undefined) continue;
    const now = typeof value === "number" ? [value] : value;
    const ref = typeof was === "number" ? [was] : was;
    for (let index = 0; index < now.length; index += 1) {
      const a = now[index];
      const b = (ref as number[])[index];
      if (typeof a === "number" && typeof b === "number" && Math.abs(a - b) > 1e-6) count += 1;
    }
  }
  return count;
}

function paintStates(): void {
  for (const button of Array.from($("states").children) as HTMLElement[]) {
    const at = button.dataset.state as Slot;
    button.classList.toggle("on", at === slot);
    button.classList.toggle("legal",
      at !== slot && (history[`${body}.${slot}->${at}`]?.versions.length ?? 0) > 0);
    const badge = button.querySelector(".sbadge");
    if (badge) {
      const off = at === slot
        ? driftCount(Object.keys(tuning).filter((f) => !HIDDEN_FIELDS.has(f)))
        : stateDrift(at);
      badge.textContent = off > 0 ? `Δ${off}` : "";
    }
  }
}

/**
 * Stub rAF BEFORE mount, so the renderer's own loop never schedules.
 *
 * Restoring it is deliberately not offered: two loops driving one body would
 * double its frame rate and make every measurement here wrong by a factor this
 * page could not report.
 */
const realRaf = window.requestAnimationFrame.bind(window);
window.requestAnimationFrame = (() => 0) as typeof window.requestAnimationFrame;

function mount(): void {
  cancelLoop();
  renderer?.destroy();
  const host = $("stage");
  host.innerHTML = "";
  renderer = newRenderer();
  // SQUARE FOR THE FAMILIAR, full-bleed for the other two. Her canvas sizes
  // itself from its own width and draws square -- the shipped Stage is
  // `aspect-ratio: 1` everywhere -- so a full-bleed host stretches the drawing
  // buffer across a wide window and every judgement made about her shape is
  // made about a distortion the app never renders.
  $("stage").classList.toggle("square", body === "familiar");
  renderer.mount(host);
  // The baked layer's loop, mounted whenever a body that has one is on stage.
  // Free until the lattice dial gives it gain; silently absent if the file is
  // not there.
  if (body === "jarvis") {
    (renderer as JarvisNeuralRenderer).setLatticeVideo({
      standby: "/tests/visual/assets/jarvis-lattice.mp4",
      listening: "/tests/visual/assets/jarvis-lattice-listening.mp4",
      thinking: "/tests/visual/assets/jarvis-lattice-thinking.mp4",
      working: "/tests/visual/assets/jarvis-lattice-working.mp4",
      speaking: "/tests/visual/assets/jarvis-lattice-speaking.mp4",
    });
  } else if (body === "ultron") {
    (renderer as UltronRenderer).setLatticeVideo({
      standby: "/tests/visual/assets/ultron-membrane.mp4",
      listening: "/tests/visual/assets/ultron-membrane-listening.mp4",
      thinking: "/tests/visual/assets/ultron-membrane-thinking.mp4",
      working: "/tests/visual/assets/ultron-membrane-working.mp4",
      speaking: "/tests/visual/assets/ultron-membrane-speaking.mp4",
    });
  } else if (body === "familiar") {
    // One loop per state, standby as the understudy for any that is missing.
    (renderer as FamiliarWebGLRenderer).setLatticeVideo({
      standby: "/tests/visual/assets/familiar-orb.mp4",
      listening: "/tests/visual/assets/familiar-orb-listening.mp4",
      thinking: "/tests/visual/assets/familiar-orb-thinking.mp4",
      working: "/tests/visual/assets/familiar-orb-working.mp4",
      speaking: "/tests/visual/assets/familiar-orb-speaking.mp4",
      error: "/tests/visual/assets/familiar-orb-error.mp4",
    });
  }
  const status = renderer.status();
  if (status.state !== "running") {
    $("readout").textContent = `FAILED — ${status.reason ?? status.state}`;
    return;
  }
  paintModes();
  // The emotion chip is the mood's source of truth: a fixed pose for judging
  // the look, where the app's inner life drives these scalars continuously.
  pheno = { ...RESTING_PHENOTYPE, ...EMOTIONS[emotion] };
  renderer.applyPhenotype(pheno as unknown as Record<string, unknown>);
  // The export is per body, so a stale one is a wrong label on a set of numbers
  // — exactly the failure mode this whole session has been unpicking.
  $("export").textContent = "";
  const clips = $("clip") as HTMLSelectElement;
  clips.innerHTML = "";
  for (const src of clipsFor(body)) {
    const option = document.createElement("option");
    option.value = src;
    option.textContent = src.split("/").pop() ?? src;
    clips.appendChild(option);
  }
  void loadKeptClips();

  shipped = shippedFor(body, slot);
  tuning = saved(slotKey(body, slot), shipped);
  // Rebuilt per body: an LFO bound to `linkGain` means nothing on Ultron.
  for (const id of Object.keys(sliderDom)) delete sliderDom[id];
  lfos = savedLfos(slotKey(body, slot));
  speech = savedSpeech(slotKey(body, slot));
  reachArming = null;
  loadBaseline();
  loadVolumes();
  buildControls();
  buildMixer();
  paintHistory();
  paintDrift();
  push();
  // THE INTRO, on every mount. `push()` first so the renderer knows what it is
  // easing TOWARD -- the saved look if there is one, not the shipped preset -- and
  // then the draw-in runs from the arrival state to that. Skipping the push would
  // animate to the wrong destination and then jump when the first slider moved.
  // ONCE PER PAGE. mount() also runs on a change of body, and replaying the
  // arrival there was the same complaint one level down.
  if (!introPlayed) {
    renderer.intro();
    introPlayed = true;
  }
  loop();
}

/** The controls, generated FROM the struct so a new field cannot be forgotten. */
/**
 * THE EMOTION REGISTERS, driveable by hand.
 *
 * Ten scalars reach both bodies and until now none of them could be MOVED here --
 * the bench called applyPhenotype(null) at mount and that was the end of it. So the
 * whole emotional range was code you could read and not a look you could judge, and
 * the one thing a body's mood has to survive is somebody looking at it.
 *
 * They are wired to colouration as well as to gains: see emotionColour in
 * bodyEmotion, where irritation crushes green and blue toward blood, valence warms
 * or cools, arousal and tension harden the highlight, and fatigue desaturates. A
 * mood that could only make a body brighter was not really expression.
 */
let pheno: BodyPhenotype = { ...RESTING_PHENOTYPE };

/** What each register means, so the panel does not need the source open beside it. */
const PHENO_TITLES: Record<string, string> = {
  valence: "Valence — how good it feels",
  arousal: "Arousal — how activated it is",
  irritation: "Irritation — pushes the colour toward blood",
  fatigue: "Fatigue — dims AND desaturates",
  attention: "Attention — how far the structure reaches",
  social: "Social — turned toward you, brightens the rim",
  buoyancy: "Buoyancy — lifts the heart",
  luminosity: "Luminosity — overall brightness",
  tension: "Tension — whitens the highlight",
  attachment: "Attachment — a steady resting warmth",
};

function rememberPheno(): void {
  try {
    localStorage.setItem(storageKey("pheno"), JSON.stringify(pheno));
  } catch { /* a blocked store is not a reason to stop rendering */ }
}

/**
 * EMOTION IS A MODIFIER, NOT A STATE. The states are the animated base looks;
 * an emotion rides on top of whichever state is on stage, the way an
 * expression rides on a face. The chips set the phenotype wholesale — the
 * in-app inner life drives these same scalars continuously; here they are
 * fixed poses for judging a look under each one.
 */
const EMOTIONS: Record<string, Partial<BodyPhenotype>> = {
  neutral: {},
  calm: { valence: 0.35, attachment: 0.35, luminosity: 0.25 },
  joy: { valence: 0.9, buoyancy: 0.8, arousal: 0.55, luminosity: 0.6, social: 0.5 },
  warm: { valence: 0.6, attachment: 0.8, social: 0.7, buoyancy: 0.4, luminosity: 0.35 },
  alert: { attention: 0.9, arousal: 0.6, tension: 0.3, luminosity: 0.4 },
  worry: { tension: 0.65, attention: 0.7, arousal: 0.45, fatigue: 0.25, irritation: 0.25 },
  anger: { irritation: 0.9, arousal: 0.75, tension: 0.85, attention: 0.6, luminosity: 0.3 },
  tired: { fatigue: 0.85, luminosity: 0.12, attention: 0.15 },
};
let emotion = ((): string => {
  try {
    return localStorage.getItem(storageKey("emotion")) ?? "neutral";
  } catch {
    return "neutral";
  }
})();

function applyEmotion(name: string): void {
  emotion = name in EMOTIONS ? name : "neutral";
  pheno = { ...RESTING_PHENOTYPE, ...EMOTIONS[emotion] };
  rememberPheno();
  try {
    localStorage.setItem(storageKey("emotion"), emotion);
  } catch { /* fine */ }
  renderer?.applyPhenotype(pheno as unknown as Record<string, unknown>);
  paintEmotions();
}

function buildEmotions(): void {
  const chips = $("emotions");
  chips.innerHTML = "";
  for (const name of Object.keys(EMOTIONS)) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.dataset.emotion = name;
    chip.textContent = name;
    chip.addEventListener("click", () => applyEmotion(name));
    chips.appendChild(chip);
  }
  paintEmotions();
}

function paintEmotions(): void {
  for (const chip of Array.from($("emotions").children) as HTMLElement[]) {
    chip.classList.toggle("on", chip.dataset.emotion === emotion);
  }
}

function buildControls(): void {
  const panel = $("controls");
  panel.innerHTML = "";
  for (const id of Object.keys(sliderDom)) delete sliderDom[id];
  ensureChannel();
  const active = channelsFor().find((c) => c.title === channel);
  if (!active) return;

  const add = (key: string) => {
    const value = (tuning as unknown as Record<string, number | number[]>)[key];
    if (typeof value === "number") {
      panel.appendChild(row(key, key, [value], (next) => assign(key, next[0])));
    } else {
      panel.appendChild(row(key, key, value, (next) => assign(key, next)));
    }
  };

  // ONE CHANNEL AT A TIME, and NO HEADER: the selected desk strip already
  // names the channel, and a rotated title only made the bus taller. The
  // UNGROUPED warning still surfaces — on its desk strip.
  for (const key of active.fields) add(key);
  // Every rebuild wipes sliderDom; presence's topbar controls re-register so
  // its sweep keeps a slider to move.
  registerPresenceDom();
  paintPresenceCtl();
}

/**
 * WHICH DRAW EACH FIELD BELONGS TO, in the order the passes actually run.
 *
 * The panel was one flat run of twenty-odd rows in struct order -- the order a
 * TypeScript interface happens to be written in, which has nothing to do with what
 * you are looking at. Grouping by PASS puts the controls for the thing you are
 * staring at together, and numbering them makes the render order legible.
 */

const GROUPS: readonly { title: string; fields: readonly string[] }[] = [
  { title: "1 · Wheels — the orbiting beams", fields: [
    "rings", "ringArc", "ringWidth", "ringGain", "ringRadius", "ringBeam",
    "ringSpin", "ringLife",
  ] },
  { title: "2 · Glyphs — the inner inscriptions", fields: [
    "glyphGain", "glyphRadius", "glyphSize", "glyphSpin", "glyphDensity",
  ] },
  { title: "2 · Sigils — the outer inscriptions", fields: [
    "glyphBGain", "glyphBRadius", "glyphBSize", "glyphBSpin", "glyphBDensity",
  ] },
  { title: "3 · The iris — radial filaments", fields: [
    "irisGain", "irisRadius", "irisFil", "irisFlow",
  ] },
  { title: "3 · Dendrites — the neurons and their signals", fields: [
    "dendriteGain", "dendrite", "dendriteTip", "bead", "signal", "arc",
  ] },
  { title: "4 · Veins and cracks", fields: [
    "veinGain", "veinStreak", "veinLimb", "crackGain", "crackRange", "crackLimb",
  ] },
  { title: "4 · Inner particle layer — the core cloud", fields: [
    "drawGain", "streak", "swirl", "drawLimb",
  ] },
  { title: "4 · Outer particle layer — the distant shell", fields: [
    "outerShell", "outerGain", "outerStreak", "outerLimb", "outerPace",
  ] },
  { title: "5 · Circuit shards", fields: ["shardGain", "shardSize", "shardStride"] },
  { title: "5 · Debris — clumping and depth", fields: ["clump", "focus"] },
  { title: "0 · Lattice loop — the baked layer", fields: [
    "lattice", "latticeBlur", "latticeSat", "latticeGlow", "latticeSpeed",
  ] },
  { title: "5 · Crystal facets", fields: [
    "facetGain", "facetSize", "facetSpin", "facetLimb",
  ] },
  { title: "6 · The eye — core and composite", fields: [
    "core", "eye", "starburst", "petal", "cloud",
  ] },
  { title: "6 · Voice reverberation — how speech crosses the body", fields: [
    "reverb",
  ] },
  // ---- The Familiar. Ordered the way her frame runs, not the way the struct
  // is written: what the voice does, then what a mode does, then who she is.
  { title: "1 · Her voice — what speech does to the body", fields: [
    "voiceLevel", "voiceLow", "voiceMid", "voiceHigh",
  ] },
  { title: "2 · Her envelope — the shape of a syllable", fields: [
    "voiceEnv", "voiceGate", "beat",
  ] },
  { title: "3 · Her attention — being spoken to", fields: [
    "listen", "gaze", "arousalLift",
  ] },
  { title: "4 · Her inner life — alive between events", fields: [
    "idlePulse", "wander", "gesture",
  ] },
  { title: "5 · Her presence — size, light and failure", fields: [
    "composition", "daylight", "errorTone",
  ] },
];

/**
 * A plain-English name for each field, shown above its code name.
 *
 * The code name stays visible because it is what Copy settings prints and what the
 * source calls it -- but `crackRange` is not a description of anything, and a panel
 * you have to read the shader to use is a panel that gets used wrong.
 */
const TITLES: Record<string, string> = {
  rings: "How many wheels",
  ringArc: "Beams per wheel, and how long each is",
  ringWidth: "How thick a beam is",
  ringGain: "How bright the beams are",
  ringRadius: "Where the wheels sit",
  ringBeam: "How far a beam spreads radially",
  ringSpin: "How fast the wheels turn and tilt",
  ringLife: "How often beams fade in and out",
  irisGain: "How bright the iris is",
  irisRadius: "Where the iris starts and ends",
  irisFil: "How many filaments, and how fine",
  irisFlow: "How fast light travels outward",
  glyphGain: "How bright the inner inscriptions are",
  glyphRadius: "Where the inner pair of rings sits",
  glyphSize: "How big each inner mark is",
  glyphSpin: "How fast the inner pair turns",
  glyphDensity: "How many inner marks are lit, and how uneven",
  glyphBGain: "How bright the outer inscriptions are",
  glyphBRadius: "Where the outer pair of rings sits",
  glyphBSize: "How big each outer mark is",
  glyphBSpin: "How fast the outer pair turns",
  glyphBDensity: "How many outer marks are lit, and how uneven",
  linkGain: "How bright the pathways are",
  linkBow: "How much a pathway wanders, and how fast",
  linkRange: "Longest pathway",
  linkLimb: "How much the pathways favour the rim",
  dendriteGain: "How bright the neurons are",
  dendrite: "The shape of a neuron",
  dendriteTip: "The clusters at the ends",
  bead: "How many signal marks, and the resting glow",
  signal: "How the electrical signals travel",
  arc: "The four terminal arcs",
  veinGain: "How bright the veins are",
  veinStreak: "How long the veins are",
  veinLimb: "How much the veins favour the rim",
  crackGain: "How bright the fracture lines are",
  crackRange: "Longest fracture line",
  crackLimb: "How much the fractures favour the rim",
  drawGain: "How bright the particles are",
  streak: "How long a particle's trail is",
  swirl: "How fast the field flows",
  outerShell: "Where the shell sits, and how many particles are on it",
  drawLimb: "How hard the core reads as a sphere",
  outerGain: "How bright the outer shell is",
  outerStreak: "How long the shell particles' trails are",
  outerLimb: "How hard the shell reads as a sphere",
  outerPace: "How much slower the shell drifts",
  shardGain: "How bright the circuit shards are",
  shardSize: "How big a shard is",
  shardStride: "How many particles become shards",
  clump: "How the debris clusters into clumps and voids",
  lattice: "The baked hubs-and-spokes loop under the live body",
  latticeBlur: "Motion blur on the footage, along its own travel",
  latticeSat: "How saturated the footage is",
  latticeGlow: "A soft glow lifted off the footage",
  latticeSpeed: "How fast the footage plays",
  presence: "How big the whole composite sits in the frame",
  focus: "How the far hemisphere falls out of focus",
  facetGain: "How bright the crystal facets are",
  facetSize: "How big a facet is",
  facetSpin: "How fast the crystal turns",
  facetLimb: "How much the facets favour the rim",
  core: "How bright the heart is",
  eye: "The eye — pupil, iris and lens ring",
  reverb: "How the voice rings through the body",
  starburst: "Horizontal flare across the middle",
  petal: "How many bloom lobes",
  cloud: "How cloud-formed the mass is",
  voiceLevel: "How hard her voice moves her overall",
  voiceLow: "How hard the lows pressurise her nucleus",
  voiceMid: "How hard the mids move her interior",
  voiceHigh: "How much the highs light her surface",
  voiceEnv: "How fast she answers a syllable, and how slowly she lets go",
  voiceGate: "How quiet counts as silence",
  beat: "How hard a syllable lands, and how long it rings",
  listen: "How much she shows that you are talking",
  gaze: "Where she is looking, idle and engaged",
  arousalLift: "How far a working or spoken turn rouses her",
  idlePulse: "The oscillator that stands in for a voice she does not have",
  composition: "How big she is inside her porthole",
  daylight: "How the time of day warms her",
  wander: "How her mood drifts when nothing is happening",
  gesture: "How often she looks, nods or preens",
  errorTone: "What a dropped call does to her",
  ...Object.fromEntries(Object.entries(PHENO_TITLES)
    .map(([k, v]) => [`pheno.${k}`, v])),
};

function row(
  key: string,
  label: string,
  values: number[],
  onChange: (next: number[]) => void,
): HTMLElement {
  const fallback = RANGE[key] ?? [0, 1, 0.005];
  const wrap = document.createElement("div");
  wrap.className = "row";
  // A STABLE HANDLE. Rows were addressed by their visible text, which stopped
  // being unique the moment the titles became prose: "How hard the core reads as a
  // sphere" belongs to drawLimb, so a probe looking for the row containing "core"
  // silently adjusted the wrong slider and then reported that the field it thought
  // it had changed had no effect. Wrong conclusions, not just a flaky selector.
  wrap.dataset.field = key;
  const name = document.createElement("label");
  // A pair is `base + perEnergy * energy`, so the two sliders are not
  // interchangeable and the legend says which is which.
  const parts = LEGEND[key] ?? [];
  // An unlabelled field is a gap in LEGEND, and saying so out loud is more useful
  // than a plausible-looking default: legending every pair as `base / xenergy` is
  // what hid the speed dials, because half of these pairs are not ramps at all.
  const named = parts.length === values.length
    ? parts
    : values.map((_, i) => parts[i]
        ?? (values.length === 1 ? "UNLABELLED" : `#${i + 1} UNLABELLED`));
  // HOVER CARRIES THE PROSE. Vertical faders leave no room for a sentence, so
  // the visible label is the code name alone and the title with the value
  // legend rides the native tooltip on the card.
  wrap.title = `${TITLES[key] ?? `${label} — UNTITLED`}\n${label} · ${named.join(" / ")}`;
  const vals = document.createElement("div");
  vals.className = "vals";
  wrap.appendChild(vals);
  const live = values.slice();
  const readouts: HTMLElement[] = [];
  values.forEach((value, index) => {
    const [min, max, step] = RANGE_AT[lfoKey(key, index)] ?? fallback;
    const input = document.createElement("input");
    input.type = "range";
    input.min = String(min);
    input.max = String(max);
    input.step = String(step);
    input.value = String(value);
    const out = document.createElement("b");
    out.textContent = value.toFixed(3);
    readouts.push(out);
    sliderDom[lfoKey(key, index)] = { input, out };
    // TYPE THE NUMBER. Click the readout and it becomes a field: Enter or blur
    // commits (clamped to the slider's range), Escape walks away. A dial you
    // can only drag cannot be set to exactly 0.5.
    out.title = "Click to type a value";
    out.style.cursor = "text";
    out.addEventListener("click", () => {
      if (out.querySelector("input")) return;
      const was = live[index];
      const field = document.createElement("input");
      field.type = "number";
      field.step = String(step);
      field.value = was.toFixed(3);
      field.style.width = "58px";
      field.style.height = "18px";
      field.style.font = "inherit";
      out.textContent = "";
      out.appendChild(field);
      field.focus();
      field.select();
      let settled = false;
      const done = (commit: boolean) => {
        // Enter removes the field, and removal fires blur — one commit only.
        if (settled) return;
        settled = true;
        const typed = Number(field.value);
        field.remove();
        const next = commit && Number.isFinite(typed)
          ? Math.min(max, Math.max(min, typed))
          : was;
        live[index] = next;
        input.value = String(next);
        out.textContent = next.toFixed(3);
        if (next !== was) {
          onChange(live.slice());
          push();
        }
      };
      field.addEventListener("keydown", (event) => {
        if (event.key === "Enter") done(true);
        if (event.key === "Escape") done(false);
        event.stopPropagation();
      });
      field.addEventListener("blur", () => done(true));
    });
    input.addEventListener("input", () => {
      live[index] = Number(input.value);
      readouts[index].textContent = live[index].toFixed(3);
      onChange(live.slice());
      push();
    });
    // The LFO toggle sits with its slider rather than in a panel of its own: it
    // belongs to that one value, and a separate panel would make you match names
    // up by eye.
    const bind = document.createElement("button");
    bind.type = "button";
    bind.className = "lfo-bind";
    bind.title = "Sweep this value";
    bind.textContent = "∿";
    // SPEECH REACH, next to the oscillator: click to arm, drag the slider to
    // the far point speech should pulse to, click again to set. The dial then
    // walks back to where it was — that setting is the start of the journey,
    // the saved point is the end, and the syllables drive the travel.
    const reach = document.createElement("button");
    reach.type = "button";
    reach.className = "lfo-bind reach";
    reach.title = "Speech reach — click, drag the slider to the far point, click again to set. Shift-click clears.";
    reach.textContent = "◉";
    const val = document.createElement("div");
    val.className = "val";
    val.title = `${TITLES[key] ?? label} — ${named[index]}`;
    val.appendChild(input);
    val.appendChild(out);
    // The legend stays VISIBLE. Hover-only names made a pair of identical
    // sliders anonymous — which of these is precess speed is not a question
    // a desk should make you ask by pointing at things.
    const tag = document.createElement("span");
    tag.className = "vtag";
    tag.textContent = named[index];
    val.appendChild(tag);
    const fxbtns = document.createElement("div");
    fxbtns.className = "fxbtns";
    fxbtns.appendChild(bind);
    fxbtns.appendChild(reach);
    val.appendChild(fxbtns);
    vals.appendChild(val);

    const panel = lfoPanel(key, index, live, min, max, onChange);
    wrap.appendChild(panel);
    const paintReach = () => {
      const id = lfoKey(key, index);
      reach.classList.toggle("arm", reachArming?.id === id);
      reach.classList.toggle("on", reachArming?.id !== id && speech[id] !== undefined);
    };
    reach.addEventListener("click", (event) => {
      const id = lfoKey(key, index);
      if (event.shiftKey) {
        delete speech[id];
        if (reachArming?.id === id) reachArming = null;
        rememberSpeech();
        paintReach();
        return;
      }
      if (reachArming?.id === id) {
        // Second press: the slider stands at the far point. Save it as the
        // end of the journey and walk the dial back to the start.
        speech[id] = live[index];
        const from = reachArming.from;
        reachArming = null;
        live[index] = from;
        input.value = String(from);
        out.textContent = from.toFixed(3);
        onChange(live.slice());
        push();
        rememberSpeech();
        paintReach();
        return;
      }
      reachArming = { id, from: live[index] };
      paintReach();
    });
    paintReach();
    const paint = () => {
      const on = lfos[lfoKey(key, index)]?.on === true;
      bind.classList.toggle("on", on);
      panel.classList.toggle("open", on);
      input.disabled = on;
    };
    bind.addEventListener("click", () => {
      const id = lfoKey(key, index);
      const existing = lfos[id];
      if (existing?.on) {
        lfos[id] = { ...existing, on: false };
      } else {
        // Default bounds are a quarter of the slider's travel either side of
        // where it already is: a sweep that starts by leaving the value you
        // chose is a sweep you have to undo before you can judge it.
        const span = (max - min) * 0.25;
        lfos[id] = existing ? { ...existing, on: true } : {
          on: true,
          rate: 0.15,
          min: Math.max(min, live[index] - span),
          max: Math.min(max, live[index] + span),
          phase: index * 0.25,
        };
      }
      rememberLfos();
      buildLfoFields(panel, key, index, min, max);
      paint();
    });
    paint();
  });
  const code = document.createElement("span");
  code.className = "code";
  code.textContent = label;
  name.appendChild(code);
  wrap.appendChild(name);
  return wrap;
}

/** rate / min / max for one bound slider. Hidden until the LFO is on. */
function lfoPanel(
  key: string,
  index: number,
  live: number[],
  min: number,
  max: number,
  onChange: (next: number[]) => void,
): HTMLElement {
  void live;
  void onChange;
  const panel = document.createElement("div");
  panel.className = "lfo";
  buildLfoFields(panel, key, index, min, max);
  return panel;
}

function buildLfoFields(
  panel: HTMLElement,
  key: string,
  index: number,
  min: number,
  max: number,
): void {
  const id = lfoKey(key, index);
  panel.innerHTML = "";
  const lfo = lfos[id];
  if (!lfo) return;
  const field = (
    label: string,
    value: number,
    step: number,
    set: (next: number) => void,
  ) => {
    const wrap = document.createElement("label");
    wrap.className = "lfo-field";
    const text = document.createElement("span");
    text.textContent = label;
    const input = document.createElement("input");
    input.type = "number";
    input.step = String(step);
    input.value = String(value);
    input.addEventListener("input", () => {
      const next = Number(input.value);
      if (Number.isFinite(next)) {
        set(next);
        rememberLfos();
      }
    });
    wrap.appendChild(text);
    wrap.appendChild(input);
    panel.appendChild(wrap);
  };
  field("Hz", lfo.rate, 0.01, (v) => { lfos[id] = { ...lfos[id], rate: Math.max(0, v) }; });
  field("min", lfo.min, (max - min) / 100, (v) => {
    lfos[id] = { ...lfos[id], min: Math.min(Math.max(min, v), max) };
  });
  field("max", lfo.max, (max - min) / 100, (v) => {
    lfos[id] = { ...lfos[id], max: Math.min(Math.max(min, v), max) };
  });
}

/**
 * Advance every bound slider, and MOVE ITS SLIDER.
 *
 * Writing the value into the tuning without moving the control would leave the
 * panel lying about what is being rendered, which is the one thing a bench must
 * never do -- Copy settings would print a number nothing was drawing.
 */
function tickLfos(nowMs: number): void {
  let changed = false;
  for (const [id, lfo] of Object.entries(lfos)) {
    if (!lfo.on) continue;
    const [field, indexText] = id.split(":");
    const index = Number(indexText);
    const current = (tuning as unknown as Record<string, number | number[]>)[field];
    if (current === undefined) continue;
    const turns = (nowMs / 1000) * lfo.rate + lfo.phase;
    // A raised cosine, so the sweep dwells at both ends rather than racing
    // through the values you most want to look at.
    const unit = 0.5 - 0.5 * Math.cos(2 * Math.PI * turns);
    const value = lfo.min + (lfo.max - lfo.min) * unit;
    if (typeof current === "number") {
      (tuning as unknown as Record<string, number>)[field] = value;
    } else {
      const next = current.slice();
      next[index] = value;
      (tuning as unknown as Record<string, number[]>)[field] = next;
    }
    const dom = sliderDom[id];
    if (dom) {
      dom.input.value = String(value);
      dom.out.textContent = value.toFixed(3);
    }
    changed = true;
  }
  // Pushed but NOT remembered: a swept value is a question, not a decision, and
  // writing it to the store every frame would overwrite the look you set.
  if (changed && renderer) {
    (renderer as { setTuning(next: never): void }).setTuning(clone(effectiveTuning()) as never);
  }
}


/**
 * REAL SPEECH, LOOPED, driving the bands.
 *
 * The bench faked them: `0.82 - i * 0.09` in speaking mode, a static descending
 * ramp. That is a plausible-looking spectrum and it is the WRONG test, because
 * every voice-reactive term -- pulsedCore's band weighting, the onset flare, the
 * wave crossing the body -- responds to how the bands MOVE, and a constant ramp
 * never moves. A body tuned against it looks correct while silent and wrong the
 * moment anybody speaks, which is the failure this whole session started with.
 *
 * The clips are the character's own audition takes out of public/companion, so what
 * is being judged is this body reacting to this voice rather than to a test tone.
 */
interface Voice {
  ctx: AudioContext;
  el: HTMLAudioElement;
  analyser: AnalyserNode;
  spectrum: Uint8Array;
  /** Smoothed bands, kept between frames so the decay is ours and not the FFT's. */
  bands: Float32Array;
  /** Previous low-band energy, for onset detection. */
  wasLow: number;
}
let voice: Voice | null = null;

/** Eight bands from the FFT, spaced so speech lands across them rather than in one. */
function foldBands(spectrum: Uint8Array, into: Float32Array): number {
  // LOG-SPACED EDGES. Linear bins put almost all of a voice in the first two bands
  // and leave six reading nothing -- the analyser's bins are linear in Hz and
  // hearing is not. These edges are fractions of the spectrum, roughly doubling.
  const edges = [0, 2, 4, 7, 12, 21, 36, 62, 128];
  let peak = 0;
  for (let b = 0; b < 8; b += 1) {
    let sum = 0;
    for (let i = edges[b]; i < edges[b + 1] && i < spectrum.length; i += 1) {
      sum += spectrum[i];
    }
    const raw = sum / Math.max(1, edges[b + 1] - edges[b]) / 255;
    // Attack fast, release slow. A band that decays as fast as it rises flickers
    // on every glottal pulse and reads as noise rather than as a voice.
    into[b] = raw > into[b] ? raw : into[b] * 0.82 + raw * 0.18;
    peak = Math.max(peak, into[b]);
  }
  return peak;
}

function fmtTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

let seeking = false;

function paintPlayBtn(): void {
  $("voicePlay").textContent = voice && !voice.el.paused ? "❚❚" : "▶";
}

function paintProgress(): void {
  const el = voice?.el;
  const duration = el && Number.isFinite(el.duration) ? el.duration : 0;
  $("npDur").textContent = fmtTime(duration);
  $("npNow").textContent = fmtTime(el?.currentTime ?? 0);
  if (!seeking) {
    ($("npSeek") as HTMLInputElement).value =
      String(duration > 0 && el ? Math.round((el.currentTime / duration) * 1000) : 0);
  }
}

function voiceFail(error: Error): void {
  // Autoplay refusals, decode failures and TTS refusals all land here, and all
  // look like "the bands are dead" if swallowed.
  $("voiceState").textContent = `AUDIO FAILED — ${error.message}`;
  $("voiceState").className = "bad";
}

async function startVoice(src: string, title?: string, kind?: string): Promise<void> {
  // SPEECH HAPPENS OVER STANDBY. He only ever speaks from standby in the app,
  // so every way of starting a line walks the body home first — what is
  // auditioned is the state speech actually plays over.
  if (slot !== "standby") setState("standby");
  await stopVoice();
  const el = new Audio(src);
  el.loop = ($("loop") as HTMLInputElement).checked;
  el.volume = Number(($("level") as HTMLInputElement).value);
  el.crossOrigin = "anonymous";
  el.addEventListener("play", paintPlayBtn);
  el.addEventListener("pause", paintPlayBtn);
  el.addEventListener("ended", paintPlayBtn);
  el.addEventListener("timeupdate", paintProgress);
  el.addEventListener("loadedmetadata", paintProgress);
  el.addEventListener("durationchange", paintProgress);
  // A context created before a gesture starts suspended and the graph runs
  // silently at zero -- which presents as "the analyser returns nothing".
  const ctx = new AudioContext();
  await ctx.resume();
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 512;
  // Ours, not the analyser's: its smoothing applies to the FFT magnitudes and
  // would blunt the onset we are trying to detect.
  analyser.smoothingTimeConstant = 0.2;
  ctx.createMediaElementSource(el).connect(analyser);
  analyser.connect(ctx.destination);
  voice = {
    ctx, el, analyser,
    spectrum: new Uint8Array(analyser.frequencyBinCount),
    bands: new Float32Array(8),
    wasLow: 0,
  };
  await el.play();
  const shown = title ?? src.split("/").pop() ?? src;
  const which = ($("body") as HTMLSelectElement).selectedOptions[0]?.textContent ?? body;
  $("npTitle").textContent = shown;
  $("npSub").textContent = `${which} · ${kind ?? "audition clip"}`;
  paintPlayBtn();
  paintProgress();
  $("voiceState").textContent = `playing ${shown}`;
  $("voiceState").className = "ok";
}

async function stopVoice(): Promise<void> {
  if (!voice) return;
  voice.el.pause();
  voice.el.src = "";
  await voice.ctx.close().catch(() => undefined);
  voice = null;
  $("npTitle").textContent = "Nothing playing";
  $("npSub").textContent = "pick a clip, or type a line below";
  paintPlayBtn();
  paintProgress();
  $("voiceState").textContent = "";
  $("voiceState").className = "";
}

/** The clips for a body, by convention rather than by a list to keep in step. */
function clipsFor(which: string): string[] {
  // The Familiar carries three extra purpose-built test clips: a sustained
  // line for reverb tails, staccato consonants for transients, and a
  // whisper-to-wave sweep for dynamic range.
  const count = which === "familiar" ? 6 : 3;
  return Array.from({ length: count }, (_, i) => `/companion/${which}-${i + 1}.wav`);
}

function assign(key: string, value: number | number[]): void {
  (tuning as unknown as Record<string, unknown>)[key] = value;
}

function push(): void {
  if (!renderer) return;
  remember(slotKey(body, slot), tuning);
  // Cast at the seam: the page holds one union and each renderer takes its own
  // half of it, which the body switch above already guarantees.
  // The renderer hears effectiveTuning() — the desk's monitor mix — while
  // remember() above stores the REAL numbers: mute and solo can never leak
  // into a saved look, which is exactly how a zeroed speaking preset once
  // happened.
  (renderer as { setTuning(next: never): void }).setTuning(clone(effectiveTuning()) as never);
  paintMixerLevels();
  paintDrift();
}

function drive(): void {
  if (!renderer) return;
  const mode = renderMode(slot) as Mode;

  // REAL AUDIO WINS over the synthetic ramp whenever a clip is playing, and it
  // wins in every mode rather than only in speaking -- the point is to see how
  // each preset answers a voice, and gating it on one mode would hide four
  // fifths of the answer.
  if (voice) {
    voice.analyser.getByteFrequencyData(voice.spectrum);
    const peak = foldBands(voice.spectrum, voice.bands);
    const low = (voice.bands[0] + voice.bands[1] + voice.bands[2]) / 3;
    // Onset is a RISE, not a level: a sustained loud vowel is not an onset, and
    // treating it as one made the body flare continuously through a sentence.
    const onset = Math.max(0, low - voice.wasLow) * 3.2;
    voice.wasLow = low;
    // The syllable envelope for speech reach: a VU needle — fast toward a
    // louder syllable, easing back through the gaps between words.
    const reachTarget = voice.el.paused ? 0 : Math.min(1, peak * 1.3);
    speechEnv += (reachTarget - speechEnv) * (reachTarget > speechEnv ? 0.45 : 0.1);
    renderer.update({
      mode,
      level: Math.min(1, peak * 1.15),
      bands: Array.from(voice.bands),
      onset: Math.min(1, onset),
      micLevel: mode === "listening" ? Math.min(1, peak) : 0,
    } as never);
    $("voiceMeter").style.width = `${Math.round(Math.min(1, peak) * 100)}%`;
    return;
  }
  if (talkTest.size > 0) {
    // A stand-in for a line being spoken: syllables at speech rate under the
    // slow swell of phrasing, so the reach plays as it would beneath a clip.
    const t = performance.now() / 1000;
    const syllable = Math.abs(Math.sin(t * Math.PI * 2.6));
    const phrase = 0.55 + 0.45 * Math.sin(t * 0.9);
    speechEnv = Math.min(1, Math.max(0, syllable * phrase));
  } else {
    speechEnv *= 0.88;
  }
  const level = Number(($("level") as HTMLInputElement).value);
  renderer.update({
    mode,
    level,
    // A FLAT SPECTRUM AND NO ONSET, deliberately. This path used to fire a 0.9
    // onset every forty-fifth frame -- a metronome that made the body look alive
    // in the bench while testing nothing about speech, and that measured as MORE
    // variance than a real clip produces. With real audio available above, the
    // honest fallback is a body with no voice, so that what the crests and the
    // heart do on their own is visible rather than hidden under a fake heartbeat.
    bands: Array.from({ length: 8 }, () => (mode === "speaking" ? 0.34 : 0.1)),
    onset: 0,
    micLevel: mode === "listening" ? level : 0,
  } as never);
}

/**
 * Draw one frame on demand, for a probe that needs to read the pixels.
 *
 * readPixels MUST happen in the same task as the draw: the compositor clears the
 * drawing buffer between tasks, so a read from outside comes back all zeros --
 * indistinguishable from a body that rendered nothing, and the cause of three false
 * diagnoses in this file's history. Exposing the step lets an external check draw
 * and read together instead of guessing.
 */
declare global {
  interface Window { __benchFrame?: () => void }
}
window.__benchFrame = () => {
  drive();
  renderer?.frame(performance.now());
};

function loop(): void {
  raf = realRaf(loop);
  frames += 1;
  if (abActive) {
    // The reference holds the stage; sweeps and journeys wait their turn.
  } else if (transit && renderer) {
    const at = Math.min(1, (performance.now() - transit.start) / transit.ms);
    // A raised cosine, so the journey leaves and arrives gently.
    const eased = 0.5 - 0.5 * Math.cos(Math.PI * at);
    const mixed = lerpTuning(transit.from, effectiveTuning(), eased);
    // A recorded journey drives its tracked fields on real time, not eased
    // time — the choreography IS the easing for those dials.
    const framed = transit.tracks ? applyTracks(mixed, transit.tracks, at) : mixed;
    (renderer as { setTuning(next: never): void }).setTuning(framed as never);
    if (at >= 1) transit = null;
  } else {
    tickLfos(performance.now());
    // SPEECH REACH rides here too: while a line plays, every dial with a
    // saved reach travels start→end on the syllable envelope, monitor-side.
    // Pushed only when the envelope actually moved, and never over a journey
    // or a take — those branches call effectiveTuning() themselves.
    if (renderer && (Object.keys(speech).length > 0 || talkTest.size > 0)
      && Math.abs(speechEnv - speechShown) > 0.003) {
      speechShown = speechEnv;
      (renderer as { setTuning(next: never): void }).setTuning(clone(effectiveTuning()) as never);
    }
  }
  drive();
  renderer?.frame(performance.now());
  // Every twelfth frame: often enough to feel live while dragging, rare enough
  // that the readback is not the reason the bench is slow.
  if (frames % 12 === 0) measure();
}

function cancelLoop(): void {
  if (raf) cancelAnimationFrame(raf);
  raf = 0;
}

/**
 * The centre of the frame, read in the SAME TASK as the draw above.
 *
 * A centred box of half the width and half the height — a quarter of the frame
 * area, which is where the iris and the core lobes are, and the only region the
 * blowout ever appeared in.
 */
function measure(): void {
  const canvas = $("stage").querySelector("canvas") as HTMLCanvasElement | null;
  const gl = canvas?.getContext("webgl2") as WebGL2RenderingContext | null;
  if (!canvas || !gl) return;
  const w = Math.max(1, Math.floor(canvas.width / 2));
  const h = Math.max(1, Math.floor(canvas.height / 2));
  const buf = new Uint8Array(w * h * 4);
  gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  gl.readPixels(Math.floor(canvas.width / 4), Math.floor(canvas.height / 4),
    w, h, gl.RGBA, gl.UNSIGNED_BYTE, buf);
  let sat = 0;
  let val = 0;
  let white = 0;
  let ink = 0;
  const n = w * h;
  for (let i = 0; i < buf.length; i += 4) {
    const a = buf[i + 3] / 255;
    const r = (buf[i] / 255) * a;
    const g = (buf[i + 1] / 255) * a;
    const b = (buf[i + 2] / 255) * a;
    const max = Math.max(r, g, b);
    const min = Math.min(r, g, b);
    sat += max <= 0 ? 0 : (max - min) / max;
    val += max;
    if (min >= 0.92) white += 1;
    if (max >= 0.02) ink += 1;
  }
  const white01 = white / n;
  $("readout").innerHTML =
    `sat <b>${(sat / n).toFixed(4)}</b>`
    + `  val <b>${(val / n).toFixed(4)}</b>`
    + `  white <b class="${white01 > 0.0005 ? "bad" : "good"}">${white01.toFixed(4)}</b>`
    + `  ink <b>${(ink / n).toFixed(4)}</b>`;
}

/**
 * LOCK THE CURRENT NUMBERS IN, to a file rather than to localStorage.
 *
 * localStorage is the right place for work in progress and the WRONG place for a
 * decision, because it lives inside one browser profile on one machine and
 * nothing outside that tab can read it. A preset that has been settled by eye has
 * to leave the browser to be ported into the source, so this posts it to a
 * dev-server route that writes tests/visual/presets.json.
 *
 * The whole tuning is written, not a delta against the shipped base. Working out
 * the delta is a source-level judgement -- some of those differences belong in the
 * mode table and some belong in the settled base -- and a machine guessing which
 * is which would quietly move a decision into the wrong table.
 */
async function savePreset(): Promise<void> {
  const status = $("saved");
  const label = window.prompt(`Label this ${slotKey(body, slot)} version (optional)`, "");
  if (label === null) {
    status.textContent = "save cancelled";
    status.className = "";
    return;
  }
  const payload = {
    body,
    slot,
    tuning,
    lfos: Object.fromEntries(Object.entries(lfos).filter(([, l]) => l.on)),
    speech,
    ...(label.trim() === "" ? {} : { label: label.trim() }),
  };
  try {
    const response = await fetch("/__bench-presets", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const body_ = await response.json() as { path?: string; versions?: number };
    status.textContent = `locked in — v${body_.versions ?? "?"} of ${slotKey(body, slot)}`;
    status.className = "ok";
    void refreshHistory();
  } catch (error) {
    // Said out loud rather than swallowed: a save that silently failed would be
    // discovered when the tuning was wanted, which is exactly too late.
    status.textContent = `SAVE FAILED — ${(error as Error).message}`;
    status.className = "bad";
  }
}

/**
 * THE DESK. One strip per draw pass along the bottom of the stage; the right
 * rail is the selected channel's effects. A strip carries the pass's short
 * name, a lamp that lights while an LFO sweeps any of its values, a fader on
 * the pass's master level, and mute/solo.
 *
 * MUTE AND SOLO ARE MONITOR CONTROLS. They shape what the renderer shows and
 * never touch `tuning`, so a saved preset cannot inherit a channel somebody
 * was auditioning without.
 */
/** Superseded by the iris: present in the struct, deliberately not a channel.
 *  Hidden rather than orphaned, so the desk does not grow a warning strip for
 *  fields nothing should be editing. */
/** link* is superseded by the iris; `presence` is GLOBAL FRAMING, owned by the
 *  topbar slider rather than a desk strip — a strip for it invited soloing
 *  the body's size, which is how the composite once shrank to a dot. */
const HIDDEN_FIELDS = new Set(["linkGain", "linkBow", "linkRange", "linkLimb", "presence"]);
let channel = "";
/** Channels auditioning their talking journey WITHOUT audio: a synthetic
 *  syllable envelope drives their speech reach, a stand-in for a line being
 *  spoken over standby. Solo survives; mute went — the fader at zero is mute. */
const talkTest = new Set<string>();
/** A SET: soloing Wheels and Film together auditions the pair. */
const soloed = new Set<string>();
const mixerDom: Record<string, { input: HTMLInputElement; out: HTMLElement }> = {};

/**
 * THE DESK READS FURTHEST-OUT TO CENTRE, left to right: the baked footage
 * behind everything, then the distant shell, in through the structure to the
 * eye. Non-spatial strips (voice, presence) sit at the right like a master
 * section; anything unranked keeps its GROUPS order after the ranked.
 */
const SPATIAL_RANK: Record<string, number> = {
  "0 · Lattice loop — the baked layer": 0,
  "4 · Outer particle layer — the distant shell": 1,
  "1 · Wheels — the orbiting beams": 2,
  "2 · Sigils — the outer inscriptions": 3,
  "2 · Glyphs — the inner inscriptions": 4,
  "5 · Crystal facets": 4,
  "4 · Veins and cracks": 5,
  "5 · Circuit shards": 6,
  "5 · Debris — clumping and depth": 7,
  "3 · Dendrites — the neurons and their signals": 8,
  "4 · Inner particle layer — the core cloud": 9,
  "3 · The iris — radial filaments": 10,
  "6 · The eye — core and composite": 11,
  "6 · Voice reverberation — how speech crosses the body": 90,
};

/**
 * ONE WORD PER STRIP. The desk reads at a glance or it does not read; the
 * full title with its prose stays on the strip's tooltip.
 */
const STRIP_NAME: Record<string, string> = {
  "0 · Lattice loop — the baked layer": "Film",
  "4 · Outer particle layer — the distant shell": "Shell",
  "1 · Wheels — the orbiting beams": "Wheels",
  "2 · Glyphs — the inner inscriptions": "Glyphs",
  "2 · Sigils — the outer inscriptions": "Sigils",
  "5 · Crystal facets": "Facets",
  "4 · Veins and cracks": "Veins",
  "5 · Circuit shards": "Shards",
  "5 · Debris — clumping and depth": "Debris",
  "3 · Dendrites — the neurons and their signals": "Neurons",
  "4 · Inner particle layer — the core cloud": "Cloud",
  "3 · The iris — radial filaments": "Iris",
  "6 · The eye — core and composite": "Eye",
  "6 · Voice reverberation — how speech crosses the body": "Reverb",
  "1 · Her voice — what speech does to the body": "Voice",
  "2 · Her envelope — the shape of a syllable": "Envelope",
  "3 · Her attention — being spoken to": "Attention",
  "4 · Her inner life — alive between events": "Life",
  "5 · Her presence — size, light and failure": "Aura",
};

function channelsFor(): { title: string; fields: string[] }[] {
  const fields = Object.keys(tuning).filter((f) => !HIDDEN_FIELDS.has(f));
  const present = GROUPS
    .map((g) => ({ title: g.title, fields: g.fields.filter((f) => fields.includes(f)) }))
    .filter((g) => g.fields.length > 0);
  const placed = new Set(present.flatMap((g) => g.fields));
  const orphans = fields.filter((f) => !placed.has(f));
  if (orphans.length > 0) {
    present.push({ title: "UNGROUPED — add these to GROUPS", fields: orphans });
  }
  return present
    .map((g, index) => ({ g, key: SPATIAL_RANK[g.title] ?? 30 + index }))
    .sort((a, b) => a.key - b.key)
    .map((x) => x.g);
}

/** What a channel's fader drives: the pass's first master level. */
function levelFields(fields: readonly string[]): string[] {
  const levels = fields.filter((f) => f.endsWith("Gain"));
  for (const special of ["core", "reverb", "voiceLevel"] as const) {
    if (fields.includes(special)) levels.push(special);
  }
  return levels;
}

/** What mute silences: every field that puts light on screen for this pass.
 *  Wider than the fader, because a pass like the eye draws through `eye` and
 *  `starburst` as well as `core` — muting only the gains left it half lit. */
const MUTE_EXTRA = new Set(["core", "eye", "starburst", "reverb", "voiceLevel", "lattice"]);
function muteFields(fields: readonly string[]): string[] {
  return fields.filter((f) => f.endsWith("Gain") || MUTE_EXTRA.has(f));
}

/** Fields that are GEOMETRY, not light. Solo and the faders must never scale
 *  these: a soloed desk zeroing `presence` shrank the whole composite —
 *  size is not a channel you silence. */
const GEOMETRY_FIELDS = new Set(["presence"]);
/** A strip the console can fade: at least one field that is light, not shape. */
function fadeable(fields: readonly string[]): boolean {
  return fields.some((f) => !GEOMETRY_FIELDS.has(f));
}

function audible(title: string): boolean {
  return soloed.size === 0 || soloed.has(title);
}

/**
 * THE FADER IS A VOLUME, NOT A DIAL. Each desk strip's slider scales the
 * whole channel's light output — every gain the channel owns, the baked
 * layer included — without touching the numbers underneath, so at zero the
 * channel simply is not there and the dials still read what you tuned.
 * Working state, per body, this browser only.
 */
let channelVolume: Record<string, number> = {};

function loadVolumes(): void {
  try {
    channelVolume = JSON.parse(localStorage.getItem(storageKey(`volume.${body}`)) ?? "{}") as
      Record<string, number>;
  } catch {
    channelVolume = {};
  }
}

function volumeOf(title: string): number {
  const v = channelVolume[title];
  return typeof v === "number" ? Math.min(1, Math.max(0, v)) : 1;
}

function rememberVolumes(): void {
  try {
    localStorage.setItem(storageKey(`volume.${body}`), JSON.stringify(channelVolume));
  } catch { /* fine */ }
}

/** The tuning the renderer hears: muted channels' levels at zero, the real
 *  numbers untouched. With nothing muted this is `tuning` itself. */
function effectiveTuning(of: Tuning = tuning): Tuning {
  const faded = Object.keys(channelVolume).some((t) => volumeOf(t) < 1);
  const talking = speechEnv > 0.002
    && (Object.keys(speech).length > 0 || talkTest.size > 0);
  if (soloed.size === 0 && !faded && !talking) return of;
  const out = clone(of);
  const record = out as unknown as Record<string, number | number[]>;
  // Speech reach FIRST, volumes after: the fader is the channel's master, so
  // it scales the spoken value the same way it scales the tuned one.
  if (talking) {
    // A real line moves every reach; the talk test moves only its channels.
    const live = voice !== null && !voice.el.paused;
    const scoped = live ? null : new Set(
      channelsFor().filter((g) => talkTest.has(g.title)).flatMap((g) => g.fields),
    );
    for (const [id, end] of Object.entries(speech)) {
      const [field, indexText] = id.split(":");
      if (scoped !== null && !scoped.has(field)) continue;
      const value = record[field];
      if (value === undefined) continue;
      if (typeof value === "number") {
        record[field] = value + (end - value) * speechEnv;
      } else {
        const next = value.slice();
        const index = Number(indexText);
        next[index] = next[index] + (end - next[index]) * speechEnv;
        record[field] = next;
      }
    }
    // A talk-tested channel with NO reach points still shows something: its
    // light breathes on the envelope. Without this, osc on a channel you had
    // not yet configured did literally nothing — a button that works only
    // after invisible setup reads as broken.
    if (!live) {
      for (const g of channelsFor()) {
        if (!talkTest.has(g.title)) continue;
        for (const field of muteFields(g.fields)) {
          if (Object.keys(speech).some((id) => id.startsWith(`${field}:`))) continue;
          const value = record[field];
          if (value === undefined) continue;
          const swell = 1 + 0.35 * speechEnv;
          record[field] = typeof value === "number"
            ? value * swell
            : value.map((x) => x * swell);
        }
      }
    }
  }
  for (const g of channelsFor()) {
    if (!fadeable(g.fields)) continue;
    const vol = audible(g.title) ? volumeOf(g.title) : 0;
    if (vol >= 1) continue;
    // A channel with no light of its own (Debris, the envelopes) scales its
    // EFFECT instead: every field fades, so zero still means "not there" —
    // except geometry, which no volume is allowed to touch.
    const lit = muteFields(g.fields);
    for (const field of (lit.length > 0 ? lit : g.fields.filter((f) => !GEOMETRY_FIELDS.has(f)))) {
      const value = record[field];
      record[field] = typeof value === "number" ? value * vol : value.map((x) => x * vol);
    }
  }
  return out;
}

function channelShortName(title: string): string {
  return title.replace(/^\d+ · /, "").split(" — ")[0];
}

function selectChannel(title: string): void {
  channel = title;
  try {
    localStorage.setItem(storageKey(`channel.${body}`), title);
  } catch { /* nothing to persist to */ }
  buildControls();
  paintMixer();
}

/** The selected channel, valid for the body on stage: the remembered one if it
 *  still exists here, the first strip otherwise. */
function ensureChannel(): void {
  const channels = channelsFor();
  if (channels.some((c) => c.title === channel)) return;
  let stored: string | null = null;
  try {
    stored = localStorage.getItem(storageKey(`channel.${body}`));
  } catch { /* fine */ }
  channel = channels.some((c) => c.title === stored)
    ? stored as string
    : channels[0]?.title ?? "";
}

function buildMixer(): void {
  const desk = $("mixer");
  desk.innerHTML = "";
  for (const id of Object.keys(mixerDom)) delete mixerDom[id];
  ensureChannel();
  for (const g of channelsFor()) {
    const strip = document.createElement("div");
    strip.className = "channel";
    strip.dataset.channel = g.title;
    const name = document.createElement("div");
    name.className = "chname";
    name.textContent = STRIP_NAME[g.title] ?? channelShortName(g.title).split(" ")[0];
    name.title = g.title;
    strip.appendChild(name);
    const lamp = document.createElement("i");
    lamp.className = "chlamp";
    lamp.title = "Lit while an LFO sweeps this channel";
    strip.appendChild(lamp);
    const drift = document.createElement("span");
    drift.className = "chdrift";
    drift.title = "Values off the baseline in this channel";
    strip.appendChild(drift);
    if (g.fields.includes("lattice")) {
      strip.classList.add("video");
      const vid = document.createElement("span");
      vid.className = "chvid";
      vid.textContent = "▣";
      vid.title = "The baked video layer — footage, not shader";
      strip.appendChild(vid);
    }
    if (fadeable(g.fields)) {
      const fader = document.createElement("input");
      fader.type = "range";
      fader.className = "fader";
      fader.min = "0";
      fader.max = "1";
      fader.step = "0.01";
      fader.value = String(volumeOf(g.title));
      fader.title = "Channel volume — everything this channel draws, dark at zero";
      const out = document.createElement("b");
      out.textContent = `${Math.round(volumeOf(g.title) * 100)}%`;
      fader.addEventListener("input", () => {
        channelVolume[g.title] = Number(fader.value);
        out.textContent = `${Math.round(Number(fader.value) * 100)}%`;
        rememberVolumes();
        push();
      });
      fader.addEventListener("click", (event) => event.stopPropagation());
      mixerDom[g.title] = { input: fader, out };
      strip.appendChild(fader);
      strip.appendChild(out);
      const ms = document.createElement("div");
      ms.className = "ms";
      const solo = document.createElement("button");
      solo.type = "button";
      solo.textContent = "S";
      solo.title = "Solo — silence every other channel";
      solo.addEventListener("click", (event) => {
        event.stopPropagation();
        if (soloed.has(g.title)) soloed.delete(g.title);
        else soloed.add(g.title);
        paintMixer();
        push();
      });
      // TALK TEST. Oscillates this channel's speech reach on a synthetic
      // syllable envelope — standby talking, without a clip — so "what does
      // speaking do to this pass" is a button rather than an audition.
      const osc = document.createElement("button");
      osc.type = "button";
      osc.textContent = "osc";
      osc.title = "Talk test — play this channel's speech reach as if a line were being spoken";
      osc.addEventListener("click", (event) => {
        event.stopPropagation();
        if (talkTest.has(g.title)) talkTest.delete(g.title);
        else talkTest.add(g.title);
        paintMixer();
      });
      const halt = document.createElement("button");
      halt.type = "button";
      halt.textContent = "■";
      halt.title = "Stop this channel's talk test";
      halt.addEventListener("click", (event) => {
        event.stopPropagation();
        talkTest.delete(g.title);
        paintMixer();
      });
      ms.appendChild(solo);
      ms.appendChild(osc);
      ms.appendChild(halt);
      strip.appendChild(ms);
    }
    strip.addEventListener("click", () => selectChannel(g.title));
    desk.appendChild(strip);
  }
  paintMixer();
}

function paintMixer(): void {
  const desk = $("mixer");
  const channels = channelsFor();
  for (const strip of Array.from(desk.children) as HTMLElement[]) {
    const title = strip.dataset.channel ?? "";
    strip.classList.toggle("selected", title === channel);
    strip.classList.toggle("muted", !audible(title));
    const fields = channels.find((c) => c.title === title)?.fields ?? [];
    const swept = fields.some((field) =>
      Object.entries(lfos).some(([id, l]) => l.on && id.startsWith(`${field}:`)));
    strip.querySelector(".chlamp")?.classList.toggle("on", swept || talkTest.has(title));
    const off = driftCount(fields);
    const badge = strip.querySelector(".chdrift");
    if (badge) badge.textContent = off > 0 ? `Δ${off}` : "";
    const [solo, osc] = Array.from(strip.querySelectorAll(".ms button"));
    solo?.classList.toggle("on", soloed.has(title));
    osc?.classList.toggle("on", talkTest.has(title));
  }
}

/** The faders show each channel's volume, wherever it was last set. */
function paintMixerLevels(): void {
  const pq = $("presenceQuick") as HTMLInputElement;
  const at = (tuning as unknown as Record<string, number>).presence;
  // Never write back into a slider mid-drag: the reflect fights the thumb.
  if (typeof at === "number" && document.activeElement !== pq) {
    pq.value = String(at);
    const out = $("presenceOut");
    if (!out.querySelector("input")) out.textContent = at.toFixed(3);
  }
  for (const [title, dom] of Object.entries(mixerDom)) {
    const vol = volumeOf(title);
    dom.input.value = String(vol);
    dom.out.textContent = `${Math.round(vol * 100)}%`;
  }
}

/**
 * THE BASELINE. "Apply to all states" copies the look on stage to every state
 * of the body and records it as the ground truth each state is then edited
 * FROM — so "how far has this state gone" is a measurable answer, not a
 * memory. Values off the baseline are marked amber in the rail, and each
 * channel strip counts its own drift.
 */
let baseline: { tuning: Tuning; lfos: LfoMap } | null = null;

/**
 * Server first, localStorage second. A baseline is a decision, and a decision
 * that lives in one browser profile is one localStorage clear from gone — the
 * same lesson the save button already carries. The file's `<body>.baseline`
 * entry is versioned like any state, so the ground truth has a history too.
 */
function loadBaseline(): void {
  const versions = history[`${body}.baseline`]?.versions ?? [];
  const newest = versions[versions.length - 1];
  if (newest) {
    baseline = {
      tuning: { ...clone(shippedFor(body, "standby")), ...newest.tuning } as Tuning,
      lfos: { ...(newest.lfos ?? {}) },
    };
    paintBaselineNote();
    return;
  }
  try {
    const raw = localStorage.getItem(storageKey(`baseline.${body}`));
    const parsed = raw ? JSON.parse(raw) as Tuning & { tuning?: Tuning; lfos?: LfoMap } : null;
    baseline = parsed
      ? ("tuning" in parsed && parsed.tuning
          ? { tuning: parsed.tuning, lfos: parsed.lfos ?? {} }
          : { tuning: parsed as Tuning, lfos: {} })
      : null;
  } catch {
    baseline = null;
  }
  paintBaselineNote();
}

function driftAt(field: string, index: number): boolean {
  if (!baseline) return false;
  const now = (tuning as unknown as Record<string, number | number[]>)[field];
  const was = (baseline.tuning as unknown as Record<string, number | number[]>)[field];
  if (now === undefined || was === undefined) return false;
  const a = typeof now === "number" ? now : now[index];
  const b = typeof was === "number" ? was : (was as number[])[index];
  return typeof a === "number" && typeof b === "number" && Math.abs(a - b) > 1e-6;
}

function driftCount(fields: readonly string[]): number {
  if (!baseline) return 0;
  let count = 0;
  for (const field of fields) {
    const now = (tuning as unknown as Record<string, number | number[]>)[field];
    const width = typeof now === "number" ? 1 : now?.length ?? 0;
    for (let index = 0; index < width; index += 1) {
      if (driftAt(field, index)) count += 1;
    }
  }
  return count;
}

function paintDrift(): void {
  for (const [id, dom] of Object.entries(sliderDom)) {
    const [field, indexText] = id.split(":");
    dom.out.classList.toggle("drift", driftAt(field, Number(indexText)));
  }
  paintBaselineNote();
  // The strips' Δ counts live in paintMixer; drift changes on every dial move,
  // so the desk repaints with the rail rather than waiting for a click.
  paintMixer();
  paintDriftFilter();
  paintStates();
}

function paintBaselineNote(): void {
  const note = $("baselineNote");
  if (!baseline) {
    note.innerHTML = "No baseline — <i>Apply to all states</i> makes this look the ground truth.";
    return;
  }
  const versions = history[`${body}.baseline`]?.versions ?? [];
  const from = versions[versions.length - 1]?.label;
  const off = driftCount(Object.keys(tuning).filter((f) => !HIDDEN_FIELDS.has(f)));
  const provenance = from ? ` · ${from}` : "";
  note.innerHTML = off === 0
    ? `<b style="color:#6ee7a8">on baseline</b> — ${slot} matches the shared ground${provenance}`
    : `<b>${off} value${off === 1 ? "" : "s"}</b> off baseline in ${slot}${provenance}`;
}

$("applyAll").addEventListener("click", () => {
  // EVERY slot, arrival and error included: "they should look the same
  // whichever tab you click on" has no exceptions, and the hidden speaking
  // slot is written too so the app's speaking state matches standby.
  const states = slotsFor(body);
  const sure = window.confirm(
    `Overwrite EVERY ${body} state — ${states.join(", ")} — with the ${slot} look, and make it the baseline they are all measured from?`,
  );
  if (!sure) return;
  const ground = { tuning: clone(tuning), lfos: { ...lfos } };
  baseline = ground;
  try {
    localStorage.setItem(storageKey(`baseline.${body}`), JSON.stringify(ground));
    for (const at of states) {
      // The look AND its motion AND its speech: a state is animated, so the
      // oscillators and the reach are part of the ground, not accessories
      // left behind.
      localStorage.setItem(storageKey(slotKey(body, at)), JSON.stringify(ground.tuning));
      localStorage.setItem(storageKey(`${slotKey(body, at)}.lfo`), JSON.stringify(ground.lfos));
      localStorage.setItem(storageKey(`${slotKey(body, at)}.speech`), JSON.stringify(speech));
    }
  } catch { /* a blocked store is not a reason to stop rendering */ }
  // And to the FILE — one OVERWRITE version per state plus the baseline — so
  // the ground survives this browser AND lands in every other one: overwrite
  // versions are adopted over local copies on the next load. Fire-and-report:
  // a failed write says so in the status line rather than pretending.
  const posts: { at: string; label: string }[] = [
    { at: "baseline", label: `baseline from ${slot}` },
    ...states.map((at) => ({ at: at as string, label: `apply-to-all from ${slot}` })),
  ];
  void Promise.all(posts.map(({ at, label }) =>
    fetch("/__bench-presets", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        body, slot: at, tuning: ground.tuning, lfos: ground.lfos, speech,
        overwrite: true, label,
      }),
    }).then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status} on ${at}`);
    }),
  )).then(() => {
    $("saved").textContent =
      `${slot} applied to all ${states.length} states and the baseline, saved to file`;
    $("saved").className = "ok";
    void refreshHistory();
  }).catch((error: Error) => {
    $("saved").textContent = `applied locally, FILE SAVE FAILED — ${error.message}`;
    $("saved").className = "bad";
  });
  lfos = { ...ground.lfos };
  paintDrift();
  paintMixer();
});

/** Load the ground into the state on stage, oscillators included, and edit up
 *  from there — the iteration loop the baseline exists for. */
$("fromBaseline").addEventListener("click", () => {
  if (!baseline) {
    $("saved").textContent = "no baseline yet — Apply to all states sets one";
    $("saved").className = "bad";
    return;
  }
  transit = null;
  tuning = { ...clone(shipped), ...clone(baseline.tuning) } as Tuning;
  lfos = { ...baseline.lfos };
  buildControls();
  remember(slotKey(body, slot), tuning);
  rememberLfos();
  renderer?.transitionTo(clone(effectiveTuning()) as never);
  paintMixerLevels();
  paintDrift();
  $("saved").textContent = `${slot} reset to baseline`;
  $("saved").className = "ok";
});

/**
 * THE SAVE HISTORY, read back from the file the saves go into. Saving appends
 * a version rather than replacing the entry, so every look ever locked in
 * stays reachable. Choosing one loads it into the dials and localStorage like
 * any edit; the file is not touched until the next save.
 */
type SavedVersion = {
  tuning: Partial<Tuning>; lfos?: LfoMap; speech?: Record<string, number>;
  savedAt?: string; label?: string; overwrite?: boolean;
};
let history: Record<string, { versions: SavedVersion[] }> = {};

/**
 * ADOPT BROADCASTS. A version marked `overwrite` is "Apply to all states"
 * speaking to EVERY browser, not just the one that pressed it: it outranks
 * this browser's local copy exactly once, stamped by its savedAt so later
 * local edits win again until the next broadcast. Without this, "all states
 * look the same" was only ever true in the browser that pressed the button —
 * everywhere else the old local copies kept shadowing the store.
 */
function adoptOverwrites(): boolean {
  let adopted = false;
  for (const [key, entry] of Object.entries(history)) {
    if (key.includes("->")) continue;
    const newest = [...(entry?.versions ?? [])].reverse().find((v) => v.overwrite === true);
    if (!newest) continue;
    const at = Date.parse(newest.savedAt ?? "") || 0;
    if (at === 0) continue;
    try {
      const seenKey = storageKey(`${key}.adopted`);
      if (Number(localStorage.getItem(seenKey) ?? 0) >= at) continue;
      if (key.endsWith(".baseline")) {
        localStorage.setItem(
          storageKey(`baseline.${key.slice(0, key.indexOf("."))}`),
          JSON.stringify({ tuning: newest.tuning, lfos: newest.lfos ?? {} }),
        );
      } else {
        localStorage.setItem(storageKey(key), JSON.stringify(newest.tuning));
        localStorage.setItem(storageKey(`${key}.lfo`), JSON.stringify(newest.lfos ?? {}));
        localStorage.setItem(storageKey(`${key}.speech`), JSON.stringify(newest.speech ?? {}));
      }
      localStorage.setItem(seenKey, String(at));
      adopted = true;
    } catch { /* a blocked store keeps its local copy */ }
  }
  return adopted;
}

async function refreshHistory(): Promise<void> {
  try {
    const response = await fetch("/__bench-presets");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    history = await response.json() as typeof history;
  } catch {
    // An unreachable store reads as empty rather than as an error page: the
    // bench still works, the select just says nothing is saved.
    history = {};
  }
  const adopted = adoptOverwrites();
  paintHistory();
  loadBaseline();
  // THE STORE JUST ARRIVED. The first mount ran before the fetch, so a look
  // with no URL and no local edit was loaded from the shipped table; re-derive
  // it now that saved() can see the store, and the bench opens on the latest
  // locked-in look everywhere.
  const key = slotKey(body, slot);
  const overridden = new URLSearchParams(location.search).has(key)
    || localStorage.getItem(storageKey(key)) !== null;
  // Re-derive after an adoption too: the broadcast just rewrote the local
  // copy, so the stage must follow it rather than keep the pre-adoption look.
  if (adopted || !overridden) {
    shipped = shippedFor(body, slot);
    tuning = saved(key, shipped);
    lfos = savedLfos(key);
    speech = savedSpeech(key);
    buildControls();
    renderer?.transitionTo(clone(effectiveTuning()) as never);
    paintMixerLevels();
  }
  paintDrift();
  paintStates();
}

function paintHistory(): void {
  const select = $("history") as HTMLSelectElement;
  const versions = history[slotKey(body, slot)]?.versions ?? [];
  select.innerHTML = "";
  const head = document.createElement("option");
  head.value = "";
  head.textContent = versions.length > 0
    ? `History — ${versions.length} saved for ${slotKey(body, slot)}`
    : `History — nothing saved for ${slotKey(body, slot)}`;
  select.appendChild(head);
  // Newest first BY DATE, with the version number stable: v3 stays v3 wherever
  // it sorts, because it names a row in the file, not a position in this list.
  const order = versions
    .map((version, index) => ({ version, index }))
    .sort((a, b) => (b.version.savedAt ?? "").localeCompare(a.version.savedAt ?? ""));
  for (const { version, index } of order) {
    const option = document.createElement("option");
    option.value = String(index);
    const when = version.savedAt
      ? version.savedAt.slice(0, 16).replace("T", " ")
      : "undated";
    option.textContent = `v${index + 1} · ${when}${version.label ? ` · ${version.label}` : ""}`;
    select.appendChild(option);
  }
}

/** The export, in the exact shape of bodyTuning.ts, so it pastes straight in. */
function settingsText(): string {
  const ty = body === "familiar"
    ? "FamiliarTuning"
    : body === "jarvis" ? "JarvisTuning" : "UltronTuning";
  const stem = body === "familiar"
    ? "FAMILIAR"
    : body === "jarvis" ? "JARVIS" : "ULTRON";
  const name = slot === "arrival"
    ? `${stem}_ARRIVAL: ${ty}`
    : `${stem}_${slot.toUpperCase()}: ${ty}`;
  const lines = Object.entries(tuning).map(([key, value]) => {
    const rendered = typeof value === "number"
      ? trim(value)
      : `[${(value as number[]).map(trim).join(", ")}]`;
    return `  ${key}: ${rendered},`;
  });
  return `export const ${name} = {\n${lines.join("\n")}\n};\n`;
}

/** Enough digits to be faithful, few enough to read. */
function trim(value: number): string {
  return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(4)));
}

$("body").addEventListener("change", (event) => {
  body = (event.target as HTMLSelectElement).value as Body;
  mount();
});
/**
 * The controls as a sheet that PUSHES the stage rather than covering it.
 *
 * Both bodies are drawn at the centre of their canvas, so a panel that overlays the
 * stage does not hide the bottom of the picture -- it hides the MIDDLE of the being,
 * because the canvas still believes it owns the whole screen and centres him behind
 * the panel. The sheet is a row of the same grid, so shutting it gives the stage the
 * height back and the renderer re-centres in what it actually has.
 *
 * Shrinking him as the sheet opens is therefore not a side effect to be corrected;
 * it is the point. On a phone the being should be small and central with the
 * controls under him, and full-screen when they are away.
 */
const SHUT_KEY = storageKey("sheetShut");

function paintSheet(): void {
  const shut = document.body.classList.contains("sheet-shut");
  const toggle = $("sheetToggle");
  toggle.textContent = shut ? "Controls" : "Hide controls";
  toggle.setAttribute("aria-expanded", String(!shut));
  // The canvas is sized from its host's box, and that box has just changed. The
  // renderer resizes on its own next frame, but telling the page explicitly means
  // anything else listening for a resize (and the readout's own measurement) does
  // not wait a frame to agree with what is on screen.
  window.dispatchEvent(new Event("resize"));
}

$("sheetToggle").addEventListener("click", () => {
  document.body.classList.toggle("sheet-shut");
  try {
    localStorage.setItem(SHUT_KEY, document.body.classList.contains("sheet-shut") ? "1" : "0");
  } catch {
    // A blocked store is not a reason to refuse to open a panel.
  }
  paintSheet();
});

// SHUT BY DEFAULT ON A PHONE, open on a desktop. Someone arriving on a small screen
// should see the being first; someone on a desktop has room for both and came here
// to move sliders.
try {
  const remembered = localStorage.getItem(SHUT_KEY);
  const narrow = window.matchMedia("(max-width: 900px)").matches;
  if (remembered === "1" || (remembered === null && narrow)) {
    document.body.classList.add("sheet-shut");
  }
} catch {
  // Ignore: the default is open, which is the safe way to be wrong.
}
paintSheet();

/**
 * THE JOURNEY BETWEEN STATES, mapped here rather than left to a cut.
 *
 * A state is an animated base look; changing state eases every number from the
 * look on stage to the destination's saved look over an interval chosen on the
 * transport. The renderer keeps drawing throughout — this is the same journey
 * the app will make, at a pace you can audition slow enough to judge.
 */
const PACE_MS: Record<string, number> = { instant: 0, fast: 350, normal: 1100, slow: 2600 };
/** Fields that are counts, kept whole mid-journey: 1.4 wheels is not a look. */
const INT_FIELDS = new Set(["rings", "shardStride", "petal"]);
let transit: { from: Tuning; start: number; ms: number; tracks?: Tracks } | null = null;
const PACE_FACTOR: Record<string, number> = { instant: 0, fast: 0.5, normal: 1, slow: 2 };

function lerpTuning(from: Tuning, to: Tuning, at: number): Tuning {
  const out = clone(to);
  const target = out as unknown as Record<string, number | number[]>;
  const source = from as unknown as Record<string, number | number[]>;
  for (const [key, value] of Object.entries(target)) {
    const was = source[key];
    if (was === undefined) continue;
    if (typeof value === "number" && typeof was === "number") {
      const mixed = was + (value - was) * at;
      target[key] = INT_FIELDS.has(key) ? Math.round(mixed) : mixed;
    } else if (Array.isArray(value) && Array.isArray(was)) {
      target[key] = value.map((v, index) =>
        typeof was[index] === "number" ? was[index] + (v - was[index]) * at : v);
    }
  }
  return out;
}

function setState(next: Slot): void {
  if (next === slot) return;
  const recorded = ((): Tracks | undefined => {
    const versions = history[`${body}.${slot}->${next}`]?.versions ?? [];
    const newest = versions[versions.length - 1] as unknown as
      { tracks?: Tracks; duration?: number } | undefined;
    return newest?.tracks;
  })();
  const recordedMs = ((): number => {
    const versions = history[`${body}.${slot}->${next}`]?.versions ?? [];
    const newest = versions[versions.length - 1] as unknown as { duration?: number } | undefined;
    return newest?.duration ?? 0;
  })();
  const from = clone(effectiveTuning());
  slot = next;
  shipped = shippedFor(body, slot);
  tuning = saved(slotKey(body, slot), shipped);
  for (const id of Object.keys(sliderDom)) delete sliderDom[id];
  lfos = savedLfos(slotKey(body, slot));
  speech = savedSpeech(slotKey(body, slot));
  reachArming = null;
  buildControls();
  remember(slotKey(body, slot), tuning);
  paintStates();
  paintMixerLevels();
  paintMixer();
  paintHistory();
  paintDrift();
  const paceName = ($("pace") as HTMLSelectElement).value;
  // A RECORDED transition is the legal path between this pair: it plays at its
  // own length scaled by the pace, and the lerp carries any untracked field.
  const ms = recorded
    ? recordedMs * (PACE_FACTOR[paceName] ?? 1)
    : PACE_MS[paceName] ?? 0;
  if (ms === 0 || !renderer) {
    transit = null;
    push();
    return;
  }
  transit = { from, start: performance.now(), ms, tracks: recorded };
}
try {
  const storedPace = localStorage.getItem(storageKey("pace"));
  if (storedPace && storedPace in PACE_MS) ($("pace") as HTMLSelectElement).value = storedPace;
} catch { /* fine */ }
$("pace").addEventListener("change", () => {
  try {
    localStorage.setItem(storageKey("pace"), ($("pace") as HTMLSelectElement).value);
  } catch { /* fine */ }
});
/** The whole body to the file: every state as it would load right now — the
 *  stage's live dials for the current slot, local edits for the rest — plus
 *  the baseline. One label covers the snapshot. */
async function saveEverything(): Promise<void> {
  const status = $("saved");
  const label = window.prompt(`Label this full ${body} snapshot (optional)`, "");
  if (label === null) {
    status.textContent = "save cancelled";
    status.className = "";
    return;
  }
  const jobs: { at: string; tuning: unknown; lfos: unknown; speech: unknown }[] =
    slotsFor(body).map((at) => ({
      at: at as string,
      tuning: at === slot ? tuning : saved(slotKey(body, at), shippedFor(body, at)),
      lfos: at === slot
        ? Object.fromEntries(Object.entries(lfos).filter(([, l]) => l.on))
        : savedLfos(slotKey(body, at)),
      speech: at === slot ? speech : savedSpeech(slotKey(body, at)),
    }));
  if (baseline) {
    jobs.push({ at: "baseline", tuning: baseline.tuning, lfos: baseline.lfos, speech: {} });
  }
  try {
    for (const job of jobs) {
      const response = await fetch("/__bench-presets", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          body, slot: job.at, tuning: job.tuning, lfos: job.lfos, speech: job.speech,
          ...(label.trim() === "" ? {} : { label: label.trim() }),
        }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status} on ${job.at}`);
    }
    status.textContent = `saved everything — ${jobs.length} slots of ${body}`;
    status.className = "ok";
    void refreshHistory();
  } catch (error) {
    status.textContent = `SAVE FAILED — ${(error as Error).message}`;
    status.className = "bad";
  }
}

$("save").addEventListener("click", () => { void saveEverything(); });
$("saveState").addEventListener("click", () => { void savePreset(); });
$("history").addEventListener("change", (event) => {
  const select = event.target as HTMLSelectElement;
  const raw = select.value;
  const picked = select.selectedOptions[0]?.textContent ?? "";
  select.value = "";
  if (raw === "") return;
  const version = history[slotKey(body, slot)]?.versions[Number(raw)];
  if (!version) return;
  transit = null;
  // Straight into the dials rather than through saved(): a URL parameter for
  // this slot would otherwise shadow the version just chosen. localStorage is
  // updated like any edit; the file is untouched until the next save.
  tuning = { ...clone(shipped), ...version.tuning } as Tuning;
  lfos = { ...(version.lfos ?? {}) };
  speech = { ...(version.speech ?? {}) };
  buildControls();
  remember(slotKey(body, slot), tuning);
  rememberLfos();
  rememberSpeech();
  renderer?.transitionTo(clone(effectiveTuning()) as never);
  paintMixerLevels();
  paintMixer();
  paintDrift();
  $("saved").textContent = `loaded ${picked}`;
  $("saved").className = "ok";
});
$("voicePlay").addEventListener("click", () => {
  // A toggle, like any player: pause holds the clip, play resumes it, and a
  // fresh press with nothing loaded starts the selected clip — over standby.
  if (voice && !voice.el.paused) {
    voice.el.pause();
    return;
  }
  if (voice && voice.el.src !== "") {
    if (slot !== "standby") setState("standby");
    void voice.el.play().catch(voiceFail);
    return;
  }
  const pick = ($("clip") as HTMLSelectElement).value;
  void startVoice(pick).catch(voiceFail);
});
$("voiceStop").addEventListener("click", () => { void stopVoice(); });

/** Step through the clip list like a playlist. */
function stepClip(delta: number): void {
  const clips = $("clip") as HTMLSelectElement;
  if (clips.options.length === 0) return;
  clips.selectedIndex =
    (clips.selectedIndex + delta + clips.options.length) % clips.options.length;
  void startVoice(clips.value).catch(voiceFail);
}
$("voicePrev").addEventListener("click", () => stepClip(-1));
$("voiceNext").addEventListener("click", () => stepClip(1));

$("voiceLoop").addEventListener("click", () => {
  const box = $("loop") as HTMLInputElement;
  box.checked = !box.checked;
  if (voice) voice.el.loop = box.checked;
  $("voiceLoop").classList.toggle("on", box.checked);
});
$("voiceLoop").classList.toggle("on", ($("loop") as HTMLInputElement).checked);

const npSeek = $("npSeek") as HTMLInputElement;
npSeek.addEventListener("pointerdown", () => { seeking = true; });
npSeek.addEventListener("input", () => {
  const el = voice?.el;
  if (el && Number.isFinite(el.duration)) {
    $("npNow").textContent = fmtTime((Number(npSeek.value) / 1000) * el.duration);
  }
});
npSeek.addEventListener("change", () => {
  seeking = false;
  const el = voice?.el;
  if (el && Number.isFinite(el.duration) && el.duration > 0) {
    el.currentTime = (Number(npSeek.value) / 1000) * el.duration;
  }
});

$("level").addEventListener("input", () => {
  if (voice) voice.el.volume = Number(($("level") as HTMLInputElement).value);
});

/** A written line, rendered by pocket TTS on the M4 and played like a clip. */
async function speakText(): Promise<void> {
  const box = $("ttsText") as HTMLInputElement;
  const text = box.value.trim();
  if (text === "") return;
  const status = $("voiceState");
  status.textContent = "rendering speech…";
  status.className = "";
  ($("ttsGo") as HTMLButtonElement).disabled = true;
  try {
    const response = await fetch("/__bench-tts", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ body, text }),
    });
    if (!response.ok) {
      throw new Error((await response.text()).slice(0, 160) || `HTTP ${response.status}`);
    }
    const blob = await response.blob();
    lastTts = { blob, text };
    ($("ttsKeep") as HTMLButtonElement).disabled = false;
    const url = URL.createObjectURL(blob);
    const short = text.length > 46 ? `${text.slice(0, 46)}…` : text;
    await startVoice(url, `“${short}”`, "pocket TTS");
  } catch (error) {
    voiceFail(error as Error);
  } finally {
    ($("ttsGo") as HTMLButtonElement).disabled = false;
  }
}
$("ttsGo").addEventListener("click", () => { void speakText(); });
$("ttsText").addEventListener("keydown", (event) => {
  if (event.key === "Enter") void speakText();
});

/** The last rendered line, held so Keep can shelve it as a real clip. */
let lastTts: { blob: Blob; text: string } | null = null;

function addClipOption(src: string, select: boolean): void {
  const clips = $("clip") as HTMLSelectElement;
  if (!Array.from(clips.options).some((option) => option.value === src)) {
    const option = document.createElement("option");
    option.value = src;
    option.textContent = src.split("/").pop() ?? src;
    clips.appendChild(option);
  }
  if (select) clips.value = src;
}

/** Kept TTS lines for the body on stage, appended to the built-in clip list. */
async function loadKeptClips(): Promise<void> {
  try {
    const response = await fetch("/__bench-clips");
    if (!response.ok) return;
    const { clips } = await response.json() as { clips: string[] };
    for (const src of clips) {
      if (src.includes(`/tts-${body}-`)) addClipOption(src, false);
    }
  } catch { /* the dropdown just shows the built-ins */ }
}

async function keepTts(): Promise<void> {
  if (!lastTts) return;
  const suggestion = lastTts.text.toLowerCase()
    .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 32);
  const name = window.prompt("Name this line", suggestion);
  if (name === null || name.trim() === "") return;
  try {
    const response = await fetch(
      `/__bench-clips?body=${body}&name=${encodeURIComponent(name.trim())}`,
      { method: "POST", headers: { "content-type": "audio/wav" }, body: lastTts.blob },
    );
    if (!response.ok) {
      throw new Error((await response.text()).slice(0, 160) || `HTTP ${response.status}`);
    }
    const { url } = await response.json() as { url: string };
    addClipOption(url, true);
    $("voiceState").textContent = `kept — ${url.split("/").pop()}`;
    $("voiceState").className = "ok";
  } catch (error) {
    voiceFail(error as Error);
  }
}
$("ttsKeep").addEventListener("click", () => { void keepTts(); });

$("clipFile").addEventListener("change", (event) => {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (file) void startVoice(URL.createObjectURL(file), file.name, "your file").catch(voiceFail);
});
$("play").addEventListener("click", () => {
  // Releases the bench's pin, so the body eases from its arrival state to this
  // mode under its own logic. Touching any slider takes control back.
  renderer?.replay();
  $("saved").textContent = "drawing in…";
  $("saved").className = "ok";
});
$("reset").addEventListener("click", () => {
  // Clear the store BEFORE pushing, since push() writes it back.
  try {
    localStorage.removeItem(storageKey(slotKey(body, slot)));
    localStorage.removeItem(storageKey(`${slotKey(body, slot)}.lfo`));
  } catch { /* nothing to clear */ }
  lfos = {};
  tuning = clone(shipped);
  buildControls();
  push();
});
/**
 * Copy, on a page that has no clipboard API.
 *
 * `navigator.clipboard` EXISTS ONLY IN A SECURE CONTEXT, and this bench is served
 * over plain http on a LAN address -- so it is undefined here, the optional call did
 * nothing at all, and Copy settings silently failed while appearing to work. The old
 * code guarded with `?.`, which is what turned a diagnosable crash into no feedback.
 *
 * So: try execCommand against a real selection, fall back to the API if it somehow
 * exists, and either way leave the text on screen SELECTED -- the worst case is one
 * keystroke, not a dead button.
 */
function copyOut(text: string): void {
  const out = $("export");
  out.textContent = text;
  let done = false;
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    done = document.execCommand("copy");
    document.body.removeChild(area);
  } catch {
    done = false;
  }
  if (!done && typeof navigator.clipboard?.writeText === "function") {
    void navigator.clipboard.writeText(text).catch(() => undefined);
  }
  const range = document.createRange();
  range.selectNodeContents(out);
  const sel = window.getSelection();
  sel?.removeAllRanges();
  sel?.addRange(range);
  $("saved").textContent = done ? "copied to clipboard" : "selected below — press Cmd/Ctrl+C";
  $("saved").className = "ok";
}

$("link").addEventListener("click", () => { copyOut(shareLink()); });
$("copy").addEventListener("click", () => { copyOut(settingsText()); });
const params = new URLSearchParams(location.search);
const startMode = params.get("mode");
const startLevel = params.get("level");
if (startMode && (SLOTS as readonly string[]).includes(startMode)) {
  slot = startMode as Slot;
}
if (startLevel) ($("level") as HTMLInputElement).value = startLevel;
// A link naming a body should open on it. Checked in order and first match
// wins, because a link carries exactly one body's numbers.
for (const named of ["familiar", "ultron"] as const) {
  const keys = [...params.keys()];
  if (keys.some((k) => k.startsWith(`${named}.`))
      && !keys.some((k) => k.startsWith("jarvis."))) {
    body = named;
    ($("body") as HTMLSelectElement).value = named;
    break;
  }
}
/** Show only the dials that have left the baseline — the working set, when
 *  iterating a state up from the ground. */
let driftOnly = ((): boolean => {
  try {
    return localStorage.getItem(storageKey("driftOnly")) === "1";
  } catch {
    return false;
  }
})();

function paintDriftFilter(): void {
  const toggle = $("driftOnly");
  toggle.classList.toggle("on", driftOnly);
  for (const wrap of Array.from($("controls").querySelectorAll(".row")) as HTMLElement[]) {
    const field = wrap.dataset.field;
    if (!field) continue;
    const value = (tuning as unknown as Record<string, number | number[]>)[field];
    const width = typeof value === "number" ? 1 : value?.length ?? 0;
    let off = false;
    for (let index = 0; index < width; index += 1) {
      if (driftAt(field, index)) { off = true; break; }
    }
    wrap.style.display = driftOnly && !off ? "none" : "";
  }
}

$("driftOnly").addEventListener("click", () => {
  driftOnly = !driftOnly;
  try {
    localStorage.setItem(storageKey("driftOnly"), driftOnly ? "1" : "0");
  } catch { /* fine */ }
  paintDriftFilter();
});

/**
 * THE TRANSITION RECORDER. A transition is choreography between two states,
 * captured the way a looper captures music: arm record, move a dial, stop —
 * that is a take. Record again and the take plays back while you move another
 * THE RECORDER IS GONE; its takes remain. Transitions ease automatically now
 * (lerpTuning on the pace), and any journey already recorded into the store
 * still plays when its pair of states is travelled — these types and the two
 * functions below are the playback half of a machine whose authoring half
 * was deliberately removed.
 */
type Sample = { t: number; v: number | number[] };
type Tracks = Record<string, Sample[]>;

/** The take's value at phase p — hold before the first sample and after the
 *  last, linear between neighbours: the dial replays exactly as it was moved. */
function trackValueAt(samples: Sample[], p: number): number | number[] {
  if (samples.length === 0) return 0;
  if (p <= samples[0].t) return samples[0].v;
  const last = samples[samples.length - 1];
  if (p >= last.t) return last.v;
  for (let i = 1; i < samples.length; i += 1) {
    if (samples[i].t >= p) {
      const a = samples[i - 1];
      const b = samples[i];
      const span = b.t - a.t;
      const mix = span > 0 ? (p - a.t) / span : 1;
      if (typeof a.v === "number" && typeof b.v === "number") {
        return a.v + (b.v - a.v) * mix;
      }
      const av = a.v as number[];
      const bv = b.v as number[];
      return bv.map((v, index) =>
        typeof av[index] === "number" ? av[index] + (v - av[index]) * mix : v);
    }
  }
  return last.v;
}

/** Apply tracks over a base look, animating the rail so the dials move. */
function applyTracks(base: Tuning, tracks: Tracks, p: number, skip?: Set<string>): Tuning {
  const out = clone(base);
  const record = out as unknown as Record<string, number | number[]>;
  for (const [field, samples] of Object.entries(tracks)) {
    if (skip?.has(field)) continue;
    if (record[field] === undefined) continue;
    const value = trackValueAt(samples, p);
    record[field] = value;
    const parts = typeof value === "number" ? [value] : value;
    parts.forEach((part, index) => {
      const dom = sliderDom[lfoKey(field, index)];
      if (dom) {
        dom.input.value = String(part);
        dom.out.textContent = part.toFixed(3);
      }
    });
  }
  return out;
}


/**
 * A/B AGAINST THE GROUND. Hold the button (or the B key) to hear the baseline;
 * release to fall back to your edit. A reference you can flash mid-judgement
 * is the difference between "I think it moved" and knowing.
 */
let abActive = false;

function abBaseline(on: boolean): void {
  if (!baseline || !renderer || on === abActive) return;
  abActive = on;
  if (on) {
    (renderer as { setTuning(next: never): void }).setTuning(clone(baseline.tuning) as never);
    $("saved").textContent = "A/B — showing baseline";
    $("saved").className = "ok";
  } else {
    push();
    $("saved").textContent = "";
  }
}

for (const [down, up] of [["mousedown", "mouseup"], ["touchstart", "touchend"]] as const) {
  $("abHold").addEventListener(down, (event) => {
    event.preventDefault();
    abBaseline(true);
  });
  $("abHold").addEventListener(up, () => abBaseline(false));
}
$("abHold").addEventListener("mouseleave", () => abBaseline(false));
document.addEventListener("keyup", (event) => {
  if (event.key.toLowerCase() === "b") abBaseline(false);
});

/** 1–6 play the states like keys, skipped while typing in any control. */
document.addEventListener("keydown", (event) => {
  const at = event.target as HTMLElement;
  if (at.tagName === "INPUT" || at.tagName === "SELECT" || at.tagName === "TEXTAREA") return;
  if (event.key.toLowerCase() === "b" && !event.repeat) {
    abBaseline(true);
    return;
  }
  const index = Number(event.key) - 1;
  if (!Number.isInteger(index) || index < 0) return;
  const available = transportSlots();
  if (index < available.length) setState(available[index]);
});

/** Framing mode: fold the desk away, keep presence at hand. */
let deskHidden = ((): boolean => {
  try {
    return localStorage.getItem(storageKey("deskHidden")) === "1";
  } catch {
    return false;
  }
})();

function paintDesk(): void {
  document.body.classList.toggle("desk-hidden", deskHidden);
  $("deskToggle").classList.toggle("on", deskHidden);
}

$("deskToggle").addEventListener("click", () => {
  deskHidden = !deskHidden;
  try {
    localStorage.setItem(storageKey("deskHidden"), deskHidden ? "1" : "0");
  } catch { /* fine */ }
  paintDesk();
});
paintDesk();

/** The console's physical size, dragged from the grip above the transport.
 *  Dragging DOWN shrinks the desk — transport, mixer and bus all move down
 *  and the stage takes the height; dragging up grows it again. */
let deskScale = ((): number => {
  try {
    const raw = Number(localStorage.getItem(storageKey("deskScale")));
    return Number.isFinite(raw) && raw >= 0.35 && raw <= 2.4 ? raw : 1;
  } catch {
    return 1;
  }
})();

function paintDeskScale(): void {
  document.documentElement.style.setProperty("--deskScale", String(deskScale));
}

$("splitter").addEventListener("pointerdown", (event) => {
  event.preventDefault();
  const startY = event.clientY;
  const from = deskScale;
  const move = (e: PointerEvent): void => {
    deskScale = Math.min(2.4, Math.max(0.35, from - (e.clientY - startY) / 110));
    paintDeskScale();
  };
  const up = (): void => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    try {
      localStorage.setItem(storageKey("deskScale"), String(deskScale));
    } catch { /* fine */ }
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
});
paintDeskScale();

$("presenceQuick").addEventListener("input", () => {
  const value = Number(($("presenceQuick") as HTMLInputElement).value);
  assign("presence", value);
  $("presenceOut").textContent = value.toFixed(3);
  push();
});

/**
 * PRESENCE'S GRANULAR CONTROLS, topbar edition. Its desk strip went — size is
 * framing, not a channel — but the strip had carried the sweep, the speech
 * reach and the typed value, and those must not go with it.
 */
function registerPresenceDom(): void {
  sliderDom[lfoKey("presence", 0)] = {
    input: $("presenceQuick") as HTMLInputElement,
    out: $("presenceOut"),
  };
}

function paintPresenceCtl(): void {
  const on = lfos[lfoKey("presence", 0)]?.on === true;
  $("presenceOsc").classList.toggle("on", on);
  ($("presenceQuick") as HTMLInputElement).disabled = on;
  const id = lfoKey("presence", 0);
  $("presenceReach").classList.toggle("arm", reachArming?.id === id);
  $("presenceReach").classList.toggle("on", reachArming?.id !== id && speech[id] !== undefined);
}

$("presenceOsc").addEventListener("click", () => {
  const id = lfoKey("presence", 0);
  const [min, max] = RANGE.presence ?? [0.4, 1.8, 0.005];
  const at = (tuning as unknown as Record<string, number>).presence ?? 1;
  const existing = lfos[id];
  if (existing?.on) {
    lfos[id] = { ...existing, on: false };
  } else {
    const span = (max - min) * 0.25;
    lfos[id] = existing ? { ...existing, on: true } : {
      on: true, rate: 0.15,
      min: Math.max(min, at - span), max: Math.min(max, at + span), phase: 0,
    };
  }
  rememberLfos();
  paintPresenceCtl();
});

$("presenceReach").addEventListener("click", (event) => {
  const id = lfoKey("presence", 0);
  const pq = $("presenceQuick") as HTMLInputElement;
  if ((event as MouseEvent).shiftKey) {
    delete speech[id];
    if (reachArming?.id === id) reachArming = null;
    rememberSpeech();
    paintPresenceCtl();
    return;
  }
  const at = (tuning as unknown as Record<string, number>).presence ?? 1;
  if (reachArming?.id === id) {
    speech[id] = at;
    const from = reachArming.from;
    reachArming = null;
    assign("presence", from);
    pq.value = String(from);
    $("presenceOut").textContent = from.toFixed(3);
    push();
    rememberSpeech();
    paintPresenceCtl();
    return;
  }
  reachArming = { id, from: at };
  paintPresenceCtl();
});

$("presenceOut").addEventListener("click", () => {
  const out = $("presenceOut");
  if (out.querySelector("input")) return;
  const pq = $("presenceQuick") as HTMLInputElement;
  const was = Number(pq.value);
  const field = document.createElement("input");
  field.type = "number";
  field.step = "0.005";
  field.value = was.toFixed(3);
  field.style.width = "58px";
  field.style.height = "20px";
  field.style.font = "inherit";
  out.textContent = "";
  out.appendChild(field);
  field.focus();
  field.select();
  let settled = false;
  const done = (commit: boolean) => {
    if (settled) return;
    settled = true;
    const typed = Number(field.value);
    field.remove();
    const next = commit && Number.isFinite(typed)
      ? Math.min(1.8, Math.max(0.4, typed))
      : was;
    pq.value = String(next);
    out.textContent = next.toFixed(3);
    if (next !== was) {
      assign("presence", next);
      push();
    }
  };
  field.addEventListener("keydown", (event) => {
    if (event.key === "Enter") done(true);
    if (event.key === "Escape") done(false);
    event.stopPropagation();
  });
  field.addEventListener("blur", () => done(true));
});
registerPresenceDom();
paintPresenceCtl();

$("gear").addEventListener("click", () => $("modal").classList.add("open"));
$("modalClose").addEventListener("click", () => $("modal").classList.remove("open"));
$("modal").addEventListener("click", (event) => {
  if (event.target === $("modal")) $("modal").classList.remove("open");
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") $("modal").classList.remove("open");
});
buildEmotions();
$("export").textContent = "";
mount();
void refreshHistory();
