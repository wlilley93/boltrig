import { useEffect, useState } from "react";
import type {
  BudgetItem,
  FamiliarGenotype,
  FamiliarPhenotypeResponse,
  NormalizedTurn,
} from "@wlilley93/boltrig-web-sdk";
import { client } from "../client";
import {
  CHARACTER_CHANGE_EVENT,
  loadCharacter,
  type CharacterId,
} from "../character";
import { characterFor } from "./characters";
import { FamiliarStage } from "./familiar/FamiliarStage";
import {
  familiarStateFromTurn,
  type FamiliarPresentationMode,
} from "./familiar/FamiliarState";
import { JarvisStage } from "./jarvis/JarvisStage";
import { jarvisStateFromTurn } from "./jarvis/JarvisState";

// The one place that decides WHICH body is on the Stage.
//
// The Familiar and Jarvis are two answers to the same question and are never
// shown at once, so this is a switch rather than a composition. Both derive
// their state from the same turn facts — the choice changes how the agent is
// depicted, never what is true about it, and neither body can influence
// dispatch (ADR 0025).

/** The turn facts both bodies read. Neither carries text, audio or identity. */
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

/** Reactive read of the chosen character; applyCharacter announces every change. */
export function useFamiliarBody(): CharacterId {
  const [body, setBody] = useState<CharacterId>(() => loadCharacter());
  useEffect(() => {
    const onChange = (event: Event) => {
      const next = (event as CustomEvent<CharacterId>).detail;
      if (next) setBody(next);
    };
    document.addEventListener(CHARACTER_CHANGE_EVENT, onChange);
    return () => document.removeEventListener(CHARACTER_CHANGE_EVENT, onChange);
  }, []);
  return body;
}

/**
 * Budgets for the Jarvis gauges. Only polled when the instrument is actually
 * showing — the Familiar has no use for them, and a body nobody chose should
 * not cost a request. Any failure leaves the tracks as ghosts, which is the
 * honest rendering of "no reading".
 */
function useBudgets(enabled: boolean): BudgetItem[] | null {
  const [budgets, setBudgets] = useState<BudgetItem[] | null>(null);
  useEffect(() => {
    if (!enabled) {
      setBudgets(null);
      return;
    }
    let cancelled = false;
    const pull = () => {
      if (typeof client.budgets !== "function") return;
      void client.budgets()
        .then((result) => { if (!cancelled) setBudgets(result.budgets); })
        .catch(() => { if (!cancelled) setBudgets(null); });
    };
    pull();
    // Ceilings move slowly; this is a gauge, not a stream.
    const timer = window.setInterval(pull, 30_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [enabled]);
  return budgets;
}

export function StageBody({
  mode,
  input,
  phenotype,
  turn,
  genotype,
  label,
}: {
  mode: FamiliarPresentationMode;
  input: StageTurnInput;
  phenotype?: FamiliarPhenotypeResponse | null;
  /** The streaming turn — its tools, subagents and steps light Jarvis's board. */
  turn?: Pick<NormalizedTurn, "tools" | "subagents" | "steps"> | null;
  genotype?: FamiliarGenotype | null;
  label?: string;
}) {
  const body = useFamiliarBody();
  const character = characterFor(body);
  const isJarvis = body === "jarvis";
  const budgets = useBudgets(isJarvis);

  // Emotion is per-character, not per-installation. A character that does not
  // read the phenotype is handed null rather than a live one — the Familiar
  // then falls back to wandering its own mood, which is its inner life and
  // always was. Passing it the machine's appraisal would attribute a state to a
  // creature that has no access to it.
  const inner = character.readsPhenotype ? phenotype : null;

  if (isJarvis) {
    return (
      <JarvisStage
        budgets={budgets}
        phenotype={inner}
        state={jarvisStateFromTurn(input)}
        suspended={mode === "minimised"}
        turn={turn}
      />
    );
  }

  return (
    <FamiliarStage
      genotype={genotype}
      label={label}
      mode={mode}
      phenotype={inner}
      state={familiarStateFromTurn(input)}
    />
  );
}
