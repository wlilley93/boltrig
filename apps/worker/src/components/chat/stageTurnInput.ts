import type { StageTurnInput } from "../StageBody";

/** The voice fields the stage reads. A subset of ChatView's voice activity. */
export interface StageVoiceActivity {
  speaking: boolean;
  level: number;
  bands?: number[];
  onset?: number;
  /** See CharacterTurnInput.speechTakeaway: a phrase, never the reply. */
  takeaway?: string | null;
}

/**
 * The turn facts both bodies read; StageBody picks which one depicts them.
 *
 * A pure mapping, out here rather than inline in ChatView, because ChatView is
 * pinned at an exact size by a ratchet the worker gate re-loads from Git and
 * refuses to let grow. Every field is a value the component already holds, so
 * nothing about the call site changed except its length.
 */
export function stageTurnInput(
  { loading, liveEventCount, liveEnded, voice }: {
    loading: boolean;
    liveEventCount: number;
    liveEnded: boolean;
    voice: StageVoiceActivity;
  },
): StageTurnInput {
  return {
    loading,
    hasLiveEvents: liveEventCount > 0,
    liveEnded,
    voiceSpeaking: voice.speaking,
    voiceLevel: voice.level,
    voiceBands: voice.bands ?? null,
    voiceOnset: voice.onset,
    speechTakeaway: voice.takeaway ?? null,
  };
}
