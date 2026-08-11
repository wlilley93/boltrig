// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  CHARACTER_CHANGE_EVENT,
  CHARACTER_SETTING_KEY,
  DEFAULT_CHARACTER,
  applyCharacter,
  bootstrapCharacter,
  characterFromSettings,
  characterToSettings,
  loadCharacter,
  saveCharacterLocal,
} from "../src/character";
import { appearanceToSettings, loadAppearance } from "../src/theme";

beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-character");
});
afterEach(() => localStorage.clear());

describe("the character on the Stage", () => {
  it("defaults to the Familiar, so no install changes Stage body on upgrade", () => {
    expect(DEFAULT_CHARACTER).toBe("familiar");
    expect(loadCharacter()).toBe("familiar");
    expect(characterFromSettings({})).toBe("familiar");
  });

  // The store validates SHAPE, not existence. Whether an id names a character
  // anyone can draw belongs to the registry, which resolves an unknown id to
  // the default at render time — so uninstalling a character's plugin costs the
  // Stage its body without corrupting the setting or losing the choice if it is
  // installed again.
  it("rejects a malformed id but keeps a well-formed one it does not know", () => {
    for (const bad of [42, null, "", "Not An Id!", "x".repeat(80)]) {
      expect(characterFromSettings({ [CHARACTER_SETTING_KEY]: bad })).toBe("familiar");
    }
    expect(characterFromSettings({ [CHARACTER_SETTING_KEY]: "some-plugin" }))
      .toBe("some-plugin");
  });

  it("round-trips through the kernel settings bag", () => {
    const settings = characterToSettings("jarvis");
    expect(settings[CHARACTER_SETTING_KEY]).toBe("jarvis");
    expect(characterFromSettings(settings)).toBe("jarvis");
  });

  // The character owns a separate persistence/event lifecycle. Appearance's
  // five-axis payload must not silently absorb it during unrelated writes.
  it("stays out of the appearance payload entirely", () => {
    saveCharacterLocal("jarvis");
    const payload = appearanceToSettings(loadAppearance());
    expect(Object.keys(payload)).not.toContain(CHARACTER_SETTING_KEY);
    expect(JSON.stringify(payload)).not.toContain("jarvis");
  });

  it("survives a reload and publishes itself on the document", () => {
    saveCharacterLocal("jarvis");
    expect(loadCharacter()).toBe("jarvis");
    expect(document.documentElement.dataset.character).toBe("jarvis");
  });

  it("bootstraps the locally cached Stage before React mounts", () => {
    saveCharacterLocal("jarvis");
    document.documentElement.removeAttribute("data-character");

    expect(bootstrapCharacter()).toBe("jarvis");
    expect(document.documentElement.dataset.character).toBe("jarvis");
  });

  it("announces changes so a Stage elsewhere can swap without a reload", () => {
    const seen: string[] = [];
    const onChange = (e: Event) => seen.push((e as CustomEvent<string>).detail);
    document.addEventListener(CHARACTER_CHANGE_EVENT, onChange);
    applyCharacter("jarvis");
    applyCharacter("familiar");
    document.removeEventListener(CHARACTER_CHANGE_EVENT, onChange);
    expect(seen).toEqual(["jarvis", "familiar"]);
  });
});
