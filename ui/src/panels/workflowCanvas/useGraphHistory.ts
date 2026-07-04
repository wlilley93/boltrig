// Lightweight present/past/future undo-redo over nodes + edges, wrapping the
// xyflow change model so the editor header (design brief sec 22.2) can offer
// undo/redo. Structural edits (add / delete / connect / inspector commit) push
// one snapshot; position drags coalesce to a single pre-drag snapshot; load /
// reset clears history so opening a workflow never pollutes the stack.
//
// Pure + framework-light: no ReactFlow context is read, only the
// applyNodeChanges / applyEdgeChanges reducers are reused so the controlled
// nodes/edges contract is preserved. Simple and correct over fancy.

import {
  useCallback,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import {
  applyEdgeChanges,
  applyNodeChanges,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
} from "@xyflow/react";

export interface GraphSnapshot<N extends Node = Node> {
  nodes: N[];
  edges: Edge[];
}

const HISTORY_CAP = 100;
const DRAG_IDLE_MS = 60;

interface HistoryState<N extends Node> {
  past: GraphSnapshot<N>[];
  present: GraphSnapshot<N>;
  future: GraphSnapshot<N>[];
}

export interface GraphHistory<N extends Node> {
  nodes: N[];
  edges: Edge[];
  setNodes: Dispatch<SetStateAction<N[]>>;
  setEdges: Dispatch<SetStateAction<Edge[]>>;
  onNodesChange: (changes: NodeChange<N>[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  // Atomic replace of both nodes + edges as one history entry (delete / clear).
  replace: (
    next: GraphSnapshot<N> | ((p: GraphSnapshot<N>) => GraphSnapshot<N>),
  ) => void;
  // Replace present and wipe history (used when loading a workflow).
  reset: (present: GraphSnapshot<N>) => void;
  canUndo: boolean;
  canRedo: boolean;
  undo: () => void;
  redo: () => void;
}

function pushPast<N extends Node>(
  past: GraphSnapshot<N>[],
  present: GraphSnapshot<N>,
): GraphSnapshot<N>[] {
  const merged = [...past, present];
  return merged.length > HISTORY_CAP
    ? merged.slice(merged.length - HISTORY_CAP)
    : merged;
}

export function useGraphHistory<N extends Node = Node>(
  initial: GraphSnapshot<N> = { nodes: [], edges: [] },
): GraphHistory<N> {
  const [state, setState] = useState<HistoryState<N>>(() => ({
    past: [],
    present: initial,
    future: [],
  }));
  const draggingRef = useRef(false);
  const dragIdle = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const { past, present, future } = state;
  const canUndo = past.length > 0;
  const canRedo = future.length > 0;

  const setNodes = useCallback<Dispatch<SetStateAction<N[]>>>((updater) => {
    setState((h) => {
      const next =
        typeof updater === "function"
          ? (updater as (n: N[]) => N[])(h.present.nodes)
          : updater;
      if (next === h.present.nodes) return h;
      return {
        past: pushPast(h.past, h.present),
        present: { nodes: next, edges: h.present.edges },
        future: [],
      };
    });
  }, []);

  const setEdges = useCallback<Dispatch<SetStateAction<Edge[]>>>((updater) => {
    setState((h) => {
      const next =
        typeof updater === "function"
          ? (updater as (e: Edge[]) => Edge[])(h.present.edges)
          : updater;
      if (next === h.present.edges) return h;
      return {
        past: pushPast(h.past, h.present),
        present: { nodes: h.present.nodes, edges: next },
        future: [],
      };
    });
  }, []);

  const replace = useCallback(
    (
      arg: GraphSnapshot<N> | ((p: GraphSnapshot<N>) => GraphSnapshot<N>),
    ) => {
      setState((h) => {
        const next = typeof arg === "function" ? arg(h.present) : arg;
        if (next.nodes === h.present.nodes && next.edges === h.present.edges) {
          return h;
        }
        return {
          past: pushPast(h.past, h.present),
          present: next,
          future: [],
        };
      });
    },
    [],
  );

  const onNodesChange = useCallback((changes: NodeChange<N>[]) => {
    const positional = changes.some((c) => c.type === "position");
    const structural = changes.some((c) => c.type === "add" || c.type === "remove");
    if (positional) {
      // Snapshot the pre-drag state once, then coalesce the move into the same
      // entry until the pointer idles (so one drag = one undo step).
      const dragStart = !draggingRef.current;
      draggingRef.current = true;
      clearTimeout(dragIdle.current);
      dragIdle.current = setTimeout(() => {
        draggingRef.current = false;
      }, DRAG_IDLE_MS);
      setState((h) => {
        const nextNodes = applyNodeChanges(changes, h.present.nodes);
        if (nextNodes === h.present.nodes) return h;
        return dragStart
          ? {
              past: pushPast(h.past, h.present),
              present: { nodes: nextNodes, edges: h.present.edges },
              future: [],
            }
          : { ...h, present: { nodes: nextNodes, edges: h.present.edges } };
      });
      return;
    }
    if (structural) {
      setState((h) => {
        const nextNodes = applyNodeChanges(changes, h.present.nodes);
        if (nextNodes === h.present.nodes) return h;
        return {
          past: pushPast(h.past, h.present),
          present: { nodes: nextNodes, edges: h.present.edges },
          future: [],
        };
      });
      return;
    }
    // selection / dimensions: apply silently (no history entry)
    setState((h) => {
      const nextNodes = applyNodeChanges(changes, h.present.nodes);
      if (nextNodes === h.present.nodes) return h;
      return { ...h, present: { nodes: nextNodes, edges: h.present.edges } };
    });
  }, []);

  const onEdgesChange = useCallback((changes: EdgeChange[]) => {
    const structural = changes.some((c) => c.type === "add" || c.type === "remove");
    setState((h) => {
      const nextEdges = applyEdgeChanges(changes, h.present.edges);
      if (nextEdges === h.present.edges) return h;
      return structural
        ? {
            past: pushPast(h.past, h.present),
            present: { nodes: h.present.nodes, edges: nextEdges },
            future: [],
          }
        : { ...h, present: { nodes: h.present.nodes, edges: nextEdges } };
    });
  }, []);

  const undo = useCallback(() => {
    setState((h) => {
      if (h.past.length === 0) return h;
      const prev = h.past[h.past.length - 1];
      return {
        past: h.past.slice(0, -1),
        present: prev,
        future: [h.present, ...h.future].slice(0, HISTORY_CAP),
      };
    });
  }, []);

  const redo = useCallback(() => {
    setState((h) => {
      if (h.future.length === 0) return h;
      const next = h.future[0];
      return {
        past: pushPast(h.past, h.present),
        present: next,
        future: h.future.slice(1),
      };
    });
  }, []);

  const reset = useCallback((presentSnap: GraphSnapshot<N>) => {
    setState({ past: [], present: presentSnap, future: [] });
  }, []);

  return {
    nodes: present.nodes,
    edges: present.edges,
    setNodes,
    setEdges,
    onNodesChange,
    onEdgesChange,
    replace,
    reset,
    canUndo,
    canRedo,
    undo,
    redo,
  };
}
