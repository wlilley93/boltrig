import { useEffect, useRef, type MouseEvent } from "react";
import type { VerbInfo } from "@/api/types";
import { useWorkflowData } from "./useWorkflowData";
import { useWorkflowMeta } from "./useWorkflowMeta";
import { useWorkflowGraph } from "./useWorkflowGraph";
import { useWorkflowInspector } from "./useWorkflowInspector";
import { useWorkflowApi } from "./useWorkflowApi";
import type { CanvasNode } from "./types";

export function useWorkflowCanvas(routeWfId?: string) {
  const data = useWorkflowData();
  const meta = useWorkflowMeta(routeWfId);
  const graph = useWorkflowGraph(data.verbsById);
  const inspector = useWorkflowInspector(
    graph.selectedNode,
    graph,
    data.verbsById,
  );
  const apiActions = useWorkflowApi({
    meta,
    graph,
    verbsById: data.verbsById,
    workflows: data.workflows,
  });

  const appliedRouteWf = useRef<string | null>(null);
  useEffect(() => {
    if (!routeWfId || appliedRouteWf.current === routeWfId) return;
    if (data.workflows.loading || data.caps.loading) return;
    appliedRouteWf.current = routeWfId;
    const summary = (data.workflows.data?.workflows ?? []).find(
      (w) => w.id === routeWfId,
    );
    if (summary) void apiActions.pickWorkflow(summary);
    else meta.setWfId(routeWfId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeWfId, data.workflows.loading, data.workflows.data, data.caps.loading]);

  const addVerbNode = (verb: VerbInfo) => {
    if (graph.selectedNode && inspector.dirty() && !inspector.commit()) return;
    graph.addVerbNode(verb);
  };

  const onNodeClick = (_event: MouseEvent, node: CanvasNode) => {
    const nextId = node.type === "step" ? node.id : null;
    if (nextId === graph.selectedId) return;
    if (graph.selectedNode && inspector.dirty() && !inspector.commit()) return;
    graph.setSelectedId(nextId);
  };

  return {
    data,
    meta,
    graph,
    inspector,
    apiActions,
    addVerbNode,
    onNodeClick,
  };
}
