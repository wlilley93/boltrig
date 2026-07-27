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
  packGenotype,
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

  it("packs genes into the uniform in slot order, and never writes past the 14 named slots", () => {
    const g = deriveGenotype({ id: "p", role: "analyst" });
    const packed = packGenotype(g);
    expect(packed.length).toBe(16);
    GENOTYPE_SLOTS.forEach((k, i) => expect(packed[i]).toBeCloseTo(g[k], 5));
    // The last two slots are reserved. If something starts writing them, the shader will read
    // whatever it is as a gene it does not have, which is the kind of bug that shows up as
    // "the avatars look odd" three weeks later.
    expect(packed[14]).toBe(0);
    expect(packed[15]).toBe(0);
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
