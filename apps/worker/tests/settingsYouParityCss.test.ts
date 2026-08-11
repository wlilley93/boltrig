import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const css = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../src/components/settings/settings-you.css"),
  "utf8",
);

describe("Settings / You parity CSS", () => {
  it("keeps the Figma section rhythm independent of shared block margins", () => {
    expect(css).toContain(".settings-you-pane {");
    expect(css).toContain("gap: 28px;");
    expect(css).toContain(".settings-you-pane > .settings-head,");
    expect(css).toContain("margin-bottom: 0;");
  });

  it("keeps the You pane on the base canvas and removes only its scrollbar gutter", () => {
    expect(css).toContain(".page:has(.settings-you-pane)");
    expect(css).toContain("background: var(--bg);");
    expect(css).toContain("scrollbar-width: none;");
    expect(css).toContain(".page:has(.settings-you-pane)::-webkit-scrollbar");
    expect(css).toContain("display: none;");
  });
});
