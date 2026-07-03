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

// One page of the owner-scoped conversation list (US-CONV-09). Asking for a
// page (a limit and/or a non-zero offset) returns this shape: the page's rows
// plus next_offset, the offset to request for the following page (null once the
// list is exhausted). A bare GET /v1/conversations (no params) still returns the
// unpaginated ConversationsResponse above, so that legacy path is untouched.
export interface ConversationsPageResponse {
  conversations: ConversationSummary[];
  next_offset: number | null;
}

// One search hit (US-CONV-10): a conversation summary plus a bounded snippet of
// the matched message body when the match was on content (null when the match
// was on the title alone, or when no preview was recorded).
export interface ConversationSearchResult extends ConversationSummary {
  snippet: string | null;
}

// One page of owner-scoped conversation search results. Same next_offset
// pagination contract as the list; an empty query is rejected 400 server-side
// and is never sent from the client.
export interface ConversationSearchResponse {
  results: ConversationSearchResult[];
  next_offset: number | null;
}

export type ChatRole = "user" | "assistant" | "system" | string;

// An inline, size-capped chat attachment ([2026] VJS-COUNTY 3). The send body
// carries {name, media_type, data} (data is base64 of the raw file bytes); the
// GET transcript view additionally carries the server-recorded decoded `size`.
// The caps (count / per-file / total decoded bytes) are enforced fail-closed at
// intake against ChatConfig, and mirrored client-side so an over-cap turn is
// rejected before it is sent.
export interface ChatAttachment {
  name: string;
  media_type: string;
  data: string;
  size?: number;
}

// A persisted message. `events` carries the structured turn (tool calls,
// sub-agents, HITL) so a re-opened conversation re-renders the same cards as
// the live stream did. `attachments` are the turn's recorded inputs and
// `superseded_by` names the newer message that froze this one (regenerate).
export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  run_id?: string | null;
  hitl_request_id?: string | null;
  events?: ChatEvent[];
  attachments?: ChatAttachment[];
  superseded_by?: string | null;
  created_at: string;
}

export interface ConversationResponse {
  messages: ChatMessage[];
}

export interface ChatRequest {
  // omit to start a new conversation; the first message_start returns the id
  conversation_id?: string;
  message: string;
  // inline, size-capped attachments ({name, media_type, data:base64}); omitted
  // when the turn carries none.
  attachments?: ChatAttachment[];
}

// POST /v1/me/conversations/{cid}/messages/{mid}/regenerate: re-runs the last
// user turn on a new run id and appends a fresh assistant reply, freezing the
// prior one (superseded_by). Owner-only; 409 regenerate_not_eligible when the
// target is not the last assistant message.
export interface RegenerateResponse {
  status: string;
  conversation_id?: string;
  message_id?: string;
  superseded?: string;
  run_id?: string;
  reason?: string;
}

