/**
 * Shared HTTP plumbing for the registration client and the head client.
 * Kernel error envelope: the central handler returns a canonical JSON body
 * with `reason` / `error` keys; 401/403 means the token failed. The token is
 * NEVER part of an error message (mirrors chat_cli.py:_http_error).
 */

export type FetchLike = (
  input: string,
  init?: {
    method?: string;
    headers?: Record<string, string>;
    body?: string;
    signal?: AbortSignal;
  },
) => Promise<{
  status: number;
  headers: { getSetCookie?: () => string[]; get: (name: string) => string | null };
  json(): Promise<unknown>;
  text(): Promise<string>;
  body?: unknown;
}>;

export class KernelApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "KernelApiError";
  }
}

export interface KernelRequestOptions {
  server: string;
  /** A PAT (or session cookie via `cookie`). Resolved from
   * BOLTRIG_TOKEN / BOLTRIG_CLI_TOKEN when omitted. Never logged. */
  token?: string;
  /** A session cookie header value (from `login`), for session-only routes. */
  cookie?: string;
  fetch?: FetchLike;
  signal?: AbortSignal;
}

export function resolveToken(explicit?: string): string {
  const token = explicit ?? process.env.BOLTRIG_TOKEN ?? process.env.BOLTRIG_CLI_TOKEN;
  if (!token) {
    throw new KernelApiError(
      "no token: pass `token`, or set BOLTRIG_TOKEN / BOLTRIG_CLI_TOKEN (mint a PAT via /v1/me/tokens)",
      0,
    );
  }
  return token;
}

function baseUrl(server: string): string {
  return server.replace(/\/+$/, "");
}

export async function kernelPost(
  opts: KernelRequestOptions,
  path: string,
  body: Record<string, unknown>,
  extraHeaders?: Record<string, string>,
): Promise<{ status: number; payload: Record<string, unknown> }> {
  const doFetch = opts.fetch ?? (fetch as unknown as FetchLike);
  const headers: Record<string, string> = { "content-type": "application/json", ...extraHeaders };
  if (opts.cookie) headers.cookie = opts.cookie;
  else headers.authorization = `Bearer ${resolveToken(opts.token)}`;
  const resp = await doFetch(`${baseUrl(opts.server)}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    ...(opts.signal ? { signal: opts.signal } : {}),
  });
  return { status: resp.status, payload: await readPayload(resp) };
}

export async function kernelGet(
  opts: KernelRequestOptions,
  path: string,
): Promise<{ status: number; payload: Record<string, unknown> }> {
  const doFetch = opts.fetch ?? (fetch as unknown as FetchLike);
  const headers: Record<string, string> = {};
  if (opts.cookie) headers.cookie = opts.cookie;
  else headers.authorization = `Bearer ${resolveToken(opts.token)}`;
  const resp = await doFetch(`${baseUrl(opts.server)}${path}`, {
    method: "GET",
    headers,
    ...(opts.signal ? { signal: opts.signal } : {}),
  });
  return { status: resp.status, payload: await readPayload(resp) };
}

async function readPayload(resp: { json(): Promise<unknown>; text(): Promise<string> }): Promise<Record<string, unknown>> {
  try {
    const payload = await resp.json();
    return payload !== null && typeof payload === "object" && !Array.isArray(payload)
      ? (payload as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

/** One-line, user-facing HTTP failure. The token is never part of it. */
export async function raiseForStatus(status: number, payload: Record<string, unknown>): Promise<void> {
  if (status >= 200 && status < 300) return;
  const reason = typeof payload.reason === "string" ? payload.reason
    : typeof payload.error === "string" ? payload.error
    : "";
  if (status === 401 || status === 403) {
    throw new KernelApiError(
      `authentication failed (HTTP ${status}) - check the token / session`,
      status,
    );
  }
  throw new KernelApiError(`request failed (HTTP ${status})${reason ? `: ${reason}` : ""}`, status);
}
