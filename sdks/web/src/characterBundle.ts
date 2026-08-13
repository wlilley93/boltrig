// The character bundle: a portable package of DATA plus DECLARED behaviour.
//
// This is the runtime half of schemas/character-bundle/v1/character-bundle.schema.json.
// It lives beside characters.ts for the same reason characters.ts lives here at
// all: the registry is the extension point, and a bundle that could not be
// parsed by anything outside the Worker would be an extension point nothing can
// reach.
//
// A BUNDLE CARRIES NO EXECUTABLE CODE. Everything below is JSON. That is not a
// restriction accepted reluctantly, it is the whole security property: a
// character is a thing you might download from a stranger, and a downloaded
// character must never be able to run a process that watches you through your
// camera or reads your enrolled face. It can only ask a question through a
// daemon YOU own and YOU can switch off.
//
// FAILURE IS LOUD ON PURPOSE. Every check below throws with the field name in
// the message. The spec's rule is that an absent capability degrades VISIBLY
// and is never silently substituted, and a validator that coerced a malformed
// manifest into a working-looking character would break that rule at the first
// hop.

export const CHARACTER_BUNDLE_SCHEMA_VERSION = 1;

/** What the character IS. A flag, never a fork in the architecture. */
export type CharacterBundleType = "shader" | "companion";

export interface CharacterBundleAssetRef {
  /** Relative to the bundle root. Never absolute, never escaping the root. */
  file: string;
  sha256: string;
}

export interface CharacterBundlePrompts {
  persona?: string;
  system?: string;
  style?: string;
}

export interface CharacterBundleShaderVisual {
  type: "shader";
  /** Id of the canvas source that draws this character. */
  source: string;
  fragment: CharacterBundleAssetRef;
  /** Uniform names the shader NEEDS; checked against what the source supplies. */
  uniforms?: string[];
}

export interface CharacterBundleCompanionVisual {
  type: "companion";
  source: string;
  frame: CharacterBundleAssetRef;
  segments?: CharacterBundleAssetRef;
  directions?: string[];
  restrictedScene?: {
    frame: CharacterBundleAssetRef;
    segments?: CharacterBundleAssetRef;
    /** A kernel user setting. Binary, explicit, revocable, never inferred. */
    permission: string;
  };
}

export type CharacterBundleVisual =
  | CharacterBundleShaderVisual
  | CharacterBundleCompanionVisual;

export interface CharacterBundlePhenotype {
  reads: boolean;
  travels?: boolean;
  state?: Record<string, number>;
}

export interface CharacterBundleEmotion {
  model: string;
  travels?: boolean;
  state?: Record<string, number>;
}

export interface CharacterBundleCapabilities {
  camera?: { wanted: boolean; prompt?: string; diary?: string; observations?: string[] };
  presence?: { wanted: boolean };
  budgets?: { wanted: boolean };
  automations?: string[];
}

export interface CharacterBundleManifest {
  schemaVersion: typeof CHARACTER_BUNDLE_SCHEMA_VERSION;
  id: string;
  name: string;
  blurb: string;
  type: CharacterBundleType;
  visual: CharacterBundleVisual;
  /**
   * Optional, and the spec says otherwise. Neither shipped character has any:
   * Familiar and Jarvis are BODIES, and the Worker's character contract is
   * explicitly presentational. See the schema's note on this field.
   */
  prompts?: CharacterBundlePrompts;
  /** ABSENT means no phenotype at all — never an empty object. */
  phenotype?: CharacterBundlePhenotype;
  emotion?: CharacterBundleEmotion;
  identity?: {
    anchorImages?: CharacterBundleAssetRef[];
    visualLora?: CharacterBundleAssetRef;
    exampleClips?: CharacterBundleAssetRef[];
  };
  voice?: {
    selfHosted?: {
      referenceAudio?: CharacterBundleAssetRef;
      lora?: CharacterBundleAssetRef;
    };
    fallbackVoiceIds?: Record<string, string>;
  };
  capabilities?: CharacterBundleCapabilities;
  distillation?: { enabled: boolean; schedule?: string; corpus?: string[] };
  /** Provider NAMES the character wishes to use. Never keys. */
  credentials?: { providers: string[] };
  provenance?: { upstream?: string; note?: string; ships?: boolean };
}

/** Thrown by every check below, so a caller can tell a bad manifest from a bug. */
export class CharacterBundleError extends Error {
  readonly field: string;
  constructor(field: string, detail: string) {
    super(`character bundle: ${field} ${detail}`);
    this.name = "CharacterBundleError";
    this.field = field;
  }
}

const BUNDLE_ID = /^[a-z][a-z0-9-]{0,63}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const UNIFORM = /^[A-Za-z_][A-Za-z0-9_]*$/;
const UNSAFE_LABEL = /[\p{Cc}\p{Cf}\p{Cs}\p{Zl}\p{Zp}]/u;

function record(value: unknown, field: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new CharacterBundleError(field, "must be an object");
  }
  return value as Record<string, unknown>;
}

