// The Familiar island's entry: the page the iPhone app loads into a web view.
//
// The app talks IN through window.familiarIsland.applyJSON(text) and hears OUT
// through its `familiar` message handler; a desktop browser gets the same page
// with the reports on the console, which is how the page is looked at without
// a phone. Nothing here knows about the app beyond that one bridge.
import { FamiliarIslandHost, type IslandReport } from "./islandHost";
import { parseIslandState, type IslandState } from "./islandState";

export interface FamiliarIslandApi {
  version: 1;
  /** Merge one state object; returns the state now in force. */
  apply(incoming: unknown): IslandState;
  /** The same from JSON text; returns the state, or the error string when the
   *  text could not be read (the error is also posted as a report). */
  applyJSON(json: string): IslandState | string;
}

interface WebKitBridge {
  messageHandlers?: { familiar?: { postMessage(message: unknown): void } };
}

function post(report: IslandReport): void {
  const handler = (window as unknown as { webkit?: WebKitBridge }).webkit?.messageHandlers?.familiar;
  if (handler) handler.postMessage(report);
  else console.log("familiar-island", JSON.stringify(report));
}

const host = new FamiliarIslandHost();
const api: FamiliarIslandApi = {
  version: 1,
  apply: (incoming) => host.apply(incoming),
  applyJSON: (json) => {
    const parsed = parseIslandState(json);
    if (typeof parsed === "string") {
      post({ type: "error", message: parsed });
      return parsed;
    }
    return host.apply(parsed);
  },
};
(window as unknown as { familiarIsland?: FamiliarIslandApi }).familiarIsland = api;

window.addEventListener("error", (event) => {
  post({ type: "error", message: event.message || "script error" });
});
window.addEventListener("unhandledrejection", (event) => {
  post({ type: "error", message: String(event.reason) });
});

function boot(): void {
  const element = document.getElementById("familiar");
  if (!element) {
    post({ type: "fallback", reason: "no #familiar element" });
    return;
  }
  // Desktop only: ?presentation=hero|conversation|minimised opens the page in
  // that presentation, so it can be looked at without the app.
  const presentation = new URLSearchParams(window.location.search).get("presentation");
  if (presentation) host.apply({ presentation });
  host.boot(element, post);
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
else boot();
