// The Familiar island's state contract: what the phone tells the page.
//
// One bounded JSON object, v1. The Stage's own input contract (FamiliarState.ts)
// already bounds the mode and the voice numbers, and it is reused here verbatim
// through clampStageState rather than re-bounded: two copies of a clamp are one
// clamp and a disagreement. What this file adds is the island's own concerns --
// which presentation the body is in, whether the OS asked for reduced motion,
// the pixel-ratio ceiling the phone is prepared to pay for -- and the rule that
// a message need only carry what changed: missing fields keep their previous
// values, a wrong TYPE keeps the previous value too, and an unknown version is
// ignored whole rather than half-applied.
import type { FamiliarGenotype } from "@wlilley93/boltrig-web-sdk";
import {
  clampStageState,
  type FamiliarMode,
  type FamiliarStageState,
} from "../components/familiar/FamiliarState";

export type IslandPresentation = "hero" | "conversation" | "minimised";
export type IslandAppearance = "dark" | "light";

export interface IslandState {
  v: 1;
  mode: FamiliarMode;
  /** 0..1 level of the voice that is live. */
  level: number;
  /** Eight 0..1 band energies of the outgoing voice, or none. */
  bands: number[] | null;
  /** 0..1 onset of the outgoing voice. */
  onset: number;
  presentation: IslandPresentation;
  /** The OS preference, read by the phone; the page never asks the media query. */
  reducedMotion: boolean;
  appearance: IslandAppearance;
  /** Ceiling on the device pixel ratio the canvas renders at, 1..2. */
  dprCap: number;
  /** Live emotion scalars from the server projection, or none (the inner life wanders). */
  phenotype: Record<string, number> | null;
  /** The authoritative visual identity, or none (the neutral body). */
  genotype: FamiliarGenotype | null;
}

export const DEFAULT_ISLAND_STATE: IslandState = {
  v: 1,
  mode: "standby",
  level: 0,
  bands: null,
  onset: 0,
  presentation: "hero",
  reducedMotion: false,
  appearance: "dark",
  dprCap: 2,
  phenotype: null,
  genotype: null,
};

/** What the host has to DO about a state change, decided here so the host
 *  only acts and never compares. */
export interface IslandEffects {
  /** Reduced motion and the pixel-ratio cap are read once, when the renderer
   *  is built, so a change to either means a new renderer. */
  remount: boolean;
  presentationChanged: boolean;
  genotypeChanged: boolean;
  phenotypeChanged: boolean;
}

export interface IslandApply {
  state: IslandState;
  effects: IslandEffects;
  /** Set when the message was ignored or could not be read as v1; the host
   *  reports each distinct warning once. */
  warning?: string;
}

type Incoming = Record<string, unknown>;

const PRESENTATIONS: readonly IslandPresentation[] = ["hero", "conversation", "minimised"];
const APPEARANCES: readonly IslandAppearance[] = ["dark", "light"];
const NO_EFFECTS: IslandEffects = {
  remount: false, presentationChanged: false, genotypeChanged: false, phenotypeChanged: false,
};

function isRecord(value: unknown): value is Incoming {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function pick<T>(value: unknown, allowed: readonly T[], prev: T): T {
  return allowed.includes(value as T) ? (value as T) : prev;
}

function readDprCap(value: unknown, prev: number): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return prev;
  return Math.min(2, Math.max(1, value));
}

/** The stage fields through the Stage's own clamp; absent ones keep their
 *  previous values, `bands: null` is an explicit clear. */
function readStage(prev: IslandState, incoming: Incoming): FamiliarStageState {
  return clampStageState({
    mode: (incoming.mode ?? prev.mode) as FamiliarMode,
    level: (incoming.level ?? prev.level) as number,
    bands: (incoming.bands === undefined ? prev.bands : incoming.bands) as number[] | null,
    onset: (incoming.onset ?? prev.onset) as number,
  });
}

