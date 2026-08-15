// Binding a character BUNDLE to the canvas.
//
// A bundle is data (schemas/character-bundle/v1/character-bundle.schema.json).
// The thing that actually draws is a canvas SOURCE, and the source is Boltrig's
// — the loop, the uniform drive, the segment machinery. This module is the join
// between the two, and it is the only place a manifest turns into a registry
// entry.
//
// ONE CANVAS, A SOURCE INTERFACE. The shader source ships with the canvas in the
// public build. The companion source — the proprietary .frame.mp4 reader — is
// registered exactly the way a character is, by a private entrypoint, so the
// private distribution adds a character and its renderer as one unit and the
// public build never contains the reader.
//
// EVERY MISMATCH REFUSES BY NAME. A manifest naming a source nobody registered,
// a shader needing a uniform this canvas cannot drive, an emotion model the
// source does not implement: each throws and names what was missing. None of
// them falls back to a source that happens to be present. That is the spec's
// rule that an absent capability must be VISIBLE and never silently
// substituted, applied at the one seam where substituting would be easy.

import type { ReactNode } from "react";
import type {
  Character as SdkCharacter,
  CharacterBundleManifest,
  CharacterRenderProps as SdkCharacterRenderProps,
  FamiliarGenotype,
  FamiliarPhenotypeResponse,
} from "@wlilley93/boltrig-web-sdk";
import {
  bundleReadsPhenotype,
  bundleWantsBudgets,
  bundleWantsCamera,
  bundleWantsPresence,
  parseCharacterBundle,
} from "@wlilley93/boltrig-web-sdk";

type BundledCharacter = SdkCharacter<ReactNode, FamiliarPhenotypeResponse, FamiliarGenotype>;
type BundledRenderProps = SdkCharacterRenderProps<FamiliarPhenotypeResponse, FamiliarGenotype>;

/**
 * A way of drawing onto the one canvas. Sources are Boltrig's; bundles choose
 * between them by id and declare what they need the chosen one to do.
 */
export interface CharacterCanvasSource {
  /** Named by a manifest's `visual.source`. */
  id: string;
  /** Which kind of visual this source can draw. */
  type: CharacterBundleManifest["type"];
  /** Uniform names this source is able to drive, for a shader source. */
  supplies?: readonly string[];
  /** Emotion models this source implements. A bundle may name no other. */
  emotionModels?: readonly string[];
  render(props: BundledRenderProps, manifest: CharacterBundleManifest): ReactNode;
}

/** A bundle asked for something this install does not have. Never swallowed. */
export class CharacterBundleUnsupported extends Error {
  readonly bundleId: string;
  constructor(bundleId: string, detail: string) {
    super(`character bundle ${bundleId}: ${detail}`);
    this.name = "CharacterBundleUnsupported";
    this.bundleId = bundleId;
  }
}

function sourceFor(
  manifest: CharacterBundleManifest,
  sources: readonly CharacterCanvasSource[],
): CharacterCanvasSource {
  const found = sources.find((candidate) => candidate.id === manifest.visual.source);
  if (!found) {
    const installed = sources.map((candidate) => candidate.id).join(", ") || "none";
    throw new CharacterBundleUnsupported(
      manifest.id,
      `no canvas source "${manifest.visual.source}" is registered (installed: ${installed})`,
    );
  }
  if (found.type !== manifest.type) {
    throw new CharacterBundleUnsupported(
      manifest.id,
      `canvas source "${found.id}" draws ${found.type}, not ${manifest.type}`,
    );
  }
  return found;
}

/**
 * A shader that needs a channel the canvas cannot drive would render a subtly
 * wrong being — the worst failure available here, because it looks like it
 * worked. Refuse it and name the uniforms.
 */
function assertUniforms(
  manifest: CharacterBundleManifest,
  source: CharacterCanvasSource,
): void {
  if (manifest.visual.type !== "shader") return;
  const needed = manifest.visual.uniforms;
  if (!needed || needed.length === 0) return;
  const supplied = new Set(source.supplies ?? []);
  const missing = needed.filter((name) => !supplied.has(name));
  if (missing.length > 0) {
    throw new CharacterBundleUnsupported(
      manifest.id,
      `canvas source "${source.id}" cannot supply ${missing.join(", ")}`,
    );
  }
}

/**
 * An unimplemented emotion model must not degrade to stillness: a character
 * that silently stops having an inner life still looks alive enough to be
 * mistaken for working.
 */
function assertEmotionModel(
  manifest: CharacterBundleManifest,
  source: CharacterCanvasSource,
): void {
  const model = manifest.emotion?.model;
  if (!model) return;
  if (!(source.emotionModels ?? []).includes(model)) {
    throw new CharacterBundleUnsupported(
      manifest.id,
      `canvas source "${source.id}" does not implement emotion model "${model}"`,
    );
  }
}

/**
 * Validates a manifest, binds it to a canvas source, and returns something the
 * registry accepts. Every field the registry reads comes from the manifest:
 * change the JSON and the settings surface changes with it.
 *
 * `wantsBudgets` is set only when the bundle asked, and left undefined
 * otherwise, because the Stage reads presence-of-key to decide whether to poll.
 */
export function characterFromBundle(
  bundle: unknown,
  sources: readonly CharacterCanvasSource[],
): BundledCharacter {
  const manifest = parseCharacterBundle(bundle);
  const source = sourceFor(manifest, sources);
  assertUniforms(manifest, source);
  assertEmotionModel(manifest, source);

  const character: BundledCharacter = {
    id: manifest.id,
    name: manifest.name,
    blurb: manifest.blurb,
    // Absence of the phenotype field is the whole point: a character with none
    // omits it, and is handed null rather than asked to ignore a live one.
    readsPhenotype: bundleReadsPhenotype(manifest),
    render: (props) => source.render(props, manifest),
  };
  if (manifest.voice?.fallbackVoiceIds) {
    character.voiceIds = Object.freeze({ ...manifest.voice.fallbackVoiceIds });
  }
  if (bundleWantsBudgets(manifest)) character.wantsBudgets = true;
  // DECLARED, never installed. The bundle says which sensing capabilities it
  // would like; the Stage asks the kernel and hands back the answer, refusal
  // included. A bundle that declares nothing here causes no request at all,
  // which is also how the shipped shader characters behave.
  const sensing: string[] = [];
  if (bundleWantsCamera(manifest)) sensing.push("camera_observations");
  if (bundleWantsPresence(manifest)) sensing.push("presence");
  if (sensing.length > 0) character.wantsSensing = sensing;
  return character;
}
