// Turning rings into readings.
//
// A HUD dial that spins at a constant rate is decoration. These functions are
// what make two of the instrument's tracks legible instruments: an arc whose
// length is a real number a person can learn to read at a glance.
//
// THE RULE THIS FILE EXISTS TO ENFORCE: a gauge must never show a number it
// does not have. Absent, unlimited and not-yet-computed all read as "no
// reading" (a ghost track), never as zero — a gauge sitting at empty says
// "you have spent nothing", which is a different and possibly expensive claim.
// The console's budget table already does this (it prints "—" when
// usage_state is not "current"); the dial must agree with the table.

import type { BudgetItem } from "@wlilley93/boltrig-web-sdk";

export interface GaugeReading {
  /** 0..1+ fraction of the ceiling consumed. Meaningless unless `known`. */
  fill: number;
  /** False when there is no ceiling, no current usage, or no budget at all. */
  known: boolean;
  /** True when crossing the ceiling actually stops work. */
  hard: boolean;
  /** Raw spend, in micros for cost and in tokens for tokens. */
  spent: number;
  /** Raw ceiling, same units as `spent`. */
  limit: number;
  /** Which window the binding ceiling belongs to — a run cap and a monthly cap
   *  at the same percentage mean very different things. */
  window: BudgetItem["window"] | null;
}

export const NO_READING: GaugeReading = {
  fill: 0, known: false, hard: false, spent: 0, limit: 0, window: null,
};

/**
 * Of all the ceilings in scope, the instrument shows the one you are closest to
 * breaching — not the total, and not the first. A dial has one arc and several
 * budgets may apply at once (tenant, department, workflow x run, daily,
 * monthly); the binding one is the only one whose position is worth knowing.
 *
 * `usage_state: "run_context_required"` means the spend figure is not
 * computable outside a run, so those rows cannot be ranked or drawn.
 */
export function bindingBudget(
  budgets: readonly BudgetItem[] | null | undefined,
  metric: "cost" | "tokens",
): GaugeReading {
  if (!budgets?.length) return NO_READING;

  let best: GaugeReading = NO_READING;
  for (const item of budgets) {
    if (item.usage_state !== "current") continue;
    const limit = metric === "cost" ? item.cost_limit_micros : item.token_limit;
    if (limit == null || limit <= 0) continue; // no ceiling is not a full gauge
    const spent = metric === "cost" ? item.spent_micros : item.spent_tokens;
    if (typeof spent !== "number" || !Number.isFinite(spent)) continue;

    const fill = Math.max(0, spent / limit);
    if (!best.known || fill > best.fill) {
      best = {
        fill, known: true, hard: item.hard_stop,
        spent, limit, window: item.window,
      };
    }
  }
  return best;
}

export interface JarvisTelemetry {
  /** Money against the binding money ceiling. */
  budget: GaugeReading;
  /** Tokens against the binding token ceiling. */
  tokens: GaugeReading;
}

export const NO_TELEMETRY: JarvisTelemetry = {
  budget: NO_READING,
  tokens: NO_READING,
};

export function telemetryFromBudgets(
  budgets: readonly BudgetItem[] | null | undefined,
): JarvisTelemetry {
  return {
    budget: bindingBudget(budgets, "cost"),
    tokens: bindingBudget(budgets, "tokens"),
  };
}
