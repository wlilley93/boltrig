import { useCallback, useState } from "react";
import {
  addEdge,
  Background,
  BackgroundVariant,
  Controls,
  type Connection,
  type Edge,
  Handle,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { usePrototype } from "../PrototypeContext";
import { Icon } from "../PrototypeIcons";

type FlowData = { label: string; description: string; kind: string; status?: string };

const initialNodes: Node<FlowData>[] = [
  { id: "schedule", type: "boltrig", position: { x: 20, y: 190 }, data: { label: "Every Monday", description: "09:00 · Europe/London", kind: "trigger", status: "done" } },
  { id: "feedback", type: "boltrig", position: { x: 250, y: 90 }, data: { label: "Fetch feedback", description: "customer.feedback.list", kind: "capability", status: "done" } },
  { id: "spawn", type: "boltrig", position: { x: 250, y: 290 }, data: { label: "Spawn researchers", description: "Up to 3 Tier 3 workers", kind: "agent", status: "done" } },
  { id: "merge", type: "boltrig", position: { x: 500, y: 190 }, data: { label: "Merge findings", description: "12 evidence items", kind: "logic", status: "running" } },
  { id: "confidence", type: "boltrig", position: { x: 735, y: 190 }, data: { label: "Confidence ≥ 0.8", description: "Branch on evidence score", kind: "logic" } },
  { id: "approval", type: "boltrig", position: { x: 970, y: 90 }, data: { label: "Human approval", description: "Publication gate", kind: "human" } },
  { id: "publish", type: "boltrig", position: { x: 1200, y: 90 }, data: { label: "Publish digest", description: "memory.remember", kind: "capability" } },
  { id: "notify", type: "boltrig", position: { x: 1200, y: 290 }, data: { label: "Notify Operations", description: "channel.send", kind: "capability" } },
];

const initialEdges: Edge[] = [
  { id: "e1", source: "schedule", target: "feedback" }, { id: "e2", source: "schedule", target: "spawn" }, { id: "e3", source: "feedback", target: "merge" }, { id: "e4", source: "spawn", target: "merge" }, { id: "e5", source: "merge", target: "confidence" }, { id: "e6", source: "confidence", target: "approval", label: "yes" }, { id: "e7", source: "approval", target: "publish" }, { id: "e8", source: "confidence", target: "notify", label: "no" },
];

function FlowNode({ id, data, selected }: NodeProps<Node<FlowData>>) {
  return <div className={`proto-flow-node proto-flow-node--${data.kind} ${selected ? "is-selected" : ""} ${data.status ? `is-${data.status}` : ""}`}>
    <Handle type="target" position={Position.Left} />
    <span className="proto-flow-node__kind">{data.kind === "agent" ? <Icon name="spark" size={13} /> : data.kind}</span>
    <strong>{data.label}</strong><small>{data.description}</small>
    {data.status && <em>{data.status}</em>}
    <Handle type="source" position={Position.Right} />
    <span className="sr-only">Node {id}</span>
  </div>;
}

const nodeTypes = { boltrig: FlowNode };

export function AutomationsScreen() {
  const { select, notify, published, publish } = usePrototype();
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [diffOpen, setDiffOpen] = useState(false);
  const onConnect = useCallback((connection: Connection) => setEdges((current) => addEdge(connection, current)), [setEdges]);

  const addWaitNode = () => {
    setNodes((current) => [...current, { id: `wait-${current.length}`, type: "boltrig", position: { x: 970, y: 330 }, data: { label: "Wait for review", description: "Timeout after 24 hours", kind: "human" } }]);
    setPaletteOpen(false);
    notify("Wait node added to the draft");
  };

  const runDraft = () => {
    setNodes((current) => current.map((node, index) => ({ ...node, data: { ...node.data, status: index < 4 ? "done" : index === 4 ? "running" : undefined } })));
    notify("Draft run started with pinned evidence data");
  };

  return (
    <section className="proto-automation">
      <header className="proto-automation__toolbar">
        <div><p className="proto-eyebrow">Automation · Draft v8</p><h1>Weekly customer evidence digest</h1></div>
        <div className="proto-automation__state"><span><i />Saved</span><button className="proto-button proto-button--secondary" onClick={() => setDiffOpen(true)}>View changes</button><button className="proto-button proto-button--secondary" onClick={runDraft}><Icon name="play" size={15} />Test workflow</button><button className="proto-button proto-button--primary" onClick={publish}>{published ? "Published v8" : "Publish"}</button></div>
      </header>
      <div className="proto-canvas-wrap">
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} fitView minZoom={0.45} maxZoom={1.4} onNodeClick={(_, node) => select({ kind: "node", id: node.data.label })}>
          <Background variant={BackgroundVariant.Dots} gap={18} size={1} />
          <Controls showInteractive={false} />
        </ReactFlow>
        <button className="proto-add-node" onClick={() => setPaletteOpen((open) => !open)}><Icon name="plus" size={16} />Add node</button>
        {paletteOpen && <div className="proto-node-palette"><header><span>Node catalogue</span><button onClick={() => setPaletteOpen(false)}>×</button></header><label className="proto-search"><Icon name="search" size={14} /><input autoFocus placeholder="Search nodes" /></label>{[
          ["Agents", "Delegate to Tier 2", "Stable ownership and durable context"], ["Agents", "Spawn Tier 3 worker", "Bounded ephemeral execution"], ["Logic", "Wait for event", "Pause durably and resume once"], ["Human control", "Human approval", "Require an explicit decision"], ["Capability", "Invoke a verb", "Use a discovered governed capability"],
        ].map(([kind, label, desc]) => <button key={label} onClick={label === "Wait for event" ? addWaitNode : () => notify(`${label} selected from the catalogue`)}><i>{kind}</i><span>{label}<small>{desc}</small></span><b>＋</b></button>)}</div>}
        <div className="proto-canvas-legend"><span><i className="is-trigger" />Trigger</span><span><i className="is-agent" />Agent</span><span><i className="is-human" />Human</span><span><i className="is-capability" />Capability</span></div>
      </div>
      {diffOpen && <div className="proto-modal-backdrop"><div className="proto-modal proto-modal--diff"><p className="proto-eyebrow">Publish review</p><h2>Changes in revision 8</h2><div className="proto-diff-row"><span>+</span><div><strong>Spawn researchers</strong><small>Adds up to three scoped Tier 3 workers</small></div><b>New delegation</b></div><div className="proto-diff-row"><span>~</span><div><strong>Human approval</strong><small>Publication now pauses before external delivery</small></div><b>Higher safety</b></div><div className="proto-diff-row"><span>~</span><div><strong>Weekly schedule</strong><small>Monday at 09:00 Europe/London</small></div><b>Trigger changed</b></div><div className="proto-callout"><Icon name="approval" /><span><b>Capability review</b>No new credentials. One new delegated runtime and one high-consequence approval gate.</span></div><div className="proto-modal__actions"><button className="proto-button proto-button--secondary" onClick={() => setDiffOpen(false)}>Keep editing</button><button className="proto-button proto-button--primary" onClick={() => { publish(); setDiffOpen(false); }}>Publish revision 8</button></div></div></div>}
    </section>
  );
}
