import { describe, expect, it } from "vitest";

import colossusBundle from "../src/bundles/colossus/character.json";
import familiarBundle from "../src/bundles/familiar/character.json";
import jarvisBundle from "../src/bundles/jarvis/character.json";
import ultronBundle from "../src/bundles/ultron/character.json";

/**
 * Which bodies read the machine's measured mood, and which deliberately do not.
 *
 * EMOTION IS PER-CHARACTER, NOT PER-INSTALLATION. That is the whole argument in
 * components/characters.ts: the relay used to publish a phenotype and whatever
 * body was mounted consumed it, which attributed the machine's mood to
 * creatures that have no access to it. So this is a per-character CLAIM, and a
 * claim needs a test or it is a comment.
 *
 * The absence is as meaningful as the presence, and is the easier one to break
 * by accident: a bundle that grows a `phenotype` block starts displaying the
 * appraisal engine's state, and nothing else in the build would object.
 */

const READS_THE_MACHINE_MOOD = {
  // He IS the instrument for the machine's measured state. Both his skins read
  // it -- the dial shows it and the neural field colours with it.
  jarvis: jarvisBundle,
  // Blue, organic, and it lands on how fast he comes apart rather than on hue.
  ultron: ultronBundle,
} as const;

const HAS_ITS_OWN_INNER_LIFE = {
  // She wanders her own mood and always did. Handing her the appraisal engine's
  // state would attribute the machine's feelings to a creature that cannot see
  // the machine.
  familiar: familiarBundle,
  // And he is excluded for the OPPOSITE reason, which is why the two sit in the
  // same map and mean different things. She is excluded because she has an
  // inner life the appraisal engine cannot see; he is excluded because he has
  // one register. His constitution is explicit that his calm is not a
  // performance and that he has no competing impulse to suppress, so there is
  // no irritated variant of a stability report to colour a panel with.
  colossus: colossusBundle,
} as const;

describe("the phenotype contract, per character", () => {
  for (const [name, bundle] of Object.entries(READS_THE_MACHINE_MOOD)) {
    it(`${name} declares that it reads the phenotype`, () => {
      expect((bundle as { phenotype?: { reads?: boolean } }).phenotype?.reads).toBe(true);
    });
  }

  for (const [name, bundle] of Object.entries(HAS_ITS_OWN_INNER_LIFE)) {
    it(`${name} OMITS the phenotype block entirely`, () => {
      // Omitted, not `{reads: false}`. The schema is explicit that absence is
      // the encoding, and an empty block invites someone to "complete" it.
      expect((bundle as { phenotype?: unknown }).phenotype).toBeUndefined();
    });
  }

  it("every shipped character is accounted for, so a new one cannot be silent", () => {
    // The point of the test. Adding a character without deciding this leaves it
    // out of both maps and fails HERE, rather than shipping a body whose
    // relationship to the appraisal engine nobody chose.
    const decided = new Set([
      ...Object.keys(READS_THE_MACHINE_MOOD),
      ...Object.keys(HAS_ITS_OWN_INNER_LIFE),
    ]);
    const shipped = [familiarBundle, jarvisBundle, ultronBundle, colossusBundle]
      .map((bundle) => (bundle as { id: string }).id);
    expect([...shipped].sort()).toEqual([...decided].sort());
  });
});
