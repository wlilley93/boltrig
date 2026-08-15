import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";

import { bundleTone, bundleVoiceId, parseCharacterBundle } from "@wlilley93/boltrig-web-sdk";
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
  });

  // The manifest names the shader by digest. If the vendored .frag moves under
  // it, this fails here rather than at first paint on someone else's machine.
  it("declares the digest of the shader the canvas actually compiles", () => {
    const digest = createHash("sha256").update(fragSrc, "utf8").digest("hex");
    const visual = parseCharacterBundle(jarvisBundle).visual;
    expect(visual.type).toBe("shader");
    if (visual.type !== "shader") return;
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

describe("Jarvis's declared tone", () => {
  const manifest = parseCharacterBundle(jarvisBundle);

  it("brings his own shaping, with a stated reason for each filter", () => {
    // A character BRINGS this; nothing in the shared stack knows his name. The
    // automatic loudness and tilt stages run for everyone regardless.
    const tone = bundleTone(manifest);
    expect(tone).toHaveLength(2);
    expect(tone.map((t) => `${t.type}@${t.frequency}`))
      .toEqual(["peaking@3000", "peaking@350"]);
    for (const filter of tone) {
      expect(filter.reason.trim().length).toBeGreaterThan(20);
      expect(Math.abs(filter.gainDb)).toBeLessThanOrEqual(12);
    }
  });

  it("asks for presence and cuts boxiness, which is what his pitch needs", () => {
    const tone = bundleTone(manifest);
    const presence = tone.find((t) => t.frequency === 3000)!;
    const boxiness = tone.find((t) => t.frequency === 350)!;
    expect(presence.gainDb).toBeGreaterThan(0);
    expect(boxiness.gainDb).toBeLessThan(0);
  });

  it("gives a character that declares nothing exactly nothing", () => {
    // Absence is never a licence to substitute -- the same rule bundleVoiceId
    // follows. Familiar declares no tone and must get none, not Jarvis's.
    expect(bundleTone(parseCharacterBundle(familiarBundle))).toEqual([]);
  });

  it("drops a malformed filter instead of silencing the character", () => {
    const mangled = {
      ...jarvisBundle,
      voice: {
        ...(jarvisBundle as { voice: Record<string, unknown> }).voice,
        tone: [
          { type: "peaking", frequency: 3000, gainDb: 5, reason: "kept" },
          { type: "peaking", frequency: 3000, gainDb: 5 },          // no reason
          { type: "peaking", frequency: 3000, gainDb: 40, reason: "too loud" },
          { type: "notch", frequency: 3000, gainDb: 5, reason: "unknown type" },
          null,
        ],
      },
    };
    const tone = bundleTone(parseCharacterBundle(mangled));
    expect(tone).toHaveLength(1);
    expect(tone[0]!.reason).toBe("kept");
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

  it("says nothing for the Familiar, who declares no voice at all", () => {
    const manifest = parseCharacterBundle(familiarBundle);
    expect(bundleVoiceId(manifest, "fish")).toBeUndefined();
  });
});
