import { test } from "node:test";
import assert from "node:assert/strict";
import { normalizeEvents, type ChatEvent } from "../src/index.js";

// The UI-SDK core reducer is the shared source of truth both frontends fold the
// stream through, so opbox and the boltrig console show identical turns.

test("normalizeEvents: empty input yields an empty, un-ended turn", () => {
  const t = normalizeEvents([]);
  assert.equal(t.text, "");
  assert.equal(t.ended, false);
  assert.equal(t.cancelled, false);
  assert.deepEqual(t.tools, []);
});

test("normalizeEvents: message_start + text_deltas accumulate; message_end ends the turn", () => {
  const events: ChatEvent[] = [
    {
      type: "message_start",
      run_id: "r1",
      conversation_id: "c1",
      agent_address: "researcher",
    },
    { type: "text_delta", delta: "Hello, " },
    { type: "text_delta", delta: "world" },
    { type: "message_end", run_id: "r1" } as ChatEvent,
  ];
  const t = normalizeEvents(events);
  assert.equal(t.text, "Hello, world");
  assert.equal(t.runId, "r1");
  assert.equal(t.conversationId, "c1");
  assert.equal(t.agentAddress, "researcher");
  assert.equal(t.ended, true);
});

test("normalizeEvents: degraded text remains explicit turn state", () => {
  const turn = normalizeEvents([
    {
      type: "text_delta",
      delta: "degraded (codex: unavailable)",
      degraded: true,
    },
  ]);

  assert.equal(turn.degraded, true);
  assert.equal(turn.text, "degraded (codex: unavailable)");
});

// --- G3: a delegation must SETTLE, in both frontends ------------------------
// The union omitted subagent_end and the reducer had no case for it, so the
// console silently dropped a frame the kernel emits and opbox already handles:
// the same delegation settled in one frontend and spun forever in the other -
// exactly the drift a shared contract exists to prevent.

test("normalizeEvents: subagent_end settles the matching node in place", () => {
  const t = normalizeEvents([
    { type: "subagent", child_run_id: "c1", task: "look it up" },
    { type: "subagent", child_run_id: "c2", task: "and this" },
    { type: "subagent_end", child_run_id: "c1", status: "ok" },
  ] as ChatEvent[]);
  assert.equal(t.subagents.length, 2, "settling must not add a row");
  assert.equal(t.subagents.find((s) => s.childRunId === "c1")?.status, "ok");
  assert.equal(
    t.subagents.find((s) => s.childRunId === "c2")?.status,
    undefined,
    "an unsettled sibling stays running",
  );
});

test("normalizeEvents: preserves a server-derived spawn-rule receipt", () => {
  const t = normalizeEvents([
    {
      type: "subagent",
      child_run_id: "c1",
      task: "research",
      spawn_rule: {
        id: "research-route",
        priority: 50,
        matched_intent_tags: ["analysis", "research"],
        capability: "codex-worker",
        skills_added: ["analysis/research"],
        max_depth: 2,
      },
    },
  ] as ChatEvent[]);
  assert.equal(t.subagents[0]?.spawnRule?.id, "research-route");
  assert.deepEqual(
    t.subagents[0]?.spawnRule?.matched_intent_tags,
    ["analysis", "research"],
  );
});

test("normalizeEvents: a settle matches on child_run_id, not arrival order", () => {
  const t = normalizeEvents([
    { type: "subagent", child_run_id: "a", task: "first" },
    { type: "subagent", child_run_id: "b", task: "second" },
    { type: "subagent_end", child_run_id: "b", status: "error" },
    { type: "subagent_end", child_run_id: "a", status: "degraded" },
  ] as ChatEvent[]);
  assert.equal(t.subagents.find((s) => s.childRunId === "a")?.status, "degraded");
  assert.equal(t.subagents.find((s) => s.childRunId === "b")?.status, "error");
});

test("normalizeEvents: a settle for an unseen child is ignored, not invented", () => {
  // A resumed stream can start after the open frame; inventing a node would
  // render a delegation with no task description.
  const t = normalizeEvents([
    { type: "subagent_end", child_run_id: "never-opened", status: "ok" },
  ] as ChatEvent[]);
  assert.deepEqual(t.subagents, []);
});

test("normalizeEvents: steer frames are lifecycle, not turn content", () => {
  const t = normalizeEvents([
    { type: "text_delta", delta: "hi" },
    { type: "steer_queued", run_id: "r1", message_id: "m1" },
    { type: "steer_consumed", run_id: "r1", message_id: "m1" },
  ] as ChatEvent[]);
  assert.equal(t.text, "hi", "a steer must not alter the turn text");
});

test("normalizeEvents: artifact and withheld frames are lifecycle, not turn content", () => {
  const t = normalizeEvents([
    { type: "text_delta", delta: "done" },
    {
      type: "artifact",
      artifact_id: "a1",
      name: "answer.txt",
      media_type: "text/plain",
      size: 4,
    },
    { type: "artifact_rejected", count: 1 },
    { type: "event_unavailable", reason: "unsupported_event" },
  ] as ChatEvent[]);
  assert.equal(t.text, "done");
  assert.deepEqual(t.tools, []);
  assert.deepEqual(t.subagents, []);
});

test("normalizeEvents: secure questions retain their one-time input purpose", () => {
  const direct = normalizeEvents([
    {
      type: "question",
      question_id: "q-direct",
      prompt: "Paste the key",
      secure: true,
      purpose: "provider-api-key",
    },
  ] as ChatEvent[]);
  assert.equal(direct.questions[0]?.secure, true);
  assert.equal(direct.questions[0]?.securePurpose, "provider-api-key");

  const paused = normalizeEvents([
    {
      type: "hitl",
      hitl_request_id: "q-hitl",
      kind: "question",
      question: "Paste the webhook",
      secure: true,
      secure_purpose: "webhook-url",
    },
  ] as ChatEvent[]);
  assert.equal(paused.questions[0]?.secure, true);
  assert.equal(paused.questions[0]?.securePurpose, "webhook-url");
});
