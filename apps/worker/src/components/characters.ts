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
import {
  CHARACTER_CHANGE_EVENT,
  DEFAULT_CHARACTER,
  DEFAULT_SKIN,
  loadSkin,
} from "../character";
import colossusBundle from "../bundles/colossus/character.json";
import familiarBundle from "../bundles/familiar/character.json";
import ultronBundle from "../bundles/ultron/character.json";
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
import { UNIFORMS as COLOSSUS_UNIFORMS } from "./colossus/ColossusRenderer";
import { ColossusStage } from "./colossus/ColossusStage";
import { colossusStateFromTurn } from "./colossus/ColossusState";
import { UltronStage } from "./ultron/UltronStage";
import { ultronStateFromTurn } from "./ultron/UltronState";

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

/**
 * The chosen skin, kept current with the change event.
 *
 * Returns the raw stored value; RESOLVING it against what the character
 * actually offers is `skinFor`'s job, below, because only the character knows
 * which looks exist.
 */
export function useSkin(): string {
  return useSyncExternalStore(
    (listener) => {
      if (typeof document === "undefined") return () => undefined;
      document.addEventListener(CHARACTER_CHANGE_EVENT, listener);
      return () => document.removeEventListener(CHARACTER_CHANGE_EVENT, listener);
    },
    loadSkin,
    () => DEFAULT_SKIN,
  );
}

/**
 * The skin this character will actually draw.
 *
 * A stored skin naming a look the character does not offer -- an uninstalled
 * variant, or a build that never shipped it -- resolves to its FIRST skin
 * rather than being drawn as nothing. Same rule as `characterFor`: a missing
 * variant costs the Stage a look and nothing else.
 */
export function skinFor(character: Character, stored: string): string {
  const offered = character.skins;
  if (!offered || offered.length === 0) return DEFAULT_SKIN;
  return offered.some((skin) => skin.id === stored) ? stored : offered[0].id;
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
  /**
   * Two bodies, one character. "default" is the instrument dial; "ultron" is the
   * neural field of components/jarvis/v2 -- the Age of Ultron hologram, which is
   * Jarvis's own look in that film and NOT Ultron's. Animal Logic coded JARVIS
   * orange and angular and ULTRON blue and organic, so an actual Ultron would be
   * a different character with a different body, not a third skin here.
   *
   * Declared so characterFromBundle can refuse a manifest naming a third.
   */
  skins: ["default", "ultron"],
  render: ({ input, mode, phenotype, budgets, turn, skin }) =>
    createElement(JarvisStage, {
      budgets: budgets as never,
      highResolution: mode === "voice",
      phenotype,
      skin,
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

/**
 * Ultron's canvas source -- a THIRD one, and for the same reason the second
 * exists: he needs a different set of channels again. He drives aggression,
 * crack range and facet separation, and drives no budgets, no work board and no
 * readout, because he has nowhere to put a number.
 *
 * He is NOT a skin of Jarvis. Animal Logic built both consciousnesses for the
 * Birth of Ultron sequence and coded them as opposites -- JARVIS orange and
 * angular and circuit-like, ULTRON blue and organic -- so the gold hologram is
 * Jarvis's own look in that film and this is a different being. Pointing his
 * manifest at Jarvis's source would be refused by assertUniforms, which is the
 * format working rather than fighting us.
 */
/**
 * Every uniform Ultron's four passes set. Kept here beside the source because
 * `supplies` describes what the SOURCE can drive; the shaders that consume them
 * are split across components/ultron and components/canvas, so no single module
 * over there owns the list.
 */
// Exported ONLY so tests/ultronBundle.test.ts can check this exact array
// against the shaders. It used to derive its own copy of the list from the
// shader sources and compare that to the manifest, which meant the one list
// production actually passes to `supplies` was never in the comparison -- adding
// `uLimb` to the shaders and the manifest left this array behind and the suite
// stayed green while the bundle refused to build at runtime.
export const ULTRON_UNIFORMS: readonly string[] = [
  "uState", "uTime", "uDt", "uEnergy", "uRadius", "uWaveT", "uWaveAmp",
  "uAspect", "uStreak", "uGrid", "uSegments", "uStride", "uSize",
  "uLinkRange", "uAggression", "uBands", "uVoice", "uSwell", "uPetal", "uLimb",
  "uSwirl",
  "uWarm", "uHot", "uFringe", "uInner", "uFringeScale", "uFringeGain", "uGain",
  "uSrc", "uDir", "uThreshold",
  "uScene", "uBloom", "uBloomGain", "uCore", "uStarburst",
];

const ULTRON_SOURCE: CharacterCanvasSource = {
  id: "boltrig.canvas.ultron",
  type: "shader",
  supplies: ULTRON_UNIFORMS,
  render: ({ input, mode, phenotype }) =>
    createElement(UltronStage, {
      highResolution: mode === "voice",
      phenotype,
      state: ultronStateFromTurn(input),
      suspended: mode === "minimised",
    }),
};

/**
 * Ultron, from his bundle like the other two. He ships, so the stock path
 * registers him: characterPlugins.ts, package.json and manifest.yaml stay
 * untouched, which is the rule intact rather than bent.
 */
const ULTRON: Character = characterFromBundle(ultronBundle, [ULTRON_SOURCE]);

/**
 * Colossus's canvas source -- a FOURTH, and the first that is not a sphere.
 *
 * The other three sources differ in which channels they drive; this one differs
 * in what it draws at all. There is no particle simulation behind it and no
 * float extension: a lamp's brightness is a closed-form function of position
 * and time, so his body is one fullscreen pass, a glyph atlas and a bloom.
 *
 * He drives no phenotype, no budgets, no work board and no readout of the
 * machine's state. What he drives is TEXT -- a ticker buffer of glyph ids and a
 * scroll offset -- which no other source here can supply, and pointing his
 * manifest at one of theirs would be refused by assertUniforms.
 */
const COLOSSUS_SOURCE: CharacterCanvasSource = {
  id: "boltrig.canvas.colossus",
  type: "shader",
  supplies: COLOSSUS_UNIFORMS,
  render: ({ input, mode }) =>
    createElement(ColossusStage, {
      highResolution: mode === "voice",
      state: colossusStateFromTurn(input),
      suspended: mode === "minimised",
    }),
};

/**
 * Colossus, from his bundle like the other three. His manifest OMITS the
 * phenotype block, which is the same encoding Familiar uses and the opposite
 * reason: she has an inner life the appraisal engine cannot see, and he has one
 * register. He ships, so the stock path registers him.
 */
const COLOSSUS: Character = characterFromBundle(colossusBundle, [COLOSSUS_SOURCE]);

registerCharacter(FAMILIAR);
registerCharacter(JARVIS);
registerCharacter(ULTRON);
registerCharacter(COLOSSUS);

// Published web and desktop builds contain exactly the four supported bodies
// above. Do not use a bundler directory glob here: Vite emits every matched companion
// as a production chunk even when the surrounding branch is DEV-only. A local
// developer can import a companion's register.ts explicitly in a dev harness
// and call registerCharacter, while the stock product never discovers or
// bundles a body it does not ship.
