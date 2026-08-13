import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const sourceRoot = join(dirname(fileURLToPath(import.meta.url)), "../src");
const css = (path: string) => readFileSync(join(sourceRoot, path), "utf8");

const shellCss = css("components/ShellParity.css");
const inspectorCss = css("components/chat/TaskInspector.css");
const transcriptCss = css("components/chat/TranscriptNavigation.css");
const mobileCss = css("components/MobileChatParity.css");
const paletteCss = css("components/CommandPalette.css");
const workerCss = css("styles.css");

describe("responsive shell hardening", () => {
  it("keeps every floating phone edge inside safe-area insets", () => {
    for (const stylesheet of [inspectorCss, mobileCss, paletteCss]) {
      expect(stylesheet).toContain("env(safe-area-inset-top, 0px)");
      expect(stylesheet).toContain("env(safe-area-inset-right, 0px)");
      expect(stylesheet).toContain("env(safe-area-inset-bottom, 0px)");
      expect(stylesheet).toContain("env(safe-area-inset-left, 0px)");
    }
    expect(transcriptCss).toContain("env(safe-area-inset-right, 0px)");
    expect(transcriptCss).toContain("env(safe-area-inset-bottom, 0px)");
    expect(workerCss).toContain("env(safe-area-inset-top, 0px)");
    expect(workerCss).toContain("env(safe-area-inset-left, 0px)");
  });

  it("preserves 44px phone targets across shell, inspector, transcript and commands", () => {
    expect(shellCss).toMatch(/@media \(max-width: 640px\)[\s\S]*?min-height: 44px/);
    expect(inspectorCss).toMatch(/@media \(max-width: 640px\)[\s\S]*?min-height: 44px/);
    expect(transcriptCss).toMatch(/@media \(max-width: 640px\)[\s\S]*?width: 44px;[\s\S]*?height: 44px/);
    expect(paletteCss).toMatch(/@media \(max-width: 640px\)[\s\S]*?min-height: 44px/);
  });

  it("offers opaque fallbacks and removes glass effects when transparency is reduced", () => {
    expect(shellCss).toContain("@media (prefers-reduced-transparency: reduce)");
    expect(shellCss).toMatch(/prefers-reduced-transparency[\s\S]*?background: var\(--side\)/);
    expect(inspectorCss).toContain("@media (prefers-reduced-transparency: reduce)");
    expect(transcriptCss).toContain("@media (prefers-reduced-transparency: reduce)");
    for (const stylesheet of [shellCss, inspectorCss, transcriptCss]) {
      expect(stylesheet).toContain("@supports not ((-webkit-backdrop-filter:");
    }
  });
});
