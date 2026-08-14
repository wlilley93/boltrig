// The user may choose a character's voice; the system may never guess one.
//
// These two properties pull against each other, which is why they are tested
// together: an override that works is easy, and an override that does not
// quietly become a fallback for every character with no declared voice is the
// part worth pinning.

import { describe, expect, it } from "vitest";

import familiar from "../src/bundles/familiar/character.json";
import {
  OVERRIDE_PROVIDER,
  VOICE_OVERRIDE_SETTING_KEY,
  resolveVoiceId,
  selectableVoices,
  voiceOverrideFromSettings,
  voiceOverrideToSettings,
} from "../src/characterVoice";

const manifest = familiar as unknown as Parameters<typeof resolveVoiceId>[0];
const silent = { id: "ghost", name: "Ghost", type: "shader", schemaVersion: 1 } as unknown as
  Parameters<typeof resolveVoiceId>[0];

describe("Familiar's shipped voice", () => {
  it("declares marius, which is CC0 and therefore shippable", () => {
    // marius resolves to hf://kyutai/tts-voices/voice-donations/Selfie.wav, and
    // voice-donations is CC0. This assertion is about LICENSING as much as
    // sound: cosette (Expresso) and jean (EARS) are CC-BY-NC and cannot ship in
    // a commercial build, so the default must never drift onto one of them.
    expect(resolveVoiceId(manifest, OVERRIDE_PROVIDER, undefined, "familiar")).toBe("marius");
  });

  it("names no cloud voice id, so the stock build needs no vendor account", () => {
    expect(resolveVoiceId(manifest, "elevenlabs", undefined, "familiar")).toBeUndefined();
    expect(resolveVoiceId(manifest, "fish", undefined, "familiar")).toBeUndefined();
  });
});

describe("the user's choice", () => {
  const settings = { [VOICE_OVERRIDE_SETTING_KEY]: { familiar: "javert" } };

  it("wins over what the bundle declares", () => {
    expect(resolveVoiceId(manifest, OVERRIDE_PROVIDER, settings, "familiar")).toBe("javert");
  });

  it("is per character, so choosing one does not repoint another", () => {
    expect(voiceOverrideFromSettings(settings, "familiar")).toBe("javert");
    expect(voiceOverrideFromSettings(settings, "jarvis")).toBeUndefined();
  });

  it("clears back to the bundle's voice rather than to silence", () => {
    const cleared = voiceOverrideToSettings(settings, "familiar", null);
    expect(cleared[VOICE_OVERRIDE_SETTING_KEY]).toEqual({});
    expect(resolveVoiceId(manifest, OVERRIDE_PROVIDER, cleared, "familiar")).toBe("marius");
  });

  it("survives a malformed sibling entry instead of losing every voice", () => {
    const messy = { [VOICE_OVERRIDE_SETTING_KEY]: { familiar: "javert", jarvis: { nope: 1 } } };
    expect(voiceOverrideFromSettings(messy, "familiar")).toBe("javert");
    expect(voiceOverrideFromSettings(messy, "jarvis")).toBeUndefined();
  });

  it("rejects a shape that is not a voice id", () => {
    for (const bad of ["../../etc/passwd", "a b", "", "x".repeat(65)]) {
      const written = voiceOverrideToSettings(undefined, "familiar", bad);
      expect(written[VOICE_OVERRIDE_SETTING_KEY]).toEqual({});
    }
  });
});

describe("an override is not a fallback", () => {
  it("never speaks a character that declares no voice", () => {
    // THE LOAD-BEARING TEST. bundleVoiceId returns undefined for a silent
    // character and the SDK is explicit that callers must not substitute. A
    // user override for `ghost` is honoured for ghost -- but must not leak into
    // any other character, and must not manufacture a voice from Familiar's.
    expect(resolveVoiceId(silent, OVERRIDE_PROVIDER, undefined, "ghost")).toBeUndefined();
    const forFamiliar = { [VOICE_OVERRIDE_SETTING_KEY]: { familiar: "javert" } };
    expect(resolveVoiceId(silent, OVERRIDE_PROVIDER, forFamiliar, "ghost")).toBeUndefined();
  });

  it("applies only to the provider with a browsable catalogue", () => {
    const settings = { [VOICE_OVERRIDE_SETTING_KEY]: { familiar: "javert" } };
    // A cloud id is an opaque handle from that vendor's account; a name picked
    // out of the local catalogue is meaningless there and must not be sent.
    expect(resolveVoiceId(manifest, "elevenlabs", settings, "familiar")).toBeUndefined();
  });
});

describe("the picker's options come from the runtime", () => {
  it("puts local clones first, because a local name wins at speak time", () => {
    const listed = selectableVoices({ local: ["maya", "marius"], catalog: ["marius", "javert"] });
    expect(listed).toEqual(["maya", "marius", "javert"]);
  });

  it("degrades to empty rather than throwing when the runtime is down", () => {
    expect(selectableVoices(undefined)).toEqual([]);
    expect(selectableVoices({})).toEqual([]);
    expect(selectableVoices({ local: "nonsense", catalog: null })).toEqual([]);
  });
});
