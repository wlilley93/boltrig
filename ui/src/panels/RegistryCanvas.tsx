// US-UI-05: the REGISTRY canvas, the visual Capability plane. A React Flow TREE
// (not a DAG) over the same caller-scoped /v1/capabilities read the RouterPanel
// list view uses. Three tiers laid out left-to-right:
//
//   col 0  noun nodes    (roots; one per noun, grouping its verbs)
//   col 1  verb nodes    (children of their noun; id + consequence badge + live
//                         adapter health when adapter-bound)
//   col 2  binding leaves (exactly one per verb; "adapter: <ref>" or
//                          "agent: <ref>", colour-keyed like the workflow canvas)
//
// It is a tree because a verb terminates in EXACTLY ONE binding: every verb node
// has a single binding child, and edges only ever point noun -> verb -> binding.
// v1 is read-only browse: pan / zoom / minimap and free node drag, no editing.
// Authz stays server-side: we render the verbs the scoped read returns and never
// pre-filter (the RouterPanel pattern). The build mirrors WorkflowCanvas's
// dependency-depth layout (tier = column, siblings stacked by a running row).

import { useEffect, useMemo, useRef } from "react";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
  type XYPosition,
} from "@xyflow/react";

import "@xyflow/react/dist/style.css";

import type { AdapterHealth, HealthResponse, VerbInfo } from "../api/types";
import { ConsequenceBadge, HealthBadge, resolveHealth } from "./RouterPanel";

// --- node data (object-literal types so they satisfy React Flow's
// Record<string, unknown> data constraint, mirroring WorkflowCanvas) ----------

type NounNodeData = {
  noun: string;
  count: number;
};

type VerbNodeData = {
  verbId: string;
  consequence?: string;
  // adapter-bound verbs carry live health; agent/unbound verbs do not.
  adapterBound: boolean;
  health: AdapterHealth;
  high: boolean;
};

// "service" matches the workflow canvas colour for an adapter-bound node;
// "agent" matches the agent colour. Keyed off the binding target_type.
type BindingKind = "agent" | "service";

type BindingNodeData = {
  kind: BindingKind;
  targetType: "adapter" | "agent";
  targetRef: string;
};

type NounNode = Node<NounNodeData, "noun">;
type VerbNode = Node<VerbNodeData, "verb">;
type BindingNode = Node<BindingNodeData, "binding">;
type RegNode = NounNode | VerbNode | BindingNode;

// --- custom node views ------------------------------------------------------

