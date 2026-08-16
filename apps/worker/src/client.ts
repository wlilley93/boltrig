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

// Empty on the web image, where nginx serves the SPA and proxies /v1 on the
// same origin. On the desktop shell an empty origin would point every call at
// the tauri://localhost webview, which AuthGate refuses to open on.
export const client = new BoltrigClient({
  baseUrl: configuredApiOrigin(),
  csrfToken: browserSessionCsrf,
  fetch: isDesktop ? desktopApiFetch : undefined,
});

// WKWebView does not persist cross-site Set-Cookie responses for the packaged
// tauri:// page. Keep the SDK surface identical, but route only the four
// session-issuing/rotating calls through the origin-pinned native bridge.
if (isDesktop) {
  client.login = ({ email, password }) => desktopAccountLogin(email, password);
  client.twoFactorChallenge = ({ challenge_token, code }) => (
    desktopAccountChallenge(challenge_token, code)
  );
  client.refreshSession = desktopAccountRefresh;
  client.logout = desktopAccountLogout;
}
