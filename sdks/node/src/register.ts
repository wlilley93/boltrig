/**
 * Registration client: authenticate to a Boltrig kernel and register this
 * app's MCP server as a governed, INERT adapter.
 *
 * The governed path (never a side door):
 *
 *   POST /v1/mcp/servers            -> the control verb control.mcp_server.register
 *                                      (platform_routes/adapters.py:46). Registers
 *                                      INERT pending the SEC-22 review gate.
 *   POST /v1/adapters/{id}/activate -> control.adapter.activate (adapters.py:30).
 *                                      High-consequence: drives HITL. The 202
 *                                      response carries a hitl_request_id; a human
 *                                      approves via /v1/hitl/{id}/respond, then the
 *                                      caller re-applies with that approval id.
 *
 * Credentials: registration takes a `credentialRef` NAMING a secret-store key
 * (with the default `env` store, an env var readable BY THE KERNEL PROCESS).
 * Raw secret material is refused kernel-side (control_mcp.py:38-43), so this
 * client has no parameter that could carry one.
 */

import {
  KernelApiError,
  baseUrl,
  kernelGet,
  kernelPost,
  raiseForStatus,
  type FetchLike,
  type KernelRequestOptions,
} from "./http.js";

/** A pending-HITL outcome (HTTP 202 from a control route). */
export interface PendingHuman {
  status: "pending_human";
  hitlRequestId: string;
}

export interface Registered {
  status: "ok";
  registered: string;
  id: string;
  activated: false;
  /** Human-readable next step: what the SEC-22 review gate requires. */
  next: string;
}

export type RegisterOutcome = Registered | PendingHuman;

export interface Activated {
  status: "ok";
  id: string;
  activated: true;
  verbs: string[];
}

export type ActivateOutcome = Activated | PendingHuman;

export function isPendingHuman(outcome: { status: string }): outcome is PendingHuman {
  return outcome.status === "pending_human";
}

// --- authentication -------------------------------------------------------

/**
 * Session login with owner credentials -> a Cookie header value for the
 * session-only routes (e.g. minting a PAT). Public route, rate-limited
 * kernel-side. The password is used once and never logged.
 */
