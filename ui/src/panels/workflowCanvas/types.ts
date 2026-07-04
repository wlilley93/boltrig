// Canvas data shapes: the graph node data and the serialised step contract.
// These are pure types with no rendering or fetching logic.

import type { Node } from "@xyflow/react";

export type NodeKind = "agent" | "service" | "kernel-run";
export type TriggerKind = "chat" | "cron" | "webhook";

export type RunNodeStatus =
  | "pending"
  | "running"
  | "ok"
  | "failed"
  | "error"
  | "skipped";

export type StepNodeData = {
  action: string;
  params: Record<string, unknown>;
  kind: NodeKind;
  label: string;
  description?: string;
  consequence?: string;
  runStatus?: RunNodeStatus;
};

export type TriggerNodeData = {
  triggerType: TriggerKind;
  label: string;
};

export type StepNode = Node<StepNodeData, "step">;
type TriggerNode = Node<TriggerNodeData, "trigger">;
export type CanvasNode = StepNode | TriggerNode;

export interface WorkflowStep {
  id: string;
  parents: string[];
  action: string;
  params?: Record<string, unknown>;
  description?: string;
}
