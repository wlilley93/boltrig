import type { InvokeResult } from "../../api/types";
import type { WorkflowDraftStep } from "../automations/draft";

export type WorkflowStep = WorkflowDraftStep;

export interface SaveParams extends Record<string, unknown> {
  id: string;
  version: string;
  source: string;
  definition: Record<string, unknown>;
  intent_tags: string[];
}

export function extractSteps(value: unknown): WorkflowStep[] {
  if (!value || typeof value !== "object") return [];
  const steps = (value as { steps?: unknown }).steps;
  if (!Array.isArray(steps)) return [];
  const parsed: Array<WorkflowStep | null> = steps.map((raw) => {
      if (!raw || typeof raw !== "object") return null;
      const r = raw as Record<string, unknown>;
      if (typeof r.id !== "string") return null;
      return {
        id: r.id,
        parents: Array.isArray(r.parents)
          ? r.parents.filter((p): p is string => typeof p === "string")
          : [],
        action: typeof r.action === "string" ? r.action : "",
        params:
          r.params && typeof r.params === "object" && !Array.isArray(r.params)
            ? (r.params as Record<string, unknown>)
            : undefined,
        description: typeof r.description === "string" ? r.description : undefined,
      };
    });
  return parsed.filter((s): s is WorkflowStep => s !== null);
}

export function bumpPatch(version: string): string {
  const parts = version.split(".");
  const patch = Number(parts[2] ?? "0");
  if (parts.length >= 3 && Number.isFinite(patch)) {
    return `${parts[0]}.${parts[1]}.${patch + 1}`;
  }
  return `${version}.1`;
}

export function uniqueStepId(steps: WorkflowStep[], base: string): string {
  const safe = (base || "step").replace(/[^a-zA-Z0-9_-]/g, "_") || "step";
  const taken = new Set(steps.map((s) => s.id));
  let id = safe;
  let i = 1;
  while (taken.has(id)) {
    i += 1;
    id = `${safe}_${i}`;
  }
  return id;
}

export function wouldCreateCycle(steps: WorkflowStep[], stepId: string, parentId: string): boolean {
  const byParent = new Map<string, string[]>();
  for (const step of steps) {
    for (const parent of step.parents) {
      const list = byParent.get(parent) ?? [];
      list.push(step.id);
      byParent.set(parent, list);
    }
  }
  const queue = [...(byParent.get(stepId) ?? [])];
  const seen = new Set<string>();
  while (queue.length > 0) {
    const id = queue.shift() as string;
    if (id === parentId) return true;
    if (seen.has(id)) continue;
    seen.add(id);
    queue.push(...(byParent.get(id) ?? []));
  }
  return false;
}

export function classifyResult(result: InvokeResult): string | null {
  if (result.status === "denied" || result.status === "error") return result.reason;
  return null;
}
