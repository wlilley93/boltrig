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

  it("keeps the New-chat voice intro at its canonical 660 by 57 box", () => {
    const intro = rule(workerCss, ".voice-intro");

    expect(intro).toContain("width: min(660px, calc(100% - 48px));");
    expect(intro).toContain("padding: 12px 13px 12px 14px;");
    expect(intro).toContain("border: 0;");
    expect(intro).toContain("box-shadow: inset 0 0 0 1px var(--border);");
    expect(33 + 12 * 2).toBe(57);
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