// POST /v1/runs/{run_id}/cancel: owner-only cooperative cancel. On success the
// run's SSE stream emits a terminal `cancelled` event and closes.
export interface CancelRunResponse {
  status: string;
  run_id?: string;
  reason?: string;
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
// A tool call as it appears live. The user-facing chat stream is bounded (K-20,
// US-CHAT-10): it carries only `tool` (the verb id), a `call_id` to pair the
// call with its result, and an `args_summary` of the argument KEYS (never the
// values). The run relay additionally carries the full `verb`/`input` for the
// run canvas + the durable record, which the Run drawer renders; both are
// optional so this one type serves both streams.
export interface ToolArgsSummary {
  keys: string[];
  count?: number;
}
export interface ChatToolCall {
  type: "tool_call";
  run_id?: string;
  // the verb id: the chat stream sends `tool`; the run relay also carries `verb`
  tool?: string;
  verb?: string;
  call_id?: string;
  args_summary?: ToolArgsSummary;
  // full input rides only on the run relay (absent on the bounded chat stream)
  input?: unknown;
  // legacy: older frames set a literal "running"; the normaliser no longer needs it
  status?: "running";
}
// The paired result, matched to its call by `call_id`. The chat stream carries
// only `call_id`, `status` and a keys-only `result_summary`; the run relay also
// carries the full `output`.
export interface ToolResultSummary {
  keys?: string[];
  status?: string;
  [key: string]: unknown;
}
export interface ChatToolResult {
  type: "tool_result";
  run_id?: string;
  call_id?: string;
  verb?: string;
  // "ok" | "error" | "degraded" | a denial/error reason string
  status: string;
  result_summary?: ToolResultSummary;
  // full output rides only on the run relay (absent on the bounded chat stream)
  output?: unknown;
}
// A keep-alive on a quiet-but-live stream. It is NOT part of the transcript and
// is never rendered: its sole job is to reset the client idle-timeout guard
// (handled in the SSE pump, so it never reaches a consumer). See client.ts.
export interface ChatHeartbeat {
  type: "heartbeat";
  run_id?: string;
}
// The agent is asking the user a clarifying QUESTION (US-CHAT-12). The prompt +
// choices are agent-authored model output and may surface on the stream; the
// user's ANSWER is submitted (and enveloped as untrusted data) via
// POST /v1/hitl/{question_id}/answer, which requeues the paused run.
export interface ChatQuestion {
  type: "question";
  run_id?: string;
  question_id: string;
  prompt: string;
  choices?: string[];
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
// A run's SSE stream emits this terminal notice when the turn was cancelled
// server-side (POST /v1/runs/{run_id}/cancel). It ends the stream cleanly.
export interface ChatCancelled {
  type: "cancelled";
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
  | ChatQuestion
  | ChatHeartbeat
  | ChatMessageEnd
  | ChatCancelled
  | ChatWorkflowStep;

// POST /v1/hitl/{question_id}/answer: owner-only, fail-closed answer to an
// agent's clarifying QUESTION. On success {status:"ok", question_id, response_id,
// run_id} and the backend requeues the paused run; a 400/403/404/409 returns
// {status:"error"|"denied", reason} which the card surfaces in place.
export interface AnswerQuestionResponse {
  status: string;
  question_id?: string;
  response_id?: string;
  run_id?: string;
  reason?: string;
}

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

// --- Channels (decision 0003, admin-gated CRUD) -----------------------------
// The webhook / request-response channel class the kernel exposes at
// /v1/channels. Management is admin-gated (the server 403s a non-author); the
// ingress webhook authenticates by the channel's own signature, never here.

export interface ChannelSummary {
  id: string;
  platform: string;
  name: string;
  transport: string;
  enabled: boolean;
  unpaired_behavior: string;
}

// channels present on success; {status:"denied", reason} when not an author.
export interface ChannelsResponse {
  channels?: ChannelSummary[];
  status?: string;
  reason?: string;
}

export interface ConnectChannelRequest {
  platform: string;
  name: string;
  // Optional HMAC signing secret; stored kernel-side (SEC-05), never returned.
  signing_secret?: string;
  unpaired_behavior?: string;
  enabled?: boolean;
  config?: Record<string, unknown>;
}

export interface ConnectChannelResponse {
  status: string;
  channel?: string;
  inbound_url?: string;
  reason?: string;
}

export interface ConfigureChannelRequest {
  name?: string;
  unpaired_behavior?: string;
  enabled?: boolean;
  config?: Record<string, unknown>;
}

export interface ChannelBindingSummary {
  id: string;
  external_user_id: string;
  subject: string;
  role: string;
}

export interface ChannelBindingsResponse {
  bindings?: ChannelBindingSummary[];
  status?: string;
  reason?: string;
}

export interface PairChannelRequest {
  external_user_id: string;
  subject: string;
  role: string;
  ttl_minutes?: number;
}

// The one-time pairing code is returned ONCE and never again (shown via
// SecretOnce); a later fetch cannot retrieve it.
export interface PairChannelResponse {
  status: string;
  pairing_id?: string;
  code?: string;
  reason?: string;
}

export interface BindChannelRequest {
  external_user_id: string;
  subject: string;
  role: string;
}

export interface BindChannelResponse {
  status: string;
  binding?: string;
  reason?: string;
}

// A minimal {status, reason} ack for channel mutations that return no body.
export interface ChannelAck {
  status: string;
  reason?: string;
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

export interface CapabilityChange {
  ts: string;
  actor: string;
  action: string;
  ref: string;
  status: string;
}

export interface CapabilityChangelogResponse {
  changes: CapabilityChange[];
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

// PATCH /v1/me/conversations/{id}: the new title (1-120 chars, owner-only).
export interface RenameConversationRequest {
  title: string;
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
