// The character contract: who can be on the Stage and how each one draws.
//
// This lives in the SDK rather than in the Worker because characters.ts already
// argues that characters beyond the ones boltrig ships belong in plugins — and
// a plugin could not reach any of it. registerCharacter, the Character shape and
// the turn input were all Worker-internal, imported by relative path, so
// registration was a function nobody outside could call. Moving the REGISTRY
// here is what makes the extension point real; the Worker registers into it on
// exactly the same terms an add-in does.
//
// GENERIC OVER THE RENDERED NODE ON PURPOSE. This package is framework-agnostic
// and has no react dependency, which is the whole basis of it being shared by
// opbox and the Worker. `render` therefore returns TNode, and the Worker
// instantiates Character<ReactNode>. Baking ReactNode in here would buy one
// convenience and cost the package its reason to exist.

import type { NormalizedTurn } from "./chatTurnTypes.js";
import type { SensingCapabilityDecision } from "./types.js";

/**
 * What a character is told when it asks for a sensing capability. Named here
 * because a plugin reads it off its render props and would otherwise have to
 * reach for the client module to learn the shape of its own refusal.
 */
export type SensingDecision = SensingCapabilityDecision;

/** How much of the shell the Stage currently owns. */
export type CharacterPresentationMode =
  | "hero"
  | "conversation"
  | "voice"
  | "minimised";

/** Short name used by character add-ins. */
export type PresentationMode = CharacterPresentationMode;

/** The turn facts every character reads. None carries text, audio or identity. */
export interface CharacterTurnInput {
  loading: boolean;
  hasLiveEvents: boolean;
  liveEnded: boolean;
  voiceSpeaking: boolean;
  voiceLevel: number;
  voiceBands?: number[] | null;
  voiceOnset?: number;
  micActive?: boolean;
  micLevel?: number;
}

/** Short name used by character add-ins. */
export type StageTurnInput = CharacterTurnInput;

/** What a body needs to draw itself, once a character has read the turn. */
export interface CharacterStageState {
  working: boolean;
  speaking: boolean;
  level: number;
  bands?: number[] | null;
  onset?: number;
}

/** Short name used by character add-ins. */
export type StageState = CharacterStageState;

/** The host's bounded phenotype projection; no raw identity or content. */
export type PhenotypeResponse = unknown;

export interface CharacterRenderProps<TPhenotype = unknown, TGenotype = unknown> {
  input: CharacterTurnInput;
  mode: CharacterPresentationMode;
  /**
   * Already gated by `readsPhenotype`: a character that does not read the
   * appraisal engine is handed null here, not asked to ignore a live one.
   */
  phenotype: TPhenotype | null;
  /** Budgets, polled only for characters that asked for them. */
  budgets: unknown;
  /**
   * The answer to every sensing capability this character DECLARED, keyed by
   * capability id — and it is often a refusal.
   *
   * A character does not own a camera; it asks a daemon the USER owns and can
   * switch off, and it is told plainly when the answer is no. The refusal
   * carries a reason, so a body can show that it cannot see rather than
   * pretending it can or falling back on a stale frame. A character that
   * declared nothing is handed an empty object and makes no request.
   */
  sensing: Record<string, SensingDecision>;
  /** The live turn, narrowed to what a body may draw from. NormalizedTurn is
   *  this package's own model, so naming it here costs no coupling and saves
   *  every host casting `unknown` back to it at the render site. */
  turn?: Pick<NormalizedTurn, "tools" | "subagents" | "steps"> | null;
  genotype?: TGenotype | null;
  label?: string;
  /**
   * Which of the character's skins to draw. Absent, or naming one the character
   * does not offer, means the first -- a stored skin from an uninstalled
   * variant costs the Stage a look, never a render.
   */
  skin?: string;
}

/** Short name used by character add-ins. */
export type StageRenderProps<TPhenotype = unknown, TGenotype = unknown> =
  CharacterRenderProps<TPhenotype, TGenotype>;

export type CharacterId = string;

/**
 * One selectable LOOK for a character -- structurally the bundle's skin entry.
 *
 * Declared on the character rather than discovered from its bundle so that a
 * picker can ask any registered character what looks it offers. A plugin that
 * registers directly, with no manifest at all, can still have skins.
 */
export interface CharacterSkin {
  id: string;
  name?: string;
  blurb?: string;
}

export interface Character<TNode = unknown, TPhenotype = unknown, TGenotype = unknown> {
  id: CharacterId;
  name: string;
  /**
   * Does this character read the server phenotype (decision 0013)?
   *
   * False does not mean "lifeless" — the Familiar still wanders. It means the
   * appraisal engine is not this character's source of truth, so handing it a
   * phenotype would attribute the machine's mood to a creature that has no
   * access to it.
   */
  readsPhenotype: boolean;
  /** True to have the Stage poll budgets; a body nobody chose costs no request. */
  wantsBudgets?: boolean;
  /**
   * Sensing capabilities this character DECLARED it would like, by id.
   *
   * A declaration, never an installation: the Stage asks the kernel on the
   * character's behalf and hands back whatever it says, which for a user who
   * has the camera off is a refusal with a reason. Set only when the bundle
   * asked, so a character that wants nothing makes no request.
   */
  wantsSensing?: readonly string[];
  /**
   * Provider-specific voice ids declared by the character bundle. These are
   * public model/voice names, never credentials. Absence means this character
   * is silent on that provider; hosts must not substitute another voice.
   */
  voiceIds?: Readonly<Record<string, string>>;
  blurb: string;
  /**
   * Looks this character offers, FIRST IS DEFAULT. Absent means one look --
   * the honest encoding, because an array of one implies a choice that does not
   * exist and every picker would have to special-case it.
   *
   * Presentation only. A skin never changes prompts, dispatch or voice, so the
   * character you are talking to is the same character either way.
   */
  skins?: readonly CharacterSkin[];
  render(props: CharacterRenderProps<TPhenotype, TGenotype>): TNode;
}

