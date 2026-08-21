// @vitest-environment happy-dom

// Page modes (?theme= / ?embed=1): URL-carried, per-load, never persisted.
// An embedding host (the Opbox Agents panel) opens the worker with
// `?theme=light&embed=1`; the override clamps the stamped palette and hides
// the shell chrome without ever writing the person's saved preference.

import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  applyAppearance,
  bootstrapAppearance,
  forcedThemeOverride,
  isEmbedMode,
  loadAppearance,
  saveAppearanceLocal,
} from "../src/theme";
import { ThemeToggle } from "../src/components/chat/ThemeToggle";

function setPageUrl(pathAndQuery: string) {
  window.history.replaceState(null, "", pathAndQuery);
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.className = "";
  document.documentElement.removeAttribute("style");
  for (const key of ["theme", "themePreference", "density", "contrast", "embed"]) {
    delete document.documentElement.dataset[key];
  }
  setPageUrl("/");
  vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({
    matches: true,
    media: "(prefers-color-scheme: dark)",
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
});

afterEach(() => {
  vi.unstubAllGlobals();
  setPageUrl("/");
});

describe("?theme= page override", () => {
  it("clamps the stamped palette without touching the saved preference", () => {
    saveAppearanceLocal({ ...loadAppearance(), theme: "dark" });
    setPageUrl("/?theme=light");

    bootstrapAppearance();

    expect(document.documentElement.dataset.theme).toBe("light");
    // The preference attr and storage keep what the person chose.
    expect(document.documentElement.dataset.themePreference).toBe("dark");
    expect(loadAppearance().theme).toBe("dark");
  });

  it("survives the server-settings re-apply (saveAppearanceLocal re-stamps through the clamp)", () => {
    setPageUrl("/?theme=light");
    bootstrapAppearance();

    // CompactSections adopts kernel settings via saveAppearanceLocal - the
    // clamp must win again on that re-apply, not just at boot.
    saveAppearanceLocal({ ...loadAppearance(), theme: "dark" });

    expect(document.documentElement.dataset.theme).toBe("light");
    expect(loadAppearance().theme).toBe("dark");
  });

  it("ignores an invalid value", () => {
    setPageUrl("/?theme=neon");
    expect(forcedThemeOverride()).toBeNull();
    bootstrapAppearance();
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("hides the ThemeToggle while forced - toggling would write a preference the person never chose", () => {
    setPageUrl("/?theme=light");
    const { container } = render(<ThemeToggle />);
    expect(container.innerHTML).toBe("");
    expect(screen.queryByRole("button", { name: "Toggle theme" })).toBeNull();
  });

  it("keeps the ThemeToggle without the override", () => {
    render(<ThemeToggle />);
    expect(screen.getByRole("button", { name: "Toggle theme" })).toBeTruthy();
  });
});

describe("?embed=1 mode", () => {
  it("stamps data-embed so the shell chrome CSS can hide", () => {
    setPageUrl("/?embed=1");
    expect(isEmbedMode()).toBe(true);
    bootstrapAppearance();
    expect(document.documentElement.dataset.embed).toBe("");
  });

  it("does not stamp (and clears a stale stamp) without the param", () => {
    document.documentElement.dataset.embed = "";
    applyAppearance(loadAppearance());
    expect("embed" in document.documentElement.dataset).toBe(false);
    expect(isEmbedMode()).toBe(false);
  });

  it("only accepts embed=1, not any truthy string", () => {
    setPageUrl("/?embed=true");
    expect(isEmbedMode()).toBe(false);
  });
});