export async function login(opts: {
  server: string;
  email: string;
  password: string;
  fetch?: FetchLike;
  signal?: AbortSignal;
}): Promise<{ cookie: string; user: Record<string, unknown> }> {
  const doFetch = opts.fetch ?? (fetch as unknown as FetchLike);
  const resp = await doFetch(`${baseUrl(opts.server)}/v1/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email: opts.email, password: opts.password }),
    ...(opts.signal ? { signal: opts.signal } : {}),
  });
  let payload: Record<string, unknown> = {};
  try {
    const parsed = await resp.json();
    if (parsed !== null && typeof parsed === "object") payload = parsed as Record<string, unknown>;
  } catch {
    /* handled below as a generic failure */
  }
  if (resp.status !== 200 || payload.status !== "ok") {
    if (payload.status === "2fa_required") {
      throw new KernelApiError(
        "login requires a second factor; complete 2FA in the console and use a PAT instead",
        resp.status,
      );
    }
    throw new KernelApiError("login failed: invalid email or password", resp.status);
  }
  const setCookies = resp.headers.getSetCookie?.() ?? [];
  const cookie = setCookies
    .map((c) => c.split(";", 1)[0]?.trim() ?? "")
    .filter(Boolean)
    .join("; ");
  if (!cookie) throw new KernelApiError("login succeeded but no session cookie was issued", resp.status);
  const user = (payload.user ?? {}) as Record<string, unknown>;
  return { cookie, user };
}

/**
 * Mint a personal access token (POST /v1/me/tokens, access_routes.py:390).
 * Auth: the session cookie from `login` (or an existing PAT). The secret is
 * shown ONCE by the kernel and never stored in the clear - the caller owns
 * keeping it out of logs.
 */
export async function mintPat(
  opts: KernelRequestOptions & { name: string; scope?: string[]; ttlDays?: number },
): Promise<{ id: string; name: string; scope: string[]; secret: string }> {
  const body: Record<string, unknown> = { name: opts.name };
  if (opts.scope) body.scope = opts.scope;
  if (opts.ttlDays !== undefined) body.ttl_days = opts.ttlDays;
  const { status, payload } = await kernelPost(opts, "/v1/me/tokens", body);
  await raiseForStatus(status, payload);
  if (typeof payload.secret !== "string" || typeof payload.id !== "string") {
    throw new KernelApiError("token mint returned an unexpected shape", status);
  }
  return {
    id: payload.id,
    name: String(payload.name ?? opts.name),
    scope: Array.isArray(payload.scope) ? payload.scope.map(String) : [],
    secret: payload.secret,
  };
}

// --- governed registration ------------------------------------------------

export interface RegisterMcpServerOptions extends KernelRequestOptions {
  /** Adapter id for this app instance, e.g. "opbox-acme". One per tenant. */
  id: string;
  /** The URL the kernel will POST JSON-RPC to (the scaffold's `url`). */
  url: string;
  /** Secret-store key (with the default `env` store: an env var name readable
   * BY THE KERNEL PROCESS) holding this server's bearer. Optional; without it
   * the consumer fails closed on calls (mcp_consumer.py:127-130). */
  credentialRef?: string;
  credentialId?: string;
  credentialStore?: string;
  credentialKind?: string;
  /** Re-apply a previously-approved HITL request (x-boltrig-approval-id). */
  approvalId?: string;
}

export async function registerMcpServer(opts: RegisterMcpServerOptions): Promise<RegisterOutcome> {
  const body: Record<string, unknown> = { id: opts.id, url: opts.url };
  // Refs only, never material (control_mcp.py:38-43 refuses raw secrets).
  if (opts.credentialRef) body.credential_ref = opts.credentialRef;
  if (opts.credentialId) body.credential_id = opts.credentialId;
  if (opts.credentialStore) body.credential_store = opts.credentialStore;
  if (opts.credentialKind) body.credential_kind = opts.credentialKind;
  if (opts.approvalId) body.approval_id = opts.approvalId;

  const headers: Record<string, string> = {};
  if (opts.approvalId) headers["x-boltrig-approval-id"] = opts.approvalId;
  const { status, payload } = await kernelPost(opts, "/v1/mcp/servers", body, headers);

  if (status === 202 && payload.status === "pending_human") {
    return { status: "pending_human", hitlRequestId: String(payload.hitl_request_id ?? "") };
  }
  await raiseForStatus(status, payload);
  return {
    status: "ok",
    registered: String(payload.registered ?? "mcp_server"),
    id: String(payload.id ?? opts.id),
    activated: false,
    next:
      "Registration is INERT (SEC-22 review gate). A human must review, then " +
      "activate via control.adapter.activate (POST /v1/adapters/{id}/activate), " +
      "which itself is high-consequence and drives HITL. Until activation the " +
      "adapter refuses execution ('mcp server pending review').",
  };
}

/**
 * Activate a reviewed adapter (control.adapter.activate). High-consequence:
 * expect a `pending_human` outcome first; a human approves, then re-call with
 * `approvalId` set to the approved hitl_request_id. Activation also requires
 * the recorded HITL reviewer (control_plane.py:254-261), which the approval
 * flow supplies.
 */
export async function activateAdapter(
  opts: KernelRequestOptions & { adapterId: string; approvalId?: string },
): Promise<ActivateOutcome> {
  const headers: Record<string, string> = {};
  if (opts.approvalId) headers["x-boltrig-approval-id"] = opts.approvalId;
  const body: Record<string, unknown> = {};
  if (opts.approvalId) body.approval_id = opts.approvalId;
  const { status, payload } = await kernelPost(
    opts,
    `/v1/adapters/${encodeURIComponent(opts.adapterId)}/activate`,
    body,
    headers,
  );
  if (status === 202 && payload.status === "pending_human") {
    return { status: "pending_human", hitlRequestId: String(payload.hitl_request_id ?? "") };
  }
  await raiseForStatus(status, payload);
  return {
    status: "ok",
    id: String(payload.id ?? opts.adapterId),
    activated: true,
    verbs: Array.isArray(payload.verbs) ? payload.verbs.map(String) : [],
  };
}

/** Approve or deny a pending HITL request (POST /v1/hitl/{id}/respond). */
export async function respondToHitl(
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

/** Adapter inventory (GET /v1/adapters): registration rows and review-gate state. */
export async function listAdapters(
  opts: KernelRequestOptions,
): Promise<Array<{ id: string; runtime: string; activated: boolean; health: string }>> {
  const { status, payload } = await kernelGet(opts, "/v1/adapters");
  await raiseForStatus(status, payload);
  const adapters = Array.isArray(payload.adapters) ? payload.adapters : [];
  return adapters.map((a) => {
    const row = a as Record<string, unknown>;
    return {
      id: String(row.id ?? ""),
      runtime: String(row.runtime ?? ""),
      activated: row.activated === true,
      health: String(row.health ?? "unknown"),
    };
  });
}
