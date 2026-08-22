import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";

import {
  CharacterBundleError,
  exportCharacterBundle,
  parseCharacterBundle,
} from "@wlilley93/boltrig-web-sdk";
import familiarBundle from "../src/bundles/familiar/character.json";
import {
  CharacterBundleUnsupported,
  characterFromBundle,
  type CharacterCanvasSource,
} from "../src/components/characterBundle";
import { UNIFORMS } from "../src/components/familiar/FamiliarWebGLRenderer";
import fragSrc from "../src/bundles/familiar/familiar.frag?raw";

// A stand-in for the real shader source. The point of these tests is the
// BINDING — what the loader accepts and what it refuses — not what WebGL draws.
const source: CharacterCanvasSource = {
  id: "boltrig.canvas.shader",
  type: "shader",
  supplies: UNIFORMS,
  emotionModels: ["autonomous-wander"],
  render: () => null,
};

describe("Familiar as a character bundle", () => {
  // SHE READS THE PHENOTYPE, reversing the 2026-08-11 decision that she should
  // not. The reasoning then was that handing a phenotype to a creature with no
  // access to the appraisal engine attributes the machine's state to something
  // that cannot know it -- and her renderer already wanders its own mood, so she
  // was not lifeless without it.
  //
  // What that argument missed is that her SHADER was built for the whole
  // spectrum all along: familiar.frag declares uValence, uArousal, uIrritation,
  // uFatigue, uAttention, uSocial, uBuoyancy, uLuminosity and uTension, and her
  // manifest has always listed all nine. So the choice was never "give her an
  // inner life or not" -- it was whether nine uniforms built to carry a measured
  // one were fed a measured one or a wander. They are fed the real thing now,
  // and the wander remains the fallback when the relay is absent or stale.
  //
  // THE FORMAT'S PROOF MOVED TO COLOSSUS, which is a better subject for it: he
  // omits the block by design and his constitution says why, where Familiar's
  // omission was a decision that could be -- and now has been -- reversed. See
  // colossusBundle.test.ts, "OMITS the phenotype block".
  it("reads the phenotype her shader was always built to display", () => {
    expect(parseCharacterBundle(familiarBundle).phenotype).toEqual({ reads: true });
    expect(characterFromBundle(familiarBundle, [source]).readsPhenotype).toBe(true);
    // Every scalar her shader takes is declared, or the Stage would feed a
    // uniform that does not exist and the mood would silently not arrive.
    const declared = new Set(familiarBundle.visual.uniforms as string[]);
    for (const name of [
      "uValence", "uArousal", "uIrritation", "uFatigue", "uAttention",
      "uSocial", "uBuoyancy", "uLuminosity", "uTension",
    ]) expect(declared.has(name), `${name} must be declared`).toBe(true);
  });

  it("produces exactly the registry entry the stock build used to hand-write", () => {
    const familiar = characterFromBundle(familiarBundle, [source]);
    expect(familiar.id).toBe("familiar");
    expect(familiar.name).toBe("Familiar");
    expect(familiar.blurb).toBe("A living body with a private inner life of its own.");
    // She never asked for budgets, so the key stays absent and the Stage makes
    // no request for a body nobody chose.
    expect(familiar.wantsBudgets).toBeUndefined();
  });

  // The manifest names the shader by digest. If the vendored .frag moves under
  // it, this fails here rather than at first paint on someone else's machine.
  it("declares the digest of the shader the canvas actually compiles", () => {
    const digest = createHash("sha256").update(fragSrc, "utf8").digest("hex");
    const visual = parseCharacterBundle(familiarBundle).visual;
    expect(visual.type).toBe("shader");
    if (visual.type !== "shader") return;
    // PRESENT, not merely correct. `fragment` became optional so a character
    // drawn by host machinery could ship no shader file; this one DOES ship
    // one, and asserting its presence is what stops "optional" turning into
    // "absent everywhere" and the digest check covering nothing.
    expect(visual.fragment).toBeDefined();
    if (!visual.fragment) return;
    expect(visual.fragment.file).toBe("familiar.frag");
    expect(visual.fragment.sha256).toBe(digest);
  });

  it("declares every uniform the shader source can drive", () => {
    const visual = parseCharacterBundle(familiarBundle).visual;
    if (visual.type !== "shader") throw new Error("expected a shader visual");
    expect([...(visual.uniforms ?? [])].sort()).toEqual([...UNIFORMS].sort());
  });
});

