import type { InvokeResult } from "../../api/types";

export const ADMIN_VIEWS = [
  { value: "config", label: "Configuration" },
  { value: "organisation", label: "Organisation & workspaces" },
];

export const ADMIN_ROLES: ReadonlySet<string> = new Set(["org-admin"]);

// Config amendments are high-consequence: the first upsert always pauses for a
// human, and denied/error map to a faithful message.
export function resultReason(result: InvokeResult): string | null {
  if (result.status === "denied" || result.status === "error") return result.reason;
  return null;
}
