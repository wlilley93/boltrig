/**
 * Head client: a faithful TypeScript port of the pure (non-TTY) parts of
 * `boltrig/api/chat_cli.py` - SSE parsing, event render dispatch, chat turns,
 * and HITL respond/answer. Rendering knowledge lives HERE, in the head, not in
 * the event schema (the streaming contract); verb outputs stay data.
 *
 * Auth is a PAT bearer (`Authorization: Bearer <token>`), same as the Python
 * CLI; the token is never logged or embedded in error messages.
 */

import { KernelApiError, kernelPost, raiseForStatus, resolveToken, type FetchLike, type KernelRequestOptions } from "./http.js";

export type ChatEvent = Record<string, unknown>;

export class ChatHeadError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ChatHeadError";
  }
}

/**
 * Incremental `data:`-only SSE parser for /v1/chat. Comments and malformed /
 * non-object payloads are dropped, never fatal (port of chat_cli.py:SseParser).
 */
export class SseParser {
  private data: string[] = [];

  /** Feed one line (without its newline). Returns a parsed event when a blank
   * line completes a frame, otherwise null. */
  feed(line: string): ChatEvent | null {
    if (line === "") return this.flush();
    if (line.startsWith("data:")) {
      this.data.push(line.slice("data:".length).replace(/^ +/, ""));
    }
    return null; // comments / event: / id: fields carry nothing we render
  }

  /** Emit any buffered frame (end of stream). */
  flush(): ChatEvent | null {
    if (this.data.length === 0) return null;
    const payload = this.data.join("\n");
    this.data = [];
    try {
      const event: unknown = JSON.parse(payload);
      if (event !== null && typeof event === "object" && !Array.isArray(event)) {
        return event as ChatEvent;
      }
      return null;
    } catch {
      return null;
    }
  }
}

/** Yield the events of a streaming SSE line source as they arrive
 * (port of chat_cli.py:parse_sse). */
export async function* parseSse(lines: AsyncIterable<string>): AsyncGenerator<ChatEvent> {
  const parser = new SseParser();
  for await (const line of lines) {
    const event = parser.feed(line);
    if (event !== null) yield event;
  }
  const tail = parser.flush();
  if (tail !== null) yield tail;
}

/**
 * One event's rendering - a string to write verbatim (deltas stream inline),
 * or null (message_start, heartbeat, unknown types). Port of
 * chat_cli.py:render_event. Heads may dispatch on `type` themselves instead;
 * this is the reference rendering.
 */
export function renderEvent(event: ChatEvent): string | null {
  const etype = event.type;
  if (etype === "text_delta" || etype === "reasoning_delta") {
    return String(event.delta ?? "");
  }
  if (etype === "tool_call") {
    const tool = event.tool ?? event.verb ?? "?";
    const argsSummary = (event.args_summary ?? {}) as Record<string, unknown>;
    const keys = Array.isArray(argsSummary.keys) ? argsSummary.keys : [];
    const args = keys.length > 0 ? `(${keys.map(String).join(", ")})` : "";
    return `\n[tool] ${String(tool)}${args}\n`;
  }
  if (etype === "tool_result") {
    return `[tool] -> ${String(event.status ?? "?")}\n`;
  }
  if (etype === "hitl") {
    const rid = event.hitl_request_id ?? "?";
    const kind = event.kind ?? "approval";
    const question = event.question ?? "";
    return (
      `\n*** HUMAN INPUT NEEDED (${String(kind)}): ${String(question)}\n` +
      `*** respond: /approve ${String(rid)}  or  /deny ${String(rid)}\n`
    );
  }
  if (etype === "question") {
    const qid = event.question_id ?? "?";
    const prompt = event.prompt ?? "";
    const choices = Array.isArray(event.choices) ? event.choices : [];
    const hint = choices.length > 0 ? ` (choices: ${choices.map(String).join(", ")})` : "";
    return (
      `\n*** QUESTION: ${String(prompt)}${hint}\n` +
      `*** answer: /answer ${String(qid)} <your answer>\n`
    );
  }
  if (etype === "subagent") {
    const name = event.name ?? event.child_run_id ?? "?";
    return `\n[subagent] ${String(name)}: ${String(event.task ?? "")}\n`;
  }
  if (etype === "cancelled") return "\n(cancelled)\n";
  if (etype === "message_end") return "\n";
  return null;
}

