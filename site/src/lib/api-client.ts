/**
 * Typed client for same-origin `/api/*` endpoints.
 *
 * For use in Client Components that need to fetch after mount. It unwraps the
 * `{ data }` / `{ error }` envelope and throws `ApiClientError` on failure.
 * The browser must only ever call same-origin `/api/*` — never a third-party
 * API directly (that belongs in a route handler).
 */

interface ApiFailure {
  error: {
    code: string;
    message: string;
    issues?: { path: string; message: string }[];
  };
}

/** Thrown by `apiFetch` when an endpoint responds with an error envelope. */
export class ApiClientError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiClientError";
  }
}

/**
 * Calls a same-origin `/api` endpoint and returns the unwrapped `data`.
 * `path` must be a relative path (e.g. `/api/contact`).
 */
export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "content-type": "application/json", ...init?.headers },
  });

  const body = (await res.json().catch(() => null)) as
    | { data: T }
    | ApiFailure
    | null;

  if (!res.ok || !body || "error" in body) {
    const err =
      body && "error" in body
        ? body.error
        : { code: "request_failed", message: "Request failed." };
    throw new ApiClientError(err.code, err.message, res.status);
  }

  return body.data;
}
