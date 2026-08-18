/** What Colossus's panel is told about the machine.
 *
 * The same four presentation signals the other animated bodies read. Written
 * out here rather than imported from Ultron's module for the reason his says:
 * a character importing another character's state type acquires that character
 * as a dependency, and the next change over there arrives here uninvited.
 *
 * Three bodies now carry the same four fields, which is the point at which a
 * shared `StageSignals` starts to earn its keep -- but extracting it would put
 * every character on one type and make the next divergence a negotiation. His
 * mic level is already unused, because a sign has nothing to say about being
 * listened to, and that is the kind of divergence a shared type suppresses.
 */
export type ColossusMode = "standby" | "listening" | "thinking" | "working" | "speaking";

export const COLOSSUS_MODES: readonly ColossusMode[] = [
  "standby", "listening", "thinking", "working", "speaking",
];

export interface ColossusStageState {
  mode: ColossusMode;
  /** 0..1 level of whichever voice is live; clamped, non-finite ignored. */
  level: number;
  /** Eight 0..1 log-band energies of the OUTGOING voice. */
  bands?: number[] | null;
  /** 0..1 spectral-flux onset; steps the counter, which is what a counter does. */
  onset?: number;
  /**
   * The phrase the sign shows while he is speaking, or null for his own copy.
   *
   * HE IS THE ONLY BODY THAT READS IT, because he is the only body made of
   * words. Jarvis and Ultron are handed the same field by the same contract and
   * ignore it -- a globe has nowhere to put a sentence, and inventing somewhere
   * would make every character a caption.
   */
  takeaway?: string | null;
}

export const RESTING_COLOSSUS_STATE: ColossusStageState = {
  mode: "standby",
  level: 0,
  bands: null,
  onset: 0,
  takeaway: null,
};

const clamp01 = (value: unknown): number =>
  typeof value === "number" && Number.isFinite(value)
    ? Math.min(1, Math.max(0, value))
    : 0;

export function clampColossusState(next: Partial<ColossusStageState>): ColossusStageState {
  const mode = COLOSSUS_MODES.includes(next.mode as ColossusMode)
    ? (next.mode as ColossusMode)
    : "standby";
  const bands = Array.isArray(next.bands) && next.bands.length === 8
    ? next.bands.map(clamp01)
    : null;
  return {
    mode,
    level: clamp01(next.level),
    bands,
    onset: clamp01(next.onset),
    // A phrase only counts while he is SPEAKING. Held across a mode change it
    // would leave the last thing he said scrolling under EVALUATING, which
    // reports something the machine is not doing.
    takeaway: mode === "speaking" ? takeawayOf(next.takeaway) : null,
  };
}

/**
 * A takeaway, or null.
 *
 * Length-capped a second time, here, even though the producer caps it. This is
 * the boundary a third-party host crosses, and the sign compiles whatever it is
 * handed into a fixed-size glyph buffer -- so the cap belongs on the side that
 * would be damaged, not only on the side that is well behaved.
 */
function takeawayOf(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim().slice(0, 80);
  return trimmed.length > 0 ? trimmed : null;
}

export function colossusStateFromTurn(input: {
  loading: boolean;
  hasLiveEvents: boolean;
  liveEnded: boolean;
  voiceSpeaking: boolean;
  voiceLevel: number;
  voiceBands?: number[] | null;
  voiceOnset?: number;
  micActive?: boolean;
  micLevel?: number;
  speechTakeaway?: string | null;
}): ColossusStageState {
  const streaming = input.hasLiveEvents && !input.liveEnded;
  let mode: ColossusMode = "standby";
  if (input.voiceSpeaking) mode = "speaking";
  else if (input.micActive) mode = "listening";
  else if (streaming) mode = "working";
  else if (input.loading) mode = "thinking";

  return clampColossusState({
    mode,
    level: input.voiceSpeaking ? input.voiceLevel : (input.micLevel ?? 0),
    bands: input.voiceBands ?? null,
    onset: input.voiceOnset,
    takeaway: input.speechTakeaway ?? null,
  });
}
