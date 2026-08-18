// What a Jarvis frame LOOKS like, given the state: which tuning is on screen,
// and what colour it is drawn in.
//
// Lifted out of JarvisNeuralRenderer when that file passed the Worker
// structural floor (400 lines, NFR-MNT-07). The seam is real rather than
// convenient: everything here is a pure function of the state handed to it,
// while what remains in the renderer is the part that owns a canvas, a GL
// context and a rAF loop. That is also the half worth testing without a GPU.

import { applyPulses, easeFactor, easeTuning, type BodyMode } from "../../canvas/bodyModes";
import { JARVIS_PULSES, jarvisModeTuning } from "../../canvas/bodyPresets";
import { emotionColour, tint, type BodyPhenotype } from "../../canvas/bodyEmotion";
import type { JarvisTuning } from "../../canvas/bodyTuning";
import type { FloatUniforms } from "../../canvas/glResources";

export interface NeuralRendererOptions {
  /** Base warm colour. Defaults to the JARVIS orange. */
  warm?: [number, number, number];
  /** Hot core colour. */
  hot?: [number, number, number];
  /** The fringe band's colour -- see FRINGE_GLSL in glslCommon.ts. */
  fringe?: [number, number, number];
  maxDevicePixelRatio?: number;
}

export interface ShownTuningInput {
  /** What is currently being drawn, and what the ease travels from. */
  live: JarvisTuning;
  /** A bench override. Null means follow the mode, which is the shipped path. */
  pinned: JarvisTuning | null;
  mode: BodyMode;
  /** Seconds of draw-in still to run. */
  introLeft: number;
  reducedMotion: boolean;
  /** Unclamped wall-clock seconds since the last frame. */
  easeDt: number;
  animClock: number;
}

export interface ShownTuning {
  live: JarvisTuning;
  shown: JarvisTuning;
  introLeft: number;
}

/**
 * The mode is the target and `live` chases it; the pulses then ride on top.
 * An explicit bench override replaces the target outright, which is why
 * dragging a slider is instant.
 *
 * Returns the new `live` and `introLeft` rather than mutating, so the caller's
 * two pieces of frame state move in one assignment and this stays testable.
 */
export function selectShownTuning(i: ShownTuningInput): ShownTuning {
  if (i.introLeft > 0 && !i.reducedMotion) {
    // THE DRAW-IN, and it outranks a pinned tuning for as long as it lasts. The
    // destination is the pin when there is one, so a bench with a saved look
    // animates to that look rather than to the shipped preset.
    const target = i.pinned ?? jarvisModeTuning(i.mode);
    const live = easeTuning(i.live, target, easeFactor(i.easeDt));
    return { live, shown: live, introLeft: Math.max(0, i.introLeft - i.easeDt) };
  }
  if (i.pinned) {
    // KEEP `live` ON WHAT IS ACTUALLY DRAWN while pinned. Otherwise it holds
    // whatever it was when the last ease finished, and the next transition starts
    // from that stale value rather than from the look on screen -- so a change of
    // mode would jump backwards before travelling forwards.
    return { live: i.pinned, shown: i.pinned, introLeft: i.introLeft };
  }
  const target = jarvisModeTuning(i.mode);
  // Reduced motion gets the destination and none of the journey: the entry
  // animation and the pulses are both motion, and neither is information.
  const live = i.reducedMotion ? target : easeTuning(i.live, target, easeFactor(i.easeDt));
  const shown = i.reducedMotion ? live : applyPulses(live, JARVIS_PULSES[i.mode], i.animClock);
  return { live, shown, introLeft: i.introLeft };
}

/**
 * Colour, after the phenotype has had its say. Irritation drags the orange
 * toward red -- the same move V1 makes, and one non-orange frame says more
 * than any amount of extra brightness.
 *
 * NO LENS FLARE ON A HOLOGRAM, AND A WARM HEART. Three things stacked at the
 * centre: the field converges there, the composite adds two gaussians on top
 * of it, and the starburst laid a hot bar fifteen times wider than it was tall
 * straight across the middle. That bar is what read as a white block shining
 * through the iris. It is off -- it belongs to Colossus, whose CRT beam earns
 * a horizontal streak -- and the lobes now sit at the warm end, so the heart
 * stays bright without leaving the orange.
 */
export function jarvisPalette(opts: NeuralRendererOptions, pheno: BodyPhenotype): FloatUniforms {
  const warm = opts.warm ?? [1.0, 0.38, 0.04];
  const hot = opts.hot ?? [1.0, 0.74, 0.32];
  const fringe = opts.fringe ?? [0.42, 0.09, 0.02];
  // The WHOLE register, not just irritation. Nine of the ten scalars used to
  // reach colour not at all, so a mood could only ever make him brighter.
  const c = emotionColour(pheno);
  return {
    uWarm: tint(warm, c.warm, c.desaturate),
    uHot: tint(hot, c.hot, c.desaturate),
    uFringe: tint(fringe, c.fringe, c.desaturate),
    // The fringe band. See FRINGE_GLSL: outer = inner / scale, and everything
    // below outer draws nothing at all.
    uInner: 0.52,
    uFringeScale: 2.4,
    uFringeGain: 1.15,
  };
}
