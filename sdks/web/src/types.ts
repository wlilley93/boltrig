// Types that mirror the kernel HTTP surface (boltrig/kernel/app.py).
// Fields the kernel may add later (binding target, live verb health) are kept
// optional so the client tolerates their absence.

export type AdapterHealth = "ok" | "degraded" | "down" | "unknown";

export interface HealthResponse {
  status: string;
  // keyed by "<tenant>/<adapterId>"
  adapters: Record<string, AdapterHealth>;
}

export interface ReadinessCheck {
  status: string;
  required: boolean;
  reason?: string;
  [key: string]: unknown;
}

export interface ReadinessResponse {
  status: "ready" | "not_ready" | string;
  checks: Record<string, ReadinessCheck>;
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
  idempotency_mode?: "cacheable" | "disabled" | string;
  [key: string]: unknown;
}

export interface CapabilitiesResponse {
  verbs: VerbInfo[];
  nouns?: unknown;
  workflows?: unknown;
  agent_capabilities?: AgentCapabilityInfo[];
}

export interface AgentCapabilityInfo {
  name: string;
  runtime: string;
  supported_skills: string[];
  max_depth: number;
  is_ephemeral: boolean;
  cost_tier: string;
  model_endpoint?: string | null;
  familiar_genotype: FamiliarGenotype;
}

export interface AgentCapabilityAuthorInfo extends AgentCapabilityInfo {
  source: "manifest" | "control-plane";
  is_active: boolean;
  status: "active" | "retired";
}

export interface AgentCapabilitiesResponse {
  agent_capabilities: AgentCapabilityAuthorInfo[];
}

export interface CapabilityLifecycleResponse {
  status: "ok" | "pending_human" | "error";
  id?: string;
  capability_status?: "active" | "retired";
  hitl_request_id?: string;
  reason?: string;
}

export interface PermanentFleetBudget {
  token_limit: number | null;
  cost_limit_micros: number | null;
  hard_stop: boolean;
  window: "run" | "daily" | "monthly";
}

export interface PermanentFleetHead {
  name: string;
  routing_id: string;
  purpose: string;
  brief: string;
  runtime: "codex" | "script";
  model_endpoint: string | null;
  supported_skills: string[];
  max_depth: number;
  cost_tier: "cheap" | "standard" | "expensive";
  budget: PermanentFleetBudget | null;
}

export interface PermanentFleetHierarchy {
  chief: PermanentFleetHead;
  departments: PermanentFleetHead[];
}

export interface PermanentFleetObservation {
  worker_id: string;
  generation: string;
  status: "applied" | "degraded";
  apply_mode: "startup_snapshot" | string;
  applied_fields: string[];
  inactive_fields: string[];
  observed_at?: string | null;
}

export interface PermanentFleetResponse {
  status: "configured" | "not_configured";
  hierarchy: PermanentFleetHierarchy | null;
  generation: string | null;
  revision: number | null;
  apply_state:
    | "not_configured"
    | "restart_required"
    | "startup_applied_liveness_unknown";
  hot_applied?: false;
  runtime_liveness?: "unknown_not_probed_by_startup";
  profiles_reconciled?: boolean;
  reconcile_at?: "next_manifest_apply_or_redeploy" | null;
  projection_state?: {
    persistent_profiles: "projected" | "desired_awaiting_manifest_apply";
    budget_policy:
      | "projected"
      | "not_authored"
      | "desired_awaiting_manifest_apply";
  };
  observations: PermanentFleetObservation[];
  field_state?: Record<string, string>;
}

export interface PermanentFleetApplyResponse {
  status: "ok" | "pending_human" | "error" | "denied";
  generation?: string;
  revision?: number;
  apply_state?: "restart_required";
  hot_applied?: false;
  profiles_reconciled?: false;
  reconcile_at?: "next_manifest_apply_or_redeploy";
  hitl_request_id?: string;
  reason?: string;
}

export interface ModelEndpointInfo {
  id: string;
  kind: string;
  model: string;
  data_class: string;
  is_active: boolean;
  status: "active" | "retired";
}

export interface ModelEndpointsResponse {
  endpoints: ModelEndpointInfo[];
}

export interface ModelEndpointAuthorView extends ModelEndpointInfo {
  base_url?: string | null;
  fallback?: string | null;
  references: {
    capabilities: string[];
    fallbacks: string[];
  };
}

export interface ModelEndpointResponse {
  endpoint: ModelEndpointAuthorView;
}

export interface ModelEndpointLifecycleResponse {
  status: "ok" | "pending_human" | "error";
  id?: string;
  model_endpoint_status?: "active" | "retired";
  hitl_request_id?: string;
  reason?: string;
}

export type ModelPolicyEndpointState =
  | "not_configured"
  | "missing"
  | "retired"
  | "active";

export interface ModelPolicyResponse {
  policy: {
    state: "unconfigured" | "configured" | "degraded";
    source: "no_process_manifest" | "process_start_manifest";
    generation: string | null;
    default: {
      endpoint_id: string | null;
      state: ModelPolicyEndpointState;
      serving_state: "inactive_no_consumer";
    };
    sensitive: {
      endpoint_id: string | null;
      state: ModelPolicyEndpointState;
      serving_state:
        | "not_configured"
        | "active_process_policy"
        | "refuses_sensitive_routing";
      eligible: boolean;
    };
    prices: Array<{
      model: string;
      input_micros_per_token: number;
      output_micros_per_token: number;
    }>;
    price_serving_state:
      | "not_configured"
      | "active_process_cost_accountant";
    changes_apply_at: "process_restart";
  };
}

export interface SpawnRulePolicyItem {
  id: string;
  priority: number;
  intent_tags: string[];
  capability: string;
  skills_added: string[];
  max_depth: number | null;
}

export interface SpawnRuleConflict {
  priority: number;
  rules: string[];
  example_intent_tags: string[];
}

export interface SpawnRulePolicyResponse {
  policy: {
    state: "ready" | "conflicted" | "invalid_policy" | "policy_unavailable";
    source: "process_start_manifest" | "config_revision" | null;
    revision_id: number | null;
    generation: string | null;
    rules: SpawnRulePolicyItem[];
    conflicts: SpawnRuleConflict[];
    execution_input: "server_trusted_classification_only";
  };
}

export interface SpawnRuleSimulationResponse {
  status:
    | "matched"
    | "no_match"
    | "conflict"
    | "invalid_input"
    | "invalid_policy"
    | "policy_unavailable";
  input_trust: "untrusted_preview_only";
  selection: SpawnRulePolicyItem | null;
  generation?: string;
  reason?: string;
}

export interface HitlPolicyResponse {
  policy: {
    state: "unconfigured" | "configured";
    source: "no_process_manifest" | "process_start_manifest";
    generation: string | null;
    blocking_verbs: string[];
    approval_timeout_seconds: number | null;
    routing: {
      primary_channel: string | null;
      notify_via: string[];
      escalation_chain: string[];
      serving_state: "inactive_no_consumer";
    };
    changes_apply_at: "process_restart";
  };
}

export interface PrivacyPolicyResponse {
  policy: {
    state: "unconfigured" | "partial";
    source: "no_process_manifest" | "process_start_manifest";
    generation: string | null;
    retention: {
      days: number | null;
      serving_state: "not_configured" | "closed_conversations_only";
      coverage: string[];
    };
    redaction: {
      configured: boolean;
      fields: string[];
      serving_state: "inactive_no_consumer";
    };
    residency: {
      region: string | null;
      serving_state: "inactive_no_consumer";
    };
    compliance_export: "account_summary_only";
  };
}

export interface BackupStatusResponse {
  backup: {
    state:
      | "unconfigured"
      | "configuration_invalid"
      | "never_observed"
      | "unavailable"
      | "invalid_marker"
      | "fresh"
      | "stale";
    evidence_kind: "shared_success_marker";
    maximum_age_seconds: number;
    last_success_at: string | null;
    age_seconds: number | null;
    off_box_state: "unknown_not_in_marker";
    encryption_state: "unknown_not_in_marker";
    restore_readiness: "unavailable_no_restore_drill_receipt";
    liveness_claimed: false;
  };
}

export type WorkStatus =
  | "pending"
  | "in_flight"
  | "blocked"
  | "awaiting_human"
  | "done"
  | "failed"
  | "cancelled";

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
  on_behalf_of?: string | null;
  depth?: number;
  workspace_id?: string | null;
}

export interface WorkResponse {
  items: WorkItem[];
  limit?: number;
  next_cursor?: string | null;
}

export interface WorkAuditEvent {
  ts: string;
  actor: string;
  actor_tier: string;
  noun: string;
  verb: string;
  status: string;
  detail?: unknown;
}

export interface WorkDetailResponse {
  item: WorkItem;
  children: WorkItem[];
  audit: WorkAuditEvent[];
}

export interface CreateWorkRequest {
  intent: string;
  owner_member?: string | null;
  parent_id?: string | null;
  confidence?: number;
  convergent?: boolean;
  idempotency_key?: string;
}

export interface WorkMutationResponse {
  status: "ok";
  item: WorkItem;
}

export type WorkMutationResult =
  | WorkMutationResponse
  | PendingHumanResponse
  | { status: "denied" | "error"; reason: string }
  | { status: "degraded"; output: unknown };

export type HITLKind = "approval" | "clarification" | "escalation" | "question";

