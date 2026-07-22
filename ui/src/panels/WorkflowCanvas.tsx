// Canvas view of the Workflow Studio. Thin orchestrator: state and helpers
// live in the workflowCanvas/ submodule; this file composes the v3 canvas view
// (design brief sec 22.2-22.10) and re-exports the public API.
//
// Wave 2 adds the editor header (sec 22.2: back / name / version / undo-redo /
// step count / high-consequence / Save / Run) in place of the old MetaForm, and
// an optional onBack so AutomationsSlide can drop its own back bar.

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
import { PendingHumanCard } from "@/panels/uxFlow/pendingHumanCard";
import { EditorHeader } from "./workflowCanvas/EditorHeader";
import { useWorkflowCanvas } from "./workflowCanvas/useWorkflowCanvas";
import { nodeTypes } from "./workflowCanvas/nodes";
import { edgeTypes } from "./workflowCanvas/edges";
import { DockToolbar } from "./workflowCanvas/DockToolbar";
import { NodeDrawer, DRAWER_DRAG_KIND } from "./workflowCanvas/NodeDrawer";
import { NodeDetailModal } from "./workflowCanvas/NodeDetailModal";
import { ExecutionConsole } from "./workflowCanvas/ExecutionConsole";
import { BoltChatPanel } from "./workflowCanvas/BoltChatPanel";
import { StickyNotes } from "./workflowCanvas/StickyNotes";
import { useStickyNotes } from "./workflowCanvas/useStickyNotes";
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

export function WorkflowCanvas({
  routeWfId,
  onBack,
}: {
  routeWfId?: string;
  onBack?: () => void;
}) {
  const ctx = useWorkflowCanvas(routeWfId);
  const pendingRun = ctx.apiActions.runMutation.pending;
  const pendingRunCard = pendingRun ? (
    <PendingHumanCard
      hitlRequestId={pendingRun.id}
      noun="control"
      verb="control.workflow.execute"
      sentParams={pendingRun.params}
      invocationContext={pendingRun.context}
      onApplied={ctx.apiActions.runMutation.onPendingApplied}
      onDenied={ctx.apiActions.runMutation.onPendingDenied}
      onReset={ctx.apiActions.runMutation.resetPending}
    />
  ) : null;

  if (ctx.meta.runView) {
    return (
      <div className="stack">
        {pendingRunCard}
        <WorkflowRunCanvas
          runId={ctx.meta.runView.runId}
          wfId={ctx.meta.runView.wfId}
          onBack={() => ctx.meta.setRunView(null)}
        />
      </div>
    );
  }

  return (
    <div className="wf-studio wf-studio--v3">
      <EditorHeader
        meta={{
          ...ctx.meta,
          runBusy: ctx.apiActions.runMutation.busy,
          runError: ctx.meta.runError ?? ctx.apiActions.runMutation.error,
        }}
        graph={ctx.graph}
        api={ctx.apiActions}
        onBack={onBack}
        canUndo={ctx.graph.canUndo}
        canRedo={ctx.graph.canRedo}
        onUndo={ctx.graph.undo}
        onRedo={ctx.graph.redo}
      />
      {pendingRunCard}
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
  const [notes, setNotes] = useStickyNotes(meta.wfId);

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
          color="var(--dot-color)"
          gap={24}
          size={2}
        />
      </ReactFlow>

      <NodeDrawer
        open={drawerOpen}
        onAdd={addAtCentre}
        onClose={() => setDrawerOpen(false)}
        verbsById={data.verbsById}
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
      <BoltChatPanel
        open={boltOpen}
        onToggle={() => setBoltOpen((v) => !v)}
        workflowId={meta.wfId}
        steps={graph.previewSteps}
      />
      <StickyNotes notes={notes} onChange={setNotes} />
    </div>
  );
}