describe("what the loader refuses", () => {
  // An absent capability must be VISIBLE. Each of these would otherwise render
  // a plausible-looking but wrong being, which is the worst failure available.
  it("refuses a source nobody registered instead of substituting one present", () => {
    const stranger = { ...familiarBundle, id: "stranger", name: "Stranger" };
    stranger.visual = { ...stranger.visual, source: "boltrig.canvas.companion" };
    expect(() => characterFromBundle(stranger, [source]))
      .toThrow(CharacterBundleUnsupported);
  });

  it("refuses a shader needing a uniform this canvas cannot drive", () => {
    const greedy = { ...familiarBundle };
    greedy.visual = { ...greedy.visual, uniforms: [...UNIFORMS, "uNotDriven"] };
    expect(() => characterFromBundle(greedy, [source]))
      .toThrow(/cannot supply uNotDriven/);
  });

  it("refuses an emotion model the source does not implement", () => {
    const moody = { ...familiarBundle, emotion: { model: "appraisal-v3" } };
    expect(() => characterFromBundle(moody, [source]))
      .toThrow(/does not implement emotion model "appraisal-v3"/);
  });

  it("refuses an asset path that escapes the bundle root", () => {
    const escaping = { ...familiarBundle };
    escaping.visual = {
      ...escaping.visual,
      fragment: { ...escaping.visual.fragment, file: "../../../etc/passwd" },
    };
    expect(() => parseCharacterBundle(escaping)).toThrow(CharacterBundleError);
  });

  it("refuses a manifest version this host cannot read", () => {
    expect(() => parseCharacterBundle({ ...familiarBundle, schemaVersion: 2 }))
      .toThrow(/schemaVersion/);
  });
});

describe("what a bundle may ask for, and what it may carry away", () => {
  // A character DECLARES; it never installs. Familiar declares neither, so she
  // costs no sensing request at all — the same rule budgets already follow.
  it("asks for no sensing capability, so the Stage makes no request for her", () => {
    expect(characterFromBundle(familiarBundle, [source]).wantsSensing).toBeUndefined();
  });

  it("turns a declared camera or presence want into a request the kernel governs", () => {
    const watcher = {
      ...familiarBundle,
      capabilities: {
        camera: { wanted: true, prompt: "What is happening in the room?" },
        presence: { wanted: true },
        budgets: { wanted: false },
      },
    };
    expect(characterFromBundle(watcher, [source]).wantsSensing)
      .toEqual(["camera_observations", "presence"]);
  });

  // THE ENROLLED FACE IS THE USER'S. Anchor images are the character's face and
  // travel; a shared character must not carry someone's biometrics. The export
  // is an allow-list, so a field this version has never heard of does not travel
  // either — which is the half a deny-list would eventually get wrong.
  it("exports only known fields, so nothing kernel-owned can ride along", () => {
    const smuggler = {
      ...familiarBundle,
      enrolledFace: { digest: "a".repeat(64), vectors: "…" },
      observations: ["someone was at the desk at 21:40"],
    };
    const exported = exportCharacterBundle(smuggler);
    expect("enrolledFace" in exported).toBe(false);
    expect("observations" in exported).toBe(false);
    expect(exported.id).toBe("familiar");
    expect(exported.visual).toBeTruthy();
  });

  // Emotion is inferred from THIS user's camera, so carrying it off the machine
  // is a deliberate act with a consent surface, never a side effect of copying.
  it("leaves inferred state behind unless the export was consented to", () => {
    const moody = {
      ...familiarBundle,
      emotion: { model: "autonomous-wander", travels: true, state: { valence: 0.7 } },
    };
    expect(exportCharacterBundle(moody).emotion?.state).toBeUndefined();
    expect(exportCharacterBundle(moody, { includeDerivedState: true }).emotion?.state)
      .toEqual({ valence: 0.7 });
  });

  // The bundle's own `travels: false` outranks the caller: consenting to export
  // something the character says does not travel is consent to nothing.
  it("honours a character that says its state does not travel", () => {
    const homebody = {
      ...familiarBundle,
      emotion: { model: "autonomous-wander", travels: false, state: { valence: 0.7 } },
    };
    expect(exportCharacterBundle(homebody, { includeDerivedState: true }).emotion?.state)
      .toBeUndefined();
  });
});
