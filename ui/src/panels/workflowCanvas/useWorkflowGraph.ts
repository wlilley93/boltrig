import { useMemo, useRef, useState, type Dispatch, type SetStateAction, type MutableRefObject } from "react";
import {
  addEdge,
  type Connection,
  type XYPosition,
} from "@xyflow/react";
import type { VerbInfo } from "@/api/types";
import { parseJson, errText } from "@/panels/shared";
import { deriveKind, deriveNodeKind, extractSteps, graphToSteps, isStepNode, stepsToGraph } from "./graph";
import {
  defaultActionForKind,
  CONTROL_NODE_KINDS,
  kindFromVisual,
  resolveVerbForKind,
  type NodeVisualKind,
} from "./nodeTaxonomy";
import { useGraphHistory, type GraphHistory } from "./useGraphHistory";
import type { CanvasNode, StepNode, TriggerKind, WorkflowStep } from "./types";

export function useWorkflowGraph(verbsById: Map<string, VerbInfo>) {
  const hist = useGraphHistory<CanvasNode>();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [paletteFilter, setPaletteFilter] = useState("");
  const [loadText, setLoadText] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const counter = useRef(0);

  const selectedNode = hist.nodes.find(
    (n): n is StepNode => n.id === selectedId && isStepNode(n),
  );
  const previewSteps = useMemo(
    () => graphToSteps(hist.nodes, hist.edges),
    [hist.nodes, hist.edges],
  );

  return {
    nodes: hist.nodes,
    setNodes: hist.setNodes,
    onNodesChange: hist.onNodesChange,
    edges: hist.edges,
    setEdges: hist.setEdges,
    onEdgesChange: hist.onEdgesChange,
    selectedId,
    setSelectedId,
    selectedNode,
    paletteFilter,
    setPaletteFilter,
    loadText,
    setLoadText,
    loadError,
    setLoadError,
    counter,
    previewSteps,
    addVerbNode: (verb: VerbInfo) =>
      addVerbNode(verb, hist.nodes, hist.setNodes, setSelectedId, counter),
    addNodeKind: (kind: NodeVisualKind, position?: { x: number; y: number }) =>
      addNodeKindNode(kind, verbsById, hist.nodes, hist.setNodes, setSelectedId, counter, position),
    addTrigger: (triggerType: TriggerKind) =>
      addTriggerNode(triggerType, hist.nodes, hist.setNodes, counter),
    onConnect: (connection: Connection) =>
      hist.setEdges((es) => addEdge({ ...connection, type: "workflow" }, es)),
    deleteSelected: () =>
      deleteSelectedNode(selectedId, hist.replace, setSelectedId),
    clearCanvas: () => clearGraph(hist.replace, setSelectedId),
    loadGraph: (steps: WorkflowStep[]) =>
      loadSteps(steps, verbsById, hist.reset, setSelectedId),
    loadFromJson: () =>
      loadFromJsonText(loadText, setLoadError, (steps) =>
        loadSteps(steps, verbsById, hist.reset, setSelectedId),
      ),
    // History surface for the editor header (sec 22.2).
    replace: hist.replace,
    resetHistory: hist.reset,
    canUndo: hist.canUndo,
    canRedo: hist.canRedo,
    undo: hist.undo,
    redo: hist.redo,
  };
}

export type WorkflowGraph = ReturnType<typeof useWorkflowGraph>;
export type { GraphHistory };

function addVerbNode(
  verb: VerbInfo,
  nodes: CanvasNode[],
  setNodes: Dispatch<SetStateAction<CanvasNode[]>>,
  setSelectedId: (id: string | null) => void,
  counter: MutableRefObject<number>,
) {
  const id = uniqueStepId(verb, nodes, counter);
  const index = nodes.filter(isStepNode).length;
  const node: StepNode = {
    id,
    type: "step",
    position: { x: 60 + (index % 3) * 60, y: 60 + index * 70 },
    data: {
      action: verb.id,
      params: {},
      kind: deriveKind(verb),
      nodeKind: deriveNodeKind(verb),
      label: id,
      consequence: verb.consequence,
    },
  };
  setNodes((ns) => [...ns, node]);
  setSelectedId(id);
}

