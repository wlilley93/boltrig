// Pure graph helpers for the WorkflowCanvas. Steps <-> React Flow nodes/edges,
// topological ordering, and kind derivation from verb bindings.

import type { Edge } from "@xyflow/react";
import type { VerbInfo } from "@/api/types";
import {
  type CanvasNode,
  type NodeKind,
  type StepNode,
  type WorkflowStep,
} from "./types";

export function deriveKind(verb: VerbInfo | undefined): NodeKind {
  const target = verb?.binding?.target_type;
  if (target === "agent") return "agent";
  if (target === "adapter") return "service";
  return "kernel-run";
}

export function isStepNode(n: CanvasNode): n is StepNode {
  return n.type === "step";
}

function topoOrder(
  stepNodes: StepNode[],
  parentsById: Map<string, string[]>,
): StepNode[] {
  const ids = stepNodes.map((n) => n.id);
  const byId = new Map(stepNodes.map((n) => [n.id, n]));
  const remaining = new Map<string, Set<string>>(
    ids.map((id) => [id, new Set(parentsById.get(id) ?? [])]),
  );
  const emitted = new Set<string>();
  const out: StepNode[] = [];
  const queue = ids.filter((id) => (remaining.get(id)?.size ?? 0) === 0);

  while (queue.length > 0) {
    const id = queue.shift() as string;
    if (emitted.has(id)) continue;
    emitted.add(id);
    out.push(byId.get(id) as StepNode);
    for (const other of ids) {
      if (emitted.has(other)) continue;
      const set = remaining.get(other);
      if (set?.has(id)) {
        set.delete(id);
        if (set.size === 0 && !queue.includes(other)) queue.push(other);
      }
    }
  }

  return out.length === stepNodes.length ? out : stepNodes;
}

export function graphToSteps(nodes: CanvasNode[], edges: Edge[]): WorkflowStep[] {
  const stepNodes = nodes.filter(isStepNode);
  const stepIds = new Set(stepNodes.map((n) => n.id));
  const parentsById = new Map<string, string[]>();
  for (const n of stepNodes) parentsById.set(n.id, []);
  for (const e of edges) {
    if (stepIds.has(e.source) && stepIds.has(e.target)) {
      parentsById.get(e.target)?.push(e.source);
    }
  }

  return topoOrder(stepNodes, parentsById).map((n) => {
    const params = n.data.params ?? {};
    const step: WorkflowStep = {
      id: n.id,
      parents: parentsById.get(n.id) ?? [],
      action: n.data.action,
    };
    if (Object.keys(params).length > 0) step.params = params;
    const desc = n.data.description?.trim();
    if (desc) step.description = desc;
    return step;
  });
}

export function stepsToGraph(
  steps: WorkflowStep[],
  verbsById: Map<string, VerbInfo>,
): { nodes: StepNode[]; edges: Edge[] } {
  const byId = new Map(steps.map((s) => [s.id, s]));

  const depthCache = new Map<string, number>();
  function depthOf(id: string, seen: Set<string>): number {
    const cached = depthCache.get(id);
    if (cached !== undefined) return cached;
    if (seen.has(id)) return 0;
    seen.add(id);
    const parents = (byId.get(id)?.parents ?? []).filter((p) => byId.has(p));
    const value =
      parents.length === 0
        ? 0
        : 1 + Math.max(...parents.map((p) => depthOf(p, seen)));
    depthCache.set(id, value);
    return value;
  }

  const perLevel = new Map<number, number>();
  const nodes: StepNode[] = steps.map((s) => {
    const level = depthOf(s.id, new Set());
    const row = perLevel.get(level) ?? 0;
    perLevel.set(level, row + 1);
    return {
      id: s.id,
      type: "step",
      position: { x: 40 + level * 240, y: 40 + row * 120 },
      data: {
        action: s.action,
        params: s.params ?? {},
        kind: deriveKind(verbsById.get(s.action)),
        label: s.id,
        consequence: verbsById.get(s.action)?.consequence,
        ...(s.description ? { description: s.description } : {}),
      },
    };
  });

  const edges: Edge[] = [];
  for (const s of steps) {
    for (const parent of s.parents ?? []) {
      if (byId.has(parent)) {
        edges.push({ id: `${parent}__${s.id}`, source: parent, target: s.id });
      }
    }
  }

  return { nodes, edges };
}

export function extractSteps(value: unknown): WorkflowStep[] | null {
  if (Array.isArray(value)) return value as WorkflowStep[];
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    if (Array.isArray(obj.steps)) return obj.steps as WorkflowStep[];
    const def = obj.definition;
    if (def && typeof def === "object") {
      const steps = (def as Record<string, unknown>).steps;
      if (Array.isArray(steps)) return steps as WorkflowStep[];
    }
  }
  return null;
}
