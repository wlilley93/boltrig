// Shared presentation helpers for the run drill-down cluster (SubagentTabs and
// RunSectionView). Everything here maps REAL server fields onto display copy;
// nothing may synthesise a value the stream or an endpoint did not carry.

// Mirrors ParityViews' unexported `formatCost` byte-for-byte so the two spend
// surfaces cannot disagree about money. If ParityViews ever exports its copy,
// this one should collapse into it.
export function formatCostMicros(micros: number): string {
  if (!Number.isFinite(micros) || micros <= 0) return "$0.00";
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: micros < 10_000 ? 6 : 2,
    maximumFractionDigits: micros < 10_000 ? 6 : 2,
  }).format(micros / 1_000_000);
}

// The ONE visual register the section drawing uses: work-item status mapped to
// the console tone tokens. There is deliberately no second register (the design
// had a dashed "not held in place" durability rail, but no durable field exists
// on RunTopologyNode, so drawing it would be an invented signal).
export type StatusTone = "green" | "amber" | "red" | "accent" | "unknown";

export function statusTone(status: string | undefined): StatusTone {
  switch (status) {
    case "done":
    case "ok":
    case "completed":
      return "green";
    case "awaiting_human":
    case "blocked":
    case "paused":
      return "amber";
    case "failed":
    case "error":
    case "cancelled":
      return "red";
    case "in_flight":
    case "running":
      return "accent";
    default:
      return "unknown";
  }
}

// Plain-language status words for the WorkStatus vocabulary. An unknown status
// string is shown verbatim rather than guessed at.
export function statusPhrase(status: string | undefined): string {
  switch (status) {
    case "done":
      return "finished";
    case "in_flight":
      return "working now";
    case "pending":
      return "queued";
    case "blocked":
      return "blocked";
    case "awaiting_human":
      return "waiting for you";
    case "failed":
      return "failed";
    case "cancelled":
      return "cancelled";
    default:
      return status ?? "unreported";
  }
}
