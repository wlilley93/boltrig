// A tiny client-side hash-router. It mirrors the identity store: a single
// source of truth exposed to React via useSyncExternalStore (no router library),
// except the state is persisted to window.location.hash instead of localStorage
// so back / forward and deep links work for free.
//
// Hash grammar:
//   #/chat                     -> { tab: "chat" }
//   #/canvas/<wfid>            -> { tab: "canvas", param: "<wfid>" }
//   #/kanban?run=<id>          -> { tab: "kanban", runId: "<id>" }  (drawer over tab)
//   #/runs/<id>                -> { tab: "runs",   runId: "<id>" }  (deep link)
// The run drawer is an orthogonal `?run=` overlay, so openRun() leaves the active
// tab untouched and any view can raise it.

import { useSyncExternalStore } from "react";

export interface Route {
  tab: string;
  // second path segment (e.g. canvas/<wfid>); not used by the run drawer.
  param?: string;
  // when set, the global Run drawer is open keyed by this run id.
  runId?: string;
}

function parse(hash: string): Route {
  const raw = hash.replace(/^#\/?/, "");
  const [path, query] = raw.split("?");
  const segs = path.split("/").filter(Boolean);
  const params = new URLSearchParams(query ?? "");
  const tab = segs[0] || "home";
  let param = segs[1] || undefined;
  let runId = params.get("run") ?? undefined;
  // The #/runs/<id> deep link carries the run in the path, not the query.
  if (tab === "runs" && segs[1]) {
    runId = segs[1];
    param = undefined;
  }
  return { tab, param, runId };
}

let current: Route = parse(window.location.hash);
const listeners = new Set<() => void>();
let bound = false;

function refresh(): void {
  current = parse(window.location.hash);
  for (const fn of listeners) fn();
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  if (!bound) {
    window.addEventListener("hashchange", refresh);
    bound = true;
  }
  return () => listeners.delete(fn);
}

export function getRoute(): Route {
  return current;
}

// Build the path portion (without the run query) of the current route, so the
// run-drawer helpers can toggle ?run while preserving where you are.
function basePath(r: Route): string {
  return r.param ? `/${r.tab}/${r.param}` : `/${r.tab}`;
}

// Switch the active tab (path). Drops any open run drawer.
export function navigate(path: string): void {
  const clean = path.startsWith("/") ? path : `/${path}`;
  window.location.hash = `#${clean}`;
}

// Raise (or re-key) the global Run drawer over the current tab.
export function openRun(runId: string): void {
  window.location.hash = `#${basePath(current)}?run=${encodeURIComponent(runId)}`;
}

// Close the run drawer, staying on the current tab.
export function closeRun(): void {
  window.location.hash = `#${basePath(current)}`;
}

export function useRoute(): Route {
  return useSyncExternalStore(subscribe, getRoute, getRoute);
}
