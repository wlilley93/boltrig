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
