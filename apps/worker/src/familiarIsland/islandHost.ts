// The island's host: one FamiliarWebGLRenderer inside the phone's web view,
// driven the way the shader bench drives it (tests/visual/shader-bench.ts): the
// renderer's own requestAnimationFrame loop is stubbed out BEFORE mount, and
// this host steps renderer.frame(now) on its own timer.
//
// OWNING THE LOOP IS THE POINT. The renderer's loop runs at the display rate
// whenever it is not minimised; a phone needs the rate capped per presentation,
// stopped outright when the page is hidden or the body is minimised, and
// measured, so the app can tell a body that costs 4ms a frame from one that
// costs 40. None of that is the renderer's business, and reaching in to change
// it would fork the one renderer the web app ships.
import { FamiliarWebGLRenderer } from "../components/familiar/FamiliarWebGLRenderer";
import type { FamiliarStageState } from "../components/familiar/FamiliarState";
import {
  applyState,
  DEFAULT_ISLAND_STATE,
  type IslandPresentation,
  type IslandState,
} from "./islandState";

export type IslandReport =
  | { type: "ready"; renderer: "webgl2"; presentation: IslandPresentation }
  | { type: "fallback"; reason: string }
  | { type: "frame"; fps: number; frameMs: number }
  | { type: "error"; message: string };

export type IslandPost = (report: IslandReport) => void;

/** The timers the loop runs on. Injectable so a test steps frames by hand; the
 *  default is the page's REAL requestAnimationFrame, captured at module load,
 *  before boot() replaces the global with a stub. */
export interface IslandClock {
  frame(callback: (now: number) => void): number;
  cancelFrame(handle: number): void;
  wait(callback: () => void, ms: number): number;
  cancelWait(handle: number): void;
  now(): number;
}

const REAL_RAF = typeof window === "undefined" ? null : window.requestAnimationFrame.bind(window);
const REAL_CAF = typeof window === "undefined" ? null : window.cancelAnimationFrame.bind(window);

export const BROWSER_CLOCK: IslandClock = {
  frame: (callback) => (REAL_RAF ? REAL_RAF(callback) : 0),
  cancelFrame: (handle) => REAL_CAF?.(handle),
  wait: (callback, ms) => window.setTimeout(callback, ms),
  cancelWait: (handle) => window.clearTimeout(handle),
  now: () => performance.now(),
};

/** Frames per second by presentation. Reduced motion overrides every one of
 *  them to a single frame a second, the renderer's own calm-creature rate. */
export const FPS_CAP: Readonly<Record<IslandPresentation, number>> = {
  hero: 60, conversation: 30, minimised: 0,
};
export const REPORT_EVERY_MS = 2000;
/** A frame due within this many ms of its slot draws now rather than a whole
 *  display refresh late; without it a 30 fps cap on a 60 Hz screen lands on 20. */
const SLACK_MS = 4;

const stageOf = (state: IslandState): Partial<FamiliarStageState> => ({
  mode: state.mode, level: state.level, bands: state.bands, onset: state.onset,
});

export class FamiliarIslandHost {
  private renderer: FamiliarWebGLRenderer | null = null;
  private element: HTMLElement | null = null;
  private post: IslandPost = () => {};
  private state: IslandState = DEFAULT_ISLAND_STATE;
  private frameHandle = 0;
  private waitHandle = 0;
  private lastDrawAt = -Infinity;
  private meter = { frames: 0, costMs: 0, since: -1 };
  private signalled: "none" | "ready" | "fallback" = "none";
  private readonly warned = new Set<string>();

  constructor(private readonly clock: IslandClock = BROWSER_CLOCK) {}

  boot(element: HTMLElement, post: IslandPost): void {
    this.element = element;
    this.post = post;
    // Stub rAF BEFORE mount, exactly as the bench does, so the renderer's own
    // loop never schedules. Deliberately never restored: two loops driving one
    // body would double its frame rate and every measurement here would lie.
    window.requestAnimationFrame = (() => 0) as typeof window.requestAnimationFrame;
    document.addEventListener("visibilitychange", this.onVisibility);
    this.mount();
  }

  current(): IslandState {
    return this.state;
  }

  /** Merge one message and act on what changed. Safe before boot: the state
   *  is kept and applied when the renderer is built. */
  apply(incoming: unknown): IslandState {
    const { state, effects, warning } = applyState(this.state, incoming);
    if (warning !== undefined && !this.warned.has(warning)) {
      this.warned.add(warning);
      this.post({ type: "error", message: warning });
    }
    this.state = state;
    if (!this.element) return state;
    if (effects.remount) {
      this.mount();
      return state;
    }
    const renderer = this.renderer;
    if (!renderer) return state;
    renderer.update(stageOf(state));
    if (effects.genotypeChanged) renderer.setGenotype(state.genotype);
    if (effects.phenotypeChanged) {
      renderer.applyPhenotype(state.phenotype as Parameters<typeof renderer.applyPhenotype>[0]);
    }
    if (effects.presentationChanged) {
      renderer.setMode(state.presentation);
      this.restart();
    }
    return state;
  }

