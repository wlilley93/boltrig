/**
 * The familiar's whole claim is that the picture is EVIDENCE about the agent, not decoration.
 * That claim is only true while three properties hold, and none of them is self-evident from
 * reading the code, so each one is pinned here.
 *
 *   1. Same agent, same body. Forever, and on both sides of the wire.
 *   2. Same role, same family. Otherwise "that's a reviewer" is not a thing you can learn.
 *   3. Different agent, different body. Otherwise the family is all you ever see, and the
 *      familiar stops identifying anything - which is exactly Codex's bag of eight.
 *
 * Property 3 is the one that would rot silently. Narrow a band while tuning how a role looks,
 * and every agent in it converges to the same shape; nothing errors, the UI still renders,
 * and the feature quietly becomes decoration. So it is measured, with a threshold.
 */

import { describe, expect, it } from "vitest";

import {
  bandForRole,
  deriveGenotype,
  GENOTYPE_DEFAULTS,
  GENOTYPE_SLOTS,
  GENOTYPE_VEC4S,
  packGenotype,
  MAGENTA_WEDGE,
  ROLE_BANDS,
  type Genotype,
} from "@/familiar/genotype";

const agents = (role: string, n: number) =>
  Array.from({ length: n }, (_, i) => ({ id: `agent-${role}-${i}`, role }));

/** Distance between two bodies, over the genes that actually change the silhouette. */
function bodyDistance(a: Genotype, b: Genotype): number {
  let d = 0;
  for (const k of GENOTYPE_SLOTS) d += Math.abs(a[k] - b[k]);
  return d;
}

describe("genotype derivation", () => {
  it("is deterministic: the same agent always gets the same body", () => {
    const a = { id: "agent-7", role: "reviewer" };
    const first = deriveGenotype(a);
    for (let i = 0; i < 25; i++) expect(deriveGenotype(a)).toEqual(first);
  });

  it("does not depend on object identity or on extra fields", () => {
    expect(deriveGenotype({ id: "x", role: "builder" })).toEqual(
      deriveGenotype({ id: "x", role: "builder", familiar: null }),
    );
  });

  it("puts every agent of a role in the same shape family", () => {
    for (const role of ["researcher", "reviewer", "builder", "guardian", "analyst"]) {
      const shapes = new Set(agents(role, 40).map((a) => deriveGenotype(a).shape));
      expect(shapes, `${role} must be one family`).toEqual(new Set([ROLE_BANDS[role].shape]));
    }
  });

  it("gives agents in the same role visibly different bodies", () => {
    // The failure this catches is a band tuned so tight that every agent in it collapses onto
    // one shape. That renders fine and looks fine and is the exact thing the design rejects,
    // so "it still draws something" is not evidence and a number is.
    for (const role of ["researcher", "reviewer", "builder", "analyst"]) {
      const gs = agents(role, 12).map(deriveGenotype);
      let collisions = 0;
      for (let i = 0; i < gs.length; i++)
        for (let j = i + 1; j < gs.length; j++)
          if (bodyDistance(gs[i], gs[j]) < 0.02) collisions++;
      expect(collisions, `${role} bodies are too alike to tell apart`).toBe(0);
    }
  });

  it("keeps reviewers on the near side of the part, because one agent is one body", () => {
    // The original reason was that a parted body had no nucleus and rendered at 5.9% lit.
    // That is fixed upstream (12.9% lit, peak 239), so the reason is now a design one and
    // this test guards the design: a parted body reads as TWO beings, and two blobs in a
    // 24px avatar say "two agents" to every glance. Reserved for something genuinely plural.
    for (const a of agents("reviewer", 60)) {
      const g = deriveGenotype(a);
      expect(g.focal).toBeLessThan(g.cassiniB);
    }
  });

  it("gives an unknown role the generic circle rather than a guess", () => {
    expect(bandForRole("wibble")).toBe("default");
    expect(bandForRole(null)).toBe("default");
    expect(deriveGenotype({ id: "q", role: "wibble" }).shape).toBe(0);
  });

  it("lets an authored familiar beat the derivation outright", () => {
    const derived = deriveGenotype({ id: "z", role: "builder" });
    const authored = deriveGenotype({ id: "z", role: "builder", familiar: { shape: 1, focal: 0.83 } });
    expect(authored.shape).toBe(1);
    expect(authored.focal).toBeCloseTo(0.83);
    // Genes the author did not mention keep the derived value, so a one-line override does
    // not silently reset the rest of the body to defaults.
    expect(authored.superM).toBe(derived.superM);
  });

  it("rounds superM to an integer, because a gear with 6.4 teeth is a smear", () => {
    for (const a of agents("builder", 20)) {
      const m = deriveGenotype(a).superM;
      expect(Number.isInteger(m)).toBe(true);
    }
  });

  it("packs genes into the uniform in slot order, filling every named slot", () => {
    const g = deriveGenotype({ id: "p", role: "analyst" });
    const packed = packGenotype(g);
    GENOTYPE_SLOTS.forEach((k, i) => {
      if (k === null) return;
      expect(packed[i], `slot ${i} carries ${k}`).toBeCloseTo(g[k], 5);
    });
    // This assertion has now gone stale TWICE by naming a number: `toBe(0)` on slots 14/15
    // until hue and saturation claimed them, then `toBe(16)` until the interior genes grew it
    // to 24. Both failures were correct and both were noise - the property being guarded was
    // never the count, it is that the packed buffer and the slot list agree and that the
    // uniform is a whole number of vec4s. Stated structurally, it stops going stale.
    expect(packed.length).toBe(GENOTYPE_VEC4S * 4);
    expect(GENOTYPE_SLOTS.length).toBe(packed.length);
    // A RESERVED SLOT UPLOADS 1, NOT 0, and this line replaces one that asserted the opposite.
    // The old version described the reserved slots as a TAIL beyond the named list and required
    // them to stay zero. Both halves were wrong, and the second was the more expensive: a
    // reserved slot's default in genotype.h is 1.0f, because every gene that has ever claimed
    // one has been a multiplier. Requiring zero here made the packer's zero fill look correct
    // right up to the moment bodyScale claimed slot 25, at which point the console multiplied
    // every familiar's radius by zero and this test stayed green. See slot-table.test.ts, which
    // now parses genotype.h so neither list can drift from the other again.
    GENOTYPE_SLOTS.forEach((k, i) => {
      if (k !== null) return;
      expect(packed[i], `reserved slot ${i} must upload the header's 1.0, not a zero fill`).toBe(1);
    });
  });

  it("degrades a malformed authored genotype to the circle rather than to a black hole", () => {
    const g = deriveGenotype({
      id: "bad",
      role: "orchestrator",
      familiar: { focal: NaN, aspect: Infinity } as never,
    });
    const packed = packGenotype(g);
    expect([...packed].every(Number.isFinite)).toBe(true);
    expect(packed[0]).toBe(GENOTYPE_DEFAULTS.shape);
  });
});

