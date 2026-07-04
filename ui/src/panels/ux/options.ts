import type { Option } from "./types";

// Notification value spaces (one source of truth for Me + Settings).
export const NOTIFY_EVENT_OPTIONS: Option[] = [
  { value: "approval", label: "Approval needed" },
  { value: "escalation", label: "Escalation" },
  { value: "work_status", label: "Work status change" },
  { value: "budget_alert", label: "Budget alert" },
  { value: "error", label: "Error" },
];
export const NOTIFY_CHANNEL_OPTIONS: Option[] = [
  { value: "in_app", label: "In-app" },
  { value: "email", label: "Email" },
  { value: "slack", label: "Slack" },
  { value: "teams", label: "Teams" },
  { value: "webhook", label: "Webhook" },
  { value: "pager", label: "Pager" },
];

// The canonical role value space (one source of truth; identity + admin + invite
// selects all read this so they can never drift). org-admin is the most
// powerful; agent the most limited.
export const ROLE_OPTIONS: Option[] = [
  { value: "org-admin", label: "org-admin", hint: "Full access to everything." },
  { value: "department-head", label: "department-head", hint: "Runs a department." },
  { value: "manager", label: "manager", hint: "Manages a team." },
  { value: "lead", label: "lead", hint: "Leads work within a team." },
  { value: "integrator", label: "integrator", hint: "Builds capability (skills, adapters, workflows)." },
  { value: "agent", label: "agent", hint: "The most limited role." },
];

// The bare role ids (one source of truth shared by the identity, admin and
// invite selects so they can never drift).
export const ROLE_VALUES: ReadonlyArray<string> = ROLE_OPTIONS.map((o) => o.value);

// Token / invitation lifetime choices (one source of truth for the invite and
// mint-token forms). "never" resolves to no expiry (ttl_days omitted).
export const TTL_OPTIONS: Option[] = [
  { value: "7", label: "7 days" },
  { value: "14", label: "14 days" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
  { value: "never", label: "Never expires" },
];

// Resolve a TTL_OPTIONS selection to an API ttl_days (undefined = no expiry).
export function ttlDaysFromSelection(v: string): number | undefined {
  return v === "never" ? undefined : Number(v);
}
