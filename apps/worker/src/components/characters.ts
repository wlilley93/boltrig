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
import { FamiliarStage } from "./familiar/FamiliarStage";
import {
  familiarStateFromTurn,
  type FamiliarPresentationMode,
} from "./familiar/FamiliarState";
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

const FAMILIAR: Character = {
  id: "familiar",
  name: "Familiar",
  readsPhenotype: false,
  blurb: "A living body with a private inner life of its own.",
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

const JARVIS: Character = {
  id: "jarvis",
  name: "Jarvis",
  readsPhenotype: true,
  wantsBudgets: true,
  blurb: "An instrument that displays the machine's measured state.",
  render: ({ input, mode, phenotype, budgets, turn }) =>
    createElement(JarvisStage, {
      budgets: budgets as never,
      phenotype,
      state: jarvisStateFromTurn(input),
      suspended: mode === "minimised",
      turn,
    }),
};

registerCharacter(FAMILIAR);
registerCharacter(JARVIS);

// Published web and desktop builds contain exactly the two supported bodies
// above. Do not use a bundler directory glob here: Vite emits every matched companion
// as a production chunk even when the surrounding branch is DEV-only. A local
// developer can import a companion's register.ts explicitly in a dev harness
// and call registerCharacter, while the stock product never discovers or
// bundles a third body.
