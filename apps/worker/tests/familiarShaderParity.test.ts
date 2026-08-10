// @vitest-environment happy-dom
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// The canonical Familiar shader lives at familiar/familiar.frag (the measured
// canon: DESIGN-BRIEF.md + familiar-bench). The worker vendors a copy so the
// bundle stays self-contained. This test is the reader that keeps the two
// identical - a vendored copy with no diff check is how parity gaps happen.
describe("familiar shader parity", () => {
  it("worker's vendored familiar.frag is byte-identical to the canon", () => {
    const canon = readFileSync(
      resolve(__dirname, "../../../familiar/familiar.frag"), "utf8");
    const vendored = readFileSync(
      resolve(__dirname, "../src/components/familiar/familiar.frag"), "utf8");
    expect(vendored).toBe(canon);
  });
});
