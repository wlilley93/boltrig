import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

// Source-of-truth drift guard (GAP G6 foundation).
//
// `boltrig-web-sdk` is the canonical definition of the chat/run frame union and
// the turn reducer both frontends fold through, so opbox and the boltrig console
// render identical data. Until the console consumes the package directly (a
// build-graph change to the live console workspace, done deliberately), the
// console keeps byte-identical copies in ui/src. This test FAILS the moment
// those copies drift from the package - forcing an edit to land in the package
// (the source of truth) and be mirrored, never forked silently.
//
// The only sanctioned difference is import specifiers: the package rewrites the
// console's `@/...` path aliases to relative `./*.js` (NodeNext). We compare
// modulo import statements; everything else must match exactly.

// dist/tests/drift.test.js -> repo root is four levels up.
const repoRoot = fileURLToPath(new URL("../../../../", import.meta.url));

/** Strip every ES import statement (single- or multi-line) and normalise
 * trailing whitespace + runs of blank lines, so only the substance remains. */
function substance(src: string): string {
  return src
    .replace(/import\b[^;]*;/g, "") // `import ... ;` incl. multi-line blocks
    .split("\n")
    .map((line) => line.replace(/\s+$/, ""))
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

const PAIRS: Array<{ console: string; pkg: string }> = [
  { console: "ui/src/api/types.ts", pkg: "sdks/web/src/types.ts" },
  { console: "ui/src/panels/chatTurnTypes.ts", pkg: "sdks/web/src/chatTurnTypes.ts" },
  { console: "ui/src/panels/chatTurnNormalizer.ts", pkg: "sdks/web/src/chatTurnNormalizer.ts" },
];

for (const { console: consolePath, pkg: pkgPath } of PAIRS) {
  test(`source-of-truth: ${consolePath} matches package ${pkgPath} (modulo imports)`, () => {
    const consoleSrc = substance(readFileSync(repoRoot + consolePath, "utf8"));
    const pkgSrc = substance(readFileSync(repoRoot + pkgPath, "utf8"));
    assert.equal(
      consoleSrc,
      pkgSrc,
      `${consolePath} has drifted from ${pkgPath}. The package is the source of ` +
        `truth: make the change in sdks/web/src and mirror it into ui/src (or ` +
        `re-point the console at the package).`,
    );
  });
}
