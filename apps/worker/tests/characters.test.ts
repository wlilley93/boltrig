import { describe, expect, it } from "vitest";

import {
  characterFor,
  isRegistered,
  listCharacters,
  registerCharacter,
} from "../src/components/characters";
import "../src/characterPlugins";

describe("the character registry", () => {
  // Emotion belongs to whoever is speaking rather than to the installation, and
  // that is still the rule -- but it is a per-character DECLARATION, not a claim
  // that only one character may have one. Three of the four now read it; the
  // fourth refuses it in his constitution, which is the point.
  it("gives the phenotype to every character that declares it, and no other", () => {
    expect(characterFor("jarvis").readsPhenotype).toBe(true);
    expect(characterFor("ultron").readsPhenotype).toBe(true);
    // Reversed 2026-08-17: her shader was built for all nine scalars and was
    // being fed a wander instead. See familiarBundle.test.ts for the argument.
    expect(characterFor("familiar").readsPhenotype).toBe(true);
    // Colossus has ONE register by design and no irritated variant of a
    // stability report, so a phenotype would concede moods he does not have.
    expect(characterFor("colossus").readsPhenotype).toBe(false);
  });

  it("ships exactly the four stock bodies through the production plugin join", () => {
    expect(listCharacters().map((c) => c.id).sort())
      .toEqual(["colossus", "familiar", "jarvis", "ultron"]);
  });

  // Jarvis and Ultron are SEPARATE CHARACTERS, not one with two skins, and the
  // reference is why: Animal Logic coded JARVIS orange and angular and ULTRON
  // blue and organic. The gold hologram is Jarvis's own look in that film,
  // which is why it is a skin ON him and Ultron is his own entry.
  it("keeps the Age of Ultron look a skin of Jarvis, and Ultron a character", () => {
    const jarvis = characterFor("jarvis");
    expect(jarvis.skins?.map((skin) => skin.id)).toEqual(["default", "ultron"]);
    expect(characterFor("ultron").id).toBe("ultron");
    // Ultron has one body, so he declares no skins at all rather than one.
    expect(characterFor("ultron").skins).toBeUndefined();
  });

  // An uninstalled plugin, or a setting carried over from a build that shipped
  // one, must cost the Stage its body and nothing else.
  it("falls back to the default for an id nobody registered", () => {
    expect(isRegistered("nobody-shipped-this")).toBe(false);
    expect(characterFor("nobody-shipped-this").id).toBe("familiar");
  });

  it("lets a character install itself without core naming it", () => {
    const before = listCharacters().length;
    registerCharacter({
      id: "test-plugin",
      name: "Test Plugin",
      readsPhenotype: false,
      blurb: "Registered from outside core.",
      render: () => null,
    });
    expect(isRegistered("test-plugin")).toBe(true);
    expect(characterFor("test-plugin").name).toBe("Test Plugin");
    expect(listCharacters().length).toBe(before + 1);
  });

  it("only polls budgets for a character that asked for them", () => {
    expect(characterFor("jarvis").wantsBudgets).toBe(true);
    expect(characterFor("familiar").wantsBudgets).toBeUndefined();
  });
});
