/** Hermes's event vocabularies, translated into the one v1's chat renders.
 *
 * WHY THIS FILE EXISTS. The v1 chat surface - transcript, tool receipts,
 * approval cards, steer queue - is written against a 20-variant `ChatEvent`
 * union and, on reattach, against `{cursor, event}` frames whose cursor must
 * never go backwards; the SDK throws and kills the stream if one does. Hermes
 * speaks two smaller vocabularies of its own. This is the whole translation,
 * and it is pure: no fetch, no DOM, no client. What talks to a cell is built on
 * top of it.
 *
 * HERMES SPEAKS TWICE, DIFFERENTLY. Read from the pinned cell image
 * (nousresearch/hermes-agent@sha256:4e4d6c60), gateway/platforms/api_server.py:
 *
 *   SESSION STREAM  POST /api/sessions/{id}/chat/stream
 *     SSE frames with a real `event:` name line. Payloads carry `seq`,
 *     `run_id`, `session_id`, `ts`. Names: run.started, message.started,
 *     assistant.delta, tool.progress, assistant.completed, run.completed,
 *     error, done.
 *
 *   RUN STREAM      GET /v1/runs/{run_id}/events
 *     Bare `data:` frames with the name INSIDE the object under `event`, and
 *     NO seq at all. Names: message.delta, reasoning.available, tool.started,
 *     tool.completed, approval.request, approval.responded, run.steered,
 *     run.completed, run.cancelled, run.failed, subagent.start,
 *     subagent.complete.
 *
 * THE RUN STREAM IS LIVE-ONLY. It attaches to an in-memory queue and 404s once
 * the run has ended - there is no replay and no `since`. So a reattach to a
 * finished turn is not a stream at all; it is the message list. The adapter
 * returns v1's own `idle` status in that case, which is a state the UI already
 * handles, rather than inventing a replay Hermes cannot serve.
 *
 * THE CURSOR IS COMPOSED, NOT COPIED. Session frames carry `seq`, but `seq = 0`
 * is initialised inside the request handler, so it restarts at 1 on every run;
 * run frames carry no counter at all. Either one used raw is the regression the
 * SDK refuses. So the cursor is (run ordinal << 20) + within-run count, which
 * is monotonic across runs by construction and needs no state beyond the list
 * of run ids seen. The negative controls in the tests feed raw seq through and
 * assert the SDK rejects it, so this claim is measured rather than argued.
 */

import type { ChatEvent } from "../types.js";

export const SEQ_BITS = 20;
export const MAX_SEQ_PER_RUN = 2 ** SEQ_BITS - 1;

/** One frame, whichever stream it came from, normalised to name + payload. */
export interface HermesFrame {
  name: string;
  payload: Record<string, unknown>;
}

export interface TranslatedFrame {
  cursor: number;
  event: ChatEvent;
}

/** A bare run-stream object (`{event: "...", ...}`) as a frame. */
export function frameFromRunEvent(raw: Record<string, unknown>): HermesFrame {
  return { name: String(raw?.event ?? ""), payload: raw ?? {} };
}

/** A session-stream frame, whose name arrived on the SSE `event:` line. */
export function frameFromSessionEvent(name: string, payload: Record<string, unknown>): HermesFrame {
  return { name, payload: payload ?? {} };
}