// Noun root: source handle on the right only (it never has a parent).
function NounNodeView({ data }: NodeProps) {
  const d = data as NounNodeData;
  return (
    <div className="wf-node reg-node--noun">
      <div className="wf-node__label">{d.noun}</div>
      <span className="muted">{d.count} verb(s)</span>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

// Verb: target handle (its noun) on the left, source (its binding) on the right.
// A high-consequence verb gets the reg-node--high border so "governed" access
// (e.g. web.fetch) reads as a first-class node, on top of the consequence badge.
function VerbNodeView({ data }: NodeProps) {
  const d = data as VerbNodeData;
  return (
    <div className={`wf-node reg-node--verb ${d.high ? "reg-node--high" : ""}`.trim()}>
      <Handle type="target" position={Position.Left} />
      <div className="wf-node__action">
        <code>{d.verbId}</code>
      </div>
      <div className="reg-node__meta">
        <ConsequenceBadge value={d.consequence} />
        {d.adapterBound && <HealthBadge health={d.health} />}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

// Binding leaf: target handle (its verb) on the left only. Colour-keyed by kind
// using the same wf-node--agent / wf-node--service classes as the studio canvas.
function BindingNodeView({ data }: NodeProps) {
  const d = data as BindingNodeData;
  return (
    <div className={`wf-node wf-node--${d.kind}`}>
      <Handle type="target" position={Position.Left} />
      <span className="badge wf-node__kind">{d.targetType}</span>
      <div className="wf-node__action">
        <code>{d.targetRef}</code>
      </div>
    </div>
  );
}

const nodeTypes: NodeTypes = {
  noun: NounNodeView,
  verb: VerbNodeView,
  binding: BindingNodeView,
};

// --- tree build (capabilities -> nodes + edges) -----------------------------

const COL_X = [40, 320, 620]; // noun / verb / binding columns
const ROW_H = 96; // vertical pitch between sibling verbs
const Y_BASE = 24;
const NOUN_GAP = 1; // blank rows inserted between noun groups

function isHigh(consequence?: string): boolean {
  return (consequence ?? "").toLowerCase() === "high";
}

function bindingKind(targetType: "adapter" | "agent"): BindingKind {
  return targetType === "agent" ? "agent" : "service";
}

// Group verbs by noun, then lay each noun out as a tree: the noun sits at col 0
// centred against its verbs, each verb at col 1, and that verb's single binding
// leaf at col 2 on the same row. A running row counter stacks siblings and a gap
// row separates nouns (mirrors WorkflowCanvas's per-level row stacking).
function buildTree(
  verbs: VerbInfo[],
  health: HealthResponse | null,
  tenant: string,
): { nodes: RegNode[]; edges: Edge[] } {
  const byNoun = new Map<string, VerbInfo[]>();
  for (const v of verbs) {
    const noun = v.noun || "(unspecified)";
    const bucket = byNoun.get(noun);
    if (bucket) bucket.push(v);
    else byNoun.set(noun, [v]);
  }
  const groups = [...byNoun.entries()].sort((a, b) => a[0].localeCompare(b[0]));

  const nodes: RegNode[] = [];
  const edges: Edge[] = [];
  let row = 0;

  for (const [noun, nounVerbs] of groups) {
    const sorted = nounVerbs.slice().sort((a, b) => a.id.localeCompare(b.id));
    const startRow = row;
    const nounId = `noun:${noun}`;

    // noun centred vertically against the rows its verbs occupy
    const centreRow = startRow + (sorted.length - 1) / 2;
    nodes.push({
      id: nounId,
      type: "noun",
      position: { x: COL_X[0], y: Y_BASE + centreRow * ROW_H },
      data: { noun, count: sorted.length },
    });

    for (const v of sorted) {
      const y = Y_BASE + row * ROW_H;
      const verbId = `verb:${v.id}`;
      const adapterBound = v.binding?.target_type === "adapter";
      nodes.push({
        id: verbId,
        type: "verb",
        position: { x: COL_X[1], y },
        data: {
          verbId: v.id,
          consequence: v.consequence,
          adapterBound,
          health: resolveHealth(v, health, tenant),
          high: isHigh(v.consequence),
        },
      });
      edges.push({ id: `${nounId}__${verbId}`, source: nounId, target: verbId });

      // exactly one binding leaf per verb (the tree invariant)
      if (v.binding) {
        const bindId = `binding:${v.id}`;
        nodes.push({
          id: bindId,
          type: "binding",
          position: { x: COL_X[2], y },
          data: {
            kind: bindingKind(v.binding.target_type),
            targetType: v.binding.target_type,
            targetRef: v.binding.target_ref,
          },
        });
        edges.push({ id: `${verbId}__${bindId}`, source: verbId, target: bindId });
      }

      row += 1;
    }
    row += NOUN_GAP;
  }

  return { nodes, edges };
}

// --- the canvas -------------------------------------------------------------

export function RegistryCanvas({
  verbs,
  health,
  tenant,
}: {
  verbs: VerbInfo[];
  health: HealthResponse | null;
  tenant: string;
}) {
  const built = useMemo(
    () => buildTree(verbs, health, tenant),
    [verbs, health, tenant],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState<RegNode>(built.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(built.edges);

  // Preserve any positions the user dragged to across rebuilds (a health poll
  // every 15s re-runs buildTree; we keep dragged nodes where they were put).
  const posRef = useRef<Map<string, XYPosition>>(new Map());
  useEffect(() => {
    setNodes(
      built.nodes.map((n) => {
        const saved = posRef.current.get(n.id);
        return saved ? { ...n, position: saved } : n;
      }),
    );
    setEdges(built.edges);
  }, [built, setNodes, setEdges]);

  if (verbs.length === 0) {
    return <p className="muted">No verbs visible for this identity.</p>;
  }

  return (
    <div className="wf-canvas">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeDragStop={(_e, node) =>
          posRef.current.set(node.id, node.position)
        }
        nodesConnectable={false}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background />
        <Controls />
        <MiniMap pannable zoomable />
      </ReactFlow>
    </div>
  );
}
