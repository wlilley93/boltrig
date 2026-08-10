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
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useState } from "react";
import { WorkflowRunCanvas } from "@/panels/WorkflowRunCanvas";
import { PendingHumanCard } from "@/panels/uxFlow/pendingHumanCard";
import { EditorHeader } from "./workflowCanvas/EditorHeader";
import { useWorkflowCanvas } from "./workflowCanvas/useWorkflowCanvas";
import { nodeTypes } from "./workflowCanvas/nodes";
import { edgeTypes } from "./workflowCanvas/edges";
import { NodeDetailModal } from "./workflowCanvas/NodeDetailModal";
import { ExecutionConsole } from "./workflowCanvas/ExecutionConsole";
import { BoltChatPanel } from "./workflowCanvas/BoltChatPanel";
import { StickyNotes } from "./workflowCanvas/StickyNotes";
import { useStickyNotes } from "./workflowCanvas/useStickyNotes";
import { useStudioChat } from "./workflowCanvas/useStudioChat";
import { stepsToGraph } from "./workflowCanvas/graph";
import { diffSteps } from "./workflowCanvas/workflowDiff";
import type { WorkflowStep } from "./workflowCanvas/types";

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
        readOnly
      />
      {pendingRunCard}
      <ReactFlowProvider>
        <CanvasSurface ctx={ctx} />
      </ReactFlowProvider>
    </div>
  );
}

type Ctx = ReturnType<typeof useWorkflowCanvas>;

// Chat-first authoring (design pivot): the canvas is a READ-ONLY projection of
// the stored definition. No node drawer, no drag-drop, no connect - describing
// the flow in the side panel chat is the only authoring channel; clicking a
// node inspects it (and can point the chat at it). Layout dragging is allowed
// (positions are presentation, not semantics); structure is not.
function CanvasSurface({ ctx }: { ctx: Ctx }) {
  const { data, meta, graph, inspector, onNodeClick } = ctx;
  const [consoleOpen, setConsoleOpen] = useState(false);
  const [boltOpen, setBoltOpen] = useState(true);
  const [notes, setNotes] = useStickyNotes(meta.wfId);
  // Proposal preview: the proposed definition read from a pending approval
  // hold, rendered on the canvas with per-node diff badges. Approving is the
  // save; this view is what you are approving.
  const [proposal, setProposal] = useState<WorkflowStep[] | null>(null);
  const chat = useStudioChat(meta.wfId, graph.previewSteps);

  const closeModal = () => graph.setSelectedId(null);

  let viewNodes = graph.nodes;
  let viewEdges = graph.edges;
  if (proposal) {
    const diff = diffSteps(graph.previewSteps, proposal);
    // Removed steps stay visible, ghosted, so a deletion is a decision you
    // SEE, not an absence you might miss.
    const removed = graph.previewSteps.filter((s) => diff.byStep.get(s.id) === "removed");
    const merged = [...proposal, ...removed];
    const g = stepsToGraph(merged, data.verbsById);
    viewNodes = g.nodes.map((n) =>
      n.type === "step" && diff.byStep.has(n.id)
        ? { ...n, data: { ...n.data, diff: diff.byStep.get(n.id) } }
        : n,
    );
    viewEdges = g.edges;
  }

  return (
    <div className="wf3-canvas-wrap">
      {proposal && (
        <div className="wf3-proposal-banner">
          <span>
            Previewing proposed change - approve or reject it in the chat panel.
          </span>
          <button type="button" className="btn btn--ghost" onClick={() => setProposal(null)}>
            Back to current
          </button>
        </div>
      )}
      <ReactFlow
        key={proposal ? "proposal" : "current"}
        nodes={viewNodes}
        edges={viewEdges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={proposal ? undefined : graph.onNodesChange}
        onNodeClick={proposal ? undefined : onNodeClick}
        nodesConnectable={false}
        edgesFocusable={false}
        deleteKeyCode={null}
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

      <button
        type="button"
        className="wf3-console-toggle btn"
        onClick={() => setConsoleOpen((v) => !v)}
        aria-label="Toggle execution console"
        title="Execution console"
      >
        Console
      </button>
      <NodeDetailModal
        selectedNode={graph.selectedNode}
        verbs={data.verbs}
        verbsById={data.verbsById}
        inspector={inspector}
        onSwap={inspector.swapVerb}
        onRename={inspector.renameStep}
        onDelete={graph.deleteSelected}
        onClose={closeModal}
        readOnly
        onAskInChat={(stepId) => {
          chat.mention(stepId);
          setBoltOpen(true);
        }}
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
        chat={chat}
        onPreviewProposal={setProposal}
      />
      <StickyNotes notes={notes} onChange={setNotes} />
    </div>
  );
}
