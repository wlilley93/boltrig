// Typed fetch client over the kernel HTTP surface. Every request carries the
// dev identity headers (x-nankle-*) read from the identity store. Paths are
// relative: the Vite dev server and the nginx prod image both proxy /v1 and
// /healthz to the kernel.

import { getIdentity } from "../identity";
import type {
  AuditTreeResponse,
  CapabilitiesResponse,
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
};
