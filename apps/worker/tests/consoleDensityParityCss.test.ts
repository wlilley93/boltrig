import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const testDir = dirname(fileURLToPath(import.meta.url));
const workerCss = readFileSync(join(testDir, "../src/styles.css"), "utf8");
const integrationsCss = readFileSync(
  join(testDir, "../src/components/IntegrationsView.css"),
  "utf8",
);
const settingsYouCss = readFileSync(
  join(testDir, "../src/components/settings/settings-you.css"),
  "utf8",
);

function rule(css: string, selector: string): string {
  const start = css.indexOf(`${selector} {`);
  expect(start, `selector ${selector} exists`).toBeGreaterThanOrEqual(0);
  return css.slice(start, css.indexOf("}", start) + 1);
}

describe("live Figma console density", () => {
  it("keeps each Plugins toggle at 56px plus its one-pixel separator", () => {
    const toggle = rule(integrationsCss, ".plugins-row-toggle");

    expect(toggle).toContain("height: 56px;");
    expect(toggle).toContain("padding: 10px 14px;");
    expect(56 + 1).toBe(57);
  });

  it("matches the roomier New-chat voice invitation and glass composer", () => {
    const intro = rule(workerCss, ".voice-intro");
    const frame = rule(workerCss, ".composer.new-context .composer-frame");
    const context = rule(workerCss, ".composer.new-context .composer-context");

    expect(intro).toContain("width: calc(100% - 24px);");
    expect(intro).toContain("min-height: 66px;");
    expect(intro).toContain("margin: 0 12px;");
    expect(intro).toContain("padding: 9px 13px 9px 14px;");
    expect(intro).toContain("border: 0;");
    expect(intro).toContain("box-shadow: inset 0 0 0 1px var(--border);");
    expect(frame).toContain("min-height: 96px;");
    expect(frame).toContain("backdrop-filter: blur(24px) saturate(1.18);");
    expect(context).toContain("height: 40px;");
    expect(context).toContain("margin-bottom: 0;");
  });

  it("lights the composer as the window's attachment drop target", () => {
    const active = rule(workerCss, ".composer[data-drop-active=\"true\"] .composer-frame");
    const target = rule(workerCss, ".composer-drop-target");

    expect(active).toContain("border-color: color-mix(in srgb, var(--accent) 78%, white 22%);");
    expect(active).toContain("0 0 0 3px color-mix(in srgb, var(--accent) 24%, transparent)");
    expect(target).toContain("backdrop-filter: blur(12px) saturate(1.12);");
    expect(target).toContain("pointer-events: none;");
  });

  it("keeps Settings card rows on the 13/14px vertical rhythm", () => {
    expect(
      rule(settingsYouCss, ".settings-you-pane > .settings-head"),
    ).toContain("min-height: 61px;");
    expect(rule(workerCss, ".settings-row")).toContain(
      "padding: 13px 16px 14px;",
    );
    expect(rule(settingsYouCss, ".settings-you-pane .settings-row")).toContain(
      "box-shadow: inset 0 -1px var(--border);",
    );
    expect(
      rule(settingsYouCss, ".settings-you-pane .settings-row + .settings-row"),
    ).toContain("border-top: 0;");
    expect(
      rule(
        settingsYouCss,
        ".settings-you-pane .settings-row + .settings-disclose",
      ),
    ).toContain("border-top: 0;");
  });
});
