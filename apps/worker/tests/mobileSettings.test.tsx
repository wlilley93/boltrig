// @vitest-environment happy-dom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// The detail screen renders the real console pane, which loads its readings on
// mount. These screens are about navigation and what is listed, so the SDK is
// stubbed rather than left to reach for a socket the runner has no business
// opening; the pane's own readings are covered by the pane's own tests.
vi.mock("../src/client", () => ({
  client: new Proxy({}, { get: () => () => new Promise(() => {}) }),
}));

import { MobileSettings } from "../src/components/MobileSettings";
import { SETTINGS_SECTIONS, settingsEntry } from "../src/settingsSections";

// The phone Settings screens. What matters is that the list is the real
// section registry rather than a hand-written copy, that opening a section
// reaches the same pane the console renders, and that back always names where
// it returns to — the target's whole navigation promise on a phone.

function phoneWidth() {
  vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => ({
    matches: query === "(max-width: 1020px)" || query === "(max-width: 640px)",
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })));
}

function renderSettings(onLeave = vi.fn()) {
  phoneWidth();
  render(
    <MobileSettings initials="WL" onLeave={onLeave} role="runs the place" user="will@acme.co" />,
  );
  return onLeave;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Worker mobile settings", () => {
  it("lists every registered section, so the phone cannot fall behind the console", () => {
    renderSettings();
    for (const entry of SETTINGS_SECTIONS) {
      expect(screen.getByRole("button", { name: new RegExp(entry.label, "i") })).toBeTruthy();
    }
    // The identity row shows who is signed in without printing a raw address
    // as the avatar.
    expect(screen.getByText("will@acme.co")).toBeTruthy();
    expect(screen.getByText("WL")).toBeTruthy();
  });

  it("opens a section onto the same pane the console renders, and comes back", () => {
    renderSettings();
    const target = SETTINGS_SECTIONS[1]!;
    fireEvent.click(screen.getByRole("button", { name: new RegExp(target.label, "i") }));

    const entry = settingsEntry(target.id);
    expect(screen.getByText(entry.title)).toBeTruthy();
    expect(screen.getByText(entry.lead)).toBeTruthy();
    // Back names its destination rather than showing a bare chevron.
    const back = screen.getByRole("button", { name: /Settings/ });
    fireEvent.click(back);
    expect(screen.getByText("Settings")).toBeTruthy();
    expect(screen.getByRole("button", { name: new RegExp(target.label, "i") })).toBeTruthy();
  });

  it("leaves for Today from the list, not from a section", () => {
    const onLeave = renderSettings();
    fireEvent.click(screen.getByRole("button", { name: /Today/ }));
    expect(onLeave).toHaveBeenCalledTimes(1);
  });
});
