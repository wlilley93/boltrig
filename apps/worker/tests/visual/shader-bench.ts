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
  JARVIS_TUNING,
  ULTRON_TUNING,
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
  JARVIS_ARRIVAL,
  ULTRON_ARRIVAL,
  jarvisModeTuning,
  ultronModeTuning,
} from "../../src/components/canvas/bodyPresets";
import { JarvisNeuralRenderer } from "../../src/components/jarvis/v2/JarvisNeuralRenderer";
import { UltronRenderer } from "../../src/components/ultron/UltronRenderer";

type Tuning = JarvisTuning | UltronTuning;
type Mode = "standby" | "listening" | "thinking" | "working" | "speaking";

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
type Slot = "arrival" | BodyMode;
const SLOTS: readonly Slot[] = ["arrival", ...BODY_MODES];
let slot: Slot = "standby";

/** The shipped numbers for a body and slot, before any local edit. */
function shippedFor(which: "jarvis" | "ultron", at: Slot): Tuning {
  if (at === "arrival") return which === "jarvis" ? JARVIS_ARRIVAL : ULTRON_ARRIVAL;
  return which === "jarvis" ? jarvisModeTuning(at) : ultronModeTuning(at);
}

/**
 * The render mode for a slot.
 *
 * Arrival has no render mode of its own -- it is a starting position, not a state
 * the body sits in -- so it is shown against standby, which is the quietest
 * backdrop and therefore the one that hides the least.
 */
function renderMode(at: Slot): BodyMode {
  return at === "arrival" ? "standby" : at;
}

/** Storage and save key. Per body AND slot: six presets, six sets of numbers. */
const slotKey = (which: string, at: Slot): string => `${which}.${at}`;

let renderer: JarvisNeuralRenderer | UltronRenderer | null = null;
/** Whether the arrival has already been shown this page load. */
let introPlayed = false;
let tuning: Tuning = clone(JARVIS_TUNING);
let shipped: Tuning = JARVIS_TUNING;
let body: "jarvis" | "ultron" = "jarvis";
let raf = 0;
let frames = 0;

function clone<T extends Tuning>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
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
  renderer = body === "jarvis"
    ? new JarvisNeuralRenderer({ maxDevicePixelRatio: 1 })
    : new UltronRenderer({ maxDevicePixelRatio: 1 });
  renderer.mount(host);
  const status = renderer.status();
  if (status.state !== "running") {
    $("readout").textContent = `FAILED — ${status.reason ?? status.state}`;
    return;
  }
  pheno = savedPheno();
  // The measured mood, not null. Passing null meant the bench always showed a
  // resting body, so the registers were unfalsifiable by eye.
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
  buildControls();
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

function savedPheno(): BodyPhenotype {
  try {
    const raw = localStorage.getItem(storageKey("pheno"));
    if (!raw) return { ...RESTING_PHENOTYPE };
    // Merged OVER resting, so a scalar added later loads as its resting value
    // rather than as undefined -- which would turn every product into NaN.
    return { ...RESTING_PHENOTYPE, ...JSON.parse(raw) as Partial<BodyPhenotype> };
  } catch {
    return { ...RESTING_PHENOTYPE };
  }
}

/** The register sliders, appended under their own collapsible heading. */
function buildPhenotype(panel: HTMLElement): void {
  const head = document.createElement("h3");
  head.className = "group";
  head.textContent = "7 · Emotion registers — mood and colour";
  panel.appendChild(head);
  const rows: HTMLElement[] = [];
  for (const scalar of PHENOTYPE_SCALARS) {
    const before = panel.childElementCount;
    panel.appendChild(row(
      `pheno.${scalar}`,
      // The full key, not the bare scalar: TITLES and LEGEND are keyed by it, and a
      // register showing only "attention" is indistinguishable from a tuning field
      // that happened to be called the same thing.
      `pheno.${scalar}`,
      [pheno[scalar]],
      (next) => {
        pheno = { ...pheno, [scalar]: next[0] };
        rememberPheno();
        renderer?.applyPhenotype(pheno as unknown as Record<string, unknown>);
      },
    ));
    for (let i = before; i < panel.childElementCount; i += 1) {
      rows.push(panel.children[i] as HTMLElement);
    }
  }
  const paint = () => {
    const shut = collapsed.has("pheno");
    head.classList.toggle("shut", shut);
    for (const r of rows) r.style.display = shut ? "none" : "";
  };
  head.addEventListener("click", () => {
    if (collapsed.has("pheno")) collapsed.delete("pheno");
    else collapsed.add("pheno");
    try {
      localStorage.setItem(storageKey("collapsed"), JSON.stringify([...collapsed]));
    } catch { /* nothing to persist to */ }
    paint();
  });
  paint();
}

