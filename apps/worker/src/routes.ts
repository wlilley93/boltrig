export type WorkerRoute =
  | "home"
  | "chat"
  | "runs"
  | "work"
  | "agents"
  | "account"
  | "build"
  | "browser"
  | "channels"
  | "evaluations"
  | "automations"
  | "knowledge"
  | "memory"
  | "integrations"
  | "organisation"
  | "settings";

const routes = new Set<WorkerRoute>([
  "home",
  "chat",
  "runs",
  "work",
  "agents",
  "account",
  "build",
  "browser",
  "channels",
  "evaluations",
  "automations",
  "knowledge",
  "memory",
  "integrations",
  "organisation",
  "settings",
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
