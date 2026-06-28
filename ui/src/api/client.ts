// Typed fetch client over the kernel HTTP surface. Every request carries the
// dev identity headers (x-nankle-*) read from the identity store. Paths are
// relative: the Vite dev server and the nginx prod image both proxy /v1 and
// /healthz to the kernel.

import { getIdentity } from "../identity";
import type {
  AuditTreeResponse,
  CapabilitiesResponse,
  ChatEvent,
  ChatRequest,
  ConversationResponse,
  ConversationsResponse,
  HealthResponse,
  HITLListResponse,
  InvokeRequest,
  InvokeResult,
  RespondResult,
  SpawnRequest,
  WorkResponse,
  WorkStatus,
} from "./types";

// Optional base prefix (e.g. when the UI is mounted under a sub-path).
const BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

function identityHeaders(): Record<string, string> {
  const id = getIdentity();
  return {
    "x-nankle-tenant": id.tenant,
    "x-nankle-subject": id.subject,
    "x-nankle-grants": id.grants,
    "x-nankle-role": id.role,
  };
}

async function parseBody(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  // when true, a non-2xx response is returned (parsed) instead of throwing
  tolerateStatus?: boolean;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, tolerateStatus = false } = opts;
  const headers: Record<string, string> = { ...identityHeaders() };
  if (body !== undefined) headers["content-type"] = "application/json";

  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (err) {
    const reason = err instanceof Error ? err.message : "network error";
    throw new ApiError(0, `request failed: ${reason}`, null);
  }

  const parsed = await parseBody(res);
  if (!res.ok && !tolerateStatus) {
    throw new ApiError(res.status, `${method} ${path} -> ${res.status}`, parsed);
  }
  return parsed as T;
}

export const api = {
  health(): Promise<HealthResponse> {
    return request<HealthResponse>("/healthz");
  },

  capabilities(noun?: string): Promise<CapabilitiesResponse> {
    const q = noun ? `?noun=${encodeURIComponent(noun)}` : "";
    return request<CapabilitiesResponse>(`/v1/capabilities${q}`);
  },

  // invoke returns one of several bodies keyed by status; never throws on a
  // documented non-2xx (202/403/503), only on transport/unexpected failures.
  invoke(req: InvokeRequest): Promise<InvokeResult> {
    return request<InvokeResult>("/v1/invoke", {
      method: "POST",
      body: req,
      tolerateStatus: true,
    });
  },

  spawn(req: SpawnRequest): Promise<unknown> {
    return request<unknown>("/v1/spawn", {
      method: "POST",
      body: req,
      tolerateStatus: true,
    });
  },

  work(status?: WorkStatus): Promise<WorkResponse> {
    const q = status ? `?status=${encodeURIComponent(status)}` : "";
    return request<WorkResponse>(`/v1/work${q}`);
  },

  hitl(): Promise<HITLListResponse> {
    return request<HITLListResponse>("/v1/hitl");
  },

  respondHitl(
    id: string,
    body: { decision: string; notes?: string },
  ): Promise<RespondResult> {
    return request<RespondResult>(`/v1/hitl/${encodeURIComponent(id)}/respond`, {
      method: "POST",
      body: { decision: body.decision, notes: body.notes ?? "" },
    });
  },

  auditTree(runId: string): Promise<AuditTreeResponse> {
    return request<AuditTreeResponse>(
      `/v1/audit/tree/${encodeURIComponent(runId)}`,
    );
  },

  // Conversation list + transcript for the Chat panel. The transcript persists
  // server-side, so re-opening a conversation always shows the completed turn.
  conversations(): Promise<ConversationsResponse> {
    return request<ConversationsResponse>("/v1/conversations");
  },

  conversation(id: string): Promise<ConversationResponse> {
    return request<ConversationResponse>(
      `/v1/conversations/${encodeURIComponent(id)}`,
    );
  },
};

// POST /v1/chat is a Server-Sent Events stream: each `data:` line is one JSON
// ChatEvent. We read the body with a ReadableStream reader and parse frames
// delimited by a blank line, buffering partial frames across chunks. onEvent is
// called once per parsed event; pass an AbortSignal to cancel (the partial
// result still persists kernel-side and can be re-fetched via conversation()).
export async function streamChat(
  body: ChatRequest,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const headers: Record<string, string> = {
    ...identityHeaders(),
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

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // Normalise CRLF so the blank-line frame delimiter is always "\n\n".
    buffer = buffer.replace(/\r\n/g, "\n");
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      emitFrame(frame, onEvent);
    }
  }

  // Flush any trailing frame that arrived without a closing blank line.
  buffer += decoder.decode();
  buffer = buffer.replace(/\r\n/g, "\n").trim();
  if (buffer) emitFrame(buffer, onEvent);
}

function emitFrame(frame: string, onEvent: (event: ChatEvent) => void): void {
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
  }
  if (dataLines.length === 0) return;
  const payload = dataLines.join("\n").trim();
  if (!payload || payload === "[DONE]") return;
  try {
    onEvent(JSON.parse(payload) as ChatEvent);
  } catch {
    // Ignore an unparseable frame so one bad line never kills the stream.
  }
}
