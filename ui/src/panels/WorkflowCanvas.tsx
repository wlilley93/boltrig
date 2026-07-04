// Canvas view of the Workflow Studio. Thin orchestrator: state and helpers
// live in the workflowCanvas/ submodule; this file composes the v3 canvas view
// (design brief sec 22.2-22.10) and re-exports the public API.
//
// Wave 1 scope: the canvas interior only. The home cards (22.1) and the editor
// header bar are handled in a separate wave, so MetaForm (Save/Run/name) is kept
// as-is for functional Save/Run access until the header lands.

import {
  Background,
  BackgroundVariant,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useState } from "react";
import { WorkflowRunCanvas } from "@/panels/WorkflowRunCanvas";
import { MetaForm } from "./workflowCanvas/MetaForm";
import { useWorkflowCanvas } from "./workflowCanvas/useWorkflowCanvas";
import { nodeTypes } from "./workflowCanvas/nodes";
import { edgeTypes } from "./workflowCanvas/edges";
import { DockToolbar } from "./workflowCanvas/DockToolbar";
import { NodeDrawer, DRAWER_DRAG_KIND } from "./workflowCanvas/NodeDrawer";
import { NodeDetailModal } from "./workflowCanvas/NodeDetailModal";
import { ExecutionConsole } from "./workflowCanvas/ExecutionConsole";
import { BoltChatPanel } from "./workflowCanvas/BoltChatPanel";
import { StickyNotes, type StickyNote } from "./workflowCanvas/StickyNotes";
import type { NodeVisualKind } from "./workflowCanvas/nodeTaxonomy";
import type { XYPosition } from "@xyflow/react";

export type {
  WorkflowStep,
  CanvasNode,
  StepNode,
  StepNodeData,
  RunNodeStatus,
} from "./workflowCanvas/types";
export { deriveKind, extractSteps, stepsToGraph } from "./workflowCanvas/graph";
export { nodeTypes } from "./workflowCanvas/nodes";

export function WorkflowCanvas({ routeWfId }: { routeWfId?: string }) {
  const ctx = useWorkflowCanvas(routeWfId);

  if (ctx.meta.runView) {
    return (
      <WorkflowRunCanvas
        runId={ctx.meta.runView.runId}
        wfId={ctx.meta.runView.wfId}
        onBack={() => ctx.meta.setRunView(null)}
      />
    );
  }

  return (
    <div className="wf-studio wf-studio--v3">
      <MetaForm
        meta={ctx.meta}
        api={ctx.apiActions}
        clearCanvas={ctx.graph.clearCanvas}
      />
      <ReactFlowProvider>
        <CanvasSurface ctx={ctx} />
      </ReactFlowProvider>
    </div>
  );
}

type Ctx = ReturnType<typeof useWorkflowCanvas>;

function CanvasSurface({ ctx }: { ctx: Ctx }) {
  const { data, meta, graph, inspector, onNodeClick } = ctx;
  const rf = useReactFlow();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [consoleOpen, setConsoleOpen] = useState(false);
  const [boltOpen, setBoltOpen] = useState(false);
  const [notes, setNotes] = useState<StickyNote[]>([]);

  const addAtCentre = (kind: NodeVisualKind) => {
    const centre = rf.screenToFlowPosition({
      x: window.innerWidth / 2,
      y: window.innerHeight / 2,
    });
    graph.addNodeKind(kind, centre);
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const kind = e.dataTransfer.getData(DRAWER_DRAG_KIND) as NodeVisualKind;
    if (!kind) return;
    const pos: XYPosition = rf.screenToFlowPosition({ x: e.clientX, y: e.clientY });
    graph.addNodeKind(kind, pos);
  };

  const closeModal = () => {
    if (inspector.dirty()) inspector.commit();
    graph.setSelectedId(null);
  };

  return (
    <div className="wf3-canvas-wrap" onDrop={onDrop} onDragOver={(e) => e.preventDefault()}>
      <ReactFlow
        nodes={graph.nodes}
        edges={graph.edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={graph.onNodesChange}
        onEdgesChange={graph.onEdgesChange}
        onConnect={graph.onConnect}
        onNodeClick={onNodeClick}
        minZoom={0.3}
        maxZoom={2}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          color="rgba(61,211,240,0.08)"
          gap={24}
          size={2}
        />
      </ReactFlow>

      <NodeDrawer
        open={drawerOpen}
        onAdd={addAtCentre}
        onClose={() => setDrawerOpen(false)}
      />
      <DockToolbar
        drawerOpen={drawerOpen}
        onToggleDrawer={() => setDrawerOpen((v) => !v)}
        consoleOpen={consoleOpen}
        onToggleConsole={() => setConsoleOpen((v) => !v)}
      />
      <NodeDetailModal
        selectedNode={graph.selectedNode}
        verbs={data.verbs}
        verbsById={data.verbsById}
        inspector={inspector}
        onSwap={inspector.swapVerb}
        onRename={inspector.renameStep}
        onDelete={graph.deleteSelected}
        onClose={closeModal}
      />
      <ExecutionConsole
        open={consoleOpen}
        onClose={() => setConsoleOpen(false)}
        runResult={meta.runResult}
      />
      <BoltChatPanel open={boltOpen} onToggle={() => setBoltOpen((v) => !v)} />
      <StickyNotes notes={notes} onChange={setNotes} />
    </div>
  );
}
