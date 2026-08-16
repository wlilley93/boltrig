// Client-side Jarvis state — the HUD instrument's input contract.
//
// Same discipline as FamiliarState (ADR 0025): bounded numbers and closed enums
// only. Nothing here may ever carry text, audio, credentials or identifiers,
// and nothing here may influence dispatch. The two contracts are siblings, not
// a hierarchy — the instrument needs a discrete mode where the creature needs a
// continuous phenotype, so they deliberately do not share a type.

export type JarvisMode =
  | "standby"
  | "listening"
  | "thinking"
  | "working"
  | "speaking";

export const JARVIS_MODES: readonly JarvisMode[] = [
  "standby", "listening", "thinking", "working", "speaking",
] as const;

/** Glyph-table ids in jarvis.frag. Must stay in step with the shader. */
export const JarvisLabel = {
  SPEAKING: 0,
  LISTENING: 1,
  THINKING: 2,
  WORKING: 3,
  STANDBY: 4,
  YOUR_TURN: 5,
  READOUT: 6,
  NONE: 7,
} as const;
export type JarvisLabelId = (typeof JarvisLabel)[keyof typeof JarvisLabel];

export interface JarvisStageState {
  /** Which behaviour the instrument is showing. */
  mode: JarvisMode;
  /** 0..1 level of whichever voice is live; clamped, non-finite ignored. */
  level: number;
  /** Eight 0..1 log-band energies of the OUTGOING voice; drives the fan. */
  bands?: number[] | null;
  /** 0..1 spectral-flux onset of the outgoing voice. */
  onset?: number;
  /** 0..1 level of the INCOMING voice; drawn as the listening sweep. */
  micLevel?: number;
  /** 0..9.99 number under the dial while working. */
  readout?: number;
}

export const RESTING_JARVIS_STATE: JarvisStageState = {
  mode: "standby",
  level: 0,
  bands: null,
  onset: 0,
  micLevel: 0,
  readout: 0,
};

const clamp01 = (value: unknown): number =>
  typeof value === "number" && Number.isFinite(value)
    ? Math.min(1, Math.max(0, value))
    : 0;

export function clampJarvisState(next: Partial<JarvisStageState>): JarvisStageState {
  const mode = JARVIS_MODES.includes(next.mode as JarvisMode)
    ? (next.mode as JarvisMode)
    : "standby";
  const bands = Array.isArray(next.bands) && next.bands.length === 8
    ? next.bands.map(clamp01)
    : null;
  const readout = typeof next.readout === "number" && Number.isFinite(next.readout)
    ? Math.min(9.99, Math.max(0, next.readout))
    : 0;
  return {
    mode,
    level: clamp01(next.level),
    bands,
    onset: clamp01(next.onset),
    micLevel: clamp01(next.micLevel),
    readout,
  };
}

/**
 * Derives the instrument's mode from what ChatView already knows. The renderer
 * never parses chat events itself — activity arrives through this one seam,
 * exactly as it does for the Familiar.
 *
 * Precedence is deliberate: an agent that is speaking is speaking even while
 * its next turn is already streaming, and a live microphone outranks a quiet
 * background turn, because the person in the room is the one waiting.
 */
export function jarvisStateFromTurn(input: {
  loading: boolean;
  hasLiveEvents: boolean;
  liveEnded: boolean;
  voiceSpeaking: boolean;
  voiceLevel: number;
  voiceBands?: number[] | null;
  voiceOnset?: number;
  micActive?: boolean;
  micLevel?: number;
  readout?: number;
}): JarvisStageState {
  const streaming = input.hasLiveEvents && !input.liveEnded;
  let mode: JarvisMode = "standby";
  if (input.voiceSpeaking) mode = "speaking";
  else if (input.micActive) mode = "listening";
  else if (streaming) mode = "working";
  else if (input.loading) mode = "thinking";

  return clampJarvisState({
    mode,
    level: input.voiceSpeaking ? input.voiceLevel : (input.micLevel ?? 0),
    bands: input.voiceBands ?? null,
    onset: input.voiceOnset,
    micLevel: input.micLevel,
    readout: input.readout,
  });
}

/**
 * Which words sit on the two arcs. Policy lives here rather than in the shader
 * so copy changes never mean recompiling GLSL, and so the pairing is testable.
 */
export function labelsForMode(mode: JarvisMode): {
  top: JarvisLabelId;
  bottom: JarvisLabelId;
  topAmt: number;
  bottomAmt: number;
} {
  switch (mode) {
    case "speaking":
      return { top: JarvisLabel.SPEAKING, bottom: JarvisLabel.THINKING, topAmt: 1, bottomAmt: 0.4 };
    case "listening":
      return { top: JarvisLabel.LISTENING, bottom: JarvisLabel.YOUR_TURN, topAmt: 1, bottomAmt: 0.55 };
    case "thinking":
      return { top: JarvisLabel.THINKING, bottom: JarvisLabel.NONE, topAmt: 1, bottomAmt: 0 };
    case "working":
      return { top: JarvisLabel.WORKING, bottom: JarvisLabel.READOUT, topAmt: 1, bottomAmt: 0.7 };
    default:
      return { top: JarvisLabel.STANDBY, bottom: JarvisLabel.NONE, topAmt: 0.5, bottomAmt: 0 };
  }
}

export interface JarvisRendererStatus {
  kind: "webgl2";
  state: "mounted" | "running" | "suspended" | "failed" | "destroyed";
  /** Present only when state is "failed"; safe to log, never user content. */
  reason?: string;
}
