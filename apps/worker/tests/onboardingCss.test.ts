import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(
  new URL("../src/components/onboarding/onboarding.css", import.meta.url),
  "utf8",
);

describe("onboarding motion and layout contract", () => {
  it("stages slide-and-rise motion with a reduced-motion fallback", () => {
    expect(css).toContain("@keyframes onboarding-slide-in");
    expect(css).toContain("@keyframes onboarding-rise");
    expect(css).toContain("prefers-reduced-motion: reduce");
  });

  // The step is a RAIL now: one card, chevrons either side, dots beneath. The
  // two-up grid is gone and so is the selected-card ring -- the card on screen
  // IS the selection, so an accent ring on the only card there is tells you
  // nothing. What must survive is that the card stays responsive.
  it("lays the companion step out as a rail and keeps it responsive", () => {
    expect(css).toContain(".companion-rail");
    expect(css).toContain(".companion-viewport");
    expect(css).toContain(".companion-chevron");
    expect(css).toContain(".companion-dot");
    expect(css).toContain("@media (max-width: 720px)");
    // The grid is not merely unused; leaving it behind would have two layouts
    // competing for the same card.
    expect(css).not.toContain(".companion-grid");
  });

  // The pills, the copy, the chevrons and the brand lockup all have to survive
  // the panel going near-black, and NONE of them is named by the rule that
  // makes it happen. That rule re-points the colour tokens on the panel; these
  // are the two tokens a pill reads, so asserting them is asserting the chips
  // do not render as light-theme chips on a near-black surface. The per-card
  // override that used to do this job is gone, and is asserted gone: bringing
  // it back would colour the pills for a companion whose panel is glass.
  it("dresses the whole panel through tokens rather than per-card overrides", () => {
    expect(css).toContain(".skin-pill");
    expect(css).toContain(OPAQUE_JARVIS);
    expect(css).toContain(OPAQUE_COLOSSUS);
    const tinted = ruleFor(`${OPAQUE_JARVIS},\n${OPAQUE_COLOSSUS}`);
    expect(tinted).toContain("--text-2:");
    expect(tinted).toContain("--border-2:");
    expect(tinted).toContain("background: var(--companion-surface);");
    expect(css).not.toContain('.companion-card[data-companion="jarvis"] .skin-pill');
  });

  // ONLY the two bodies that paint an opaque rectangle. tests/visual/render-bodies.mjs
  // reads a real frame and reports alpha 255 for the Jarvis dial and Colossus
  // and alpha 0 for the neural field and Ultron; tinting the panel for a
  // transparent body would be colouring in a rectangle that is not there.
  it("tints the panel for the opaque bodies and no others", () => {
    expect(tintedSelectors()).toEqual([OPAQUE_JARVIS, OPAQUE_COLOSSUS].sort());
  });

  // The scrim under the copy was the last surviving edge of the inner card: a
  // near-opaque band across the bottom of the art, which read as the card’s
  // footer whatever the card itself was doing.
  it("gives the companion copy no scrim of its own", () => {
    const copy = ruleFor(".companion-copy");
    expect(copy).toContain("background: none;");
    expect(copy).not.toContain("linear-gradient");
  });
});

const OPAQUE_JARVIS =
  '.onboarding-panel:has(.companion-card[data-companion="jarvis"][data-skin="default"])';
const OPAQUE_COLOSSUS =
  '.onboarding-panel:has(.companion-card[data-companion="colossus"])';

/** The declaration block of the rule whose selector list starts with `selector`. */
function ruleFor(selector: string): string {
  const at = css.indexOf(`${selector} {`);
  expect(at, `no rule for ${selector}`).toBeGreaterThan(-1);
  return css.slice(at, css.indexOf("}", at));
}

/**
 * Every selector that sets --companion-surface, sorted.
 *
 * Read out of the stylesheet rather than asserted one by one, so ADDING a
 * companion to the tinted set fails this test. A `toContain` pair would let a
 * third one through unnoticed, and a transparent body with a tinted panel is
 * precisely the mistake worth catching.
 */
function tintedSelectors(): string[] {
  return [...css.matchAll(/([^\n{}]+)\s*\{[^{}]*--companion-surface:/g)]
    .map((match) => match[1].trim())
    .sort();
}
