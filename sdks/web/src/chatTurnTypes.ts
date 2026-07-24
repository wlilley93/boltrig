// Shared data model for a streamed turn. These entry types are the normalized
// shape that normalizeEvents folds the chat/run event stream into, and that the
// card components render.

import type { HITLKind } from "./types.js";

export interface ToolEntry {
  key: string;
  // the correlation id that pairs a tool_call with its tool_result (US-CHAT-10);
  // absent on older run-relay frames, which fall back to verb matching.
  callId?: string;
  verb: string;
  // the argument KEYS only (from args_summary) - never the values, by design.
  argKeys?: string[];
  argCount?: number;
  // "pending" while the call is in flight; then the result status ("ok" |
  // "error" | "degraded" | a reason string).
  status: string;
  // full input/output ride only on the run relay (the Run drawer); the bounded
  // chat stream carries neither, so both are optional.
  input?: unknown;
  output?: unknown;
  resultKeys?: string[];
  consequence?: "low" | "high";
}

export interface QuestionEntry {
  questionId: string;
  prompt: string;
  choices: string[];
}

export interface SubagentEntry {
  key: string;
  childRunId: string;
  task: string;
  skills: string[];
  // Identity carried up from the subagent event when the backend provides it
  // (brief sec 6.4). All optional; renderers fall back to the palette + a
  // derived name/initials when the stream omits them.
  name?: string;
  role?: string;
  initials?: string;
  color?: string;
  stepCount?: number;
}

export interface HitlEntry {
  hitlRequestId: string;
  kind: HITLKind;
  question: string;
  options: string[];
  verb?: string;
  requestedBy?: string;
}

export interface StepEntry {
  stepId: string;
  action: string;
  status: "running" | "ok" | "failed" | "skipped" | "paused" | "error";
}

// Typed transcript entries preserve the arrival order of executable work. A
// tool result mutates its earlier tool entry in place, while workflow updates
// share one ordered card whose step rows settle in place.
export type TimelineEntry =
  | { kind: "tool"; key: string; entry: ToolEntry }
  | { kind: "subagent"; key: string; entry: SubagentEntry }
  | { kind: "hitl"; key: string; entry: HitlEntry }
  | { kind: "question"; key: string; entry: QuestionEntry }
  | { kind: "steps"; key: string; entries: StepEntry[] };

export interface NormalizedTurn {
  runId?: string;
  conversationId?: string;
  text: string;
  reasoning: string;
  tools: ToolEntry[];
  subagents: SubagentEntry[];
  hitls: HitlEntry[];
  questions: QuestionEntry[];
  steps: StepEntry[];
  timeline: TimelineEntry[];
  ended: boolean;
  cancelled: boolean;
}
