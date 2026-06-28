// Types that mirror the kernel HTTP surface (nankle/kernel/app.py).
// Fields the kernel may add later (binding target, live verb health) are kept
// optional so the client tolerates their absence.

export type AdapterHealth = "ok" | "degraded" | "down" | "unknown";

export interface HealthResponse {
  status: string;
  // keyed by "<tenant>/<adapterId>"
  adapters: Record<string, AdapterHealth>;
}

export type Consequence = "low" | "high" | string;

export interface Verb {
  id: string;
  noun: string;
  input_schema?: unknown;
  output_schema?: unknown;
  consequence?: Consequence;
  // possibly-present forward-compatible fields:
  binding?: string;
  target?: string;
  target_type?: string;
  health?: AdapterHealth;
  [key: string]: unknown;
}

export interface CapabilitiesResponse {
  verbs: Verb[];
}

export type WorkStatus =
  | "pending"
  | "in_flight"
  | "blocked"
  | "awaiting_human"
  | "done"
  | "failed";

export interface WorkItem {
  id: string;
  intent: string;
  status: WorkStatus;
  confidence?: number | null;
  convergent?: boolean;
  owner_member?: string | null;
  source?: string | null;
  parent_id?: string | null;
  hatchet_run_id?: string | null;
}

export interface WorkResponse {
  items: WorkItem[];
}

export type HITLKind = "approval" | "clarification" | "escalation";

export interface HITLRequest {
  id: string;
  type: HITLKind;
  urgency?: string;
  question: string;
  context?: unknown;
  options?: string[];
  work_item_id?: string | null;
  status?: string;
}

export interface HITLListResponse {
  requests: HITLRequest[];
}

export interface RespondResult {
  status: string;
  response_id: string;
}

export interface InvokeRequest {
  noun: string;
  verb: string;
  params?: Record<string, unknown>;
  context?: Record<string, unknown>;
  idempotency_key?: string;
  approval_id?: string;
}

// The kernel returns different bodies per status code; this is the union.
export type InvokeResult =
  | { status: "ok"; output: unknown }
  | { status: "pending_human"; hitl_request_id: string }
  | { status: "denied"; reason: string }
  | { status: "degraded"; output: unknown }
  | { status: "error"; reason: string };

export interface SpawnRequest {
  task: string;
  skills?: string[];
  prefer?: Record<string, unknown>;
  context?: Record<string, unknown>;
}

// Audit execution tree (nankle/observability/tree.py). Shape is recursive and
// partly free-form, so it is typed loosely.
export interface AuditNode {
  run_id: string;
  parent_run_id?: string | null;
  actor?: string;
  tier?: string;
  depth?: number;
  actions?: number;
  cost_micros?: number;
  total_cost_micros?: number;
  tokens?: number;
  statuses?: Record<string, number>;
  children?: AuditNode[];
  [key: string]: unknown;
}

export interface AuditTreeResponse {
  root: AuditNode;
}
