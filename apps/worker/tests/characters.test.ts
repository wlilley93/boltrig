import { describe, expect, it } from "vitest";

import {
  CHARACTERS,
  characterFor,
} from "../src/components/characters";

describe("characters", () => {
  // The inversion this file exists for: emotion belongs to whoever is speaking,
  // not to the installation.
  it("gives the phenotype only to the character who can actually read it", () => {
    expect(CHARACTERS.jarvis.readsPhenotype).toBe(true);
    expect(CHARACTERS.familiar.readsPhenotype).toBe(false);
  });

  // Not "lifeless" — the Familiar's renderer wanders its own mood. It simply is
  // not wired to the appraisal engine.
  it("does not claim either Stage body changes response prose", () => {
    expect(CHARACTERS.familiar).not.toHaveProperty("persona");
    expect(CHARACTERS.jarvis).not.toHaveProperty("persona");
  });

  it("falls back to the Familiar for an unknown body", () => {
    expect(characterFor("nonsense" as never).id).toBe("familiar");
  });
});
