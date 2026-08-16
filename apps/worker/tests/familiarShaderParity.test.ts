// @vitest-environment happy-dom
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// The canonical Familiar shader lives at familiar/familiar.frag (the measured
// canon: DESIGN-BRIEF.md + familiar-bench). The worker vendors a copy so the
// bundle stays self-contained. This test is the reader that keeps the two
// identical - a vendored copy with no diff check is how parity gaps happen.
//
// The vendored copy lives under src/bundles/familiar/, not src/components/:
// characters became bundles, and a bundle owns its own shader. This test was
// written against the components path on a branch that did not yet have the
// move, which is why it could pass on main and on the feature branch and fail
// only on the merge of the two.
describe("familiar shader parity", () => {
  it("worker's vendored familiar.frag is byte-identical to the canon", () => {
    const canon = readFileSync(
      resolve(__dirname, "../../../familiar/familiar.frag"), "utf8");
    const vendored = readFileSync(
      resolve(__dirname, "../src/bundles/familiar/familiar.frag"), "utf8");
    expect(vendored).toBe(canon);
  });
});
