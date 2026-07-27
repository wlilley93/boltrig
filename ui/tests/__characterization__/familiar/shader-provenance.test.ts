/**
 * `familiar.frag` is VENDORED. It is authored in ~/Projects/beelink-desktop/familiar and copied
 * here, so there are now two files that must stay equal and no compiler that will ever notice
 * when they stop being.
 *
 * That is the whole failure mode, and it is quiet: someone tunes a mood in the desktop shader,
 * boltrig keeps rendering the old one, and for weeks the console shows agents that do not look
 * like the being on the desktop. Nothing errors. The pictures are just wrong.
 *
 * This pins the half that CI can actually see. It hashes the vendored copy and compares it to
 * a recorded digest, so editing the copy in place fails immediately with an instruction to
 * change the upstream instead. It cannot see the upstream repo - CI has no checkout of it - so
 * it deliberately does NOT claim the two are in sync. `scripts/check_familiar_shader.sh`
 * answers that question, on a machine that has both, and reports NOT CHECKED where it cannot
 * look rather than reporting an agreement it did not observe.
 *
 * To update: change the shader upstream, re-copy, run the script, and paste the new digest.
 * The friction is the point - a vendored file that can be edited casually is not vendored.
 */

import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

// Resolved from the working directory, not from import.meta.url: under happy-dom the module
// URL is not a file:// URL and fileURLToPath throws "The URL must be of scheme file".
const SHADER = resolve(process.cwd(), "src/familiar/familiar.frag");

/** Source of truth: wlilley93/beelink-desktop, familiar/familiar.frag at ff0cfa1. */
const RECORDED_SHA256 = "902521bfe5f023196ed63f30445518872ac9c713d8cfe4e7145e92a469bf2166";

describe("vendored familiar.frag", () => {
  it("is actually where this test thinks it is", () => {
    // Without this, a moved file turns both checks below into errors that read like
    // infrastructure noise rather than like the real answer, which is "there is no shader".
    expect(existsSync(SHADER), `no shader at ${SHADER} (cwd ${process.cwd()})`).toBe(true);
  });

  it("matches the digest recorded from its upstream", () => {
    const bytes = readFileSync(SHADER);
    const got = createHash("sha256").update(bytes).digest("hex");
    expect(got, [
      "The vendored shader no longer matches its recorded upstream digest.",
      "",
      "If you edited it here: don't. It is authored in beelink-desktop/familiar and copied in;",
      "an edit here is lost the next time it is re-copied, and until then the console renders a",
      "different being from the desktop.",
      "",
      "If you re-copied it deliberately: run scripts/check_familiar_shader.sh, then update",
      "RECORDED_SHA256 and the commit reference above.",
    ].join("\n")).toBe(RECORDED_SHA256);
  });

  it("still declares the uniforms the renderer sets", () => {
    // A digest catches CHANGE. This catches the specific change that would break the
    // integration silently: a uniform being renamed or dropped upstream. WebGL does not error
    // on a missing uniform - getUniformLocation returns null and the write is discarded - so
    // the familiar would keep rendering, at the default value, with no warning anywhere.
    const src = readFileSync(SHADER, "utf8");
    for (const name of ["uGene", "uPresence", "uFill", "uCompanion", "uAperture", "uFitScale"]) {
      expect(src, `${name} is gone from the shader; the renderer's write to it is now a no-op`)
        .toMatch(new RegExp(`uniform\\s+\\w+\\s+${name}\\b`));
    }
  });
});
