/** What Ultron's body is told about the machine.
 *
 * The same four presentation signals every animated body reads -- which mode,
 * how loud, the eight voice bands, the onset. Written out here rather than
 * imported from Jarvis's module because they are not his: a character importing
 * another character's state type acquires that character as a dependency, and
 * the next change to Jarvis's dial would arrive uninvited in Ultron.
 *
 * If a fourth body ever wants the same four fields, this is the point at which
 * extracting a shared `StageSignals` earns its keep. Two is not yet that point:
 * the duplication is twenty lines and the coupling it avoids is permanent.
 */
export type UltronMode = "standby" | "listening" | "thinking" | "working" | "speaking";

export const ULTRON_MODES: readonly UltronMode[] = [
  "standby", "listening", "thinking", "working", "speaking",
];

export interface UltronStageState {
  mode: UltronMode;
  /** 0..1 level of whichever voice is live; clamped, non-finite ignored. */
  level: number;
  /** Eight 0..1 log-band energies of the OUTGOING voice. */
  bands?: number[] | null;
  /** 0..1 spectral-flux onset of the outgoing voice; starts the travelling wave. */
  onset?: number;
  /** 0..1 level of the INCOMING voice. */
  micLevel?: number;
}

export const RESTING_ULTRON_STATE: UltronStageState = {
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

export function clampUltronState(next: Partial<UltronStageState>): UltronStageState {
  const mode = ULTRON_MODES.includes(next.mode as UltronMode)
    ? (next.mode as UltronMode)
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

export function ultronStateFromTurn(input: {
  loading: boolean;
  hasLiveEvents: boolean;
  liveEnded: boolean;
  voiceSpeaking: boolean;
  voiceLevel: number;
  voiceBands?: number[] | null;
  voiceOnset?: number;
  micActive?: boolean;
  micLevel?: number;
}): UltronStageState {
  const streaming = input.hasLiveEvents && !input.liveEnded;
  let mode: UltronMode = "standby";
  if (input.voiceSpeaking) mode = "speaking";
  else if (input.micActive) mode = "listening";
  else if (streaming) mode = "working";
  else if (input.loading) mode = "thinking";

  return clampUltronState({
    mode,
    level: input.voiceSpeaking ? input.voiceLevel : (input.micLevel ?? 0),
    bands: input.voiceBands ?? null,
    onset: input.voiceOnset,
    micLevel: input.micLevel,
  });
}
