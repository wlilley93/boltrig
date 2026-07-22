// Custom edge for the automations canvas (design brief sec 22.4). A bezier path
// between the source right-port and target left-port, an open-chevron arrowhead,
// an optional midpoint branch label, and an animated cyan dot on running edges.

import {
  BaseEdge,
  EdgeLabelRenderer,
  type EdgeProps,
  type EdgeTypes,
} from "@xyflow/react";
import type { RunEdgeVariant } from "./runState";

function variantOf(data: Record<string, unknown> | undefined): RunEdgeVariant {
  const v = data?.variant;
  if (v === "ok" || v === "running" || v === "failed" || v === "paused") return v;
  if (data?.state === "running") return "running";
  if (data?.state === "ok") return "ok";
  if (data?.state === "failed" || data?.state === "denied") return "failed";
  if (data?.state === "paused") return "paused";
  return "default";
}

// Build a horizontal bezier with control points pulled 40% across the gap, per
// the brief. Returns the path string plus its midpoint for label placement.
function curvePath(
  sx: number,
  sy: number,
  tx: number,
  ty: number,
): { d: string; midX: number; midY: number } {
  const dx = tx - sx;
  const c1x = sx + dx * 0.4;
  const c2x = sx + dx * 0.6;
  const d = `M ${sx} ${sy} C ${c1x} ${sy}, ${c2x} ${ty}, ${tx} ${ty}`;
  return { d, midX: (sx + tx) / 2, midY: (sy + ty) / 2 };
}

export function WorkflowEdge({
  sourceX,
  sourceY,
  targetX,
  targetY,
  data,
  selected,
}: EdgeProps) {
  const variant = variantOf(data as Record<string, unknown> | undefined);
  const label = (data as { label?: string } | undefined)?.label;
  const { d, midX, midY } = curvePath(sourceX, sourceY, targetX, targetY);

  // Open chevron arrowhead at the target port (rounded caps/joins, no fill).
  const arrow = `M ${targetX - 7} ${targetY - 4} L ${targetX} ${targetY} L ${targetX - 7} ${targetY + 4}`;

  return (
    <>
      <BaseEdge
        path={d}
        className={`wf3-edge wf3-edge--${variant}`}
        style={{
          strokeWidth: 1.5,
          strokeDasharray: selected ? "4 3" : undefined,
        }}
      />
      <path
        d={arrow}
        className={`wf3-edge wf3-edge--${variant}`}
        fill="none"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {variant === "running" && (
        <circle className="wf3-edge__runner" r={3}>
          <animateMotion dur="1.5s" repeatCount="indefinite" path={d} />
        </circle>
      )}
      {label && (
        <EdgeLabelRenderer>
          <div
            className="wf3-edge-label"
            style={{
              transform: `translate(-50%, -50%) translate(${midX}px, ${midY}px)`,
            }}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

export const edgeTypes: EdgeTypes = { workflow: WorkflowEdge };
