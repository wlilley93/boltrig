import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const sourceRoot = join(dirname(fileURLToPath(import.meta.url)), "../src");
const css = (path: string) => readFileSync(join(sourceRoot, path), "utf8");

const shellCss = css("components/ShellParity.css");
const inspectorCss = css("components/chat/TaskInspector.css");
const railCss = css("components/chat/ChatRailParity.css");
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

  it("keeps thin Chat on the shared canvas with compact type and a multiline dock", () => {
    expect(mobileCss).toMatch(/html:root\[data-theme\] \.mobile-surface[\s\S]*?--m-bg: var\(--bg\)/);
    expect(mobileCss).toMatch(/\.mobile-surface \.m-head[\s\S]*?44px/);
    expect(mobileCss).toMatch(/\.mobile-surface \.m-message > p[\s\S]*?font-size: 15px/);
    expect(mobileCss).toMatch(/\.mobile-surface \.m-composer[\s\S]*?min-height: 88px/);
    expect(mobileCss).toContain(".mobile-surface .m-composer-dock");
    expect(mobileCss).toContain(".mobile-surface .work-disclosure.transcript-tool-disclosure");
  });

  it("waits to inline task details until the full chat column and rail fit", () => {
    expect(workerCss).toContain("@media (max-width: 1374px)");
    expect(railCss).toContain("@media (max-width: 1374px)");
    expect(transcriptCss).toContain("@media (max-width: 1374px)");
    expect(railCss).toContain("grid-template-columns: minmax(793px, 1fr) auto");
    expect(inspectorCss).toContain(".task-inspector.right-rail.task-inspector--overlay");
    expect(inspectorCss).toContain("position: fixed;");
    expect(inspectorCss).toContain("transform: translateX(calc(100% + 20px))");
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
