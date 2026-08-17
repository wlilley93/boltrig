// Colossus: World Control, as a wall of lamps.
//
// WHY A PANEL AND NOT A BODY. The other three characters are spheres -- a
// creature, an instrument, a membrane -- and a fourth glowing orb would have
// been a recolour with a different personality bolted on. He is the one
// character in the set who is explicitly NOT a companion: a strategic system
// that was switched on, reasoned to a conclusion, and now reports. The 1970
// reference is a room, and the only part of it that faces you is a sign.
//
// HE DOES NOT READ THE PHENOTYPE, and his bundle omits the block rather than
// carrying `reads: false`. Familiar is excluded because she has her own inner
// life the appraisal engine cannot see; he is excluded for the opposite reason.
// He has ONE register. A stability report does not come in an irritated
// variant, and a panel that changed colour when the machine was annoyed would
// be conceding that it has moods to be managed.
//
// SO WHAT DOES HE REACT TO. The voice, and only the voice. The sign scrolls
// faster while he speaks, the indicator fields answer their band, and the
// counter steps on onsets. That is the same contract the other three now hold
// -- live reactivity through the voice channel rather than a scripted idle --
// expressed in the one vocabulary a sign has.

import { type FloatUniforms } from "../canvas/glResources";
import { ColossusPasses, type ColossusDrive } from "./colossusPasses";
import type { ColossusStageState } from "./ColossusState";
import { READOUT_LEN } from "./shadersColossus";
import { glyphIds } from "./glyphAtlas";
import { scrollSpeed, tickerFor } from "./tickerText";

const SILENT_BANDS = new Float32Array(8);

export interface ColossusRendererOptions {
  /** The lamp colour at ordinary brightness. Amber, and it stays amber. */
  amber?: [number, number, number];
  /** A fully driven lamp, blown toward white as the reference ones are. */
  hot?: [number, number, number];
  /** The single cool accent. One column of the lower field, never a second. */
  teal?: [number, number, number];
  maxDevicePixelRatio?: number;
}

type Status = { state: "idle" | "running" | "failed"; reason?: string };

export class ColossusRenderer {
  private host: HTMLElement | null = null;
  private canvas: HTMLCanvasElement | null = null;
  private gl: WebGL2RenderingContext | null = null;
  private passes: ColossusPasses | null = null;
  private raf = 0;
  private lastFrameAt = 0;
  /** Animation seconds, summed from CLAMPED frame deltas -- never wall clock.
   *
   * A background tab stops delivering frames, so a wall-clock time advances by
   * the whole hidden duration in one frame and the sign lurches half a sentence
   * on return. Every other renderer here carried that bug once; this one does
   * not get to be the fourth. */
  private animClock = 0;
  private suspended = false;
  private reducedMotion = false;
  private size: [number, number] = [0, 0];
  private state: ColossusStageState | null = null;
  private bands = new Float32Array(8);
  private scroll = 0;
  private ticker = tickerFor("standby");
  private tickerMode: ColossusStageState["mode"] = "standby";
  private tickerTakeaway: string | null = null;
  private counter = 0;
  private counterGlow = 0;
  private readout = new Int32Array(READOUT_LEN);
  private _status: Status = { state: "idle" };

  constructor(private readonly opts: ColossusRendererOptions = {}) {
    this.writeReadout();
  }

  status(): Status { return this._status; }

  mount(host: HTMLElement): void {
    this.host = host;
    const canvas = document.createElement("canvas");
    canvas.className = "colossus-canvas";
    host.appendChild(canvas);
    this.canvas = canvas;

    const gl = canvas.getContext("webgl2", {
      alpha: true, antialias: false, premultipliedAlpha: false,
    }) as WebGL2RenderingContext | null;
    if (!gl) { this.fail("webgl2 unavailable"); return; }
    this.gl = gl;

    // NOTE the absence: no EXT_color_buffer_float check. The other three need it
    // because they integrate positions in a float texture; a lamp's brightness
    // is closed-form, so this body runs on plain WebGL2 and half-float targets.
    try {
      this.passes = new ColossusPasses(gl);
      this.passes.init();
    } catch (err) {
      this.fail(String(err));
      return;
    }

    this.reducedMotion = typeof matchMedia === "function"
      && matchMedia("(prefers-reduced-motion: reduce)").matches;

    this.resize();
    this._status = { state: "running" };
    this.lastFrameAt = performance.now();
    this.loop();
  }

  destroy(): void {
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    this.passes?.destroy();
    this.passes = null;
    this.canvas?.remove();
    this.canvas = null;
    this.gl = null;
    this.host = null;
  }

  update(state: ColossusStageState): void {
    const bands = state.bands;
    if (bands && bands.length === 8) {
      for (let i = 0; i < 8; i++) this.bands[i] = Math.min(1, Math.max(0, bands[i]));
    } else {
      this.bands.set(SILENT_BANDS);
    }
    // The sign changes its sentence when the mode changes OR when he starts
    // saying something else, and NOT otherwise: recompiling every update would
    // reset the scroll and make the text stutter.
    //
    // The takeaway is part of the key rather than a second branch, because the
    // two change together on the frame a reply starts -- mode goes to speaking
    // and the phrase arrives in the same update, and two separate checks would
    // compile the sentence twice.
    const takeaway = state.takeaway ?? null;
    if (state.mode !== this.tickerMode || takeaway !== this.tickerTakeaway) {
      this.ticker = tickerFor(state.mode, takeaway);
      this.tickerMode = state.mode;
      this.tickerTakeaway = takeaway;
    }
    const onset = typeof state.onset === "number" ? state.onset : 0;
    if (onset > 0.35) {
      // The counter steps on onsets, which is the reference instrument's whole
      // behaviour: it is measuring something and the something is his speech.
      this.counter = (this.counter + 1) % 10000;
      this.counterGlow = 1;
      this.writeReadout();
    }
    this.state = state;
  }