function label(value: unknown, field: string, maxLength: number): string {
  if (typeof value !== "string" || value.length === 0 || value.length > maxLength
    || value !== value.trim() || UNSAFE_LABEL.test(value)) {
    throw new CharacterBundleError(field, `must be a trimmed, safe 1..${maxLength} character label`);
  }
  return value;
}

function optionalBoolean(value: unknown, field: string): boolean | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "boolean") throw new CharacterBundleError(field, "must be a boolean");
  return value;
}

/**
 * A path inside the bundle root. The bundle must be copyable as a directory, so
 * an absolute path or a `..` segment is a refusal rather than something to
 * normalise: normalising it would silently reach outside the thing being copied.
 */
function assetRef(value: unknown, field: string): CharacterBundleAssetRef {
  const asset = record(value, field);
  const file = asset.file;
  if (typeof file !== "string" || file.length === 0) {
    throw new CharacterBundleError(`${field}.file`, "must be a non-empty relative path");
  }
  if (file.startsWith("/") || file.split("/").includes("..")) {
    throw new CharacterBundleError(`${field}.file`, "must not escape the bundle root");
  }
  if (typeof asset.sha256 !== "string" || !SHA256.test(asset.sha256)) {
    throw new CharacterBundleError(`${field}.sha256`, "must be a lowercase hex sha256 digest");
  }
  return { file, sha256: asset.sha256 };
}

function uniforms(value: unknown, field: string): string[] | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value)) throw new CharacterBundleError(field, "must be an array");
  const names = value.map((name, index) => {
    if (typeof name !== "string" || !UNIFORM.test(name)) {
      throw new CharacterBundleError(`${field}[${index}]`, "must be a GLSL identifier");
    }
    return name;
  });
  if (new Set(names).size !== names.length) {
    throw new CharacterBundleError(field, "must not repeat a uniform name");
  }
  return names;
}

function shaderVisual(visual: Record<string, unknown>): CharacterBundleShaderVisual {
  return {
    type: "shader",
    source: label(visual.source, "visual.source", 128),
    fragment: assetRef(visual.fragment, "visual.fragment"),
    uniforms: uniforms(visual.uniforms, "visual.uniforms"),
  };
}

function companionVisual(visual: Record<string, unknown>): CharacterBundleCompanionVisual {
  const restricted = visual.restrictedScene === undefined
    ? undefined
    : record(visual.restrictedScene, "visual.restrictedScene");
  return {
    type: "companion",
    source: label(visual.source, "visual.source", 128),
    frame: assetRef(visual.frame, "visual.frame"),
    segments: visual.segments === undefined
      ? undefined
      : assetRef(visual.segments, "visual.segments"),
    directions: uniforms(visual.directions, "visual.directions"),
    restrictedScene: restricted && {
      frame: assetRef(restricted.frame, "visual.restrictedScene.frame"),
      segments: restricted.segments === undefined
        ? undefined
        : assetRef(restricted.segments, "visual.restrictedScene.segments"),
      // Checked at SELECTION time by the player, never cached into director
      // state, so revoking it takes effect on the next turn.
      permission: label(restricted.permission, "visual.restrictedScene.permission", 128),
    },
  };
}

function visualOf(value: unknown): CharacterBundleVisual {
  const visual = record(value, "visual");
  if (visual.type === "shader") return shaderVisual(visual);
  if (visual.type === "companion") return companionVisual(visual);
  throw new CharacterBundleError("visual.type", 'must be "shader" or "companion"');
}

function phenotypeOf(value: unknown): CharacterBundlePhenotype | undefined {
  // The load-bearing absence. A character with no phenotype OMITS the field;
  // it does not carry an empty one, and nothing here invents a default for it.
  if (value === undefined) return undefined;
  const phenotype = record(value, "phenotype");
  if (typeof phenotype.reads !== "boolean") {
    throw new CharacterBundleError("phenotype.reads", "must be a boolean when phenotype is present");
  }
  return {
    reads: phenotype.reads,
    travels: optionalBoolean(phenotype.travels, "phenotype.travels"),
    state: phenotype.state === undefined
      ? undefined
      : (record(phenotype.state, "phenotype.state") as Record<string, number>),
  };
}

function emotionOf(value: unknown): CharacterBundleEmotion | undefined {
  if (value === undefined) return undefined;
  const emotion = record(value, "emotion");
  return {
    model: label(emotion.model, "emotion.model", 128),
    travels: optionalBoolean(emotion.travels, "emotion.travels"),
    state: emotion.state === undefined
      ? undefined
      : (record(emotion.state, "emotion.state") as Record<string, number>),
  };
}

/**
 * Validates a manifest and returns it typed. Unknown top-level keys are kept as
 * written rather than stripped: a host that does not understand a field must
 * not quietly delete it on the way through, or a round-trip through an older
 * Boltrig would silently strip a newer character's data.
 */
