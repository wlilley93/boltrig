// Who is on the Stage — and therefore whether there is anyone home.
//
// Emotion was modelled as a global add-on: the relay published a phenotype and
// whatever body was mounted consumed it. That was the wrong seam. An inner life
// belongs to a CHARACTER, not to an installation.
//
// The Familiar is a creature with its own private life. It wanders its own mood
// (see FamiliarWebGLRenderer's mood model) and is not wired to the appraisal
// engine — its state is its own, and always was.
//
// Jarvis is the opposite and that is the whole point of him: he reads the
// machine's measured affective state and his body displays it. He is the one
// allowed to have moods, because his are the only ones that are real.
//
// This file describes how each Stage renderer consumes presentation state. It
// does not participate in Chat dispatch or response generation.

import type { CharacterId } from "../character";

export interface Character {
  id: CharacterId;
  name: string;
  /**
   * Does this character read the server phenotype (decision 0013)?
   *
   * False does not mean "lifeless" — the Familiar still wanders. It means the
   * appraisal engine is not this character's source of truth, so handing it a
   * phenotype would be attributing the machine's mood to a creature that does
   * not have access to it.
   */
  readsPhenotype: boolean;
  blurb: string;
}

export const CHARACTERS: Record<CharacterId, Character> = {
  familiar: {
    id: "familiar",
    name: "Familiar",
    readsPhenotype: false,
    blurb: "A living body with a private inner life of its own.",
  },
  jarvis: {
    id: "jarvis",
    name: "Jarvis",
    readsPhenotype: true,
    blurb: "An instrument that displays the machine's measured state.",
  },
};

export function characterFor(body: CharacterId): Character {
  return CHARACTERS[body] ?? CHARACTERS.familiar;
}
