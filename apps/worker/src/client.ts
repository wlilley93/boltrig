import { BoltrigClient } from "@wlilley93/boltrig-web-sdk";

import { configuredApiOrigin } from "./apiOrigin";
import {
  desktopAccountChallenge,
  desktopAccountLogin,
  desktopAccountLogout,
  desktopAccountRefresh,
  desktopApiFetch,
  isDesktop,
} from "./desktop";

let sessionCsrfToken: string | null = null;

export function rememberSessionCsrf(value: unknown): void {
  sessionCsrfToken = typeof value === "string" && value ? value : null;
}

function browserSessionCsrf(): string | null {
  if (sessionCsrfToken) return sessionCsrfToken;
  if (typeof document === "undefined") return null;
  const item = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith("boltrig_csrf="));
  return item ? decodeURIComponent(item.slice("boltrig_csrf=".length)) : null;
}

import { client as hermesClient } from "./hermes/client";

export const client = hermesClient;

// WKWebView does not persist cross-site Set-Cookie responses for the packaged
// tauri:// page. Keep the SDK surface identical, but route only the four
// session-issuing/rotating calls through the origin-pinned native bridge.
if (isDesktop) {
  // @ts-ignore - Hermes adapter is a Proxy and doesn't have these methods by default
  client.login = ({ email, password }) => desktopAccountLogin(email, password);
  // @ts-ignore
  client.twoFactorChallenge = ({ challenge_token, code }) => (
    desktopAccountChallenge(challenge_token, code)
  );
  // @ts-ignore
  client.refreshSession = desktopAccountRefresh;
  // @ts-ignore
  client.logout = desktopAccountLogout;
}

/** Call a client method only when it is actually there.
 *
 *  AN ABSENT METHOD IS `undefined`, NOT A REJECTING FUNCTION - deliberately, so
 *  that `typeof client.x === "function"` probes report a feature as missing
 *  instead of rendering it into a broken state. The cost is that INVOKING one
 *  throws synchronously, and inside a `Promise.allSettled([...])` array literal
 *  that throw escapes before allSettled can settle anything: the whole batch
 *  rejects, and a caller that only inspects settled results waits forever with
 *  no error to show. WorkerGlobalContext did exactly that, and the shell never
 *  learned who you were - no name, no organisation, no workspace.
 *
 *  So the probe and the call belong together, once, rather than at each site
 *  that has to remember. */
export function whenPresent<T>(method: unknown, call: () => Promise<T>): Promise<T> {
  return typeof method === "function"
    ? call()
    : Promise.reject(new Error("not available on this runtime"));
}
