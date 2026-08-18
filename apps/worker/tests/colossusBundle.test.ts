import { describe, expect, it } from "vitest";

import colossusBundle from "../src/bundles/colossus/character.json";
import {
  CharacterBundleUnsupported,
  characterFromBundle,
  type CharacterCanvasSource,
} from "../src/components/characterBundle";
import { BLOOM_FRAG } from "../src/components/canvas/shadersPost";
import { QUAD_VERT } from "../src/components/canvas/shadersSim";
import { glyphIds, TICKER_GLYPH_COUNT } from "../src/components/colossus/glyphAtlas";
import {
  PANEL_COMPOSITE_FRAG,
  PANEL_FRAG,
  READOUT_LEN,
  TICKER_CAPACITY,
} from "../src/components/colossus/shadersColossus";
import {
  compileTicker,
  scrollSpeed,
  tickerFor,
  type ColossusMode,
} from "../src/components/colossus/tickerText";

/**
 * Colossus's manifest and his ticker, pinned against what actually runs.
 *
 * SAME REASON ULTRON HAS ONE. He ships no .frag -- he is two passes and a
 * generated glyph atlas -- so he has neither the sha256 pin Jarvis and Familiar
 * carry nor the scan that goes with it, and a uniform added to a pass would
 * leave his manifest quietly wrong. `assertUniforms` refuses a bundle naming a
 * uniform its source cannot supply, but a manifest that UNDER-declares sails
 * through while describing something other than what runs.
 *
 * AND THE TICKER NEEDS ITS OWN PINNING, which no other body does. Every other
 * character's shader reads numbers; his reads TEXT, compiled to glyph ids on
 * the CPU and drawn from an atlas on the GPU. If those two disagree the panel
 * does not fail -- it confidently spells something else, which no compiler,
 * type or uniform check can see. That is what most of this file is for.
 */

const SHADERS = [QUAD_VERT, PANEL_FRAG, PANEL_COMPOSITE_FRAG, BLOOM_FRAG];

/** Every `uniform <type> <name>` the passes declare, array suffix stripped. */
function declaredUniforms(): Set<string> {
  const found = new Set<string>();
  for (const source of SHADERS) {
    for (const match of source.matchAll(/^\s*uniform\s+\w+\s+(\w+)/gm)) {
      found.add(match[1]);
    }
  }
  return found;
}

const colossusSource: CharacterCanvasSource = {
  id: "boltrig.canvas.colossus",
  type: "shader",
  supplies: [...declaredUniforms()],
  render: () => null,
};

describe("Colossus as a character bundle", () => {
  it("declares exactly the uniforms his passes actually use", () => {
    const declared = declaredUniforms();
    const manifest = new Set(colossusBundle.visual.uniforms ?? []);
    const missing = [...declared].filter((name) => !manifest.has(name)).sort();
    const stale = [...manifest].filter((name) => !declared.has(name)).sort();
    // Both directions: missing means the manifest lies by omission, stale means
    // it names a channel nothing reads.
    expect({ missing, stale }).toEqual({ missing: [], stale: [] });
  });

  it("ships no fragment, because he is passes and an atlas rather than one shader", () => {
    expect((colossusBundle.visual as { fragment?: unknown }).fragment).toBeUndefined();
  });

  it("OMITS the phenotype block, which is the encoding and not an oversight", () => {
    // Omitted, not `{reads: false}`. His constitution is explicit that his calm
    // is not a performance and that he has no competing impulse to suppress --
    // one register, and no irritated variant of a stability report.
    expect((colossusBundle as { phenotype?: unknown }).phenotype).toBeUndefined();
    expect(characterFromBundle(colossusBundle, [colossusSource]).readsPhenotype)
      .toBeFalsy();
  });

  it("offers one body and polls no budgets", () => {
    const colossus = characterFromBundle(colossusBundle, [colossusSource]);
    expect(colossus.id).toBe("colossus");
    expect(colossus.skins).toBeUndefined();
    // A counter window is an instrument measuring his own speech, not a gauge
    // for the machine's spend. Polling for a body that cannot display the
    // answer is a request nobody reads.
    expect(colossus.wantsBudgets).toBeUndefined();
  });

  it("is refused by a source that cannot supply his channels", () => {
    const deaf = { ...colossusSource, supplies: ["uTime"] };
    expect(() => characterFromBundle(colossusBundle, [deaf]))
      .toThrow(CharacterBundleUnsupported);
  });

  it("names the voice channels, so a silent panel is a bug and not a design", () => {
    const manifest = new Set(colossusBundle.visual.uniforms ?? []);
    expect(manifest.has("uBands")).toBe(true);
    expect(manifest.has("uVoice")).toBe(true);
  });
});