  /**
   * Accepted and ignored, on purpose.
   *
   * The Stage calls this on every character, so refusing to implement it would
   * be a branch at the call site naming him by id. He takes the argument and
   * does nothing with it because he has one register -- see the header, and his
   * bundle, which omits the phenotype block entirely rather than declaring
   * `reads: false`.
   */
  applyPhenotype(_pheno: Record<string, unknown> | null): void {}

  suspend(): void { this.suspended = true; }
  resume(): void {
    if (!this.suspended) return;
    this.suspended = false;
    this.lastFrameAt = performance.now();
  }

  /** Render one frame. Public so a still can be taken without a rAF loop. */
  frame(nowMs: number): void {
    const passes = this.passes;
    if (!passes || !this.canvas) return;
    this.resize();
    const drive = this.drive(nowMs);
    passes.render(drive, this.palette(), 0.30 + 0.25 * drive.voice);
  }

  // ------------------------------------------------------------------ internals

  private fail(reason: string): void {
    this._status = { state: "failed", reason };
    this.canvas?.remove();
    this.canvas = null;
    this.gl = null;
  }

  private resize(): void {
    const canvas = this.canvas;
    const host = this.host;
    if (!canvas || !host || !this.passes) return;
    const dpr = Math.min(window.devicePixelRatio || 1, this.opts.maxDevicePixelRatio ?? 1.5);
    const w = Math.max(1, Math.round(host.clientWidth * dpr));
    const h = Math.max(1, Math.round(host.clientHeight * dpr));
    if (w === this.size[0] && h === this.size[1]) return;
    this.size = [w, h];
    canvas.width = w;
    canvas.height = h;
    this.passes.resize(w, h);
  }

  /** "+0042 US" -- sign, four digits, a space, and a unit, as in the film. */
  private writeReadout(): void {
    const digits = String(this.counter).padStart(4, "0");
    const ids = glyphIds(`+${digits} US`);
    for (let i = 0; i < READOUT_LEN; i++) this.readout[i] = ids[i] ?? 0;
  }

  private drive(nowMs: number): ColossusDrive {
    const dt = Math.min(0.05, Math.max(0.001, (nowMs - this.lastFrameAt) / 1000));
    this.lastFrameAt = nowMs;
    if (!this.reducedMotion) this.animClock += dt;

    const mode = this.state?.mode ?? "standby";
    const level = Math.min(1, Math.max(0, this.state?.level ?? 0));
    const speaking = mode === "speaking";

    // A sign that stopped would read as broken, and every reference panel is
    // moving. Reduced motion holds it still anyway -- that is the one case
    // where a stopped sign is the correct answer.
    if (!this.reducedMotion) {
      this.scroll += scrollSpeed(mode, level) * dt;
    }
    this.counterGlow *= Math.exp(-dt * 3.4);

    const base = speaking ? 0.90 : mode === "working" ? 0.70
      : mode === "thinking" ? 0.55 : mode === "listening" ? 0.44 : 0.30;

    return {
      time: this.animClock,
      energy: Math.min(1, base + level * 0.30),
      // Speaking is when the voice should move the board. Idle stays idle -- a
      // panel answering silence would be answering nothing.
      voice: speaking ? Math.max(0.30, level) : level * 0.25,
      bands: this.bands,
      scroll: this.scroll,
      ticker: this.ticker.glyphs,
      tickerLen: this.ticker.length,
      readout: this.readout,
      readoutGlow: this.counterGlow,
    };
  }

  /**
   * Amber, and it stays amber.
   *
   * Fixed where the other three take a mood: this is the palette of a machine
   * that has one thing to say. The hot end is deliberately close to white
   * because the reference lamps genuinely blow out -- clipping the brightest
   * cores is faithful here rather than the saturation defect it was on Jarvis.
   */
  private palette(): FloatUniforms {
    return {
      uAmber: this.opts.amber ?? [1.0, 0.36, 0.05],
      uHot: this.opts.hot ?? [1.0, 0.62, 0.24],
      uTeal: this.opts.teal ?? [0.10, 0.82, 0.78],
      uCurve: 0.055,
      // FINE lamps across the panel width -- the indicator fields. Coarse in
      // absolute terms: the reference boards are low-resolution, and a fine
      // lattice reads as a modern LED screen.
      uPitch: 138,
      // And the sign draws at 1.8x that, which lands about a dozen characters
      // across a 16:9 card. The reference destination boards show ten to
      // twenty; below that a message will not fit and above it stops being
      // readable at a glance, which is the whole job of a sign.
      uTickerScale: 1.8,
      uDecay: 0.85,
    };
  }

  private loop = (): void => {
    this.raf = requestAnimationFrame(this.loop);
    if (this.suspended || (typeof document !== "undefined" && document.hidden)) {
      this.lastFrameAt = performance.now();
      return;
    }
    this.frame(performance.now());
  };
}

/** Every uniform the two passes set. Named here so the bundle can declare them. */
export const UNIFORMS: readonly string[] = [
  "uTime", "uAspect", "uEnergy", "uVoice", "uBands", "uScroll",
  "uTicker", "uTickerLen", "uReadout", "uReadoutGlow",
  "uCurve", "uPitch", "uTickerScale", "uAmber", "uHot", "uTeal", "uDecay",
  "uSrc", "uDir", "uThreshold",
  "uScene", "uBloom", "uBloomGain", "uVignette",
];