export function parseCharacterBundle(value: unknown): CharacterBundleManifest {
  const manifest = record(value, "manifest");
  if (manifest.schemaVersion !== CHARACTER_BUNDLE_SCHEMA_VERSION) {
    throw new CharacterBundleError(
      "schemaVersion",
      `must be ${CHARACTER_BUNDLE_SCHEMA_VERSION}; refusing a manifest this host cannot read`,
    );
  }
  if (typeof manifest.id !== "string" || !BUNDLE_ID.test(manifest.id)) {
    throw new CharacterBundleError("id", "must match [a-z][a-z0-9-]{0,63}");
  }
  if (manifest.type !== "shader" && manifest.type !== "companion") {
    throw new CharacterBundleError("type", 'must be "shader" or "companion"');
  }
  const visual = visualOf(manifest.visual);
  if (visual.type !== manifest.type) {
    throw new CharacterBundleError("visual.type", "must agree with the manifest type");
  }
  return {
    ...manifest,
    schemaVersion: CHARACTER_BUNDLE_SCHEMA_VERSION,
    id: manifest.id,
    name: label(manifest.name, "name", 64),
    blurb: label(manifest.blurb, "blurb", 240),
    type: manifest.type,
    visual,
    phenotype: phenotypeOf(manifest.phenotype),
    emotion: emotionOf(manifest.emotion),
  } as CharacterBundleManifest;
}

/** Does this bundle read the host's measured affective state? Absence is false. */
export function bundleReadsPhenotype(manifest: CharacterBundleManifest): boolean {
  return manifest.phenotype?.reads === true;
}

/** Polling budgets costs a request, so only a character that asked for them gets them. */
export function bundleWantsBudgets(manifest: CharacterBundleManifest): boolean {
  return manifest.capabilities?.budgets?.wanted === true;
}

/** Does this bundle DECLARE that it would like the camera? A declaration only. */
export function bundleWantsCamera(manifest: CharacterBundleManifest): boolean {
  return manifest.capabilities?.camera?.wanted === true;
}

/** Does this bundle DECLARE that it would like presence? A declaration only. */
export function bundleWantsPresence(manifest: CharacterBundleManifest): boolean {
  return manifest.capabilities?.presence?.wanted === true;
}

/**
 * Every field a bundle may carry out of this install.
 *
 * AN ALLOW-LIST, NOT A DENY-LIST, and that is the whole point. A deny-list has
 * to be updated every time the kernel learns to hold something new about the
 * user, and the update that gets forgotten is the one that leaks. Anything not
 * named here does not travel, including fields this version has never heard of.
 */
const EXPORTABLE_BUNDLE_FIELDS = [
  "$schema", "schemaVersion", "id", "name", "blurb", "type", "visual",
  "prompts", "phenotype", "emotion", "identity", "voice", "capabilities",
  "distillation", "credentials", "provenance",
] as const;

/**
 * THE ENROLLED FACE IS KERNEL DATA AND NEVER TRAVELS.
 *
 * `identity.anchorImages` is the CHARACTER's face; `~/pixy-stream/identity/`
 * (kernel key `sensing.enrollment`) is the USER's. A character is a thing you
 * might hand to someone else, and a shared character must not carry someone's
 * biometrics — so this is the one place the "likeness belongs to the character"
 * rule is deliberately overridden. The exclusion is structural rather than a
 * filtering step: the enrolled face has no field in the manifest schema at all,
 * nothing here can read it, and the kernel never serves it (see
 * `boltrig/kernel/sensing_policy.py`, `NEVER_LEAVES_THE_KERNEL`, and the
 * enrolment projection whose `exportable` is a constant `false`).
 *
 * `camera.diary` and `camera.prompt` DO travel: what the character asks about a
 * frame is the character's. The frames, the observations, the retention window
 * and the enrolled face are Boltrig's and stay behind.
 */
export interface CharacterBundleExportOptions {
  /**
   * Carry inferred affective state. Emotion is derived from THIS user's camera,
   * so exporting it moves an inference about a person off a device they
   * control. Default `false` deliberately: the spec makes carrying it a
   * deliberate act with a consent surface, never a silent side effect of
   * copying a directory.
   */
  includeDerivedState?: boolean;
}

/**
 * The bundle as it leaves this install. Validates first, so an export cannot
 * launder a manifest that would be refused on the way back in.
 */
export function exportCharacterBundle(
  value: unknown,
  options: CharacterBundleExportOptions = {},
): CharacterBundleManifest {
  const manifest = parseCharacterBundle(value);
  const source = manifest as unknown as Record<string, unknown>;
  const exported: Record<string, unknown> = {};
  for (const field of EXPORTABLE_BUNDLE_FIELDS) {
    if (source[field] !== undefined) exported[field] = source[field];
  }

  // `travels: false` is the bundle's own statement that its state is not
  // portable, and it outranks the caller's consent: consenting to export
  // something the character says does not travel is consent to nothing.
  const carries = options.includeDerivedState === true;
  if (manifest.phenotype) {
    const travels = carries && manifest.phenotype.travels !== false;
    exported.phenotype = travels
      ? manifest.phenotype
      : { ...manifest.phenotype, state: undefined };
  }
  if (manifest.emotion) {
    const travels = carries && manifest.emotion.travels !== false;
    exported.emotion = travels
      ? manifest.emotion
      : { ...manifest.emotion, state: undefined };
  }
  return exported as unknown as CharacterBundleManifest;
}
