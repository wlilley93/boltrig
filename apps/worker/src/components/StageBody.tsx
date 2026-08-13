import { Suspense, useEffect, useState } from "react";
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
import {
  useCharacter,
  type StageTurnInput,
} from "./characters";
import type { FamiliarPresentationMode } from "./familiar/FamiliarState";

// The one place that decides WHICH body is on the Stage — and it does so
// without naming any of them.
//
// Characters are a registry (components/characters.ts). This file resolves the
// chosen id, gates the phenotype on whether that character can honestly read it,
// polls budgets only if it asked for them, and hands the result to the
// character's own renderer. Adding a character touches nothing here.

export type { StageTurnInput };

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
 * Budgets, for characters that display them. Only polled when such a character
 * is actually showing — a body nobody chose should not cost a request. Any
 * failure leaves the reading absent, which is the honest rendering of "no
 * reading" rather than a gauge at zero.
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
  /** The streaming turn — its tools, subagents and steps light an instrument's board. */
  turn?: Pick<NormalizedTurn, "tools" | "subagents" | "steps"> | null;
  genotype?: FamiliarGenotype | null;
  label?: string;
}) {
  const body = useFamiliarBody();
  const character = useCharacter(body);
  const budgets = useBudgets(character.wantsBudgets === true);

  // Emotion is per-character, not per-installation. A character that does not
  // read the phenotype is handed null rather than a live one — the Familiar
  // then falls back to wandering its own mood, which is its inner life and
  // always was. Passing it the machine's appraisal would attribute a state to a
  // creature that has no access to it.
  const inner = character.readsPhenotype ? (phenotype ?? null) : null;

  // Suspense because a character's renderer may be lazy: a plugin registers
  // cheaply at load and pulls its heavy body in only once it is chosen.
  return (
    <Suspense fallback={null}>
      {character.render({
        budgets,
        genotype,
        input,
        label,
        mode,
        phenotype: inner,
        turn,
      })}
    </Suspense>
  );
}
