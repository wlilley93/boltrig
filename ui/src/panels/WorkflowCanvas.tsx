// Canvas view of the Workflow Studio. Thin orchestrator: state and helpers live
// in the workflowCanvas/ submodule; this file only composes the view and
// re-exports the public API.

import { Background, Controls, MiniMap, ReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { WorkflowRunCanvas } from "@/panels/WorkflowRunCanvas";
import { MetaForm } from "./workflowCanvas/MetaForm";
import { VerbPalette } from "./workflowCanvas/VerbPalette";
import { TriggerPalette } from "./workflowCanvas/TriggerPalette";
import { WorkflowList } from "./workflowCanvas/WorkflowList";
import { LoadPanel } from "./workflowCanvas/LoadPanel";
import { StepInspector } from "./workflowCanvas/StepInspector";
import { StepsPreview } from "./workflowCanvas/StepsPreview";
import { RunRecord } from "./workflowCanvas/RunRecord";
import { useWorkflowCanvas } from "./workflowCanvas/useWorkflowCanvas";
import { nodeTypes } from "./workflowCanvas/nodes";

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
  const { data, meta, graph, inspector, apiActions, addVerbNode, onNodeClick } =
    useWorkflowCanvas(routeWfId);

  if (meta.runView) {
    return (
      <WorkflowRunCanvas
        runId={meta.runView.runId}
        wfId={meta.runView.wfId}
        onBack={() => meta.setRunView(null)}
      />
    );
  }

  return (
    <div className="wf-studio">
      <div className="stack">
        <MetaForm
          meta={meta}
          api={apiActions}
          clearCanvas={graph.clearCanvas}
        />
        <VerbPalette
          verbs={data.verbs}
          filter={graph.paletteFilter}
          onFilter={graph.setPaletteFilter}
          onAdd={addVerbNode}
        />
        <TriggerPalette onAdd={graph.addTrigger} />
        <WorkflowList
          workflows={data.workflows}
          list={data.workflows.data?.workflows ?? []}
          onPick={apiActions.pickWorkflow}
        />
        <LoadPanel
          loadText={graph.loadText}
          loadError={graph.loadError}
          onChange={graph.setLoadText}
          onLoad={graph.loadFromJson}
        />
      </div>
      <div className="stack">
        <div className="wf-canvas">
          <ReactFlow
            nodes={graph.nodes}
            edges={graph.edges}
            nodeTypes={nodeTypes}
            onNodesChange={graph.onNodesChange}
            onEdgesChange={graph.onEdgesChange}
            onConnect={graph.onConnect}
            onNodeClick={onNodeClick}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background />
            <Controls />
            <MiniMap pannable zoomable />
          </ReactFlow>
        </div>
        <StepInspector
          selectedNode={graph.selectedNode}
          verbs={data.verbs}
          verbsById={data.verbsById}
          inspector={inspector}
          onSwap={inspector.swapVerb}
          onRename={inspector.renameStep}
          onDelete={graph.deleteSelected}
        />
        <StepsPreview steps={graph.previewSteps} />
        {meta.runResult && <RunRecord runResult={meta.runResult} />}
      </div>
    </div>
  );
}
