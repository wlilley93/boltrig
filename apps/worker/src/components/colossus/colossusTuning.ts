// Colossus's tunable surface, in a sign's vocabulary.
//
// HE HAD NO TUNING STRUCT, on the argument that one register needs no numbers
// — and the bench disagreed: a body that cannot be mixed is a body whose look
// is settled by whoever wrote the last literal. So the literals moved here.
// Every value in this file is exactly what the renderer hardcoded before it
// existed; a build with this module and no bench edits draws the same panel.
//
// THE FIELDS ARE DRIVE AND GLASS, NOT LAMP GEOMETRY. What the shaders compute
// stays theirs; this struct carries what a mixing desk can honestly own — how
// hard the board is driven, how the voice moves it, how fast the sign runs,
// and the tube the whole picture is seen through.

import type { ColossusMode } from "./ColossusState";

export interface ColossusTuning {
  /** Panel drive: the resting energy, and what the voice adds on top. */
  energy: readonly [base: number, byVoice: number];
  /**
   * How the voice reaches the board: the floor it holds while he is speaking
   * (a report never whispers), and how much of it bleeds through in every
   * other mode (a panel answering silence would be answering nothing).
   */
  voice: readonly [speakingFloor: number, idleBleed: number];
  /** The sign: cells per second at rest, and cells added per unit of voice. */
  ticker: readonly [pace: number, byVoice: number];
  /** Sign glyph scale, as a multiple of the lamp pitch. */
  tickerScale: number;
  /** Lamps across the panel width. Coarse is the reference; fine is an LED. */
  pitch: number;
  /** CRT curvature of the glass. */
  curve: number;
  /** Phosphor persistence — how long a driven lamp holds its light. */
  decay: number;
  /** Bloom over the composite: resting gain, and what the voice adds. */
  bloom: readonly [base: number, byVoice: number];
  /** How hard the picture falls off toward the corners. */
  vignette: number;
  /** The counter: the onset that steps it, and how fast its glow fades. */
  counter: readonly [threshold: number, fade: number];
}

/** What ships: his standby register, exactly as the renderer hardcoded it. */
export const COLOSSUS_TUNING: ColossusTuning = {
  energy: [0.30, 0.30],
  voice: [0.30, 0.25],
  ticker: [10, 5],
  tickerScale: 1.8,
  pitch: 138,
  curve: 0.055,
  decay: 0.85,
  bloom: [0.30, 0.25],
  vignette: 0.85,
  counter: [0.35, 3.4],
};

/**
 * Per mode: the drive rises and the sign quickens, and nothing else changes —
 * which is the panel the renderer always drew, now stated as deltas. Speaking
 * is the one mode where the voice really owns the sign (×22 against ×5): what
 * a listener hears in his voice they see in how fast the sentence crosses.
 */
export const COLOSSUS_MODES: Record<ColossusMode, Partial<ColossusTuning>> = {
  standby: {},
  listening: { energy: [0.44, 0.30], ticker: [13, 5] },
  thinking: { energy: [0.55, 0.30], ticker: [16, 5] },
  working: { energy: [0.70, 0.30], ticker: [20, 5] },
  speaking: { energy: [0.90, 0.30], ticker: [26, 22] },
};

/** His target for a mode: the base with that mode's deltas laid over it. */
export function colossusModeTuning(mode: ColossusMode): ColossusTuning {
  return { ...COLOSSUS_TUNING, ...COLOSSUS_MODES[mode] };
}
