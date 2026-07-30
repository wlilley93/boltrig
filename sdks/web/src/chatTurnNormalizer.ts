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
  ChatModelRouting,
  ChatQuestion,
  ChatReasoningDelta,
  ChatSubagent,
  ChatSubagentEnd,
  ChatTextDelta,
  ChatToolCall,
  ChatToolResult,
  ChatWorkflowStep,
} from "./types.js";
import type {
  HitlEntry,
  NormalizedTurn,
  QuestionEntry,
  StepEntry,
  SubagentEntry,
  TimelineEntry,
  ToolEntry,
} from "./chatTurnTypes.js";

interface Accumulator {
  runId?: string;
  conversationId?: string;
  text: string;
  reasoning: string;
  ended: boolean;
  cancelled: boolean;
  degraded: boolean;
  tools: ToolEntry[];
  subagents: SubagentEntry[];
  hitls: HitlEntry[];
  questions: QuestionEntry[];
  steps: StepEntry[];
  stepIndex: Map<string, StepEntry>;
  timeline: TimelineEntry[];
  modelRouting?: NormalizedTurn["modelRouting"];
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
      case "subagent_end":
        handleSubagentEnd(ev, acc);
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
      case "model_routing":
        handleModelRouting(ev, acc);
        break;
      case "cancelled":
        handleCancelled(ev, acc);
        break;
      case "heartbeat":
      case "workflow_run":
      // Steers carry no turn CONTENT - they are queue lifecycle. Listed
      // explicitly so the union stays exhaustive and a future frame cannot be
      // dropped by silence.
      case "steer_queued":
      case "steer_consumed":
      // Artifact frames trigger a governed list refresh in the surface that
      // owns artifact state. A withheld internal frame is a visible continuity
      // notice there; neither is executable turn content.
      case "artifact":
      case "artifact_rejected":
      case "event_unavailable":
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
    degraded: false,
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
    degraded: acc.degraded,
    modelRouting: acc.modelRouting,
  };
}

function handleMessageStart(ev: ChatMessageStart, acc: Accumulator) {
  acc.runId = ev.run_id;
  acc.conversationId = ev.conversation_id;
}

function handleTextDelta(ev: ChatTextDelta, acc: Accumulator) {
  acc.text += ev.delta;
  if (ev.degraded === true) acc.degraded = true;
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
    spawnRule: ev.spawn_rule,
    familiarGenotype: ev.familiar_genotype,
  };
  acc.subagents.push(entry);
  acc.timeline.push({ kind: "subagent", key: entry.key, entry });
}

function handleModelRouting(ev: ChatModelRouting, acc: Accumulator) {
  acc.modelRouting = {
    selectedProfileId: ev.selected_profile_id,
    requestedProfileId: ev.requested_profile_id,
    routingClass: ev.routing_class,
    reason: ev.reason,
    overridden: ev.overridden,
  };
}

/**
 * Settle a delegation node (G3). Matched on `child_run_id`, NOT on arrival order,
 * and it MUTATES the existing entry rather than pushing a new one - the entry is
 * shared by reference with the timeline, so the rendered node flips in place
 * instead of the tree gaining a duplicate row.
 *
 * A settle for an unknown child is ignored: it means the open frame was never
 * seen (a resumed stream that starts after it), and inventing a node for a
 * delegation we never saw begin would render a task with no description.
 */
function handleSubagentEnd(ev: ChatSubagentEnd, acc: Accumulator) {
  const entry = [...acc.subagents].reverse().find((s) => s.childRunId === ev.child_run_id);
  if (entry) entry.status = ev.status;
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
        secure: ev.secure === true,
        securePurpose: ev.secure === true
          ? ev.purpose ?? ev.secure_purpose ?? undefined
          : undefined,
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
    existing.secure = ev.secure === true;
    existing.securePurpose = ev.secure === true ? ev.purpose : undefined;
    return;
  }
  const entry: QuestionEntry = {
    questionId: ev.question_id,
    prompt: ev.prompt,
    choices: ev.choices ?? [],
    secure: ev.secure === true,
    securePurpose: ev.secure === true ? ev.purpose : undefined,
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
