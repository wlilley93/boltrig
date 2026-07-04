import { describe, expect, it } from "vitest";
import { normalizeEvents, type NormalizedTurn } from "@/panels/chatTurn";

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
  });
});
