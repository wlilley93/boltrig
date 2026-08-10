// Client-side Familiar state (ADR 0025). This is the Stage's input contract —
// bounded numbers and closed enums only. It is deliberately a subset of the
// future FamiliarState v2 SDK contract: nothing here may ever carry text,
// audio, credentials or identifiers, and nothing here may influence dispatch.

export type FamiliarPresentationMode =
  | "hero"
  | "conversation"
  | "voice"
  | "minimised";

export interface FamiliarStageState {
  /** A turn is streaming: the body visibly works (pulse drive). */
  working: boolean;
  /** Outgoing voice is playing: the body articulates (stronger drive). */
  speaking: boolean;
  /** 0..1 voice/activity level; clamped, non-finite values ignored. */
  level: number;
  /** Eight 0..1 log-band energies of the outgoing voice; optional. */
  bands?: number[] | null;
  /** 0..1 spectral-flux onset of the outgoing voice; optional. */
  onset?: number;
}

export const RESTING_STAGE_STATE: FamiliarStageState = {
  working: false,
  speaking: false,
  level: 0,
  bands: null,
  onset: 0,
};

export function clampStageState(next: Partial<FamiliarStageState>): FamiliarStageState {
  const level = typeof next.level === "number" && Number.isFinite(next.level)
    ? Math.min(1, Math.max(0, next.level))
    : 0;
  const clamp01 = (value: unknown) =>
    typeof value === "number" && Number.isFinite(value)
      ? Math.min(1, Math.max(0, value))
      : 0;
  const bands = Array.isArray(next.bands) && next.bands.length === 8
    ? next.bands.map(clamp01)
    : null;
  return {
    working: next.working === true,
    speaking: next.speaking === true,
    level,
    bands,
    onset: clamp01(next.onset),
  };
}

/**
 * Derives the Stage's state from what ChatView already knows. The visual
 * renderer never parses chat events itself — activity arrives through this
 * one seam (and later through FamiliarState v2).
 */
export function familiarStateFromTurn(input: {
  loading: boolean;
  hasLiveEvents: boolean;
  liveEnded: boolean;
  voiceSpeaking: boolean;
  voiceLevel: number;
  voiceBands?: number[] | null;
  voiceOnset?: number;
}): FamiliarStageState {
  return clampStageState({
    working: input.loading || (input.hasLiveEvents && !input.liveEnded),
    speaking: input.voiceSpeaking,
    level: input.voiceLevel,
    bands: input.voiceBands ?? null,
    onset: input.voiceOnset,
  });
}

export interface FamiliarRendererStatus {
  kind: "webgl2";
  state: "mounted" | "running" | "suspended" | "failed" | "destroyed";
  /** Present only when state is "failed"; safe to log, never user content. */
  reason?: string;
}
