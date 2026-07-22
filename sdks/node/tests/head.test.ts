import { test } from "node:test";
import assert from "node:assert/strict";
import {
  answerQuestion,
  parseSse,
  renderEvent,
  respondHitl,
  SseParser,
  type ChatEvent,
  type FetchLike,
} from "../src/index.js";

// --- SseParser (port of chat_cli.py:SseParser) ------------------------------

test("SseParser: data-only frames, blank line completes", () => {
  const p = new SseParser();
  assert.equal(p.feed('data: {"type":"text_delta","delta":"he"}'), null);
  const event = p.feed("");
  assert.deepEqual(event, { type: "text_delta", delta: "he" });
});

test("SseParser: multi-line data joins with newline; comments/id dropped", () => {
  const p = new SseParser();
  p.feed(": a comment");
  p.feed("event: message");
  p.feed("id: 42");
  p.feed('data: {"a":');
  p.feed("data: 1}");
  const event = p.feed("");
  assert.deepEqual(event, { a: 1 });
});

test("SseParser: malformed JSON and non-object payloads are dropped, never fatal", () => {
  const p = new SseParser();
  p.feed("data: {not json");
  assert.equal(p.feed(""), null);
  p.feed("data: [1,2]");
  assert.equal(p.feed(""), null);
  p.feed("data: 42");
  assert.equal(p.feed(""), null);
  // The parser recovers for the next frame.
  p.feed('data: {"type":"message_end"}');
  assert.deepEqual(p.feed(""), { type: "message_end" });
});

test("parseSse yields events as lines arrive and flushes the tail", async () => {
  async function* lines(): AsyncGenerator<string> {
    yield 'data: {"type":"message_start","conversation_id":"c-1"}';
    yield "";
    yield 'data: {"type":"text_delta","delta":"hi"}';
    yield ""; // no trailing blank for the last frame? give one anyway
    yield 'data: {"type":"message_end"}'; // tail flushed at stream end
  }
  const events: ChatEvent[] = [];
  for await (const e of parseSse(lines())) events.push(e);
  assert.deepEqual(events.map((e) => e.type), ["message_start", "text_delta", "message_end"]);
});

// --- renderEvent (port of chat_cli.py:render_event) --------------------------

test("renderEvent: deltas stream inline", () => {
  assert.equal(renderEvent({ type: "text_delta", delta: "abc" }), "abc");
  assert.equal(renderEvent({ type: "reasoning_delta", delta: "..." }), "...");
});

test("renderEvent: tool_call / tool_result lines", () => {
  assert.equal(
    renderEvent({ type: "tool_call", tool: "orders.list", args_summary: { keys: ["status"] } }),
    "\n[tool] orders.list(status)\n",
  );
  assert.equal(renderEvent({ type: "tool_call", verb: "orders.get" }), "\n[tool] orders.get\n");
  assert.equal(renderEvent({ type: "tool_result", status: "ok" }), "[tool] -> ok\n");
});

test("renderEvent: hitl and question blocks carry their ids", () => {
  assert.equal(
    renderEvent({ type: "hitl", hitl_request_id: "h-1", kind: "approval", question: "Adjust stock?" }),
    "\n*** HUMAN INPUT NEEDED (approval): Adjust stock?\n*** respond: /approve h-1  or  /deny h-1\n",
  );
  assert.equal(
    renderEvent({ type: "question", question_id: "q-1", prompt: "Which SKU?", choices: ["A", "B"] }),
    "\n*** QUESTION: Which SKU? (choices: A, B)\n*** answer: /answer q-1 <your answer>\n",
  );
});

test("renderEvent: subagent, cancelled, message_end, and null-rendered types", () => {
  assert.equal(renderEvent({ type: "subagent", name: "cos", task: "triage" }), "\n[subagent] cos: triage\n");
  assert.equal(renderEvent({ type: "cancelled" }), "\n(cancelled)\n");
  assert.equal(renderEvent({ type: "message_end" }), "\n");
  assert.equal(renderEvent({ type: "message_start" }), null);
  assert.equal(renderEvent({ type: "heartbeat" }), null);
  assert.equal(renderEvent({ type: "something_new" }), null);
});

// --- HITL helpers over mocked fetch -----------------------------------------

function mockFetch(status: number, payload: unknown): { fetch: FetchLike; calls: Array<{ url: string; body: Record<string, unknown> }> } {
  const calls: Array<{ url: string; body: Record<string, unknown> }> = [];
  const fetchMock: FetchLike = async (input, init) => {
    calls.push({ url: input, body: init?.body ? (JSON.parse(init.body) as Record<string, unknown>) : {} });
    return {
      status,
      headers: { get: () => null },
      json: async () => payload,
      text: async () => JSON.stringify(payload),
    };
  };
  return { fetch: fetchMock, calls };
}

test("respondHitl posts the decision to /v1/hitl/{id}/respond", async () => {
  const { fetch: f, calls } = mockFetch(200, { status: "ok" });
  await respondHitl({ server: "http://k/", token: "t", fetch: f, requestId: "h-1", decision: "approve" });
  assert.equal(calls[0]?.url, "http://k/v1/hitl/h-1/respond");
  assert.deepEqual(calls[0]?.body, { decision: "approve", notes: "" });
});

test("answerQuestion posts the answer to /v1/hitl/{id}/answer", async () => {
  const { fetch: f, calls } = mockFetch(200, { status: "ok" });
  await answerQuestion({ server: "http://k/", token: "t", fetch: f, questionId: "q-1", answer: "WIDGET-9" });
  assert.equal(calls[0]?.url, "http://k/v1/hitl/q-1/answer");
  assert.deepEqual(calls[0]?.body, { answer: "WIDGET-9" });
});
