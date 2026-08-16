import { Suspense, useEffect, useState } from "react";
import type {
  BudgetItem,
  FamiliarGenotype,
  FamiliarPhenotypeResponse,
  NormalizedTurn,
  SensingDecision,
} from "@wlilley93/boltrig-web-sdk";
import { client } from "../client";
import {
  CHARACTER_CHANGE_EVENT,
  loadCharacter,
  type CharacterId,
} from "../character";
import { skinFor, type StageTurnInput, useCharacter, useSkin } from "./characters";
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

/**
 * The honest-refusal path, from the character's side.
 *
 * A character DECLARES that it would like the camera; it never carries one. The
 * Stage asks the kernel on its behalf and hands back whatever comes, which for a
 * user who has the camera off is a refusal naming the reason. Three rules hold
 * here and each one is load-bearing:
 *
 *  - NO SUBSTITUTION. A failure to reach the kernel yields a refusal, not a
 *    silent grant and not a cached previous answer. A character that cannot be
 *    told must behave as though it cannot see.
 *  - CHECKED AT USE, NEVER CACHED ACROSS CONSENT. Re-asked on the same cadence
 *    the capture loop runs, so a toggle moved in Settings bites within about
 *    thirty seconds rather than at the next restart.
 *  - NOTHING DECLARED, NOTHING ASKED. A character that wants no capability costs
 *    no request, exactly as budgets already work.
 *
 * And the refusal must name the reason it ACTUALLY has. Failing safe is not the
 * same as failing honestly: this used to answer `camera_disabled` when the
 * kernel could not be asked, which is safe but untrue, and anything reading the
 * machine-readable code — a body that draws "you turned me off" differently from
 * "I cannot reach home", a log, a future policy — was told a user decision that
 * nobody made.
 */
function useSensing(capabilities: readonly string[] | undefined): Record<string, SensingDecision> {
  const key = (capabilities ?? []).join(",");
  const [decisions, setDecisions] = useState<Record<string, SensingDecision>>({});
  useEffect(() => {
    const wanted = key ? key.split(",") : [];
    if (wanted.length === 0) {
      setDecisions({});
      return;
    }
    let cancelled = false;
    /**
     * The kernel could not be asked — the request failed, or this client is too
     * old to know the route. Both are the same truth: the question was never
     * put, so there is no consent to act on.
     *
     * It is its OWN code, not `camera_disabled`. Being unable to ask is not a
     * setting the user moved, and no remedy in Settings changes it; it clears
     * when the kernel answers again, which the 30 s re-ask below will notice
     * within one capture interval. It still fails toward refusal, because an
     * unreachable kernel is not consent.
     */
    const unreachable = (capability: string): SensingDecision => ({
      status: "refused",
      capability,
      reason: "kernel_unreachable",
      detail: "Boltrig could not be asked, so consent is unknown and nothing is being seen.",
      remedy: "retry:automatic",
    });
    const ask = () => {
      void Promise.all(wanted.map((capability) => (
        typeof client.sensingCapability === "function"
          ? client.sensingCapability(capability).catch(() => unreachable(capability))
          : Promise.resolve(unreachable(capability))
      ))).then((results) => {
        if (cancelled) return;
        setDecisions(Object.fromEntries(results.map((row, index) => [wanted[index]!, row])));
      });
    };
    ask();
    const timer = window.setInterval(ask, 30_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [key]);
  return decisions;
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
  const storedSkin = useSkin();
  const body = useFamiliarBody();
  const character = useCharacter(body);
  const skin = skinFor(character, storedSkin);
  const budgets = useBudgets(character.wantsBudgets === true);
  const sensing = useSensing(character.wantsSensing);

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
        sensing,
        skin,
        turn,
      })}
    </Suspense>
  );
}
