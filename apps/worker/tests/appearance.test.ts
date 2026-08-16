// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  APPEARANCE_KEYS,
  appearanceFromSettings,
  appearanceToSettings,
  loadAppearance,
  saveAppearanceLocal,
  toggleTheme,
} from "../src/theme";

beforeEach(() => {
  localStorage.clear();
  document.documentElement.className = "";
  document.documentElement.removeAttribute("style");
  for (const key of ["theme", "themePreference", "density", "contrast"]) {
    delete document.documentElement.dataset[key];
  }
  vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({
    matches: true,
    media: "(prefers-color-scheme: dark)",
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("worker appearance runtime", () => {
  it("round-trips the five documented kernel setting keys", () => {
    const appearance = appearanceFromSettings({
      theme: "light",
      density: "compact",
      font_scale: "1.1",
      "a11y.reduced_motion": "true",
      "a11y.high_contrast": true,
    });
    expect(appearance).toEqual({
      theme: "light",
      density: "compact",
      fontScale: "1.1",
      reducedMotion: true,
      highContrast: true,
    });
    expect(appearanceToSettings(appearance)).toEqual({
      [APPEARANCE_KEYS.theme]: "light",
      [APPEARANCE_KEYS.density]: "compact",
      [APPEARANCE_KEYS.fontScale]: "1.1",
      [APPEARANCE_KEYS.reducedMotion]: true,
      [APPEARANCE_KEYS.highContrast]: true,
    });
  });

  it("mirrors and applies all axes, resolving System without losing the preference", () => {
    saveAppearanceLocal({
      theme: "system",
      density: "compact",
      fontScale: "1.25",
      reducedMotion: true,
      highContrast: true,
    });

    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.dataset.themePreference).toBe("system");
    expect(document.documentElement.dataset.density).toBe("compact");
    expect(document.documentElement.dataset.contrast).toBe("high");
    expect(document.documentElement.style.getPropertyValue("--font-scale")).toBe("1.25");
    expect(document.documentElement.classList.contains("reduce-motion")).toBe(true);
    expect(loadAppearance().theme).toBe("system");
    expect(localStorage.getItem("boltrig-worker-theme")).toBe("system");
  });

  it("keeps the other axes when the conversation theme shortcut toggles", () => {
    saveAppearanceLocal({
      theme: "dark",
      density: "compact",
      fontScale: "0.9",
      reducedMotion: false,
      highContrast: true,
    });

    expect(toggleTheme()).toBe("light");
    expect(loadAppearance()).toMatchObject({
      theme: "light",
      density: "compact",
      fontScale: "0.9",
      highContrast: true,
    });
  });

});
