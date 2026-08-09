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
}

export const RESTING_STAGE_STATE: FamiliarStageState = {
  working: false,
  speaking: false,
  level: 0,
};

export function clampStageState(next: Partial<FamiliarStageState>): FamiliarStageState {
  const level = typeof next.level === "number" && Number.isFinite(next.level)
    ? Math.min(1, Math.max(0, next.level))
    : 0;
  return {
    working: next.working === true,
    speaking: next.speaking === true,
    level,
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
}): FamiliarStageState {
  return clampStageState({
    working: input.loading || (input.hasLiveEvents && !input.liveEnded),
    speaking: input.voiceSpeaking,
    level: input.voiceLevel,
  });
}

export interface FamiliarRendererStatus {
  kind: "webgl2";
  state: "mounted" | "running" | "suspended" | "failed" | "destroyed";
  /** Present only when state is "failed"; safe to log, never user content. */
  reason?: string;
}
