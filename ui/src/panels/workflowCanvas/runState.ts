import type { Edge } from "@xyflow/react";

import type { CanvasNode, RunNodeStatus, StepNode } from "./types";

export type RunEdgeVariant =
  | "default"
  | "running"
  | "ok"
  | "failed"
  | "paused";

export function edgeVariantForStatus(
  status: RunNodeStatus | undefined,
): RunEdgeVariant {
  switch (status) {
    case "running":
      return "running";
    case "ok":
    // An absorbed failure delivered a defined output and traversal continued -
    // the wire is taken; the node's own badge carries the caveat.
    case "exception":
      return "ok";
    case "failed":
    case "error":
      return "failed";
    case "paused":
      return "paused";
    default:
      return "default";
  }
}

// Apply one run snapshot to the authored graph without changing its topology.
// Edges key off their target step: when that step starts, the current visibly
// travels into it; once it settles, the traversed wire keeps the outcome tint.
export function overlayRunState(
  baseNodes: CanvasNode[],
  baseEdges: Edge[],
  statusById: Record<string, RunNodeStatus>,
  streamDone: boolean,
): { nodes: CanvasNode[]; edges: Edge[] } {
  const effective = new Map<string, RunNodeStatus>();
  const nodes = baseNodes.map((node) => {
    if (node.type !== "step") return node;
    let runStatus = statusById[node.id] ?? "pending";
    if (streamDone && runStatus === "running") runStatus = "pending";
    effective.set(node.id, runStatus);
    return {
      ...node,
      data: { ...(node as StepNode).data, runStatus },
    } as StepNode;
  });

  const edges = baseEdges.map((edge) => ({
    ...edge,
    data: {
      ...(edge.data ?? {}),
      variant: edgeVariantForStatus(effective.get(edge.target)),
    },
  }));

  return { nodes, edges };
}
