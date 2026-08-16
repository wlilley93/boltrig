// Which voice a character speaks with, when the USER has chosen one.
//
// This is deliberately a separate module from the bundle's own declaration, and
// the distinction it draws is the whole reason it exists.
//
// `bundleVoiceId()` in the web SDK answers "what does this BUNDLE declare", and
// its contract is strict: undefined means silence or an honest refusal, "never
// another character's voice ... callers must not fall back to a default here;
// substituting is exactly the failure this returns undefined to prevent."
//
// A user override is not a substitution. Nobody guessed; a person opened
// Settings and picked. So the override is applied HERE, above that call, rather
// than by loosening it -- which would turn every absent declaration into a
// silent guess and lose the property the SDK is protecting.
//
// Resolution order, and there are only two steps on purpose:
//
//     user override (this module)  ->  bundle declaration  ->  undefined
//
// `undefined` still means silence. Nothing in this file invents a voice.

import {
  bundleVoiceId,
  type Character,
  type CharacterBundleManifest,
} from "@wlilley93/boltrig-web-sdk";

import type { CharacterId } from "./character";

/**
 * Key inside the kernel's /v1/me/settings bag: character id -> voice id.
 *
 * A map rather than one value, because the choice is per character. Jarvis and
 * Familiar are different voices in the same install, and a single key would
 * make picking one silently repoint the other.
 */
export const VOICE_OVERRIDE_SETTING_KEY = "agent.voice";

/** Persisted opt-in for speaking completed text-chat replies. */
export const READ_REPLIES_SETTING_KEY = "voice.read_replies";

/**
 * The provider a browsable override applies to.
 *
 * Only the self-hosted runtime publishes a catalogue the user can page through
 * (`voice.voices.list` answers `{local, catalog}`), so it is the only provider
 * an override can meaningfully name. A cloud provider's id is an opaque string
 * from that vendor's account, not something to offer in a picker.
 */
export const OVERRIDE_PROVIDER = "pocket-voice";

/** A voice id is an opaque name from the runtime; validate shape, never a list. */
const VOICE_ID = /^[a-z0-9][a-z0-9._-]{0,63}$/i;

function readMap(settings: Record<string, unknown> | undefined): Record<string, string> {
  const raw = settings?.[VOICE_OVERRIDE_SETTING_KEY];
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  const out: Record<string, string> = {};
  for (const [character, voice] of Object.entries(raw as Record<string, unknown>)) {
    // A malformed entry is dropped rather than throwing: a settings bag is
    // shared, hand-editable and forward-compatible, so one bad key must not
    // take the other characters' voices down with it.
    if (typeof voice === "string" && VOICE_ID.test(voice)) out[character] = voice;
  }
  return out;
}

/** The voice this user chose for this character, or undefined if they have not. */
export function voiceOverrideFromSettings(
  settings: Record<string, unknown> | undefined,
  character: CharacterId,
): string | undefined {
  return readMap(settings)[character];
}

/**
 * The settings patch that records (or clears) a choice.
 *
 * Clearing writes the map back WITHOUT the key rather than writing null, so
 * "the user never chose" and "the user chose nothing" stay the same state --
 * both mean fall through to what the bundle declares.
 */
export function voiceOverrideToSettings(
  settings: Record<string, unknown> | undefined,
  character: CharacterId,
  voice: string | null,
): Record<string, unknown> {
  const map = readMap(settings);
  if (voice && VOICE_ID.test(voice)) map[character] = voice;
  else delete map[character];
  return { [VOICE_OVERRIDE_SETTING_KEY]: map };
}

/**
 * The voice id to speak this character with, honouring the user's choice.
 *
 * Returns undefined when neither the user nor the bundle names one, which the
 * caller must treat as silence. Do not add a default here.
 */
export function resolveVoiceId(
  manifest: CharacterBundleManifest,
  provider: string,
  settings: Record<string, unknown> | undefined,
  character: CharacterId,
): string | undefined {
  if (provider === OVERRIDE_PROVIDER) {
    const chosen = voiceOverrideFromSettings(settings, character);
    if (chosen) return chosen;
  }
  return bundleVoiceId(manifest, provider);
}

/** Registry equivalent of resolveVoiceId for a character already installed. */
export function resolveRegisteredVoiceId(
  character: Pick<Character, "id" | "voiceIds">,
  provider: string,
  settings: Record<string, unknown> | undefined,
): string | undefined {
  if (provider === OVERRIDE_PROVIDER) {
    const chosen = voiceOverrideFromSettings(settings, character.id);
    if (chosen) return chosen;
  }
  return character.voiceIds?.[provider];
}

export function readRepliesFromSettings(
  settings: Record<string, unknown> | undefined,
): boolean {
  return settings?.[READ_REPLIES_SETTING_KEY] === true;
}

export function readRepliesToSettings(enabled: boolean): Record<string, unknown> {
  return { [READ_REPLIES_SETTING_KEY]: enabled };
}

/**
 * Voices this install may offer in a picker, from the runtime's own catalogue.
 *
 * TAKES the catalogue rather than fetching it: it arrives from the kernel verb
 * `voice.voices.list`, and hard-coding the names here would drift the first
 * time the runtime gains a voice -- the failure this estate has already paid
 * for with copied constants.
 *
 * `local` first: a locally cloned voice of the same name WINS over a catalogue
 * one in the runtime (server.py resolves local before catalogue), so the picker
 * must show the one that would actually speak.
 */
export function selectableVoices(
  catalogue: { local?: unknown; catalog?: unknown } | undefined,
): string[] {
  const take = (v: unknown): string[] =>
    Array.isArray(v) ? v.filter((x): x is string => typeof x === "string" && VOICE_ID.test(x)) : [];
  const local = take(catalogue?.local);
  const stock = take(catalogue?.catalog).filter((name) => !local.includes(name));
  return [...local, ...stock];
}
