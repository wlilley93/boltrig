import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(
  new URL("../src/components/onboarding/onboarding.css", import.meta.url),
  "utf8",
);

describe("onboarding motion and layout contract", () => {
  it("stages slide-and-rise motion with a reduced-motion fallback", () => {
    expect(css).toContain("@keyframes onboarding-slide-in");
    expect(css).toContain("@keyframes onboarding-rise");
    expect(css).toContain("prefers-reduced-motion: reduce");
  });

  // The step is a RAIL now: one card, chevrons either side, dots beneath. The
  // two-up grid is gone and so is the selected-card ring -- the card on screen
  // IS the selection, so an accent ring on the only card there is tells you
  // nothing. What must survive is that the card stays responsive.
  it("lays the companion step out as a rail and keeps it responsive", () => {
    expect(css).toContain(".companion-rail");
    expect(css).toContain(".companion-viewport");
    expect(css).toContain(".companion-chevron");
    expect(css).toContain(".companion-dot");
    expect(css).toContain("@media (max-width: 720px)");
    // The grid is not merely unused; leaving it behind would have two layouts
    // competing for the same card.
    expect(css).not.toContain(".companion-grid");
  });

  // The skin pills live inside the card, and the dark Jarvis treatment has to
  // reach them or they render as light-theme chips on a near-black surface.
  it("styles the skin pills, including on the dark Jarvis card", () => {
    expect(css).toContain(".skin-pill");
    expect(css).toContain('.companion-card[data-companion="jarvis"] .skin-pill');
  });
});
