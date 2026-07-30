// Typed fetch transport over the kernel HTTP surface. Every request carries the
// dev identity headers (x-boltrig-*) read from the identity store. Paths are
// relative: the Vite dev server and the nginx prod image both proxy /v1 and
// /healthz to the kernel.
//
// Every call into the kernel goes through BASE below - `request` here, plus the
// three streaming fetches in api/sse.ts and api/domains/knowledge.ts, which
// import it. That makes BASE the single place the console's mount point enters
// the wire, which is why deriving it once is enough to mount the whole app
// under a sub-path.

import { getIdentity } from "@/identity";

// The mount point of this console, as a path prefix ("" at the root,
// "/boltrig" under a tenant app). Pure and exported so it can be tested without
// a DOM.
//
// This is DERIVED rather than configured, and that is the point: one built
// artefact serves at any mount, so a tenant never runs a differently-built
// image and there is no mount path to remember, render or drift. See
// docs/GOAL-console-mounts-with-its-stack.md (M1, M2).
//
// It is only safe because src/router.ts is a HASH router. Every deep link lives
// in the fragment (#/runs/123), which the browser never sends, so pathname is
// only ever the mount point itself. If this app ever adopts history routing,
// this derivation breaks and the prefix must come from elsewhere.
export function mountPrefix(pathname: string): string {
  const segs = pathname.split("/");
  // A trailing segment that names a file (index.html) belongs to the document,
  // not to the mount. Without this, /boltrig/index.html derives
  // "/boltrig/index.html" and every API call 404s.
  if (segs.length > 0 && segs[segs.length - 1].includes(".")) segs.pop();
  return segs.join("/").replace(/\/+$/, "");
}

// Build-time VITE_API_BASE still wins where a deployment needs to state the
// prefix explicitly; unset, the prefix is derived at runtime.
export const BASE = (
  import.meta.env.VITE_API_BASE ??
  (typeof window === "undefined" ? "" : mountPrefix(window.location.pathname))
).replace(/\/$/, "");

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

export function identityHeaders(): Record<string, string> {
  const id = getIdentity();
  return {
    "x-boltrig-tenant": id.tenant,
    "x-boltrig-subject": id.subject,
    "x-boltrig-grants": id.grants,
    "x-boltrig-role": id.role,
    "x-boltrig-departments": id.departments ?? "",
    "x-boltrig-tier": id.actorTier ?? "human",
    "x-boltrig-obo": id.onBehalfOf ?? "",
    "x-boltrig-verbs": id.verbs ?? "",
  };
}

// The mutating HTTP methods that a first-party session gates with CSRF. The
// session cookie (boltrig_session) is httpOnly, so a browser attaches it
// automatically; the double-submit defence is to ALSO echo the readable
// boltrig_csrf cookie in the x-boltrig-csrf header (a value a cross-site form
// cannot set). Safe reads never need it. See boltrig/identity/sessions.py.
const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const CSRF_COOKIE = "boltrig_csrf";
const CSRF_HEADER = "x-boltrig-csrf";

// Read the readable CSRF cookie the login route set. Absent under the dev
// header-auth resolver (no session cookie), so the header is simply omitted -
// dev/e2e requests are unaffected; only a real session carries the cookie.
function readCsrfCookie(): string | null {
  if (typeof document === "undefined" || !document.cookie) return null;
  for (const part of document.cookie.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name === CSRF_COOKIE) return decodeURIComponent(rest.join("="));
  }
  return null;
}

// The x-boltrig-csrf header for a mutating request, or {} when there is no CSRF
// cookie (header-auth dev / logged-out). Never throws.
export function csrfHeaders(method: string): Record<string, string> {
  if (!MUTATING_METHODS.has(method.toUpperCase())) return {};
  const token = readCsrfCookie();
  return token ? { [CSRF_HEADER]: token } : {};
}

export async function parseBody(res: Response): Promise<unknown> {
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

export async function request<T>(
  path: string,
  opts: RequestOptions = {},
): Promise<T> {
  const { method = "GET", body, tolerateStatus = false } = opts;
  const headers: Record<string, string> = {
    ...identityHeaders(),
    ...csrfHeaders(method),
  };
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
