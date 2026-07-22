import { cleanTaskText } from "@/panels/shared";
import type { ChatMessage } from "@/api/types";
import { whenText } from "@/panels/chat/formatting";
import { toolLabel } from "@/panels/chat/text";
import type { ActivityNode } from "@/panels/chat/types";
import type { NormalizedTurn } from "@/panels/chatTurn";
import { normalizeEvents } from "@/panels/chatTurn";

export function toolTone(status: string): string {
  if (status === "ok") return "var(--color-ok)";
  if (status === "pending" || status === "running") return "var(--color-run-running)";
  if (status === "pending_human" || status === "paused") return "var(--color-consequence-high)";
  return "var(--color-down)";
}

// Per-event-type constants (brief sec 13.1, lines 354-363).
const CYAN = "var(--color-accent)";
const MUTED = "var(--color-text-muted)";
const DELEGATION_COLOR = "var(--color-accent-2)";
const DOT_BORDER_AGENT = "2px solid var(--color-bg-base)";
const DOT_BORDER_EPHEMERAL = `2px solid ${MUTED}`;

function initialsOf(name: string): string {
  const letter = name.trim().charAt(0).toUpperCase();
  return letter || "?";
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
    dotSize: 8,
    dotColor: CYAN,
    hasAvatar: false,
    hasLine: true,
    labelWeight: 500,
  };
}

function buildToolNode(prefix: string, toolKey: string, verb: string, status: string, callId: string | undefined, time: string): ActivityNode {
  return {
    key: `${prefix}-${toolKey}`,
    label: toolLabel(verb),
    detail: callId ?? toolKey, // receipt id
    time,
    tone: toolTone(status),
    badge: "tool",
    dotSize: 7,
    dotColor: toolTone(status),
    hasAvatar: false,
    hasLine: true,
    labelWeight: 400,
  };
}

function buildStepNode(prefix: string, stepId: string, action: string, status: string, time: string): ActivityNode {
  return {
    key: `${prefix}-${stepId}`,
    label: action,
    detail: status,
    time,
    tone: toolTone(status),
    badge: "step",
    dotSize: 7,
    dotColor: toolTone(status),
    hasAvatar: false,
    hasLine: true,
    labelWeight: 400,
  };
}

function buildEphemeralNode(key: string, detail: string, time: string): ActivityNode {
  return {
    key,
    label: "Skill loaded",
    detail,
    time,
    tone: MUTED,
    badge: "ephemeral",
    dotSize: 9,
    dotColor: MUTED,
    dotExtra: DOT_BORDER_EPHEMERAL,
    hasAvatar: true,
    avatarColor: MUTED,
    avatarInitials: initialsOf(detail),
    avatarSize: 16,
    hasLine: true,
    labelWeight: 500,
    badgeBorder: MUTED,
  };
}

function buildDelegationNode(prefix: string, sub: NormalizedTurn["subagents"][number], time: string, skillTime: string): ActivityNode {
  return {
    key: `${prefix}-${sub.key}`,
    label: "Delegation",
    detail: cleanTaskText(sub.task),
    time,
    tone: DELEGATION_COLOR,
    runId: sub.childRunId,
    badge: "delegation",
    dotSize: 12,
    dotColor: DELEGATION_COLOR,
    hasAvatar: false,
    hasLine: true,
    labelWeight: 600,
    labelColor: DELEGATION_COLOR,
    badgeColor: DELEGATION_COLOR,
    badgeBorder: DELEGATION_COLOR,
    children: sub.skills.map((skill, i) => buildEphemeralNode(`${prefix}-${sub.key}-skill-${i}`, skill, skillTime)),
  };
}

function buildAssistantNode(message: ChatMessage, color: string, name: string): ActivityNode {
  const turn = normalizeEvents(message.events ?? []);
  const children: ActivityNode[] = [
    ...turn.tools.map((tool) => buildToolNode(message.id, tool.key, tool.verb, tool.status, tool.callId, whenText(message.created_at))),
    ...turn.steps.map((step) => buildStepNode(message.id, step.stepId, step.action, step.status, whenText(message.created_at))),
    ...turn.subagents.map((sub) => buildDelegationNode(message.id, sub, whenText(message.created_at), whenText(message.created_at))),
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
    dotSize: 12,
    dotColor: color,
    dotExtra: DOT_BORDER_AGENT,
    hasAvatar: true,
    avatarColor: color,
    avatarInitials: initialsOf(name),
    avatarSize: 20,
    hasLine: true,
    labelWeight: 600,
    labelColor: color,
  };
}

function buildLiveNode(live: NormalizedTurn, color: string, name: string): ActivityNode {
  return {
    key: "live",
    label: live.ended ? "Run complete" : "Agent action",
    detail: live.text || live.reasoning || "Streaming execution events",
    time: "live",
    tone: color,
    runId: live.runId,
    badge: live.ended ? "complete" : "agent",
    dotSize: 12,
    dotColor: color,
    dotExtra: DOT_BORDER_AGENT,
    hasAvatar: true,
    avatarColor: color,
    avatarInitials: initialsOf(name),
    avatarSize: 20,
    hasLine: true,
    labelWeight: 600,
    labelColor: color,
    children: [
      ...live.tools.map((tool) => buildToolNode("live", tool.key, tool.verb, tool.status, tool.callId, "live")),
      ...live.subagents.map((sub) => buildDelegationNode("live", sub, "live", "live")),
    ],
  };
}

function buildPendingNode(): ActivityNode {
  return {
    key: "pending",
    label: "Waiting for first instruction",
    detail: "Activity appears here as the agent plans, delegates and calls tools.",
    time: "pending",
    tone: CYAN,
    badge: "pending",
    dotSize: 8,
    dotColor: CYAN,
    hasAvatar: false,
    hasLine: false, // brief 13.1: pending has no bottom connecting line
    labelColor: MUTED,
  };
}

export function buildTimelineNodes(input: BuildTimelineInput): ActivityNode[] {
  const { messages, live, activeAgentColor, activeAgentName } = input;
  const nodes: ActivityNode[] = [buildSessionNode(activeAgentName, activeAgentColor)];

  messages.forEach((message) => {
    if (message.role === "assistant") {
      nodes.push(buildAssistantNode(message, activeAgentColor, activeAgentName));
    }
  });

  if (live.runId || live.tools.length > 0 || live.subagents.length > 0) {
    nodes.push(buildLiveNode(live, activeAgentColor, activeAgentName));
  }

  if (nodes.length === 1) {
    nodes.push(buildPendingNode());
  }

  return nodes;
}

export type { ActivityNode } from "@/panels/chat/types";