const REGISTRY = new Map<string, Character<never>>();
const LISTENERS = new Set<() => void>();
const CHARACTER_ID = /^[a-z][a-z0-9-]{0,63}$/;
const MAX_CHARACTER_NAME = 64;
const MAX_CHARACTER_BLURB = 240;
let revision = 0;

/** The one id grammar shared by plugin registration and persisted settings. */
export function isCharacterId(value: unknown): value is CharacterId {
  return typeof value === "string" && CHARACTER_ID.test(value);
}

function isSafeLabel(value: unknown, maxLength: number): value is string {
  return typeof value === "string"
    && value.length > 0
    && value.length <= maxLength
    && value === value.trim()
    && !/[\p{Cc}\p{Cf}\p{Cs}\p{Zl}\p{Zp}]/u.test(value);
}

/** Monotonic snapshot for framework adapters such as React useSyncExternalStore. */
export function characterRegistryRevision(): number {
  return revision;
}

/** Notify a host when a compile-time or lazy plugin adds a character. */
export function subscribeCharacters(listener: () => void): () => void {
  LISTENERS.add(listener);
  return () => LISTENERS.delete(listener);
}

/**
 * Adds a character. Ids and display names are unique and validated so import
 * order cannot silently replace a stock body or make one settings button select
 * another character.
 */
export function registerCharacter<TNode, TPhenotype, TGenotype>(
  character: Character<TNode, TPhenotype, TGenotype>,
): void {
  if (!isCharacterId(character.id)) {
    throw new TypeError("character id must match [a-z][a-z0-9-]{0,63}");
  }
  if (!isSafeLabel(character.name, MAX_CHARACTER_NAME)) {
    throw new TypeError("character name must be a trimmed, safe 1..64 character label");
  }
  if (!isSafeLabel(character.blurb, MAX_CHARACTER_BLURB)) {
    throw new TypeError("character blurb must be trimmed, safe, and at most 240 characters");
  }
  if (typeof character.readsPhenotype !== "boolean" || typeof character.render !== "function") {
    throw new TypeError("character must declare readsPhenotype and a render function");
  }
  if (character.voiceIds) {
    for (const [provider, voice] of Object.entries(character.voiceIds)) {
      if (!isSafeLabel(provider, 64) || !isSafeLabel(voice, 128)) {
        throw new TypeError("character voice ids must be safe provider/voice labels");
      }
    }
  }
  if (REGISTRY.has(character.id)) {
    throw new TypeError(`character id is already registered: ${character.id}`);
  }
  const foldedName = character.name.toLowerCase();
  if ([...REGISTRY.values()].some((candidate) => candidate.name.toLowerCase() === foldedName)) {
    throw new TypeError(`character name is already registered: ${character.name}`);
  }
  // Keep the registry invariants true after registration. A JavaScript add-in
  // can retain and mutate the object it passed us even though TypeScript users
  // normally treat the contract as declarative. Storing that live reference
  // lets it change its id/name/render after validation, so the map key, the
  // Settings label and the body actually rendered can silently disagree.
  const registered = Object.freeze({
    ...character,
    ...(character.voiceIds
      ? { voiceIds: Object.freeze({ ...character.voiceIds }) }
      : {}),
  });
  REGISTRY.set(character.id, registered as unknown as Character<never>);
  revision += 1;
  // Registration is already committed at this point. A broken host listener
  // must not make the add-in observe a thrown "failure" while the registry has
  // in fact changed, nor prevent the remaining hosts from seeing the revision.
  for (const listener of LISTENERS) {
    try {
      listener();
    } catch {
      // Subscribers are render invalidation hints, not part of registration's
      // transaction or an authority boundary.
    }
  }
}

/** Everything installed, for the settings surface to offer. */
export function listCharacters<TNode = unknown>(): Character<TNode>[] {
  return [...REGISTRY.values()] as unknown as Character<TNode>[];
}

export function isCharacterRegistered(id: string): boolean {
  return REGISTRY.has(id);
}

/**
 * Resolves an id to something drawable, falling back through the supplied
 * default. An unregistered id — an uninstalled plugin, or a setting carried
 * over from a build that shipped it — costs the Stage its body and nothing
 * else, so this returns undefined rather than throwing and lets the caller
 * decide the fallback it ships.
 */
export function characterFor<TNode = unknown>(
  id: CharacterId,
  fallbackId?: CharacterId,
): Character<TNode> | undefined {
  const found = REGISTRY.get(id) ?? (fallbackId ? REGISTRY.get(fallbackId) : undefined);
  return found as unknown as Character<TNode> | undefined;
}