  destroy(): void {
    this.stop();
    document.removeEventListener("visibilitychange", this.onVisibility);
    this.renderer?.destroy();
    this.renderer = null;
  }

  // ------------------------------------------------------------------ internals

  private mount(): void {
    this.stop();
    this.renderer?.destroy();
    this.renderer = null;
    if (!this.element) return;
    const renderer = new FamiliarWebGLRenderer({
      reducedMotion: this.state.reducedMotion,
      dprCap: this.state.dprCap,
      onFirstPaint: () => this.signal("ready"),
    });
    renderer.mount(this.element);
    const status = renderer.status();
    if (status.state !== "running") {
      // Never rewrite the look to survive a failure: say so, and the app shows
      // the badge in the body's place.
      renderer.destroy();
      this.signal("fallback", status.reason ?? status.state);
      return;
    }
    this.renderer = renderer;
    renderer.update(stageOf(this.state));
    renderer.setGenotype(this.state.genotype);
    renderer.applyPhenotype(this.state.phenotype as Parameters<typeof renderer.applyPhenotype>[0]);
    renderer.setMode(this.state.presentation);
    this.restart();
  }

  /** ready and fallback are posted on CHANGE, so a renderer that fails, is
   *  rebuilt and recovers announces each turn once, never twice in a row. */
  private signal(kind: "ready" | "fallback", reason = ""): void {
    if (this.signalled === kind) return;
    this.signalled = kind;
    if (kind === "ready") {
      this.post({ type: "ready", renderer: "webgl2", presentation: this.state.presentation });
    } else {
      this.post({ type: "fallback", reason });
    }
  }

  private onVisibility = (): void => {
    if (document.hidden) this.stop();
    else this.restart();
  };

  /** (Re)start the loop on a fresh meter; a no-op while minimised, failed or hidden. */
  private restart(): void {
    this.stop();
    this.meter = { frames: 0, costMs: 0, since: -1 };
    this.lastDrawAt = -Infinity;
    this.schedule();
  }

  private stop(): void {
    if (this.frameHandle) this.clock.cancelFrame(this.frameHandle);
    if (this.waitHandle) this.clock.cancelWait(this.waitHandle);
    this.frameHandle = 0;
    this.waitHandle = 0;
  }

  private drawing(): boolean {
    return this.renderer?.status().state === "running" && !document.hidden;
  }

  private intervalMs(): number {
    if (this.state.reducedMotion) return 1000;
    const fps = FPS_CAP[this.state.presentation];
    return fps > 0 ? 1000 / fps : Infinity;
  }

  private schedule(): void {
    if (this.frameHandle || this.waitHandle || !this.drawing()) return;
    const interval = this.intervalMs();
    if (!Number.isFinite(interval)) return;
    if (interval >= 100) {
      // A slow cadence sleeps on a timer rather than waking every display
      // refresh to decide not to draw.
      const due = Math.max(0, this.lastDrawAt + interval - this.clock.now());
      this.waitHandle = this.clock.wait(() => {
        this.waitHandle = 0;
        this.pump(this.clock.now());
      }, due);
      return;
    }
    this.frameHandle = this.clock.frame((now) => {
      this.frameHandle = 0;
      this.pump(now);
    });
  }

  private pump(now: number): void {
    if (!this.drawing()) return;
    if (now - this.lastDrawAt >= this.intervalMs() - SLACK_MS) this.draw(now);
    this.schedule();
  }

  private draw(now: number): void {
    const renderer = this.renderer;
    if (!renderer) return;
    this.lastDrawAt = now;
    const began = this.clock.now();
    try {
      renderer.frame(now);
    } catch (error) {
      this.stop();
      renderer.destroy();
      this.renderer = null;
      this.signal("fallback", error instanceof Error ? error.message : String(error));
      return;
    }
    this.measure(now, this.clock.now() - began);
  }

  /** fps and mean frame cost over each window of drawing; nothing is posted
   *  while minimised or hidden because nothing is drawn. The window opens on
   *  the first frame, so the intervals counted are whole ones. */
  private measure(now: number, costMs: number): void {
    const meter = this.meter;
    if (meter.since < 0) {
      meter.since = now;
      return;
    }
    meter.frames += 1;
    meter.costMs += costMs;
    const elapsed = now - meter.since;
    if (elapsed < REPORT_EVERY_MS) return;
    this.post({
      type: "frame",
      fps: Math.round((meter.frames * 1000) / elapsed),
      frameMs: Math.round((meter.costMs / meter.frames) * 100) / 100,
    });
    this.meter = { frames: 0, costMs: 0, since: now };
  }
}
