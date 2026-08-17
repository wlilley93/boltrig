import { describe, expect, it } from "vitest";

import ultronBundle from "../src/bundles/ultron/character.json";
import {
  CharacterBundleUnsupported,
  characterFromBundle,
  type CharacterCanvasSource,
} from "../src/components/characterBundle";
import { ULTRON_UNIFORMS } from "../src/components/characters";
import { FIELD_GLSL, FRINGE_GLSL, PROJECT_GLSL } from "../src/components/canvas/glslCommon";
import { BLOOM_FRAG, COMPOSITE_FRAG } from "../src/components/canvas/shadersPost";
import { QUAD_VERT, SIM_FRAG } from "../src/components/canvas/shadersSim";
import {
  CRACK_FRAG,
  CRACK_VERT,
  FACET_FRAG,
  FACET_VERT,
  VEIN_FRAG,
  VEIN_VERT,
} from "../src/components/ultron/shadersUltron";

/**
 * Ultron's manifest, pinned against the shaders that actually run.
 *
 * WHY HE NEEDED HIS OWN TEST. Jarvis and Familiar each ship ONE .frag,
 * byte-pinned by sha256, and each has a test that scans that file and asserts
 * the manifest names every uniform it declares. Ultron ships no frag at all --
 * he is four passes across three modules, which is why `visual.fragment` became
 * optional -- so he had neither the pin nor the scan, and a uniform added to a
 * pass left his manifest quietly wrong.
 *
 * That is not cosmetic. `assertUniforms` refuses a bundle naming a uniform its
 * source cannot supply, which is what stops a character rendering as a subtly
 * wrong being. A manifest that UNDER-declares sails through that check while
 * describing something other than what runs, and the failure shows up as a body
 * that looks fine and ignores half its inputs -- which is exactly how Ultron
 * spent his first day not listening to the voice.
 */

const SHADERS = [
  QUAD_VERT, SIM_FRAG, BLOOM_FRAG, COMPOSITE_FRAG,
  VEIN_VERT, VEIN_FRAG, CRACK_VERT, CRACK_FRAG, FACET_VERT, FACET_FRAG,
  FIELD_GLSL, PROJECT_GLSL, FRINGE_GLSL,
];

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

const ultronSource: CharacterCanvasSource = {
  id: "boltrig.canvas.ultron",
  type: "shader",
  // The list PRODUCTION passes, not one derived here. Deriving it made this
  // file agree with itself: `uLimb` reached the shaders and the manifest while
  // ULTRON_UNIFORMS was left behind, and every test passed while
  // characterFromBundle threw "cannot supply uLimb" on the real page.
  supplies: ULTRON_UNIFORMS,
  render: () => null,
};

describe("Ultron as a character bundle", () => {
  // THREE LISTS HAVE TO AGREE, and the third is the one that was missing here.
  // The shaders declare the uniforms; the manifest says which the bundle wants;
  // and ULTRON_UNIFORMS says which the canvas source can drive. A uniform in the
  // first two but not the third is refused at registration -- at runtime, on the
  // real page, with the suite green.
  it("has a canvas source that can drive every uniform his shaders declare", () => {
    const declared = declaredUniforms();
    const supplies = new Set(ULTRON_UNIFORMS);
    const cannotSupply = [...declared].filter((name) => !supplies.has(name)).sort();
    const suppliesNothing = [...supplies].filter((name) => !declared.has(name)).sort();
    expect({ cannotSupply, suppliesNothing }).toEqual({
      cannotSupply: [], suppliesNothing: [],
    });
  });

  it("declares exactly the uniforms his passes actually use", () => {
    const declared = declaredUniforms();
    const visual = ultronBundle.visual;
    const manifest = new Set(visual.uniforms ?? []);

    const missing = [...declared].filter((name) => !manifest.has(name)).sort();
    const stale = [...manifest].filter((name) => !declared.has(name)).sort();
    // Both directions. Missing means the manifest lies by omission; stale means
    // it names a channel nothing reads, which is how a body ends up "supporting"
    // an input that was deleted two refactors ago.
    expect({ missing, stale }).toEqual({ missing: [], stale: [] });
  });

  it("ships no fragment, because he is passes rather than one shader", () => {
    // The reason `visual.fragment` is optional at all. A digest of an invented
    // .frag would be a pin that lies; the uniform check above is his equivalent.
    expect((ultronBundle.visual as { fragment?: unknown }).fragment).toBeUndefined();
  });

  it("reads the phenotype, and offers exactly one body", () => {
    const ultron = characterFromBundle(ultronBundle, [ultronSource]);
    expect(ultron.id).toBe("ultron");
    expect(ultron.readsPhenotype).toBe(true);
    // One look, so he declares no skins rather than an array of one.
    expect(ultron.skins).toBeUndefined();
  });

  it("does not poll budgets, having nowhere to show them", () => {
    // Jarvis wants budgets because he has a gauge. A membrane has no dial, and
    // polling for a body that cannot display the answer is a request nobody reads.
    expect(characterFromBundle(ultronBundle, [ultronSource]).wantsBudgets).toBeUndefined();
  });

  it("is refused by a source that cannot supply his channels", () => {
    const deaf = { ...ultronSource, supplies: ["uTime"] };
    expect(() => characterFromBundle(ultronBundle, [deaf]))
      .toThrow(CharacterBundleUnsupported);
  });

  it("names the voice channels, so a silent body is a bug and not a design", () => {
    // The regression this file was written for: he clamped eight bands into a
    // field every frame and no pass ever uploaded them.
    const manifest = new Set(ultronBundle.visual.uniforms ?? []);
    expect(manifest.has("uBands")).toBe(true);
    expect(manifest.has("uVoice")).toBe(true);
  });
});
