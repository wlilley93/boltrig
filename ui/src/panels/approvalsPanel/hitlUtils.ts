import type { HITLKind, HITLRequest } from "@/api/types";

export const ALL_HITL_TYPES = "all-types";
export const ALL_HITL_URGENCIES = "all-urgencies";

const TYPE_ORDER: Record<HITLKind, number> = {
  approval: 0,
  escalation: 1,
  clarification: 2,
  question: 3,
};

const URGENCY_ORDER: Record<string, number> = {
  blocking: 0,
  async: 1,
};

export interface HitlFilters {
  type: string;
  urgency: string;
}

// Approval producers normally send explicit approve/reject options. Keep the
// deliberate two-step ritual even for a legacy approval that omitted them.
export function decisionOptions(type: HITLKind, options: string[] = []): string[] {
  if (options.length > 0) return options;
  return type === "approval" ? ["approve", "reject"] : [];
}

// The queue is deterministic and operationally useful: blocking work first,
// then approvals/escalations before informational questions, then stable id.
export function filterAndSortHitl(
  requests: readonly HITLRequest[],
  filters: HitlFilters,
): HITLRequest[] {
  return requests
    .filter((request) =>
      (filters.type === ALL_HITL_TYPES || request.type === filters.type) &&
      (filters.urgency === ALL_HITL_URGENCIES || request.urgency === filters.urgency),
    )
    .slice()
    .sort((left, right) => {
      const urgency = (URGENCY_ORDER[left.urgency ?? ""] ?? 2) -
        (URGENCY_ORDER[right.urgency ?? ""] ?? 2);
      if (urgency !== 0) return urgency;
      const type = TYPE_ORDER[left.type] - TYPE_ORDER[right.type];
      return type !== 0 ? type : left.id.localeCompare(right.id);
    });
}

export function renderContext(context: unknown): string | null {
  if (context === null || context === undefined) return null;
  if (typeof context === "string") {
    try {
      return JSON.stringify(JSON.parse(context), null, 2);
    } catch {
      return context;
    }
  }
  try {
    return JSON.stringify(context, null, 2);
  } catch {
    return String(context);
  }
}

export function runFromContext(context: unknown): string | null {
  if (!context || typeof context !== "object") return null;
  const obj = context as Record<string, unknown>;
  const candidate = obj.run_id ?? obj.run;
  return typeof candidate === "string" && candidate ? candidate : null;
}

// Pull the faithful server reason out of a thrown ApiError (its body carries a
// reason on a 403/409) rather than leaking "POST ... -> 403".
export function reasonOf(err: unknown): string {
  if (err && typeof err === "object") {
    const body = (err as { body?: unknown }).body;
    if (body && typeof body === "object") {
      const r = (body as { reason?: unknown }).reason;
      if (typeof r === "string" && r) return r;
    }
  }
  return err instanceof Error ? err.message : String(err);
}

// "approve"-like options read as the primary, weighted action; "reject"-like as
// a neutral decline. Everything else is a neutral button.
export function optionClass(opt: string): string {
  const o = opt.toLowerCase();
  if (o === "approve" || o === "yes" || o === "allow") return "btn btn--primary";
  if (o === "reject" || o === "no" || o === "deny") return "btn btn--danger";
  return "btn";
}
