// React Flow node components for the v3 automations canvas (design brief
// sec 22.3). Step nodes render as a 56x56 square card with a coloured filled
// icon, status dot, optional high-consequence shield badge, and connection
// ports; the label + a mono config preview sit below the card.

import { Handle, Position, type NodeProps, type NodeTypes } from "@xyflow/react";
import { DEFAULT_NODE_KIND, findKind } from "./nodeTaxonomy";
import { NodeIcon, ShieldBadge } from "./nodeIcons";
import type { RunNodeStatus, StepNodeData, TriggerNodeData } from "./types";

const RUN_COLOR: Record<RunNodeStatus, string> = {
  pending: "#7E95B0",
  running: "#3DD3F0",
  ok: "#3FB984",
  failed: "#F0654A",
  error: "#F0654A",
  skipped: "#4E637E",
};

function configPreview(d: StepNodeData): string {
  const p = d.params ?? {};
  if (typeof p.agent === "string") return p.agent;
  if (typeof p.url === "string") return String(p.url).slice(0, 16);
  const keys = Object.keys(p).filter((k) => k !== "__nodeKind");
  if (keys.length > 0) {
    const val = String(p[keys[0]]).slice(0, 14);
    return `${keys[0]}=${val}`;
  }
  return d.action;
}

function NodeCard({
  color,
  icon,
  selected,
  consequence,
  runStatus,
}: {
  color: string;
  icon: string;
  selected: boolean;
  consequence?: string;
  runStatus?: RunNodeStatus;
}) {
  const statusColor = runStatus ? RUN_COLOR[runStatus] : null;
  return (
    <div
      className="wf3-node__card"
      style={{ borderColor: selected ? color : "rgba(255,255,255,0.1)" }}
    >
      {statusColor && (
        <span
          className="wf3-node__status"
          style={{ background: statusColor, borderColor: "rgba(18,22,34,0.95)" }}
        />
      )}
      {consequence === "high" && (
        <span className="wf3-node__shield" title="High consequence step">
          <span className="wf3-node__shield-bg" style={{ background: "#FF7A45" }}>
            <ShieldBadge size={9} />
          </span>
        </span>
      )}
      <span className="wf3-node__icon" style={{ color }}>
        <NodeIcon name={icon} size={21} />
      </span>
      <Handle
        className="wf3-node__port wf3-node__port--in"
        type="target"
        position={Position.Left}
      />
      <Handle
        className="wf3-node__port wf3-node__port--out"
        type="source"
        position={Position.Right}
      />
    </div>
  );
}

function WorkflowNodeView({ data, selected }: NodeProps) {
  const d = data as StepNodeData;
  const meta = findKind(d.nodeKind) ?? findKind(DEFAULT_NODE_KIND)!;
  return (
    <div className="wf3-node" data-selected={selected ? "true" : "false"}>
      <NodeCard
        color={meta.color}
        icon={meta.icon}
        selected={!!selected}
        consequence={d.consequence}
        runStatus={d.runStatus}
      />
      <div className="wf3-node__label" style={{ color: selected ? meta.color : undefined }}>
        {d.label}
      </div>
      <div className="wf3-node__preview">{configPreview(d)}</div>
    </div>
  );
}

function TriggerNodeView({ data, selected }: NodeProps) {
  const d = data as TriggerNodeData;
  const meta = findKind("trigger")!;
  return (
    <div className="wf3-node" data-selected={selected ? "true" : "false"}>
      <NodeCard
        color={meta.color}
        icon={meta.icon}
        selected={!!selected}
      />
      <div className="wf3-node__label">{d.label}</div>
      <div className="wf3-node__preview">{d.triggerType} trigger</div>
    </div>
  );
}

export const nodeTypes: NodeTypes = { step: WorkflowNodeView, trigger: TriggerNodeView };
