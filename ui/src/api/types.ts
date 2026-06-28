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

// --- Conversational chat surface (US-CONV-01..04, US-CONV-07) ---------------
// Mirrors the kernel chat endpoints. POST /v1/chat returns Server-Sent Events;
// each `data:` line is one JSON object of the ChatEvent union below.

export interface ConversationSummary {
  id: string;
  title: string;
  status: string;
  updated_at: string;
}

export interface ConversationsResponse {
  conversations: ConversationSummary[];
}

export type ChatRole = "user" | "assistant" | "system" | string;

// A persisted message. `events` carries the structured turn (tool calls,
// sub-agents, HITL) so a re-opened conversation re-renders the same cards as
// the live stream did.
export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  run_id?: string | null;
  hitl_request_id?: string | null;
  events?: ChatEvent[];
  created_at: string;
}

export interface ConversationResponse {
  messages: ChatMessage[];
}

export interface ChatRequest {
  // omit to start a new conversation; the first message_start returns the id
  conversation_id?: string;
  message: string;
}

// --- The streamed event union (one JSON object per SSE data line) -----------

export interface ChatMessageStart {
  type: "message_start";
  run_id: string;
  conversation_id: string;
}
export interface ChatTextDelta {
  type: "text_delta";
  delta: string;
}
export interface ChatReasoningDelta {
  type: "reasoning_delta";
  delta: string;
}
export interface ChatToolCall {
  type: "tool_call";
  verb: string;
  input?: unknown;
  status: "running";
}
export interface ChatToolResult {
  type: "tool_result";
  verb: string;
  status: "ok" | "error";
  output?: unknown;
}
export interface ChatSubagent {
  type: "subagent";
  child_run_id: string;
  task: string;
  skills?: string[];
}
export interface ChatHitlEvent {
  type: "hitl";
  hitl_request_id: string;
  kind: HITLKind;
  question: string;
  options?: string[];
}
export interface ChatMessageEnd {
  type: "message_end";
  run_id: string;
}

export type ChatEvent =
  | ChatMessageStart
  | ChatTextDelta
  | ChatReasoningDelta
  | ChatToolCall
  | ChatToolResult
  | ChatSubagent
  | ChatHitlEvent
  | ChatMessageEnd;
