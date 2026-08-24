/** The contract this port rests on, proven against the real SDK validator.
 *
 * The plan named one thing that could sink the v1 UI port: v1's chat surface
 * expects `{cursor, event}` frames whose cursor never regresses, and the SDK
 * THROWS if it does. These tests do not re-implement that check - they drive
 * `BoltrigClient.followConversation` itself with a fake fetcher, so what passes
 * here is what the shipping client accepts.
 */

import assert from "node:assert/strict";
import test from "node:test";

import { BoltrigClient } from "../src/client.js";
import type { ChatFollowFrame } from "../src/types.js";
import {
  CursorClock, MAX_SEQ_PER_RUN, asSseBody, frameFromRunEvent, toChatEvents, translate,
  translateRunStream,
} from "../src/hermes/shim.js";
import type { HermesFrame } from "../src/hermes/shim.js";

/** One turn as Hermes actually writes it, names and payload keys taken from
 *  gateway/platforms/api_server.py in the pinned cell image. */
function turn(runId: string, deltas: string[]): HermesFrame[] {
  let seq = 0;
  const next = (name: string, payload: Record<string, unknown>): HermesFrame => ({
    name,
    payload: { seq: ++seq, run_id: runId, session_id: "sess_1", ts: 1, ...payload },
  });
  return [
    next("run.started", {}),
    next("message.started", { message: { id: "msg_1", role: "assistant" } }),
    ...deltas.map((delta) => next("assistant.delta", { message_id: "msg_1", delta })),
    next("assistant.completed", { message_id: "msg_1" }),
    next("run.completed", {}),
    next("done", {}),
  ];
}

function clientOver(body: string): BoltrigClient {
  const fetcher = async () =>
    new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
  return new BoltrigClient({ baseUrl: "https://cell.invalid", fetch: fetcher as unknown as typeof fetch });
}

test("a whole turn survives the SDK's follow validation", async () => {
  const frames = translate(turn("run_a", ["Hel", "lo"]), "conv_1");
  const seen: ChatFollowFrame[] = [];
  const client = clientOver(asSseBody(frames));
  const result = await client.followConversation("conv_1", (frame: ChatFollowFrame) => seen.push(frame), { since: 0 });

  assert.equal(result.status, "ended");
  assert.deepEqual(seen.map((f) => f.event.type),
    ["message_start", "text_delta", "text_delta", "message_end"]);
  assert.equal(result.cursor, seen[seen.length - 1]!.cursor);
});

test("the cursor does not regress across runs, which raw Hermes seq does", async () => {
  // Hermes restarts seq at 1 for every run: `seq = 0` lives inside the request
  // handler. Feeding that through raw is the bug this composition prevents.
  const raw = [...turn("run_a", ["one"]), ...turn("run_b", ["two"])];
  const seqs = raw.map((f) => Number(f.payload.seq));
  assert.ok(seqs.indexOf(1) !== seqs.lastIndexOf(1), "the fixture must contain a real seq restart");

  const clock = new CursorClock();
  const frames = translate(raw, "conv_1", clock);
  const cursors = frames.map((f) => f.cursor);
  for (let i = 1; i < cursors.length; i += 1) {
    assert.ok(cursors[i]! > cursors[i - 1]!, `cursor ${cursors[i]} followed ${cursors[i - 1]}`);
  }

  const client = clientOver(asSseBody(frames));
  const result = await client.followConversation("conv_1", () => {}, { since: 0 });
  assert.equal(result.status, "ended");
});

test("a reattach continues the count instead of starting again", async () => {
  const first = new CursorClock();
  const before = translate(turn("run_a", ["one"]), "conv_1", first);
  const last = before[before.length - 1]!.cursor;

  // A new connection, seeded with what the last one saw.
  const resumed = new CursorClock(first.seenRuns);
  const after = translate(turn("run_b", ["two"]), "conv_1", resumed);
  assert.ok(after[0]!.cursor > last, "the second connection must not rewind");

  const client = clientOver(asSseBody(after));
  const result = await client.followConversation("conv_1", () => {}, { since: last });
  assert.equal(result.status, "ended");
});

test("every cursor is a non-negative safe integer, which the SDK requires", () => {
  const clock = new CursorClock();
  const frames = translate([...turn("a", ["x"]), ...turn("b", ["y"]), ...turn("c", ["z"])], "c1", clock);
  for (const frame of frames) {
    assert.ok(Number.isSafeInteger(frame.cursor) && frame.cursor >= 0, String(frame.cursor));
  }
  // And still safe at the far end of the budget.
  const far = new CursorClock(Array.from({ length: 4096 }, (_, i) => `run_${i}`));
  assert.ok(Number.isSafeInteger(far.cursorFor("run_4095", MAX_SEQ_PER_RUN)));
});

test("a run that overruns its budget saturates rather than overtaking the next", () => {
  const clock = new CursorClock();
  const overrun = clock.cursorFor("run_a", MAX_SEQ_PER_RUN + 5_000);
  const next = clock.cursorFor("run_b", 1);
  assert.ok(next > overrun, "a saturated cursor must still be below the next run's");
});

test("an agent error is visible, not silent", () => {
  const events = toChatEvents(
    { name: "error", payload: { run_id: "r1", message: "provider refused the request" } },
    "conv_1",
  );
  assert.deepEqual(events.map((e) => e.type), ["text_delta", "message_end"]);
  assert.equal((events[0] as { degraded?: boolean }).degraded, true);
  // event_unavailable would have been the tempting mapping and the normaliser
  // ignores it outright, so the turn would end with no answer and no reason.
  assert.ok(!events.some((e) => e.type === "event_unavailable"));
});