function buildControls(): void {
  const panel = $("controls");
  panel.innerHTML = "";
  const fields = Object.keys(tuning);
  const placed = new Set<string>();

  const add = (key: string) => {
    const value = (tuning as unknown as Record<string, number | number[]>)[key];
    if (typeof value === "number") {
      panel.appendChild(row(key, key, [value], (next) => assign(key, next[0])));
    } else {
      panel.appendChild(row(key, key, value, (next) => assign(key, next)));
    }
  };

  for (const group of GROUPS) {
    const mine = group.fields.filter((f) => fields.includes(f));
    if (mine.length === 0) continue;
    const head = document.createElement("h3");
    head.className = "group";
    head.textContent = group.title;
    panel.appendChild(head);
    // COLLAPSIBLE, and collapsed state is remembered. Nine groups of controls is
    // more than fits on a screen, so working on the wheels means scrolling past
    // the dendrites every time -- and the scroll position is lost on every remount.
    const rows: HTMLElement[] = [];
    for (const key of mine) {
      const before = panel.childElementCount;
      add(key);
      placed.add(key);
      for (let i = before; i < panel.childElementCount; i += 1) {
        rows.push(panel.children[i] as HTMLElement);
      }
    }
    const paintGroup = () => {
      const shut = collapsed.has(group.title);
      head.classList.toggle("shut", shut);
      for (const r of rows) r.style.display = shut ? "none" : "";
    };
    head.addEventListener("click", () => {
      if (collapsed.has(group.title)) collapsed.delete(group.title);
      else collapsed.add(group.title);
      try {
        localStorage.setItem(storageKey("collapsed"), JSON.stringify([...collapsed]));
      } catch { /* a blocked store is not a reason to stop rendering */ }
      paintGroup();
    });
    paintGroup();
  }

  // Nothing is hidden. A field in no group still appears, because a panel you
  // cannot trust to show everything is worse than an untidy one -- silently
  // dropping one would make a control vanish the moment a field is renamed.
  const orphans = fields.filter((f) => !placed.has(f));
  if (orphans.length > 0) {
    const head = document.createElement("h3");
    head.className = "group warn";
    head.textContent = "UNGROUPED — add these to GROUPS";
    panel.appendChild(head);
    for (const key of orphans) add(key);
  }

  buildPhenotype(panel);
}

/**
 * WHICH DRAW EACH FIELD BELONGS TO, in the order the passes actually run.
 *
 * The panel was one flat run of twenty-odd rows in struct order -- the order a
 * TypeScript interface happens to be written in, which has nothing to do with what
 * you are looking at. Grouping by PASS puts the controls for the thing you are
 * staring at together, and numbering them makes the render order legible.
 */
/** Which groups are shut, remembered across reloads. */
const collapsed = new Set<string>((() => {
  try {
    return JSON.parse(localStorage.getItem(storageKey("collapsed")) ?? "[]") as string[];
  } catch {
    return [];
  }
})());

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
  { title: "3 · Neural pathways — superseded by the iris", fields: [
    "linkGain", "linkBow", "linkRange", "linkLimb",
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
  { title: "5 · Crystal facets", fields: [
    "facetGain", "facetSize", "facetSpin", "facetLimb",
  ] },
  { title: "6 · The eye — core and composite", fields: [
    "core", "eye", "starburst", "petal", "cloud",
  ] },
  { title: "6 · Voice reverberation — how speech crosses the body", fields: [
    "reverb",
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
    (renderer as { setTuning(next: never): void }).setTuning(clone(tuning) as never);
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
  (tuning as unknown as Record<string, unknown>)[key] = value;
}

function push(): void {
  if (!renderer) return;
  remember(slotKey(body, slot), tuning);
  // Cast at the seam: the page holds one union and each renderer takes its own
  // half of it, which the body switch above already guarantees.
  (renderer as { setTuning(next: never): void }).setTuning(clone(tuning) as never);
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
    });
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
  tickLfos(performance.now());
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
  const payload = {
    body,
    slot,
    tuning,
    lfos: Object.fromEntries(Object.entries(lfos).filter(([, l]) => l.on)),
  };
  try {
    const response = await fetch("/__bench-presets", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const body_ = await response.json() as { path?: string; count?: number };
    status.textContent = `locked in — ${body_.count ?? "?"} saved`;
    status.className = "ok";
  } catch (error) {
    // Said out loud rather than swallowed: a save that silently failed would be
    // discovered when the tuning was wanted, which is exactly too late.
    status.textContent = `SAVE FAILED — ${(error as Error).message}`;
    status.className = "bad";
  }
}

/** The export, in the exact shape of bodyTuning.ts, so it pastes straight in. */
function settingsText(): string {
  const ty = body === "jarvis" ? "JarvisTuning" : "UltronTuning";
  const stem = body === "jarvis" ? "JARVIS" : "ULTRON";
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
  body = (event.target as HTMLSelectElement).value as "jarvis" | "ultron";
  mount();
});
$("mode").addEventListener("change", (event) => {
  // The mode select drives BOTH the render state and which preset is loaded.
  // Two controls for those would be two things to forget to line up.
  slot = (event.target as HTMLSelectElement).value as Slot;
  // A TRANSITION, NOT A REMOUNT. This used to call mount(), which destroys the
  // renderer, rebuilds it and plays the arrival -- so every change of mode sent the
  // body back out to twice the radius and drew it in again. Changing mode is a
  // response, not an introduction; the arrival happens once, on load.
  shipped = shippedFor(body, slot);
  tuning = saved(slotKey(body, slot), shipped);
  for (const id of Object.keys(sliderDom)) delete sliderDom[id];
  lfos = savedLfos(slotKey(body, slot));
  buildControls();
  remember(slotKey(body, slot), tuning);
  renderer?.transitionTo(clone(tuning) as never);
});
$("save").addEventListener("click", () => { void savePreset(); });
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
  ($("mode") as HTMLSelectElement).value = startMode;
}
if (startLevel) ($("level") as HTMLInputElement).value = startLevel;
// A link naming the other body should open on it.
if ([...params.keys()].some((k) => k.startsWith("ultron."))
    && ![...params.keys()].some((k) => k.startsWith("jarvis."))) {
  body = "ultron";
  ($("body") as HTMLSelectElement).value = "ultron";
}
$("export").textContent = "";
mount();
