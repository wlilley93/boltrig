// Canvas view of the Workflow Studio. A React Flow graph where every node is one
// workflow step and every edge (source -> target) is a parent link. The canvas
// serialises to EXACTLY the definition.steps contract the backend interpreter
// runs (id / parents / action / params / description), so a graph built here is
// byte-for-byte the same shape as one typed into the form view.
//
// Round-trip (the two directions are inverse):
//   load  (stepsToGraph): each step becomes a "step" node; for every parent p of
//         step s we emit an edge p -> s. Layout lays steps out by dependency
//         depth so roots sit on the left.
//   save  (graphToSteps): each "step" node becomes a step; a step's `parents` is
//         the set of edge sources that target it (only edges BETWEEN step nodes
//         count). Steps come out in dependency order (parents before children).
//
// Node kind is derived purely from the chosen verb's binding (api.capabilities),
// never a hand-kept authority list: agent-bound -> "agent", adapter-bound ->
// "service", anything else -> "kernel-run" (the default). Trigger nodes (chat /
// cron / webhook) are visual entry markers only: they are EXCLUDED from the
// serialised steps. Authz stays server-side; we show the server's denial, we
// never pre-check (the AdminPanel pattern).

import { useEffect, useMemo, useRef, useState } from "react";
import {
  addEdge,
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react";

import "@xyflow/react/dist/style.css";

import { api } from "../api/client";
import type {
  StatusAck,
  VerbInfo,
  WorkflowRunRecord,
  WorkflowSourceValue,
  WorkflowSummary,
} from "../api/types";
import { useFetch } from "../useFetch";
import {
  CodeBlock,
  RunLink,
  csvToList,
  errText,
  listToCsv,
  parseJson,
  runBadgeClass,
  stepBadgeClass,
} from "./shared";
import { WorkflowRunCanvas } from "./WorkflowRunCanvas";
import { SchemaForm, Select } from "./ux";

// Parse the inspector params JSON into an object for the schema form (an
// in-progress edit may be invalid; the form just sees {} until valid again).
function safeObj(text: string): Record<string, unknown> {
  try {
    const v = JSON.parse(text || "{}");
    return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

// --- the data contract ------------------------------------------------------

// One step in definition.steps. The backend walks these parents-before-children
// and dispatches each `action` (a "noun.verb" id) through the kernel chokepoint.
export interface WorkflowStep {
  id: string;
  parents: string[];
  action: string;
  params?: Record<string, unknown>;
  description?: string;
}

type NodeKind = "agent" | "service" | "kernel-run";
type TriggerKind = "chat" | "cron" | "webhook";

// Per-node run state overlaid in run mode (WorkflowRunCanvas). "pending" is the
// default before any workflow_step event names the node; the rest mirror the
// interpreter's per-step status vocabulary.
export type RunNodeStatus =
  | "pending"
  | "running"
  | "ok"
  | "failed"
  | "error"
  | "skipped";

// Object-literal type aliases (not interfaces) so the node data satisfies React
// Flow's `Record<string, unknown>` data constraint. `runStatus` is unset in edit
// mode and set by the live canvas to colour the node by execution state.
export type StepNodeData = {
  action: string;
  params: Record<string, unknown>;
  kind: NodeKind;
  label: string;
  description?: string;
  consequence?: string; // "high" -> a marker foreshadowing the approval pause
  runStatus?: RunNodeStatus;
};

type TriggerNodeData = {
  triggerType: TriggerKind;
  label: string;
};

export type StepNode = Node<StepNodeData, "step">;
type TriggerNode = Node<TriggerNodeData, "trigger">;
export type CanvasNode = StepNode | TriggerNode;

// --- kind derivation (binding-driven, no authority list) --------------------

export function deriveKind(verb: VerbInfo | undefined): NodeKind {
  const target = verb?.binding?.target_type;
  if (target === "agent") return "agent";
  if (target === "adapter") return "service";
  return "kernel-run";
}

// --- custom nodes -----------------------------------------------------------

// A step: target handle on the left (incoming parent), source on the right. In
// run mode `runStatus` adds a wf-node--run-<status> modifier (and the running one
// pulses, honoured against prefers-reduced-motion in CSS).
function StepNodeView({ data, selected }: NodeProps) {
  const d = data as StepNodeData;
  const runClass = d.runStatus ? `wf-node--run-${d.runStatus}` : "";
  return (
    <div
      className={`wf-node wf-node--${d.kind} ${selected ? "wf-node--sel" : ""} ${runClass}`.trim()}
    >
      <Handle type="target" position={Position.Left} />
      {d.consequence === "high" && (
        <span
          className="wf-node__conseq"
          title="High consequence - this step may pause for human approval"
          aria-label="high consequence"
        >
          !
        </span>
      )}
      <div className="wf-node__top">
        <span className="wf-node__label">{d.label}</span>
        <span className="badge wf-node__kind">{d.kind}</span>
      </div>
      <div className="wf-node__action">
        <code>{d.action}</code>
      </div>
      {d.runStatus && <span className="badge wf-node__run">{d.runStatus}</span>}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

// A trigger: entry marker, source handle only (it never has parents).
function TriggerNodeView({ data }: NodeProps) {
  const d = data as TriggerNodeData;
  return (
    <div className="wf-node wf-node--trigger">
      <div className="wf-node__label">{d.label}</div>
      <span className="badge">{d.triggerType} trigger</span>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

export const nodeTypes: NodeTypes = { step: StepNodeView, trigger: TriggerNodeView };

// --- round-trip: graph <-> steps --------------------------------------------

function isStepNode(n: CanvasNode): n is StepNode {
  return n.type === "step";
}

// Order steps parents-before-children (Kahn). Falls back to insertion order if
// the graph has a cycle, so save never throws.
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

// Serialise: nodes + edges -> the exact definition.steps array.
function graphToSteps(nodes: CanvasNode[], edges: Edge[]): WorkflowStep[] {
  const stepNodes = nodes.filter(isStepNode);
  const stepIds = new Set(stepNodes.map((n) => n.id));
  const parentsById = new Map<string, string[]>();
  for (const n of stepNodes) parentsById.set(n.id, []);
  // Only edges between two step nodes are parent links; a trigger source is an
  // entry marker and contributes no parent.
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

// Load: definition.steps -> nodes + edges (inverse of graphToSteps). Lays steps
// out left-to-right by dependency depth.
export function stepsToGraph(
  steps: WorkflowStep[],
  verbsById: Map<string, VerbInfo>,
): { nodes: StepNode[]; edges: Edge[] } {
  const byId = new Map(steps.map((s) => [s.id, s]));

  const depthCache = new Map<string, number>();
  function depthOf(id: string, seen: Set<string>): number {
    const cached = depthCache.get(id);
    if (cached !== undefined) return cached;
    if (seen.has(id)) return 0; // cycle guard
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

// Accept a pasted array of steps, a {steps:[...]} object, or a full
// {definition:{steps:[...]}} workflow, returning the steps array or null.
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

// --- the canvas -------------------------------------------------------------

export function WorkflowCanvas() {
  const workflows = useFetch(() => api.workflows(), []);
  const caps = useFetch(() => api.capabilities(), []);

  const [nodes, setNodes, onNodesChange] = useNodesState<CanvasNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  // workflow metadata (Save target / Run target)
  const [wfId, setWfId] = useState("");
  const [version, setVersion] = useState("1.0.0");
  const [source, setSource] = useState<WorkflowSourceValue>("precreated");
  const [tags, setTags] = useState("");

  const [selectedId, setSelectedId] = useState<string | null>(null);

  // selected-node inspector fields (synced from the node on selection change)
  const [editId, setEditId] = useState("");
  const [editParams, setEditParams] = useState("{}");
  const [editDesc, setEditDesc] = useState("");
  const [paletteFilter, setPaletteFilter] = useState("");
  const [editError, setEditError] = useState<string | null>(null);

  const [loadText, setLoadText] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);

  const [saveBusy, setSaveBusy] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [ack, setAck] = useState<StatusAck | null>(null);

  const [runBusy, setRunBusy] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [runResult, setRunResult] = useState<WorkflowRunRecord | null>(null);

  // When set, the canvas switches to the read-only live run view (the graph
  // lighting up). Either Run sets it (to the fresh run_id) or the "view run"
  // control opens an existing run for the current workflow id.
  const [runView, setRunView] = useState<{ runId: string; wfId: string } | null>(
    null,
  );
  const [viewRunId, setViewRunId] = useState("");

  const counter = useRef(0);

  const verbs: VerbInfo[] = useMemo(() => caps.data?.verbs ?? [], [caps.data]);
  const verbsById = useMemo(
    () => new Map(verbs.map((v) => [v.id, v])),
    [verbs],
  );

  const selectedNode = nodes.find(
    (n): n is StepNode => n.id === selectedId && isStepNode(n),
  );

  // Sync the inspector inputs whenever the selected step changes.
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
    // Only re-sync when the selection (or its identity) changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  function uniqueStepId(verb: VerbInfo): string {
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

  function addVerbNode(verb: VerbInfo) {
    const id = uniqueStepId(verb);
    const index = nodes.filter(isStepNode).length;
    const node: StepNode = {
      id,
      type: "step",
      position: { x: 60 + (index % 3) * 60, y: 60 + index * 70 },
      data: {
        action: verb.id,
        params: {},
        kind: deriveKind(verb),
        label: id,
        consequence: verb.consequence,
      },
    };
    setNodes((ns) => [...ns, node]);
    setSelectedId(id);
  }

  function addTrigger(triggerType: TriggerKind) {
    counter.current += 1;
    const id = `trigger_${triggerType}_${counter.current}`;
    const index = nodes.filter((n) => n.type === "trigger").length;
    const node: TriggerNode = {
      id,
      type: "trigger",
      position: { x: -200, y: 60 + index * 90 },
      data: { triggerType, label: `${triggerType} entry` },
    };
    setNodes((ns) => [...ns, node]);
  }

  function onConnect(connection: Connection) {
    setEdges((es) => addEdge(connection, es));
  }

  function onNodeClick(_event: React.MouseEvent, node: CanvasNode) {
    setSelectedId(node.type === "step" ? node.id : null);
  }

  // Inspector: apply the edited params JSON to the selected step.
  // Inspector: rewire the selected step to a different verb in place (re-derives
  // kind + consequence from the new verb's binding).
  function swapVerb(verbId: string) {
    if (!selectedNode || !verbId) return;
    const v = verbsById.get(verbId);
    if (!v) return;
    const id = selectedNode.id;
    setNodes((ns) =>
      ns.map((n) =>
        n.id === id && isStepNode(n)
          ? { ...n, data: { ...n.data, action: v.id, kind: deriveKind(v), consequence: v.consequence } }
          : n,
      ),
    );
  }

  function applyParams() {
    if (!selectedNode) return;
    let parsed: Record<string, unknown>;
    try {
      parsed = parseJson<Record<string, unknown>>(editParams, {});
    } catch (err) {
      setEditError(`params: ${errText(err)}`);
      return;
    }
    setEditError(null);
    const id = selectedNode.id;
    setNodes((ns) =>
      ns.map((n) =>
        n.id === id && isStepNode(n)
          ? { ...n, data: { ...n.data, params: parsed, description: editDesc.trim() || undefined } }
          : n,
      ),
    );
  }

  // Inspector: rename the selected step id (and re-point its edges).
  function renameStep() {
    if (!selectedNode) return;
    const oldId = selectedNode.id;
    const newId = editId.trim();
    if (!newId || newId === oldId) return;
    if (nodes.some((n) => n.id === newId)) {
      setEditError("a node with that id already exists");
      return;
    }
    setEditError(null);
    setNodes((ns) =>
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
    setEdges((es) =>
      es.map((e) => ({
        ...e,
        source: e.source === oldId ? newId : e.source,
        target: e.target === oldId ? newId : e.target,
      })),
    );
    setSelectedId(newId);
  }

  function deleteSelected() {
    if (!selectedId) return;
    const id = selectedId;
    setNodes((ns) => ns.filter((n) => n.id !== id));
    setEdges((es) => es.filter((e) => e.source !== id && e.target !== id));
    setSelectedId(null);
  }

  function clearCanvas() {
    setNodes([]);
    setEdges([]);
    setSelectedId(null);
  }

  // Pick a workflow from the list: populate the Save/Run metadata and load its
  // stored steps onto the canvas via the governed GET /v1/workflows/{id} read.
  async function pickWorkflow(w: WorkflowSummary) {
    setWfId(w.id);
    setVersion(w.version || "1.0.0");
    setSource((w.source as WorkflowSourceValue) || "precreated");
    setTags(listToCsv(w.intent_tags));
    setLoadError(null);
    try {
      const detail = await api.getWorkflow(w.id);
      const steps = extractSteps(detail.definition) ?? [];
      const graph = stepsToGraph(steps, verbsById);
      setNodes(graph.nodes);
      setEdges(graph.edges);
      setSelectedId(null);
    } catch (err) {
      setLoadError(`load '${w.id}': ${errText(err)}`);
    }
  }

  function loadFromJson() {
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
    const graph = stepsToGraph(steps, verbsById);
    setNodes(graph.nodes);
    setEdges(graph.edges);
    setSelectedId(null);
  }

  async function save() {
    const id = wfId.trim();
    if (!id) {
      setSaveError("Workflow id is required.");
      return;
    }
    setSaveBusy(true);
    setSaveError(null);
    setAck(null);
    try {
      const steps = graphToSteps(nodes, edges);
      const res = await api.upsertWorkflow({
        id,
        version: version.trim() || "1.0.0",
        source,
        definition: { steps },
        intent_tags: csvToList(tags),
      });
      setAck(res);
      if (res.status === "ok") workflows.reload();
    } catch (err) {
      setSaveError(errText(err));
    } finally {
      setSaveBusy(false);
    }
  }

  async function run() {
    const id = wfId.trim();
    if (!id) {
      setRunError("Workflow id is required.");
      return;
    }
    setRunBusy(true);
    setRunError(null);
    setRunResult(null);
    try {
      const record = await api.executeWorkflow(id, {});
      setRunResult(record);
      // Open the live canvas on the new run; follow:true replays the steps it
      // just walked so the graph still lights up after a synchronous execute.
      if (record.run_id) setRunView({ runId: record.run_id, wfId: id });
    } catch (err) {
      setRunError(errText(err));
    } finally {
      setRunBusy(false);
    }
  }

  // Open the live run canvas for an already-existing run of the current workflow.
  function openRunCanvas() {
    const id = wfId.trim();
    const rid = viewRunId.trim();
    if (!id || !rid) {
      setRunError("Workflow id and run id are required to view a run.");
      return;
    }
    setRunError(null);
    setRunView({ runId: rid, wfId: id });
  }

  const list: WorkflowSummary[] = workflows.data?.workflows ?? [];
  // Live preview of the exact steps shape that Save will send.
  const previewSteps = useMemo(
    () => graphToSteps(nodes, edges),
    [nodes, edges],
  );

  // Run mode takes over the canvas: the read-only graph lighting up live.
  if (runView) {
    return (
      <WorkflowRunCanvas
        runId={runView.runId}
        wfId={runView.wfId}
        onBack={() => setRunView(null)}
      />
    );
  }

  return (
    <div className="wf-studio">
      <div className="stack">
        <div className="form">
          <div className="form__title">Workflow</div>
          <div className="form__grid">
            <label className="field">
              <span>id</span>
              <input value={wfId} onChange={(e) => setWfId(e.target.value)} />
            </label>
            <label className="field">
              <span>version</span>
              <input
                value={version}
                onChange={(e) => setVersion(e.target.value)}
              />
            </label>
            <label className="field">
              <span>source</span>
              <select
                value={source}
                onChange={(e) =>
                  setSource(e.target.value as WorkflowSourceValue)
                }
              >
                <option value="precreated">precreated</option>
                <option value="generated">generated</option>
                <option value="learned">learned</option>
              </select>
            </label>
          </div>
          <label className="field">
            <span>intent_tags (comma list)</span>
            <input value={tags} onChange={(e) => setTags(e.target.value)} />
          </label>
          <div className="form__actions">
            <button
              className="btn btn--primary"
              disabled={saveBusy}
              onClick={save}
            >
              {saveBusy ? "..." : "Save"}
            </button>
            <button className="btn" disabled={runBusy} onClick={run}>
              {runBusy ? "..." : "Run"}
            </button>
            <button className="btn btn--ghost" onClick={clearCanvas}>
              Clear
            </button>
          </div>
          {ack &&
            (ack.status === "ok" ? (
              <p className="ok">
                Saved {[ack.id, ack.version ? `v${ack.version}` : null]
                  .filter(Boolean)
                  .join(" ") || "ok"}
                .
              </p>
            ) : (
              <p className="error">
                {ack.status}: {ack.reason ?? "request rejected"}
              </p>
            ))}
          {saveError && <p className="error">{saveError}</p>}
          {runError && <p className="error">{runError}</p>}
          <div className="kv">
            <input
              placeholder="existing run id"
              value={viewRunId}
              onChange={(e) => setViewRunId(e.target.value)}
            />
            <button className="btn" onClick={openRunCanvas}>
              View run
            </button>
          </div>
        </div>

        <div className="form">
          <div className="form__title">Verb palette</div>
          <p className="muted">
            Scoped to this identity. Click a verb to drop a step node; its kind is
            derived from the verb binding. Drag handle to handle to add a parent
            link.
          </p>
          {caps.loading && !caps.data && <p className="muted">Loading...</p>}
          {caps.error && <p className="error">Failed to load: {caps.error}</p>}
          {!caps.loading && !caps.error && verbs.length === 0 && (
            <p className="muted">No verbs visible for this identity.</p>
          )}
          {verbs.length > 6 && (
            <input
              className="wf-palette__search"
              placeholder="Search actions..."
              value={paletteFilter}
              onChange={(e) => setPaletteFilter(e.target.value)}
              aria-label="Search actions"
            />
          )}
          <div className="wf-palette">
            {verbs
              .filter((v) => {
                const q = paletteFilter.trim().toLowerCase();
                return !q || v.id.toLowerCase().includes(q) || v.noun.toLowerCase().includes(q);
              })
              .map((v) => (
                <button
                  className="row-line palette-row"
                  key={v.id}
                  onClick={() => addVerbNode(v)}
                  title="Add as a step node"
                >
                  <div className="kv">
                    <code>{v.id}</code>
                    {v.consequence === "high" && (
                      <span className="badge badge--conseq-high">high</span>
                    )}
                  </div>
                  <span className="badge">{deriveKind(v)}</span>
                </button>
              ))}
          </div>
        </div>

        <div className="form">
          <div className="form__title">Triggers (entry markers)</div>
          <p className="muted">
            Visual entry points only. They are not steps and are excluded from the
            saved definition.
          </p>
          <div className="kv">
            <button className="btn" onClick={() => addTrigger("chat")}>
              + chat
            </button>
            <button className="btn" onClick={() => addTrigger("cron")}>
              + cron
            </button>
            <button className="btn" onClick={() => addTrigger("webhook")}>
              + webhook
            </button>
          </div>
        </div>

        <div className="list-card">
          <div className="list-card__head">
            <h3>Workflows</h3>
            <button className="btn" onClick={() => workflows.reload()}>
              Refresh
            </button>
          </div>
          <div className="list-card__body">
            {workflows.loading && !workflows.data && (
              <p className="muted">Loading...</p>
            )}
            {workflows.error && (
              <p className="error">Failed to load: {workflows.error}</p>
            )}
            {!workflows.loading && list.length === 0 && (
              <p className="muted">No workflows yet.</p>
            )}
            {list.map((w) => (
              <button
                className="row-line palette-row"
                key={`${w.id}@${w.version}`}
                onClick={() => pickWorkflow(w)}
                title="Use as the Save / Run target"
              >
                <div>
                  <code>{w.id}</code>{" "}
                  <span className="muted">v{w.version}</span>
                </div>
                <span className="badge">{w.source}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="form">
          <div className="form__title">Load definition (JSON)</div>
          <p className="muted">
            Paste a steps array or a {"{steps:[...]}"} object to render it on the
            canvas (the inverse of Save).
          </p>
          <textarea
            className="code"
            value={loadText}
            onChange={(e) => setLoadText(e.target.value)}
          />
          <div className="form__actions">
            <button className="btn" onClick={loadFromJson}>
              Load onto canvas
            </button>
            {loadError && <span className="error">{loadError}</span>}
          </div>
        </div>
      </div>

      <div className="stack">
        <div className="wf-canvas">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background />
            <Controls />
            <MiniMap pannable zoomable />
          </ReactFlow>
        </div>

        {selectedNode ? (
          <div className="form">
            <div className="form__title">Step inspector</div>
            <div className="form__grid">
              <label className="field">
                <span>id</span>
                <input
                  value={editId}
                  onChange={(e) => setEditId(e.target.value)}
                />
              </label>
              <label className="field">
                <span>action (verb)</span>
                <Select
                  value={selectedNode.data.action}
                  ariaLabel="Action verb"
                  onChange={swapVerb}
                  options={verbs.map((v) => ({ value: v.id, label: v.id }))}
                />
              </label>
              <label className="field">
                <span>kind</span>
                <input value={selectedNode.data.kind} readOnly />
              </label>
            </div>
            <label className="field">
              <span>description</span>
              <input
                value={editDesc}
                onChange={(e) => setEditDesc(e.target.value)}
              />
            </label>
            {(() => {
              const sv = verbsById.get(selectedNode.data.action);
              const props = (sv?.input_schema as { properties?: object } | undefined)?.properties;
              const hasSchema = props && Object.keys(props).length > 0;
              return hasSchema ? (
                <>
                  <span className="field"><span>parameters</span></span>
                  <SchemaForm
                    schema={sv!.input_schema}
                    value={safeObj(editParams)}
                    onChange={(o) => setEditParams(JSON.stringify(o, null, 2))}
                  />
                  <details>
                    <summary className="ux-hint" style={{ cursor: "pointer" }}>
                      Edit as JSON
                    </summary>
                    <textarea
                      className="code"
                      value={editParams}
                      onChange={(e) => setEditParams(e.target.value)}
                    />
                  </details>
                </>
              ) : (
                <label className="field">
                  <span>params (JSON)</span>
                  <textarea
                    className="code"
                    value={editParams}
                    onChange={(e) => setEditParams(e.target.value)}
                  />
                </label>
              );
            })()}
            <div className="form__actions">
              <button className="btn btn--primary" onClick={applyParams}>
                Apply
              </button>
              <button className="btn" onClick={renameStep}>
                Rename id
              </button>
              <button className="btn btn--ghost" onClick={deleteSelected}>
                Delete
              </button>
              {editError && <span className="error">{editError}</span>}
            </div>
          </div>
        ) : (
          <div className="form">
            <div className="form__title">Step inspector</div>
            <p className="muted">Select a step node to edit its id and params.</p>
          </div>
        )}

        <div className="form">
          <div className="form__title">Serialised steps (preview)</div>
          <p className="muted">
            The exact definition.steps Save will send. Parents are derived from
            the incoming edges of each step.
          </p>
          <CodeBlock value={previewSteps} />
        </div>

        {runResult && (
          <div className="form">
            <div className="form__title">Run record</div>
            <div className="kv">
              <span className={`badge ${runBadgeClass(runResult.status)}`}>
                {runResult.status}
              </span>
              <RunLink runId={runResult.run_id} />
              <span className="muted">
                {runResult.workflow_id} v{runResult.version}
              </span>
            </div>
            {runResult.steps.length === 0 ? (
              <p className="muted">No steps.</p>
            ) : (
              <ul className="verb-list">
                {runResult.steps.map((s, i) => (
                  <li className="verb-row" key={`${s.id}-${i}`}>
                    <div className="verb-row__main">
                      <code className="verb-row__id">{s.id}</code>
                      {s.action && <span className="muted">{s.action}</span>}
                      <span className={`badge ${stepBadgeClass(s.status)}`}>
                        {s.status}
                      </span>
                    </div>
                    {s.reason && (
                      <div className="verb-row__meta">
                        <span className="muted">reason: {s.reason}</span>
                      </div>
                    )}
                    {s.output !== undefined && <CodeBlock value={s.output} />}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