test("thinking is reasoning, and a real tool is a tool", () => {
  const thinking = toChatEvents(
    { name: "tool.progress", payload: { run_id: "r", tool_name: "_thinking", delta: "hmm" } }, "c");
  assert.equal(thinking[0]!.type, "reasoning_delta");
  const tool = toChatEvents(
    { name: "tool.progress", payload: { run_id: "r", tool_name: "web_search", message_id: "m" } }, "c");
  assert.equal(tool[0]!.type, "tool_call");
});

test("an event this shim has never seen is reported, not dropped silently", () => {
  const events = toChatEvents({ name: "hermes.something.new", payload: { run_id: "r" } }, "c");
  assert.deepEqual(events.map((e) => e.type), ["event_unavailable"]);
});

test("two events from one frame do not share a cursor", () => {
  const frames = translate(
    [{ name: "error", payload: { seq: 4, run_id: "r1", message: "boom" } }], "c1");
  assert.equal(frames.length, 2);
  assert.ok(frames[1]!.cursor > frames[0]!.cursor);
});

/* --- negative controls: proof that the thing under test can fail ---------- */

test("NEGATIVE CONTROL: raw Hermes seq, used as the cursor, is rejected", async () => {
  // The whole reason the cursor is composed. This feeds Hermes's own per-run
  // seq straight through, exactly as a naive adapter would, and the SDK kills
  // the stream. If this test ever passes silently, the validation stopped
  // running and every other test here proves nothing.
  const raw = [...turn("run_a", ["one"]), ...turn("run_b", ["two"])];
  const naive = raw
    .flatMap((frame) => toChatEvents(frame, "conv_1")
      .map((event) => ({ cursor: Number(frame.payload.seq), event })));
  const client = clientOver(asSseBody(naive));
  await assert.rejects(
    client.followConversation("conv_1", () => {}, { since: 0 }),
    /cursor regressed/i,
  );
});

test("NEGATIVE CONTROL: a frame with no cursor is rejected", async () => {
  const client = clientOver(`data: ${JSON.stringify({ event: { type: "text_delta", delta: "x" } })}\n\n`);
  await assert.rejects(
    client.followConversation("conv_1", () => {}, { since: 0 }),
    /Invalid chat follow frame/i,
  );
});


/* --- the run stream, which numbers nothing ------------------------------- */

/** A live run as `/v1/runs/{run_id}/events` writes it: the name is INSIDE the
 *  object, and there is no seq anywhere. Taken from api_server.py's _push. */
function runStream(runId: string): HermesFrame[] {
  return [
    { event: "message.delta", run_id: runId, timestamp: 1, delta: "Hel" },
    { event: "message.delta", run_id: runId, timestamp: 1, delta: "lo" },
    { event: "tool.started", run_id: runId, timestamp: 1, tool: "web_search", preview: "..." },
    { event: "tool.completed", run_id: runId, timestamp: 1, tool: "web_search", duration: 0.4, error: false },
    { event: "run.completed", run_id: runId, timestamp: 1 },
  ].map((raw) => frameFromRunEvent(raw as Record<string, unknown>));
}

test("the run stream, which carries no counter at all, still yields a valid cursor", async () => {
  const frames = translateRunStream(runStream("run_live"), "conv_1");
  assert.deepEqual(frames.map((f) => f.event.type),
    ["text_delta", "text_delta", "tool_call", "tool_result", "message_end"]);
  const client = clientOver(asSseBody(frames));
  const result = await client.followConversation("conv_1", () => {}, { since: 0 });
  assert.equal(result.status, "ended");
});

test("one clock spans both streams without rewinding", async () => {
  const clock = new CursorClock();
  const first = translate(turn("run_a", ["one"]), "conv_1", clock);
  const second = translateRunStream(runStream("run_b"), "conv_1", clock);
  const all = [...first, ...second];
  for (let i = 1; i < all.length; i += 1) {
    assert.ok(all[i]!.cursor > all[i - 1]!.cursor, `${all[i]!.cursor} followed ${all[i - 1]!.cursor}`);
  }
  const client = clientOver(asSseBody(all));
  assert.equal((await client.followConversation("conv_1", () => {}, { since: 0 })).status, "ended");
});

test("an approval becomes a card the person can answer", () => {
  const events = toChatEvents(frameFromRunEvent({
    event: "approval.request", run_id: "run_x", tool: "shell",
    command: "rm -rf /tmp/build", choices: ["once", "session", "always", "deny"],
  }), "conv_1");
  assert.equal(events.length, 1);
  const hitl = events[0] as { type: string; hitl_request_id: string; options?: string[] };
  assert.equal(hitl.type, "hitl");
  // Hermes resolves an approval at POST /v1/runs/{run_id}/approval, so the run
  // id is the only handle there is - and the card must carry it.
  assert.equal(hitl.hitl_request_id, "run_x");
  assert.deepEqual(hitl.options, ["once", "session", "always", "deny"]);
});

test("a cancelled run ends the turn as cancelled, not as an answer", () => {
  const events = toChatEvents(frameFromRunEvent({ event: "run.cancelled", run_id: "r" }), "c");
  assert.deepEqual(events.map((e) => e.type), ["cancelled"]);
});

test("a failed run is degraded and ended, never silent", () => {
  const events = toChatEvents(
    frameFromRunEvent({ event: "run.failed", run_id: "r", error: "context length exceeded" }), "c");
  assert.deepEqual(events.map((e) => e.type), ["text_delta", "message_end"]);
  assert.equal((events[0] as { degraded?: boolean }).degraded, true);
  assert.match((events[0] as { delta: string }).delta, /context length/);
});

test("approval.responded adds nothing, because the card resolves itself", () => {
  assert.deepEqual(toChatEvents(frameFromRunEvent({ event: "approval.responded", run_id: "r" }), "c"), []);
});
