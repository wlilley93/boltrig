// A tiny client-side hash-router. It mirrors the identity store: a single
// source of truth exposed to React via useSyncExternalStore (no router library),
// except the state is persisted to window.location.hash instead of localStorage
// so back / forward and deep links work for free.
//
// Hash grammar:
//   #/chat                     -> { tab: "chat", segs: ["chat"] }
//   #/canvas/<wfid>            -> { tab: "canvas", param: "<wfid>", segs: ["canvas", "<wfid>"] }
//   #/automations/wf/step/s3   -> { tab: "automations", param: "wf", segs: [all four] }
//   #/kanban?run=<id>          -> { tab: "kanban", runId: "<id>" }  (drawer over tab)
//   #/runs/<id>                -> { tab: "runs",   runId: "<id>" }  (deep link)
//   (empty hash)               -> { tab: "chat" }  (the deck's default landing)
// segs carries EVERY path segment (decoded), so deep routes survive the run
// drawer: basePath rebuilds the full path and openRun()/closeRun() only toggle
// the orthogonal ?run= overlay, never moving the deck.

import { useSyncExternalStore } from "react";

export interface Route {
  tab: string;
  // second path segment (e.g. canvas/<wfid>); not used by the run drawer.
  param?: string;
  // all path segments, each decoded - the deck resolves deep routes from these.
  segs: string[];
  // when set, the global Run drawer is open keyed by this run id.
  runId?: string;
}

// decodeURIComponent throws on malformed input (a hand-typed hash); fall back
// to the raw segment rather than crashing the router.
function decodeSeg(s: string): string {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
}

function parse(hash: string): Route {
  const raw = hash.replace(/^#\/?/, "");
  const [path, query] = raw.split("?");
  const segs = path.split("/").filter(Boolean).map(decodeSeg);
  const params = new URLSearchParams(query ?? "");
  const tab = segs[0] || "chat";
  let param = segs[1] || undefined;
  let runId = params.get("run") ?? undefined;
  // The #/runs/<id> deep link carries the run in the path, not the query.
  if (tab === "runs" && segs[1]) {
    runId = segs[1];
    param = undefined;
  }
  return { tab, param, segs, runId };
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
// run-drawer helpers can toggle ?run while preserving where you are. Rebuilt
// from ALL segments so deep routes (e.g. /automations/wf/step/s3) round-trip.
function basePath(r: Route): string {
  const segs = r.segs.length > 0 ? r.segs : [r.tab];
  return `/${segs.map(encodeURIComponent).join("/")}`;
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
