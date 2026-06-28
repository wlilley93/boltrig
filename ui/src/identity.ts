// A tiny dev-identity store. The kernel's dev principal resolver trusts the
// x-nankle-* headers (nankle/kernel/app.py::_dev_principal), so the UI lets you
// set the caller identity used on every request. Backed by localStorage and
// exposed to React via useSyncExternalStore (no state library needed).

import { useSyncExternalStore } from "react";

export interface Identity {
  tenant: string;
  subject: string;
  grants: string; // comma-separated grant patterns, e.g. "*" or "noun.verb,other.*"
  role: string;
  // comma-separated department refs sent as x-nankle-departments; the kernel
  // uses it to scope-filter audit/cost/runs (SEC-33). Empty = unrestricted by
  // this header (the role/scope still governs server-side).
  departments: string;
}

const STORAGE_KEY = "nankle.identity";

const DEFAULT_IDENTITY: Identity = {
  tenant: "default",
  subject: "dev",
  grants: "*",
  role: "org-admin",
  departments: "",
};

function load(): Identity {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_IDENTITY };
    const parsed = JSON.parse(raw) as Partial<Identity>;
    return { ...DEFAULT_IDENTITY, ...parsed };
  } catch {
    return { ...DEFAULT_IDENTITY };
  }
}

let current: Identity = load();
const listeners = new Set<() => void>();

function emit(): void {
  for (const fn of listeners) fn();
}

export function getIdentity(): Identity {
  return current;
}

export function setIdentity(next: Identity): void {
  current = next;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // ignore persistence failures (private mode, etc.)
  }
  emit();
}

export function updateIdentity(patch: Partial<Identity>): void {
  setIdentity({ ...current, ...patch });
}

export function resetIdentity(): void {
  setIdentity({ ...DEFAULT_IDENTITY });
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function useIdentity(): Identity {
  return useSyncExternalStore(subscribe, getIdentity, getIdentity);
}