function text(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

/** Composes a monotonic cursor for a session out of per-run counters.
 *
 * The state is the run ids seen, in order. A new connection is constructed with
 * the ones the last connection knew about, so the count continues rather than
 * restarting - which is the whole point of `since`.
 */
export class CursorClock {
  private readonly runs: string[];
  private readonly counts = new Map<string, number>();

  constructor(knownRuns: readonly string[] = []) {
    this.runs = [...knownRuns];
  }

  get seenRuns(): readonly string[] {
    return this.runs;
  }

  private ordinal(runId: string): number {
    let index = this.runs.indexOf(runId);
    if (index < 0) {
      index = this.runs.length;
      this.runs.push(runId);
    }
    return index;
  }

  /** For a stream that numbers its own frames (the session stream's `seq`). */
  cursorFor(runId: string, seq: number): number {
    // Saturating, not wrapping: a cursor that stalls at the top of its run is
    // recoverable, one that overtakes the next run's range is a regression the
    // moment that run starts.
    const bounded = Math.max(0, Math.min(Math.trunc(seq), MAX_SEQ_PER_RUN));
    return this.ordinal(runId) * (MAX_SEQ_PER_RUN + 1) + bounded;
  }

  /** For a stream that does not number anything (the run stream). */
  nextCursor(runId: string): number {
    const seen = (this.counts.get(runId) ?? 0) + 1;
    this.counts.set(runId, seen);
    return this.cursorFor(runId, seen);
  }
}

/** One Hermes frame as zero, one or two v1 events.
 *
 * ZERO IS A REAL ANSWER. run.started, assistant.completed and done carry
 * nothing v1 renders; inventing an event for them would put rows in the
 * transcript that never happened.
 *
 * TWO, FOR A FAILURE. v1's union has no error event. `event_unavailable` means
 * "this client cannot render that frame" and the normaliser ignores it
 * outright, so routing an agent failure there makes the failure INVISIBLE - the
 * turn stops with no answer and no reason. The visible seam is `degraded`,
 * which the transcript renders as "this response used a degraded fallback;
 * treat its result as incomplete". So a failure becomes a degraded delta
 * carrying Hermes's own redacted message, then the end of the turn.
 */
export function toChatEvents(frame: HermesFrame, conversationId: string): ChatEvent[] {
  const payload = frame.payload ?? {};
  const runId = text(payload.run_id);
  const failed = (reason: string): ChatEvent[] => ([
    { type: "text_delta", delta: reason, degraded: true },
    { type: "message_end", run_id: runId },
  ]);

  switch (frame.name) {
    /* ---- session stream ---- */
    case "message.started":
      return [{ type: "message_start", run_id: runId, conversation_id: conversationId }];
    case "assistant.delta":
      return [{ type: "text_delta", delta: text(payload.delta) }];
    case "tool.progress": {
      // `_thinking` is Hermes's name for the model's own reasoning preview, not
      // a tool. Rendering it as a tool call would invent a call that never
      // happened, and v1 has a reasoning lane for exactly this.
      const tool = text(payload.tool_name);
      if (tool === "" || tool === "_thinking") {
        return [{ type: "reasoning_delta", delta: text(payload.delta) }];
      }
      return [{
        type: "tool_call",
        run_id: runId,
        call_id: `${text(payload.message_id, runId)}:${tool}`,
        tool,
      }];
    }
    case "error":
      return failed(text(payload.message) || text(payload.error) || "the agent failed");

    /* ---- run stream ---- */
    case "message.delta":
      return [{ type: "text_delta", delta: text(payload.delta) }];
    case "reasoning.available":
      return [{ type: "reasoning_delta", delta: text(payload.text) }];
    case "tool.started":
      return [{
        type: "tool_call",
        run_id: runId,
        call_id: `${runId}:${text(payload.tool)}`,
        tool: text(payload.tool),
      }];
    case "tool.completed":
      return [{
        type: "tool_result",
        run_id: runId,
        call_id: `${runId}:${text(payload.tool)}`,
        verb: text(payload.tool),
        // Hermes reports only whether it errored. Anything richer here would be
        // invented, and the receipt renders the status verbatim.
        status: payload.error === true ? "error" : "ok",
      }];
    case "approval.request":
      // Hermes gates one approval per RUN and resolves it at
      // POST /v1/runs/{run_id}/approval with a `choice`, so the run id IS the
      // request id - there is no separate handle to carry.
      return [{
        type: "hitl",
        hitl_request_id: runId,
        question: text(payload.command) || text(payload.tool) || "The agent needs approval.",
        options: Array.isArray(payload.choices) ? payload.choices.map((c) => String(c)) : undefined,
        verb: text(payload.tool) || undefined,
      }];
    case "approval.responded":
      // The card resolves itself from the run's state; a second hitl frame
      // would re-open it.
      return [];
    case "run.steered":
      return [{ type: "steer_consumed", run_id: runId, conversation_id: conversationId }];
    case "subagent.start":
      return [{
        type: "subagent",
        child_run_id: text(payload.child_run_id, runId),
        task: text(payload.task) || text(payload.description) || "subagent",
      }];
    case "subagent.complete":
      return [{ type: "subagent_end", child_run_id: text(payload.child_run_id, runId) } as ChatEvent];
    case "run.cancelled":
      return [{ type: "cancelled", run_id: runId }];
    case "run.failed":
      return failed(text(payload.error) || text(payload.message) || "the run failed");

    /* ---- both ---- */
    case "run.completed":
      return [{ type: "message_end", run_id: runId }];
    case "run.started":
    case "assistant.completed":
    case "done":
      return [];

    default:
      // An event this shim has not been taught. NAMED rather than dropped: the
      // normaliser ignores event_unavailable, so an unknown frame costs a gap
      // in the transcript and never a wrong render - and a client that counts
      // them can tell somebody the vocabulary moved.
      return [{ type: "event_unavailable", reason: "unsupported_event" }];
  }
}

/** Session-stream frames (which number themselves) into cursored frames. */
export function translate(
  frames: readonly HermesFrame[],
  conversationId: string,
  clock: CursorClock = new CursorClock(),
): TranslatedFrame[] {
  return expand(frames, conversationId, clock, (frame, runId) =>
    clock.cursorFor(runId, Number(frame.payload?.seq ?? 0)));
}

/** Run-stream frames (which number nothing) into cursored frames. */
export function translateRunStream(
  frames: readonly HermesFrame[],
  conversationId: string,
  clock: CursorClock = new CursorClock(),
): TranslatedFrame[] {
  return expand(frames, conversationId, clock, (_frame, runId) => clock.nextCursor(runId));
}

function expand(
  frames: readonly HermesFrame[],
  conversationId: string,
  clock: CursorClock,
  cursorOf: (frame: HermesFrame, runId: string) => number,
): TranslatedFrame[] {
  const out: TranslatedFrame[] = [];
  for (const frame of frames) {
    const runId = text(frame.payload?.run_id);
    const events = toChatEvents(frame, conversationId);
    if (events.length === 0) continue;
    // One frame can carry two events, and they must not share a cursor: the
    // SDK tolerates equal cursors, but a client resuming from `since` would
    // then replay or skip half a pair.
    const base = cursorOf(frame, runId);
    events.forEach((event, index) => out.push({ cursor: base + index, event }));
  }
  return out;
}

/** The frames as an SSE body, the way a cursored endpoint would write them. */
export function asSseBody(frames: readonly TranslatedFrame[]): string {
  return frames.map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join("");
}
