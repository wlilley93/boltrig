/**
 * THE TWO SLOT TABLES MUST AGREE, AND BEING CAREFUL IS NOT A MECHANISM.
 *
 * `uniform vec4 uGene[]` is read POSITIONALLY by the shader. Nothing about slot 24 says
 * "tempoBase"; the shader simply reads `uGene[6].x` and the packer simply writes index 24, and
 * the only thing that makes those the same gene is that two hand-written lists in two
 * repositories happen to line up.
 *
 * On 2026-07-27 they stopped lining up, and this test exists because of it. `genotype.h` pads
 * its table with NULL entries so that every gene keeps a fixed index as the array grows.
 * `genotype.ts` dropped the padding. From slot 22 onward the two disagreed: tempoBase and
 * bodyScale were uploaded into what the shader reads as specGain and fresnelGain, and the
 * slots the shader reads AS tempoBase and bodyScale were left at the Float32Array's zero fill.
 *
 * A bodyScale of 0 does not degrade the familiar. It multiplies the body's radius by zero.
 * Measured on the desktop bench against the identity render, it changes 73% of pixels by up to
 * 232 levels. That shipped to both tenants and was found by reading the two tables side by
 * side, not by any check.
 *
 * So the vendored `genotype.h` is now the source and this parses it. If the header grows a
 * gene, this goes red until `genotype.ts` grows the same gene at the same index. If the header
 * is reordered, this goes red, which is the correct answer: reordering silently re-labels
 * every gene in every genotype already on disk.
 */

import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  GENOTYPE_DEFAULTS,
  GENOTYPE_SLOTS,
  GENOTYPE_VEC4S,
  packGenotype,
} from "../../../src/familiar/genotype";

const HEADER = resolve(process.cwd(), "src/familiar/genotype.h");

/** Pull one brace-delimited C initialiser list out of the header, comments stripped.
 *  Deliberately dumb: a real C parser would accept things this table must never contain. */
function initialiser(src: string, declaration: string): string[] {
  const at = src.indexOf(declaration);
  if (at < 0) throw new Error(`no declaration matching ${declaration} in genotype.h`);
  const open = src.indexOf("{", at);
  const close = src.indexOf("};", open);
  if (open < 0 || close < 0) throw new Error(`unterminated initialiser for ${declaration}`);
  return src
    .slice(open + 1, close)
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\/\/[^\n]*/g, "")
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

describe("the vendored genotype.h and genotype.ts describe the same uniform", () => {
  it("has a vendored header to compare against", () => {
    // Without this the checks below fail as "no such file", which reads like infrastructure
    // noise rather than like the real answer, which is that the source table is missing.
    expect(existsSync(HEADER), `no genotype.h at ${HEADER} (cwd ${process.cwd()})`).toBe(true);
  });

  it("agrees on every slot, name for name and hole for hole", () => {
    const src = readFileSync(HEADER, "utf8");
    const keys = initialiser(src, "GENOTYPE_KEYS[GENOTYPE_SLOTS]").map((tok) =>
      tok === "NULL" ? null : tok.replace(/^"|"$/g, ""),
    );

    expect(keys.length, "genotype.h slot count").toBe(GENOTYPE_SLOTS.length);
    keys.forEach((key, i) => {
      expect(
        GENOTYPE_SLOTS[i],
        `slot ${i} (uGene[${Math.floor(i / 4)}].${"xyzw"[i % 4]}): the header says ` +
          `${key === null ? "RESERVED" : key}`,
      ).toBe(key);
    });
  });

  it("agrees on every default, including the reserved ones", () => {
    const src = readFileSync(HEADER, "utf8");
    const defaults = initialiser(src, "GENOTYPE_DEFAULTS[GENOTYPE_SLOTS]").map((tok) =>
      Number.parseFloat(tok),
    );
    const packed = packGenotype(GENOTYPE_DEFAULTS);

    expect(defaults.length, "genotype.h default count").toBe(GENOTYPE_SLOTS.length);
    defaults.forEach((want, i) => {
      const key = GENOTYPE_SLOTS[i];
      // The reserved entries are checked too, and that is the whole point: the C table fills
      // them with 1.0f and a Float32Array fills them with 0. The difference is invisible right
      // up until the slot is claimed by a multiplier, and then every familiar in the fleet
      // multiplies that term by zero.
      expect(
        packed[i],
        `slot ${i} (${key ?? "RESERVED"}) uploads ${packed[i]}, header default is ${want}`,
      ).toBeCloseTo(want, 6);
    });
  });

  it("uploads whole vec4s, and exactly as many as the header declares", () => {
    expect(GENOTYPE_SLOTS.length % 4, "the slot table must be a whole number of vec4s").toBe(0);
    expect(GENOTYPE_VEC4S).toBe(GENOTYPE_SLOTS.length / 4);
    expect(packGenotype(GENOTYPE_DEFAULTS).length).toBe(GENOTYPE_SLOTS.length);
  });

  it("names every slot the vendored shader actually reads", () => {
    // The other direction. The header could pad a slot the shader has already claimed, which
    // the name comparison above cannot see because both tables would agree on the hole.
    const frag = readFileSync(resolve(process.cwd(), "src/familiar/familiar.frag"), "utf8");
    const read = new Set<number>();
    for (const m of frag.matchAll(/uGene\[(\d+)\]\.([xyzw])/g)) {
      read.add(Number(m[1]) * 4 + "xyzw".indexOf(m[2]));
    }
    expect(read.size, "the shader reads no gene slots at all").toBeGreaterThan(0);
    for (const slot of [...read].sort((a, b) => a - b)) {
      expect(
        GENOTYPE_SLOTS[slot],
        `the shader reads uGene[${Math.floor(slot / 4)}].${"xyzw"[slot % 4]} (slot ${slot}) ` +
          `but the slot table calls it RESERVED, so nothing ever writes it`,
      ).not.toBe(null);
      expect(GENOTYPE_SLOTS[slot], `slot ${slot} is beyond the slot table`).toBeDefined();
    }
  });
});
