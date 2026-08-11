import { describe, expect, it } from "vitest";

import {
  GENE,
  GENE_COUNT,
  NEUTRAL_GENOTYPE,
  genotypeFrom,
} from "../src/components/jarvis/JarvisGenotype";

describe("jarvis genotype", () => {
  it("returns the hand-tuned neutral dial for an absent identity", () => {
    // Compared through Float32Array: the genes are stored at f32 precision, so
    // 0.55 is 0.550000011920929 by the time it reaches the GPU. Asserting
    // against f64 literals would fail on a correct value.
    const neutral = Float32Array.from(NEUTRAL_GENOTYPE);
    for (const absent of [null, undefined, ""]) {
      expect(genotypeFrom(absent)).toEqual(neutral);
    }
  });

  // The entire value of a genotype is recognising the same instrument again.
  // A hash that varied between sessions would be worse than none.
  it("is stable for the same identity", () => {
    const a = genotypeFrom("chief-of-staff");
    const b = genotypeFrom("chief-of-staff");
    expect(Array.from(a)).toEqual(Array.from(b));
  });

  it("gives different identities different dials", () => {
    const names = ["chief-of-staff", "researcher", "scheduler", "auditor"];
    const seen = new Set(names.map((n) => Array.from(genotypeFrom(n)).join(",")));
    expect(seen.size).toBe(names.length);
  });

  it("uploads as vec4[2]", () => {
    expect(genotypeFrom("anything").length).toBe(GENE_COUNT);
    expect(GENE_COUNT % 4).toBe(0);
  });

  // The variation must stay inside ranges the dial can survive. A negative
  // segment count or a zero speed would not be distinctive, it would be broken.
  it("keeps every gene inside a range the dial can render", () => {
    for (let i = 0; i < 400; i++) {
      const g = genotypeFrom(`agent-${i}`);
      expect(g[GENE.irisSegments]).toBeGreaterThanOrEqual(-4);
      expect(g[GENE.irisSegments]).toBeLessThanOrEqual(4);
      expect(g[GENE.dashSegments]).toBeGreaterThanOrEqual(-6);
      expect(g[GENE.dashSegments]).toBeLessThanOrEqual(6);
      expect(g[GENE.arc1Fill]).toBeGreaterThanOrEqual(0.42);
      expect(g[GENE.arc1Fill]).toBeLessThanOrEqual(0.68);
      expect(g[GENE.arc2Fill]).toBeGreaterThanOrEqual(0.36);
      expect(g[GENE.arc2Fill]).toBeLessThanOrEqual(0.62);
      // Speed must never reach zero, or the instrument stops dead.
      expect(g[GENE.speedSkew]).toBeGreaterThanOrEqual(0.8);
      expect(g[GENE.speedSkew]).toBeLessThanOrEqual(1.25);
      expect(g[GENE.tickDensity]).toBeGreaterThanOrEqual(-18);
      expect(g[GENE.tickDensity]).toBeLessThanOrEqual(18);
    }
  });

  // Base counts are 12 and 16; the offsets must never drive a ring to a
  // segment count the shader would have to clamp.
  it("never drives a segment count to something degenerate", () => {
    for (let i = 0; i < 200; i++) {
      const g = genotypeFrom(`n${i}`);
      expect(12 + g[GENE.irisSegments]).toBeGreaterThanOrEqual(8);
      expect(16 + g[GENE.dashSegments]).toBeGreaterThanOrEqual(10);
    }
  });
});
