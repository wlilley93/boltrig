// Client-side Familiar state (ADR 0025). This is the Stage's input contract —
// bounded numbers and closed enums only. It is deliberately a subset of the
// future FamiliarState v2 SDK contract: nothing here may ever carry text,
// audio, credentials or identifiers, and nothing here may influence dispatch.

/**
 * THE STATES, and why there are six rather than the two there were.
 *
 * This was `working` and `speaking`, two booleans — which can express four
 * combinations, two of which are nonsense, and which cannot express the two
 * states a person waiting on a voice agent most needs to see. LISTENING was the
 * larger gap: the shared turn input has carried `micActive` since the character
 * contract was written, Jarvis and Ultron both read it, and the Familiar
 * dropped it on the floor — so while you were talking to her she was rendering
 * her idle state, which is the one moment a body has an obvious job.
 *
 * ERROR is the other. Worker maps a dropped call to "not working any more", so
 * a failure looked exactly like a finished turn: she went calm while the page
 * said the call had died.
 *
 * The five shared with the other bodies keep their spellings, so a mode is one
 * word across all three characters and the shader bench can drive any of them
 * from one select. `error` is the Familiar's alone: adding it to the shared
 * BodyMode would have forced an entry into Jarvis's and Ultron's preset tables,
 * and an empty entry there is a state the enum claims and the body does not
 * honour — the exact defect this file is closing.
 */
export type FamiliarMode =
  | "standby"
  | "listening"
  | "thinking"
  | "working"
  | "speaking"
  | "error";

export const FAMILIAR_MODES: readonly FamiliarMode[] = [
  "standby", "listening", "thinking", "working", "speaking", "error",
];

export type FamiliarPresentationMode =
  | "hero"
  | "conversation"
  | "voice"
  | "minimised";

export interface FamiliarStageState {
  /** What the machine is doing, as one closed enum. */
  mode: FamiliarMode;
  /** 0..1 level of whichever voice is live; clamped, non-finite ignored. */
  level: number;
  /** Eight 0..1 log-band energies of the OUTGOING voice; optional. */
  bands?: number[] | null;
  /** 0..1 spectral-flux onset of the outgoing voice; optional. */
  onset?: number;
  /** 0..1 level of the INCOMING voice — what she is being told. */
  micLevel?: number;
}

export const RESTING_STAGE_STATE: FamiliarStageState = {
  mode: "standby",
  level: 0,
  bands: null,
  onset: 0,
  micLevel: 0,
};

const clamp01 = (value: unknown): number =>
  typeof value === "number" && Number.isFinite(value)
    ? Math.min(1, Math.max(0, value))
    : 0;

export function clampStageState(next: Partial<FamiliarStageState>): FamiliarStageState {
  const mode = FAMILIAR_MODES.includes(next.mode as FamiliarMode)
    ? (next.mode as FamiliarMode)
    : "standby";
  const bands = Array.isArray(next.bands) && next.bands.length === 8
    ? next.bands.map(clamp01)
    : null;
  return {
    mode,
    level: clamp01(next.level),
    bands,
    onset: clamp01(next.onset),
    micLevel: clamp01(next.micLevel),
  };
}

/**
 * Derives the Stage's state from what ChatView and VoiceCall already know. The
 * visual renderer never parses chat events itself — activity arrives through
 * this one seam (and later through FamiliarState v2).
 *
 * PRECEDENCE IS THE DECISION HERE, and it is the same order Jarvis uses so that
 * two characters cannot disagree about what the machine is doing:
 *
 *   failure  outranks everything. A dropped call is not less important than
 *            the turn that was streaming when it dropped.
 *   speaking outranks listening. She is speaking even while the next turn is
 *            already streaming behind it.
 *   listening outranks a background turn, because the person in the room is
 *            the one waiting.
 *   working  is a turn with live events; thinking is a turn with none yet,
 *            which is the difference between "I am doing it" and "I heard you".
 */
export function familiarStateFromTurn(input: {
  loading: boolean;
  hasLiveEvents: boolean;
  liveEnded: boolean;
  voiceSpeaking: boolean;
  voiceLevel: number;
  voiceBands?: number[] | null;
  voiceOnset?: number;
  micActive?: boolean;
  micLevel?: number;
  failed?: boolean;
}): FamiliarStageState {
  const streaming = input.hasLiveEvents && !input.liveEnded;
  let mode: FamiliarMode = "standby";
  if (input.failed) mode = "error";
  else if (input.voiceSpeaking) mode = "speaking";
  else if (input.micActive) mode = "listening";
  else if (streaming) mode = "working";
  else if (input.loading) mode = "thinking";

  return clampStageState({
    mode,
    level: input.voiceSpeaking ? input.voiceLevel : (input.micLevel ?? 0),
    bands: input.voiceBands ?? null,
    onset: input.voiceOnset,
    micLevel: input.micLevel,
  });
}

/** Whether the being is doing something, for hosts that only need the bit. */
export function familiarBusy(state: FamiliarStageState): boolean {
  return state.mode !== "standby" && state.mode !== "error";
}

/**
 * The mode in words, for the Stage's live region.
 *
 * NOT DECORATION. If a body is the only indicator of what the machine is doing
 * then a screen-reader user has no indicator at all, and an `aria-label` that
 * changes on a `role="img"` is not reliably announced — it is a name, not a
 * status. So the Stage carries a real live region and this is what it says.
 * Plain words rather than the enum, because "standby" is jargon for a state a
 * person would call ready.
 */
export function familiarModeLabel(mode: FamiliarMode): string {
  switch (mode) {
    case "listening": return "listening";
    case "thinking": return "thinking";
    case "working": return "working";
    case "speaking": return "speaking";
    case "error": return "disconnected";
    default: return "ready";
  }
}

export interface FamiliarRendererStatus {
  kind: "webgl2";
  state: "mounted" | "running" | "suspended" | "failed" | "destroyed";
  /** Present only when state is "failed"; safe to log, never user content. */
  reason?: string;
}
