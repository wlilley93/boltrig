import type { ConsoleOverview, ConsoleSettings } from "./types";

const API_BASE_KEY = "boltrig.console.apiBase";
const TOKEN_KEY = "boltrig.console.bearerToken";

export function overviewUrl(apiBase: string, limit = 50): string {
  const path = `/v1/console/overview?limit=${Math.max(1, Math.min(limit, 200))}`;
  const base = apiBase.trim().replace(/\/+$/, "");
  return base ? `${base}${path}` : path;
}

export function hitlRespondUrl(apiBase: string, requestId: string): string {
  const base = apiBase.trim().replace(/\/+$/, "");
  const path = `/v1/hitl/${encodeURIComponent(requestId)}/respond`;
  return base ? `${base}${path}` : path;
}

function authHeaders(settings: ConsoleSettings): Record<string, string> {
  const headers: Record<string, string> = { accept: "application/json" };
  const token = settings.bearerToken.trim();
  if (token) {
    headers.authorization = token.toLowerCase().startsWith("bearer ")
      ? token
      : `Bearer ${token}`;
  }
  return headers;
}

export function defaultSettings(): ConsoleSettings {
  return {
    apiBase: process.env.NEXT_PUBLIC_BOLTRIG_API_BASE ?? "",
    bearerToken: "",
  };
}

export function loadSettings(): ConsoleSettings {
  if (typeof window === "undefined") return defaultSettings();
  return {
    apiBase: window.sessionStorage.getItem(API_BASE_KEY) ?? defaultSettings().apiBase,
    bearerToken: "",
  };
}

export function saveSettings(settings: ConsoleSettings): void {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(API_BASE_KEY, settings.apiBase.trim());
  window.sessionStorage.removeItem(TOKEN_KEY);
}

export async function fetchOverview(settings: ConsoleSettings): Promise<ConsoleOverview> {
  const response = await fetch(overviewUrl(settings.apiBase), {
    cache: "no-store",
    headers: authHeaders(settings),
  });
  if (!response.ok) {
    throw new Error(`Console API returned ${response.status}`);
  }
  return (await response.json()) as ConsoleOverview;
}

export async function respondApproval(
  settings: ConsoleSettings,
  requestId: string,
  decision: string,
): Promise<void> {
  const response = await fetch(hitlRespondUrl(settings.apiBase, requestId), {
    body: JSON.stringify({ decision }),
    cache: "no-store",
    headers: { ...authHeaders(settings), "content-type": "application/json" },
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`Approval API returned ${response.status}`);
  }
}
