import { cleanTaskText } from "@/panels/shared";
import type { ChatMessage } from "@/api/types";
import { whenText } from "@/panels/chat/formatting";
import { toolLabel } from "@/panels/chat/text";
import type { ActivityNode } from "@/panels/chat/types";
import type { NormalizedTurn } from "@/panels/chatTurn";
import { normalizeEvents } from "@/panels/chatTurn";

export function toolTone(status: string): string {
  if (status === "ok") return "#3FB984";
  if (status === "pending" || status === "running") return "#3DD3F0";
  return "#F0654A";
}

interface BuildTimelineInput {
  messages: ChatMessage[];
  live: NormalizedTurn;
  activeAgentColor: string;
  activeAgentName: string;
}

function buildSessionNode(name: string, color: string): ActivityNode {
  return {
    key: "session",
    label: "Session start",
    detail: `Conversation with ${name}`,
    time: "now",
    tone: color,
    badge: "session",
  };
}

function buildSubagentChildren(messageId: string, subKey: string, skills: string[], createdAt: string): ActivityNode[] {
  return skills.map((skill, i) => ({
    key: `${messageId}-${subKey}-skill-${i}`,
    label: "Skill loaded",
    detail: skill,
    time: whenText(createdAt),
    tone: "#7E95B0",
    badge: "ephemeral",
  }));
}

function buildAssistantNode(message: ChatMessage, color: string): ActivityNode {
  const turn = normalizeEvents(message.events ?? []);
  const children: ActivityNode[] = [
    ...turn.tools.map((tool) => ({
      key: `${message.id}-${tool.key}`,
      label: toolLabel(tool.verb),
      detail: `${tool.verb} - ${tool.status}`,
      time: whenText(message.created_at),
      tone: toolTone(tool.status),
      badge: "tool",
    })),
    ...turn.steps.map((step) => ({
      key: `${message.id}-${step.stepId}`,
      label: step.action,
      detail: step.status,
      time: whenText(message.created_at),
      tone: toolTone(step.status),
      badge: "step",
    })),
    ...turn.subagents.map((sub) => ({
      key: `${message.id}-${sub.key}`,
      label: "Delegation",
      detail: cleanTaskText(sub.task),
      time: whenText(message.created_at),
      tone: "#5E69DD",
      runId: sub.childRunId,
      badge: "handoff",
      children: buildSubagentChildren(message.id, sub.key, sub.skills, message.created_at),
    })),
  ];
  return {
    key: message.id,
    label: "Agent response",
    detail: message.content ? message.content.slice(0, 120) : "Structured response",
    time: whenText(message.created_at),
    tone: color,
    runId: message.run_id ?? turn.runId,
    badge: "agent",
    children,
  };
}

function buildLiveNode(live: NormalizedTurn, color: string): ActivityNode {
  return {
    key: "live",
    label: live.ended ? "Run complete" : "Agent action",
    detail: live.text || live.reasoning || "Streaming execution events",
    time: "live",
    tone: color,
    runId: live.runId,
    badge: live.ended ? "complete" : "agent",
    children: [
      ...live.tools.map((tool) => ({
        key: `live-${tool.key}`,
        label: toolLabel(tool.verb),
        detail: `${tool.verb} - ${tool.status}`,
        time: "live",
        tone: toolTone(tool.status),
        badge: "tool",
      })),
      ...live.subagents.map((sub) => ({
        key: `live-${sub.key}`,
        label: "Delegation",
        detail: cleanTaskText(sub.task),
        time: "live",
        tone: "#5E69DD",
        runId: sub.childRunId,
        badge: "handoff",
        children: sub.skills.map((skill, i) => ({
          key: `live-${sub.key}-skill-${i}`,
          label: "Skill loaded",
          detail: skill,
          time: "live",
          tone: "#7E95B0",
          badge: "ephemeral",
        })),
      })),
    ],
  };
}

function buildPendingNode(): ActivityNode {
  return {
    key: "pending",
    label: "Waiting for first instruction",
    detail: "Activity appears here as the agent plans, delegates and calls tools.",
    time: "pending",
    tone: "#3DD3F0",
    badge: "pending",
  };
}

export function buildTimelineNodes(input: BuildTimelineInput): ActivityNode[] {
  const { messages, live, activeAgentColor, activeAgentName } = input;
  const nodes: ActivityNode[] = [buildSessionNode(activeAgentName, activeAgentColor)];

  messages.forEach((message) => {
    if (message.role === "assistant") {
      nodes.push(buildAssistantNode(message, activeAgentColor));
    }
  });

  if (live.runId || live.tools.length > 0 || live.subagents.length > 0) {
    nodes.push(buildLiveNode(live, activeAgentColor));
  }

  if (nodes.length === 1) {
    nodes.push(buildPendingNode());
  }

  return nodes;
}

export type { ActivityNode } from "@/panels/chat/types";
