// One graph-check function shared by the routine canvas Problems strip and the
// picker cards' State word, so the list and the canvas can never disagree about
// what needs fixing. It runs on a normalized step shape so the same checks
// apply to a WorkflowStepDraft (the editor) and a WorkflowStepDefinition (a
// picker card's saved spec). Every finding is phrased as what the ENGINE will
// actually do — "never runs", "arrives empty" — not as a style opinion.

import type { WorkflowStepDefinition } from "@wlilley93/boltrig-web-sdk";

import type { WorkflowStepDraft } from "../../workflowDraft";

export interface GraphCheckStep {
  id: string;
  action: string;
  parents: string[];
  branch: string;
  /** `$step` references found in this step's parameters. */
  refs: string[];
}

export interface GraphProblem {
  stepId: string;
  text: string;
  /** red blocks the walk entirely; amber means a step silently does nothing. */
  tone: "red" | "amber";
}

const REF_PATTERN = /\$([A-Za-z0-9_-]+)/g;

export function draftToCheckStep(step: WorkflowStepDraft): GraphCheckStep {
  return {
    id: step.id.trim(),
    action: step.action.trim(),
    parents: step.parents.map((parent) => parent.trim()),
    branch: step.branchArm,
    refs: collectRefs(step.paramsText),
  };
}

export function definitionToCheckStep(
  step: WorkflowStepDefinition,
): GraphCheckStep {
  const record = step as Record<string, unknown>;
  const params = record.params ?? record.with;
  return {
    id: typeof record.id === "string" ? record.id : "",
    action: typeof record.action === "string" ? record.action : "",
    parents: Array.isArray(record.parents)
      ? record.parents.filter((item): item is string => typeof item === "string")
      : [],
    branch: typeof record.branch === "string" ? record.branch : "",
    refs: collectRefs(safeJson(params)),
  };
}

/**
 * The full check set: cycle (red), unreachable step, missing action, branch
 * label nothing above produces, $ref to a non-ancestor, and a step waiting on
 * both a loop and something outside it. Cycle and missing-action also exist in
 * validateWorkflowDraft as save blockers; the rest are honest warnings — the
 * definition saves, but the named step will not do what its author expects.
 */
export function checkGraph(steps: GraphCheckStep[]): GraphProblem[] {
  const problems: GraphProblem[] = [];
  const byId = new Map(steps.map((step) => [step.id, step]));
  const ancestors = ancestorMap(steps, byId);
  const reachable = reachableFromRoots(steps);
  const loopBodies = loopBodyMap(steps, byId);

  for (const step of steps) {
    if (!step.id) continue;
    if (ancestors.get(step.id)?.has(step.id)) {
      problems.push({
        stepId: step.id,
        text: `${step.id} leads back to itself, so the walk would never finish.`,
        tone: "red",
      });
    }
    if (!reachable.has(step.id)) {
      problems.push({
        stepId: step.id,
        text: `${step.id} has nothing leading to it, so it never runs.`,
        tone: "amber",
      });
    }
    if (!step.action) {
      problems.push({
        stepId: step.id,
        text: `${step.id} has no action set yet.`,
        tone: "amber",
      });
    }
    if (step.branch) {
      const producesLabel = [...(ancestors.get(step.id) ?? [])].some(
        (ancestor) => byId.get(ancestor)?.action === "flow.branch",
      );
      if (!producesLabel) {
        problems.push({
          stepId: step.id,
          text: `${step.id} declares the ${step.branch} label, but nothing above it produces one, so the label is ignored.`,
          tone: "amber",
        });
      }
    }
    for (const ref of step.refs) {
      if (ref === step.id || !byId.has(ref)) continue;
      if (!ancestors.get(step.id)?.has(ref)) {
        problems.push({
          stepId: step.id,
          text: `${step.id} reads $${ref}, which is not one of its ancestors, so the value is not guaranteed and can arrive empty.`,
          tone: "amber",
        });
      }
    }
  }

  for (const [loopId, body] of loopBodies) {
    for (const step of steps) {
      if (step.id === loopId || body.has(step.id)) continue;
      const touchesLoop = step.parents.some(
        (parent) => parent === loopId || body.has(parent),
      );
      const waitsOutside = step.parents.some(
        (parent) => parent !== loopId && !body.has(parent),
      );
      if (touchesLoop && waitsOutside) {
        problems.push({
          stepId: step.id,
          text: `${step.id} waits on the loop and on something outside it, so it falls outside the body and runs once, after the loop.`,
          tone: "amber",
        });
      }
    }
  }
  return problems;
}

