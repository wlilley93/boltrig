import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { GAUGE_RADII, LABEL_CAP_H, R_OUTER, RADII, SVG_UNITS, toSvg }
  from "../src/components/jarvis/geometry";

// jarvis.frag cannot import anything, so its radii are duplicated in
// geometry.ts and only a comment holds them together. A comment is not a test.
// If the shader's outer ring moves and geometry.ts does not, the SVG labels
// silently slide off the ring they are supposed to sit on — and nothing else in
// the suite would notice, because both files stay individually valid.
const SHADER = readFileSync(
  fileURLToPath(new URL("../src/components/jarvis/jarvis.frag", import.meta.url)),
  "utf8",
);

function shaderConst(name: string): number {
  const match = SHADER.match(
    new RegExp(`const\\s+float\\s+${name}\\s*=\\s*(-?[0-9.]+)\\s*;`),
  );
  if (!match) throw new Error(`jarvis.frag has no const float ${name}`);
  return Number(match[1]);
}

describe("jarvis geometry stays in step with the shader", () => {
  it("agrees on the outer ring, which is where the labels sit", () => {
    expect(shaderConst("R_OUTER")).toBe(R_OUTER);
  });

  it("agrees on every radius geometry.ts republishes", () => {
    const pairs: [string, number][] = [
      ["R_CORE", RADII.core],
      ["R_IRIS", RADII.iris],
      ["R_FAN_IN", RADII.fanIn],
      ["R_FAN_OUT", RADII.fanOut],
      ["R_DASH2", RADII.dash2],
      ["R_HAIRCIRC", RADII.hairCircle],
      ["R_GAUGE", RADII.gauge],
      ["R_ARC1", RADII.arc1],
      ["R_ARC2", RADII.arc2],
      ["R_OUTER", RADII.outer],
    ];
    for (const [name, expected] of pairs) {
      expect(shaderConst(name), `${name} drifted`).toBe(expected);
    }
  });

  // The legends are positioned from these, so a drift here puts the word
  // "SPEND" next to the wrong ring — worse than no legend at all.
  it("agrees on the gauge track radii the legends are placed from", () => {
    expect(shaderConst("R_G_BUDGET")).toBe(GAUGE_RADII.budget);
    expect(shaderConst("R_G_TOKEN")).toBe(GAUGE_RADII.tokens);
  });

  // The SVG overlay sizes its type in these units, so a change to the shader's
  // cap height without a matching change here makes the two label paths
  // different sizes.
  it("agrees on the label cap height", () => {
    const match = SHADER.match(/float\s+capH\s*=\s*([0-9.]+)\s*;/);
    expect(match, "jarvis.frag no longer declares capH").toBeTruthy();
    expect(Number(match![1])).toBe(LABEL_CAP_H);
  });

  // The overlay's viewBox is "-50 -50 100 100" with xMidYMid meet, which maps
  // 100 SVG units onto the short side — the same normalisation the shader does
  // with min(iResolution). If SVG_UNITS ever stops being 100, that viewBox has
  // to change with it.
  it("keeps the 100-unit convention the label viewBox depends on", () => {
    expect(SVG_UNITS).toBe(100);
    expect(toSvg(R_OUTER)).toBeCloseTo(40.3, 6);
  });
});
