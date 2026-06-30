// Types that mirror the kernel HTTP surface (boltrig/kernel/app.py).
// Fields the kernel may add later (binding target, live verb health) are kept
// optional so the client tolerates their absence.

export type AdapterHealth = "ok" | "degraded" | "down" | "unknown";

export interface HealthResponse {
  status: string;
  // keyed by "<tenant>/<adapterId>"
  adapters: Record<string, AdapterHealth>;
}

export type Consequence = "low" | "high" | string;

// Where a verb is fulfilled: an adapter or an agent, named by target_ref.
export interface VerbBinding {
  target_type: "adapter" | "agent";
  target_ref: string;
}

// One entry in the scoped verb registry (GET /v1/capabilities). The registry is
// caller-scoped: only verbs this identity may use come back. Forward-compatible
// fields the kernel may add later are tolerated via the index signature.
export interface VerbInfo {
  id: string;
  noun: string;
  input_schema?: unknown;
  output_schema?: unknown;
  consequence?: Consequence;
  binding?: VerbBinding;
  health?: AdapterHealth | string;
  [key: string]: unknown;
}

export interface CapabilitiesResponse {
  verbs: VerbInfo[];
  nouns?: unknown;
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

// Audit execution tree (boltrig/observability/tree.py). Shape is recursive and
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
// Emitted by the interpreter per step as it walks the workflow (the live canvas
// lights each node by matching step_id to a graph node id). Delivered on a run's
// event stream alongside the step's underlying tool_call / tool_result.
export interface ChatWorkflowStep {
  type: "workflow_step";
  step_id: string;
  action: string;
  status: "running" | "ok" | "failed" | "skipped" | "error";
}

export type ChatEvent =
  | ChatMessageStart
  | ChatTextDelta
  | ChatReasoningDelta
  | ChatToolCall
  | ChatToolResult
  | ChatSubagent
  | ChatHitlEvent
  | ChatMessageEnd
  | ChatWorkflowStep;

// ===========================================================================
// Round Three: authoring studios, admin console, insight, eval, personal.
// Every shape below mirrors boltrig/kernel/platform_routes.py (and the services
// it delegates to). Fields that depend on the response branch are optional so
// the client can render a denial / 404 / 503 alongside the happy path.
// ===========================================================================

// A small acknowledgement body returned by most write routes:
// {"status": "ok", ...} on success or {"status": "denied"|"error", "reason"}.
export interface StatusAck {
  status: string;
  id?: string;
  version?: string;
  verb?: string;
  reason?: string;
  [key: string]: unknown;
}

// The free-form spawn/agent result (boltrig/fleet/spawn.py::spawn). The fields
// present depend on status ("ok" | "error" | "partial"); effective_grants is the
// child's grants after the initiator-ceiling intersection (proves no escalation,
// SEC-29/30). Absent on the budget-partial branch.
export interface SpawnResult {
  run_id?: string;
  agent_type?: string;
  status?: string;
  reason?: string;
  summary?: string;
  output?: unknown;
  tokens_used?: number;
  cost_micros?: number;
  new_work_items?: unknown[];
  effective_grants?: string[];
  [key: string]: unknown;
}

// --- Skill Studio -----------------------------------------------------------

export interface SkillSummary {
  id: string;
  version: string;
  extends?: string | null;
  tool_grants: string[];
  locale: string;
}

export interface SkillsResponse {
  skills: SkillSummary[];
}

export interface UpsertSkillRequest {
  id: string;
  version?: string;
  prompt_fragment?: string;
  tool_grants?: string[];
  context_requirements?: Record<string, unknown>;
  extends?: string | null;
  locale?: string;
}

export interface TestSpawnRequest {
  task?: string;
  context?: Record<string, unknown>;
}

// --- Router authoring -------------------------------------------------------

export interface UpsertNounRequest {
  id: string;
  description?: string;
  schema?: Record<string, unknown>;
}

export interface UpsertVerbRequest {
  id: string;
  noun_id: string;
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
  description?: string;
  consequence?: "low" | "high";
}

export type TargetTypeValue = "adapter" | "agent";

export interface SetBindingRequest {
  target_type: TargetTypeValue;
  target_ref: string;
}

// --- Adapter Studio ---------------------------------------------------------

export interface GenerateAdapterRequest {
  spec: unknown;
  adapter_id: string;
}

export interface GenerateAdapterResponse {
  status: string;
  id?: string;
  // false on generate: the adapter is loaded but inert until reviewed/activated.
  activated?: boolean;
  verbs?: string[];
  reason?: string;
}

export interface AdapterSourceResponse {
  id?: string;
  source?: string;
  error?: string;
}

export interface ActivateAdapterRequest {
  reviewer?: string;
}

export interface ActivateAdapterResponse {
  status?: string;
  id?: string;
  verbs?: string[];
  error?: string;
  reason?: string;
}

export interface RegisterMcpRequest {
  id: string;
  url?: string;
  token?: string;
}

export interface AdapterRecord {
  id: string;
  runtime: string;
  version: string;
  source: string;
  activated: boolean;
  health: AdapterHealth | string;
}

export interface AdapterInventoryResponse {
  adapters: AdapterRecord[];
}

// --- Workflow Studio --------------------------------------------------------

export type WorkflowSourceValue = "precreated" | "generated" | "learned";

export interface WorkflowSummary {
  id: string;
  version: string;
  source: string;
  intent_tags: string[];
}

export interface WorkflowsResponse {
  workflows: WorkflowSummary[];
}

export interface WorkflowDetail {
  id: string;
  version: string;
  source: string;
  definition: Record<string, unknown>;
  intent_tags: string[];
}

export interface UpsertWorkflowRequest {
  id: string;
  version?: string;
  source?: WorkflowSourceValue;
  definition?: Record<string, unknown>;
  intent_tags?: string[];
}

export interface ScheduleWorkflowRequest {
  cron: string;
  timezone?: string;
}

export interface ScheduleWorkflowResponse {
  status: string;
  id?: string;
  schedule?: unknown;
  reason?: string;
}

export interface TriggerWorkflowRequest {
  inputs?: Record<string, unknown>;
}

// The run descriptor returned by trigger (boltrig/workflows/library.py::trigger).
export interface WorkflowRunDescriptor {
  run_id?: string;
  tenant_id?: string;
  workflow_id?: string;
  version?: string;
  source?: string;
  engine?: string;
  durable?: boolean;
  status?: string;
  inputs?: Record<string, unknown>;
  queued_at?: string;
  error?: string;
  [key: string]: unknown;
}

export interface WorkflowRunsResponse {
  workflow_id: string;
  runs: string[];
}

// --- Round Seven: workflow interpreter ("execute") --------------------------
// POST /v1/workflows/{id}/execute actually RUNS the stored workflow's steps
// through the kernel chokepoint (each step is a governed verb call), unlike
// trigger() which only queues a descriptor. The run record carries the overall
// status plus a per-step result (output on success, reason on a stop).

export interface WorkflowStepResult {
  id: string;
  action?: string;
  status: "ok" | "failed" | "skipped" | "paused" | "error" | string;
  output?: unknown;
  reason?: string;
}

export interface WorkflowRunRecord {
  run_id: string;
  workflow_id: string;
  version: string;
  status: "completed" | "failed" | "paused" | string;
  steps: WorkflowStepResult[];
  inputs: Record<string, unknown>;
}

// --- Admin console ----------------------------------------------------------

export interface ConfigSectionResponse {
  section?: string;
  value?: unknown;
  status?: string;
  reason?: string;
  error?: string;
}

export interface PutConfigRequest {
  value: unknown;
}

export interface PutConfigResponse {
  status: string;
  section?: string;
  revision?: string;
  reason?: string;
}

export interface ConfigRevisionSummary {
  id: number;
  version: string;
  actor: string;
  rolled_back: boolean;
  created_at: string;
}

export interface ConfigHistoryResponse {
  section?: string;
  revisions?: ConfigRevisionSummary[];
  error?: string;
}

export interface ConfigRollbackRequest {
  revision_id: number;
}

export interface ConfigRollbackResponse {
  status: string;
  section?: string;
  value?: unknown;
  reason?: string;
}

export interface ConfigExportResponse {
  manifest?: Record<string, unknown>;
  error?: string;
}

export interface CredentialRef {
  adapter?: string;
  credential?: string;
}

export interface CredentialsResponse {
  credentials?: CredentialRef[];
  error?: string;
}

// --- Insight (scope-filtered server-side) -----------------------------------

export interface CostResponse {
  total_cost_micros: number;
  by_actor: Record<string, number>;
  // "all" (unrestricted) or the list of departments the caller may see.
  scope: string[] | string;
}

export interface BudgetItem {
  id: string;
  scope_type: string; // tenant | department | workflow
  window: string; // run | daily | monthly
  hard_stop: boolean;
  token_limit: number | null;
  spent_tokens: number;
  cost_limit_micros: number | null;
  spent_micros: number;
}

export interface BudgetsResponse {
  budgets: BudgetItem[];
  scope: string[] | string;
}

export interface AuditRow {
  seq: number;
  ts: string;
  actor: string;
  verb: string;
  status: string;
  run_id?: string | null;
}

export interface AuditSearchResponse {
  results: AuditRow[];
  scope: string[] | string;
}

export interface AuditExportRow extends AuditRow {
  on_behalf_of?: string | null;
}

export interface AuditExportResponse {
  format?: string;
  count?: number;
  events?: AuditExportRow[];
  error?: string;
}

export interface RunRow {
  run_id?: string | null;
  work_item: string;
  intent: string;
  status: string;
  owner?: string | null;
}

export interface RunsResponse {
  runs: RunRow[];
}

// --- Evaluation -------------------------------------------------------------

export interface CreateEvalCaseRequest {
  id?: string;
  target_kind: string;
  target_ref: string;
  input?: Record<string, unknown>;
  assertions?: Record<string, unknown>;
  labels?: string[];
}

export interface RunEvalRequest {
  case_id: string;
}

export interface EvalRunDetail {
  checks?: Record<string, boolean>;
  effective_grants?: string[];
  spawn_error?: string;
  [key: string]: unknown;
}

export interface EvalRunResult {
  id?: string;
  passed?: boolean;
  score?: number;
  run_id?: string;
  detail?: EvalRunDetail;
  error?: string;
}

export interface EvalRunSummary {
  id: string;
  case_id: string;
  passed: boolean;
  score: number;
  run_id?: string;
}

export interface EvalRunsResponse {
  runs: EvalRunSummary[];
}

// --- Personal agent / notifications / memory --------------------------------

export interface ConfigurePersonalAgentRequest {
  runtime?: string;
  skills?: string[];
}

export interface ConfigurePersonalAgentResponse {
  status: string;
  id?: string;
  owner?: string;
}

export interface InvokePersonalAgentRequest {
  message: string;
  context?: Record<string, unknown>;
}

export interface NotificationPrefItem {
  id: string;
  event_type: string;
  channel: string;
  target?: string | null;
  enabled: boolean;
}

export interface NotificationPrefsResponse {
  prefs: NotificationPrefItem[];
}

export interface PutNotificationPrefRequest {
  id?: string;
  scope_kind?: string;
  scope_ref?: string;
  event_type: string;
  channel: string;
  target?: string | null;
  enabled?: boolean;
}

export interface MemoryQueryRequest {
  kind?: string;
  limit?: number;
}

export interface MemoryItem {
  id: string;
  owner_scope: string;
  kind: string;
  content: unknown;
  source_ref?: string | null;
}

export interface MemoryQueryResponse {
  items: MemoryItem[];
  scopes: string[];
}

// ===========================================================================
// Round Four: settings, account & access management (boltrig/kernel/
// access_routes.py). Per-user routes act on the caller's own scope; admin
// routes require org-admin (a 403 returns {status:"denied", reason} which the
// UI renders as a notice). User/invitation scope is a free-form dict
// (departments / nouns / verbs visible), typed as a Record here.
// ===========================================================================

export interface UserProfile {
  id: string;
  email?: string | null;
  display_name?: string | null;
  role?: string;
  scope?: Record<string, unknown>;
  status?: string;
  source?: string;
  source_group?: string | null;
  last_seen_at?: string | null;
}

export interface MeSettingsResponse {
  profile: UserProfile;
  settings: Record<string, unknown>;
}

// PUT accepts either {key, value} or {settings: {k: v}}.
export interface PutSettingsRequest {
  key?: string;
  value?: unknown;
  settings?: Record<string, unknown>;
}

export interface PutSettingsResponse {
  status: string;
  keys?: string[];
  reason?: string;
}

export interface ActivityRow {
  seq: number;
  ts: string | null;
  verb: string;
  status: string;
  run_id?: string | null;
}

export interface MeActivityResponse {
  results: ActivityRow[];
}

export interface ExportConversation {
  id: string;
  title: string;
  status: string;
}

export interface ExportWorkItem {
  id: string;
  intent: string;
  status: string;
}

export interface MeExportResponse {
  user: string;
  conversations: ExportConversation[];
  work_items: ExportWorkItem[];
  settings: Record<string, unknown>;
}

// {status, id} on success; {status:"error"|"denied", reason} on 404/403.
export interface DeleteAck {
  status: string;
  id?: string;
  reason?: string;
}

// A personal access token as listed: never the secret or the hash (PAT-02).
export interface PatView {
  id: string;
  name: string;
  scope: string[];
  created_at?: string | null;
  last_used_at?: string | null;
  expires_at?: string | null;
  revoked: boolean;
}

export interface TokensResponse {
  tokens: PatView[];
}

export interface MintTokenRequest {
  name: string;
  scope?: string[];
  ttl_days?: number;
}

// On success the body spreads a PatView plus the one-time `secret`; on rejection
// it is {status:"error", reason}.
export interface MintTokenResponse extends Partial<PatView> {
  status: string;
  secret?: string;
  reason?: string;
}

export interface ConnectionsResponse {
  rest_base: string;
  mcp_endpoint: string;
  auth: string;
  snippets: { claude_code: string; curl: string };
  note: string;
}

export interface SessionView {
  id: string;
  client?: string | null;
  revoked: boolean;
  created_at?: string | null;
  last_seen_at?: string | null;
}

export interface SessionsResponse {
  sessions: SessionView[];
}

export interface MeNotificationItem {
  id: string;
  event_type: string;
  channel: string;
  target?: string | null;
  enabled: boolean;
}

export interface MeNotificationsResponse {
  prefs: MeNotificationItem[];
}

export interface PutMeNotificationRequest {
  id?: string;
  event_type: string;
  channel: string;
  target?: string | null;
  enabled?: boolean;
}

export interface PersonalAgentView {
  id: string;
  runtime: string;
  skills: string[];
  enabled: boolean;
}

export interface MeAgentResponse {
  agent: PersonalAgentView | null;
}

export interface DirectoryUser {
  id: string;
  email?: string | null;
  display_name?: string | null;
  role: string;
  scope: Record<string, unknown>;
  status: string;
  source?: string;
  source_group?: string | null;
  last_seen_at?: string | null;
}

// users present on success; {status:"denied", reason} when the server refuses.
export interface AdminUsersResponse {
  users?: DirectoryUser[];
  status?: string;
  reason?: string;
}

export interface PatchUserRequest {
  role?: string;
  scope?: Record<string, unknown>;
  status?: "active" | "deactivated";
}

export interface PatchUserResponse {
  status: string;
  user?: DirectoryUser;
  reason?: string;
}

export interface AdminInvitation {
  id: string;
  email: string;
  intended_role: string;
  intended_scope: Record<string, unknown>;
  status: string;
  invited_by: string;
  expires_at?: string | null;
}

export interface AdminInvitationsResponse {
  invitations?: AdminInvitation[];
  status?: string;
  reason?: string;
}

export interface CreateInvitationRequest {
  email: string;
  role?: string;
  scope?: Record<string, unknown>;
  ttl_days?: number;
}

export interface CreateInvitationResponse {
  status: string;
  id?: string;
  email?: string;
  reason?: string;
}

// ===========================================================================
// Round Five: memory & knowledge (boltrig/kernel/memory_routes.py). recall /
// remember / forget / ingest run the memory.* verbs through the chokepoint, so
// when memory is disabled the verb routes return {status:"error",
// reason:"binding_not_found"} (the UI surfaces that as "memory not enabled").
// Reads (facts / ingestions) are scope-filtered server-side. Returned facts
// carry provenance so the surface can show WHY a fact is known.
// ===========================================================================

export type MemoryDataClass = "standard" | "sensitive" | string;
export type RecallMode = "similarity" | "graph_completion";

export interface MemoryProvenance {
  source_kind?: string | null;
  source_ref?: string | null;
  // present on browse (GET /facts)
  created_at?: string | null;
  // present on graph_completion recall: how the fact was reached
  hops?: number;
  path?: string[];
}

export interface MemoryFactView {
  id: string;
  owner_scope: string;
  kind: string;
  content: unknown;
  data_class: MemoryDataClass;
  provenance: MemoryProvenance;
}

export interface MemoryFactsResponse {
  facts: MemoryFactView[];
  scopes: string[];
}

export interface MemoryRecallRequest {
  query: string;
  mode?: RecallMode;
  limit?: number;
}

// success: {facts, count}; denial / memory-off: {status, reason}.
export interface MemoryRecallResponse {
  facts?: MemoryFactView[];
  count?: number;
  status?: string;
  reason?: string;
}

export interface MemoryRememberRequest {
  content: string;
  owner_scope?: string;
  kind?: string;
  source_kind?: string;
  source_ref?: string;
  data_class?: MemoryDataClass;
  relates_to?: string[];
}

export interface MemoryRememberResponse {
  status: string;
  fact_ids?: string[];
  owner_scope?: string;
  reason?: string;
}

export interface MemoryForgetRequest {
  target?: string;
  source_ref?: string;
}

export interface MemoryForgetResponse {
  status: string;
  erasure_id?: string;
  removed?: string[];
  facts_removed?: number;
  engine_confirmed?: boolean;
  transcript_handled?: boolean;
  reason?: string;
}

export interface MemoryIngestRequest {
  source_kind: string;
  source_ref: string;
  owner_scope?: string;
  items?: string[];
}

export interface MemoryIngestResponse {
  status: string;
  id?: string;
  ingestion_status?: string;
  facts_added?: number;
  screened?: number;
  reason?: string;
}

export interface MemoryIngestionRow {
  id: string;
  source_kind: string;
  source_ref: string;
  owner_scope: string;
  status: string;
  facts_added: number;
  screened: number;
  created_at?: string | null;
}

export interface MemoryIngestionsResponse {
  ingestions: MemoryIngestionRow[];
}
