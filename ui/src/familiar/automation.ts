/**
 * A FAMILIAR FOR AN AUTOMATION.
 *
 * An automation is an agent that runs when nobody is watching, which changes which surface
 * matters: not the live view, the HISTORY. So the mood on an automation card is a statement
 * about its record, not about this instant, and the rule from `phenotype.ts` still binds -
 * every channel must be answerable with a fact.
 *
 * The facts available on a card are the ones already fetched for it: how many times it has
 * run, what fraction succeeded, and whether it has ever run at all. That is enough, and
 * nothing further is invented.
 *
 * WHY "NEVER RUN" IS NOT "IDLE". A workflow that has never executed and one that ran cleanly
 * an hour ago are different in the way that matters most - one is unproven. Idle would say
 * they are the same. `queued` is used instead, which reads as held and not yet working, and
 * that is exactly what an unrun automation is.
 */

import { phenotypeForRun, type Phenotype, type RunFacts } from "@/familiar/phenotype";

export interface AutomationFacts {
  /** null when the card has no run history at all */
  successRate: number | null;
  runCount: number;
  /** true while this automation is executing right now */
  firing?: boolean;
}

/**
 * The threshold below which an automation reads as failing.
 *
 * 70% rather than 100%: automations touch the outside world, and a job that retries a flaky
 * endpoint and succeeds on the second attempt is healthy, not broken. Painting anything short
 * of perfect in the failure colour would put most of a real fleet permanently in magenta, and
 * a warning that is always on is a warning nobody reads - the same failure `fleet-health`
 * already learned the hard way.
 */
export const AUTOMATION_HEALTHY_RATE = 70;

export function automationRunFacts(f: AutomationFacts): RunFacts {
  // Firing beats every historical judgement. What it is doing right now is more urgent than
  // how it has done on average, and it is the only signal in a list of twenty scheduled jobs
  // that separates "scheduled" from "happening".
  if (f.firing) return { status: "running" };
  if (f.successRate === null || f.runCount === 0) return { status: "queued" };
  if (f.successRate < AUTOMATION_HEALTHY_RATE) return { status: "failed" };
  return { status: "done" };
}

export function automationPhenotype(f: AutomationFacts): Phenotype {
  return phenotypeForRun(automationRunFacts(f));
}

/**
 * Automations have no `role` field, so their shape family comes from their intent tags.
 *
 * Same rule as agents: derived from meaning, and an unrecognised automation gets the generic
 * circle rather than a guess. The tags are matched with the SAME vocabulary `bandForRole` uses
 * for agents, deliberately - an automation that reviews things and an agent that reviews
 * things should look like relatives, because they are.
 */
export function automationRole(id: string, tags: string[] | undefined): string {
  const hay = [id, ...(tags ?? [])].join(" ").toLowerCase();
  // Ordered by SPECIFICITY, most specific first, because first-match-wins makes the order the
  // decision. "compliance" and "security" name one thing; "check" names almost anything, so it
  // must not get first refusal - `nightly-compliance-check` is a guardian that checks, not a
  // reviewer that happens to mention compliance. (It resolved to "reviewer" until a test said
  // otherwise, which is the entire argument for writing the test.)
  if (/guard|security|compliance|approv|gate|protect/.test(hay)) return "guardian";
  if (/review|verif|audit|check|validate/.test(hay)) return "reviewer";
  if (/research|explore|search|scout|gather|scrape/.test(hay)) return "researcher";
  if (/report|analy|measure|metric|summar|digest/.test(hay)) return "analyst";
  if (/build|deploy|publish|generate|create|sync|migrate/.test(hay)) return "builder";
  if (/orchestrat|schedul|dispatch|route|pipeline/.test(hay)) return "orchestrator";
  return "";
}
