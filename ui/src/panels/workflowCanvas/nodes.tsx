// React Flow node components for the v3 automations canvas (design brief
// sec 22.3). Step nodes render as a 56x56 square card with a coloured filled
// icon, status glyph, optional high-consequence shield badge, and connection
// ports; the label + a mono config preview sit below the card.

import { Handle, Position, type NodeProps, type NodeTypes } from "@xyflow/react";
import { DEFAULT_NODE_KIND, findKind } from "./nodeTaxonomy";
import { NodeIcon, ShieldBadge } from "./nodeIcons";
import type { RunNodeStatus, StepNodeData, TriggerNodeData } from "./types";

const RUN_GLYPH: Record<RunNodeStatus, string> = {
  pending: "·",
  running: "›",
  ok: "✓",
  failed: "×",
  error: "!",
  skipped: "−",
  paused: "‖",
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
  icon,
  consequence,
  runStatus,
}: {
  icon: string;
  consequence?: string;
  runStatus?: RunNodeStatus;
}) {
  return (
    <div
      className={`wf3-node__card${runStatus ? ` wf3-node__card--${runStatus}` : ""}`}
    >
      {runStatus && (
        <span
          className={`wf3-node__status wf3-node__status--${runStatus}`}
          aria-label={`Step ${runStatus}`}
          title={`Step ${runStatus}`}
        >
          {RUN_GLYPH[runStatus]}
        </span>
      )}
      {consequence === "high" && (
        <span className="wf3-node__shield" title="High consequence step">
          <span className="wf3-node__shield-bg">
            <ShieldBadge size={9} />
          </span>
        </span>
      )}
      <span className="wf3-node__icon">
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
    <div
      className="wf3-node"
      data-selected={selected ? "true" : "false"}
      style={{ "--wf-node-color": meta.color } as React.CSSProperties}
    >
      <NodeCard
        icon={meta.icon}
        consequence={d.consequence}
        runStatus={d.runStatus}
      />
      <div className="wf3-node__label">
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
    <div
      className="wf3-node"
      data-selected={selected ? "true" : "false"}
      style={{ "--wf-node-color": meta.color } as React.CSSProperties}
    >
      <NodeCard
        icon={meta.icon}
      />
      <div className="wf3-node__label">{d.label}</div>
      <div className="wf3-node__preview">{d.triggerType} trigger</div>
    </div>
  );
}

export const nodeTypes: NodeTypes = { step: WorkflowNodeView, trigger: TriggerNodeView };