describe("the ticker, where a silent disagreement spells the wrong word", () => {
  it("compiles text to ids the atlas can draw", () => {
    // The contract in one line: every id the CPU emits must index the GPU's
    // table. An out-of-range id draws nothing, so the failure is a missing
    // letter rather than an error.
    for (const id of glyphIds("STANDBY * WORLD CONTROL 0123 +%:,./-")) {
      expect(id).toBeGreaterThanOrEqual(0);
      expect(id).toBeLessThan(TICKER_GLYPH_COUNT);
    }
  });

  it("folds case and turns the unknown into a space rather than throwing", () => {
    expect(glyphIds("abc")).toEqual(glyphIds("ABC"));
    // A ticker is decoration on a running system: a character nobody thought
    // of must cost a glyph, never the frame.
    const [space] = glyphIds(" ");
    expect(glyphIds("~")).toEqual([space]);
    expect(glyphIds("é")).toEqual([space]);
  });

  it("pads to capacity and reports the length that actually fits", () => {
    const long = compileTicker("X".repeat(TICKER_CAPACITY + 40));
    expect(long.glyphs.length).toBe(TICKER_CAPACITY);
    // The shader repeats `length` glyphs. Reporting more than fits would scroll
    // through slots that were never written, i.e. trailing blank forever.
    expect(long.length).toBe(TICKER_CAPACITY);

    const short = compileTicker("AB");
    expect(short.length).toBe(2);
    expect(short.glyphs.length).toBe(TICKER_CAPACITY);
  });

  it("gives every mode a line that fits, and leads with the mode word", () => {
    // HERO CONTENT: the first word off the right edge has to say what the
    // machine is doing. A line whose head is elaboration fails that at a glance.
    const heads: Record<ColossusMode, string> = {
      standby: "STANDBY",
      listening: "RECEIVING",
      thinking: "EVALUATING",
      working: "EXECUTING",
      speaking: "TRANSMITTING",
    };
    for (const [mode, head] of Object.entries(heads)) {
      const buffer = tickerFor(mode as ColossusMode);
      expect(buffer.length).toBeLessThanOrEqual(TICKER_CAPACITY);
      expect(buffer.length).toBeGreaterThan(0);
      const first = glyphIds(head);
      expect([...buffer.glyphs.slice(0, first.length)]).toEqual(first);
    }
  });

  it("scrolls faster while speaking, and never stops", () => {
    expect(scrollSpeed("speaking", 1)).toBeGreaterThan(scrollSpeed("working", 1));
    expect(scrollSpeed("working", 0)).toBeGreaterThan(scrollSpeed("standby", 0));
    // A stopped sign reads as broken, and every reference panel is moving.
    for (const mode of ["standby", "listening", "thinking", "working", "speaking"] as const) {
      expect(scrollSpeed(mode, 0)).toBeGreaterThan(0);
    }
  });

  it("sizes the readout window to what the renderer writes into it", () => {
    // "+0042 US" -- sign, four digits, a space, a two-glyph unit. The shader
    // indexes uReadout[0..READOUT_LEN); a mismatch reads uninitialised slots.
    expect(glyphIds("+0042 US")).toHaveLength(READOUT_LEN);
  });
});
