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

  it("keeps companion cards responsive and visibly selected", () => {
    expect(css).toContain(".companion-grid");
    expect(css).toContain(".companion-card.selected");
    expect(css).toContain("@media (max-width: 720px)");
  });
});
