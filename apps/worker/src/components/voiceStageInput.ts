// What a call tells the body on the Stage.
//
// LIFTED OUT OF THE COMPONENT because it is a pure mapping from four facts to
// the character contract, and it was sitting in the middle of a nine-hundred
// line function that also owns a WebSocket, an AudioContext and a reconnect
// state machine. Out here it can be read, and tested, without any of that.
//
// NOTHING BUT FACTS CROSS. Every field is a bounded number or a boolean about
// the call: no transcript, no participant identity, no credentials. That is the
// character contract's rule rather than a local preference -- a body registered
// by a plugin reads this same shape, and anything richer here would be a way to
// read somebody's conversation by declaring a stage.

import type { CallStatus, StageTurnInput } from "@wlilley93/boltrig-web-sdk";

/** The outgoing voice's measured features. Structural rather than an import of
 *  VoiceCall's own `VoiceFeatures`, which would make the module that calls this
 *  one a dependency of it -- a cycle, for a shape that is four numbers. */
interface SpokenFeatures {
  speaking: boolean;
  level: number;
  bands: number[];
  onset: number;
}

/** The statuses during which a call is CONNECTING rather than connected. */
const SETTLING: readonly (CallStatus | "idle")[] = ["creating", "joining", "reconnecting"];

/**
 * The statuses during which the microphone is actually open.
 *
 * `held` counts: the call is paused on an approval, the microphone is still
 * live, and a body that stopped attending there would look away at the moment
 * the person is most likely to say something. `creating` and `joining` do not:
 * there is nothing to listen with yet, and claiming otherwise has the body
 * attending to a room it has no connection to.
 */
const HEARING: readonly (CallStatus | "idle")[] = ["active", "held"];

export function voiceStageInput(call: {
  status: CallStatus | "idle";
  muted: boolean;
  micLevel: number;
  features: SpokenFeatures;
}): StageTurnInput {
  const { features, micLevel, muted, status } = call;
  const settling = !features.speaking && SETTLING.includes(status);
  return {
    loading: false,
    hasLiveEvents: settling,
    liveEnded: false,
    voiceSpeaking: features.speaking,
    voiceLevel: features.level,
    voiceBands: features.bands,
    voiceOnset: features.onset,
    micActive: !muted && HEARING.includes(status),
    micLevel,
    // THE FAILURE IS A STATE, not the absence of one. Every other field goes
    // quiet in exactly the same way whether a call ended or died, so without
    // this the body went calm at the moment the page said the call had dropped
    // -- the one moment it must not look serene.
    failed: status === "failed",
  };
}