export function checkDraftSteps(steps: WorkflowStepDraft[]): GraphProblem[] {
  return checkGraph(steps.map(draftToCheckStep));
}

export function checkDefinitionSteps(
  steps: WorkflowStepDefinition[],
): GraphProblem[] {
  return checkGraph(steps.map(definitionToCheckStep));
}

/** Worst tone per step, for card outlines: red wins over amber. */
export function problemToneByStep(
  problems: GraphProblem[],
): Map<string, "red" | "amber"> {
  const tones = new Map<string, "red" | "amber">();
  for (const problem of problems) {
    if (problem.tone === "red" || !tones.has(problem.stepId)) {
      tones.set(problem.stepId, problem.tone);
    }
  }
  return tones;
}

/** Ancestor sets per step; a cyclic step contains itself. */
export function ancestorMap(
  steps: GraphCheckStep[],
  byId = new Map(steps.map((step) => [step.id, step])),
): Map<string, Set<string>> {
  const map = new Map<string, Set<string>>();
  for (const step of steps) {
    const out = new Set<string>();
    const stack = [...step.parents];
    let guard = 0;
    while (stack.length > 0 && guard++ < 4000) {
      const parent = stack.pop()!;
      if (out.has(parent)) continue;
      out.add(parent);
      for (const grand of byId.get(parent)?.parents ?? []) {
        if (!out.has(grand)) stack.push(grand);
      }
    }
    map.set(step.id, out);
  }
  return map;
}

// --- internals --------------------------------------------------------------

function reachableFromRoots(steps: GraphCheckStep[]): Set<string> {
  const reachable = new Set<string>();
  const queue = steps
    .filter((step) => step.parents.length === 0)
    .map((step) => step.id);
  let guard = 0;
  while (queue.length > 0 && guard++ < 4000) {
    const id = queue.shift()!;
    if (reachable.has(id)) continue;
    reachable.add(id);
    for (const step of steps) {
      if (step.parents.includes(id) && !reachable.has(step.id)) {
        queue.push(step.id);
      }
    }
  }
  return reachable;
}

/**
 * Loop bodies via the same fixed point as workflowDraft.loopBodyStepIds: a
 * step is inside a loop's body when every parent is the loop or already in
 * the body. Kept separate because this module also runs on saved definitions.
 */
function loopBodyMap(
  steps: GraphCheckStep[],
  byId: Map<string, GraphCheckStep>,
): Map<string, Set<string>> {
  const bodies = new Map<string, Set<string>>();
  for (const loop of steps) {
    if (loop.action !== "flow.loop") continue;
    const body = new Set<string>();
    let changed = true;
    let guard = 0;
    while (changed && guard++ < 400) {
      changed = false;
      for (const step of steps) {
        if (step.id === loop.id || body.has(step.id) || step.parents.length === 0) {
          continue;
        }
        const inside = step.parents.every(
          (parent) => parent === loop.id || body.has(parent),
        );
        const touches = step.parents.some(
          (parent) => parent === loop.id || body.has(parent),
        );
        if (inside && touches && byId.has(step.id)) {
          body.add(step.id);
          changed = true;
        }
      }
    }
    bodies.set(loop.id, body);
  }
  return bodies;
}

function collectRefs(text: string): string[] {
  const refs: string[] = [];
  for (const match of text.matchAll(REF_PATTERN)) {
    if (!refs.includes(match[1])) refs.push(match[1]);
  }
  return refs;
}

function safeJson(value: unknown): string {
  if (value === undefined) return "";
  try {
    return JSON.stringify(value) ?? "";
  } catch {
    return "";
  }
}
