import type { RecoveryFlow } from "./types";

export function recoveryFlowFromHash(hash = window.location.hash): RecoveryFlow {
  if (hash.startsWith("#/reset-password")) return "confirm";
  if (hash.startsWith("#/forgot-password")) return "request";
  return "none";
}

export function acceptingInviteFromHash(hash = window.location.hash): boolean {
  return hash.startsWith("#/accept-invite");
}

export function tokenFromHash(hash = window.location.hash): string {
  return new URLSearchParams(hash.split("?")[1] ?? "").get("token") ?? "";
}

export function detailOf(body: unknown): string | null {
  return body && typeof body === "object" && "detail" in body
    ? String((body as { detail?: unknown }).detail ?? "")
    : null;
}
