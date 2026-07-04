// Shared data model for a streamed turn. These entry types are the normalized
// shape that normalizeEvents folds the chat/run event stream into, and that the
// card components render.

import type { HITLKind } from "@/api/types";

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
}

export interface HitlEntry {
  hitlRequestId: string;
  kind: HITLKind;
  question: string;
  options: string[];
}

export interface StepEntry {
  stepId: string;
  action: string;
  status: "running" | "ok" | "failed" | "skipped" | "error";
}

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
  ended: boolean;
  cancelled: boolean;
}
