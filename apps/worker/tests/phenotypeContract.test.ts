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
  // MOVED HERE 2026-08-17, reversing the 2026-08-11 decision below.
  //
  // The argument for excluding her was that handing the appraisal engine's state
  // to a creature with no access to it attributes the machine's feelings to
  // something that cannot see the machine -- and that she was not lifeless
  // without it, because her renderer wanders its own mood.
  //
  // Both halves of that are still true, and neither was the whole picture:
  // familiar.frag has declared uValence, uArousal, uIrritation, uFatigue,
  // uAttention, uSocial, uBuoyancy, uLuminosity and uTension since it was
  // written, and her manifest has always listed all nine. So the real choice was
  // never whether she has an inner life -- it was whether nine uniforms built to
  // show a MEASURED one were shown a measured one or a wander. The wander is
  // still the fallback when the relay is absent or stale, which is what makes
  // this safe: nothing about her at rest changed.
  familiar: familiarBundle,
} as const;

const HAS_ITS_OWN_INNER_LIFE = {
  // ONE left, and his exclusion is the durable kind. Familiar's was a decision
  // that could be reversed and has been; his is written into his constitution --
  // his calm is not a performance and he has no competing impulse to suppress,
  // so there is no irritated variant of a stability report to colour a panel
  // with. A phenotype would concede moods he does not have.
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