export interface HITLRequest {
  id: string;
  type: HITLKind;
  urgency?: string;
  question: string;
  context?: unknown;
  options?: string[];
  work_item_id?: string | null;
  status?: string;
  run_id?: string | null;
  verb?: string | null;
  requested_by?: string | null;
  requested_on_behalf_of?: string | null;
  inputs?: unknown;
  secure?: boolean;
  secure_purpose?: string | null;
}

export interface HITLListResponse {
  requests: HITLRequest[];
}

export interface RespondResult {
  status: string;
  response_id?: string;
  run_id?: string;
  reason?: string;
}

export interface InvokeRequest {
  noun: string;
  verb: string;
  params?: Record<string, unknown>;
  context?: Record<string, unknown>;
  idempotency_key?: string;
  approval_id?: string;
}

export interface PendingHumanResponse {
  status: "pending_human";
  hitl_request_id: string;
}

export interface InvokeApprovalStateResponse {
  status: "pending" | "approved" | "rejected" | "expired" | "consumed";
}

// Compatibility author/admin routes use the same HITL gate as /v1/invoke, so
// every high-consequence route may honestly return a 202 pause instead of its
// ordinary success body.
export type GovernedRouteResponse<T> = T | PendingHumanResponse;

// The kernel returns different bodies per status code; this is the union.
export type InvokeResult =
  | { status: "ok"; output: unknown }
  | PendingHumanResponse
  | { status: "denied"; reason: string }
  | { status: "unavailable"; reason: string }
  | { status: "degraded"; output: unknown }
  | { status: "error"; reason: string };

export interface SpawnRequest {
  task: string;
  skills?: string[];
  prefer?: Record<string, unknown>;
  context?: Record<string, unknown>;
}

