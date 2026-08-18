// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  APPEARANCE_KEYS,
  DEFAULT_APPEARANCE,
  appearanceFromSettings,
  appearanceToSettings,
  bootstrapAppearance,
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

  it("gives a first-run visitor dark, without a stored preference or a system hint", () => {
    // The defect this pins: the default was "system", so a first-run visitor on
    // a light Mac met a dark product in its light palette. Nothing is stored
    // here and no theme is passed - this is exactly what a new browser gets.
    localStorage.clear();
    expect(loadAppearance().theme).toBe("dark");
    bootstrapAppearance();
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.dataset.themePreference).toBe("dark");
  });

  it("still lets a person choose System, which is a preference and not the default", () => {
    saveAppearanceLocal({ ...DEFAULT_APPEARANCE, theme: "system" });
    expect(document.documentElement.dataset.themePreference).toBe("system");
    expect(loadAppearance().theme).toBe("system");
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
