import { BoltrigApiError } from "@wlilley93/boltrig-web-sdk";

/** Two destinations, and confusing them is the bug this file exists to prevent.
 *
 *  THE CONTROL PLANE (`/api/...`) owns identity, membership, settings and the
 *  workspace. THE CELL (`/api/cell/{gateway_id}/...`) is this member's own
 *  Hermes container, reached through a proxy that checks membership first and
 *  refuses any path not on its allowlist.
 *
 *  They are not interchangeable. `/api/settings` sent through the cell proxy
 *  asks Hermes for a route it has never had, and the proxy answers 403 before
 *  it even gets there - which presents as the whole app failing to render,
 *  because AuthGate gates on `meSettings()`.
 */

/** A control-plane call. Same origin, session cookie, no gateway involved. */
export async function planeFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const response = await fetch(path, { credentials: "same-origin", ...options });
  if (!response.ok) throw await apiError(response, path);
  return response;
}

export async function planeJson<T>(path: string, options: RequestInit = {}): Promise<T> {
  return (await planeFetch(path, options)).json() as Promise<T>;
}

let cachedGatewayId: string | null = null;

export function resetGatewayCache(): void {
  cachedGatewayId = null;
}

/** Which cell this browser talks to.
 *
 *  `tenant_gateway_id` first, because on a tenant address the CONTROL PLANE is
 *  the only thing that knows which workspace that hostname belongs to - the
 *  browser must never parse it out of the hostname. The fallback is for the
 *  public origin, where a member with exactly one cell should still work.
 */
export async function getGatewayId(): Promise<string> {
  if (cachedGatewayId) return cachedGatewayId;
  const me = await planeJson<{
    tenant_gateway_id?: string | null;
    gateways?: { gateway_id?: string }[];
  }>("/api/me");
  // `gateway_id`, NOT `id`. /api/me returns rows keyed by gateway_id, and
  // reading `.id` yields undefined, which then fails as "no gateway found" -
  // a message that sends the reader looking for a provisioning fault that is
  // not there.
  const id = me.tenant_gateway_id
    ?? (me.gateways?.length === 1 ? me.gateways[0]?.gateway_id : undefined)
    ?? me.gateways?.[0]?.gateway_id;
  if (!id) throw new BoltrigApiError(404, { reason: "no_gateway" }, "no cell for this user yet");
  cachedGatewayId = id;
  return id;
}

/** A call to this member's own cell, through the membership-checked proxy. */
export async function cellFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const gatewayId = await getGatewayId();
  const url = `/api/cell/${encodeURIComponent(gatewayId)}${path}`;
  const response = await fetch(url, { credentials: "same-origin", ...options });
  if (!response.ok) throw await apiError(response, url);
  return response;
}

export async function cellJson<T>(path: string, options: RequestInit = {}): Promise<T> {
  return (await cellFetch(path, options)).json() as Promise<T>;
}

/** A JSON POST. The control plane refuses any POST that is not
 *  `application/json`, and caps the body at 64KB, so this is the only shape
 *  either destination accepts. */
export function jsonBody(body: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export async function cellPost<T>(path: string, body: unknown): Promise<T> {
  return cellJson<T>(path, jsonBody(body));
}

export async function planePost<T>(path: string, body: unknown): Promise<T> {
  return planeJson<T>(path, jsonBody(body));
}

/** The server's own words where it gave any.
 *
 *  Reading the body matters: the control plane answers
 *  `{error: {code, message}}` and the proxy's refusals name the reason
 *  (`route_not_allowed`, `cell_unreachable`). Throwing only a status code
 *  turns a specific, actionable refusal into "something went wrong". */
async function apiError(response: Response, url: string): Promise<BoltrigApiError> {
  let body: unknown = null;
  try {
    body = await response.clone().json();
  } catch {
    body = null;
  }
  const detail = (body as { error?: { message?: string } } | null)?.error?.message;
  return new BoltrigApiError(response.status, body, detail ?? `${response.status} from ${url}`);
}
