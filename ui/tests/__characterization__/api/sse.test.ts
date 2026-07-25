import { afterEach, describe, expect, it, vi } from "vitest";

import { streamChat, streamRunEvents } from "@/api/client";
import type { ChatEvent } from "@/api/types";

// A kernel-shaped SSE response: one `data:` frame per event, then the server's
// own close. StreamingResponse frames exactly like this.
function sseResponse(events: unknown[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const ev of events) controller.enqueue(encoder.encode(`data: ${JSON.stringify(ev)}\n\n`));
      controller.close();
    },
  });
  return new Response(body, {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
}

function stubFetch(res: Response): void {
  vi.stubGlobal("fetch", vi.fn(async () => res));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api/sse (POST /v1/chat is a multi-turn stream)", () => {
  it("keeps reading past message_end so a steered second turn is not dropped", async () => {
    // US-CHAT-15: a steer queued behind the caller's turn is drained as a SECOND
    // turn on the SAME response - steer_consumed, a fresh message_start, the
    // whole turn - after the first message_end.
    const frames = [
      { type: "message_start", run_id: "r1", conversation_id: "c1" },
      { type: "text_delta", delta: "one" },
      { type: "message_end", run_id: "r1" },
      { type: "steer_consumed", run_id: "r2", conversation_id: "c1", message_id: "m2" },
      { type: "message_start", run_id: "r2", conversation_id: "c1" },
      { type: "text_delta", delta: "two" },
      { type: "message_end", run_id: "r2" },
    ];
    stubFetch(sseResponse(frames));

    const seen: ChatEvent[] = [];
    await streamChat({ message: "one", conversation_id: "c1" }, (ev) => seen.push(ev));

    expect(
      seen.map((ev) => ev.type),
      "the chat pump closed the stream at the first message_end, dropping the steered turn the kernel drains onto the SAME response (and killing it server-side, because that response generator is what drives it)",
    ).toEqual(frames.map((f) => f.type));
  });

  it("returns the 202 queued ack instead of pumping it as an empty stream", async () => {
    const ack = { status: "queued", conversation_id: "c1", message_id: "m9", run_id: "r1" };
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify(ack), {
            status: 202,
            headers: { "content-type": "application/json" },
          }),
      ),
    );

    const seen: ChatEvent[] = [];
    const queued = await streamChat({ message: "steer", conversation_id: "c1" }, (ev) => seen.push(ev));

    expect(seen, "the 202 JSON ack must never be dispatched as turn events").toEqual([]);
    expect(
      queued,
      "the 202 queued ack was pumped through the SSE parser and swallowed, so a queued steer was indistinguishable from a turn that completed with no events",
    ).toEqual({
      status: "queued",
      conversation_id: "c1",
      message_id: "m9",
      run_id: "r1",
    });
  });

  it("resolves a streamed turn with null (nothing was queued)", async () => {
    stubFetch(sseResponse([{ type: "message_start", run_id: "r1", conversation_id: "c1" }, { type: "message_end", run_id: "r1" }]));
    const queued = await streamChat({ message: "one" }, () => {});
    expect(queued).toBeNull();
  });
});

describe("api/sse (GET /v1/runs/{id}/events still closes on a terminal event)", () => {
  it("stops at message_end on a run stream", async () => {
    // What this pins is that the two endpoints have SEPARATE end predicates and
    // that the run one still closes eagerly - not that the Run drawer depends on
    // it. Stated precisely because the honest version is narrower: `message_end`
    // is yielded onto the /v1/chat HTTP generator only and is never published to
    // the run relay, so in practice a real run stream settles on the relay's own
    // close and this arm does not fire there. It is `cancelled` that carries the
    // predicate's weight on this endpoint.
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      async start(controller) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify({ type: "message_end", run_id: "r1" })}\n\n`));
        await new Promise((r) => setTimeout(r, 20));
        try {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify({ type: "text_delta", delta: "late" })}\n\n`));
          controller.close();
        } catch {
          // the reader was cancelled first, which is the point of this test
        }
      },
    });
    stubFetch(new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } }));

    const seen: ChatEvent[] = [];
    await streamRunEvents("r1", (ev) => seen.push(ev), { follow: true });

    expect(seen.map((ev) => ev.type)).toEqual(["message_end"]);
  });
});
