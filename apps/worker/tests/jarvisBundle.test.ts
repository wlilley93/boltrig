import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";

import { bundleVoiceId, parseCharacterBundle } from "@wlilley93/boltrig-web-sdk";
import familiarBundle from "../src/bundles/familiar/character.json";
import jarvisBundle from "../src/bundles/jarvis/character.json";
import {
  CharacterBundleUnsupported,
  characterFromBundle,
  type CharacterCanvasSource,
} from "../src/components/characterBundle";
import { UNIFORMS as FAMILIAR_UNIFORMS } from "../src/components/familiar/FamiliarWebGLRenderer";
import { UNIFORMS as JARVIS_UNIFORMS } from "../src/components/jarvis/JarvisRenderer";
import fragSrc from "../src/bundles/jarvis/jarvis.frag?raw";

// Stand-ins. As in familiarBundle.test.ts, what is under test is the BINDING,
// not what WebGL draws.
const jarvisSource: CharacterCanvasSource = {
  id: "boltrig.canvas.jarvis",
  type: "shader",
  supplies: [...JARVIS_UNIFORMS, "uGene"],
  // Both bodies the real source can draw: the instrument dial and the neural
  // field. A source that named neither would now be refused, which is the
  // point of declaring them.
  skins: ["default", "ultron"],
  render: () => null,
};

const familiarSource: CharacterCanvasSource = {
  id: "boltrig.canvas.shader",
  type: "shader",
  supplies: FAMILIAR_UNIFORMS,
  emotionModels: ["autonomous-wander"],
  render: () => null,
};

describe("Jarvis as a character bundle", () => {
  it("produces exactly the registry entry the stock build used to hand-write", () => {
    const jarvis = characterFromBundle(jarvisBundle, [jarvisSource]);
    expect(jarvis.id).toBe("jarvis");
    expect(jarvis.name).toBe("Jarvis");
    expect(jarvis.blurb).toBe("An instrument that displays the machine's measured state.");
    // The two he DID ask for, unlike Familiar.
    expect(jarvis.readsPhenotype).toBe(true);
    expect(jarvis.wantsBudgets).toBe(true);
    // Two bodies, one character. The default is FIRST, so an install that has
    // never heard of skins keeps rendering what it always rendered.
    expect(jarvis.skins?.map((skin) => skin.id)).toEqual(["default", "ultron"]);
    expect(jarvis.skins?.[0].name).toBe("Instrument");
  });

  // A skin the canvas cannot draw must be refused BY NAME. Collapsing it to the
  // default would offer a look in the picker and then silently not draw it,
  // which is indistinguishable from the feature being broken.
  it("refuses a skin the bound canvas source cannot draw", () => {
    const oneBody = { ...jarvisSource, skins: ["default"] };
    expect(() => characterFromBundle(jarvisBundle, [oneBody]))
      .toThrow(CharacterBundleUnsupported);
    expect(() => characterFromBundle(jarvisBundle, [oneBody]))
      .toThrow(/cannot draw skin ultron/);
  });

  // Familiar has one body and says so by SAYING NOTHING. An array of one would
  // imply a choice, and every picker would have to special-case it.
  it("leaves a character with one look carrying no skins at all", () => {
    const familiar = characterFromBundle(familiarBundle, [familiarSource]);
    expect(familiar.skins).toBeUndefined();
  });

  // The manifest names the shader by digest. If the vendored .frag moves under
  // it, this fails here rather than at first paint on someone else's machine.
  it("declares the digest of the shader the canvas actually compiles", () => {
    const digest = createHash("sha256").update(fragSrc, "utf8").digest("hex");
    const visual = parseCharacterBundle(jarvisBundle).visual;
    expect(visual.type).toBe("shader");
    if (visual.type !== "shader") return;
    // PRESENT, not merely correct. `fragment` became optional so a character
    // drawn by host machinery could ship no shader file; this one DOES ship
    // one, and asserting its presence is what stops "optional" turning into
    // "absent everywhere" and the digest check covering nothing.
    expect(visual.fragment).toBeDefined();
    if (!visual.fragment) return;
    expect(visual.fragment.file).toBe("jarvis.frag");
    expect(visual.fragment.sha256).toBe(digest);
  });

  // Every uniform the shader declares must be one the bound source can drive.
  // uGene is included deliberately: the shader needs it, and the renderer
  // uploads it once at mount rather than per frame — a difference in WHEN, not
  // in whether the source can supply it.
  it("names every uniform its own shader declares, uGene included", () => {
    const declared = [...fragSrc.matchAll(/^\s*uniform\s+\w+\s+(\w+)/gm)].map((m) => m[1]);
    const visual = parseCharacterBundle(jarvisBundle).visual;
    if (visual.type !== "shader") throw new Error("expected a shader visual");
    expect([...(visual.uniforms ?? [])].sort()).toEqual([...new Set(declared)].sort());
    expect(visual.uniforms).toContain("uGene");
  });

  /**
   * The reason Jarvis names his own source rather than reusing Familiar's.
   *
   * Both are `type: shader`, which makes it tempting to draw them through one
   * source. They are not interchangeable — and the format says so out loud
   * rather than rendering an instrument with a creature's channels.
   */
  it("is refused by the Familiar's canvas, which cannot drive his channels", () => {
    expect(() => characterFromBundle(jarvisBundle, [familiarSource]))
      .toThrow(CharacterBundleUnsupported);
  });

  it("and the Familiar is refused by his, for the same reason in reverse", () => {
    expect(() => characterFromBundle(familiarBundle, [jarvisSource]))
      .toThrow(CharacterBundleUnsupported);
  });
});

describe("Jarvis's voice", () => {
  // Two providers doing two different jobs, and the distinction is the point:
  // `fish` GENERATED the register references and is not called at runtime;
  // `pocket-voice` is what actually speaks him, from local clones.
  it("names the Fish id that generated him and the local voice that speaks him", () => {
    const manifest = parseCharacterBundle(jarvisBundle);
    expect(bundleVoiceId(manifest, "fish")).toBe("d2d43385f4a749389dda58ecff883bb5");
    expect(bundleVoiceId(manifest, "pocket-voice")).toBe("jarvis");
  });

  // "Absent voice means a silent character, never a substituted one." A
  // provider the bundle does not name must come back empty so the caller stays
  // silent, rather than borrowing whichever voice happens to be configured.
  it("says nothing for a provider it does not name", () => {
    const manifest = parseCharacterBundle(jarvisBundle);
    expect(bundleVoiceId(manifest, "elevenlabs")).toBeUndefined();
    expect(bundleVoiceId(manifest, "xai")).toBeUndefined();
  });

  it("reads the Familiar's own fish id rather than Jarvis's", () => {
    // She declares one now, where she used to declare nothing. The point of the
    // assertion is unchanged: bundleVoiceId must answer from the manifest it was
    // handed. Returning Jarvis's id here would be the failure, and it is a live
    // possibility precisely because both bundles now name the same provider.
    const manifest = parseCharacterBundle(familiarBundle);
    const jarvis = parseCharacterBundle(jarvisBundle);
    expect(bundleVoiceId(manifest, "fish")).toBe("c8f64deb39914cfca7f47ccfc3bca82f");
    expect(bundleVoiceId(manifest, "fish")).not.toBe(bundleVoiceId(jarvis, "fish"));
  });
});
