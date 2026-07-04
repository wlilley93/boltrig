import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import type { Edge } from "@xyflow/react";
import type { VerbInfo } from "@/api/types";
import { parseJson, errText } from "@/panels/shared";
import { deriveKind, isStepNode } from "./graph";
import type { CanvasNode, StepNode } from "./types";

interface GraphBag {
  nodes: CanvasNode[];
  setNodes: Dispatch<SetStateAction<CanvasNode[]>>;
  setEdges: Dispatch<SetStateAction<Edge[]>>;
  setSelectedId: (id: string | null) => void;
}

export function useWorkflowInspector(
  selectedNode: StepNode | undefined,
  graph: GraphBag,
  verbsById: Map<string, VerbInfo>,
) {
  const [editId, setEditId] = useState("");
  const [editParams, setEditParams] = useState("{}");
  const [editDesc, setEditDesc] = useState("");
  const [editError, setEditError] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedNode) {
      setEditId("");
      setEditParams("{}");
      setEditDesc("");
      setEditError(null);
      return;
    }
    setEditId(selectedNode.id);
    setEditParams(JSON.stringify(selectedNode.data.params ?? {}, null, 2));
    setEditDesc(selectedNode.data.description ?? "");
    setEditError(null);
  }, [selectedNode?.id]);

  return {
    editId,
    setEditId,
    editParams,
    setEditParams,
    editDesc,
    setEditDesc,
    editError,
    setEditError,
    dirty: () => inspectorDirty(selectedNode, editParams, editDesc),
    commit: () =>
      commitInspector(selectedNode, editParams, editDesc, setEditError, graph.setNodes),
    applyParams: () =>
      commitInspector(selectedNode, editParams, editDesc, setEditError, graph.setNodes),
    swapVerb: (verbId: string) =>
      swapVerb(verbId, selectedNode, verbsById, graph.setNodes),
    renameStep: () =>
      renameStep(selectedNode, editId, graph, setEditError),
  };
}

function inspectorDirty(
  selectedNode: StepNode | undefined,
  editParams: string,
  editDesc: string,
): boolean {
  const nodeParams = JSON.stringify(selectedNode?.data.params ?? {}, null, 2);
  return (
    editParams !== nodeParams ||
    editDesc !== (selectedNode?.data.description ?? "")
  );
}

function commitInspector(
  selectedNode: StepNode | undefined,
  editParams: string,
  editDesc: string,
  setEditError: (err: string | null) => void,
  setNodes: Dispatch<SetStateAction<CanvasNode[]>>,
): boolean {
  if (!selectedNode) return false;
  let parsed: Record<string, unknown>;
  try {
    parsed = parseJson<Record<string, unknown>>(editParams, {});
  } catch (err) {
    setEditError(`params: ${errText(err)}`);
    return false;
  }
  setEditError(null);
  const id = selectedNode.id;
  setNodes((ns) =>
    ns.map((n) =>
      n.id === id && isStepNode(n)
        ? {
            ...n,
            data: {
              ...n.data,
              params: parsed,
              description: editDesc.trim() || undefined,
            },
          }
        : n,
    ),
  );
  return true;
}

function swapVerb(
  verbId: string,
  selectedNode: StepNode | undefined,
  verbsById: Map<string, VerbInfo>,
  setNodes: Dispatch<SetStateAction<CanvasNode[]>>,
) {
  if (!selectedNode || !verbId) return;
  const v = verbsById.get(verbId);
  if (!v) return;
  const id = selectedNode.id;
  setNodes((ns) =>
    ns.map((n) =>
      n.id === id && isStepNode(n)
        ? {
            ...n,
            data: {
              ...n.data,
              action: v.id,
              kind: deriveKind(v),
              consequence: v.consequence,
            },
          }
        : n,
    ),
  );
}

function renameStep(
  selectedNode: StepNode | undefined,
  editId: string,
  graph: GraphBag,
  setEditError: (err: string | null) => void,
) {
  if (!selectedNode) return;
  const oldId = selectedNode.id;
  const newId = editId.trim();
  if (!newId || newId === oldId) return;
  if (graph.nodes.some((n) => n.id === newId)) {
    setEditError("a node with that id already exists");
    return;
  }
  setEditError(null);
  graph.setNodes((ns) =>
    ns.map((n) => {
      if (n.id !== oldId) return n;
      if (isStepNode(n)) {
        return {
          ...n,
          id: newId,
          data: {
            ...n.data,
            label: n.data.label === oldId ? newId : n.data.label,
          },
        };
      }
      return { ...n, id: newId };
    }),
  );
  graph.setEdges((es) =>
    es.map((e) => ({
      ...e,
      source: e.source === oldId ? newId : e.source,
      target: e.target === oldId ? newId : e.target,
    })),
  );
  graph.setSelectedId(newId);
}
