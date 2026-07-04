// Server-Sent Events transport over the kernel HTTP surface. Two entry points
// are exposed: streamChat (POST /v1/chat) and streamRunEvents (GET /v1/runs/...).
// Both use the same frame pump with idle-timeout hardening so a dead stream
// never hangs the UI.

import {
  ApiError,
  BASE,
  csrfHeaders,
  identityHeaders,
  parseBody,
} from "@/api/transport";
import type { ChatEvent, ChatRequest } from "@/api/types";

// Raised when an SSE stream goes silent past the idle window: no frame, no
// heartbeat, not even the server's close. It carries status 0 so apiReason
// treats it as a connectivity fault, and the caller offers reconnect/replay.
export class StreamIdleError extends ApiError {
  constructor(idleMs: number) {
    super(0, `stream idle for ${Math.round(idleMs / 1000)}s (no data)`, null);
    this.name = "StreamIdleError";
  }
}

// A dead SSE stream (server wedged, proxy holding the socket open) must never
// hang the UI forever. If no byte arrives within this window we abandon the read
// and surface a StreamIdleError so the caller can reconnect with replay. The
// window resets on every chunk, including the SSE heartbeat comment (": ping"),
// so a live-but-quiet turn is not falsely tripped.
const STREAM_IDLE_MS = 120_000;

// Terminal events that end an SSE turn. Seeing one lets us close the reader
// eagerly instead of waiting on the socket's own (possibly buffered) close.
function isTerminalEvent(ev: ChatEvent): boolean {
  return ev.type === "message_end" || ev.type === "cancelled";
}

// Race a single reader.read() against the idle window. On timeout the reader is
// cancelled (releasing the socket) and a StreamIdleError is thrown.
async function readWithIdleTimeout(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  idleMs: number,
): Promise<ReadableStreamReadResult<Uint8Array>> {
  if (!idleMs || idleMs <= 0) return reader.read();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const idle = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => reject(new StreamIdleError(idleMs)), idleMs);
  });
  try {
    return await Promise.race([reader.read(), idle]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}

// The shared SSE pump: read frames delimited by a blank line, buffering partial
// frames across chunks, dispatch each parsed ChatEvent, and close cleanly on a
// terminal event (message_end / cancelled) or the server's own stream close. An
// idle-timeout guard bounds a dead stream; an AbortSignal cancels immediately.
async function pumpSse(
  res: Response,
  onEvent: (event: ChatEvent) => void,
  idleMs: number,
): Promise<void> {
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminated = false;
  try {
    for (;;) {
      const { value, done } = await readWithIdleTimeout(reader, idleMs);
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // Normalise CRLF so the blank-line frame delimiter is always "\n\n".
      buffer = buffer.replace(/\r\n/g, "\n");
      let idx: number;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        const ev = emitFrame(frame, onEvent);
        if (ev && isTerminalEvent(ev)) {
          terminated = true;
          break;
        }
      }
      if (terminated) break;
    }
    if (!terminated) {
      // Flush any trailing frame that arrived without a closing blank line.
      buffer += decoder.decode();
      buffer = buffer.replace(/\r\n/g, "\n").trim();
      if (buffer) emitFrame(buffer, onEvent);
    }
  } finally {
    // Release the socket on every exit path (terminal event, idle timeout,
    // abort). A double cancel is a harmless no-op.
    void reader.cancel().catch(() => {});
  }
}

// POST /v1/chat is a Server-Sent Events stream: each `data:` line is one JSON
// ChatEvent. onEvent is called once per parsed event; pass an AbortSignal to
// cancel (the partial result still persists kernel-side and can be re-fetched
// via conversation()). The stream closes cleanly on message_end / cancelled and
// is bounded by an idle-timeout guard so a dead stream never hangs the UI.
export async function streamChat(
  body: ChatRequest,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const headers: Record<string, string> = {
    ...identityHeaders(),
    ...csrfHeaders("POST"),
    "content-type": "application/json",
    accept: "text/event-stream",
  };

  let res: Response;
  try {
    res = await fetch(`${BASE}/v1/chat`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    const reason = err instanceof Error ? err.message : "network error";
    throw new ApiError(0, `chat stream failed: ${reason}`, null);
  }

  if (!res.ok || !res.body) {
    const parsed = await parseBody(res);
    throw new ApiError(res.status, `POST /v1/chat -> ${res.status}`, parsed);
  }

  await pumpSse(res, onEvent, STREAM_IDLE_MS);
}

// Subscribe to a run's event stream (Round Eleven, the Run drawer / live canvas).
// follow=false (default) yields the current snapshot then ends; follow=true keeps
// streaming live until the run closes. Same SSE frame format + hardening as
// streamChat (clean terminal close, idle-timeout guard). Because the kernel relay
// replays a run's events on subscribe, this doubles as the reconnect/replay path.
export async function streamRunEvents(
  runId: string,
  onEvent: (event: ChatEvent) => void,
  opts: { signal?: AbortSignal; follow?: boolean } = {},
): Promise<void> {
  const headers: Record<string, string> = {
    ...identityHeaders(),
    accept: "text/event-stream",
  };
  const q = opts.follow ? "?follow=1" : "";
  let res: Response;
  try {
    res = await fetch(`${BASE}/v1/runs/${encodeURIComponent(runId)}/events${q}`, {
      method: "GET",
      headers,
      signal: opts.signal,
    });
  } catch (err) {
    const reason = err instanceof Error ? err.message : "network error";
    throw new ApiError(0, `run events stream failed: ${reason}`, null);
  }
  if (!res.ok || !res.body) {
    const parsed = await parseBody(res);
    throw new ApiError(res.status, `GET /v1/runs/${runId}/events -> ${res.status}`, parsed);
  }
  // A snapshot (follow=false) ends on the server's stream close, so keep the idle
  // guard for the live-follow case only; a snapshot without a heartbeat is fine.
  await pumpSse(res, onEvent, opts.follow ? STREAM_IDLE_MS : 0);
}

// Parse one SSE frame and dispatch its ChatEvent. Returns the parsed event (or
// null for a heartbeat / unparseable / [DONE] frame) so the pump can detect a
// terminal event and close eagerly.
function emitFrame(
  frame: string,
  onEvent: (event: ChatEvent) => void,
): ChatEvent | null {
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
  }
  if (dataLines.length === 0) return null;
  const payload = dataLines.join("\n").trim();
  if (!payload || payload === "[DONE]") return null;
  try {
    const ev = JSON.parse(payload) as ChatEvent;
    // A heartbeat is a keep-alive only: receiving its frame already reset the
    // idle-timeout guard (the guard resets on every reader.read that returns),
    // so we drop it here without dispatching. It must never reach a consumer or
    // land in the transcript - it is not rendered and not folded into a turn.
    if (ev.type === "heartbeat") return null;
    onEvent(ev);
    return ev;
  } catch {
    // Ignore an unparseable frame so one bad line never kills the stream.
    return null;
  }
}
