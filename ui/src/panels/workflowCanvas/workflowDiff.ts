// Structural diff between the CURRENT workflow definition and a PROPOSED one
// (read from a pending control.workflow.upsert approval hold). Pure data - the
// canvas renders it, the approval decides it. This is the Studio's trust
// surface: what you approve is exactly the delta you previewed.

import type { WorkflowStep } from "./types";

export type StepDiffKind = "added" | "removed" | "changed";

export interface StepsDiff {
  added: string[];
  removed: string[];
  changed: string[];
  byStep: Map<string, StepDiffKind>;
}

// Key-order-insensitive fingerprint so a re-serialised but identical step is
// not reported as changed.
function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([k, v]) => `${JSON.stringify(k)}:${stable(v)}`);
    return `{${entries.join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

export function diffSteps(current: WorkflowStep[], proposed: WorkflowStep[]): StepsDiff {
  const currentById = new Map(current.map((s) => [s.id, s]));
  const proposedById = new Map(proposed.map((s) => [s.id, s]));
  const added: string[] = [];
  const removed: string[] = [];
  const changed: string[] = [];
  for (const step of proposed) {
    const prior = currentById.get(step.id);
    if (!prior) added.push(step.id);
    else if (stable(prior) !== stable(step)) changed.push(step.id);
  }
  for (const step of current) {
    if (!proposedById.has(step.id)) removed.push(step.id);
  }
  const byStep = new Map<string, StepDiffKind>();
  for (const id of added) byStep.set(id, "added");
  for (const id of removed) byStep.set(id, "removed");
  for (const id of changed) byStep.set(id, "changed");
  return { added, removed, changed, byStep };
}

// Extract the proposed definition's steps from an approval hold's display
// context ({version, requested_by, verb, inputs, resource_context} with
// inputs = the validated control.workflow.upsert params). Returns null when
// the context does not carry a readable step list (redaction, older shapes) -
// the preview simply isn't offered; nothing guesses.
export function proposedStepsFromContext(context: unknown): WorkflowStep[] | null {
  if (!context || typeof context !== "object") return null;
  const inputs = (context as { inputs?: unknown }).inputs;
  if (!inputs || typeof inputs !== "object") return null;
  const definition = (inputs as { definition?: unknown }).definition;
  if (!definition || typeof definition !== "object") return null;
  const steps = (definition as { steps?: unknown }).steps;
  if (!Array.isArray(steps)) return null;
  const out: WorkflowStep[] = [];
  for (const raw of steps) {
    if (!raw || typeof raw !== "object") return null;
    const step = raw as Record<string, unknown>;
    if (typeof step.id !== "string" || typeof step.action !== "string") return null;
    out.push({
      id: step.id,
      action: step.action,
      parents: Array.isArray(step.parents) ? (step.parents as string[]) : [],
      params:
        step.params && typeof step.params === "object"
          ? (step.params as Record<string, unknown>)
          : undefined,
      description: typeof step.description === "string" ? step.description : undefined,
    });
  }
  return out;
}
