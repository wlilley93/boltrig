/** The routes this build actually has.
 *
 *  MEASURED, NOT CHOSEN BY TASTE. Every other v1 route is a console over the
 *  Boltrig kernel, and a Hermes cell has no kernel: `home` calls 11 methods
 *  (audit, budgets, readiness, platform status) and none is backed; `build`
 *  calls 45 and two are; the parity views - work, agents, runs, knowledge,
 *  memory - call 22 between them and none belongs to those surfaces; routines
 *  calls six workflow methods, all of them kernel; browser needs a WebSocket
 *  the cell proxy refuses on purpose.
 *
 *  A route kept in that state renders "unavailable" for ever. That is honest
 *  and it is still a promise nobody can keep, so the route goes. Their view
 *  modules stay in the tree, unrouted and therefore unbundled, until the scope
 *  is confirmed - deleting 100 files is easy to do and slow to undo.
 */
export type WorkerRoute =
  | "chat"
  | "settings"
  | "account";

const routes = new Set<WorkerRoute>([
  "chat",
  "settings",
  "account",
]);

export function routeFromHash(hash: string): WorkerRoute {
  const candidate = hash.replace(/^#\/?/, "").split("/")[0] as WorkerRoute;
  return routes.has(candidate) ? candidate : "chat";
}

export function conversationFromHash(hash: string): string | null {
  return selectionFromHash(hash, "chat");
}

export function selectionFromHash(
  hash: string,
  expectedRoute: WorkerRoute,
): string | null {
  const [route, encodedId, extra] = hash.replace(/^#\/?/, "").split("/");
  if (route !== expectedRoute || !encodedId || extra) return null;
  try {
    const id = decodeURIComponent(encodedId);
    return id && id.length <= 256 ? id : null;
  } catch {
    return null;
  }
}

export function routeHash(route: WorkerRoute, selectionId?: string | null): string {
  return selectionId
    ? `#/${route}/${encodeURIComponent(selectionId)}`
    : `#/${route}`;
}

export function navigate(route: WorkerRoute, selectionId?: string | null): void {
  window.location.hash = routeHash(route, selectionId);
}
