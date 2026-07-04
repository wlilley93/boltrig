// React Flow node type components for step and trigger nodes.

import { Handle, Position, type NodeProps, type NodeTypes } from "@xyflow/react";
import type { StepNodeData, TriggerNodeData } from "./types";

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
