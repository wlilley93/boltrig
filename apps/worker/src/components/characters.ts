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

import { createElement, type ReactNode } from "react";
import type {
  FamiliarGenotype,
  FamiliarPhenotypeResponse,
  NormalizedTurn,
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

/** The turn facts every character reads. None carries text, audio or identity. */
export interface StageTurnInput {
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

export interface StageRenderProps {
  input: StageTurnInput;
  mode: FamiliarPresentationMode;
  /**
   * Already gated by `readsPhenotype`: a character that does not read the
   * appraisal engine is handed null here, not asked to ignore a live one.
   */
  phenotype: FamiliarPhenotypeResponse | null;
  /** Budgets, polled only for characters that asked for them. */
  budgets: unknown;
  turn?: Pick<NormalizedTurn, "tools" | "subagents" | "steps"> | null;
  genotype?: FamiliarGenotype | null;
  label?: string;
}

export interface Character {
  id: CharacterId;
  name: string;
  /**
   * Does this character read the server phenotype (decision 0013)?
   *
   * False does not mean "lifeless" — the Familiar still wanders. It means the
   * appraisal engine is not this character's source of truth, so handing it a
   * phenotype would be attributing the machine's mood to a creature that does
   * not have access to it.
   */
  readsPhenotype: boolean;
  /** True to have the Stage poll budgets; a body nobody chose costs no request. */
  wantsBudgets?: boolean;
  blurb: string;
  render(props: StageRenderProps): ReactNode;
}

const REGISTRY = new Map<CharacterId, Character>();

/**
 * Adds a character. Later registration of the same id wins, so a plugin may
 * deliberately replace a stock body — but it must say so by reusing the id
 * rather than by editing anything here.
 */
export function registerCharacter(character: Character): void {
  REGISTRY.set(character.id, character);
}

/**
 * Resolves an id to something drawable. An unregistered id — an uninstalled
 * plugin, or a setting carried over from a build that shipped it — falls back
 * to the default rather than throwing, so a missing character costs the Stage
 * its body and nothing else.
 */
export function characterFor(id: CharacterId): Character {
  return REGISTRY.get(id)
    ?? REGISTRY.get(DEFAULT_CHARACTER)
    ?? FAMILIAR;
}

/** Everything installed, for the settings surface to offer. */
export function listCharacters(): Character[] {
  return [...REGISTRY.values()];
}

export function isRegistered(id: CharacterId): boolean {
  return REGISTRY.has(id);
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

// Everything else registers itself. Each additional character ships a
// `register.ts` beside its own components; this glob imports them without
// naming one, so a plugin is added by dropping a directory in rather than by
// editing boltrig. Registration is deliberately cheap and eager — it is
// metadata plus a render function — while the heavy renderer behind it stays
// lazy inside the character's own module.
const registrations = import.meta.glob("./*/register.ts", { eager: true });
void registrations;
