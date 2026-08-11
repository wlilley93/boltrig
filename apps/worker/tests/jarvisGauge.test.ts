import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import {
  gaugeArcs,
  WARN_FROM,
  WARN_TO,
} from "../src/components/jarvis/JarvisGauge";

describe("jarvis gauge arcs", () => {
  it("draws nothing at all for an unknown reading", () => {
    expect(gaugeArcs(0.7, false)).toEqual({ lap1: 0, lap2: 0, warn: 0 });
    expect(gaugeArcs(NaN, true)).toEqual({ lap1: 0, lap2: 0, warn: 0 });
  });

  it("fills the first lap proportionally", () => {
    expect(gaugeArcs(0, true).lap1).toBe(0);
    expect(gaugeArcs(0.26, true).lap1).toBeCloseTo(0.26, 6);
    expect(gaugeArcs(1, true).lap1).toBe(1);
  });

  // The whole point of the second lap: 114% must not render as 100%.
  it("puts an overrun on a second lap instead of pinning the first", () => {
    const over = gaugeArcs(1.14, true);
    expect(over.lap1).toBe(1);
    expect(over.lap2).toBeCloseTo(0.14, 6);

    const full = gaugeArcs(1.0, true);
    expect(full.lap2).toBe(0);
    expect(over.lap2).not.toBe(full.lap2);
  });

  it("clamps a runaway overrun to one extra lap", () => {
    expect(gaugeArcs(3.5, true).lap2).toBe(1);
    expect(gaugeArcs(50, true).lap2).toBe(1);
  });

  it("raises the dash warning only as the ceiling approaches", () => {
    expect(gaugeArcs(0.5, true).warn).toBe(0);
    expect(gaugeArcs(WARN_FROM, true).warn).toBe(0);
    expect(gaugeArcs(0.95, true).warn).toBeGreaterThan(0);
    expect(gaugeArcs(WARN_TO, true).warn).toBe(1);
  });

  it("never returns a negative arc for a negative fill", () => {
    const g = gaugeArcs(-5, true);
    expect(g.lap1).toBe(0);
    expect(g.lap2).toBe(0);
  });

  // The shader draws; this module defines. If the shader's thresholds drift,
  // the tests above stop describing what is actually on screen.
  it("agrees with the thresholds compiled into the shader", () => {
    const shader = readFileSync(
      fileURLToPath(new URL("../src/components/jarvis/jarvis.frag", import.meta.url)),
      "utf8",
    );
    const warn = shader.match(/smoothstep\(([0-9.]+),\s*([0-9.]+),\s*fill\)/);
    expect(warn, "jarvis.frag no longer derives `warn` from fill").toBeTruthy();
    expect(Number(warn![1])).toBe(WARN_FROM);
    expect(Number(warn![2])).toBe(WARN_TO);
  });
});
