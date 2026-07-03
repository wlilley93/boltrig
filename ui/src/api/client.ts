// Typed fetch client over the kernel HTTP surface. Every request carries the
// dev identity headers (x-boltrig-*) read from the identity store. Paths are
// relative: the Vite dev server and the nginx prod image both proxy /v1 and
// /healthz to the kernel.

import { getIdentity } from "../identity";
import type {
  ActivateAdapterRequest,
  ActivateAdapterResponse,
  AdapterInventoryResponse,
  AnswerQuestionResponse,
  AdapterSourceResponse,
  AdminInvitationsResponse,
  AdminUsersResponse,
  AuditExportResponse,
  AuditSearchResponse,
  AuditTreeResponse,
  BindChannelRequest,
  BindChannelResponse,
  CancelRunResponse,
  CapabilitiesResponse,
  CapabilityChangelogResponse,
  ChannelAck,
  ChannelBindingsResponse,
  ChannelsResponse,
  ChatEvent,
  ChatRequest,
  ConfigureChannelRequest,
  ConnectChannelRequest,
  ConnectChannelResponse,
  ConfigExportResponse,
  ConfigHistoryResponse,
  ConfigRollbackRequest,
  ConfigRollbackResponse,
  ConfigSectionResponse,
  ConfigurePersonalAgentRequest,
  ConfigurePersonalAgentResponse,
  ConnectionsResponse,
  ConversationResponse,
  ConversationsResponse,
  ConversationsPageResponse,
  ConversationSearchResponse,
  BudgetsResponse,
  CostResponse,
  CreateEvalCaseRequest,
  CreateInvitationRequest,
  CreateInvitationResponse,
  CredentialsResponse,
  DeleteAck,
  EvalRunResult,
  EvalRunsResponse,
  GenerateAdapterRequest,
  GenerateAdapterResponse,
  HealthResponse,
  HITLListResponse,
  InvokePersonalAgentRequest,
  InvokeRequest,
  InvokeResult,
  MeActivityResponse,
  MeAgentResponse,
  MeExportResponse,
  MeNotificationsResponse,
  MeSettingsResponse,
  MemoryFactsResponse,
  MemoryForgetRequest,
  MemoryForgetResponse,
  MemoryIngestRequest,
  MemoryIngestResponse,
  MemoryIngestionsResponse,
  MemoryQueryRequest,
  MemoryQueryResponse,
  MemoryRecallRequest,
  MemoryRecallResponse,
  MemoryRememberRequest,
  MemoryRememberResponse,
  MintTokenRequest,
  MintTokenResponse,
  PairChannelRequest,
  PairChannelResponse,
  PatchUserRequest,
  PatchUserResponse,
  PutConfigRequest,
  PutConfigResponse,
  PutMeNotificationRequest,
  PutSettingsRequest,
  PutSettingsResponse,
  RegenerateResponse,
  RegisterMcpRequest,
  RenameConversationRequest,
  RespondResult,
  RunEvalRequest,
  RunsResponse,
  ScheduleWorkflowRequest,
  ScheduleWorkflowResponse,
  SessionsResponse,
  SetBindingRequest,
  SkillsResponse,
  SpawnRequest,
  SpawnResult,
  StatusAck,
  TestSpawnRequest,
  TokensResponse,
  TriggerWorkflowRequest,
  UpsertNounRequest,
  UpsertSkillRequest,
  UpsertVerbRequest,
  UpsertWorkflowRequest,
  WorkResponse,
  WorkStatus,
  WorkflowDetail,
  WorkflowRunDescriptor,
  WorkflowRunRecord,
  WorkflowRunsResponse,
  WorkflowsResponse,
  AcceptInviteRequest,
  AcceptInviteResponse,
  AddWorkspaceMemberRequest,
  AddWorkspaceMemberResponse,
  AiKeysResponse,
  CreateWorkspaceRequest,
  CurrentOrgResponse,
  DeleteAiKeyResponse,
  LoginRequest,
  LoginResponse,
  OrgMembersResponse,
  SetAiKeyRequest,
  SetAiKeyResponse,
  SwitchContextResponse,
  UpdateOrgRequest,
  UpdateOrgResponse,
  UpdateWorkspaceRequest,
  WorkspaceMembersResponse,
  WorkspaceMutationResponse,
  WorkspacesResponse,
} from "./types";

// Optional base prefix (e.g. when the UI is mounted under a sub-path).
const BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

function identityHeaders(): Record<string, string> {
  const id = getIdentity();
  return {
    "x-boltrig-tenant": id.tenant,
    "x-boltrig-subject": id.subject,
    "x-boltrig-grants": id.grants,
    "x-boltrig-role": id.role,
    "x-boltrig-departments": id.departments ?? "",
  };
}

// The mutating HTTP methods that a first-party session gates with CSRF. The
// session cookie (boltrig_session) is httpOnly, so a browser attaches it
// automatically; the double-submit defence is to ALSO echo the readable
// boltrig_csrf cookie in the x-boltrig-csrf header (a value a cross-site form
// cannot set). Safe reads never need it. See boltrig/identity/sessions.py.
const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const CSRF_COOKIE = "boltrig_csrf";
const CSRF_HEADER = "x-boltrig-csrf";

