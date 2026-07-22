import { describe, expect, it } from "vitest";
import { normalizeEvents, type NormalizedTurn, TurnExtras } from "@/panels/chatTurn";

describe("chatTurn (normalizeEvents)", () => {
  it("folds a stream of chat events into a normalized turn", () => {
    const events = [
      { type: "message_start", run_id: "run-1", conversation_id: "conv-1" },
      { type: "text_delta", delta: "Hello" },
      { type: "reasoning_delta", delta: "thinking" },
      { type: "tool_call", call_id: "c1", tool: "search", args_summary: { keys: ["q"], count: 1 } },
      { type: "tool_result", call_id: "c1", status: "ok", output: "found" },
      { type: "workflow_step", step_id: "s1", action: "step", status: "running" },
      { type: "workflow_step", step_id: "s1", action: "step", status: "ok" },
    ];

    const turn: NormalizedTurn = normalizeEvents(events as unknown[]);
    expect(turn.runId).toBe("run-1");
    expect(turn.conversationId).toBe("conv-1");
    expect(turn.text).toBe("Hello");
    expect(turn.reasoning).toBe("thinking");
    expect(turn.tools).toHaveLength(1);
    expect(turn.tools[0].status).toBe("ok");
    expect(turn.steps).toHaveLength(1);
    expect(turn.steps[0].status).toBe("ok");
    expect(turn.timeline.map((entry) => entry.kind)).toEqual(["tool", "steps"]);
  });

  it("keeps typed cards in arrival order and turns a held call into a high-consequence pause", () => {
    const turn = normalizeEvents([
      { type: "tool_call", call_id: "c1", tool: "ticket.update" },
      { type: "subagent", child_run_id: "child-1", task: "check policy" },
      {
        type: "hitl",
        hitl_request_id: "h1",
        call_id: "c1",
        kind: "approval",
        verb: "ticket.update",
        question: "Approve ticket.update?",
      },
    ] as unknown[]);

    expect(turn.timeline.map((entry) => entry.kind)).toEqual([
      "tool",
      "subagent",
      "hitl",
    ]);
    expect(turn.tools[0]).toMatchObject({
      status: "pending_human",
      consequence: "high",
    });
    expect(turn.hitls[0].verb).toBe("ticket.update");
  });

  it("renders an ask-user pause as one question without inventing high consequence", () => {
    const turn = normalizeEvents([
      { type: "tool_call", call_id: "c1", tool: "chat.ask_user" },
      {
        type: "question",
        question_id: "q1",
        prompt: "Which region?",
        choices: ["EU", "US"],
      },
      {
        type: "hitl",
        hitl_request_id: "q1",
        call_id: "c1",
        kind: "question",
        question: "Which region?",
        options: ["EU", "US"],
      },
    ] as unknown[]);

    expect(turn.timeline.map((entry) => entry.kind)).toEqual(["tool", "question"]);
    expect(turn.questions).toHaveLength(1);
    expect(turn.hitls).toHaveLength(0);
    expect(turn.tools[0]).toMatchObject({
      status: "pending_human",
      consequence: undefined,
    });
  });
});

describe("chatTurn public API", () => {
  it("preserves the barrel exports", () => {
    expect(typeof normalizeEvents).toBe("function");
    expect(typeof TurnExtras).toBe("function");
  });
});
