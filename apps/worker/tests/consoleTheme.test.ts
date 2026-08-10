import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

// The console token contract: both themes must define the complete set the
// "Boltrig Console" design component binds against, and the legacy aliases
// must resolve into it rather than carrying their own colour values. A token
// defined in only one theme silently inherits the other theme's colour, which
// is exactly the class of drift this pins down.
const CONSOLE_TOKENS = [
  "--bg",
  "--side",
  "--card",
  "--card-2",
  "--inset",
  "--canvas",
  "--border",
  "--border-2",
  "--hover",
  "--text",
  "--text-2",
  "--text-3",
  "--text-4",
  "--accent",
  "--switch-off",
  "--seg-active",
  "--orange",
  "--green",
  "--amber",
  "--red",
  "--unknown",
  "--shadow",
];

const LEGACY_ALIASES = [
  "--paper",
  "--paper-2",
  "--ink",
  "--muted",
  "--line",
  "--line-strong",
  "--notice-ink",
  "--blue",
];

const css = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "../src/styles.css"),
  "utf-8",
);

function block(selector: string): string {
  const start = css.indexOf(`${selector} {`);
  expect(start, `selector ${selector} exists`).toBeGreaterThanOrEqual(0);
  return css.slice(start, css.indexOf("}", start) + 1);
}

describe("console theme tokens", () => {
  const light = block(":root");
  const dark = block(':root[data-theme="dark"]');

  it("defines every console token in the light theme", () => {
    for (const token of CONSOLE_TOKENS) {
      expect(light.includes(`${token}:`), `${token} in light`).toBeTruthy();
    }
  });

  it("defines every console token in the dark theme", () => {
    for (const token of CONSOLE_TOKENS) {
      expect(dark.includes(`${token}:`), `${token} in dark`).toBeTruthy();
    }
  });

  it("keeps the legacy aliases pointing at console tokens, not at colours", () => {
    for (const alias of LEGACY_ALIASES) {
      const match = light.match(new RegExp(`${alias}: ([^;]+);`));
      expect(match, `${alias} defined once, in the light block`).toBeTruthy();
      expect(
        /var\(--|color-mix\(/.test(match![1]),
        `${alias} resolves into a console token`,
      ).toBeTruthy();
      // The dark block must not redefine an alias: a dark-only alias value is
      // a second place a colour can live, and it would drift.
      expect(dark.includes(`${alias}:`), `${alias} absent from dark`).toBeFalsy();
    }
  });
});
