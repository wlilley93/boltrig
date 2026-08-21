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

function saved(name: string, shipped: Tuning): Tuning {
  const fromUrl = new URLSearchParams(location.search).get(name);
  const raw = fromUrl ?? localStorage.getItem(storageKey(name));
  if (!raw) return clone(shipped);
  try {
    return { ...clone(shipped), ...JSON.parse(raw) } as Tuning;
  } catch {
    return clone(shipped);
  }
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
  if (!raw) return {};
  try {
    return JSON.parse(raw) as LfoMap;
  } catch {
    return {};
  }
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
  const available = slotsFor(body);
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

  shipped = shippedFor(body, slot);
  tuning = saved(slotKey(body, slot), shipped);
  // Rebuilt per body: an LFO bound to `linkGain` means nothing on Ultron.
  for (const id of Object.keys(sliderDom)) delete sliderDom[id];
  lfos = savedLfos(slotKey(body, slot));
  loadBaseline();
  loadDraft();
  buildControls();
  buildMixer();
  paintTransTo();
  paintTransChoose();
  paintRec();
  transStatus(draft ? `draft: ${Object.keys(draft.tracks).length} track(s) from ${draft.from}` : "");
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

  // ONE CHANNEL AT A TIME. The rail used to stack every group and rely on
  // collapsing; the desk below is now the index, so the rail is the selected
  // channel's effects and nothing else. Nothing is hidden: every field belongs
  // to a strip, orphans get a warning strip of their own.
  const head = document.createElement("h3");
  head.className = active.title.startsWith("UNGROUPED") ? "group warn" : "group";
  head.textContent = active.title;
  panel.appendChild(head);
  for (const key of active.fields) add(key);
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
  { title: "2 · Glyph layers — the inscriptions", fields: [
    "glyphGain", "glyphRadius", "glyphSize", "glyphSpin", "glyphDensity",
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
  { title: "0 · Lattice loop — the baked layer", fields: ["lattice"] },
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
  glyphGain: "How bright the inscriptions are",
  glyphRadius: "Where the glyph layers sit",
  glyphSize: "How big each mark is",
  glyphSpin: "How fast the layers turn",
  glyphDensity: "How many marks are lit, and how uneven",
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
  const title = document.createElement("strong");
  title.textContent = TITLES[key] ?? `${label} — UNTITLED`;
  name.appendChild(title);
  const code = document.createElement("span");
  code.className = "code";
  code.textContent = `${label} · ${named.join(" / ")}`;
  name.appendChild(code);
  wrap.appendChild(name);
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
    wrap.appendChild(input);
    wrap.appendChild(out);
    wrap.appendChild(bind);

    const panel = lfoPanel(key, index, live, min, max, onChange);
    wrap.appendChild(panel);
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

async function startVoice(src: string): Promise<void> {
  await stopVoice();
  const el = new Audio(src);
  el.loop = ($("loop") as HTMLInputElement).checked;
  el.crossOrigin = "anonymous";
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
  $("voiceState").textContent = `playing ${src.split("/").pop()}`;
  $("voiceState").className = "ok";
}

async function stopVoice(): Promise<void> {
  if (!voice) return;
  voice.el.pause();
  voice.el.src = "";
  await voice.ctx.close().catch(() => undefined);
  voice = null;
  $("voiceState").textContent = "";
  $("voiceState").className = "";
}

/** The clips for a body, by convention rather than by a list to keep in step. */
function clipsFor(which: string): string[] {
  return [1, 2, 3].map((n) => `/companion/${which}-${n}.wav`);
}

function assign(key: string, value: number | number[]): void {
  // The recorder taps every dial here — rail sliders and desk faders alike.
  if (recState === "armed") {
    recClock = performance.now();
    recState = "recording";
    transStatus("recording…");
    paintRec();
  }
  if (recState === "recording" || recState === "overdub") {
    const now = performance.now();
    const at = recState === "recording"
      ? now - recClock
      : (draft ? ((now - recClock) % draft.duration) / draft.duration : 0);
    if (!takeTouched.has(key)) {
      takeTouched.add(key);
      const prev = (tuning as unknown as Record<string, number | number[]>)[key];
      // The dial's resting value holds from the start of the take until the
      // first movement — without this seed the journey would begin mid-air.
      takeTracks[key] = [{ t: recState === "recording" ? 0 : Math.max(0, at - 0.001), v: clone({ v: prev }).v }];
    }
    takeTracks[key].push({ t: at, v: clone({ v: value }).v });
  }
  (tuning as unknown as Record<string, unknown>)[key] = value;
}

function push(): void {
  if (!renderer) return;
  if (recState === "idle") remember(slotKey(body, slot), tuning);
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
  } else if (looping && renderer) {
    // LOOP PREVIEW: journey, hold at the destination, go again. The base is
    // the live tuning, so dials keep answering while the loop plays.
    const hold = looping.dest ? 700 : 0;
    const cycle = (performance.now() - looping.start) % (looping.duration + hold);
    const at = Math.min(1, cycle / looping.duration);
    const eased = 0.5 - 0.5 * Math.cos(Math.PI * at);
    const base = looping.dest ? lerpTuning(tuning, looping.dest, eased) : tuning;
    (renderer as { setTuning(next: never): void })
      .setTuning(effectiveTuning(applyTracks(base, looping.tracks, at)) as never);
  } else if (recState === "overdub" && draft && renderer) {
    // The existing tracks replay on a loop while new dial moves record on top;
    // a field being re-recorded stops replaying the moment it is touched.
    const at = ((performance.now() - recClock) % draft.duration) / draft.duration;
    (renderer as { setTuning(next: never): void })
      .setTuning(effectiveTuning(applyTracks(tuning, draft.tracks, at, takeTouched)) as never);
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
const HIDDEN_FIELDS = new Set(["linkGain", "linkBow", "linkRange", "linkLimb"]);
let channel = "";
const muted = new Set<string>();
let soloed: string | null = null;
const mixerDom: Record<string, { input: HTMLInputElement; out: HTMLElement }> = {};

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
  return present;
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
const MUTE_EXTRA = new Set(["core", "eye", "starburst", "reverb", "voiceLevel"]);
function muteFields(fields: readonly string[]): string[] {
  return fields.filter((f) => f.endsWith("Gain") || MUTE_EXTRA.has(f));
}

function audible(title: string): boolean {
  return soloed !== null ? title === soloed : !muted.has(title);
}

/** The tuning the renderer hears: muted channels' levels at zero, the real
 *  numbers untouched. With nothing muted this is `tuning` itself. */
function effectiveTuning(of: Tuning = tuning): Tuning {
  if (muted.size === 0 && soloed === null) return of;
  const out = clone(of);
  const record = out as unknown as Record<string, number | number[]>;
  for (const g of channelsFor()) {
    if (audible(g.title)) continue;
    for (const field of muteFields(g.fields)) {
      const value = record[field];
      record[field] = typeof value === "number" ? 0 : value.map(() => 0);
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
    name.textContent = channelShortName(g.title);
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
    const level = levelFields(g.fields)[0] ?? g.fields[0];
    if (level !== undefined) {
      const record = tuning as unknown as Record<string, number | number[]>;
      const current = record[level];
      const at = typeof current === "number" ? current : current[0];
      const [min, max, step] = RANGE[level] ?? [0, 1, 0.005];
      const fader = document.createElement("input");
      fader.type = "range";
      fader.className = "fader";
      fader.min = String(min);
      fader.max = String(max);
      fader.step = String(step);
      fader.value = String(at);
      fader.title = TITLES[level] ?? level;
      const out = document.createElement("b");
      out.textContent = at.toFixed(3);
      fader.addEventListener("input", () => {
        const live = tuning as unknown as Record<string, number | number[]>;
        const value = live[level];
        const next = Number(fader.value);
        assign(level, typeof value === "number"
          ? next
          : [next, ...(value as number[]).slice(1)]);
        out.textContent = next.toFixed(3);
        // The rail's slider for the same value follows, if it is on show.
        const rail = sliderDom[lfoKey(level, 0)];
        if (rail) {
          rail.input.value = fader.value;
          rail.out.textContent = next.toFixed(3);
        }
        push();
      });
      // The fader must not also select the channel mid-drag.
      fader.addEventListener("click", (event) => event.stopPropagation());
      mixerDom[level] = { input: fader, out };
      strip.appendChild(fader);
      strip.appendChild(out);
      const ms = document.createElement("div");
      ms.className = "ms";
      const mute = document.createElement("button");
      mute.type = "button";
      mute.textContent = "M";
      mute.title = "Mute — silence this channel in the renderer; the numbers are untouched";
      mute.addEventListener("click", (event) => {
        event.stopPropagation();
        if (muted.has(g.title)) muted.delete(g.title);
        else muted.add(g.title);
        paintMixer();
        push();
      });
      const solo = document.createElement("button");
      solo.type = "button";
      solo.textContent = "S";
      solo.title = "Solo — silence every other channel";
      solo.addEventListener("click", (event) => {
        event.stopPropagation();
        soloed = soloed === g.title ? null : g.title;
        paintMixer();
        push();
      });
      ms.appendChild(mute);
      ms.appendChild(solo);
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
    strip.querySelector(".chlamp")?.classList.toggle("on", swept);
    const off = driftCount(fields);
    const badge = strip.querySelector(".chdrift");
    if (badge) badge.textContent = off > 0 ? `Δ${off}` : "";
    const [mute, solo] = Array.from(strip.querySelectorAll(".ms button"));
    mute?.classList.toggle("on", muted.has(title));
    solo?.classList.toggle("on", soloed === title);
  }
}

/** The faders follow the numbers, wherever the numbers were changed. */
function paintMixerLevels(): void {
  const record = tuning as unknown as Record<string, number | number[]>;
  for (const [field, dom] of Object.entries(mixerDom)) {
    const value = record[field];
    const at = typeof value === "number" ? value : value?.[0];
    if (typeof at !== "number") continue;
    dom.input.value = String(at);
    dom.out.textContent = at.toFixed(3);
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
  const states = slotsFor(body).filter((at) => at !== "arrival" && at !== "error");
  const sure = window.confirm(
    `Copy the ${slot} look of ${body} to ${states.join(", ")}, and make it the baseline every state is measured from?`,
  );
  if (!sure) return;
  baseline = { tuning: clone(tuning), lfos: { ...lfos } };
  try {
    localStorage.setItem(storageKey(`baseline.${body}`), JSON.stringify(baseline));
    for (const at of states) {
      // The look AND its motion: a state is animated, so the oscillators are
      // part of the ground, not an accessory left behind.
      localStorage.setItem(storageKey(slotKey(body, at)), JSON.stringify(baseline.tuning));
      localStorage.setItem(storageKey(`${slotKey(body, at)}.lfo`), JSON.stringify(baseline.lfos));
    }
  } catch { /* a blocked store is not a reason to stop rendering */ }
  // And to the FILE, so the ground survives this browser. Fire-and-report:
  // a failed write says so in the status line rather than pretending.
  void fetch("/__bench-presets", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      body,
      slot: "baseline",
      tuning: baseline.tuning,
      lfos: baseline.lfos,
      label: `baseline from ${slot}`,
    }),
  }).then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    $("saved").textContent = `baseline set from ${slot} — applied to ${states.length} states, saved to file`;
    $("saved").className = "ok";
    void refreshHistory();
  }).catch((error: Error) => {
    $("saved").textContent = `baseline applied locally, FILE SAVE FAILED — ${error.message}`;
    $("saved").className = "bad";
  });
  lfos = { ...baseline.lfos };
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
  tuning: Partial<Tuning>; lfos?: LfoMap; savedAt?: string; label?: string;
};
let history: Record<string, { versions: SavedVersion[] }> = {};

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
  paintHistory();
  loadBaseline();
  paintDrift();
  paintTransChoose();
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
  if (recState !== "idle") finishTake("recording cancelled — state changed");
  if (looping) stopLoop();
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
  buildControls();
  remember(slotKey(body, slot), tuning);
  paintStates();
  paintMixerLevels();
  paintMixer();
  paintHistory();
  paintDrift();
  paintTransChoose();
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
$("save").addEventListener("click", () => { void savePreset(); });
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
  buildControls();
  remember(slotKey(body, slot), tuning);
  rememberLfos();
  renderer?.transitionTo(clone(effectiveTuning()) as never);
  paintMixerLevels();
  paintMixer();
  paintDrift();
  $("saved").textContent = `loaded ${picked}`;
  $("saved").className = "ok";
});
$("voicePlay").addEventListener("click", () => {
  const pick = ($("clip") as HTMLSelectElement).value;
  void startVoice(pick).catch((error: Error) => {
    // Autoplay refusals and decode failures both land here, and both look like
    // "the bands are dead" if swallowed.
    $("voiceState").textContent = `AUDIO FAILED — ${error.message}`;
    $("voiceState").className = "bad";
  });
});
$("voiceStop").addEventListener("click", () => { void stopVoice(); });
$("loop").addEventListener("change", () => {
  if (voice) voice.el.loop = ($("loop") as HTMLInputElement).checked;
});
$("clipFile").addEventListener("change", (event) => {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (file) void startVoice(URL.createObjectURL(file));
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
 * dial on top; layer until the journey is complete, then bind it to a
 * destination. Saving writes the take to the file AND commits the end values
 * into the destination state, so arriving there IS the look you built toward
 * — and marks the pair as a legal transition the state buttons will play.
 */
type Sample = { t: number; v: number | number[] };
type Tracks = Record<string, Sample[]>;
let recState: "idle" | "armed" | "recording" | "overdub" = "idle";
let recClock = 0;
let takeTracks: Tracks = {};
const takeTouched = new Set<string>();
let preTake: Tuning | null = null;
let draft: { from: Slot; duration: number; tracks: Tracks } | null = null;
let looping: { tracks: Tracks; duration: number; dest: Tuning | null; start: number } | null = null;

function draftKey(): string {
  return storageKey(`transitdraft.${body}`);
}
function saveDraft(): void {
  try {
    if (draft) localStorage.setItem(draftKey(), JSON.stringify(draft));
    else localStorage.removeItem(draftKey());
  } catch { /* fine */ }
}
function loadDraft(): void {
  try {
    const raw = localStorage.getItem(draftKey());
    draft = raw ? JSON.parse(raw) as typeof draft : null;
  } catch {
    draft = null;
  }
}

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

function transStatus(text: string): void {
  $("transStatus").textContent = text;
}

function paintRec(): void {
  const rec = $("rec");
  rec.classList.toggle("armed", recState === "armed");
  rec.classList.toggle("live", recState === "recording" || recState === "overdub");
  $("transSave").style.display = draft ? "" : "none";
  $("transTo").style.display = draft ? "" : "none";
  $("transLoop").classList.toggle("on", looping !== null);
}

function paintTransTo(): void {
  const select = $("transTo") as HTMLSelectElement;
  const keep = select.value;
  select.innerHTML = "";
  const head = document.createElement("option");
  head.value = "";
  head.textContent = "→ destination…";
  select.appendChild(head);
  if (!draft) return;
  for (const at of slotsFor(body)) {
    if (at === "arrival" || at === "error" || at === draft.from) continue;
    const option = document.createElement("option");
    option.value = at;
    option.textContent = `→ ${at}`;
    option.selected = at === keep;
    select.appendChild(option);
  }
}

/** Saved transitions leaving the state on stage, for the loop preview. */
function transitionsFrom(at: Slot): string[] {
  return Object.keys(history)
    .filter((key) => key.startsWith(`${body}.${at}->`));
}

function paintTransChoose(): void {
  const select = $("transChoose") as HTMLSelectElement;
  const keep = select.value;
  const from = transitionsFrom(slot);
  select.innerHTML = "";
  for (const key of from) {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = `⟳ ${key.slice(body.length + 1)}`;
    option.selected = key === keep;
    select.appendChild(option);
  }
  select.style.display = from.length > 0 ? "" : "none";
}

function stopLoop(): void {
  looping = null;
  paintRec();
  push();
}

$("rec").addEventListener("click", () => {
  if (recState === "armed") {
    recState = "idle";
    preTake = null;
    transStatus(draft ? `draft: ${Object.keys(draft.tracks).length} tracks` : "");
    paintRec();
    return;
  }
  if (recState === "recording") {
    // End of take one. Time ran from the first dial move to this click.
    const duration = Math.max(400, performance.now() - recClock);
    for (const samples of Object.values(takeTracks)) {
      for (const sample of samples) sample.t = Math.min(1, Math.max(0, sample.t / duration));
      samples.sort((a, b) => a.t - b.t);
    }
    draft = { from: slot, duration, tracks: takeTracks };
    saveDraft();
    finishTake(`take saved — ${Object.keys(takeTracks).length} track(s), ${(duration / 1000).toFixed(1)}s. Choose a destination, or record again to layer.`);
    return;
  }
  if (recState === "overdub") {
    for (const [field, samples] of Object.entries(takeTracks)) {
      samples.sort((a, b) => a.t - b.t);
      if (draft) draft.tracks[field] = samples;
    }
    saveDraft();
    finishTake(`layered — now ${draft ? Object.keys(draft.tracks).length : 0} track(s)`);
    return;
  }
  // Idle. Arm a first take, or roll an overdub pass over the draft.
  if (recState === "idle" && draft && draft.from === slot) {
    preTake = clone(tuning);
    takeTracks = {};
    takeTouched.clear();
    recClock = performance.now();
    recState = "overdub";
    transStatus("overdubbing — existing tracks play, move a dial to layer");
    paintRec();
    return;
  }
  preTake = clone(tuning);
  takeTracks = {};
  takeTouched.clear();
  recState = "armed";
  transStatus("record armed — move a dial to start the take");
  paintRec();
});

function finishTake(message: string): void {
  recState = "idle";
  if (preTake) {
    // The origin look is restored: a transition is choreography, and
    // recording one must not quietly rewrite the state it leaves from.
    tuning = preTake;
    preTake = null;
    buildControls();
    push();
  }
  transStatus(message);
  paintTransTo();
  paintRec();
}

$("transSave").addEventListener("click", () => {
  const to = ($("transTo") as HTMLSelectElement).value as Slot | "";
  if (!draft || to === "") {
    transStatus("choose a destination first");
    return;
  }
  const from = draft.from;
  const origin = saved(slotKey(body, from), shippedFor(body, from));
  // The arrival: the origin look with every track at its final value. This is
  // the whole point of the layering — the end of the journey IS the next state.
  const arrival = applyTracks(origin, draft.tracks, 1);
  const label = `${Object.keys(draft.tracks).length} tracks, ${(draft.duration / 1000).toFixed(1)}s`;
  void fetch("/__bench-presets", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ body, slot: from, to, tracks: draft.tracks, duration: draft.duration, label }),
  }).then(async (response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    try {
      localStorage.setItem(storageKey(slotKey(body, to)), JSON.stringify(arrival));
    } catch { /* fine */ }
    await fetch("/__bench-presets", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ body, slot: to, tuning: arrival, lfos: {}, label: `arrival via ${from}->${to}` }),
    });
    draft = null;
    saveDraft();
    paintTransTo();
    paintRec();
    transStatus(`saved ${from}->${to} — arrival committed into ${to}`);
    void refreshHistory();
  }).catch((error: Error) => {
    transStatus(`SAVE FAILED — ${error.message}`);
  });
});

$("transLoop").addEventListener("click", () => {
  if (looping) {
    stopLoop();
    transStatus(draft ? `draft: ${Object.keys(draft.tracks).length} tracks` : "");
    return;
  }
  if (draft && draft.from === slot) {
    looping = { tracks: draft.tracks, duration: draft.duration, dest: null, start: performance.now() };
    transStatus("looping the draft — dials stay live");
    paintRec();
    return;
  }
  const key = ($("transChoose") as HTMLSelectElement).value;
  const versions = history[key]?.versions ?? [];
  const newest = versions[versions.length - 1] as unknown as
    { tracks?: Tracks; duration?: number } | undefined;
  if (!newest?.tracks) {
    transStatus("no transition to loop from this state");
    return;
  }
  const destSlot = key.slice(key.indexOf("->") + 2) as Slot;
  looping = {
    tracks: newest.tracks,
    duration: newest.duration || 1200,
    dest: saved(slotKey(body, destSlot), shippedFor(body, destSlot)),
    start: performance.now(),
  };
  transStatus(`looping ${key.slice(body.length + 1)} — dials stay live`);
  paintRec();
});

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
  const available = slotsFor(body);
  if (index < available.length) setState(available[index]);
});

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
