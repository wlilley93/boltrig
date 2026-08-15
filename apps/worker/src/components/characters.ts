// The character registry: who can be on the Stage, and how each one draws.
//
// Emotion was modelled as a global add-on: the relay published a phenotype and
// whatever body was mounted consumed it. That was the wrong seam. An inner life
// belongs to a CHARACTER, not to an installation.
//
// The Familiar is a creature with its own private life. It wanders its own mood
// (see FamiliarWebGLRenderer's mood model) and is not wired to the appraisal
// engine — its state is its own, and always was. Jarvis is the opposite, and
// that is the whole point of him: he reads the machine's measured affective
// state and his body displays it.
//
// WHY A REGISTRY RATHER THAN A UNION. Characters beyond these two belong in
// plugins, and a closed `"familiar" | "jarvis" | ...` union forced every new one
// to edit boltrig core — the id type, a total Record, a branch in the Stage, and
// the settings options. Four core files per character is a bleed, not an
// extension point. Registration inverts it: core states the contract and
// discovers what is installed; a character supplies its own renderer and names
// itself. Nothing in this directory names a character it does not ship.
//
// This file describes how a Stage renderer consumes presentation state. It does
// not participate in Chat dispatch or response generation.

import { createElement, useSyncExternalStore, type ReactNode } from "react";
import type {
  Character as SdkCharacter,
  CharacterRenderProps as SdkCharacterRenderProps,
  FamiliarGenotype,
  FamiliarPhenotypeResponse,
  NormalizedTurn,
} from "@wlilley93/boltrig-web-sdk";
import {
  characterRegistryRevision as sdkCharacterRegistryRevision,
  characterFor as sdkCharacterFor,
  isCharacterRegistered,
  listCharacters as sdkListCharacters,
  registerCharacter as sdkRegisterCharacter,
  subscribeCharacters as sdkSubscribeCharacters,
} from "@wlilley93/boltrig-web-sdk";
import type { CharacterId } from "../character";
import { DEFAULT_CHARACTER } from "../character";
import familiarBundle from "../bundles/familiar/character.json";
import jarvisBundle from "../bundles/jarvis/character.json";
import {
  characterFromBundle,
  type CharacterCanvasSource,
} from "./characterBundle";
import { FamiliarStage } from "./familiar/FamiliarStage";
import {
  familiarStateFromTurn,
  type FamiliarPresentationMode,
} from "./familiar/FamiliarState";
import { UNIFORMS as SHADER_UNIFORMS } from "./familiar/FamiliarWebGLRenderer";
import { UNIFORMS as JARVIS_UNIFORMS } from "./jarvis/JarvisRenderer";
import { JarvisStage } from "./jarvis/JarvisStage";
import { jarvisStateFromTurn } from "./jarvis/JarvisState";

export type StageTurnInput = import("@wlilley93/boltrig-web-sdk").CharacterTurnInput;
export type StageRenderProps = SdkCharacterRenderProps<FamiliarPhenotypeResponse, FamiliarGenotype>;
export type Character = SdkCharacter<ReactNode, FamiliarPhenotypeResponse, FamiliarGenotype>;

/**
 * Adds one validated character. Duplicate ids and display names fail closed in
 * the shared registry rather than changing meaning with module import order.
 */
export function registerCharacter(character: Character): void {
  sdkRegisterCharacter(character);
}

export function characterRegistryRevision(): number {
  return sdkCharacterRegistryRevision();
}

export function subscribeCharacters(listener: () => void): () => void {
  return sdkSubscribeCharacters(listener);
}

function useCharacterRegistry(): void {
  useSyncExternalStore(
    subscribeCharacters,
    characterRegistryRevision,
    characterRegistryRevision,
  );
}

export function useCharacter(id: CharacterId): Character {
  useCharacterRegistry();
  return characterFor(id);
}

export function useCharacterOptions(): {
  options: string[];
  values: Record<string, CharacterId>;
} {
  useCharacterRegistry();
  const installed = listCharacters();
  return {
    options: installed.map(({ name }) => name),
    values: Object.fromEntries(installed.map(({ id, name }) => [name, id])),
  };
}

/** Reactive installed-character list for surfaces that need more than labels. */
export function useCharacters(): Character[] {
  useCharacterRegistry();
  return listCharacters();
}

/**
 * Resolves an id to something drawable. An unregistered id — an uninstalled
 * plugin, or a setting carried over from a build that shipped it — falls back
 * to the default rather than throwing, so a missing character costs the Stage
 * its body and nothing else.
 */
