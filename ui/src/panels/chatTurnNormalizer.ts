// Folds a stream of chat/run events into a NormalizedTurn. The same event
// vocabulary (message_start / text_delta / reasoning_delta / tool_call /
// tool_result / subagent / hitl / question / workflow_step / message_end /
// cancelled) is produced by POST /v1/chat and by GET /v1/runs/{id}/events, so
// the Chat panel and the Run drawer share this one reducer.

import type {
  ChatCancelled,
  ChatEvent,
  ChatHitlEvent,
  ChatMessageEnd,
  ChatMessageStart,
  ChatQuestion,
  ChatReasoningDelta,
  ChatSubagent,
  ChatTextDelta,
  ChatToolCall,
  ChatToolResult,
  ChatWorkflowStep,
} from "@/api/types";
import type {
  HitlEntry,
  NormalizedTurn,
  QuestionEntry,
  StepEntry,
  SubagentEntry,
  TimelineEntry,
  ToolEntry,
} from "@/panels/chatTurnTypes";

interface Accumulator {
  runId?: string;
  conversationId?: string;
  text: string;
  reasoning: string;
  ended: boolean;
  cancelled: boolean;
  tools: ToolEntry[];
  subagents: SubagentEntry[];
  hitls: HitlEntry[];
  questions: QuestionEntry[];
  steps: StepEntry[];
  stepIndex: Map<string, StepEntry>;
  timeline: TimelineEntry[];
}

export function normalizeEvents(events: ChatEvent[]): NormalizedTurn {
  const acc = createAccumulator();
  events.forEach((ev, i) => {
    switch (ev.type) {
      case "message_start":
        handleMessageStart(ev, acc);
        break;
      case "text_delta":
        handleTextDelta(ev, acc);
        break;
      case "reasoning_delta":
        handleReasoningDelta(ev, acc);
        break;
      case "tool_call":
        handleToolCall(ev, i, acc);
        break;
      case "tool_result":
        handleToolResult(ev, i, acc);
        break;
      case "subagent":
        handleSubagent(ev, i, acc);
        break;
      case "hitl":
        handleHitl(ev, acc);
        break;
      case "question":
        handleQuestion(ev, acc);
        break;
      case "workflow_step":
        handleWorkflowStep(ev, i, acc);
        break;
      case "message_end":
        handleMessageEnd(ev, acc);
        break;
      case "cancelled":
        handleCancelled(ev, acc);
        break;
      case "heartbeat":
      case "workflow_run":
        break;
    }
  });
  return buildTurn(acc);
}

function createAccumulator(): Accumulator {
  return {
    text: "",
    reasoning: "",
    ended: false,
    cancelled: false,
    tools: [],
    subagents: [],
    hitls: [],
    questions: [],
    steps: [],
    stepIndex: new Map(),
    timeline: [],
  };
}

function buildTurn(acc: Accumulator): NormalizedTurn {
  return {
    runId: acc.runId,
    conversationId: acc.conversationId,
    text: acc.text,
    reasoning: acc.reasoning,
    tools: acc.tools,
    subagents: acc.subagents,
    hitls: acc.hitls,
    questions: acc.questions,
    steps: acc.steps,
    timeline: acc.timeline,
    ended: acc.ended,
    cancelled: acc.cancelled,
  };
}

function handleMessageStart(ev: ChatMessageStart, acc: Accumulator) {
  acc.runId = ev.run_id;
  acc.conversationId = ev.conversation_id;
}

function handleTextDelta(ev: ChatTextDelta, acc: Accumulator) {
  acc.text += ev.delta;
}

function handleReasoningDelta(ev: ChatReasoningDelta, acc: Accumulator) {
  acc.reasoning += ev.delta;
}

function handleToolCall(ev: ChatToolCall, index: number, acc: Accumulator) {
  const entry: ToolEntry = {
    key: `t${index}`,
    callId: ev.call_id,
    verb: ev.tool ?? ev.verb ?? "(tool)",
    argKeys: ev.args_summary?.keys ?? [],
    argCount: ev.args_summary?.count,
    input: ev.input,
    status: "pending",
    consequence: ev.consequence,
  };
  acc.tools.push(entry);
  acc.timeline.push({ kind: "tool", key: entry.key, entry });
}

