import type { WorkerRoute } from "../../routes";

/**
 * The Integrations page's tabs, expressed as the SELECTION segment of the hash.
 *
 * `#/integrations/review` is two segments, so `selectionFromHash` already
 * parses it: the third-segment limit only bites when a tab needs a selection of
 * its own (`#/integrations/review/cb:open`), which none of these do. Adding a
 * tab is a line here plus a panel; nothing in the router changes.
 *
 * `connections` is the default and is NOT in the hash: a bare `#/integrations`
 * has always meant the connections list, and rewriting it on load would break
 * every link anyone has already saved.
 */
export const CAPABILITY_TABS = [
  { id: "connections", label: "Connections" },
  { id: "capabilities", label: "Capabilities" },
  { id: "rules", label: "Rules" },
  { id: "review", label: "Review" },
] as const;

export type CapabilityTabId = (typeof CAPABILITY_TABS)[number]["id"];

export const INTEGRATIONS_ROUTE: WorkerRoute = "integrations";

const KNOWN = new Set<string>(CAPABILITY_TABS.map((tab) => tab.id));

/** An unknown or absent selection is the connections list, never a blank page. */
export function tabFromSelection(selection: string | null): CapabilityTabId {
  return selection && KNOWN.has(selection)
    ? (selection as CapabilityTabId)
    : "connections";
}

/** The selection to navigate to. The default tab clears the segment. */
export function selectionForTab(tab: CapabilityTabId): string | null {
  return tab === "connections" ? null : tab;
}
