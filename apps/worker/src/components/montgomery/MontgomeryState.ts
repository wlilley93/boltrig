// Turn facts -> what his body needs to draw itself.
//
// Kept here rather than in a shared module because there is no shared module
// in this build: he is the only frame-graph body that ships. When a second one
// lands, this is the part they share.
//
// NOT familiarStateFromTurn. That maps a CREATURE'S PRIVATE MOOD, and the
// Familiar deliberately does not read the appraisal engine. He does --
// `phenotype.reads` is true in his manifest -- so borrowing it would attribute
// a wandering inner life to a character whose whole point is that he responds
// to the machine's measured state.
import type { CharacterStageState, CharacterTurnInput } from "@wlilley93/boltrig-web-sdk";

export function montgomeryStateFromTurn(input: CharacterTurnInput): CharacterStageState {
  return {
    // A turn is in flight: he is at his desk, working.
    working: input.loading || (input.hasLiveEvents && !input.liveEnded),
    speaking: input.voiceSpeaking,
    // No amplitude channel on this input, so a floor rather than a guess: the
    // drive only reads it to tell a raised voice from an ordinary one.
    level: input.voiceSpeaking ? 0.5 : 0,
  };
}