function handleToolResult(ev: ChatToolResult, index: number, acc: Accumulator) {
  const byId = ev.call_id
    ? [...acc.tools].reverse().find((t) => t.callId === ev.call_id)
    : undefined;
  const match =
    byId ??
    [...acc.tools]
      .reverse()
      .find((t) => t.status === "pending" && t.verb === (ev.verb ?? ""));
  const resultKeys = ev.result_summary?.keys;
  if (match) {
    match.status = ev.status;
    match.output = ev.output;
    match.resultKeys = resultKeys;
  } else {
    const entry: ToolEntry = {
      key: `t${index}`,
      callId: ev.call_id,
      verb: ev.verb ?? "(tool)",
      status: ev.status,
      output: ev.output,
      resultKeys,
    };
    acc.tools.push(entry);
    acc.timeline.push({ kind: "tool", key: entry.key, entry });
  }
}

function handleSubagent(ev: ChatSubagent, index: number, acc: Accumulator) {
  const entry: SubagentEntry = {
    key: `s${index}`,
    childRunId: ev.child_run_id,
    task: ev.task,
    skills: ev.skills ?? [],
    name: ev.name,
    role: ev.role,
    color: ev.color,
    stepCount: ev.step_count,
  };
  acc.subagents.push(entry);
  acc.timeline.push({ kind: "subagent", key: entry.key, entry });
}

function handleHitl(ev: ChatHitlEvent, acc: Accumulator) {
  const kind = ev.kind ?? "approval";
  if (ev.call_id) {
    const tool = [...acc.tools].reverse().find((item) => item.callId === ev.call_id);
    if (tool) {
      tool.status = "pending_human";
      if (kind === "approval") tool.consequence = "high";
    }
  }
  if (kind === "question") {
    if (!acc.questions.some((item) => item.questionId === ev.hitl_request_id)) {
      const question: QuestionEntry = {
        questionId: ev.hitl_request_id,
        prompt: ev.question ?? "The agent needs an answer.",
        choices: ev.options ?? [],
      };
      acc.questions.push(question);
      acc.timeline.push({ kind: "question", key: `q${question.questionId}`, entry: question });
    }
    return;
  }
  const entry: HitlEntry = {
    hitlRequestId: ev.hitl_request_id,
    kind,
    question: ev.question ?? "A governed action needs your response.",
    options: ev.options ?? [],
    verb: ev.verb,
    requestedBy: ev.requested_by,
  };
  acc.hitls.push(entry);
  acc.timeline.push({
    kind: "hitl",
    key: `h${ev.hitl_request_id}`,
    entry,
  });
}

function handleQuestion(ev: ChatQuestion, acc: Accumulator) {
  const existing = acc.questions.find((item) => item.questionId === ev.question_id);
  if (existing) {
    existing.prompt = ev.prompt;
    existing.choices = ev.choices ?? [];
    return;
  }
  const entry: QuestionEntry = {
    questionId: ev.question_id,
    prompt: ev.prompt,
    choices: ev.choices ?? [],
  };
  acc.questions.push(entry);
  acc.timeline.push({ kind: "question", key: `q${ev.question_id}`, entry });
}

function handleWorkflowStep(ev: ChatWorkflowStep, index: number, acc: Accumulator) {
  const existing = acc.stepIndex.get(ev.step_id);
  if (existing) {
    existing.status = ev.status;
    existing.action = ev.action;
  } else {
    const entry: StepEntry = {
      stepId: ev.step_id,
      action: ev.action,
      status: ev.status,
    };
    acc.stepIndex.set(ev.step_id, entry);
    if (acc.steps.length === 0) {
      acc.timeline.push({ kind: "steps", key: `w${index}`, entries: acc.steps });
    }
    acc.steps.push(entry);
  }
}

function handleMessageEnd(ev: ChatMessageEnd, acc: Accumulator) {
  acc.ended = true;
  acc.runId = ev.run_id ?? acc.runId;
}

function handleCancelled(ev: ChatCancelled, acc: Accumulator) {
  acc.ended = true;
  acc.cancelled = true;
  acc.runId = ev.run_id ?? acc.runId;
}
