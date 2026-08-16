import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(
  new URL("../src/components/chat/ComposerAddMenu.css", import.meta.url),
  "utf8",
);

describe("composer add menu styling", () => {
  it("stays compact, scrollable and motion-safe", () => {
    expect(css).toMatch(/\.composer-add-popover\s*\{[\s\S]*?width:\s*min\(318px/);
    expect(css).toMatch(/\.composer-add-scroll\s*\{[\s\S]*?overflow-y:\s*auto/);
    expect(css).toContain("overscroll-behavior: contain");
    expect(css).toContain("@media (prefers-reduced-motion: reduce)");
  });
});
