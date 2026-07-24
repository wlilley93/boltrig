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
    { type: "message_start", run_id: "r1", conversation_id: "c1" },
    { type: "text_delta", delta: "Hello, " },
    { type: "text_delta", delta: "world" },
    { type: "message_end", run_id: "r1" } as ChatEvent,
  ];
  const t = normalizeEvents(events);
  assert.equal(t.text, "Hello, world");
  assert.equal(t.runId, "r1");
  assert.equal(t.conversationId, "c1");
  assert.equal(t.ended, true);
});
