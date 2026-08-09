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

export interface FamiliarRendererStatus {
  kind: "webgl2";
  state: "mounted" | "running" | "suspended" | "failed" | "destroyed";
  /** Present only when state is "failed"; safe to log, never user content. */
  reason?: string;
}
