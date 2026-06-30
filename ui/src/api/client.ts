// Typed fetch client over the kernel HTTP surface. Every request carries the
// dev identity headers (x-nankle-*) read from the identity store. Paths are
// relative: the Vite dev server and the nginx prod image both proxy /v1 and
// /healthz to the kernel.

import { getIdentity } from "../identity";
import type {
  ActivateAdapterRequest,
  ActivateAdapterResponse,
  AdapterInventoryResponse,
  AdapterSourceResponse,
  AdminInvitationsResponse,
  AdminUsersResponse,
  AuditExportResponse,
  AuditSearchResponse,
  AuditTreeResponse,
  CapabilitiesResponse,
  ChatEvent,
  ChatRequest,
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
  NotificationPrefsResponse,
  PatchUserRequest,
  PatchUserResponse,
  PutConfigRequest,
  PutConfigResponse,
  PutMeNotificationRequest,
  PutNotificationPrefRequest,
  PutSettingsRequest,
  PutSettingsResponse,
  RegisterMcpRequest,
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
    "x-nankle-tenant": id.tenant,
    "x-nankle-subject": id.subject,
    "x-nankle-grants": id.grants,
    "x-nankle-role": id.role,
    "x-nankle-departments": id.departments ?? "",
  };
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
  const headers: Record<string, string> = { ...identityHeaders() };
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

  conversation(id: string): Promise<ConversationResponse> {
    return request<ConversationResponse>(
      `/v1/conversations/${encodeURIComponent(id)}`,
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

  // === Round Three: insight (scope-filtered server-side, SEC-33) ===

  cost(): Promise<CostResponse> {
    return request<CostResponse>("/v1/cost");
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

  notificationPrefs(): Promise<NotificationPrefsResponse> {
    return request<NotificationPrefsResponse>("/v1/notifications/prefs");
  },

  putNotificationPref(body: PutNotificationPrefRequest): Promise<StatusAck> {
    return request<StatusAck>("/v1/notifications/prefs", {
      method: "PUT",
      body,
    });
  },

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
};

// POST /v1/chat is a Server-Sent Events stream: each `data:` line is one JSON
// ChatEvent. We read the body with a ReadableStream reader and parse frames
// delimited by a blank line, buffering partial frames across chunks. onEvent is
// called once per parsed event; pass an AbortSignal to cancel (the partial
// result still persists kernel-side and can be re-fetched via conversation()).
export async function streamChat(
  body: ChatRequest,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const headers: Record<string, string> = {
    ...identityHeaders(),
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

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // Normalise CRLF so the blank-line frame delimiter is always "\n\n".
    buffer = buffer.replace(/\r\n/g, "\n");
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      emitFrame(frame, onEvent);
    }
  }

  // Flush any trailing frame that arrived without a closing blank line.
  buffer += decoder.decode();
  buffer = buffer.replace(/\r\n/g, "\n").trim();
  if (buffer) emitFrame(buffer, onEvent);
}

// Subscribe to a run's event stream (Round Eleven, the Run drawer / live canvas).
// follow=false (default) yields the current snapshot then ends; follow=true keeps
// streaming live until the run closes. Same SSE frame format as streamChat.
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
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    buffer = buffer.replace(/\r\n/g, "\n");
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      emitFrame(frame, onEvent);
    }
  }
  buffer += decoder.decode();
  buffer = buffer.replace(/\r\n/g, "\n").trim();
  if (buffer) emitFrame(buffer, onEvent);
}

function emitFrame(frame: string, onEvent: (event: ChatEvent) => void): void {
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("data:")) dataLines.push(line.slice(5).replace(/^ /, ""));
  }
  if (dataLines.length === 0) return;
  const payload = dataLines.join("\n").trim();
  if (!payload || payload === "[DONE]") return;
  try {
    onEvent(JSON.parse(payload) as ChatEvent);
  } catch {
    // Ignore an unparseable frame so one bad line never kills the stream.
  }
}
