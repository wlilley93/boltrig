import { useMemo, useRef, useState, type Dispatch, type SetStateAction, type MutableRefObject } from "react";
import {
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type XYPosition,
} from "@xyflow/react";
import type { VerbInfo } from "@/api/types";
import { parseJson, errText } from "@/panels/shared";
import { deriveKind, deriveNodeKind, extractSteps, graphToSteps, isStepNode, stepsToGraph } from "./graph";
import {
  defaultActionForKind,
  kindFromVisual,
  type NodeVisualKind,
} from "./nodeTaxonomy";
import type { CanvasNode, StepNode, TriggerKind, WorkflowStep } from "./types";

export function useWorkflowGraph(verbsById: Map<string, VerbInfo>) {
  const [nodes, setNodes, onNodesChange] = useNodesState<CanvasNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [paletteFilter, setPaletteFilter] = useState("");
  const [loadText, setLoadText] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const counter = useRef(0);

  const selectedNode = nodes.find(
    (n): n is StepNode => n.id === selectedId && isStepNode(n),
  );
  const previewSteps = useMemo(
    () => graphToSteps(nodes, edges),
    [nodes, edges],
  );

  return {
    nodes,
    setNodes,
    onNodesChange,
    edges,
    setEdges,
    onEdgesChange,
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
      addVerbNode(verb, nodes, setNodes, setSelectedId, counter),
    addNodeKind: (kind: NodeVisualKind, position?: { x: number; y: number }) =>
      addNodeKindNode(kind, nodes, setNodes, setSelectedId, counter, position),
    addTrigger: (triggerType: TriggerKind) =>
      addTriggerNode(triggerType, nodes, setNodes, counter),
    onConnect: (connection: Connection) =>
      setEdges((es) => addEdge({ ...connection, type: "workflow" }, es)),
    deleteSelected: () =>
      deleteSelectedNode(selectedId, setNodes, setEdges, setSelectedId),
    clearCanvas: () => clearGraph(setNodes, setEdges, setSelectedId),
    loadGraph: (steps: WorkflowStep[]) =>
      loadSteps(steps, verbsById, setNodes, setEdges, setSelectedId),
    loadFromJson: () =>
      loadFromJsonText(loadText, setLoadError, (steps) =>
        loadSteps(steps, verbsById, setNodes, setEdges, setSelectedId),
      ),
  };
}

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
  nodes: CanvasNode[],
  setNodes: Dispatch<SetStateAction<CanvasNode[]>>,
  setSelectedId: (id: string | null) => void,
  counter: MutableRefObject<number>,
  position?: XYPosition,
) {
  const { action, params } = defaultActionForKind(kind);
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
  setNodes: Dispatch<SetStateAction<CanvasNode[]>>,
  setEdges: Dispatch<SetStateAction<Edge[]>>,
  setSelectedId: (id: string | null) => void,
) {
  if (!selectedId) return;
  setNodes((ns) => ns.filter((n) => n.id !== selectedId));
  setEdges((es) =>
    es.filter((e) => e.source !== selectedId && e.target !== selectedId),
  );
  setSelectedId(null);
}

function clearGraph(
  setNodes: Dispatch<SetStateAction<CanvasNode[]>>,
  setEdges: Dispatch<SetStateAction<Edge[]>>,
  setSelectedId: (id: string | null) => void,
) {
  setNodes([]);
  setEdges([]);
  setSelectedId(null);
}

function loadSteps(
  steps: WorkflowStep[],
  verbsById: Map<string, VerbInfo>,
  setNodes: Dispatch<SetStateAction<CanvasNode[]>>,
  setEdges: Dispatch<SetStateAction<Edge[]>>,
  setSelectedId: (id: string | null) => void,
) {
  const graph = stepsToGraph(steps, verbsById);
  setNodes(graph.nodes);
  setEdges(graph.edges);
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
