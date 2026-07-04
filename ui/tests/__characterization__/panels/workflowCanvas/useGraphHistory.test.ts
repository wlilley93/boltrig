import { describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";
import type { Edge, Node, NodeChange } from "@xyflow/react";
import { useGraphHistory } from "@/panels/workflowCanvas/useGraphHistory";

const node = (id: string): Node => ({ id, position: { x: 0, y: 0 }, data: {} });
const ids = (ns: Node[]) => ns.map((n) => n.id);
const emptyEdges: Edge[] = [];

describe("useGraphHistory", () => {
  it("starts with undo/redo disabled", () => {
    const { result } = renderHook(() =>
      useGraphHistory<Node>({ nodes: [], edges: emptyEdges }),
    );
    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(false);
    expect(result.current.nodes).toEqual([]);
  });

  it("records a structural setNodes change as one undo step", () => {
    const { result } = renderHook(() =>
      useGraphHistory<Node>({ nodes: [], edges: emptyEdges }),
    );
    act(() => result.current.setNodes([node("a")]));
    expect(ids(result.current.nodes)).toEqual(["a"]);
    expect(result.current.canUndo).toBe(true);
    expect(result.current.canRedo).toBe(false);
  });

  it("undo restores the previous snapshot", () => {
    const { result } = renderHook(() =>
      useGraphHistory<Node>({ nodes: [], edges: emptyEdges }),
    );
    act(() => result.current.setNodes([node("a")]));
    act(() => result.current.setNodes([node("a"), node("b")]));
    act(() => result.current.undo());
    expect(ids(result.current.nodes)).toEqual(["a"]);
    expect(result.current.canRedo).toBe(true);
  });

  it("redo reapplies the undone snapshot", () => {
    const { result } = renderHook(() =>
      useGraphHistory<Node>({ nodes: [], edges: emptyEdges }),
    );
    act(() => result.current.setNodes([node("a")]));
    act(() => result.current.setNodes([node("a"), node("b")]));
    act(() => result.current.undo());
    act(() => result.current.redo());
    expect(ids(result.current.nodes)).toEqual(["a", "b"]);
    expect(result.current.canRedo).toBe(false);
  });

  it("reset wipes history", () => {
    const { result } = renderHook(() =>
      useGraphHistory<Node>({ nodes: [], edges: emptyEdges }),
    );
    act(() => result.current.setNodes([node("a")]));
    act(() => result.current.reset({ nodes: [node("z")], edges: emptyEdges }));
    expect(ids(result.current.nodes)).toEqual(["z"]);
    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(false);
  });

  it("a no-op setNodes does not create history", () => {
    const { result } = renderHook(() =>
      useGraphHistory<Node>({ nodes: [node("a")], edges: emptyEdges }),
    );
    act(() => result.current.setNodes(result.current.nodes));
    expect(result.current.canUndo).toBe(false);
  });

  it("coalesces a position drag into a single undo step", () => {
    const { result } = renderHook(() =>
      useGraphHistory<Node>({ nodes: [node("a")], edges: emptyEdges }),
    );
    const move = (x: number, y: number): NodeChange<Node>[] => [
      { type: "position", id: "a", position: { x, y }, dragging: true },
    ];
    act(() => result.current.onNodesChange(move(5, 5)));
    act(() => result.current.onNodesChange(move(20, 20)));
    expect(result.current.nodes[0].position).toEqual({ x: 20, y: 20 });
    expect(result.current.canUndo).toBe(true);
    act(() => result.current.undo());
    expect(result.current.nodes[0].position).toEqual({ x: 0, y: 0 });
  });
});