// Read the readable CSRF cookie the login route set. Absent under the dev
// header-auth resolver (no session cookie), so the header is simply omitted -
// dev/e2e requests are unaffected; only a real session carries the cookie.
function readCsrfCookie(): string | null {
  if (typeof document === "undefined" || !document.cookie) return null;
  for (const part of document.cookie.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name === CSRF_COOKIE) return decodeURIComponent(rest.join("="));
  }
  return null;
}

// The x-boltrig-csrf header for a mutating request, or {} when there is no CSRF
// cookie (header-auth dev / logged-out). Never throws.
function csrfHeaders(method: string): Record<string, string> {
  if (!MUTATING_METHODS.has(method.toUpperCase())) return {};
  const token = readCsrfCookie();
  return token ? { [CSRF_HEADER]: token } : {};
}

async function parseBody(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  // when true, a non-2xx response is returned (parsed) instead of throwing
  tolerateStatus?: boolean;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, tolerateStatus = false } = opts;
  const headers: Record<string, string> = {
    ...identityHeaders(),
    ...csrfHeaders(method),
  };
  if (body !== undefined) headers["content-type"] = "application/json";

  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (err) {
    const reason = err instanceof Error ? err.message : "network error";
    throw new ApiError(0, `request failed: ${reason}`, null);
  }

  const parsed = await parseBody(res);
  if (!res.ok && !tolerateStatus) {
    throw new ApiError(res.status, `${method} ${path} -> ${res.status}`, parsed);
  }
  return parsed as T;
}

