// First-party session auth store (COUNTY 7). The kernel supports two auth modes:
// the header-trusting dev resolver (x-boltrig-* headers, what the dev flow + the
// e2e smoke drive) and, when auth_mode=session, a real cookie session that is
// the sole internet-facing gate (it replaces Cloudflare Access). This store
// decides whether the app shows its login gate or enters the console.
//
// The signal is deliberate: we PROBE one authenticated endpoint. Under session
// auth with no cookie the kernel answers 401 -> show the login gate. Under the
// dev header resolver (and in the e2e harness) that same probe resolves to the
// dev principal -> 200 -> enter the app, so the gate never appears there. Only a
// DEFINITE 401 gates; a 200, a network blip or a 5xx all enter the app (we never
// block the console on a transient), so the deterministic smoke path is safe.

import { useSyncExternalStore } from "react";

import { ApiError, api } from "./api/client";
import type { AuthUser } from "./api/types";

// "enroll_required" ([2026] VJS-COUNTY 10, D4): the session is live but the org
// requires two-factor and the user has not enrolled, so the resolver clamps them to
// the enrollment surface only. The gate renders the enrollment screen.
export type AuthStatus =
  | "checking"
  | "authenticated"
  | "unauthenticated"
  | "enroll_required";

interface AuthState {
  status: AuthStatus;
  user: AuthUser | null;
  // the workspace the user last switched to in this browser. The session is the
  // real source of truth (re-authorized server-side each request); this is only
  // the client's view of the active context, used to mark the switcher.
  activeWorkspaceId: string | null;
}

const ACTIVE_WS_KEY = "boltrig.active_workspace";

function loadActiveWorkspace(): string | null {
  try {
    return localStorage.getItem(ACTIVE_WS_KEY);
  } catch {
    return null;
  }
}

let state: AuthState = {
  status: "checking",
  user: null,
  activeWorkspaceId: loadActiveWorkspace(),
};

const listeners = new Set<() => void>();

function emit(): void {
  for (const fn of listeners) fn();
}

function set(patch: Partial<AuthState>): void {
  state = { ...state, ...patch };
  emit();
}

export function getAuthState(): AuthState {
  return state;
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function useAuth(): AuthState {
  return useSyncExternalStore(subscribe, getAuthState, getAuthState);
}

// Probe an authenticated endpoint to decide the gate. A 401 means session auth
// is active and we are logged out; anything else enters the app.
export async function probeSession(): Promise<void> {
  try {
    await api.meSettings();
    set({ status: "authenticated" });
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      set({ status: "unauthenticated", user: null });
      return;
    }
    // A live-but-clamped session ([2026] VJS-COUNTY 10, D4): the org requires 2FA
    // and this user has not enrolled, so every non-enroll route is refused with the
    // distinct marker. Route to the enrollment screen (never strand them).
    if (
      err instanceof ApiError &&
      err.status === 403 &&
      isEnrollmentRequired(err.body)
    ) {
      set({ status: "enroll_required" });
      return;
    }
    // 200 already returned above; a network/5xx failure must not strand the user
    // on a login gate they cannot pass in dev/e2e - enter the app.
    set({ status: "authenticated" });
  }
}

// The resolver's enrollment clamp answers 403 with {detail:"two_factor_enrollment_required"}.
function isEnrollmentRequired(body: unknown): boolean {
  return (
    typeof body === "object" &&
    body !== null &&
    (body as { detail?: string }).detail === "two_factor_enrollment_required"
  );
}

// Called when the gate needs to force enrollment (login returned
// 2fa_enrollment_required, or the probe was clamped). Renders the enroll screen.
export function markEnrollRequired(): void {
  set({ status: "enroll_required" });
}

// Called by the login page on a successful /v1/auth/login. The session + CSRF
// cookies are already set by the response; flip the gate open.
export function markAuthenticated(user: AuthUser | null): void {
  set({ status: "authenticated", user });
}

// Called by the logout control after /v1/auth/logout. The cookies are cleared
// by the response; drop back to the login gate.
export function markUnauthenticated(): void {
  set({ status: "unauthenticated", user: null });
}

// True when a first-party session's readable CSRF cookie is present, i.e. the
// user is on the cookie-session auth path (not the dev header resolver). The
// chrome uses this to show the switcher + logout ONLY for a real session, so
// they never appear in the dev flow or the e2e header-auth harness.
export function hasSessionCookie(): boolean {
  if (typeof document === "undefined" || !document.cookie) return false;
  return document.cookie
    .split(";")
    .some((part) => part.trim().startsWith("boltrig_csrf="));
}

export function setActiveWorkspace(id: string): void {
  try {
    localStorage.setItem(ACTIVE_WS_KEY, id);
  } catch {
    // ignore persistence failures (private mode, etc.)
  }
  set({ activeWorkspaceId: id });
}