/** Finite numbers only, keys sorted so two equal phenotypes serialise equal. */
function readPhenotype(value: unknown, prev: IslandState["phenotype"]): IslandState["phenotype"] {
  if (value === null) return null;
  if (!isRecord(value)) return prev;
  const scalars: Record<string, number> = {};
  for (const key of Object.keys(value).sort()) {
    const raw = value[key];
    if (typeof raw === "number" && Number.isFinite(raw)) scalars[key] = raw;
  }
  return scalars;
}

const stringList = (value: unknown): string[] | undefined =>
  Array.isArray(value) && value.every((item) => typeof item === "string")
    ? (value as string[])
    : undefined;

/** Shallowly typed: an unknown body is the renderer's to handle (it draws the
 *  neutral body), a wrong type is dropped here before it can reach a shader. */
function readGenotype(value: unknown, prev: IslandState["genotype"]): IslandState["genotype"] {
  if (value === null) return null;
  if (!isRecord(value)) return prev;
  const genotype: FamiliarGenotype = {};
  if (value.source === "agent_capability.name.v1") genotype.source = value.source;
  if (typeof value.seed === "number" && Number.isFinite(value.seed)) genotype.seed = value.seed;
  if (typeof value.body === "string") genotype.body = value.body;
  const palette = stringList(value.palette);
  if (palette) genotype.palette = palette;
  const markings = stringList(value.markings);
  if (markings) genotype.markings = markings;
  const accessories = stringList(value.accessories);
  if (accessories) genotype.accessories = accessories;
  return genotype;
}

const same = (a: unknown, b: unknown): boolean => JSON.stringify(a) === JSON.stringify(b);

function effectsOf(prev: IslandState, next: IslandState): IslandEffects {
  return {
    remount: next.reducedMotion !== prev.reducedMotion || next.dprCap !== prev.dprCap,
    presentationChanged: next.presentation !== prev.presentation,
    genotypeChanged: !same(prev.genotype, next.genotype),
    phenotypeChanged: !same(prev.phenotype, next.phenotype),
  };
}

/** Merge one message into the state. Never throws: a message that cannot be
 *  read leaves the state as it was and says why. */
export function applyState(prev: IslandState, incoming: unknown): IslandApply {
  if (!isRecord(incoming)) {
    return { state: prev, effects: NO_EFFECTS, warning: "island state must be a JSON object" };
  }
  if (incoming.v !== undefined && incoming.v !== 1) {
    return {
      state: prev,
      effects: NO_EFFECTS,
      warning: `island state v${String(incoming.v)} is not v1; ignored`,
    };
  }
  const stage = readStage(prev, incoming);
  const state: IslandState = {
    v: 1,
    mode: stage.mode,
    level: stage.level,
    bands: stage.bands ?? null,
    onset: stage.onset ?? 0,
    presentation: pick(incoming.presentation, PRESENTATIONS, prev.presentation),
    reducedMotion: typeof incoming.reducedMotion === "boolean"
      ? incoming.reducedMotion
      : prev.reducedMotion,
    appearance: pick(incoming.appearance, APPEARANCES, prev.appearance),
    dprCap: readDprCap(incoming.dprCap, prev.dprCap),
    phenotype: incoming.phenotype === undefined
      ? prev.phenotype
      : readPhenotype(incoming.phenotype, prev.phenotype),
    genotype: incoming.genotype === undefined
      ? prev.genotype
      : readGenotype(incoming.genotype, prev.genotype),
  };
  return { state, effects: effectsOf(prev, state) };
}

/** The JSON the phone hands over, as an object for applyState, or the reason
 *  it could not be one. A string return IS the error: the phone's bridge
 *  passes JSON text, and text that is not a v1 object must never reach apply. */
export function parseIslandState(json: string): Incoming | string {
  let value: unknown;
  try {
    value = JSON.parse(json);
  } catch (error) {
    return `island state is not JSON: ${error instanceof Error ? error.message : String(error)}`;
  }
  if (!isRecord(value)) return "island state must be a JSON object";
  return value;
}
