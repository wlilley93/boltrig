// No DOM environment pragma: this reads two files and compares them.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// Mirrors familiarShaderParity: the canonical Jarvis shader lives at
// familiar/jarvis.frag alongside its sibling, and the worker vendors a copy so
// the bundle stays self-contained. This test is the reader that keeps the two
// identical.
//
// Jarvis needs this MORE than the Familiar does, not less. It was authored
// browser-first, so the vendored copy is the one that gets edited, and the
// canon is the copy that silently rots — the opposite direction to the
// Familiar, whose rule is that visual changes never start in the worker.
describe("jarvis shader parity", () => {
  it("worker's vendored jarvis.frag is byte-identical to the canon", () => {
    const canon = readFileSync(
      resolve(__dirname, "../../../familiar/jarvis.frag"), "utf8");
    const vendored = readFileSync(
      resolve(__dirname, "../src/bundles/jarvis/jarvis.frag"), "utf8");
    expect(vendored).toBe(canon);
  });

  // The post chain is part of the shader, not part of the host: the look is
  // decided by the bloom threshold and curve as much as by the dial itself.
  it("worker's vendored jarvis-post.frag is byte-identical to the canon", () => {
    const canon = readFileSync(
      resolve(__dirname, "../../../familiar/jarvis-post.frag"), "utf8");
    const vendored = readFileSync(
      resolve(__dirname, "../src/components/jarvis/jarvis-post.frag"), "utf8");
    expect(vendored).toBe(canon);
  });

  // The single-pass path must survive: the desktop GLES host has no
  // framebuffers, so uHDR=0 has to keep its own grade. Deleting that branch
  // would look harmless in the browser and break the wallpaper silently.
  it("keeps the single-pass grade the desktop host depends on", () => {
    const shader = readFileSync(
      resolve(__dirname, "../src/bundles/jarvis/jarvis.frag"), "utf8");
    expect(shader).toContain("uniform float uHDR;");
    expect(shader).toMatch(/if \(uHDR > 0\.5\)/);
    expect(shader).toContain("Single-pass grade");
  });

  // The atlas is generated, and the generator has to travel with the shader or
  // the canon cannot be regenerated from its own directory.
  it("ships the glyph generator beside the canon", () => {
    const gen = readFileSync(
      resolve(__dirname, "../../../familiar/scripts/gen_font.py"), "utf8");
    expect(gen).toContain("def pack(rows)");
  });
});