describe("the magenta wedge is reserved", () => {
  it("keeps every role's hue band out of it", () => {
    // Prose would not hold this. The wedge exists because the shader spends magenta on
    // irritation and the phenotype raises irritation for exactly one state - a failed run -
    // which makes "magenta means failed" the only signal on the screen that is learnable at a
    // glance across a fleet. A role seeded inside the wedge would sit at rest looking exactly
    // like an agent whose run had just died, and identity would be quietly destroying the alarm.
    const [lo, hi] = MAGENTA_WEDGE;
    for (const [role, band] of Object.entries(ROLE_BANDS)) {
      const h = band.ranges.hue;
      if (!h) continue;
      const overlaps = h[0] < hi && h[1] > lo;
      expect(overlaps, `${role} hue ${JSON.stringify(h)} enters the reserved magenta wedge`).toBe(false);
    }
  });

  it("keeps derived agents out of it too, not just the band edges", () => {
    // The band could clear the wedge while a gene drawn from it lands inside, if the range
    // were ever written backwards. Cheap to check against the thing that actually renders.
    const [lo, hi] = MAGENTA_WEDGE;
    for (const role of Object.keys(ROLE_BANDS)) {
      for (let i = 0; i < 40; i++) {
        const h = deriveGenotype({ id: `${role}-${i}`, role }).hue;
        expect(h < lo || h > hi, `${role}-${i} derived hue ${h.toFixed(3)} is in the wedge`).toBe(true);
      }
    }
  });

  it("gives each role a visibly different hue from the others", () => {
    // Colour is only worth spending if the roles are separable by it. The bands are placed so
    // the worst-case adjacent pair is 0.40 rad (~23 degrees) apart; 0.35 is the floor asserted.
    const hues = Object.keys(ROLE_BANDS)
      .filter((r) => r !== "default" && ROLE_BANDS[r].ranges.hue)
      .map((r) => deriveGenotype({ id: "x", role: r }).hue)
      .sort((a, b) => a - b);
    for (let i = 1; i < hues.length; i++) {
      expect(hues[i] - hues[i - 1], `hues ${hues[i - 1]} and ${hues[i]} are too close`)
        .toBeGreaterThan(0.35);
    }
  });
});
