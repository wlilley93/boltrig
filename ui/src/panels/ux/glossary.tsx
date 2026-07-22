import type { ReactNode } from "react";

import type { Term } from "./types";

// --- Glossary: one home for the plain-language meaning of every status /
// run-state / governance term surfaced across the panels. Keep copy calm and
// glanceable; the badges below read their label + tooltip from here. ---------

export const WORK_STATUS: Record<string, Term> = {
  pending: { label: "Pending", tip: "Queued. Not started yet.", cls: "badge--run-pending" },
  in_flight: { label: "In flight", tip: "Running right now.", cls: "badge--run-running" },
  blocked: { label: "Blocked", tip: "Stuck waiting on a dependency or a system.", cls: "badge--degraded" },
  awaiting_human: {
    label: "Awaiting human",
    tip: "Paused - needs a person to approve or answer. See Approvals.",
    cls: "badge--conseq-high",
  },
  done: { label: "Done", tip: "Finished successfully.", cls: "badge--ok" },
  failed: { label: "Failed", tip: "Stopped with an error.", cls: "badge--down" },
};

export const AUDIT_STATUS: Record<string, Term> = {
  ok: { label: "OK", tip: "Succeeded.", cls: "badge--ok" },
  denied: { label: "Denied", tip: "Blocked by a permission or policy.", cls: "badge--down" },
  degraded: { label: "Degraded", tip: "Worked, but a system was unhealthy.", cls: "badge--degraded" },
  error: { label: "Error", tip: "Failed.", cls: "badge--down" },
  pending_human: { label: "Paused", tip: "Paused for an approval.", cls: "badge--run-paused" },
};

export const MEMORY_INGEST_STATUS: Record<string, Term> = {
  pending: { label: "Pending", tip: "Queued for screening.", cls: "badge--run-pending" },
  screening: { label: "Screening", tip: "Checking source content before storage.", cls: "badge--run-running" },
  cognifying: { label: "Loading", tip: "Turning accepted source items into scoped facts.", cls: "badge--run-running" },
  done: { label: "Done", tip: "Screened facts were stored.", cls: "badge--ok" },
  failed: { label: "Failed", tip: "The ingestion stopped with an error.", cls: "badge--down" },
  rejected: { label: "Rejected", tip: "No source item passed screening.", cls: "badge--down" },
};

export const HITL_TYPE: Record<string, Term> = {
  approval: { label: "Approval", tip: "Needs your sign-off before it runs.", cls: "badge--type-approval" },
  clarification: { label: "Question", tip: "The system has a question for you.", cls: "badge--type-clarification" },
  escalation: { label: "Escalated", tip: "Raised to you because it is above someone else's authority.", cls: "badge--type-escalation" },
  question: { label: "Question", tip: "A run owned by you is waiting for an answer.", cls: "badge--type-clarification" },
};

export const HITL_URGENCY: Record<string, Term> = {
  blocking: { label: "Blocks the run", tip: "The run is paused until you answer.", cls: "badge--conseq-high" },
  async: { label: "Can wait", tip: "Answer when you get to it; the run is not blocked.", cls: "badge" },
};

// The live state of a single tool call in a transcript callout: "pending" while
// the call is in flight (before its paired result arrives), then the result
// status. A denial / error reason string that is not one of these falls back to
// the raw token via StatusBadge.
export const TOOL_STATUS: Record<string, Term> = {
  pending: { label: "Running", tip: "The tool call is in flight - awaiting its result.", cls: "badge--tool-running" },
  pending_human: { label: "Needs you", tip: "The tool call is paused for human approval.", cls: "badge--run-paused" },
  paused: { label: "Needs you", tip: "The tool call is paused for human approval.", cls: "badge--run-paused" },
  ok: { label: "OK", tip: "The tool call succeeded.", cls: "badge--tool-ok" },
  degraded: { label: "Degraded", tip: "Worked, but a system was unhealthy.", cls: "badge--degraded" },
  error: { label: "Error", tip: "The tool call failed.", cls: "badge--tool-error" },
};

export const CONSEQUENCE: Record<string, Term> = {
  high: { label: "High consequence", tip: "High-impact or hard to undo - requires human approval.", cls: "badge--conseq-high" },
  low: { label: "Low consequence", tip: "Routine - runs without sign-off.", cls: "badge--conseq-low" },
};

// A badge that renders a known term's friendly label + colour + a tooltip
// carrying the plain-language meaning. Unknown values fall back to the raw token.
export function StatusBadge({
  value,
  glossary,
  fallbackLabel,
  compact,
}: {
  value: string | undefined | null;
  glossary: Record<string, Term>;
  fallbackLabel?: string;
  compact?: boolean;
}) {
  const key = (value ?? "").toString();
  const term = glossary[key];
  const label = term ? term.label : (fallbackLabel ?? key ?? "-");
  const display = compact ? label.toLowerCase() : label;
  const baseCls = compact ? "badge badge--compact" : "badge";
  if (!term) {
    return <span className={baseCls} title={key}>{display}</span>;
  }
  return (
    <span className={`${baseCls} ${term.cls}`} title={term.tip}>
      {display}
    </span>
  );
}

// A plain label that carries a tooltip gloss (for column headers, dt labels,
// metric captions - anywhere a term needs a quiet explanation on hover).
export function TermTip({ term, children }: { term: string; children: ReactNode }) {
  return (
    <span className="ux-termtip" title={term}>
      {children}
    </span>
  );
}