export const api = {
  health(): Promise<HealthResponse> {
    return request<HealthResponse>("/healthz");
  },

  capabilities(noun?: string): Promise<CapabilitiesResponse> {
    const q = noun ? `?noun=${encodeURIComponent(noun)}` : "";
    return request<CapabilitiesResponse>(`/v1/capabilities${q}`);
  },

  capabilityChangelog(): Promise<CapabilityChangelogResponse> {
    return request<CapabilityChangelogResponse>("/v1/capabilities/changelog");
  },

  // invoke returns one of several bodies keyed by status; never throws on a
  // documented non-2xx (202/403/503), only on transport/unexpected failures.
  invoke(req: InvokeRequest): Promise<InvokeResult> {
    return request<InvokeResult>("/v1/invoke", {
      method: "POST",
      body: req,
      tolerateStatus: true,
    });
  },

  spawn(req: SpawnRequest): Promise<unknown> {
    return request<unknown>("/v1/spawn", {
      method: "POST",
      body: req,
      tolerateStatus: true,
    });
  },

  work(status?: WorkStatus): Promise<WorkResponse> {
    const q = status ? `?status=${encodeURIComponent(status)}` : "";
    return request<WorkResponse>(`/v1/work${q}`);
  },

  hitl(): Promise<HITLListResponse> {
    return request<HITLListResponse>("/v1/hitl");
  },

  respondHitl(
    id: string,
    body: { decision: string; notes?: string },
  ): Promise<RespondResult> {
    return request<RespondResult>(`/v1/hitl/${encodeURIComponent(id)}/respond`, {
      method: "POST",
      body: { decision: body.decision, notes: body.notes ?? "" },
    });
  },

  // Answer an agent's clarifying QUESTION (US-CHAT-12). Owner-only and
  // fail-closed server-side; tolerateStatus so a 400 (empty answer), 403 (not
  // your run), 404 (unknown) or 409 (not a question) renders as a notice in the
  // card instead of throwing. On success the backend requeues the paused run so
  // the stream resumes on its own.
  answerQuestion(
    questionId: string,
    answer: string,
  ): Promise<AnswerQuestionResponse> {
    return request<AnswerQuestionResponse>(
      `/v1/hitl/${encodeURIComponent(questionId)}/answer`,
      { method: "POST", body: { answer }, tolerateStatus: true },
    );
  },

  auditTree(runId: string): Promise<AuditTreeResponse> {
    return request<AuditTreeResponse>(
      `/v1/audit/tree/${encodeURIComponent(runId)}`,
    );
  },

  // Conversation list + transcript for the Chat panel. The transcript persists
  // server-side, so re-opening a conversation always shows the completed turn.
  conversations(): Promise<ConversationsResponse> {
    return request<ConversationsResponse>("/v1/conversations");
  },

  // One bounded page of the owner-scoped conversation list (US-CONV-09). Passing
  // a limit + offset opts into pagination: the response carries next_offset (the
  // offset for the next page, or null when the list is exhausted). The bare
  // conversations() above stays the unpaginated legacy call.
  listConversations(
    limit: number,
    offset: number,
  ): Promise<ConversationsPageResponse> {
    const q = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    });
    return request<ConversationsPageResponse>(`/v1/conversations?${q}`);
  },

  // Owner-scoped conversation search (US-CONV-10), paginated the same way. The
  // caller must pass a non-empty term (an empty q is a 400 server-side); the UI
  // never sends one. Each result carries an optional snippet of the matched
  // message body.
  searchConversations(
    q: string,
    limit: number,
    offset: number,
  ): Promise<ConversationSearchResponse> {
    const params = new URLSearchParams({
      q,
      limit: String(limit),
      offset: String(offset),
    });
    return request<ConversationSearchResponse>(
      `/v1/conversations/search?${params}`,
    );
  },

  conversation(id: string): Promise<ConversationResponse> {
    return request<ConversationResponse>(
      `/v1/conversations/${encodeURIComponent(id)}`,
    );
  },

  // Regenerate the LAST assistant reply (owner-only, append-plus-supersede).
  // tolerateStatus so a 403 (not owner) or 409 (not the last assistant message)
  // renders as a message instead of throwing.
  regenerateMessage(
    conversationId: string,
    messageId: string,
  ): Promise<RegenerateResponse> {
    return request<RegenerateResponse>(
      `/v1/me/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/regenerate`,
      { method: "POST", tolerateStatus: true },
    );
  },

  // Cancel a live run (owner-only, cooperative). The run's SSE stream then emits
  // a terminal `cancelled` event and closes. tolerateStatus so a 403/404 renders
  // as a message; the caller falls back to a local abort when it is not "ok".
  cancelRun(runId: string): Promise<CancelRunResponse> {
    return request<CancelRunResponse>(
      `/v1/runs/${encodeURIComponent(runId)}/cancel`,
      { method: "POST", tolerateStatus: true },
    );
  },

  // === Round Three: authoring studios ===
  // Writes carry tolerateStatus so a 403 (role lacks authoring) renders as a
  // denial message instead of throwing.

  skills(): Promise<SkillsResponse> {
    return request<SkillsResponse>("/v1/skills");
  },

  upsertSkill(body: UpsertSkillRequest): Promise<StatusAck> {
    return request<StatusAck>("/v1/skills", {
      method: "POST",
      body,
      tolerateStatus: true,
    });
  },

  // Spawns the skill under the AUTHOR's grants (ceiling); the returned
  // effective_grants prove the child never escalates (SEC-29).
  testSpawn(skillId: string, body: TestSpawnRequest): Promise<SpawnResult> {
    return request<SpawnResult>(
      `/v1/skills/${encodeURIComponent(skillId)}/test-spawn`,
      { method: "POST", body, tolerateStatus: true },
    );
  },

  upsertNoun(body: UpsertNounRequest): Promise<StatusAck> {
    return request<StatusAck>("/v1/nouns", {
      method: "POST",
      body,
      tolerateStatus: true,
    });
  },

  upsertVerb(body: UpsertVerbRequest): Promise<StatusAck> {
    return request<StatusAck>("/v1/verbs", {
      method: "POST",
      body,
      tolerateStatus: true,
    });
  },

  setBinding(verbId: string, body: SetBindingRequest): Promise<StatusAck> {
    return request<StatusAck>(
      `/v1/verbs/${encodeURIComponent(verbId)}/binding`,
      { method: "POST", body, tolerateStatus: true },
    );
  },

  generateAdapter(
    body: GenerateAdapterRequest,
  ): Promise<GenerateAdapterResponse> {
    return request<GenerateAdapterResponse>("/v1/adapters/generate", {
      method: "POST",
      body,
      tolerateStatus: true,
    });
  },

  adapterSource(adapterId: string): Promise<AdapterSourceResponse> {
    return request<AdapterSourceResponse>(
      `/v1/adapters/${encodeURIComponent(adapterId)}/source`,
      { tolerateStatus: true },
    );
  },

  activateAdapter(
    adapterId: string,
    body: ActivateAdapterRequest,
  ): Promise<ActivateAdapterResponse> {
    return request<ActivateAdapterResponse>(
      `/v1/adapters/${encodeURIComponent(adapterId)}/activate`,
      { method: "POST", body, tolerateStatus: true },
    );
  },

  registerMcpServer(body: RegisterMcpRequest): Promise<StatusAck> {
    return request<StatusAck>("/v1/mcp/servers", {
      method: "POST",
      body,
      tolerateStatus: true,
    });
  },

  adapters(): Promise<AdapterInventoryResponse> {
    return request<AdapterInventoryResponse>("/v1/adapters");
  },

  workflows(): Promise<WorkflowsResponse> {
    return request<WorkflowsResponse>("/v1/workflows");
  },

  getWorkflow(wfId: string): Promise<WorkflowDetail> {
    return request<WorkflowDetail>(`/v1/workflows/${encodeURIComponent(wfId)}`);
  },

  upsertWorkflow(body: UpsertWorkflowRequest): Promise<StatusAck> {
    return request<StatusAck>("/v1/workflows", {
      method: "POST",
      body,
      tolerateStatus: true,
    });
  },

  scheduleWorkflow(
    wfId: string,
    body: ScheduleWorkflowRequest,
  ): Promise<ScheduleWorkflowResponse> {
    return request<ScheduleWorkflowResponse>(
      `/v1/workflows/${encodeURIComponent(wfId)}/schedule`,
      { method: "POST", body, tolerateStatus: true },
    );
  },

  triggerWorkflow(
    wfId: string,
    body: TriggerWorkflowRequest,
  ): Promise<WorkflowRunDescriptor> {
    return request<WorkflowRunDescriptor>(
      `/v1/workflows/${encodeURIComponent(wfId)}/trigger`,
      { method: "POST", body, tolerateStatus: true },
    );
  },

  // execute RUNS the stored workflow's steps through the chokepoint and returns
  // the resulting run record (overall status + per-step results); distinct from
  // trigger, which only queues a descriptor.
  executeWorkflow(
    wfId: string,
    inputs: Record<string, unknown>,
  ): Promise<WorkflowRunRecord> {
    return request<WorkflowRunRecord>(
      `/v1/workflows/${encodeURIComponent(wfId)}/execute`,
      { method: "POST", body: { inputs } },
    );
  },

  workflowRuns(wfId: string): Promise<WorkflowRunsResponse> {
    return request<WorkflowRunsResponse>(
      `/v1/workflows/${encodeURIComponent(wfId)}/runs`,
    );
  },

  // === Round Three: admin console (org-admin / author roles) ===

  getConfig(section: string): Promise<ConfigSectionResponse> {
    return request<ConfigSectionResponse>(
      `/v1/admin/config/${encodeURIComponent(section)}`,
      { tolerateStatus: true },
    );
  },

  putConfig(
    section: string,
    body: PutConfigRequest,
  ): Promise<PutConfigResponse> {
    return request<PutConfigResponse>(
      `/v1/admin/config/${encodeURIComponent(section)}`,
      { method: "PUT", body, tolerateStatus: true },
    );
  },

  configHistory(section: string): Promise<ConfigHistoryResponse> {
    return request<ConfigHistoryResponse>(
      `/v1/admin/config/${encodeURIComponent(section)}/history`,
      { tolerateStatus: true },
    );
  },

  configRollback(
    section: string,
    body: ConfigRollbackRequest,
  ): Promise<ConfigRollbackResponse> {
    return request<ConfigRollbackResponse>(
      `/v1/admin/config/${encodeURIComponent(section)}/rollback`,
      { method: "POST", body, tolerateStatus: true },
    );
  },

  configExport(): Promise<ConfigExportResponse> {
    return request<ConfigExportResponse>("/v1/admin/config/export", {
      method: "POST",
      tolerateStatus: true,
    });
  },

  adminCredentials(): Promise<CredentialsResponse> {
    return request<CredentialsResponse>("/v1/admin/credentials", {
      tolerateStatus: true,
    });
  },

  // === Channels (decision 0003, admin-gated) ===
  // Every call carries tolerateStatus so a 403 (not an author), 400 (bad input)
  // or 404 (unknown channel) renders as a message instead of throwing. The
  // connect body's signing_secret and the pair response's code are the only
  // secret material and are handled show-once by the caller.

  channels(): Promise<ChannelsResponse> {
    return request<ChannelsResponse>("/v1/channels", { tolerateStatus: true });
  },

  connectChannel(body: ConnectChannelRequest): Promise<ConnectChannelResponse> {
    return request<ConnectChannelResponse>("/v1/channels", {
      method: "POST",
      body,
      tolerateStatus: true,
    });
  },

  configureChannel(
    id: string,
    body: ConfigureChannelRequest,
  ): Promise<ChannelAck> {
    return request<ChannelAck>(`/v1/channels/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body,
      tolerateStatus: true,
    });
  },

  disconnectChannel(id: string): Promise<ChannelAck> {
    return request<ChannelAck>(`/v1/channels/${encodeURIComponent(id)}`, {
      method: "DELETE",
      tolerateStatus: true,
    });
  },

  channelBindings(id: string): Promise<ChannelBindingsResponse> {
    return request<ChannelBindingsResponse>(
      `/v1/channels/${encodeURIComponent(id)}/bindings`,
      { tolerateStatus: true },
    );
  },

  // The minted pairing code is in the response ONCE and is never returned again.
  pairChannel(
    id: string,
    body: PairChannelRequest,
  ): Promise<PairChannelResponse> {
    return request<PairChannelResponse>(
      `/v1/channels/${encodeURIComponent(id)}/pair`,
      { method: "POST", body, tolerateStatus: true },
    );
  },

  bindChannel(
    id: string,
    body: BindChannelRequest,
  ): Promise<BindChannelResponse> {
    return request<BindChannelResponse>(
      `/v1/channels/${encodeURIComponent(id)}/bindings`,
      { method: "POST", body, tolerateStatus: true },
    );
  },

  deleteChannelBinding(id: string, bindingId: string): Promise<ChannelAck> {
    return request<ChannelAck>(
      `/v1/channels/${encodeURIComponent(id)}/bindings/${encodeURIComponent(bindingId)}`,
      { method: "DELETE", tolerateStatus: true },
    );
  },

  // === Round Three: insight (scope-filtered server-side, SEC-33) ===

  cost(): Promise<CostResponse> {
    return request<CostResponse>("/v1/cost");
  },

  budgets(): Promise<BudgetsResponse> {
    return request<BudgetsResponse>("/v1/budgets");
  },

  auditSearch(
    params: { actor?: string; verb?: string; run?: string } = {},
  ): Promise<AuditSearchResponse> {
    const q = new URLSearchParams();
    if (params.actor) q.set("actor", params.actor);
    if (params.verb) q.set("verb", params.verb);
    if (params.run) q.set("run", params.run);
    const qs = q.toString();
    return request<AuditSearchResponse>(
      `/v1/audit/search${qs ? `?${qs}` : ""}`,
    );
  },

  auditExport(): Promise<AuditExportResponse> {
    return request<AuditExportResponse>("/v1/audit/export", {
      method: "POST",
      tolerateStatus: true,
    });
  },

  runs(): Promise<RunsResponse> {
    return request<RunsResponse>("/v1/runs");
  },

  // === Round Three: evaluation ===

  createEvalCase(body: CreateEvalCaseRequest): Promise<StatusAck> {
    return request<StatusAck>("/v1/eval/cases", {
      method: "POST",
      body,
      tolerateStatus: true,
    });
  },

  runEval(body: RunEvalRequest): Promise<EvalRunResult> {
    return request<EvalRunResult>("/v1/eval/run", {
      method: "POST",
      body,
      tolerateStatus: true,
    });
  },

  evalRuns(caseId?: string): Promise<EvalRunsResponse> {
    const q = caseId ? `?case_id=${encodeURIComponent(caseId)}` : "";
    return request<EvalRunsResponse>(`/v1/eval/runs${q}`);
  },

  // === Round Three: personal agent / notifications / memory ===

  configurePersonalAgent(
    body: ConfigurePersonalAgentRequest,
  ): Promise<ConfigurePersonalAgentResponse> {
    return request<ConfigurePersonalAgentResponse>("/v1/me/agent", {
      method: "POST",
      body,
    });
  },

  // delegated-only: spawns on-behalf-of the owner, capped to the owner's grants
  // (SEC-30); effective_grants in the result show that cap.
  invokePersonalAgent(
    body: InvokePersonalAgentRequest,
  ): Promise<SpawnResult> {
    return request<SpawnResult>("/v1/me/agent/invoke", {
      method: "POST",
      body,
      tolerateStatus: true,
    });
  },

  // Notification prefs are served only at /v1/me/notifications (meNotifications /
  // putMeNotification below) - the scope-locked, audited endpoint. The former
  // /v1/notifications/prefs pair was a weaker unaudited duplicate and was removed.

  memoryQuery(body: MemoryQueryRequest): Promise<MemoryQueryResponse> {
    return request<MemoryQueryResponse>("/v1/memory/query", {
      method: "POST",
      body,
    });
  },

  // === Round Five: memory & knowledge ===
  // The verb routes (recall/remember/forget/ingest) carry tolerateStatus so a
  // 404 (memory disabled -> binding_not_found) or 403 (scope denied) renders as
  // a message instead of throwing. The reads are scope-filtered server-side.

  memoryFacts(
    params: { kind?: string; limit?: number } = {},
  ): Promise<MemoryFactsResponse> {
    const q = new URLSearchParams();
    if (params.kind) q.set("kind", params.kind);
    if (params.limit !== undefined) q.set("limit", String(params.limit));
    const qs = q.toString();
    return request<MemoryFactsResponse>(`/v1/memory/facts${qs ? `?${qs}` : ""}`);
  },

  memoryRecall(body: MemoryRecallRequest): Promise<MemoryRecallResponse> {
    return request<MemoryRecallResponse>("/v1/memory/recall", {
      method: "POST",
      body,
      tolerateStatus: true,
    });
  },

  memoryRemember(body: MemoryRememberRequest): Promise<MemoryRememberResponse> {
    return request<MemoryRememberResponse>("/v1/memory/remember", {
      method: "POST",
      body,
      tolerateStatus: true,
    });
  },

  memoryForget(body: MemoryForgetRequest): Promise<MemoryForgetResponse> {
    return request<MemoryForgetResponse>("/v1/memory/forget", {
      method: "POST",
      body,
      tolerateStatus: true,
    });
  },

  memoryIngest(body: MemoryIngestRequest): Promise<MemoryIngestResponse> {
    return request<MemoryIngestResponse>("/v1/memory/ingest", {
      method: "POST",
      body,
      tolerateStatus: true,
    });
  },

  memoryIngestions(): Promise<MemoryIngestionsResponse> {
    return request<MemoryIngestionsResponse>("/v1/memory/ingestions", {
      tolerateStatus: true,
    });
  },

  // === Round Four: settings, account & access management ===
  // Writes carry tolerateStatus so a 400 (bad input), 403 (admin-only) or 404
  // (not found) renders as a message instead of throwing.

  meSettings(): Promise<MeSettingsResponse> {
    return request<MeSettingsResponse>("/v1/me/settings");
  },

  putMeSettings(body: PutSettingsRequest): Promise<PutSettingsResponse> {
    return request<PutSettingsResponse>("/v1/me/settings", {
      method: "PUT",
      body,
      tolerateStatus: true,
    });
  },

  meActivity(): Promise<MeActivityResponse> {
    return request<MeActivityResponse>("/v1/me/activity");
  },

  meExport(): Promise<MeExportResponse> {
    return request<MeExportResponse>("/v1/me/export");
  },

  deleteMyConversation(id: string): Promise<DeleteAck> {
    return request<DeleteAck>(
      `/v1/me/conversations/${encodeURIComponent(id)}`,
      { method: "DELETE", tolerateStatus: true },
    );
  },

  renameConversation(id: string, title: string): Promise<DeleteAck> {
    const body: RenameConversationRequest = { title };
    return request<DeleteAck>(
      `/v1/me/conversations/${encodeURIComponent(id)}`,
      { method: "PATCH", body, tolerateStatus: true },
    );
  },

  meTokens(): Promise<TokensResponse> {
    return request<TokensResponse>("/v1/me/tokens");
  },

  // The minted secret is in the response ONCE and is never returned again.
  mintToken(body: MintTokenRequest): Promise<MintTokenResponse> {
    return request<MintTokenResponse>("/v1/me/tokens", {
      method: "POST",
      body,
      tolerateStatus: true,
    });
  },

  revokeToken(id: string): Promise<DeleteAck> {
    return request<DeleteAck>(`/v1/me/tokens/${encodeURIComponent(id)}`, {
      method: "DELETE",
      tolerateStatus: true,
    });
  },

  meConnections(): Promise<ConnectionsResponse> {
    return request<ConnectionsResponse>("/v1/me/connections");
  },

  meSessions(): Promise<SessionsResponse> {
    return request<SessionsResponse>("/v1/me/sessions");
  },

  revokeSession(id: string): Promise<DeleteAck> {
    return request<DeleteAck>(`/v1/me/sessions/${encodeURIComponent(id)}`, {
      method: "DELETE",
      tolerateStatus: true,
    });
  },

  meNotifications(): Promise<MeNotificationsResponse> {
    return request<MeNotificationsResponse>("/v1/me/notifications");
  },

  putMeNotification(body: PutMeNotificationRequest): Promise<StatusAck> {
    return request<StatusAck>("/v1/me/notifications", {
      method: "PUT",
      body,
      tolerateStatus: true,
    });
  },

  meAgent(): Promise<MeAgentResponse> {
    return request<MeAgentResponse>("/v1/me/agent", { tolerateStatus: true });
  },

  adminUsers(): Promise<AdminUsersResponse> {
    return request<AdminUsersResponse>("/v1/admin/users", {
      tolerateStatus: true,
    });
  },

  patchUser(id: string, body: PatchUserRequest): Promise<PatchUserResponse> {
    return request<PatchUserResponse>(
      `/v1/admin/users/${encodeURIComponent(id)}`,
      { method: "PATCH", body, tolerateStatus: true },
    );
  },

  adminInvitations(): Promise<AdminInvitationsResponse> {
    return request<AdminInvitationsResponse>("/v1/admin/invitations", {
      tolerateStatus: true,
    });
  },

  createInvitation(
    body: CreateInvitationRequest,
  ): Promise<CreateInvitationResponse> {
    return request<CreateInvitationResponse>("/v1/admin/invitations", {
      method: "POST",
      body,
      tolerateStatus: true,
    });
  },

  revokeInvitation(id: string): Promise<DeleteAck> {
    return request<DeleteAck>(
      `/v1/admin/invitations/${encodeURIComponent(id)}`,
      { method: "DELETE", tolerateStatus: true },
    );
  },

  // === First-party auth (COUNTY 7): session login, invite accept, logout ===
  // These are the internet-facing gate when auth_mode=session. login/accept are
  // public (no principal); logout requires the session. All carry tolerateStatus
  // so a 401 (generic), 429 (throttled) or 400 (bad token / weak password)
  // renders faithfully instead of throwing.

  login(body: LoginRequest): Promise<LoginResponse> {
    return request<LoginResponse>("/v1/auth/login", {
      method: "POST",
      body,
      tolerateStatus: true,
    });
  },

  acceptInvite(body: AcceptInviteRequest): Promise<AcceptInviteResponse> {
    return request<AcceptInviteResponse>("/v1/auth/accept-invite", {
      method: "POST",
      body,
      tolerateStatus: true,
    });
  },

  logout(): Promise<StatusAck> {
    return request<StatusAck>("/v1/auth/logout", {
      method: "POST",
      tolerateStatus: true,
    });
  },

  // === Active context (COUNTY 8): switch the session's active workspace ===
  // The switch is re-authorized against membership server-side (404 unknown, 403
  // non-member, no write); tolerateStatus so those render as a message.
  switchActiveContext(workspaceId: string): Promise<SwitchContextResponse> {
    return request<SwitchContextResponse>("/v1/me/active-context", {
      method: "POST",
      body: { workspace_id: workspaceId },
      tolerateStatus: true,
    });
  },

  // === Workspaces (COUNTY 8): the caller's own workspaces + management ===

  workspaces(): Promise<WorkspacesResponse> {
    return request<WorkspacesResponse>("/v1/workspaces");
  },

  createWorkspace(
    body: CreateWorkspaceRequest,
  ): Promise<WorkspaceMutationResponse> {
    return request<WorkspaceMutationResponse>("/v1/workspaces", {
      method: "POST",
      body,
      tolerateStatus: true,
    });
  },

  updateWorkspace(
    id: string,
    body: UpdateWorkspaceRequest,
  ): Promise<WorkspaceMutationResponse> {
    return request<WorkspaceMutationResponse>(
      `/v1/workspaces/${encodeURIComponent(id)}`,
      { method: "PATCH", body, tolerateStatus: true },
    );
  },

  workspaceMembers(id: string): Promise<WorkspaceMembersResponse> {
    return request<WorkspaceMembersResponse>(
      `/v1/workspaces/${encodeURIComponent(id)}/members`,
      { tolerateStatus: true },
    );
  },

  addWorkspaceMember(
    id: string,
    body: AddWorkspaceMemberRequest,
  ): Promise<AddWorkspaceMemberResponse> {
    return request<AddWorkspaceMemberResponse>(
      `/v1/workspaces/${encodeURIComponent(id)}/members`,
      { method: "POST", body, tolerateStatus: true },
    );
  },

  removeWorkspaceMember(id: string, userId: string): Promise<DeleteAck> {
    return request<DeleteAck>(
      `/v1/workspaces/${encodeURIComponent(id)}/members/${encodeURIComponent(userId)}`,
      { method: "DELETE", tolerateStatus: true },
    );
  },

  // === Organisation (COUNTY 8): the caller's org handle + policy flags ===

  currentOrg(): Promise<CurrentOrgResponse> {
    return request<CurrentOrgResponse>("/v1/orgs/current");
  },

  updateCurrentOrg(body: UpdateOrgRequest): Promise<UpdateOrgResponse> {
    return request<UpdateOrgResponse>("/v1/orgs/current", {
      method: "PATCH",
      body,
      tolerateStatus: true,
    });
  },

  orgMembers(): Promise<OrgMembersResponse> {
    return request<OrgMembersResponse>("/v1/orgs/current/members");
  },

  // === AI keys (COUNTY 8): per-org / workspace / user, sealed once ===
  // GET returns has_key only (never the key). PUT accepts the key once (sealed
  // server-side). DELETE drops the row + sealed credential.

  aiKeys(): Promise<AiKeysResponse> {
    return request<AiKeysResponse>("/v1/ai-keys");
  },

  setAiKey(body: SetAiKeyRequest): Promise<SetAiKeyResponse> {
    return request<SetAiKeyResponse>("/v1/ai-keys", {
      method: "PUT",
      body,
      tolerateStatus: true,
    });
  },

  deleteAiKey(level: string, scopeId: string): Promise<DeleteAiKeyResponse> {
    return request<DeleteAiKeyResponse>(
      `/v1/ai-keys/${encodeURIComponent(level)}/${encodeURIComponent(scopeId)}`,
      { method: "DELETE", tolerateStatus: true },
    );
  },
};

// Raised when an SSE stream goes silent past the idle window: no frame, no
// heartbeat, not even the server's close. It carries status 0 so apiReason
// treats it as a connectivity fault, and the caller offers reconnect/replay.
export class StreamIdleError extends ApiError {
  constructor(idleMs: number) {
    super(0, `stream idle for ${Math.round(idleMs / 1000)}s (no data)`, null);
    this.name = "StreamIdleError";
  }
}

// A dead SSE stream (server wedged, proxy holding the socket open) must never
// hang the UI forever. If no byte arrives within this window we abandon the read
// and surface a StreamIdleError so the caller can reconnect with replay. The
// window resets on every chunk, including the SSE heartbeat comment (": ping"),
// so a live-but-quiet turn is not falsely tripped.
const STREAM_IDLE_MS = 120_000;

// Terminal events that end an SSE turn. Seeing one lets us close the reader
// eagerly instead of waiting on the socket's own (possibly buffered) close.
function isTerminalEvent(ev: ChatEvent): boolean {
  return ev.type === "message_end" || ev.type === "cancelled";
}

// Race a single reader.read() against the idle window. On timeout the reader is
// cancelled (releasing the socket) and a StreamIdleError is thrown.
async function readWithIdleTimeout(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  idleMs: number,
): Promise<ReadableStreamReadResult<Uint8Array>> {
  if (!idleMs || idleMs <= 0) return reader.read();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const idle = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => reject(new StreamIdleError(idleMs)), idleMs);
  });
  try {
    return await Promise.race([reader.read(), idle]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}

// The shared SSE pump: read frames delimited by a blank line, buffering partial
// frames across chunks, dispatch each parsed ChatEvent, and close cleanly on a
// terminal event (message_end / cancelled) or the server's own stream close. An
// idle-timeout guard bounds a dead stream; an AbortSignal cancels immediately.
async function pumpSse(
  res: Response,
  onEvent: (event: ChatEvent) => void,
  idleMs: number,
): Promise<void> {
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let terminated = false;
  try {
    for (;;) {
      const { value, done } = await readWithIdleTimeout(reader, idleMs);
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      // Normalise CRLF so the blank-line frame delimiter is always "\n\n".
      buffer = buffer.replace(/\r\n/g, "\n");
      let idx: number;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        const ev = emitFrame(frame, onEvent);
        if (ev && isTerminalEvent(ev)) {
          terminated = true;
          break;
        }
      }
      if (terminated) break;
    }
    if (!terminated) {
      // Flush any trailing frame that arrived without a closing blank line.
      buffer += decoder.decode();
      buffer = buffer.replace(/\r\n/g, "\n").trim();
      if (buffer) emitFrame(buffer, onEvent);
    }
  } finally {
    // Release the socket on every exit path (terminal event, idle timeout,
    // abort). A double cancel is a harmless no-op.
    void reader.cancel().catch(() => {});
  }
}

// POST /v1/chat is a Server-Sent Events stream: each `data:` line is one JSON
// ChatEvent. onEvent is called once per parsed event; pass an AbortSignal to
// cancel (the partial result still persists kernel-side and can be re-fetched
// via conversation()). The stream closes cleanly on message_end / cancelled and
// is bounded by an idle-timeout guard so a dead stream never hangs the UI.
export async function streamChat(
  body: ChatRequest,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const headers: Record<string, string> = {
    ...identityHeaders(),
    ...csrfHeaders("POST"),
    "content-type": "application/json",
    accept: "text/event-stream",
  };

  let res: Response;
  try {
    res = await fetch(`${BASE}/v1/chat`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    const reason = err instanceof Error ? err.message : "network error";
    throw new ApiError(0, `chat stream failed: ${reason}`, null);
  }

  if (!res.ok || !res.body) {
    const parsed = await parseBody(res);
    throw new ApiError(res.status, `POST /v1/chat -> ${res.status}`, parsed);
  }

  await pumpSse(res, onEvent, STREAM_IDLE_MS);
}

// Subscribe to a run's event stream (Round Eleven, the Run drawer / live canvas).
// follow=false (default) yields the current snapshot then ends; follow=true keeps
// streaming live until the run closes. Same SSE frame format + hardening as
// streamChat (clean terminal close, idle-timeout guard). Because the kernel relay
// replays a run's events on subscribe, this doubles as the reconnect/replay path.
export async function streamRunEvents(
  runId: string,
  onEvent: (event: ChatEvent) => void,
  opts: { signal?: AbortSignal; follow?: boolean } = {},
): Promise<void> {
  const headers: Record<string, string> = {
    ...identityHeaders(),
    accept: "text/event-stream",
  };
  const q = opts.follow ? "?follow=1" : "";
  let res: Response;
  try {
    res = await fetch(`${BASE}/v1/runs/${encodeURIComponent(runId)}/events${q}`, {
      method: "GET",
      headers,
      signal: opts.signal,
    });
  } catch (err) {
    const reason = err instanceof Error ? err.message : "network error";
    throw new ApiError(0, `run events stream failed: ${reason}`, null);
  }
  if (!res.ok || !res.body) {
    const parsed = await parseBody(res);
    throw new ApiError(res.status, `GET /v1/runs/${runId}/events -> ${res.status}`, parsed);
  }
  // A snapshot (follow=false) ends on the server's stream close, so keep the idle
  // guard for the live-follow case only; a snapshot without a heartbeat is fine.
  await pumpSse(res, onEvent, opts.follow ? STREAM_IDLE_MS : 0);
}

// Parse one SSE frame and dispatch its ChatEvent. Returns the parsed event (or
// null for a heartbeat / unparseable / [DONE] frame) so the pump can detect a
// terminal event and close eagerly.
function emitFrame(
  frame: string,
  onEvent: (event: ChatEvent) => void,
): ChatEvent | null {
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
  }
  if (dataLines.length === 0) return null;
  const payload = dataLines.join("\n").trim();
  if (!payload || payload === "[DONE]") return null;
  try {
    const ev = JSON.parse(payload) as ChatEvent;
    // A heartbeat is a keep-alive only: receiving its frame already reset the
    // idle-timeout guard (the guard resets on every reader.read that returns),
    // so we drop it here without dispatching. It must never reach a consumer or
    // land in the transcript - it is not rendered and not folded into a turn.
    if (ev.type === "heartbeat") return null;
    onEvent(ev);
    return ev;
  } catch {
    // Ignore an unparseable frame so one bad line never kills the stream.
    return null;
  }
}
