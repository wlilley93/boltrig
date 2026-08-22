import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Every body has to survive a phone, and they kept not doing so one at a time.
 *
 * This is a drift test, not a rendering test. Jarvis and Familiar each grew a mobile
 * rule when somebody looked at them on a phone; Ultron and Colossus did not, and the
 * consequence is invisible on a desktop and total on a handset -- their stages are
 * `height: 100%` over a `min-height: 160px` floor, so a parent that gives no height
 * leaves the being a stamp in the middle of a tall empty screen.
 *
 * Four bodies, four stylesheets, and nothing that made them agree. So: assert the
 * rule exists for each, and assert the BOUND is on the short side, because a body
 * bounded only by width grows taller than a short window and pushes the transcript
 * and composer out of view. familiar.css paid for that lesson; this is what stops
 * the next body paying for it again.
 */

const HERE = dirname(fileURLToPath(import.meta.url));
const BODIES = ["jarvis", "ultron", "familiar", "colossus"] as const;

function stylesheet(body: string): string {
  return readFileSync(resolve(HERE, `../src/components/${body}/${body}.css`), "utf8");
}

describe("every body stage survives a phone", () => {
  it.each(BODIES)("%s responds to the viewport, by either mechanism", (body) => {
    const css = stylesheet(body);
    // A MEDIA QUERY OR AN INTRINSIC BOUND. The first cut of this test demanded a
    // max-width media query and FAILED FAMILIAR, which is the best of the four:
    // `width: min(340px, 60vw, 38vh)` responds continuously and needs no breakpoint
    // at all. That was a test encoding a MECHANISM where it should have been
    // asserting a PROPERTY -- and a test that fails the best implementation is
    // pressure to make the code worse.
    //
    // prefers-reduced-motion does not count as either: it is a motion preference,
    // not a viewport, and matching on "@media" alone would have passed Ultron before
    // the rule this test exists to require was written.
    const breakpoint = /@media\s*\([^)]*max-width/.test(css);
    const intrinsic = /(min|max|clamp)\([^)]*\b\d+(\.\d+)?(vh|dvh|vw|dvw)\b/.test(css);
    expect(
      breakpoint || intrinsic,
      `${body} has neither a max-width media query nor a viewport-relative bound`,
    ).toBe(true);
  });

  it.each(BODIES)("%s bounds its stage against the viewport, not just in pixels", (body) => {
    const css = stylesheet(body);
    // vh or dvh somewhere in the sizing. A purely pixel bound cannot know whether it
    // is taller than the window it is in, which is the entire failure mode.
    expect(css).toMatch(/\b\d+(\.\d+)?(vh|dvh)\b/);
  });

  it("does not let a body bound itself on width alone", () => {
    // familiar is the square one and the one that got this wrong first: a width-only
    // bound let a square stage grow taller than a short window. Its fix bounds both
    // axes in the same expression, and that shape is what is pinned here.
    const css = stylesheet("familiar");
    const width = css.match(/width:\s*min\(([^)]*)\)/);
    expect(width, "familiar's stage should bound its width with a min()").toBeTruthy();
    expect(width?.[1]).toMatch(/vh/);
  });
});