/** Split a byte stream into lines, carrying partial tails across chunks. */
async function* streamLines(body: ReadableStream<Uint8Array>): AsyncGenerator<string> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let nl: number;
      while ((nl = buffer.indexOf("\n")) !== -1) {
        let line = buffer.slice(0, nl);
        buffer = buffer.slice(nl + 1);
        if (line.endsWith("\r")) line = line.slice(0, -1);
        yield line;
      }
    }
    buffer += decoder.decode();
    if (buffer.endsWith("\r")) buffer = buffer.slice(0, -1);
    if (buffer !== "") yield buffer;
  } finally {
    reader.releaseLock();
  }
}

export interface StreamTurnOptions extends KernelRequestOptions {
  message: string;
  conversationId?: string;
}

/**
 * POST one chat turn and yield its SSE events as they arrive
 * (port of chat_cli.py:stream_turn). No read timeout: heartbeats keep a quiet
 * turn's stream alive server-side.
 */
export async function* streamTurn(opts: StreamTurnOptions): AsyncGenerator<ChatEvent> {
  const doFetch = opts.fetch ?? (fetch as unknown as FetchLike);
  const body: Record<string, unknown> = { message: opts.message };
  if (opts.conversationId) body.conversation_id = opts.conversationId;
  let resp: Awaited<ReturnType<FetchLike>>;
  try {
    resp = await doFetch(`${opts.server.replace(/\/+$/, "")}/v1/chat`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${resolveToken(opts.token)}`,
      },
      body: JSON.stringify(body),
      ...(opts.signal ? { signal: opts.signal } : {}),
    });
  } catch (exc) {
    throw new ChatHeadError(
      `cannot reach the kernel at ${opts.server} (${exc instanceof Error ? exc.name : "error"}) - is the stack running?`,
    );
  }
  if (resp.status !== 200) {
    let payload: Record<string, unknown> = {};
    try {
      const parsed = await resp.json();
      if (parsed !== null && typeof parsed === "object") payload = parsed as Record<string, unknown>;
    } catch {
      /* generic message below */
    }
    if (resp.status === 401 || resp.status === 403) {
      throw new ChatHeadError(`authentication failed (HTTP ${resp.status}) - check the token`);
    }
    const reason = typeof payload.reason === "string" ? payload.reason
      : typeof payload.error === "string" ? payload.error : "";
    throw new ChatHeadError(`request failed (HTTP ${resp.status})${reason ? `: ${reason}` : ""}`);
  }
  const stream = resp.body;
  if (stream === null || stream === undefined || typeof (stream as ReadableStream<Uint8Array>).getReader !== "function") {
    throw new ChatHeadError("chat response had no stream body");
  }
  yield* parseSse(streamLines(stream as ReadableStream<Uint8Array>));
}

/** Approve/deny a pending HITL request via /v1/hitl/{id}/respond
 * (port of chat_cli.py:respond_hitl). */
export async function respondHitl(
  opts: KernelRequestOptions & { requestId: string; decision: "approve" | "deny"; notes?: string },
): Promise<Record<string, unknown>> {
  const { status, payload } = await kernelPost(
    opts,
    `/v1/hitl/${encodeURIComponent(opts.requestId)}/respond`,
    { decision: opts.decision, notes: opts.notes ?? "" },
  );
  await raiseForStatus(status, payload);
  return payload;
}

/** Answer an agent's clarifying question via /v1/hitl/{id}/answer
 * (port of chat_cli.py:answer_question). */
export async function answerQuestion(
  opts: KernelRequestOptions & { questionId: string; answer: string },
): Promise<Record<string, unknown>> {
  const { status, payload } = await kernelPost(
    opts,
    `/v1/hitl/${encodeURIComponent(opts.questionId)}/answer`,
    { answer: opts.answer },
  );
  await raiseForStatus(status, payload);
  return payload;
}