export interface SpawnRuleReceipt {
  id: string;
  priority: number;
  matched_intent_tags: string[];
  capability: string;
  skills_added: string[];
  max_depth: number | null;
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

export type FederatedSearchSource =
  | "conversations"
  | "executions"
  | "knowledge"
  | "memory"
  | "audit";

export type FederatedSearchSourceStatus =
  | "ok"
  | "denied"
  | "unavailable";

export interface FederatedSearchRequest {
  query: string;
  limit?: number;
  sources?: FederatedSearchSource[];
}

export interface FederatedSearchHit {
  source: FederatedSearchSource;
  id: string;
  title: string;
  preview: string | null;
  route: "chat" | "runs" | "knowledge" | "memory" | "operate";
  route_id: string | null;
  score?: number | null;
  occurred_at?: string | null;
  metadata: Record<string, unknown>;
}

export interface FederatedSearchSourceResult {
  source: FederatedSearchSource;
  status: FederatedSearchSourceStatus;
  count: number;
  truncated: boolean;
  reason?: string;
}

export interface FederatedSearchResponse {
  query: string;
  limit: number;
  results: FederatedSearchHit[];
  sources: FederatedSearchSourceResult[];
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

export interface ChatAttachmentLimits {
  max_count: number;
  max_bytes: number;
  max_total_bytes: number;
  model_readable_media_types: string[];
}

export interface ChatConfigResponse {
  attachments: ChatAttachmentLimits;
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

export interface ConversationModelContext {
  compacted: boolean;
  covered_count: number;
  recent_exact_count: number;
  up_to_message_id?: string | null;
  summary?: string | null;
}

export interface ConversationResponse {
  messages: ChatMessage[];
  active_run_id?: string | null;
  model_context?: ConversationModelContext;
}

export interface ChatFollowFrame {
  cursor: number;
  event: ChatEvent;
  replay_truncated?: boolean;
}

export interface ChatRequest {
  // omit to start a new conversation; the first message_start returns the id
  conversation_id?: string;
  message: string;
  // inline, size-capped attachments ({name, media_type, data:base64}); omitted
  // when the turn carries none.
  attachments?: ChatAttachment[];
  // Exactly-once key for THIS user message, chosen by the caller. A retry that
  // reuses it is answered as an accepted replay instead of convening a second
  // agent. Measured on a live tenant before this existed: one message sent five
  // times 1.4-2.1s apart produced seven agent_spawn rows - N times the spend and
  // N duplicate answers. Omit for today's behaviour.
  idempotency_key?: string;
  // WHICH SURFACE this turn arrived through, so one conversation can span two of
  // them and still say where each turn came from. A label only: it reaches no
  // authority or routing decision, and an unusable value is dropped rather than
  // failing the message. Lower-case, <=64 chars of [a-z0-9._:-] starting alnum.
  origin?: string;
  // One administrator-approved, caller-visible routing profile. The server
  // remains authoritative and may override this request under classification,
  // availability, or cost policy; the selected profile is emitted as a
  // model_routing event.
  model_profile_id?: string;
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
  degraded?: boolean;
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
  consequence?: "low" | "high";
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
  secure?: boolean;
  purpose?: string;
}
export interface ChatSubagent {
  type: "subagent";
  child_run_id: string;
  task: string;
  skills?: string[];
  // Optional identity so delegation cards (brief sec 6.4) can render the real
  // sub-agent name/role/color and a real step count. Backward compatible: older
  // streams omit these and the UI falls back to the palette + derived initials.
  name?: string;
  role?: string;
  color?: string;
  step_count?: number;
  // Server-derived policy receipt. Absent means ordinary capability selection;
  // clients must never infer a rule from the capability or task text.
  spawn_rule?: SpawnRuleReceipt;
  // Familiar identity is optional birth configuration. Phenotype/mood is
  // deliberately absent: clients derive it from current run/call facts.
  familiar_genotype?: FamiliarGenotype | null;
}
export interface ChatHitlEvent {
  type: "hitl";
  hitl_request_id: string;
  kind?: HITLKind;
  question?: string;
  options?: string[];
  verb?: string;
  call_id?: string;
  requested_by?: string;
  secure?: boolean;
  secure_purpose?: string | null;
  purpose?: string;
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
  status: "running" | "ok" | "failed" | "skipped" | "paused" | "error";
}

// The interpreter's run-level state marker. A completed or failed marker lets
// live clients settle their follow connection without waiting for an idle
// timeout; paused remains open because the same run may resume after approval.
export interface ChatWorkflowRun {
  type: "workflow_run";
  run_id: string;
  workflow_id: string;
  status: "completed" | "failed" | "paused";
}

// The non-secret explanation of the model route selected for this run. Provider
// URLs, account identifiers, and credentials are never fields in this event.
export interface ChatModelRouting {
  type: "model_routing";
  run_id: string;
  selected_profile_id: string;
  routing_class: string;
  reason: string;
  requested_profile_id?: string | null;
  overridden: boolean;
}

/**
 * The paired settle for a `subagent` open frame (G3). The kernel emits it on the
 * SAME parent relay with the SAME `child_run_id`, so a consumer upserts by that id
 * and the delegation node flips RUNNING -> DONE/FAILED instead of gaining a
 * duplicate row.
 *
 * This union omitted it, so the console silently dropped a frame the kernel emits
 * and opbox already handles: the same delegation settled in one frontend and span
 * forever in the other - exactly the drift a shared contract exists to prevent.
 * An un-upgraded kernel emits no `subagent_end`, so a node simply stays running,
 * which is an honest reflection of what that kernel reports.
 */
export interface ChatSubagentEnd {
  type: "subagent_end";
  child_run_id: string;
  status: "ok" | "degraded" | "error";
}

/** A steer queued behind the in-flight turn (US-CHAT-13). Carries no turn content. */
export interface ChatSteerQueued {
  type: "steer_queued";
  run_id?: string;
  conversation_id?: string;
  message_id?: string;
}

/** A queued steer being consumed as its own run. Carries no turn content. */
export interface ChatSteerConsumed {
  type: "steer_consumed";
  run_id?: string;
  conversation_id?: string;
  message_id?: string;
}

/** A newly persisted output is ready to fetch through the governed artifact API. */
export interface ChatArtifact {
  type: "artifact";
  artifact_id: string;
  name: string;
  media_type: string;
  size: number;
  run_id?: string;
}

/** One or more runtime-declared outputs failed the bounded artifact contract. */
export interface ChatArtifactRejected {
  type: "artifact_rejected";
  count: number;
  run_id?: string;
}

/**
 * A relay frame was intentionally withheld because it is not part of the
 * reviewed public chat vocabulary or did not satisfy that vocabulary.
 */
export interface ChatEventUnavailable {
  type: "event_unavailable";
  reason: "unsupported_event" | "malformed_event";
}

export type ChatEvent =
  | ChatMessageStart
  | ChatTextDelta
  | ChatReasoningDelta
  | ChatToolCall
  | ChatToolResult
  | ChatSubagent
  | ChatSubagentEnd
  | ChatSteerQueued
  | ChatSteerConsumed
  | ChatHitlEvent
  | ChatQuestion
  | ChatHeartbeat
  | ChatMessageEnd
  | ChatCancelled
  | ChatWorkflowStep
  | ChatWorkflowRun
  | ChatModelRouting
  | ChatArtifact
  | ChatArtifactRejected
  | ChatEventUnavailable;

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
  spawn_rule?: SpawnRuleReceipt;
  [key: string]: unknown;
}

// --- Skill Studio -----------------------------------------------------------

export interface SkillSummary {
  id: string;
  version: string;
  extends?: string | null;
  tool_grants: string[];
  locale: string;
  is_active: boolean;
  status: "active" | "archived";
}

export interface SkillsResponse {
  skills: SkillSummary[];
}

export interface SkillAuthorView extends SkillSummary {
  prompt_fragment: string;
  context_requirements: Record<string, unknown>;
  description: string;
}

export interface SkillResponse {
  skill: SkillAuthorView;
}

export interface UpsertSkillRequest {
  id: string;
  version?: string;
  prompt_fragment?: string;
  tool_grants?: string[];
  context_requirements?: Record<string, unknown>;
  extends?: string | null;
  locale?: string;
  description?: string;
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

export interface NounAuthorView {
  id: string;
  description: string;
  schema: Record<string, unknown>;
  is_active: boolean;
  status: "active" | "archived";
}

export interface NounResponse {
  noun: NounAuthorView;
}

export interface NounsResponse {
  nouns: NounAuthorView[];
}

export interface UpsertVerbRequest {
  id: string;
  noun_id: string;
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown>;
  description?: string;
  consequence?: "low" | "high";
  degraded_mode?: Record<string, unknown>;
  identity_mode?: "service-principal" | "delegated";
  idempotency_mode?: "cacheable" | "disabled";
}

export type TargetTypeValue = "adapter" | "agent";

export interface SetBindingRequest {
  target_type: TargetTypeValue;
  target_ref: string;
  rate_limit?: {
    per: "minute" | "hour";
    max: number;
    scope?: "tenant" | "verb";
  };
}

export interface VerbAuthorView {
  id: string;
  noun_id: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  description: string;
  consequence: "low" | "high";
  degraded_mode?: Record<string, unknown> | null;
  identity_mode: "service-principal" | "delegated";
  idempotency_mode: "cacheable" | "disabled";
  is_active: boolean;
  status: "active" | "archived";
  noun_status: "active" | "archived";
}

export interface VerbResponse {
  verb: VerbAuthorView;
  binding?: (VerbBinding & {
    rate_limit?: {
      per: "minute" | "hour";
      max: number;
      scope: "tenant" | "verb";
    } | null;
  }) | null;
}

export interface VerbInventoryItem extends VerbAuthorView {
  binding?: (VerbBinding & {
    rate_limit?: {
      per: "minute" | "hour";
      max: number;
      scope: "tenant" | "verb";
    } | null;
  }) | null;
}

export interface VerbsResponse {
  verbs: VerbInventoryItem[];
}

export interface AuthoredDefinitionLifecycleResponse {
  status: "ok" | "pending_human" | "error";
  id?: string;
  definition_status?: "active" | "archived";
  hitl_request_id?: string;
  reason?: string;
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
  url: string;
  allow_internal?: boolean;
  credential_ref?: string;
  credential_id?: string;
  credential_store?: string;
  credential_kind?: string;
}

export type McpCredentialMode = "preserve" | "replace" | "remove";

export type UpdateMcpServerRequest =
  | {
      url: string;
      allow_internal: boolean;
      credential_mode: "preserve" | "remove";
    }
  | {
      url: string;
      allow_internal: boolean;
      credential_mode: "replace";
      credential_ref: string;
      credential_id?: string;
      credential_store?: string;
      credential_kind?: string;
    };

export interface UpdateMcpServerResponse {
  status: string;
  id?: string;
  state?: "inert";
  updated?: boolean;
  reprobe_required?: boolean;
  config_revision?: number;
  error?: string;
  reason?: string;
}

export interface DeleteMcpServerResponse {
  status: string;
  id?: string;
  deleted?: boolean;
  error?: string;
  reason?: string;
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

export type McpServerHealthStatus = "ok" | "degraded" | "down" | "unknown";
export type McpServerOperability = "ready" | "degraded" | "unavailable";
export type McpServerAction =
  | "probe"
  | "activate"
  | "deactivate"
  | "retire"
  | "restore"
  | "update"
  | "delete";
export type McpProbeFailureCode =
  | "credential_unavailable"
  | "egress_denied"
  | "transport_unavailable"
  | "protocol_invalid"
  | "discovery_invalid"
  | "unexpected_failure"
  | (string & {});

export interface McpProbeEvidence {
  checked_at: string;
  outcome: "succeeded" | "failed";
  failure_code: McpProbeFailureCode | null;
  tool_count: number;
}

export interface McpToolSnapshotEvidence {
  status: "snapshot" | "never_discovered";
  observed_at: string | null;
  count: number;
  publication_status:
    | "published"
    | "drifted"
    | "inactive"
    | "retired"
    | "never_discovered";
}

export interface McpProbeHistoryItem extends McpProbeEvidence {
  probe_id: string;
}

export interface McpServerSummary {
  id: string;
  config_revision: number;
  version: string;
  source: string;
  state: "active" | "inert" | "retired";
  activated: boolean;
  runtime_loaded: boolean;
  endpoint: {
    origin: string | null;
    path_redacted: boolean;
    internal_egress_allowed: boolean;
  };
  credential_configured: boolean;
  recorded_health: McpServerHealthStatus;
  health: {
    status: McpServerHealthStatus;
    source: "durable_probe" | "cached_adapter_probe" | "unverified";
    checked_at: string | null;
  };
  operability: {
    status: McpServerOperability;
    reason: string | null;
  };
  last_probe: McpProbeEvidence | null;
  tool_snapshot: McpToolSnapshotEvidence;
  available_actions: McpServerAction[];
}

export interface McpToolProjection {
  id: string;
  name: string;
  description: string;
  consequence: "low" | "high";
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
}

export interface McpServersResponse {
  servers: McpServerSummary[];
  truncated: boolean;
}

export interface McpServerDetailResponse {
  server: McpServerSummary;
  tools: McpToolProjection[];
  tools_status: "snapshot" | "never_discovered";
  tools_truncated: boolean;
  probe_history: McpProbeHistoryItem[];
  probe_history_truncated: boolean;
}

// --- Workflow Studio --------------------------------------------------------

export type WorkflowSourceValue = "precreated" | "generated" | "learned";
export type WorkflowLoopBindingSource = "item" | "index";

/**
 * A workflow step is intentionally open-ended: the kernel owns the complete
 * step vocabulary, while clients may understand only a subset of its fields.
 * Editors must retain keys they do not understand when replacing a workflow.
 */
export interface WorkflowStepDefinition extends Record<string, unknown> {
  id: string;
  action: string;
  parents?: string[];
  description?: string;
  params?: Record<string, unknown>;
  with?: Record<string, unknown>;
  branch?: string;
  /**
   * In a flow.loop body, replace existing top-level capability params with the
   * current typed item or zero-based index. The kernel validates the complete
   * loop contract before any body action dispatches.
   */
  loop_bindings?: Record<string, WorkflowLoopBindingSource>;
}

export interface WorkflowDefinition extends Record<string, unknown> {
  steps?: unknown[];
}

export type WorkflowScheduleObservedStatus =
  | "inactive"
  | "pending"
  | "active"
  | "needs_action"
  | "unavailable"
  | "degraded";

export interface WorkflowScheduleState {
  desired: {
    status: "inactive" | "active";
    cron?: string;
    timezone?: string;
  };
  observed: {
    status: WorkflowScheduleObservedStatus;
    reason: string | null;
    next_run_at: string | null;
    last_scheduled_for: string | null;
    observed_at: string | null;
  };
}

export interface WorkflowSummary {
  id: string;
  version: string;
  source: WorkflowSourceValue;
  intent_tags: string[];
  status: "active" | "archived";
  schedule?: { cron: string; timezone: string } | null;
  schedule_state?: WorkflowScheduleState;
}

export interface WorkflowsResponse {
  workflows: WorkflowSummary[];
}

export interface WorkflowDetail {
  id: string;
  version: string;
  source: WorkflowSourceValue;
  definition: WorkflowDefinition;
  intent_tags: string[];
  status: "active" | "archived";
  schedule?: { cron: string; timezone: string } | null;
  schedule_state?: WorkflowScheduleState;
}

export interface UpsertWorkflowRequest {
  id: string;
  version?: string;
  /** Provenance is assigned and preserved by the kernel, never authored here. */
  definition?: WorkflowDefinition;
  intent_tags?: string[];
}

export interface ScheduleWorkflowRequest {
  cron: string;
  timezone?: string;
}

export interface ScheduleWorkflowResponse {
  status: string;
  id?: string;
  schedule?: { type?: "cron"; cron: string; timezone: string };
  schedule_state?: WorkflowScheduleState;
  hitl_request_id?: string;
  reason?: string;
}

export type WorkflowScheduleOccurrenceStatus =
  | "claimed"
  | "retryable"
  | "enqueued"
  | "succeeded"
  | "failed";

export interface WorkflowScheduleOccurrence {
  scheduled_for: string;
  run_id: string;
  status: WorkflowScheduleOccurrenceStatus;
  claimed_at: string | null;
  enqueued_at: string | null;
  outcome_at: string | null;
  engine_outcome:
    | { status: "settled"; recovery: "not_applicable" }
    | {
        status: "pending_or_unknown";
        recovery: "engine_terminal_reconciliation_unavailable";
      }
    | { status: "not_enqueued"; recovery: "not_applicable" };
  reason: string | null;
  retry: {
    attempts: number;
    manual_retries: number;
    last_retry_at: string | null;
  };
}

export interface WorkflowScheduleOccurrencesResponse {
  workflow_id: string;
  occurrences: WorkflowScheduleOccurrence[];
  truncated: boolean;
  backfill: {
    status: "unavailable";
    reason: "historical_backfill_not_supported_by_canonical_claim";
  };
}

export interface RetryWorkflowScheduleOccurrenceResponse {
  status: "ok" | "pending_human" | "error";
  workflow_id?: string;
  scheduled_for?: string;
  run_id?: string;
  occurrence_status?: "retryable";
  manual_retries?: number;
  hitl_request_id?: string;
  reason?: string;
}

export interface WorkflowLifecycleResponse {
  status: "ok" | "pending_human" | "error";
  id?: string;
  workflow_status?: "active" | "archived";
  schedule?: { type?: "cron"; cron: string; timezone: string } | null;
  hitl_request_id?: string;
  reason?: string;
}

export type WorkflowTriggerSource = "webhook" | "channel";

export interface WorkflowTriggerSummary {
  id: string;
  workflow_id: string;
  workspace_id: string | null;
  name: string;
  source: WorkflowTriggerSource;
  owner_id: string;
  channel_id: string | null;
  enabled: boolean;
  secret_configured: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface WorkflowTriggersResponse {
  workflow_id: string;
  triggers: WorkflowTriggerSummary[];
}

export interface CreateWorkflowTriggerRequest {
  name: string;
  source: WorkflowTriggerSource;
  channel_id?: string;
}

export interface WorkflowTriggerMutationResponse {
  status: "ok" | "pending_human" | "error";
  trigger_id?: string;
  workflow_id?: string;
  source?: WorkflowTriggerSource;
  enabled?: boolean;
  /** Present only in the successful create/rotate response; never listable. */
  secret?: string;
  webhook_path?: string;
  hitl_request_id?: string;
  reason?: string;
}

export interface WorkflowTriggerDelivery {
  trigger_id: string;
  event_digest: string;
  status: string;
  authority_subject: string | null;
  run_id: string | null;
  hitl_request_id: string | null;
  reason: string | null;
  created_at: string | null;
}

export interface WorkflowTriggerDeliveriesResponse {
  workflow_id: string;
  trigger_id: string;
  deliveries: WorkflowTriggerDelivery[];
}

export type WorkflowTriggerFinalization =
  | {
      request_id: string;
      action: "create";
      state: "waiting" | "ready";
      name: string;
      source: "webhook";
    }
  | {
      request_id: string;
      action: "rotate";
      state: "waiting" | "ready";
      trigger_id: string;
    };

export interface WorkflowTriggerFinalizationsResponse {
  workflow_id: string;
  finalizations: WorkflowTriggerFinalization[];
}

// ===========================================================================
// Worker contracts (decision 0021)
// These are capability contracts, not availability claims. A catalogue entry,
// enrolled device, call provider, or schedule reports its explicit state.
// ===========================================================================

export interface FamiliarGenotype {
  source?: "agent_capability.name.v1";
  seed?: number;
  body?: string;
  palette?: string[];
  markings?: string[];
  accessories?: string[];
  voice_id?: string | null;
}

export interface ModelProfile {
  id: string;
  label: string;
  description?: string;
  routing_class: string;
  data_classes: string[];
  available: boolean;
  unavailable_reason?: string | null;
}

export interface ModelProfilesResponse {
  profiles: ModelProfile[];
}

export type ArtifactProvenanceKind =
  | "agent"
  | "tool"
  | "workflow"
  | "call"
  | "system";

export interface ArtifactProvenance {
  kind: ArtifactProvenanceKind;
  actor_ref?: string | null;
  source_ref?: string | null;
  tool_call_id?: string | null;
}

export interface Artifact {
  id: string;
  tenant_id?: string;
  owner_id: string;
  workspace_id?: string | null;
  conversation_id?: string | null;
  run_id?: string | null;
  work_item_id?: string | null;
  name: string;
  digest: string;
  media_type: string;
  size: number;
  revision: number;
  previous_revision_id?: string | null;
  provenance: ArtifactProvenance;
  created_at: string;
}

export interface ArtifactsResponse {
  artifacts: Artifact[];
  next_cursor?: string | null;
}

export interface ArtifactListOptions {
  conversationId?: string;
  limit?: number;
  cursor?: string;
}

export type DevicePresence = "online" | "offline" | "locked" | "revoked";
export type DeviceAvailabilityMode = "unlocked_session" | "background";
export type DeviceRootScope = "read" | "read_write";

export interface DeviceRoot {
  id: string;
  label: string;
  scope: DeviceRootScope;
  command_enabled: boolean;
  git_enabled: boolean;
}

export interface EnrolledDevice {
  id: string;
  label: string;
  public_key_fingerprint: string;
  presence: DevicePresence;
  availability_mode: DeviceAvailabilityMode;
  roots: DeviceRoot[];
  last_seen_at?: string | null;
  revoked_at?: string | null;
}

export interface DevicesResponse {
  devices: EnrolledDevice[];
}

export interface DeviceEnrollmentStart {
  authorization_code: string;
  expires_at: string;
  verification_uri: string;
  lease_verifier: {
    algorithm: string;
    key_id: string;
    public_key: string;
  };
}

export interface DeviceLease {
  id: string;
  tenant_id: string;
  device_id: string;
  root_id: string;
  owner_id: string;
  verb: string;
  action: Record<string, unknown>;
  action_digest: string;
  approval_id: string;
  issued_at: string;
  expires_at: string;
  signing_key_id: string;
  signature: string;
  status: string;
}

export type OwnerDeviceLeaseStatus =
  | "issued"
  | "claimed"
  | "completed"
  | "failed"
  | "expired";

export interface OwnerDeviceLeaseReceipt {
  code?: string;
  byte_size?: number;
  content_digest?: string;
  reported_local_result_available?: boolean;
  overwrite?: boolean;
  duration_ms?: number;
  exit_code?: number | null;
  output_captured?: false;
}

export interface OwnerDeviceLease {
  id: string;
  device_id: string;
  root_id: string;
  verb: "device.file.read" | "device.file.write" | "device.command.run";
  status: OwnerDeviceLeaseStatus;
  issued_at: string;
  expires_at: string;
  settled_at: string | null;
  receipt: OwnerDeviceLeaseReceipt | null;
}

export interface OwnerDeviceLeasesResponse {
  leases: OwnerDeviceLease[];
}

export interface CreateDeviceRootRequest {
  label: string;
  scope: DeviceRootScope;
  command_enabled?: boolean;
  git_enabled?: boolean;
}

export interface DeviceRootResponse {
  root: DeviceRoot;
}

export type AddonActivation = "active" | "inactive";
export type AddonRequirementStatus =
  | "ready"
  | "missing"
  | "degraded"
  | "unavailable"
  | "unverified";
export type AddonRequirementReason =
  | "not_configured"
  | "record_missing"
  | "not_loaded"
  | "health_degraded"
  | "health_down"
  | "health_unverified"
  | "component_missing"
  | "credential_missing"
  | "evidence_unavailable";
export type AddonRequirementEvidence =
  | "declaration"
  | "configuration_presence"
  | "credential_reference"
  | "cached_adapter_health"
  | "stack_status";
export type AddonConfigurationStatus =
  | "ready"
  | "missing"
  | "degraded"
  | "unavailable"
  | "unverified"
  | "not_required";
export type AddonRuntimeStatus =
  | "ready"
  | "degraded"
  | "unavailable"
  | "unverified"
  | "inactive";

export interface AddonRequirement {
  id: string;
  kind: "adapter" | "component" | "environment" | "credential_ref";
  required: boolean;
  status: AddonRequirementStatus;
  reason: AddonRequirementReason | null;
  evidence: AddonRequirementEvidence;
}

export interface RuntimeAddon {
  id: string;
  version: string;
  installation: "installed";
  activation: AddonActivation;
  contributions: {
    harness: boolean;
    adapter: boolean;
    consequence_hint: boolean;
  };
  configuration: {
    status: AddonConfigurationStatus;
    requirements: AddonRequirement[];
  };
  runtime: {
    status: AddonRuntimeStatus;
    reason: AddonRequirementReason | null;
  };
}

export interface AddonsResponse {
  scope: {
    tenant_id: string;
    workspace_id: string | null;
  };
  addons: RuntimeAddon[];
}

export type IntegrationTransport = "rest" | "mcp" | "channel_gateway" | "browser";
export type IntegrationAuthKind = "oauth2" | "manual_secret" | "channel_pairing";
export type IntegrationCertification =
  | "uncertified"
  | "certifying"
  | "certified"
  | "suspended";
export type IntegrationConnectionHealth =
  | "pending"
  | "ok"
  | "degraded"
  | "down"
  | "revoked";

export interface IntegrationCatalogueEntry {
  id: string;
  label: string;
  category:
    | "communications"
    | "work"
    | "storage_design"
    | "crm_sales"
    | "finance"
    | "analytics_operations"
    | "browser";
  transport: IntegrationTransport;
  auth: IntegrationAuthKind[];
  description: string;
  certification: IntegrationCertification;
  setup_copy?: string;
  access_copy?: string;
  available?: boolean;
  availability_reason?: string | null;
  setup_supported?: boolean;
  setup_contract?: IntegrationManualSecretContract | null;
  enabled_tools?: string[];
  icon?: string;
}

export interface IntegrationSecretFieldContract {
  name: string;
  label: string;
  input_kind: "api_key" | "password" | "text" | "token" | "username";
  secret: boolean;
  required: boolean;
  min_length: number;
  max_length: number;
}

export interface IntegrationManualSecretContract {
  kind: "manual_secret";
  version: string;
  fields: IntegrationSecretFieldContract[];
}

export interface IntegrationCatalogueResponse {
  integrations: IntegrationCatalogueEntry[];
}

export interface IntegrationAccount {
  id: string;
  label: string;
  selected: boolean;
}

export interface IntegrationConnection {
  id: string;
  integration_id: string;
  label: string;
  health: IntegrationConnectionHealth;
  credential_ref_present: boolean;
  accounts: IntegrationAccount[];
  enabled_tools: string[];
  last_checked_at?: string | null;
  created_at: string;
}

export interface IntegrationConnectionsResponse {
  connections: IntegrationConnection[];
}

export interface IntegrationConnectionResponse {
  connection: IntegrationConnection;
}

export interface IntegrationSecretSubmission {
  fields: Record<string, string>;
  label?: string;
}

export interface IntegrationSetupResponse {
  status: "connected";
  connection: IntegrationConnection;
}

export interface IntegrationOAuthStartResponse {
  authorization_url: string;
  state_expires_at: string;
}

export type CallStatus =
  | "creating"
  | "joining"
  | "active"
  | "reconnecting"
  | "held"
  | "ended"
  | "realtime_unavailable"
  | "failed";

export interface CallParticipant {
  id: string;
  label: string;
  kind: "user" | "agent" | "guest";
  familiar_genotype?: FamiliarGenotype | null;
}

export interface RealtimeCall {
  id: string;
  conversation_id: string;
  run_id?: string | null;
  status: CallStatus;
  provider_class: "realtime_voice";
  participants: CallParticipant[];
  started_at?: string | null;
  ended_at?: string | null;
  created_at?: string;
  updated_at?: string;
  unavailable_reason?: string | null;
  agent_profile_id?: string | null;
  model_profile_id?: string | null;
}

export interface CallCreateRequest {
  conversation_id?: string;
  agent_profile_id?: string;
  model_profile_id?: string;
}

export interface CallCreateResponse {
  call: RealtimeCall;
  media_token?: string;
  media_token_expires_at?: string;
  websocket_url?: string;
  text_continuation_conversation_id?: string;
}

export interface CallTranscriptItem {
  id: string;
  participant_id: string;
  text: string;
  final: boolean;
  created_at: string;
}

export interface CallEvent {
  id: string;
  call_id: string;
  type:
    | "participant_joined"
    | "participant_left"
    | "transcript"
    | "tool_call"
    | "tool_result"
    | "hitl"
    | "usage"
    | "interrupted"
    | "reconnected"
    | "ended";
  payload: Record<string, unknown>;
  participant_id?: string | null;
  created_at: string;
}

export interface CallEventsResponse {
  events: CallEvent[];
}

export interface CallsResponse {
  calls: RealtimeCall[];
}

export interface CurrentCallResponse {
  call: RealtimeCall | null;
}

export interface CallUsage {
  input_audio_bytes: number;
  output_audio_bytes: number;
  tool_calls: number;
  provider_input_tokens: number;
  provider_output_tokens: number;
  estimated_cost_micros: number;
  pricing_revision: string | null;
  cost_status: "estimated" | "unpriced";
}

export interface CallUsageResponse {
  call_id: string;
  usage: CallUsage;
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

// GET /v1/workflow-stats (design brief 22.1): aggregated run stats per workflow,
// the real numbers that override the deterministic placeholders on the
// automations home cards. last_run_at is null when a workflow has no runs yet.
export interface WorkflowRunStat {
  workflow_id: string;
  run_count: number;
  success_count: number;
  last_run_at: string | null;
}

export interface WorkflowStatsResponse {
  stats: WorkflowRunStat[];
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

export type ChannelAddressingTargetKind =
  | "chief"
  | "department"
  | "workflow";

export type ChannelAddressingTargetState =
  | "available"
  | "startup_constructed_liveness_unknown"
  | "restart_required";

export interface ChannelAddressingTarget {
  id: string;
  kind: ChannelAddressingTargetKind;
  label: string;
  state: ChannelAddressingTargetState;
  runtime_liveness:
    | "unknown_not_probed_by_catalogue"
    | "not_applicable";
}

export interface ChannelAddressingCatalogue {
  targets: ChannelAddressingTarget[];
  supports_arbitrary_agent_pinning: false;
  scope: {
    workspace_id: string | null;
    departments: "all" | string[];
  };
}

export interface ChannelAddressingProjection {
  configured_default_target: string | null;
  effective_default_target: string;
  default_target_state:
    | ChannelAddressingTargetState
    | "stale_or_unsupported";
  routes: Array<{
    thread: string;
    target: string;
    state: ChannelAddressingTargetState | "stale_or_unsupported";
  }>;
  valid: boolean;
}

export interface ChannelAddressingConfig {
  default_target?: string;
  routes?: Record<string, string>;
  thread_field?: string;
}

export interface ChannelSelfOnboardConfig {
  role: "member";
  scope: {
    departments: string[];
  };
  welcome?: string;
}

export interface ChannelPolicyConfig extends Record<string, unknown> {
  addressing?: ChannelAddressingConfig;
  self_onboard?: ChannelSelfOnboardConfig;
}

export interface ChannelSummary {
  id: string;
  platform: string;
  name: string;
  transport: string;
  enabled: boolean;
  unpaired_behavior: string;
  config: ChannelPolicyConfig;
  addressing?: ChannelAddressingProjection;
  credential_configured: boolean;
  credentials_configured?: Record<string, boolean>;
  provider?: {
    id: string;
    label: string;
    transport: string;
    credential_keys: string[];
    provider_config_keys: string[];
    required_provider_config: string[];
    activation:
      | "automatic"
      | "external_pairing"
      | "deployment_managed"
      | "unsupported";
    shipped: boolean;
    capability: "shipped_adapter" | "unsupported";
  };
  gateway?: {
    status: string;
    gateway_id?: string;
    desired_revision?: string;
    observed_revision?: string;
    reason_code?: string | null;
    observed_at?: string | null;
    ownership?: {
      status:
        | "active_lease"
        | "expired_lease"
        | "unclaimed"
        | "not_applicable";
      gateway_id: string | null;
      lease_expires_at: string | null;
      single_owner_enforced: boolean;
      owner_lease_id_disclosed: false;
      proves_process_liveness: false;
    };
  };
}

// channels present on success; {status:"denied", reason} when not an author.
export interface ChannelsResponse {
  channels?: ChannelSummary[];
  addressing_catalogue?: ChannelAddressingCatalogue;
  status?: string;
  reason?: string;
}

export interface ChannelGatewaySessionRequest {
  channels: string[];
  gateway_id?: string;
  ttl_seconds?: number;
}

export interface ChannelGatewaySessionResponse {
  status: "ok" | "denied" | "error";
  token?: string;
  channels?: string[];
  gateway_id?: string;
  expires_in?: number;
  reason?: string;
  bootstrap?: {
    token_delivery: "show_once";
    recovery: "replace_token_file_or_restart";
    owner_election: "durable_per_channel_lease";
    provider_credentials_included: false;
  };
}

export interface ConnectChannelRequest {
  platform: string;
  name: string;
  // Legacy inline HMAC input; new clients should pass a secret-store reference.
  signing_secret?: string;
  signing_secret_ref?: string;
  // Canonical socket-provider credential references. Values are secret-store
  // names, never material; they are write-only and never returned by the API.
  credential_refs?: Record<string, string>;
  provider_config?: Record<string, unknown>;
  unpaired_behavior?: string;
  enabled?: boolean;
  config?: ChannelPolicyConfig;
}

export interface ConnectChannelResponse {
  status: string;
  channel?: string;
  inbound_url?: string;
  hitl_request_id?: string;
  reason?: string;
}

export interface ConfigureChannelRequest {
  name?: string;
  unpaired_behavior?: string;
  enabled?: boolean;
  config?: ChannelPolicyConfig;
  credential_refs?: Record<string, string>;
  provider_config?: Record<string, unknown>;
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

export type ChannelDeliveryStatus =
  | "queued"
  | "in_flight"
  | "retryable"
  | "delivered"
  | "terminal_failed";

export interface ChannelDeliveryReceipt {
  id: string;
  channel_id: string;
  status: ChannelDeliveryStatus;
  attempts: number;
  safe_reason: "delivery_failed" | null;
  created_at: string | null;
  updated_at: string | null;
  next_attempt_at: string | null;
}

export interface ChannelDeliveriesResponse {
  deliveries?: ChannelDeliveryReceipt[];
  status?: string;
  reason?: string;
}

export interface RetryChannelDeliveryResponse extends ChannelAck {
  delivery?: ChannelDeliveryReceipt;
  hitl_request_id?: string;
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
  hitl_request_id?: string;
  reason?: string;
}

export interface ChannelPairFinalization {
  request_id: string;
  state: "waiting" | "ready";
  external_user_id: string;
  subject: string;
  role: string;
  ttl_minutes: number;
}

export interface ChannelPairFinalizationsResponse {
  channel_id: string;
  finalizations: ChannelPairFinalization[];
}

export interface BindChannelRequest {
  external_user_id: string;
  subject: string;
  role: string;
}

export interface BindChannelResponse {
  status: string;
  binding?: string;
  hitl_request_id?: string;
  reason?: string;
}

// A minimal {status, reason} ack for channel mutations that return no body.
export interface ChannelAck {
  status: string;
  hitl_request_id?: string;
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
  scope_type: "tenant" | "department" | "workflow";
  window: "run" | "daily" | "monthly";
  hard_stop: boolean;
  token_limit: number | null;
  spent_tokens: number;
  cost_limit_micros: number | null;
  spent_micros: number;
  usage_state: "current" | "run_context_required";
  window_key: string | null;
  window_started_at: string | null;
  window_ends_at: string | null;
}

export interface BudgetPolicyRequest {
  scope_type: BudgetItem["scope_type"];
  scope_id: string;
  token_limit?: number;
  cost_limit_micros?: number;
  hard_stop: boolean;
  window: BudgetItem["window"];
}

export interface BudgetsResponse {
  budgets: BudgetItem[];
  scope: string[] | string;
}

export interface ConsolePlatformItem {
  id: string;
  kind: string;
  status: string;
  message?: string;
  updated_at?: string;
  metadata?: Record<string, unknown>;
}

export type BackgroundJobName = "hitl_expiry" | "retention";
export type BackgroundJobEvidenceState =
  | "recent_succeeded_evidence"
  | "recent_failed_evidence"
  | "stale_succeeded_evidence"
  | "stale_failed_evidence"
  | "future_evidence";

export interface BackgroundJobReceiptView {
  job_name: BackgroundJobName;
  process_instance_identity: string;
  state: BackgroundJobEvidenceState;
  last_outcome: "succeeded" | "failed";
  last_attempt_at: string;
  last_success_at: string | null;
  last_failure_at: string | null;
  failure_code: "sweep_failed" | null;
  last_item_count: number;
  interval_seconds: number;
  lag_seconds: number;
  stale_after_seconds: number;
  evidence_kind: "bounded_attempt_receipt_not_liveness";
  proves_liveness: false;
  process_coverage: "bounded_receipts_not_replica_inventory";
}

export interface BackgroundJobEvidenceSummary {
  status: "available" | "unavailable";
  evidence_kind: "bounded_attempt_receipt_not_liveness";
  proves_liveness: false;
  process_coverage: "bounded_receipts_not_replica_inventory";
  max_retained_process_receipts_per_job: number;
  max_returned_receipts: number;
}

export interface EffectiveNetworkPolicyField {
  enforcement: "enforced";
  enabled?: boolean;
  configured?: boolean;
  entry_count?: number;
}

export interface EffectiveWebFetchNetworkPolicy {
  surface: "web.fetch";
  status: "enforced";
  policy_snapshot: "adapter_process_start";
  fields: Record<string, EffectiveNetworkPolicyField>;
  controls: {
    ssrf_preflight: "enforced";
    redirects: "disabled";
    dns_pinning: "enforced" | "proxy_resolution_delegated";
  };
}

export interface NetworkPolicyCoverageItem {
  surface: string;
  status:
    | "separate_policy"
    | "partial_shared_controls"
    | "provider_transport_only";
  manifest_network_policy: "not_applied";
  controls: string[];
  limitation: string;
}

export interface EffectiveNetworkPolicyView {
  status: "available" | "unavailable";
  policy_source: "live_adapter_process_start_snapshot";
  changes_require_restart: true;
  universal_egress_control: false;
  sensitive_values_redacted: true;
  web_fetch: EffectiveWebFetchNetworkPolicy | null;
  coverage: NetworkPolicyCoverageItem[];
}

export interface CodexAdmissionView {
  status: "available";
  evidence_kind: "process_composition_not_runtime_liveness";
  rollout: {
    policy_source: "immutable_off_scaffold" | "scaffold_not_composed";
    mode: "off";
    generation: number | null;
    shadow_root_decisions: "active_execution_neutral" | "disabled";
    root_execution: "legacy_only";
    assignment_admission: "inactive_never_called";
    canary_decision: "unavailable_rollout_off";
  };
  runtime: {
    trusted_provider: "off" | "configured_development_only";
    runtime_config_production_ready: boolean;
    runtime_class_production_ready: boolean;
    production_activation:
      | "available"
      | "refused_unresolved_isolation_controls";
    preflight_evidence: "unavailable_no_durable_cell_receipts";
    cell_liveness: "unavailable";
  };
  execution_changed_by_projection: false;
  sensitive_values_redacted: true;
}

export interface PasswordResetDeliveryEvidence {
  configuration: "configured" | "unavailable";
  configuration_reason: "not_configured" | null;
  evidence_status:
    | "available"
    | "restricted"
    | "not_observed_in_bounded_tail";
  last_attempt_at: string | null;
  last_outcome:
    | "accepted_by_notifier"
    | "not_accepted_by_notifier"
    | "notifier_unavailable"
    | null;
  evidence_kind: "bounded_audit_attempt_not_provider_receipt";
  proves_recipient_delivery: false;
  target_disclosed: false;
  audit_tail_limit: number;
}

export interface LangfuseDeliveryView {
  status: "available" | "unavailable";
  evidence_kind: "process_local_attempt_counters_not_sink_health";
  process_coverage: "api_spawner_only_not_replica_inventory";
  sink_state: "enabled" | "disabled" | "unavailable";
  reason:
    | "configured"
    | "disabled_by_config"
    | "missing_keys"
    | "package_unavailable"
    | "client_initialization_failed"
    | "status_source_unavailable";
  attempt_count: number;
  success_count: number;
  failure_count: number;
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  delivery_lag: "unavailable";
  liveness_claimed: false;
  sensitive_values_redacted: true;
}

export type MemoryProjectionDeliveryState =
  | "queued_not_yet_attempted"
  | "retry_attempt_observed"
  | "delivered"
  | "delivered_after_retry"
  | "enqueue_failed_retry_unsafe"
  | "terminal_after_retry_cap"
  | "terminal_failure_attempt_count_unknown";

export type MemoryProjectionFailureCode =
  | "enqueue_failed"
  | "projection_operation_failed"
  | "projection_not_configured"
  | "invalid_projection_result";

export interface MemoryProjectionDeliveryReceipt {
  receipt_identity: string;
  projection_identity: string;
  operation: "remember" | "forget";
  state: MemoryProjectionDeliveryState;
  status: "pending" | "written" | "failed" | "deleted" | "delete_failed";
  enqueue_attempts: number;
  operation_attempts: number;
  max_operation_attempts: number;
  queued_at: string;
  first_attempt_at: string | null;
  last_attempt_at: string | null;
  last_failure_at: string | null;
  last_failure_code: MemoryProjectionFailureCode | null;
  queue_wait_seconds: number | null;
  pending_age_seconds: number | null;
  terminal_at: string | null;
  content_retained_in_receipt: false;
  manual_retry:
    | "unavailable_original_payload_not_retained"
    | "not_applicable";
}

export interface MemoryProjectionQueuePosture {
  status: "configured" | "no_projections" | "unavailable";
  execution_mode:
    | "inline_no_queue"
    | "durable_executor"
    | "local_inline_fallback"
    | "external_executor_durability_unknown"
    | "unknown";
  configured_projection_count: number;
  max_operation_attempts: number;
  retry_scope: "single_task_invocation" | "unknown";
  enqueue_retry: "disabled_ambiguous_acceptance" | "unknown";
  payload_retention:
    | "executor_owned_not_in_status_receipt"
    | "not_observed";
  manual_retry: "unavailable_original_payload_not_retained";
  proves_worker_liveness: false;
}

export interface MemoryProjectionDeliveryView {
  status: "available" | "unavailable";
  evidence_kind: "bounded_status_receipts_not_queue_or_worker_liveness";
  proves_queue_depth: false;
  proves_worker_liveness: false;
  queue_posture: MemoryProjectionQueuePosture;
  receipts: MemoryProjectionDeliveryReceipt[];
  max_returned_receipts: number;
  truncated: boolean;
  manual_retry: "unavailable_original_payload_not_retained";
}

export interface IdentityPolicyView {
  status: "available" | "unavailable";
  mode:
    | "first_party_session"
    | "cloudflare_access"
    | "oidc"
    | "development_header_trust"
    | "deny_all";
  oidc: {
    manifest_trio_configured: boolean;
    process_trio_configured: boolean;
    manifest_trio_state: "absent" | "partial" | "complete";
    process_trio_state: "absent" | "partial" | "complete";
    serving_state:
      | "active_manifest_and_process_match"
      | "active_manifest"
      | "active_process"
      | "inactive_selected_other_auth_mode"
      | "not_configured";
    drift_policy: "exact_match_or_boot_refused";
  };
  generation: string | null;
  changes_apply_at: "process_restart";
  sensitive_values_redacted: true;
}

export interface PlatformStatusResponse {
  generated_at: string;
  tenant_id: string;
  workspace_id?: string | null;
  components: ConsolePlatformItem[];
  runtimes: ConsolePlatformItem[];
  background_jobs?: BackgroundJobReceiptView[];
  background_job_evidence?: BackgroundJobEvidenceSummary;
  network_policy?: EffectiveNetworkPolicyView;
  codex_admission?: CodexAdmissionView;
  password_reset_delivery?: PasswordResetDeliveryEvidence;
  langfuse_delivery?: LangfuseDeliveryView;
  memory_projection_delivery?: MemoryProjectionDeliveryView;
  identity_policy?: IdentityPolicyView;
}

export type BirthProfileProcessKind = "api" | "fleet" | "hatchet";

export type BirthProfileEvidenceState =
  | "unavailable"
  | "startup_observed_reference_unavailable"
  | "stale_startup_liveness_unknown"
  | "mismatched_startup_liveness_unknown"
  | "matched_reference_liveness_unknown";

export interface BirthProfileReference {
  status:
    | "unavailable"
    | "startup_snapshot_liveness_unknown"
    | "stale_startup_liveness_unknown";
  source_process: "api";
  reason: "api_startup_receipt_unavailable" | null;
  basis: "latest_api_startup_receipt";
  instance_identity: string | null;
  manifest_generation: string | null;
  addon_set_identity: string | null;
  codex_provider_identity: string | null;
  codex_provider_state: "off" | "configured" | "unavailable";
  sensitive_role_identity: string | null;
  sensitive_role_state: "absent" | "configured" | "unavailable";
  observed_at: string | null;
  expires_at: string | null;
  liveness_claimed: false;
}

export interface BirthProfileObservation {
  process_kind: BirthProfileProcessKind;
  instance_identity: string | null;
  evidence_state: BirthProfileEvidenceState;
  reason: "no_startup_receipt" | null;
  matches_reference: boolean | null;
  mismatches: Array<
    | "manifest_generation"
    | "addon_set_identity"
    | "codex_provider_identity"
    | "sensitive_role_identity"
  >;
  manifest_generation: string | null;
  addon_set_identity: string | null;
  codex_provider_identity: string | null;
  codex_provider_state: "off" | "configured" | "unavailable";
  sensitive_role_identity: string | null;
  sensitive_role_state: "absent" | "configured" | "unavailable";
  receipt_kind: "startup_snapshot" | null;
  observed_at: string | null;
  expires_at: string | null;
  liveness_claimed: false;
}

export interface BirthProfileResponse {
  tenant_id: string;
  status:
    | "reference_unavailable"
    | "observed_mismatch"
    | "process_kind_unavailable"
    | "stale_startup_evidence"
    | "startup_profiles_match_reference_liveness_unknown";
  reference: BirthProfileReference;
  observations: BirthProfileObservation[];
  summary: {
    mismatch_count: number;
    stale_count: number;
    unavailable_count: number;
    retained_instance_count: number;
    max_retained_instances_per_process: number;
    max_returned_instances: number;
    liveness_claimed: false;
    replica_coverage_claimed: false;
  };
}

export interface ModelTelemetryResponse {
  generated_at: string;
  tenant_id: string;
  workspace_id?: string | null;
  scope: string[] | string;
  models: ConsoleModelTelemetry[];
}

export interface AuditVerifyResponse {
  tenant_id?: string;
  workspace_id?: string | null;
  chain_intact?: boolean;
  chain_first_bad_seq?: number | null;
  security_chain_intact?: boolean;
  security_first_bad_seq?: number | null;
  anchor_intact?: boolean;
  anchor?: AuditAnchorEvidence | null;
  intact?: boolean;
  status?: string;
  reason?: string;
}

export interface AuditAnchorEvidence {
  id: string;
  seq_start: number;
  seq_end: number;
  rollup_root_hash: string;
  anchored_at: string;
  is_dev_fallback: boolean;
  rfc3161_token?: string | null;
  kms_signature?: string | null;
}

export interface ConsoleModelTelemetry {
  provider: string;
  model: string;
  runtime: string;
  profile?: string;
  calls: number;
  tokens: number;
  cost_micros: number;
  avg_latency_ms?: number | null;
  last_seen: string;
  statuses: Record<string, number>;
}

export interface ConsoleRunEvent {
  seq: number;
  ts: string;
  run_id?: string | null;
  parent_run_id?: string | null;
  actor: string;
  verb: string;
  status: string;
  tokens_used: number;
  cost_micros: number;
  latency_ms?: number | null;
}

export interface ConsoleOverviewResponse {
  generated_at: string;
  tenant_id: string;
  workspace_id?: string | null;
  scope: string[] | string;
  platform: {
    components: ConsolePlatformItem[];
    runtimes: ConsolePlatformItem[];
  };
  models: ConsoleModelTelemetry[];
  cost: {
    total_cost_micros: number;
    by_actor: Record<string, number>;
    by_status: Record<string, number>;
  };
  budgets: BudgetItem[];
  recent_runs: ConsoleRunEvent[];
  approvals: HITLRequest[];
  counts: {
    visible_events: number;
    recent_runs: number;
    pending_approvals: number;
  };
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
  verb?: string;
  status?: string;
  run_id?: string | null;
  event_type?: string;
  reason?: string | null;
  workspace_id?: string | null;
  ip_address?: string | null;
  user_agent?: string | null;
  resource?: string | null;
  resource_id?: string | null;
}

export interface AuditSearchResponse {
  stream?: "audit" | "security";
  results: AuditRow[];
  scope: string[] | string;
  limit: number;
  offset: number;
  next_offset: number | null;
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
  // The intake lane this work arrived on. It SELECTS THE HANDLING DEPARTMENT
  // (chief_of_staff matches it against each department's queue_sources), which is
  // why no caller may set it and why it is not the channel a person typed into.
  source?: string | null;
  // WHICH SURFACE this run came from - "opbox" for a turn typed into an Opbox
  // spotlight, absent for one typed into boltrig itself. The kernel's generic
  // opaque external reference, so it is also the filter key:
  // GET /v1/runs?external_ref=opbox. A label: it reaches no authority decision.
  external_ref?: string | null;
}

export interface RunsResponse {
  runs: RunRow[];
  limit?: number;
  next_cursor?: string | null;
  filters?: {
    owner?: string | null;
    on_behalf_of?: string | null;
    label?: string | null;
    source?: string | null;
    external_ref?: string | null;
  };
}

export interface RunTopologyNode {
  run_id: string;
  work_item: string;
  parent_run_id?: string | null;
  member?: string | null;
  task: string;
  status: string;
  depth: number;
  source?: string | null;
  external_ref?: string | null;
  on_behalf_of?: string | null;
  attempts: number;
  degraded: boolean;
  cycle?: boolean;
  children: RunTopologyNode[];
}

export interface RunTopologyResponse {
  root: RunTopologyNode;
}

// --- Evaluation -------------------------------------------------------------

export type EvalTargetKind = "skill" | "workflow";

export interface EvalCaseItem {
  id: string;
  target_kind: EvalTargetKind;
  target_ref: string;
  input: Record<string, unknown>;
  assertions: Record<string, unknown>;
  labels: string[];
  is_active: boolean;
  status: "active" | "archived";
}

export interface EvalCasesResponse {
  cases: EvalCaseItem[];
}

export interface CreateEvalCaseRequest {
  id?: string;
  target_kind: EvalTargetKind;
  target_ref: string;
  input?: Record<string, unknown>;
  assertions?: Record<string, unknown>;
  labels?: string[];
}

export interface EvalCaseLifecycleResponse {
  status: "ok" | "pending_human" | "error";
  id?: string;
  eval_case_status?: "active" | "archived";
  hitl_request_id?: string;
  reason?: string;
}

export interface RunEvalRequest {
  case_id: string;
}

export interface EvalRunDetail {
  checks?: Record<string, boolean>;
  effective_grants?: string[];
  target?: { kind: string; ref: string };
  target_error?: string;
  workflow_status?: string;
  [key: string]: unknown;
}

export interface EvalRunResult {
  id?: string;
  passed?: boolean;
  score?: number;
  run_id?: string;
  target_kind?: EvalTargetKind;
  target_ref?: string;
  detail?: EvalRunDetail;
  error?: string;
}

export interface EvalRunSummary {
  id: string;
  case_id: string;
  passed: boolean;
  score: number;
  run_id?: string;
  target_kind?: EvalTargetKind;
  target_ref?: string;
  detail?: EvalRunDetail;
  created_at?: string;
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
  setting_sources?: Record<string, "tenant_default" | "user_override">;
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
  limit: number;
  offset: number;
  next_offset: number | null;
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
  conversation_status?: "active" | "closed";
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
  deliverable: boolean;
  last_delivery?: NotificationDeliveryStatus | null;
}

export interface NotificationEventOption {
  id: string;
  label: string;
  description: string;
}

export interface NotificationTargetOption {
  id: string;
  label: string;
}

export interface NotificationTransportOption {
  id: string;
  platform: string;
  label: string;
  delivery_mode: "durable_outbox";
  targets: NotificationTargetOption[];
}

export interface NotificationDeliveryStatus {
  id: string;
  status: "pending" | "in_flight" | "delivered" | "failed";
  updated_at?: string | null;
}

export interface NotificationCatalogue {
  events: NotificationEventOption[];
  transports: NotificationTransportOption[];
}

export interface MeNotificationsResponse {
  prefs: MeNotificationItem[];
  catalogue: NotificationCatalogue;
}

export interface PutMeNotificationRequest {
  id?: string;
  event_type: string;
  channel: string;
  target?: string | null;
  enabled?: boolean;
}

export interface TestMeNotificationResponse {
  status: string;
  delivery_id?: string;
  delivery_status?: "queued";
  reason?: string;
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
  workspace_id?: string | null;
  provision_workspace_name?: string | null;
  provision_org_name?: string | null;
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
  workspace_id?: string;
  provision_workspace_name?: string;
  provision_org_name?: string;
}

export interface CreateInvitationResponse {
  status: string;
  id?: string;
  email?: string;
  invite_token?: string;
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

export interface MemoryFactResponse {
  fact: MemoryFactView;
}

export interface MemoryRecallRequest {
  query: string;
  mode?: RecallMode;
  limit?: number;
  owner_scope?: string;
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
  hitl_request_id?: string;
  fact_ids?: string[];
  owner_scope?: string;
  reason?: string;
}

export interface MemoryImproveRequest {
  target: string;
  signal: "up" | "down";
}

export interface MemoryImproveResponse {
  status: string;
  hitl_request_id?: string;
  adjusted?: number;
  reason?: string;
}

export interface MemoryForgetRequest {
  target?: string;
  source_ref?: string;
}

export interface MemoryForgetResponse {
  status: string;
  hitl_request_id?: string;
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
  hitl_request_id?: string;
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

// --- Codex-native Knowledge fabric (decision 0015) -------------------------
export interface KnowledgeAsset {
  id: string;
  title: string;
  filename: string;
  asset_type: string;
  workspace_id?: string | null;
  revision_id: string;
  source_kind: string;
  source_ref?: string | null;
  segment_count: number;
  created_at: string;
}

export interface KnowledgeAssetsResponse {
  assets: KnowledgeAsset[];
  next_offset?: number | null;
}

export interface KnowledgeAssetDetailResponse {
  asset: Omit<KnowledgeAsset, "segment_count" | "workspace_id">;
  segments: Array<Record<string, unknown>>;
  provenance: Record<string, unknown>;
  projections: Array<Record<string, unknown>>;
}

export interface KnowledgeCitation {
  asset_id: string;
  revision_id: string;
  segment_id: string;
  title: string;
  filename: string;
  locator: Record<string, unknown>;
  source_kind: string;
  source_ref?: string | null;
  content_hash: string;
}

export interface KnowledgeSearchHit {
  asset_id: string;
  revision_id: string;
  segment_id: string;
  title: string;
  filename: string;
  text: string;
  locator: Record<string, unknown>;
  score: number;
  citation: KnowledgeCitation;
}

export interface KnowledgeSearchResponse {
  query: string;
  hits: KnowledgeSearchHit[];
}

export interface KnowledgeProvider {
  id: string;
  display_name: string;
  role: string;
  enabled: boolean;
  bundled: boolean;
  health: string;
  status: string;
  last_error?: string | null;
}

export interface KnowledgeProvidersResponse {
  providers: KnowledgeProvider[];
}

export interface KnowledgeUploadResponse {
  asset_id: string;
  revision_id: string;
  status: string;
  segment_count: number;
  digest: string;
  projections: Array<{ provider_id: string; status: string; error?: string | null }>;
}

export interface KnowledgeMutationResponse {
  asset_id?: string;
  status?: string;
  operation_status?: string;
  provider?: KnowledgeProvider;
  hitl_request_id?: string;
  reason?: string;
}

// === First-party auth + org/workspace tenancy (COUNTY 7 / 8) ===
// The session login surface (boltrig/api/auth_routes.py) and the org/workspace
// management surface (boltrig/kernel/access_routes.py). Every write below is a
// mutating cookie request, so the client echoes the readable boltrig_csrf cookie
// in the x-boltrig-csrf header (double-submit, see api/client.ts).

// The authenticated user summary the login route returns (never a secret).
export interface AuthUser {
  id: string;
  email: string;
  role: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface PasswordResetRequest {
  email: string;
}

export interface PasswordResetRequestResponse {
  status: string;
  message?: string;
  reason?: string;
}

export interface PasswordResetConfirmRequest {
  token: string;
  new_password: string;
}

export interface PasswordResetConfirmResponse {
  status: string;
  reason?: string;
}

// The login body is {status:"ok", csrf_token, user} on success, or a GENERIC
// {status:"error", reason} on 401 (never enumerates emails) / 429 (throttled).
// When two-factor is due ([2026] VJS-COUNTY 10) the status is instead
// "2fa_required" (a challenge_token is returned and NO session is issued) or
// "2fa_enrollment_required" (an org requires 2FA and the enrollment-only session
// cookie is set - only the enroll surface is reachable).
export interface LoginResponse {
  status: string;
  csrf_token?: string;
  user?: AuthUser;
  reason?: string;
  challenge_token?: string;
}

// The follow-up second-factor verification that issues the session withheld by
// login ([2026] VJS-COUNTY 10, D3). The code is a 6-digit TOTP or a recovery code.
export interface TwoFactorChallengeRequest {
  challenge_token: string;
  code: string;
}
export interface TwoFactorChallengeResponse {
  status: string;
  csrf_token?: string;
  user?: AuthUser;
  reason?: string;
}

// Enroll-begin returns the otpauth URI + secret (for the QR) and the one-time
// recovery codes EXACTLY ONCE; verify-enroll confirms a code to activate.
export interface TwoFactorEnrollBeginResponse {
  status: string;
  otpauth_uri?: string;
  secret?: string;
  recovery_codes?: string[];
  reason?: string;
}
export interface TwoFactorVerifyEnrollRequest {
  code: string;
}
export interface TwoFactorVerifyEnrollResponse {
  status: string;
  recovery_codes_remaining?: number;
  reason?: string;
}
export interface TwoFactorDisableRequest {
  code: string;
}

export interface AcceptInviteRequest {
  token: string;
  password: string;
}

// Success is {status:"ok", email}; a bad/expired token or a weak password is a
// faithful {status:"error", reason} 400.
export interface AcceptInviteResponse {
  status: string;
  email?: string;
  reason?: string;
}

// The session's active workspace switch (re-authorized server-side each call).
export interface SwitchContextResponse {
  status: string;
  workspace_id?: string;
  reason?: string;
}

export interface WorkspaceView {
  id: string;
  name: string;
  slug: string;
  status: string;
  settings: Record<string, unknown>;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface WorkspacesResponse {
  workspaces: WorkspaceView[];
}

export interface CreateWorkspaceRequest {
  name: string;
  settings?: Record<string, unknown>;
}

export interface WorkspaceMutationResponse {
  status: string;
  workspace?: WorkspaceView;
  reason?: string;
}

export interface UpdateWorkspaceRequest {
  name?: string;
  settings?: Record<string, unknown>;
  status?: "active" | "archived";
}

export interface WorkspaceMemberView {
  user_id: string;
  workspace_id: string;
  role: string;
  permissions: Record<string, unknown>;
  created_at?: string | null;
}

// The roster read is {members:[...]}; a non-member/non-admin caller is refused
// with {status:"denied"/"error", reason} (403/404), no members key.
export interface WorkspaceMembersResponse {
  members?: WorkspaceMemberView[];
  status?: string;
  reason?: string;
}

export interface AddWorkspaceMemberRequest {
  user_id: string;
  role: string;
  permissions?: Record<string, unknown>;
}

export interface AddWorkspaceMemberResponse {
  status: string;
  member?: WorkspaceMemberView;
  reason?: string;
}

export interface OrganisationView {
  id: string;
  name: string;
  slug: string;
  settings: Record<string, unknown>;
  allow_own_ai_keys: boolean;
  require_two_factor: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface CurrentOrgResponse {
  organisation: OrganisationView;
}

export interface MyOrganisationView {
  id: string;
  active: boolean;
}

export interface MyOrganisationsResponse {
  organisations: MyOrganisationView[];
}

export interface UpdateOrgRequest {
  name?: string;
  slug?: string;
  settings?: Record<string, unknown>;
  allow_own_ai_keys?: boolean;
  require_two_factor?: boolean;
}

// The PATCH echoes the updated org on success; a non-admin is refused
// {status:"denied", reason} (403) via the central error envelope.
export interface UpdateOrgResponse {
  status?: string;
  organisation?: OrganisationView;
  reason?: string;
}

export interface OrgMemberView {
  user_id: string;
  role: string;
  created_at?: string | null;
}

export interface OrgMembersResponse {
  members: OrgMemberView[];
}

export type AiKeyLevel = "org" | "workspace" | "user";

// An AI-config row for listing: provider/model + WHETHER a key is set, NEVER the
// key itself (the secret lives only in the sealed credential store).
export interface AiKeyView {
  level: AiKeyLevel;
  scope_id: string;
  provider: string;
  model: string;
  base_url?: string | null;
  has_key: boolean;
  updated_at?: string | null;
}

export interface AiKeysResponse {
  allow_own_ai_keys: boolean;
  ai_keys: AiKeyView[];
}

// The api_key is accepted ONCE and sealed server-side; it is never echoed back.
export interface SetAiKeyRequest {
  level: AiKeyLevel;
  scope_id?: string;
  provider: string;
  model: string;
  base_url?: string;
  api_key: string;
}

export type AiKeyProposalStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "expired"
  | "consumed"
  | "invalidated"
  | "unavailable";

export interface AiKeyProposalView {
  id: string;
  level: AiKeyLevel;
  scope_id: string;
  provider: string;
  model: string;
  base_url?: string | null;
  status: AiKeyProposalStatus;
  created_at: string;
  expires_at: string;
}

export interface SetAiKeyResponse {
  status: string;
  proposal?: AiKeyProposalView;
  proposal_id?: string;
  level?: string;
  scope_id?: string;
  provider?: string;
  model?: string;
  reason?: string;
}

export interface AiKeyProposalsResponse {
  proposals: AiKeyProposalView[];
}

export interface AiKeyProposalResponse {
  status: AiKeyProposalStatus | "ok" | "error";
  proposal?: AiKeyProposalView;
  proposal_id?: string;
  level?: string;
  scope_id?: string;
  provider?: string;
  model?: string;
  base_url?: string | null;
  reason?: string;
}

export interface DeleteAiKeyResponse {
  status: string;
  hitl_request_id?: string;
  level?: string;
  scope_id?: string;
  reason?: string;
}