function uniqueStepId(
  verb: VerbInfo,
  nodes: CanvasNode[],
  counter: MutableRefObject<number>,
): string {
  const base = (verb.id.split(".").pop() || "step").replace(
    /[^a-zA-Z0-9_]/g,
    "_",
  );
  const taken = new Set(nodes.map((n) => n.id));
  let candidate = base;
  while (taken.has(candidate)) {
    counter.current += 1;
    candidate = `${base}_${counter.current}`;
  }
  return candidate;
}

function addNodeKindNode(
  kind: NodeVisualKind,
  verbsById: Map<string, VerbInfo>,
  nodes: CanvasNode[],
  setNodes: Dispatch<SetStateAction<CanvasNode[]>>,
  setSelectedId: (id: string | null) => void,
  counter: MutableRefObject<number>,
  position?: XYPosition,
) {
  // Capability nodes bind only to a caller-scoped real verb. The only fallback
  // actions are safe interpreter-owned control nodes.
  const resolved = resolveVerbForKind(kind, verbsById);
  if (!resolved && !CONTROL_NODE_KINDS.has(kind)) return;
  const fallback = defaultActionForKind(kind);
  const action = resolved?.action ?? fallback.action;
  const params = resolved?.params ?? fallback.params;
  const base = (action.split(".").pop() || "node").replace(/[^a-zA-Z0-9_]/g, "_");
  const taken = new Set(nodes.map((n) => n.id));
  let candidate = base;
  while (taken.has(candidate)) {
    counter.current += 1;
    candidate = `${base}_${counter.current}`;
  }
  const index = nodes.filter(isStepNode).length;
  const node: StepNode = {
    id: candidate,
    type: "step",
    position: position ?? { x: 80 + (index % 3) * 80, y: 80 + index * 90 },
    data: {
      action,
      params: { ...params, __nodeKind: kind },
      kind: kindFromVisual(kind),
      nodeKind: kind,
      label: candidate,
    },
  };
  setNodes((ns) => [...ns, node]);
  setSelectedId(candidate);
}

function addTriggerNode(
  triggerType: TriggerKind,
  nodes: CanvasNode[],
  setNodes: Dispatch<SetStateAction<CanvasNode[]>>,
  counter: MutableRefObject<number>,
) {
  counter.current += 1;
  const id = `trigger_${triggerType}_${counter.current}`;
  const index = nodes.filter((n) => n.type === "trigger").length;
  const node = {
    id,
    type: "trigger" as const,
    position: { x: -200, y: 60 + index * 90 },
    data: { triggerType, label: `${triggerType} entry` },
  };
  setNodes((ns) => [...ns, node]);
}

function deleteSelectedNode(
  selectedId: string | null,
  replace: GraphHistory<CanvasNode>["replace"],
  setSelectedId: (id: string | null) => void,
) {
  if (!selectedId) return;
  replace((p) => ({
    nodes: p.nodes.filter((n) => n.id !== selectedId),
    edges: p.edges.filter((e) => e.source !== selectedId && e.target !== selectedId),
  }));
  setSelectedId(null);
}

function clearGraph(
  replace: GraphHistory<CanvasNode>["replace"],
  setSelectedId: (id: string | null) => void,
) {
  replace({ nodes: [], edges: [] });
  setSelectedId(null);
}

function loadSteps(
  steps: WorkflowStep[],
  verbsById: Map<string, VerbInfo>,
  reset: GraphHistory<CanvasNode>["reset"],
  setSelectedId: (id: string | null) => void,
) {
  const graph = stepsToGraph(steps, verbsById);
  reset({ nodes: graph.nodes, edges: graph.edges });
  setSelectedId(null);
}

function loadFromJsonText(
  loadText: string,
  setLoadError: (err: string | null) => void,
  loadGraph: (steps: WorkflowStep[]) => void,
) {
  let parsed: unknown;
  try {
    parsed = parseJson<unknown>(loadText, []);
  } catch (err) {
    setLoadError(`definition: ${errText(err)}`);
    return;
  }
  const steps = extractSteps(parsed);
  if (!steps) {
    setLoadError("expected a steps array or a {steps:[...]} object");
    return;
  }
  setLoadError(null);
  loadGraph(steps);
}
