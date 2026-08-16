import { describe, expect, it } from "vitest";

import {
  characterFor,
  isRegistered,
  listCharacters,
  registerCharacter,
} from "../src/components/characters";
import "../src/characterPlugins";

describe("the character registry", () => {
  // The inversion this file exists for: emotion belongs to whoever is speaking,
  // not to the installation.
  it("gives the phenotype only to the character who can actually read it", () => {
    expect(characterFor("jarvis").readsPhenotype).toBe(true);
    expect(characterFor("familiar").readsPhenotype).toBe(false);
  });

  it("ships Familiar and Jarvis only through the production plugin join", () => {
    expect(listCharacters().map((c) => c.id).sort()).toEqual(["familiar", "jarvis"]);
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
