import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const css = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../src/components/chat/ChatRailParity.css"),
  "utf8",
);

function relativeLuminance(hex: string) {
  const channels = [1, 3, 5]
    .map((offset) => Number.parseInt(hex.slice(offset, offset + 2), 16) / 255)
    .map((channel) => channel <= 0.04045
      ? channel / 12.92
      : ((channel + 0.055) / 1.055) ** 2.4);
  return 0.2126 * channels[0]! + 0.7152 * channels[1]! + 0.0722 * channels[2]!;
}

function contrast(foreground: string, background: string) {
  const lighter = Math.max(relativeLuminance(foreground), relativeLuminance(background));
  const darker = Math.min(relativeLuminance(foreground), relativeLuminance(background));
  return (lighter + 0.05) / (darker + 0.05);
}

describe("Chat rail parity CSS", () => {
  it("floats one borderless glass surface over a transparent rail column", () => {
    expect(css).toContain(".right-rail:not(.task-details-sheet) {");
    expect(css).toContain("grid-template-columns: minmax(0, 1fr) 316px");
    expect(css).toContain("width: 316px");
    expect(css).toContain("padding: 16px 12px 12px 2px");
    expect(css).toContain("background: transparent;");
    expect(css).toContain("> .chat-rail-glass");
    expect(css).toContain("width: 302px;");
    expect(css).toContain("max-width: 100%;");
    expect(css).toContain("border: 0;");
    expect(css).toContain("border-radius: 20px;");
    expect(css).toContain("backdrop-filter: blur(22px) saturate(125%);");
    expect(css).toContain("color-mix(in srgb, #2d2d2d 76%, transparent)");
  });

  it("uses inset internal separators without outlining the floating surface", () => {
    expect(css).toContain(".rail-group + .rail-group");
    expect(css).toContain("border-top: 0;");
    expect(css).toContain(".rail-group + .rail-group::before");
    expect(css).toContain("right: 14px;");
    expect(css).toContain("min-height: 35px;");
    expect(css).toContain("padding: 7px 15px 8px;");
  });

  it("keeps muted group labels readable over the brightest dark glass glint", () => {
    expect(css).toMatch(/data-theme="dark"[\s\S]*?rail-group-head > span[\s\S]*?color:\s*#9a9a9a/);
    expect(contrast("#9a9a9a", "#313131")).toBeGreaterThanOrEqual(4.5);
  });

  it("keeps compact task details as one borderless floating glass object", () => {
    expect(css).toContain("@media (max-width: 1020px)");
    expect(css).toContain(".right-rail.task-details-sheet {");
    expect(css).toContain("max-height: calc(100dvh - 20px);");
    expect(css).toContain(".right-rail.task-details-sheet > .chat-rail-glass");
    expect(css).toContain(".right-rail.task-details-sheet .task-details-header .eyebrow");
  });
});
