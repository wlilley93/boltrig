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
import { JarvisNeuralRenderer } from "../../src/components/jarvis/v2/JarvisNeuralRenderer";
import { UltronRenderer } from "../../src/components/ultron/UltronRenderer";

type Tuning = JarvisTuning | UltronTuning;
type Mode = "standby" | "listening" | "thinking" | "working" | "speaking";

/** Slider ranges. A number with no entry gets 0..1, which is right for a gain. */
const RANGE: Record<string, [number, number, number]> = {
  linkRange: [0.02, 0.60, 0.005],
  crackRange: [0.02, 0.60, 0.005],
  shardSize: [0.002, 0.06, 0.001],
  facetSize: [0.002, 0.06, 0.001],
  shardStride: [1, 64, 1],
  petal: [0, 1, 0.01],
  // Down to a standstill, because the complaint was that it is far too fast and
  // the shipped value is 0.26 -- a slider starting at 0.2 could not answer it.
  swirl: [0, 1.2, 0.005],
  // The crests own pace, separate from the fields. It has to reach a crawl:
  // "orbiting slowly" is the whole brief, and the old baked rate was 0.16.
  ringSpin: [0, 0.4, 0.002],
  ringBeam: [0.01, 0.3, 0.005],
  rings: [1, 12, 1],
  // Up to about 1.6 rad/s was what swept the fracture slivers around like clock
  // hands, so this needs to go well below its old base of 0.4.
  facetSpin: [0, 1.0, 0.005],
  // radius / population / brightness. The population reaching 0 matters: that is
  // how a body says it does not want an outer sphere at all.
  outerShell: [0, 2.2, 0.01],
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
  url.searchParams.set(body, JSON.stringify(tuning));
  url.searchParams.set("mode", ($("mode") as HTMLSelectElement).value);
  url.searchParams.set("level", ($("level") as HTMLInputElement).value);
  return url.toString();
}

let renderer: JarvisNeuralRenderer | UltronRenderer | null = null;
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
  renderer.applyPhenotype(null);
  // The export is per body, so a stale one is a wrong label on a set of numbers
  // — exactly the failure mode this whole session has been unpicking.
  $("export").textContent = "";
  shipped = body === "jarvis" ? JARVIS_TUNING : ULTRON_TUNING;
  tuning = saved(body, shipped);
  buildControls();
  push();
  loop();
}

/** The controls, generated FROM the struct so a new field cannot be forgotten. */
function buildControls(): void {
  const panel = $("controls");
  panel.innerHTML = "";
  for (const [key, value] of Object.entries(tuning)) {
    if (typeof value === "number") {
      panel.appendChild(row(key, key, [value], (next) => assign(key, next[0])));
    } else {
      panel.appendChild(row(key, key, value as number[], (next) => assign(key, next)));
    }
  }
}

function row(
  key: string,
  label: string,
  values: number[],
  onChange: (next: number[]) => void,
): HTMLElement {
  const [min, max, step] = RANGE[key] ?? [0, 1, 0.005];
  const wrap = document.createElement("div");
  wrap.className = "row";
  const name = document.createElement("label");
  // A pair is `base + perEnergy * energy`, so the two sliders are not
  // interchangeable and the legend says which is which.
  name.textContent = values.length === 2 ? `${label}  ·  base / ×energy` : label;
  wrap.appendChild(name);
  const live = values.slice();
  const readouts: HTMLElement[] = [];
  values.forEach((value, index) => {
    const input = document.createElement("input");
    input.type = "range";
    input.min = String(min);
    input.max = String(max);
    input.step = String(step);
    input.value = String(value);
    const out = document.createElement("b");
    out.textContent = value.toFixed(3);
    readouts.push(out);
    input.addEventListener("input", () => {
      live[index] = Number(input.value);
      readouts[index].textContent = live[index].toFixed(3);
      onChange(live.slice());
      push();
    });
    wrap.appendChild(input);
    wrap.appendChild(out);
  });
  return wrap;
}

function assign(key: string, value: number | number[]): void {
  (tuning as unknown as Record<string, unknown>)[key] = value;
}

function push(): void {
  if (!renderer) return;
  remember(body, tuning);
  // Cast at the seam: the page holds one union and each renderer takes its own
  // half of it, which the body switch above already guarantees.
  (renderer as { setTuning(next: never): void }).setTuning(clone(tuning) as never);
}

function drive(): void {
  if (!renderer) return;
  const mode = ($("mode") as HTMLSelectElement).value as Mode;
  const level = Number(($("level") as HTMLInputElement).value);
  renderer.update({
    mode,
    level,
    bands: Array.from({ length: 8 }, (_, i) => (mode === "speaking" ? 0.82 - i * 0.09 : 0.1)),
    onset: mode === "speaking" && frames % 45 === 0 ? 0.9 : 0,
    micLevel: mode === "listening" ? level : 0,
  } as never);
}

function loop(): void {
  raf = realRaf(loop);
  frames += 1;
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

/** The export, in the exact shape of bodyTuning.ts, so it pastes straight in. */
function settingsText(): string {
  const name = body === "jarvis" ? "JARVIS_TUNING: JarvisTuning" : "ULTRON_TUNING: UltronTuning";
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
$("reset").addEventListener("click", () => {
  // Clear the store BEFORE pushing, since push() writes it back.
  try { localStorage.removeItem(storageKey(body)); } catch { /* nothing to clear */ }
  tuning = clone(shipped);
  buildControls();
  push();
});
$("link").addEventListener("click", () => {
  const url = shareLink();
  void navigator.clipboard?.writeText(url).catch(() => undefined);
  $("export").textContent = url;
});
$("copy").addEventListener("click", () => {
  const text = settingsText();
  void navigator.clipboard?.writeText(text).catch(() => undefined);
  $("export").textContent = text;
});
const params = new URLSearchParams(location.search);
const startMode = params.get("mode");
const startLevel = params.get("level");
if (startMode) ($("mode") as HTMLSelectElement).value = startMode;
if (startLevel) ($("level") as HTMLInputElement).value = startLevel;
// A link naming the other body should open on it.
if (params.has("ultron") && !params.has("jarvis")) {
  body = "ultron";
  ($("body") as HTMLSelectElement).value = "ultron";
}
$("export").textContent = "";
mount();