export function characterFor(id: CharacterId): Character {
  return sdkCharacterFor<ReactNode>(id, DEFAULT_CHARACTER) as Character | undefined
    ?? FAMILIAR;
}

/** Everything installed, for the settings surface to offer. */
export function listCharacters(): Character[] {
  return sdkListCharacters<ReactNode>() as Character[];
}

export function isRegistered(id: CharacterId): boolean {
  return isCharacterRegistered(id);
}

/**
 * The public shader source: one of the canvas's two sources, and the one that
 * ships. It draws any `type: shader` bundle, so it names no character — Familiar
 * and Jarvis are both shaders, and a third would need nothing added here.
 *
 * The companion source (the proprietary .frame.mp4 reader) is deliberately
 * absent from the public build. It registers exactly the way a character does,
 * from a private entrypoint, which is why `type: companion` is expressible in
 * the format and unimplemented here rather than being a second subsystem.
 */
const SHADER_SOURCE: CharacterCanvasSource = {
  id: "boltrig.canvas.shader",
  type: "shader",
  supplies: SHADER_UNIFORMS,
  // The Familiar's resting baseline wanders on its own; it is not wired to the
  // appraisal engine, and never was. Naming the model here is what lets a
  // bundle asking for one this canvas does not implement be refused out loud.
  emotionModels: ["autonomous-wander"],
  // createElement, never a direct call: these components use hooks, and calling
  // one as a plain function attaches its hooks to whoever called it. That
  // "works" until the character swaps and the hook order changes underneath the
  // caller.
  render: ({ input, mode, phenotype, genotype, label }) =>
    createElement(FamiliarStage, {
      genotype,
      label,
      mode,
      phenotype,
      state: familiarStateFromTurn(input),
    }),
};

/**
 * Familiar, built from her bundle rather than written out here. Every field the
 * registry reads — id, name, blurb, readsPhenotype, whether budgets are polled —
 * now comes from bundles/familiar/character.json, and her manifest OMITS the
 * phenotype field entirely rather than carrying an empty one.
 *
 * She ships, so the stock path registers her. That is the rule intact, not bent:
 * characterPlugins.ts, package.json and manifest.yaml stay untouched, and a
 * bundle that does not ship is added by a private entrypoint instead.
 */
const FAMILIAR: Character = characterFromBundle(familiarBundle, [SHADER_SOURCE]);

/**
 * The instrument's canvas source — a SECOND shader source, not a variant of the
 * one above.
 *
 * Both bodies are `type: shader`, but they are not interchangeable: the source
 * above supplies the Familiar's channels (uAudio, uBeat, uMouse, uGesture...)
 * and Jarvis needs an entirely different set (budgets, work, speech, readout).
 * Pointing his bundle at `boltrig.canvas.shader` would be REFUSED at
 * registration by assertUniforms, which is the format working, not fighting us.
 *
 * `uGene` is appended because the shader needs it while JarvisRenderer uploads
 * it once at mount rather than per frame — `supplies` describes what the source
 * can drive, not which loop drives it.
 */
const JARVIS_SOURCE: CharacterCanvasSource = {
  id: "boltrig.canvas.jarvis",
  type: "shader",
  supplies: [...JARVIS_UNIFORMS, "uGene"],
  render: ({ input, mode, phenotype, budgets, turn }) =>
    createElement(JarvisStage, {
      budgets: budgets as never,
      highResolution: mode === "voice",
      phenotype,
      state: jarvisStateFromTurn(input),
      suspended: mode === "minimised",
      turn,
    }),
};

/**
 * Jarvis, now built from his bundle for the same reason Familiar is: id, name,
 * blurb, whether he reads the phenotype and whether he polls budgets all come
 * from the manifest, so the settings surface changes with the JSON. His voice
 * travels with him there too — a fallback id, never a key.
 */
const JARVIS: Character = characterFromBundle(jarvisBundle, [JARVIS_SOURCE]);

registerCharacter(FAMILIAR);
registerCharacter(JARVIS);

// Published web and desktop builds contain exactly the two supported bodies
// above. Do not use a bundler directory glob here: Vite emits every matched companion
// as a production chunk even when the surrounding branch is DEV-only. A local
// developer can import a companion's register.ts explicitly in a dev harness
// and call registerCharacter, while the stock product never discovers or
// bundles a third body.
