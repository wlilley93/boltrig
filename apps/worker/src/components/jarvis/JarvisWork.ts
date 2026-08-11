// Making the circuit board real.
//
// The board's comment in jarvis.frag has always claimed it is "only visible
// when current is flowing through it". Until now that was a lie: the traces
// were a hash function and `thinking` lit all of them uniformly, so a turn
// doing one cheap lookup looked exactly like a turn fanning out to six
// subagents.
//
// NormalizedTurn already carries the truth, and it is the DAG: `steps` are the
// workflow's own nodes with live statuses, `tools` are calls in flight, and
// `subagents` are parallel workers. Nothing here needs a new endpoint — the
// stream the transcript already renders is the stream the board should run on.
//
// Same honesty rule as the gauges: no work means a dark board, and a dark board
// means no work. The load is never padded to look busy.

import type { NormalizedTurn } from "@wlilley93/boltrig-web-sdk";

export interface JarvisWork {
  /** 0..1 how much of the board is energised. */
  load: number;
  /** 0..1 how much of the running work has failed or degraded. */
  fail: number;
  /** Raw count of units currently in flight; exposed for tests and debugging. */
  active: number;
  /** Raw count of units that ended badly this turn. */
  failed: number;
}

export const NO_WORK: JarvisWork = { load: 0, fail: 0, active: 0, failed: 0 };

/**
 * Concurrency at which the board is fully lit. Six is not arbitrary: past about
 * six simultaneous units a person stops counting and starts reading "a lot", so
 * lighting further traces would add no information.
 */
export const SATURATION = 6;

/**
 * A tool entry is in flight while its status is "pending" — the normalizer sets
 * the result status in place when the paired result arrives.
 */
const isToolRunning = (status: string): boolean => status === "pending";

/** Anything that is not a clean "ok" once settled counts against the turn. */
const isBadStatus = (status: string): boolean =>
  status === "error" || status === "failed" || status === "degraded";

export function workFromTurn(
  turn: Pick<NormalizedTurn, "tools" | "subagents" | "steps"> | null | undefined,
): JarvisWork {
  if (!turn) return NO_WORK;

  let active = 0;
  let failed = 0;

  for (const tool of turn.tools ?? []) {
    if (isToolRunning(tool.status)) active += 1;
    else if (isBadStatus(tool.status)) failed += 1;
  }

  for (const sub of turn.subagents ?? []) {
    // `undefined` is honestly "still running": an un-upgraded kernel emits no
    // settle frame, and guessing "finished" there would darken a board that is
    // in fact still working.
    if (sub.status === undefined || sub.status === "running") active += 1;
    else if (isBadStatus(sub.status)) failed += 1;
  }

  for (const step of turn.steps ?? []) {
    if (step.status === "running") active += 1;
    else if (isBadStatus(step.status)) failed += 1;
  }

  const load = Math.min(1, active / SATURATION);
  // Failures are measured against everything that happened, not against the
  // live count — otherwise a turn whose every unit failed would report zero,
  // because nothing is left running to divide by.
  const total = active + failed;
  const fail = total > 0 ? failed / total : 0;

  return { load, fail, active, failed };
}
