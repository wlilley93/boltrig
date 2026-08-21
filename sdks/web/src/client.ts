import type {
  ActivateAdapterRequest,
  ActivateAdapterResponse,
  ActivateAiKeyRequest,
  AddWorkspaceMemberRequest,
  AddWorkspaceMemberResponse,
  AdminInvitationsResponse,
  AdminUsersResponse,
  AddonsResponse,
  BrandingResponse,
  AdapterInventoryResponse,
  AdapterSourceResponse,
  Artifact,
  ArtifactListOptions,
  ArtifactsResponse,
  AiKeysResponse,
  AiKeyProposalResponse,
  AiKeyProposalsResponse,
  AcceptInviteRequest,
  AcceptInviteResponse,
  AnswerQuestionResponse,
  AuditExportResponse,
  AuditSearchResponse,
  AuditTreeResponse,
  AuditVerifyResponse,
  AuthoredDefinitionLifecycleResponse,
  BindChannelRequest,
  BindChannelResponse,
  BudgetPolicyRequest,
  BudgetsResponse,
  BirthProfileResponse,
  CallCreateRequest,
  CallCreateResponse,
  CallEventsResponse,
  CallsResponse,
  CurrentCallResponse,
  CallUsageResponse,
  CancelRunResponse,
  ChannelAck,
  ChannelBindingsResponse,
  ChannelDeliveriesResponse,
  ChannelPairFinalizationsResponse,
  ChannelGatewaySessionRequest,
  ChannelGatewaySessionResponse,
  RetryChannelDeliveryResponse,
  ChannelsResponse,
  ChatConfigResponse,
  ChatEvent,
  ChatFollowFrame,
  ChatModelChoicesResponse,
  BifrostModelsResponse,
  ChatRequest,
  AgentCapabilitiesResponse,
  PermanentFleetApplyResponse,
  PermanentFleetHierarchy,
  PermanentFleetResponse,
  CapabilityLifecycleResponse,
  CapabilityChangelogResponse,
  CapabilitiesResponse,
  ConfigureChannelRequest,
  ConfigurePersonalAgentRequest,
  ConfigurePersonalAgentResponse,
  ConnectChannelRequest,
  ConnectChannelResponse,
  ConnectionsResponse,
  ConsoleOverviewResponse,
  ConversationResponse,
  ConversationProjectMoveResponse,
  ConversationQueueReorderRequest,
  ConversationQueueReorderResponse,
  ConversationSearchResponse,
  ConversationsPageResponse,
  ConversationsResponse,
  CostResponse,
  CreateInvitationRequest,
  CreateInvitationResponse,
  CreateWorkRequest,
  CreateEvalCaseRequest,
  CreateWorkflowTriggerRequest,
  CreateWorkspaceRequest,
  CurrentOrgResponse,
  DeleteAck,
  DevicesResponse,
  DeleteAiKeyResponse,
  DeviceEnrollmentStart,
  DeviceFileListRequest,
  DeviceLeaseInvokeOptions,
  OwnerDeviceLeasesResponse,
  DeviceRootResponse,
  CreateDeviceRootRequest,
  EvalCasesResponse,
  EvalCaseLifecycleResponse,
  EvalRunResult,
  EvalRunsResponse,
  FederatedSearchRequest,
  FederatedSearchResponse,
  GenerateAdapterRequest,
  GenerateAdapterResponse,
  HealthResponse,
  HITLListResponse,
  HitlPolicyResponse,
  ApprovalPostureResponse,
  PutApprovalPostureRequest,
  PutSensingCameraRequest,
  PutSensingPresenceRequest,
  SensingCapabilityDecision,
  SensingResponse,
  PrivacyPolicyResponse,
  BackupStatusResponse,
  CapabilityBindingsResponse,
  CapabilityBindingStatus,
  CapabilityCatalogueResponse,
  RoutingPoliciesResponse,
  IntegrationCatalogueResponse,
  IntegrationConnectionResponse,
  IntegrationConnectionsResponse,
  IntegrationOAuthStartResponse,
  IntegrationSecretSubmission,
  IntegrationSetupResponse,
  InvokeRequest,
  InvokeApprovalStateResponse,
  InvokeResult,
  GovernedRouteResponse,
  KnowledgeAssetsResponse,
  KnowledgeAssetDetailResponse,
  KnowledgeMutationResponse,
  MemberIntegrationConnectionsResponse,
  KnowledgeProvidersResponse,
  KnowledgeSearchResponse,
  KnowledgeUploadResponse,
  LoginRequest,
  LoginResponse,
  MeActivityResponse,
  MeAgentResponse,
  MeExportResponse,
  MeNotificationsResponse,
  MyOrganisationsResponse,
  MeSettingsResponse,
  NamedAgentsResponse,
  UpdateMeProfileRequest,
  UpdateMeProfileResponse,
  MemoryFactResponse,
  MemoryFactsResponse,
  MemoryForgetRequest,
  MemoryForgetResponse,
  MemoryImproveRequest,
  MemoryImproveResponse,
  MemoryIngestRequest,
  MemoryIngestResponse,
  MemoryCandidateReviewRequest,
  MemoryCandidateReviewResponse,
  MemoryCandidatesResponse,
  MemoryIngestionsResponse,
  MemoryTimelineResponse,
  MemoryRecallRequest,
  MemoryRecallResponse,
  MemoryRememberRequest,
  MemoryRememberResponse,
  McpServerDetailResponse,
  McpServersResponse,
  DeleteMcpServerResponse,
  ModelProfilesResponse,
  ModelEndpointsResponse,
  ModelEndpointLifecycleResponse,
  ModelEndpointResponse,
  ModelPolicyResponse,
  SpawnRulePolicyResponse,
  SpawnRuleSimulationResponse,
  ModelTelemetryResponse,
  NounResponse,
  NounsResponse,
  MintTokenRequest,
  MintTokenResponse,
  OrgMembersResponse,
  PairChannelRequest,
  PairChannelResponse,
  PatchUserRequest,
  PatchUserResponse,
  PasswordResetConfirmRequest,
  PasswordResetConfirmResponse,
  PasswordResetRequest,
  PasswordResetRequestResponse,
  PlatformStatusResponse,
  PutMeNotificationRequest,
  TestMeNotificationResponse,
  PutSettingsRequest,
  PutSettingsResponse,
  ReadinessResponse,
  RealtimeCall,
  RegenerateResponse,
  RegisterMcpRequest,
  UpdateMcpServerRequest,
  UpdateMcpServerResponse,
  RespondResult,
  RunEffectsResponse,
  RunEvalRequest,
  RunRevertResponse,
  RunsResponse,
  RunTopologyResponse,
  ScheduleWorkflowRequest,
  ScheduleWorkflowResponse,
  RetryWorkflowScheduleOccurrenceResponse,
  SetAiKeyRequest,
  SetAiKeyResponse,
  SessionsResponse,
  SessionCsrfResponse,
  SetBindingRequest,
  SkillsResponse,
  SkillResponse,
  SpawnRequest,
  SpawnResult,
  StatusAck,
  SwitchContextResponse,
  TestSpawnRequest,
  TokensResponse,
  TriggerWorkflowRequest,
  UpdateOrgRequest,
  UpdateOrgResponse,
  UpdateWorkspaceRequest,
  WorkDetailResponse,
  WorkMutationResult,
  WorkResponse,
  WorkStatus,
  WorkflowDetail,
  WorkflowRunDescriptor,
  WorkflowRunRecord,
  WorkflowLifecycleResponse,
  WorkflowScheduleOccurrencesResponse,
  WorkflowRunsResponse,
  WorkflowStatsResponse,
  WorkflowTriggerDeliveriesResponse,
  WorkflowTriggerFinalizationsResponse,
  WorkflowTriggerMutationResponse,
  WorkflowTriggersResponse,
  WorkflowsResponse,
  WorkspaceMembersResponse,
  WorkspaceMutationResponse,
  WorkspacesResponse,
  InvokePersonalAgentRequest,
  UpsertNounRequest,
  UpsertSkillRequest,
  UpsertVerbRequest,
  UpsertWorkflowRequest,
  TwoFactorChallengeRequest,
  TwoFactorChallengeResponse,
  TwoFactorEnrollBeginResponse,
  TwoFactorVerifyEnrollRequest,
  TwoFactorVerifyEnrollResponse,
  VerbResponse,
  VerbsResponse,
} from "./types.js";
import type { FamiliarPhenotypeResponse } from "./familiarState.js";

export interface BoltrigClientOptions {
  baseUrl?: string;
  fetch?: typeof globalThis.fetch;
  /**
   * Desktop supplies a short-lived Boltrig device session from the OS keychain.
   * Browser clients omit this and use the existing httpOnly cookie + CSRF flow.
   */
  accessToken?: () => string | null | Promise<string | null>;
  csrfToken?: () => string | null;
  headers?: () => Record<string, string>;
  /**
   * Whether the browser attaches its cookies. Defaults to "include" for a
   * cookie-session client and "omit" for a BEARER one, which is the case that
   * matters: every fetch here hardcoded "include", so a host application
   * authenticating with `accessToken` from its own origin would have shipped
   * the user's Boltrig session cookie cross-origin on every call, alongside a
   * bearer that already authenticates the request. The cookie is not needed and
   * sending it is not free.
   *
   * Set it explicitly to override either default, for a host that genuinely
   * wants both credentials on one request.
   */
  credentials?: RequestCredentials;
}

export interface ChatQueued {
  status: "queued";
  conversation_id: string | null;
  message_id: string | null;
  run_id: string | null;
  /** Stable run id reserved for the queued turn itself. */
  queued_run_id?: string | null;
  agent_address?: string | null;
}

export interface ChatFollowResult {
  status: "ended" | "idle" | "aborted";
  cursor: number;
}

export class BoltrigApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: unknown,
    message = `Boltrig request failed (${status})`,
  ) {
    super(message);
    this.name = "BoltrigApiError";
  }
}

const mutating = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function browserCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const item = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith("boltrig_csrf="));
  return item ? decodeURIComponent(item.slice("boltrig_csrf=".length)) : null;
}

async function parseResponse(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export class BoltrigClient {
  private readonly baseUrl: string;
  private readonly fetcher: typeof globalThis.fetch;

  constructor(private readonly options: BoltrigClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? "").replace(/\/$/, "");
    this.fetcher = options.fetch ?? globalThis.fetch.bind(globalThis);
  }

  /** Cookies for a cookie session; nothing for a bearer one. */
  private credentials(): RequestCredentials {
    if (this.options.credentials) return this.options.credentials;
    return this.options.accessToken ? "omit" : "include";
  }

  /**
   * The double-submit CSRF token, or null.
   *
   * The browser FALLBACK reads `document.cookie`, which is meaningful only for
   * a cookie session on this origin. A bearer caller has no such cookie to
   * read, and reaching for one would copy an unrelated same-origin cookie value
   * into a cross-origin header. An explicitly supplied `csrfToken` is always
   * honoured: a host that configures one has said it wants it.
   */
  private csrf(): string | null {
    if (this.options.csrfToken) return this.options.csrfToken();
    return this.options.accessToken ? null : browserCsrfToken();
  }

  private async request<T>(
    path: string,
    init: RequestInit & { tolerateStatus?: boolean } = {},
  ): Promise<T> {
    const method = (init.method ?? "GET").toUpperCase();
    const headers = new Headers(init.headers);
    headers.set("accept", "application/json");
    for (const [key, value] of Object.entries(this.options.headers?.() ?? {})) {
      headers.set(key, value);
    }
    const accessToken = await this.options.accessToken?.();
    if (accessToken) headers.set("authorization", `Bearer ${accessToken}`);
    const csrf = this.csrf();
    if (csrf && mutating.has(method)) headers.set("x-boltrig-csrf", csrf);

    let response: Response;
    try {
      response = await this.fetcher(`${this.baseUrl}${path}`, {
        ...init,
        method,
        headers,
        credentials: this.credentials(),
      });
    } catch (error) {
      throw new BoltrigApiError(
        0,
        null,
        error instanceof Error ? error.message : "Network request failed",
      );
    }
    const body = await parseResponse(response);
    if (!response.ok && !init.tolerateStatus) {
      throw new BoltrigApiError(response.status, body);
    }
    return body as T;
  }

  private json<T>(
    path: string,
    method: "POST" | "PUT" | "PATCH" | "DELETE",
    body?: unknown,
    tolerateStatus = false,
  ): Promise<T> {
    return this.request<T>(path, {
      method,
      headers: body === undefined ? undefined : { "content-type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      tolerateStatus,
    });
  }

  private governedJson<T>(
    path: string,
    method: "POST" | "PUT" | "PATCH" | "DELETE",
    body?: unknown,
    approvalId?: string,
  ): Promise<T> {
    return this.request<T>(path, {
      method,
      headers: {
        ...(body === undefined ? {} : { "content-type": "application/json" }),
        ...(approvalId ? { "x-boltrig-approval-id": approvalId } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      tolerateStatus: true,
    });
  }

  private async raw(path: string, init: RequestInit = {}): Promise<Response> {
    const method = (init.method ?? "GET").toUpperCase();
    const headers = new Headers(init.headers);
    for (const [key, value] of Object.entries(this.options.headers?.() ?? {})) {
      headers.set(key, value);
    }
    const accessToken = await this.options.accessToken?.();
    if (accessToken) headers.set("authorization", `Bearer ${accessToken}`);
    const csrf = this.csrf();
    if (csrf && mutating.has(method)) headers.set("x-boltrig-csrf", csrf);
    let response: Response;
    try {
      response = await this.fetcher(`${this.baseUrl}${path}`, {
        ...init,
        method,
        headers,
        credentials: this.credentials(),
      });
    } catch (error) {
      throw new BoltrigApiError(
        0,
        null,
        error instanceof Error ? error.message : "Network request failed",
      );
    }
    if (!response.ok) {
      throw new BoltrigApiError(response.status, await parseResponse(response));
    }
    return response;
  }

  conversations(): Promise<ConversationsResponse> {
    return this.request("/v1/conversations");
  }

  chatConfig(): Promise<ChatConfigResponse> {
    return this.request("/v1/chat/config");
  }

  /** Cosmetic, owner-scoped familiar phenotype (ADR 0025). Resting when stale. */
  familiarPhenotype(): Promise<FamiliarPhenotypeResponse> {
    return this.request("/v1/familiar/phenotype");
  }

  conversationsPage(limit = 50, offset = 0): Promise<ConversationsPageResponse> {
    const query = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    });
    return this.request(`/v1/conversations?${query.toString()}`);
  }

  searchConversations(
    queryText: string,
    limit = 50,
    offset = 0,
  ): Promise<ConversationSearchResponse> {
    const value = queryText.trim();
    if (!value) {
      return Promise.reject(new BoltrigApiError(400, { reason: "q is required" }));
    }
    const query = new URLSearchParams({
      q: value,
      limit: String(limit),
      offset: String(offset),
    });
    return this.request(`/v1/conversations/search?${query.toString()}`);
  }

  federatedSearch(body: FederatedSearchRequest): Promise<FederatedSearchResponse> {
    return this.json("/v1/search", "POST", body);
  }

  conversation(id: string): Promise<ConversationResponse> {
    return this.request(`/v1/conversations/${encodeURIComponent(id)}`);
  }

  namedAgents(): Promise<NamedAgentsResponse> {
    return this.request("/v1/named-agents");
  }

  reorderConversationQueue(
    id: string,
    body: ConversationQueueReorderRequest,
  ): Promise<ConversationQueueReorderResponse> {
    return this.json(
      `/v1/conversations/${encodeURIComponent(id)}/queue`,
      "PUT",
      body,
    );
  }

  async followConversation(
    id: string,
    onFrame: (frame: ChatFollowFrame) => void,
    options: { since?: number; signal?: AbortSignal } = {},
  ): Promise<ChatFollowResult> {
    const since = options.since ?? 0;
    if (!Number.isSafeInteger(since) || since < 0) {
      throw new BoltrigApiError(400, { reason: "invalid cursor" });
    }
    const query = new URLSearchParams({ follow: "1", since: String(since) });
    const headers = new Headers({ accept: "text/event-stream" });
    for (const [key, value] of Object.entries(this.options.headers?.() ?? {})) {
      headers.set(key, value);
    }
    const accessToken = await this.options.accessToken?.();
    if (accessToken) headers.set("authorization", `Bearer ${accessToken}`);

    let response: Response;
    try {
      response = await this.fetcher(
        `${this.baseUrl}/v1/conversations/${encodeURIComponent(id)}/events?${query}`,
        {
          method: "GET",
          headers,
          credentials: this.credentials(),
          signal: options.signal,
        },
      );
    } catch (error) {
      if (options.signal?.aborted) return { status: "aborted", cursor: since };
      throw new BoltrigApiError(
        0,
        null,
        error instanceof Error ? error.message : "Chat reattachment failed",
      );
    }
    if (response.status === 409) {
      await parseResponse(response);
      return { status: "idle", cursor: since };
    }
    if (!response.ok || !response.body) {
      throw new BoltrigApiError(response.status, await parseResponse(response));
    }

    let cursor = since;
    let sawFrame = false;
    try {
      await pumpSseFrames<ChatFollowFrame>(response.body, (frame) => {
        if (
          !frame
          || !Number.isSafeInteger(frame.cursor)
          || frame.cursor < 0
          || !frame.event
        ) {
          throw new BoltrigApiError(0, frame, "Invalid chat follow frame");
        }
        if (sawFrame && frame.cursor < cursor) {
          throw new BoltrigApiError(0, frame, "Chat follow cursor regressed");
        }
        cursor = frame.cursor;
        sawFrame = true;
        if (frame.event.type !== "heartbeat") onFrame(frame);
      }, options.signal);
    } catch (error) {
      if (options.signal?.aborted) return { status: "aborted", cursor };
      throw error;
    }
    return { status: "ended", cursor };
  }

  meSettings(): Promise<MeSettingsResponse> {
    return this.request("/v1/me/settings");
  }

  updateMeProfile(body: UpdateMeProfileRequest): Promise<UpdateMeProfileResponse> {
    return this.json("/v1/me/profile", "PATCH", body, true);
  }

  aiKeys(): Promise<AiKeysResponse> {
    return this.request("/v1/ai-keys", { tolerateStatus: true });
  }

  setAiKey(body: SetAiKeyRequest): Promise<SetAiKeyResponse> {
    return this.json("/v1/ai-keys", "PUT", body, true);
  }

  activateAiKey(body: ActivateAiKeyRequest): Promise<SetAiKeyResponse> {
    return this.json("/v1/ai-keys/activate", "POST", body, true);
  }

  aiKeyProposals(): Promise<AiKeyProposalsResponse> {
    return this.request("/v1/ai-keys/proposals", { tolerateStatus: true });
  }

  aiKeyProposal(proposalId: string): Promise<AiKeyProposalResponse> {
    return this.request(
      `/v1/ai-keys/proposals/${encodeURIComponent(proposalId)}`,
      { tolerateStatus: true },
    );
  }

  finalizeAiKeyProposal(proposalId: string): Promise<AiKeyProposalResponse> {
    return this.json(
      `/v1/ai-keys/proposals/${encodeURIComponent(proposalId)}/finalize`,
      "POST",
      undefined,
      true,
    );
  }

  approveAiKeyProposal(proposalId: string): Promise<AiKeyProposalResponse> {
    return this.json(
      `/v1/ai-keys/proposals/${encodeURIComponent(proposalId)}/approve`,
      "POST",
      {},
      true,
    );
  }

  invalidateAiKeyProposal(proposalId: string): Promise<AiKeyProposalResponse> {
    return this.json(
      `/v1/ai-keys/proposals/${encodeURIComponent(proposalId)}`,
      "DELETE",
      undefined,
      true,
    );
  }

  deleteAiKey(
    level: string,
    scopeId: string,
    approvalId?: string,
    modality: "text" | "vision" = "text",
  ): Promise<DeleteAiKeyResponse> {
    const suffix = modality === "text"
      ? ""
      : `?modality=${encodeURIComponent(modality)}`;
    return this.governedJson(
      `/v1/ai-keys/${encodeURIComponent(level)}/${encodeURIComponent(scopeId)}${suffix}`,
      "DELETE",
      undefined,
      approvalId,
    );
  }

  putMeSettings(body: PutSettingsRequest): Promise<PutSettingsResponse> {
    return this.json("/v1/me/settings", "PUT", body, true);
  }

  approvalPosture(): Promise<ApprovalPostureResponse> {
    return this.request("/v1/me/approval-posture");
  }

  putApprovalPosture(body: PutApprovalPostureRequest): Promise<ApprovalPostureResponse> {
    return this.json("/v1/me/approval-posture", "PUT", body, true);
  }

  // --- Camera and presence ---------------------------------------------------
  // The camera is a Boltrig SERVICE with a UI, not a companion's private daemon.
  // These four are the consent surface; the fifth is what a CHARACTER gets when
  // it asks, and it answers with a reason rather than throwing.

  sensing(): Promise<SensingResponse> {
    return this.request("/v1/me/sensing");
  }

  putSensingCamera(body: PutSensingCameraRequest): Promise<SensingResponse> {
    return this.json("/v1/me/sensing/camera", "PUT", body, true);
  }

  putSensingPresence(body: PutSensingPresenceRequest): Promise<SensingResponse> {
    return this.json("/v1/me/sensing/presence", "PUT", body, true);
  }

  deleteSensingEnrollment(): Promise<SensingResponse> {
    return this.json("/v1/me/sensing/enrollment", "DELETE", undefined, true);
  }

  /**
   * What a character asking for this capability RIGHT NOW is told. Checked at
   * use and never cached: a cached grant would keep a character watching after
   * the user moved the toggle. `tolerateStatus` is on because a refusal is a
   * 409 the caller must read, not an exception it must catch.
   */
  sensingCapability(capability: string): Promise<SensingCapabilityDecision> {
    return this.request(
      `/v1/sensing/capability?capability=${encodeURIComponent(capability)}`,
      { tolerateStatus: true },
    );
  }

  meActivity(params: { limit?: number; offset?: number } = {}): Promise<MeActivityResponse> {
    const query = new URLSearchParams();
    if (params.limit !== undefined) query.set("limit", String(params.limit));
    if (params.offset !== undefined) query.set("offset", String(params.offset));
    return this.request(`/v1/me/activity${query.size ? `?${query}` : ""}`);
  }

  meExport(): Promise<MeExportResponse> {
    return this.request("/v1/me/export");
  }

  deleteMyConversation(id: string): Promise<DeleteAck> {
    return this.json(
      `/v1/me/conversations/${encodeURIComponent(id)}`,
      "DELETE",
      undefined,
      true,
    );
  }

  restoreMyConversation(id: string): Promise<DeleteAck> {
    return this.json(
      `/v1/me/conversations/${encodeURIComponent(id)}/restore`,
      "POST",
      {},
      true,
    );
  }

  renameConversation(id: string, title: string): Promise<DeleteAck> {
    return this.json(
      `/v1/me/conversations/${encodeURIComponent(id)}`,
      "PATCH",
      { title },
      true,
    );
  }

  moveConversationProject(
    id: string,
    workspaceId: string | null,
    expectedWorkspaceId: string | null,
  ): Promise<ConversationProjectMoveResponse> {
    return this.json(
      `/v1/me/conversations/${encodeURIComponent(id)}/project`,
      "PATCH",
      { workspace_id: workspaceId, expected_workspace_id: expectedWorkspaceId },
      true,
    );
  }

  regenerateMessage(conversationId: string, messageId: string): Promise<RegenerateResponse> {
    return this.json(
      `/v1/me/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/regenerate`,
      "POST",
      undefined,
      true,
    );
  }

  meTokens(): Promise<TokensResponse> {
    return this.request("/v1/me/tokens");
  }

  mintToken(body: MintTokenRequest): Promise<MintTokenResponse> {
    return this.json("/v1/me/tokens", "POST", body, true);
  }

  revokeToken(id: string): Promise<DeleteAck> {
    return this.json(`/v1/me/tokens/${encodeURIComponent(id)}`, "DELETE", undefined, true);
  }

  meConnections(): Promise<ConnectionsResponse> {
    return this.request("/v1/me/connections");
  }

  meSessions(): Promise<SessionsResponse> {
    return this.request("/v1/me/sessions");
  }

  revokeSession(id: string): Promise<DeleteAck> {
    return this.json(`/v1/me/sessions/${encodeURIComponent(id)}`, "DELETE", undefined, true);
  }

  switchActiveContext(workspaceId: string): Promise<SwitchContextResponse> {
    return this.json(
      "/v1/me/active-context",
      "POST",
      { workspace_id: workspaceId },
      true,
    );
  }

  switchActiveOrg(orgId: string): Promise<SwitchContextResponse> {
    return this.json("/v1/me/active-org", "POST", { org_id: orgId }, true);
  }

  meNotifications(): Promise<MeNotificationsResponse> {
    return this.request("/v1/me/notifications");
  }

  putMeNotification(
    body: PutMeNotificationRequest,
    approvalId?: string,
  ): Promise<GovernedRouteResponse<DeleteAck>> {
    return this.governedJson(
      "/v1/me/notifications", "PUT", body, approvalId,
    );
  }

  testMeNotification(id: string): Promise<TestMeNotificationResponse> {
    return this.json(
      `/v1/me/notifications/${encodeURIComponent(id)}/test`,
      "POST",
      undefined,
      true,
    );
  }

  meAgent(): Promise<MeAgentResponse> {
    return this.request("/v1/me/agent", { tolerateStatus: true });
  }

  configurePersonalAgent(
    body: ConfigurePersonalAgentRequest,
  ): Promise<ConfigurePersonalAgentResponse> {
    return this.json("/v1/me/agent", "POST", body, true);
  }

  deletePersonalAgent(): Promise<DeleteAck> {
    return this.json("/v1/me/agent", "DELETE", undefined, true);
  }

  invokePersonalAgent(body: InvokePersonalAgentRequest): Promise<SpawnResult> {
    return this.json("/v1/me/agent/invoke", "POST", body, true);
  }

  currentOrg(): Promise<CurrentOrgResponse> {
    return this.request("/v1/orgs/current");
  }

  myOrganisations(): Promise<MyOrganisationsResponse> {
    return this.request("/v1/me/orgs");
  }

  updateCurrentOrg(
    body: UpdateOrgRequest,
    approvalId?: string,
  ): Promise<GovernedRouteResponse<UpdateOrgResponse>> {
    return this.governedJson(
      "/v1/orgs/current", "PATCH", body, approvalId,
    );
  }

  orgMembers(): Promise<OrgMembersResponse> {
    return this.request("/v1/orgs/current/members");
  }

  workspaces(): Promise<WorkspacesResponse> {
    return this.request("/v1/workspaces");
  }

  createWorkspace(
    body: CreateWorkspaceRequest,
    approvalId?: string,
  ): Promise<GovernedRouteResponse<WorkspaceMutationResponse>> {
    return this.governedJson("/v1/workspaces", "POST", body, approvalId);
  }

  updateWorkspace(
    id: string,
    body: UpdateWorkspaceRequest,
    approvalId?: string,
  ): Promise<GovernedRouteResponse<WorkspaceMutationResponse>> {
    return this.governedJson(
      `/v1/workspaces/${encodeURIComponent(id)}`,
      "PATCH",
      body,
      approvalId,
    );
  }

  workspaceMembers(id: string): Promise<WorkspaceMembersResponse> {
    return this.request(
      `/v1/workspaces/${encodeURIComponent(id)}/members`,
      { tolerateStatus: true },
    );
  }

  addWorkspaceMember(
    id: string,
    body: AddWorkspaceMemberRequest,
    approvalId?: string,
  ): Promise<GovernedRouteResponse<AddWorkspaceMemberResponse>> {
    return this.governedJson(
      `/v1/workspaces/${encodeURIComponent(id)}/members`,
      "POST",
      body,
      approvalId,
    );
  }

  removeWorkspaceMember(
    id: string,
    userId: string,
    approvalId?: string,
  ): Promise<GovernedRouteResponse<DeleteAck>> {
    return this.governedJson(
      `/v1/workspaces/${encodeURIComponent(id)}/members/${encodeURIComponent(userId)}`,
      "DELETE",
      undefined,
      approvalId,
    );
  }

  adminUsers(): Promise<AdminUsersResponse> {
    return this.request("/v1/admin/users", { tolerateStatus: true });
  }

  patchUser(
    id: string,
    body: PatchUserRequest,
    approvalId?: string,
  ): Promise<GovernedRouteResponse<PatchUserResponse>> {
    return this.governedJson(
      `/v1/admin/users/${encodeURIComponent(id)}`,
      "PATCH",
      body,
      approvalId,
    );
  }

  adminInvitations(): Promise<AdminInvitationsResponse> {
    return this.request("/v1/admin/invitations", { tolerateStatus: true });
  }

  createInvitation(
    body: CreateInvitationRequest,
    approvalId?: string,
  ): Promise<GovernedRouteResponse<CreateInvitationResponse>> {
    return this.governedJson(
      "/v1/admin/invitations", "POST", body, approvalId,
    );
  }

  revokeInvitation(
    id: string,
    approvalId?: string,
  ): Promise<GovernedRouteResponse<DeleteAck>> {
    return this.governedJson(
      `/v1/admin/invitations/${encodeURIComponent(id)}`,
      "DELETE",
      undefined,
      approvalId,
    );
  }

  health(): Promise<HealthResponse> {
    return this.request("/healthz", { tolerateStatus: true });
  }

  readiness(): Promise<ReadinessResponse> {
    return this.request("/readyz", { tolerateStatus: true });
  }

  consoleOverview(limit = 20): Promise<ConsoleOverviewResponse> {
    return this.request(`/v1/console/overview?limit=${encodeURIComponent(String(limit))}`);
  }

  platformStatus(): Promise<PlatformStatusResponse> {
    return this.request("/v1/platform/status");
  }

  birthProfile(): Promise<BirthProfileResponse> {
    return this.request("/v1/birth-profile");
  }

  modelTelemetry(limit = 50): Promise<ModelTelemetryResponse> {
    return this.request(`/v1/model/telemetry?limit=${encodeURIComponent(String(limit))}`);
  }

  cost(): Promise<CostResponse> {
    return this.request("/v1/cost");
  }

  budgets(): Promise<BudgetsResponse> {
    return this.request("/v1/budgets");
  }

  upsertBudget(
    scopeType: BudgetPolicyRequest["scope_type"],
    scopeId: string,
    body: Omit<BudgetPolicyRequest, "scope_type" | "scope_id">,
    approvalId?: string,
  ): Promise<GovernedRouteResponse<StatusAck>> {
    return this.governedJson(
      `/v1/budgets/${encodeURIComponent(scopeType)}/${encodeURIComponent(scopeId)}`,
      "PUT",
      body,
      approvalId,
    );
  }

  resetBudget(
    scopeType: BudgetPolicyRequest["scope_type"],
    scopeId: string,
    _window: BudgetPolicyRequest["window"],
    approvalId?: string,
  ): Promise<GovernedRouteResponse<StatusAck>> {
    return this.governedJson(
      `/v1/budgets/${encodeURIComponent(scopeType)}/${encodeURIComponent(scopeId)}/reset`,
      "POST",
      { reason: "Worker-authorised current-window usage reset" },
      approvalId,
    );
  }

  auditSearch(params: {
    query?: string;
    actor?: string;
    verb?: string;
    run?: string;
    resource?: string;
    status?: string;
    since?: string;
    until?: string;
    security?: boolean;
    eventType?: string;
    limit?: number;
    offset?: number;
  } = {}): Promise<AuditSearchResponse> {
    const query = new URLSearchParams();
    if (params.query) query.set("query", params.query);
    if (params.actor) query.set("actor", params.actor);
    if (params.verb) query.set("verb", params.verb);
    if (params.run) query.set("run", params.run);
    if (params.resource) query.set("resource", params.resource);
    if (params.status) query.set("status", params.status);
    if (params.since) query.set("since", params.since);
    if (params.until) query.set("until", params.until);
    if (params.security) query.set("security", "1");
    if (params.eventType) query.set("event_type", params.eventType);
    if (params.limit !== undefined) query.set("limit", String(params.limit));
    if (params.offset !== undefined) query.set("offset", String(params.offset));
    return this.request(`/v1/audit/search${query.size ? `?${query}` : ""}`);
  }

  auditVerify(workspace?: string): Promise<AuditVerifyResponse> {
    const query = workspace ? `?workspace=${encodeURIComponent(workspace)}` : "";
    return this.request(`/v1/audit/verify${query}`, { tolerateStatus: true });
  }

  auditExport(): Promise<AuditExportResponse> {
    return this.json("/v1/audit/export", "POST", undefined, true);
  }

  channels(): Promise<ChannelsResponse> {
    return this.request("/v1/channels", { tolerateStatus: true });
  }

  channelGatewaySession(
    body: ChannelGatewaySessionRequest,
  ): Promise<ChannelGatewaySessionResponse> {
    return this.json("/v1/channels/gateway/session", "POST", body, true);
  }

  connectChannel(
    body: ConnectChannelRequest,
    approvalId?: string,
  ): Promise<ConnectChannelResponse> {
    return this.governedJson("/v1/channels", "POST", body, approvalId);
  }

  configureChannel(
    id: string,
    body: ConfigureChannelRequest,
    approvalId?: string,
  ): Promise<ChannelAck> {
    return this.governedJson(
      `/v1/channels/${encodeURIComponent(id)}`,
      "PATCH",
      body,
      approvalId,
    );
  }

  disconnectChannel(id: string, approvalId?: string): Promise<ChannelAck> {
    return this.governedJson(
      `/v1/channels/${encodeURIComponent(id)}`,
      "DELETE",
      undefined,
      approvalId,
    );
  }

  channelBindings(id: string): Promise<ChannelBindingsResponse> {
    return this.request(`/v1/channels/${encodeURIComponent(id)}/bindings`, {
      tolerateStatus: true,
    });
  }

  channelDeliveries(
    id: string,
    limit = 50,
  ): Promise<ChannelDeliveriesResponse> {
    const bounded = Math.max(1, Math.min(100, Math.trunc(limit)));
    return this.request(
      `/v1/channels/${encodeURIComponent(id)}/deliveries?limit=${bounded}`,
      { tolerateStatus: true },
    );
  }

  retryChannelDelivery(
    id: string,
    messageId: string,
    expectedUpdatedAt: string,
    approvalId?: string,
  ): Promise<RetryChannelDeliveryResponse> {
    return this.governedJson(
      `/v1/channels/${encodeURIComponent(id)}/deliveries/${encodeURIComponent(messageId)}/retry`,
      "POST",
      { expected_updated_at: expectedUpdatedAt },
      approvalId,
    );
  }

  pairChannel(
    id: string,
    body: PairChannelRequest,
    approvalId?: string,
  ): Promise<PairChannelResponse> {
    return this.governedJson(
      `/v1/channels/${encodeURIComponent(id)}/pair`,
      "POST",
      body,
      approvalId,
    );
  }

  channelPairFinalizations(
    id: string,
  ): Promise<ChannelPairFinalizationsResponse> {
    return this.request(
      `/v1/channels/${encodeURIComponent(id)}/pair-finalizations`,
    );
  }

  bindChannel(
    id: string,
    body: BindChannelRequest,
    approvalId?: string,
  ): Promise<BindChannelResponse> {
    return this.governedJson(
      `/v1/channels/${encodeURIComponent(id)}/bindings`,
      "POST",
      body,
      approvalId,
    );
  }

  deleteChannelBinding(
    id: string,
    bindingId: string,
    approvalId?: string,
  ): Promise<ChannelAck> {
    return this.governedJson(
      `/v1/channels/${encodeURIComponent(id)}/bindings/${encodeURIComponent(bindingId)}`,
      "DELETE",
      undefined,
      approvalId,
    );
  }

  evalCases(): Promise<EvalCasesResponse> {
    return this.request("/v1/eval/cases");
  }

  createEvalCase(
    body: CreateEvalCaseRequest,
    approvalId?: string,
  ): Promise<StatusAck> {
    return this.governedJson("/v1/eval/cases", "POST", body, approvalId);
  }

  archiveEvalCase(
    id: string,
    approvalId?: string,
  ): Promise<EvalCaseLifecycleResponse> {
    return this.governedJson(
      `/v1/eval/cases/${encodeURIComponent(id)}/archive`,
      "POST",
      {},
      approvalId,
    );
  }

  restoreEvalCase(
    id: string,
    approvalId?: string,
  ): Promise<EvalCaseLifecycleResponse> {
    return this.governedJson(
      `/v1/eval/cases/${encodeURIComponent(id)}/restore`,
      "POST",
      {},
      approvalId,
    );
  }

  runEval(body: RunEvalRequest): Promise<EvalRunResult> {
    return this.json("/v1/eval/run", "POST", body, true);
  }

  evalRuns(caseId?: string): Promise<EvalRunsResponse> {
    const query = caseId ? `?case_id=${encodeURIComponent(caseId)}` : "";
    return this.request(`/v1/eval/runs${query}`);
  }

  login(body: LoginRequest): Promise<LoginResponse> {
    return this.json("/v1/auth/login", "POST", body, true);
  }

  sessionCsrf(): Promise<SessionCsrfResponse> {
    return this.request("/v1/auth/csrf");
  }

  requestPasswordReset(
    body: PasswordResetRequest,
  ): Promise<PasswordResetRequestResponse> {
    return this.json("/v1/auth/password-reset/request", "POST", body, true);
  }

  confirmPasswordReset(
    body: PasswordResetConfirmRequest,
  ): Promise<PasswordResetConfirmResponse> {
    return this.json("/v1/auth/password-reset/confirm", "POST", body, true);
  }

  twoFactorChallenge(
    body: TwoFactorChallengeRequest,
  ): Promise<TwoFactorChallengeResponse> {
    return this.json("/v1/auth/2fa/challenge", "POST", body, true);
  }

  acceptInvite(body: AcceptInviteRequest): Promise<AcceptInviteResponse> {
    return this.json("/v1/auth/accept-invite", "POST", body, true);
  }

  twoFactorEnrollBegin(): Promise<TwoFactorEnrollBeginResponse> {
    return this.json("/v1/auth/2fa/enroll", "POST", undefined, true);
  }

  twoFactorVerifyEnroll(
    body: TwoFactorVerifyEnrollRequest,
  ): Promise<TwoFactorVerifyEnrollResponse> {
    return this.json("/v1/auth/2fa/verify-enroll", "POST", body, true);
  }

  twoFactorDisable(code: string): Promise<StatusAck> {
    return this.json("/v1/auth/2fa/disable", "POST", { code }, true);
  }

  changePassword(body: {
    current_password: string;
    new_password: string;
  }): Promise<{ status: string; reason?: string }> {
    return this.json("/v1/auth/change-password", "POST", body, true);
  }

  logout(): Promise<{ status: string; reason?: string }> {
    return this.json("/v1/auth/logout", "POST", undefined, true);
  }

  refreshSession(): Promise<{ status: string; csrf_token?: string; reason?: string }> {
    return this.json("/v1/auth/refresh", "POST", undefined, false);
  }

  cancelRun(runId: string): Promise<CancelRunResponse> {
    return this.json(`/v1/runs/${encodeURIComponent(runId)}/cancel`, "POST", undefined, true);
  }

  /** The run's durable effect ledger: each step with its honest undoability. */
  runEffects(runId: string): Promise<RunEffectsResponse> {
    return this.request<RunEffectsResponse>(`/v1/runs/${encodeURIComponent(runId)}/effects`, {});
  }

  /**
   * Revert the run's recorded effects, newest first, through the governed
   * chokepoint. An `approval_pending` outcome names the HITL request; answer
   * it, then call again with `approvals={String(seq): approval_id}` so the
   * SAME approved request releases the SAME inverse.
   */
  revertRun(runId: string, approvals?: Record<string, string>): Promise<RunRevertResponse> {
    return this.json(
      `/v1/runs/${encodeURIComponent(runId)}/revert`,
      "POST",
      approvals && Object.keys(approvals).length ? { approvals } : {},
      true,
    );
  }

  /**
   * Load the already-authorized run-event snapshot used by execution drawers.
   * Unlike the bounded chat stream, this route can include server-redacted
   * input/output values, so callers should request it only after an explicit
   * user action and render it as untrusted text.
   */
  async runEvents(runId: string, signal?: AbortSignal): Promise<ChatEvent[]> {
    const headers = new Headers({ accept: "text/event-stream" });
    for (const [key, value] of Object.entries(this.options.headers?.() ?? {})) {
      headers.set(key, value);
    }
    const accessToken = await this.options.accessToken?.();
    if (accessToken) headers.set("authorization", `Bearer ${accessToken}`);

    let response: Response;
    try {
      response = await this.fetcher(`${this.baseUrl}/v1/runs/${encodeURIComponent(runId)}/events`, {
        method: "GET",
        headers,
        credentials: this.credentials(),
        signal,
      });
    } catch (error) {
      if (signal?.aborted) return [];
      throw new BoltrigApiError(
        0,
        null,
        error instanceof Error ? error.message : "Run details failed",
      );
    }
    if (!response.ok || !response.body) {
      throw new BoltrigApiError(response.status, await parseResponse(response));
    }

    const events: ChatEvent[] = [];
    try {
      await pumpSse(response.body, (event) => events.push(event), signal);
    } catch (error) {
      if (!signal?.aborted) throw error;
    }
    return events;
  }

  hitl(): Promise<HITLListResponse> {
    return this.request("/v1/hitl");
  }

  hitlPolicy(): Promise<HitlPolicyResponse> {
    return this.request("/v1/hitl/policy");
  }

  privacyPolicy(): Promise<PrivacyPolicyResponse> {
    return this.request("/v1/privacy/policy");
  }

  backupStatus(): Promise<BackupStatusResponse> {
    return this.request("/v1/backup/status");
  }

  respondHitl(id: string, decision: string, notes = ""): Promise<RespondResult> {
    return this.json(
      `/v1/hitl/${encodeURIComponent(id)}/respond`,
      "POST",
      { decision, notes },
      true,
    );
  }

  answerQuestion(id: string, answer: string): Promise<AnswerQuestionResponse> {
    return this.json(
      `/v1/hitl/${encodeURIComponent(id)}/answer`,
      "POST",
      { answer },
      true,
    );
  }

  modelProfiles(): Promise<ModelProfilesResponse> {
    return this.request("/v1/model-profiles");
  }

  chatModelChoices(): Promise<ChatModelChoicesResponse> {
    return this.request("/v1/chat/model-choices");
  }

  bifrostModels(): Promise<BifrostModelsResponse> {
    return this.request("/v1/bifrost/models");
  }

  modelEndpoints(): Promise<ModelEndpointsResponse> {
    return this.request("/v1/model-endpoints");
  }

  modelPolicy(): Promise<ModelPolicyResponse> {
    return this.request("/v1/model-policy");
  }

  spawnRules(): Promise<SpawnRulePolicyResponse> {
    return this.request("/v1/spawn-rules");
  }

  simulateSpawnRules(
    intentTags: string[],
  ): Promise<SpawnRuleSimulationResponse> {
    return this.json(
      "/v1/spawn-rules/simulate",
      "POST",
      { intent_tags: intentTags },
      true,
    );
  }

  modelEndpoint(id: string): Promise<ModelEndpointResponse> {
    return this.request(`/v1/model-endpoints/${encodeURIComponent(id)}`);
  }

  retireModelEndpoint(
    id: string,
    approvalId?: string,
  ): Promise<ModelEndpointLifecycleResponse> {
    return this.governedJson(
      `/v1/model-endpoints/${encodeURIComponent(id)}/retire`,
      "POST",
      {},
      approvalId,
    );
  }

  restoreModelEndpoint(
    id: string,
    approvalId?: string,
  ): Promise<ModelEndpointLifecycleResponse> {
    return this.governedJson(
      `/v1/model-endpoints/${encodeURIComponent(id)}/restore`,
      "POST",
      {},
      approvalId,
    );
  }

  capabilities(): Promise<CapabilitiesResponse> {
    return this.request("/v1/capabilities");
  }

  agentCapabilities(): Promise<AgentCapabilitiesResponse> {
    return this.request("/v1/agent-capabilities");
  }

  permanentFleet(): Promise<PermanentFleetResponse> {
    return this.request("/v1/permanent-fleet");
  }

  applyPermanentFleet(
    hierarchy: PermanentFleetHierarchy,
    approvalId?: string,
  ): Promise<PermanentFleetApplyResponse> {
    return this.governedJson(
      "/v1/permanent-fleet",
      "PUT",
      { hierarchy },
      approvalId,
    );
  }

  retireAgentCapability(
    name: string,
    approvalId?: string,
  ): Promise<CapabilityLifecycleResponse> {
    return this.governedJson(
      `/v1/agent-capabilities/${encodeURIComponent(name)}/retire`,
      "POST",
      {},
      approvalId,
    );
  }

  restoreAgentCapability(
    name: string,
    approvalId?: string,
  ): Promise<CapabilityLifecycleResponse> {
    return this.governedJson(
      `/v1/agent-capabilities/${encodeURIComponent(name)}/restore`,
      "POST",
      {},
      approvalId,
    );
  }

  capabilityChangelog(): Promise<CapabilityChangelogResponse> {
    return this.request("/v1/capabilities/changelog");
  }

  async invoke(body: InvokeRequest): Promise<InvokeResult> {
    try {
      return await this.json("/v1/invoke", "POST", body);
    } catch (error) {
      if (!(error instanceof BoltrigApiError)) throw error;
      const envelope = error.body;
      if (envelope !== null && typeof envelope === "object" && !Array.isArray(envelope)) {
        const status = (envelope as Record<string, unknown>).status;
        if (
          status === "pending_human"
          && typeof (envelope as Record<string, unknown>).hitl_request_id === "string"
        ) {
          return envelope as InvokeResult;
        }
        if (
          (status === "denied" || status === "error" || status === "unavailable")
          && typeof (envelope as Record<string, unknown>).reason === "string"
        ) {
          return envelope as InvokeResult;
        }
        if (status === "degraded" && "output" in envelope) {
          return envelope as InvokeResult;
        }
      }
      const detail = envelope !== null && typeof envelope === "object" && !Array.isArray(envelope)
        ? (envelope as Record<string, unknown>).detail
        : undefined;
      const reason = typeof detail === "string"
        ? detail
        : error.status === 0
          ? error.message
          : `Invocation request failed (${error.status}).`;
      if (error.status === 401 || error.status === 403) {
        return { status: "denied", reason };
      }
      if (error.status === 0 || error.status === 502 || error.status === 503 || error.status === 504) {
        return { status: "unavailable", reason };
      }
      return { status: "error", reason };
    }
  }

  invokeApprovalState(requestId: string): Promise<InvokeApprovalStateResponse> {
    return this.request(
      `/v1/invoke/approvals/${encodeURIComponent(requestId)}`,
    );
  }

  spawn(body: SpawnRequest): Promise<SpawnResult> {
    return this.json("/v1/spawn", "POST", body, true);
  }

  runs(params: {
    limit?: number;
    cursor?: string;
    owner?: string;
    onBehalfOf?: string;
    label?: string;
    source?: string;
    externalRef?: string;
  } = {}): Promise<RunsResponse> {
    const query = new URLSearchParams();
    if (params.limit != null) query.set("limit", String(params.limit));
    if (params.cursor) query.set("cursor", params.cursor);
    if (params.owner) query.set("owner", params.owner);
    if (params.onBehalfOf) query.set("on_behalf_of", params.onBehalfOf);
    if (params.label) query.set("label", params.label);
    if (params.source) query.set("source", params.source);
    if (params.externalRef) query.set("external_ref", params.externalRef);
    return this.request(`/v1/runs${query.size ? `?${query}` : ""}`);
  }

  runTopology(runId: string): Promise<RunTopologyResponse> {
    return this.request(`/v1/runs/${encodeURIComponent(runId)}/topology`);
  }

  auditTree(runId: string): Promise<AuditTreeResponse> {
    return this.request(`/v1/audit/tree/${encodeURIComponent(runId)}`);
  }

  work(
    status?: WorkStatus,
    params: { limit?: number; cursor?: string } = {},
  ): Promise<WorkResponse> {
    const query = new URLSearchParams();
    if (status) query.set("status", status);
    if (params.limit != null) query.set("limit", String(params.limit));
    if (params.cursor) query.set("cursor", params.cursor);
    return this.request(`/v1/work${query.size ? `?${query}` : ""}`);
  }

  workDetail(id: string): Promise<WorkDetailResponse> {
    return this.request(`/v1/work/${encodeURIComponent(id)}`);
  }

  createWork(
    body: CreateWorkRequest,
    approvalId?: string,
  ): Promise<WorkMutationResult> {
    return this.governedJson("/v1/work", "POST", body, approvalId);
  }

  assignWork(
    id: string,
    ownerMember: string | null,
    idempotencyKey?: string,
    approvalId?: string,
  ): Promise<WorkMutationResult> {
    return this.governedJson(
      `/v1/work/${encodeURIComponent(id)}/assignment`,
      "PATCH",
      { owner_member: ownerMember, idempotency_key: idempotencyKey },
      approvalId,
    );
  }

  transitionWork(
    id: string,
    status: WorkStatus,
    idempotencyKey?: string,
    approvalId?: string,
  ): Promise<WorkMutationResult> {
    return this.governedJson(
      `/v1/work/${encodeURIComponent(id)}/status`,
      "PATCH",
      { status, idempotency_key: idempotencyKey },
      approvalId,
    );
  }

  reparentWork(
    id: string,
    parentId: string | null,
    idempotencyKey?: string,
    approvalId?: string,
  ): Promise<WorkMutationResult> {
    return this.governedJson(
      `/v1/work/${encodeURIComponent(id)}/parent`,
      "PATCH",
      { parent_id: parentId, idempotency_key: idempotencyKey },
      approvalId,
    );
  }

  knowledgeAssets(limit = 50, offset = 0): Promise<KnowledgeAssetsResponse> {
    const query = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    });
    return this.request(`/v1/knowledge/assets?${query}`);
  }

  knowledgeAsset(id: string): Promise<KnowledgeAssetDetailResponse> {
    return this.request(`/v1/knowledge/assets/${encodeURIComponent(id)}`);
  }

  knowledgeSearch(query: string, limit = 12): Promise<KnowledgeSearchResponse> {
    return this.json("/v1/knowledge/search", "POST", { query, limit });
  }

  knowledgeProviders(): Promise<KnowledgeProvidersResponse> {
    return this.request("/v1/knowledge/providers");
  }

  setKnowledgeProvider(
    providerId: string,
    enabled: boolean,
    approvalId?: string,
  ): Promise<KnowledgeMutationResponse> {
    return this.governedJson(
      `/v1/knowledge/providers/${encodeURIComponent(providerId)}`,
      "POST",
      { enabled },
      approvalId,
    );
  }

  eraseKnowledgeAsset(
    assetId: string,
    approvalId?: string,
  ): Promise<KnowledgeMutationResponse> {
    return this.governedJson(
      `/v1/knowledge/assets/${encodeURIComponent(assetId)}`,
      "DELETE",
      undefined,
      approvalId,
    );
  }

  async uploadKnowledge(file: File, title = ""): Promise<KnowledgeUploadResponse> {
    const begun = await this.json<{ upload_id: string }>(
      "/v1/knowledge/uploads",
      "POST",
      {
        title: title.trim() || file.name,
        filename: file.name,
        media_type: file.type || "application/octet-stream",
      },
    );
    await this.raw(`/v1/knowledge/uploads/${encodeURIComponent(begun.upload_id)}`, {
      method: "PUT",
      headers: { "content-type": file.type || "application/octet-stream" },
      body: file,
    });
    return this.json(
      `/v1/knowledge/uploads/${encodeURIComponent(begun.upload_id)}/commit`,
      "POST",
    );
  }

  async knowledgeOriginal(assetId: string): Promise<Blob> {
    const response = await this.raw(
      `/v1/knowledge/assets/${encodeURIComponent(assetId)}/original`,
    );
    return response.blob();
  }

  memoryFacts(params: { kind?: string; limit?: number } = {}): Promise<MemoryFactsResponse> {
    const query = new URLSearchParams();
    if (params.kind) query.set("kind", params.kind);
    if (params.limit !== undefined) query.set("limit", String(params.limit));
    const suffix = query.size ? `?${query}` : "";
    return this.request(`/v1/memory/facts${suffix}`);
  }

  memoryFact(factId: string): Promise<MemoryFactResponse> {
    return this.request(`/v1/memory/facts/${encodeURIComponent(factId)}`);
  }

  memoryRecall(body: MemoryRecallRequest): Promise<MemoryRecallResponse> {
    return this.json("/v1/memory/recall", "POST", body, true);
  }

  memoryRemember(
    body: MemoryRememberRequest,
    approvalId?: string,
  ): Promise<MemoryRememberResponse> {
    return this.governedJson("/v1/memory/remember", "POST", body, approvalId);
  }

  memoryImprove(
    body: MemoryImproveRequest,
    approvalId?: string,
  ): Promise<MemoryImproveResponse> {
    return this.governedJson("/v1/memory/improve", "POST", body, approvalId);
  }

  memoryForget(
    body: MemoryForgetRequest,
    approvalId?: string,
  ): Promise<MemoryForgetResponse> {
    return this.governedJson("/v1/memory/forget", "POST", body, approvalId);
  }

  memoryIngest(
    body: MemoryIngestRequest,
    approvalId?: string,
  ): Promise<MemoryIngestResponse> {
    return this.governedJson("/v1/memory/ingest", "POST", body, approvalId);
  }

  memoryIngestions(): Promise<MemoryIngestionsResponse> {
    return this.request("/v1/memory/ingestions", { tolerateStatus: true });
  }

  // Typed memory planes (decision 0029): the candidate queue and one slot's
  // version history. Review is high-consequence: it may pend for an approval
  // (hitl_request_id) which the caller then answers and replays with
  // approvalId.
  memoryCandidates(params: { limit?: number } = {}): Promise<MemoryCandidatesResponse> {
    const query = new URLSearchParams();
    if (params.limit !== undefined) query.set("limit", String(params.limit));
    const suffix = query.size ? `?${query}` : "";
    return this.request(`/v1/memory/candidates${suffix}`, { tolerateStatus: true });
  }

  memoryCandidateReview(
    candidateId: string,
    body: MemoryCandidateReviewRequest,
    approvalId?: string,
  ): Promise<MemoryCandidateReviewResponse> {
    return this.governedJson(
      `/v1/memory/candidates/${encodeURIComponent(candidateId)}/review`,
      "POST",
      body,
      approvalId,
    );
  }

  memoryTimeline(params: {
    subject_type?: string;
    subject_id?: string;
    predicate?: string;
    owner_scope?: string;
    memory_key?: string;
    limit?: number;
  }): Promise<MemoryTimelineResponse> {
    const query = new URLSearchParams();
    if (params.memory_key) query.set("memory_key", params.memory_key);
    if (params.subject_type) query.set("subject_type", params.subject_type);
    if (params.subject_id) query.set("subject_id", params.subject_id);
    if (params.predicate) query.set("predicate", params.predicate);
    if (params.owner_scope) query.set("owner_scope", params.owner_scope);
    if (params.limit !== undefined) query.set("limit", String(params.limit));
    return this.request(`/v1/memory/timeline?${query}`, { tolerateStatus: true });
  }

  skills(): Promise<SkillsResponse> {
    return this.request("/v1/skills");
  }

  skill(id: string): Promise<SkillResponse> {
    return this.request(`/v1/skills/${encodeURIComponent(id)}`);
  }

  archiveSkill(
    id: string,
    approvalId?: string,
  ): Promise<AuthoredDefinitionLifecycleResponse> {
    return this.governedJson(
      `/v1/skills/${encodeURIComponent(id)}/archive`,
      "POST",
      {},
      approvalId,
    );
  }

  restoreSkill(
    id: string,
    approvalId?: string,
  ): Promise<AuthoredDefinitionLifecycleResponse> {
    return this.governedJson(
      `/v1/skills/${encodeURIComponent(id)}/restore`,
      "POST",
      {},
      approvalId,
    );
  }

  upsertSkill(
    body: UpsertSkillRequest,
    approvalId?: string,
  ): Promise<GovernedRouteResponse<StatusAck>> {
    return this.governedJson("/v1/skills", "POST", body, approvalId);
  }

  testSpawn(skillId: string, body: TestSpawnRequest): Promise<SpawnResult> {
    return this.json(
      `/v1/skills/${encodeURIComponent(skillId)}/test-spawn`,
      "POST",
      body,
      true,
    );
  }

  upsertNoun(
    body: UpsertNounRequest,
    approvalId?: string,
  ): Promise<GovernedRouteResponse<StatusAck>> {
    return this.governedJson("/v1/nouns", "POST", body, approvalId);
  }

  noun(id: string): Promise<NounResponse> {
    return this.request(`/v1/nouns/${encodeURIComponent(id)}`);
  }

  nouns(): Promise<NounsResponse> {
    return this.request("/v1/nouns");
  }

  archiveNoun(
    id: string,
    approvalId?: string,
  ): Promise<AuthoredDefinitionLifecycleResponse> {
    return this.governedJson(
      `/v1/nouns/${encodeURIComponent(id)}/archive`,
      "POST",
      {},
      approvalId,
    );
  }

  restoreNoun(
    id: string,
    approvalId?: string,
  ): Promise<AuthoredDefinitionLifecycleResponse> {
    return this.governedJson(
      `/v1/nouns/${encodeURIComponent(id)}/restore`,
      "POST",
      {},
      approvalId,
    );
  }

  upsertVerb(
    body: UpsertVerbRequest,
    approvalId?: string,
  ): Promise<GovernedRouteResponse<StatusAck>> {
    return this.governedJson("/v1/verbs", "POST", body, approvalId);
  }

  verb(id: string): Promise<VerbResponse> {
    return this.request(`/v1/verbs/${encodeURIComponent(id)}`);
  }

  verbs(): Promise<VerbsResponse> {
    return this.request("/v1/verbs");
  }

  archiveVerb(
    id: string,
    approvalId?: string,
  ): Promise<AuthoredDefinitionLifecycleResponse> {
    return this.governedJson(
      `/v1/verbs/${encodeURIComponent(id)}/archive`,
      "POST",
      {},
      approvalId,
    );
  }

  restoreVerb(
    id: string,
    approvalId?: string,
  ): Promise<AuthoredDefinitionLifecycleResponse> {
    return this.governedJson(
      `/v1/verbs/${encodeURIComponent(id)}/restore`,
      "POST",
      {},
      approvalId,
    );
  }

  setBinding(
    verbId: string,
    body: SetBindingRequest,
    approvalId?: string,
  ): Promise<GovernedRouteResponse<StatusAck>> {
    return this.governedJson(
      `/v1/verbs/${encodeURIComponent(verbId)}/binding`,
      "POST",
      body,
      approvalId,
    );
  }

  generateAdapter(body: GenerateAdapterRequest): Promise<GenerateAdapterResponse> {
    return this.json("/v1/adapters/generate", "POST", body, true);
  }

  adapterSource(adapterId: string): Promise<AdapterSourceResponse> {
    return this.request(
      `/v1/adapters/${encodeURIComponent(adapterId)}/source`,
      { tolerateStatus: true },
    );
  }

  activateAdapter(
    adapterId: string,
    body: ActivateAdapterRequest = {},
    approvalId?: string,
  ): Promise<GovernedRouteResponse<ActivateAdapterResponse>> {
    return this.governedJson(
      `/v1/adapters/${encodeURIComponent(adapterId)}/activate`,
      "POST",
      body,
      approvalId,
    );
  }

  deactivateAdapter(
    adapterId: string,
    approvalId?: string,
  ): Promise<GovernedRouteResponse<ActivateAdapterResponse>> {
    return this.governedJson(
      `/v1/adapters/${encodeURIComponent(adapterId)}/deactivate`,
      "POST",
      undefined,
      approvalId,
    );
  }

  deleteAdapter(
    adapterId: string,
    approvalId?: string,
  ): Promise<GovernedRouteResponse<StatusAck>> {
    return this.governedJson(
      `/v1/adapters/${encodeURIComponent(adapterId)}`,
      "DELETE",
      undefined,
      approvalId,
    );
  }

  registerMcpServer(body: RegisterMcpRequest): Promise<StatusAck> {
    return this.json("/v1/mcp/servers", "POST", body, true);
  }

  mcpServers(): Promise<McpServersResponse> {
    return this.request("/v1/mcp/servers");
  }

  mcpServer(serverId: string): Promise<McpServerDetailResponse> {
    return this.request(`/v1/mcp/servers/${encodeURIComponent(serverId)}`);
  }

  updateMcpServer(
    serverId: string,
    body: UpdateMcpServerRequest,
    approvalId?: string,
  ): Promise<GovernedRouteResponse<UpdateMcpServerResponse>> {
    return this.governedJson(
      `/v1/mcp/servers/${encodeURIComponent(serverId)}`,
      "PUT",
      body,
      approvalId,
    );
  }

  deleteMcpServer(
    serverId: string,
    approvalId?: string,
  ): Promise<GovernedRouteResponse<DeleteMcpServerResponse>> {
    return this.governedJson(
      `/v1/mcp/servers/${encodeURIComponent(serverId)}`,
      "DELETE",
      undefined,
      approvalId,
    );
  }

  activateMcpServer(
    serverId: string,
    approvalId?: string,
  ): Promise<GovernedRouteResponse<ActivateAdapterResponse>> {
    return this.governedJson(
      `/v1/mcp/servers/${encodeURIComponent(serverId)}/activate`,
      "POST",
      undefined,
      approvalId,
    );
  }

  deactivateMcpServer(
    serverId: string,
    approvalId?: string,
  ): Promise<GovernedRouteResponse<ActivateAdapterResponse>> {
    return this.governedJson(
      `/v1/mcp/servers/${encodeURIComponent(serverId)}/deactivate`,
      "POST",
      undefined,
      approvalId,
    );
  }

  probeMcpServer(
    serverId: string,
    approvalId?: string,
  ): Promise<GovernedRouteResponse<ActivateAdapterResponse>> {
    return this.governedJson(
      `/v1/mcp/servers/${encodeURIComponent(serverId)}/probe`,
      "POST",
      undefined,
      approvalId,
    );
  }

  retireMcpServer(
    serverId: string,
    approvalId?: string,
  ): Promise<GovernedRouteResponse<ActivateAdapterResponse>> {
    return this.governedJson(
      `/v1/mcp/servers/${encodeURIComponent(serverId)}/retire`,
      "POST",
      undefined,
      approvalId,
    );
  }

  restoreMcpServer(
    serverId: string,
    approvalId?: string,
  ): Promise<GovernedRouteResponse<ActivateAdapterResponse>> {
    return this.governedJson(
      `/v1/mcp/servers/${encodeURIComponent(serverId)}/restore`,
      "POST",
      undefined,
      approvalId,
    );
  }

  adapters(): Promise<AdapterInventoryResponse> {
    return this.request("/v1/adapters");
  }

  workflows(): Promise<WorkflowsResponse> {
    return this.request("/v1/workflows");
  }

  workflow(id: string): Promise<WorkflowDetail> {
    return this.request(`/v1/workflows/${encodeURIComponent(id)}`);
  }

  upsertWorkflow(
    body: UpsertWorkflowRequest,
    approvalId?: string,
  ): Promise<GovernedRouteResponse<StatusAck>> {
    return this.governedJson("/v1/workflows", "POST", body, approvalId);
  }

  scheduleWorkflow(
    id: string,
    body: ScheduleWorkflowRequest,
    approvalId?: string,
  ): Promise<ScheduleWorkflowResponse> {
    return this.governedJson(
      `/v1/workflows/${encodeURIComponent(id)}/schedule`,
      "POST",
      body,
      approvalId,
    );
  }

  workflowScheduleOccurrences(
    id: string,
    limit = 25,
  ): Promise<WorkflowScheduleOccurrencesResponse> {
    const bounded = Math.max(1, Math.min(Math.trunc(limit), 50));
    return this.request(
      `/v1/workflows/${encodeURIComponent(id)}/schedule/occurrences?limit=${bounded}`,
    );
  }

  retryWorkflowScheduleOccurrence(
    id: string,
    scheduledFor: string,
    runId: string,
    approvalId?: string,
  ): Promise<RetryWorkflowScheduleOccurrenceResponse> {
    return this.json(
      `/v1/workflows/${encodeURIComponent(id)}/schedule/occurrences/${encodeURIComponent(scheduledFor)}/retry`,
      "POST",
      {
        run_id: runId,
        ...(approvalId ? { approval_id: approvalId } : {}),
      },
      true,
    );
  }

  unscheduleWorkflow(
    id: string,
    approvalId?: string,
  ): Promise<WorkflowLifecycleResponse> {
    return this.governedJson(
      `/v1/workflows/${encodeURIComponent(id)}/unschedule`,
      "POST",
      {},
      approvalId,
    );
  }

  archiveWorkflow(
    id: string,
    approvalId?: string,
  ): Promise<WorkflowLifecycleResponse> {
    return this.governedJson(
      `/v1/workflows/${encodeURIComponent(id)}/archive`,
      "POST",
      {},
      approvalId,
    );
  }

  restoreWorkflow(
    id: string,
    approvalId?: string,
  ): Promise<WorkflowLifecycleResponse> {
    return this.governedJson(
      `/v1/workflows/${encodeURIComponent(id)}/restore`,
      "POST",
      {},
      approvalId,
    );
  }

  triggerWorkflow(
    id: string,
    body: TriggerWorkflowRequest = {},
    approvalId?: string,
  ): Promise<GovernedRouteResponse<WorkflowRunDescriptor>> {
    return this.governedJson(
      `/v1/workflows/${encodeURIComponent(id)}/trigger`,
      "POST",
      body,
      approvalId,
    );
  }

  executeWorkflow(
    id: string,
    inputs: Record<string, unknown> = {},
    approvalId?: string,
  ): Promise<GovernedRouteResponse<WorkflowRunRecord>> {
    return this.governedJson(
      `/v1/workflows/${encodeURIComponent(id)}/execute`,
      "POST",
      { inputs },
      approvalId,
    );
  }

  workflowRuns(id: string): Promise<WorkflowRunsResponse> {
    return this.request(`/v1/workflows/${encodeURIComponent(id)}/runs`);
  }

  workflowStats(): Promise<WorkflowStatsResponse> {
    return this.request("/v1/workflow-stats");
  }

  workflowTriggers(id: string): Promise<WorkflowTriggersResponse> {
    return this.request(`/v1/workflows/${encodeURIComponent(id)}/triggers`);
  }

  workflowTriggerFinalizations(
    id: string,
  ): Promise<WorkflowTriggerFinalizationsResponse> {
    return this.request(
      `/v1/workflows/${encodeURIComponent(id)}/trigger-finalizations`,
    );
  }

  createWorkflowTrigger(
    id: string,
    body: CreateWorkflowTriggerRequest,
    approvalId?: string,
  ): Promise<WorkflowTriggerMutationResponse> {
    return this.json(
      `/v1/workflows/${encodeURIComponent(id)}/triggers`,
      "POST",
      { ...body, ...(approvalId ? { approval_id: approvalId } : {}) },
      true,
    );
  }

  enableWorkflowTrigger(
    workflowId: string,
    triggerId: string,
    approvalId?: string,
  ): Promise<WorkflowTriggerMutationResponse> {
    return this.workflowTriggerAction(
      workflowId, triggerId, "enable", approvalId,
    );
  }

  disableWorkflowTrigger(
    workflowId: string,
    triggerId: string,
    approvalId?: string,
  ): Promise<WorkflowTriggerMutationResponse> {
    return this.workflowTriggerAction(
      workflowId, triggerId, "disable", approvalId,
    );
  }

  rotateWorkflowTriggerSecret(
    workflowId: string,
    triggerId: string,
    approvalId?: string,
  ): Promise<WorkflowTriggerMutationResponse> {
    return this.workflowTriggerAction(
      workflowId, triggerId, "rotate", approvalId,
    );
  }

  workflowTriggerDeliveries(
    workflowId: string,
    triggerId: string,
  ): Promise<WorkflowTriggerDeliveriesResponse> {
    return this.request(
      `/v1/workflows/${encodeURIComponent(workflowId)}/triggers/` +
      `${encodeURIComponent(triggerId)}/deliveries`,
    );
  }

  private workflowTriggerAction(
    workflowId: string,
    triggerId: string,
    action: "enable" | "disable" | "rotate",
    approvalId?: string,
  ): Promise<WorkflowTriggerMutationResponse> {
    return this.json(
      `/v1/workflows/${encodeURIComponent(workflowId)}/triggers/` +
      `${encodeURIComponent(triggerId)}/${action}`,
      "POST",
      approvalId ? { approval_id: approvalId } : {},
      true,
    );
  }

  artifacts(
    options?: string | ArtifactListOptions,
  ): Promise<ArtifactsResponse> {
    const normalized = typeof options === "string"
      ? { conversationId: options }
      : options ?? {};
    const query = new URLSearchParams();
    if (normalized.conversationId) {
      query.set("conversation_id", normalized.conversationId);
    }
    if (normalized.limit !== undefined) {
      query.set("limit", String(normalized.limit));
    }
    if (normalized.cursor) query.set("cursor", normalized.cursor);
    const suffix = query.size ? `?${query.toString()}` : "";
    return this.request(`/v1/artifacts${suffix}`);
  }

  artifact(id: string): Promise<Artifact> {
    return this.request(`/v1/artifacts/${encodeURIComponent(id)}`);
  }

  artifactDownloadUrl(id: string): string {
    return `${this.baseUrl}/v1/artifacts/${encodeURIComponent(id)}/download`;
  }

  async downloadArtifact(id: string, signal?: AbortSignal): Promise<Uint8Array> {
    const headers = new Headers();
    for (const [key, value] of Object.entries(this.options.headers?.() ?? {})) {
      headers.set(key, value);
    }
    const accessToken = await this.options.accessToken?.();
    if (accessToken) headers.set("authorization", `Bearer ${accessToken}`);
    let response: Response;
    try {
      response = await this.fetcher(this.artifactDownloadUrl(id), {
        headers,
        credentials: this.credentials(),
        signal,
      });
    } catch (error) {
      throw new BoltrigApiError(
        0,
        null,
        error instanceof Error ? error.message : "Artifact download failed",
      );
    }
    if (!response.ok) {
      throw new BoltrigApiError(response.status, await parseResponse(response));
    }
    return new Uint8Array(await response.arrayBuffer());
  }

  devices(): Promise<DevicesResponse> {
    return this.request("/v1/devices");
  }

  deviceLeases(deviceId: string): Promise<OwnerDeviceLeasesResponse> {
    return this.request(
      `/v1/devices/${encodeURIComponent(deviceId)}/leases`,
    );
  }

  requestDeviceFileListLease(
    deviceId: string,
    rootId: string,
    body: DeviceFileListRequest,
    options: DeviceLeaseInvokeOptions = {},
  ): Promise<InvokeResult> {
    return this.invoke({
      noun: "device",
      verb: "device.file.list",
      params: {
        device_id: deviceId,
        root_id: rootId,
        relative_path: body.relative_path,
        max_entries: body.max_entries,
      },
      ...(options.approvalId ? { approval_id: options.approvalId } : {}),
      ...(options.idempotencyKey
        ? { idempotency_key: options.idempotencyKey }
        : {}),
      ...(options.context ? { context: options.context } : {}),
    });
  }

  startDeviceEnrollment(label: string): Promise<DeviceEnrollmentStart | StatusAck> {
    return this.json("/v1/devices/enrollment/start", "POST", { label }, true);
  }

  createDeviceRoot(
    deviceId: string,
    body: CreateDeviceRootRequest,
  ): Promise<DeviceRootResponse | StatusAck> {
    return this.json(
      `/v1/devices/${encodeURIComponent(deviceId)}/roots`,
      "POST",
      body,
      true,
    );
  }

  revokeDeviceRoot(deviceId: string, rootId: string): Promise<StatusAck> {
    return this.json(
      `/v1/devices/${encodeURIComponent(deviceId)}/roots/${encodeURIComponent(rootId)}`,
      "DELETE",
      undefined,
      true,
    );
  }

  revokeDevice(deviceId: string): Promise<StatusAck> {
    return this.json(`/v1/devices/${encodeURIComponent(deviceId)}`, "DELETE", undefined, true);
  }

  addons(): Promise<AddonsResponse> {
    return this.request("/v1/addons");
  }

  /** Unauthenticated: the sign-in screen renders before anyone has a session. */
  branding(): Promise<BrandingResponse> {
    return this.request("/v1/branding");
  }

  integrationCatalogue(): Promise<IntegrationCatalogueResponse> {
    return this.request("/v1/integrations/catalogue");
  }

  integrationConnections(): Promise<IntegrationConnectionsResponse> {
    return this.request("/v1/integrations/connections");
  }

  /**
   * The capability review queue. `status` filters it; an unknown status returns
   * an empty list with a reason rather than falling through to everything,
   * because "show me the rejected ones" must never answer with all of them.
   */
  capabilityBindings(
    status?: CapabilityBindingStatus,
  ): Promise<CapabilityBindingsResponse> {
    const query = status ? `?status=${encodeURIComponent(status)}` : "";
    return this.request(`/v1/capability-bindings${query}`);
  }

  /** Which capabilities exist, derived from the bindings that claim them. */
  capabilityCatalogue(): Promise<CapabilityCatalogueResponse> {
    return this.request("/v1/capability-catalogue");
  }

  routingPolicies(capabilityId?: string): Promise<RoutingPoliciesResponse> {
    const query = capabilityId
      ? `?capability_id=${encodeURIComponent(capabilityId)}`
      : "";
    return this.request(`/v1/routing-policies${query}`);
  }

  integrationConnectionHealth(id: string): Promise<IntegrationConnectionResponse> {
    return this.request(`/v1/integrations/connections/${encodeURIComponent(id)}/health`);
  }

  startIntegrationOAuth(id: string): Promise<IntegrationOAuthStartResponse> {
    return this.json(`/v1/integrations/${encodeURIComponent(id)}/oauth/start`, "POST");
  }

  submitIntegrationSecret(
    id: string,
    body: IntegrationSecretSubmission,
  ): Promise<IntegrationSetupResponse> {
    return this.json(`/v1/integrations/${encodeURIComponent(id)}/secrets`, "POST", body);
  }

  disconnectIntegration(
    id: string,
    approvalId?: string,
  ): Promise<GovernedRouteResponse<StatusAck>> {
    return this.governedJson(
      `/v1/integrations/connections/${encodeURIComponent(id)}`,
      "DELETE",
      undefined,
      approvalId,
    );
  }

  /** Every OTHER member's personal connections. Author roles only; 403 otherwise. */
  memberIntegrationConnections(): Promise<MemberIntegrationConnectionsResponse> {
    return this.request("/v1/integrations/member-connections");
  }

  revokeMemberIntegrationConnection(
    id: string,
    approvalId?: string,
  ): Promise<GovernedRouteResponse<StatusAck>> {
    return this.governedJson(
      `/v1/integrations/member-connections/${encodeURIComponent(id)}`,
      "DELETE",
      undefined,
      approvalId,
    );
  }

  async createCall(body: CallCreateRequest): Promise<CallCreateResponse> {
    const result = await this.json<unknown>("/v1/calls", "POST", body, true);
    if (isCallCreateResponse(result)) return result;
    return {
      call: {
        id: "realtime-unavailable",
        conversation_id: body.conversation_id ?? "",
        status: "realtime_unavailable",
        provider_class: "realtime_voice",
        participants: [],
        unavailable_reason: "realtime_call_service_unavailable",
      },
      text_continuation_conversation_id: body.conversation_id,
    };
  }

  async endCall(id: string): Promise<RealtimeCall> {
    const result = await this.json<{ call: RealtimeCall }>(
      `/v1/calls/${encodeURIComponent(id)}/end`,
      "POST",
    );
    return result.call;
  }

  refreshCallMedia(id: string): Promise<CallCreateResponse> {
    return this.json(`/v1/calls/${encodeURIComponent(id)}/media-token`, "POST");
  }

  reopenCall(id: string): Promise<CallCreateResponse> {
    return this.json(`/v1/calls/${encodeURIComponent(id)}/reopen`, "POST");
  }

  calls(limit = 50, conversationId?: string): Promise<CallsResponse> {
    const params = new URLSearchParams({ limit: String(limit) });
    if (conversationId) params.set("conversation_id", conversationId);
    return this.request(`/v1/calls?${params.toString()}`);
  }

  currentCall(conversationId?: string): Promise<CurrentCallResponse> {
    const suffix = conversationId
      ? `?conversation_id=${encodeURIComponent(conversationId)}`
      : "";
    return this.request(`/v1/calls/current${suffix}`);
  }

  getCall(id: string): Promise<{ call: RealtimeCall }> {
    return this.request(`/v1/calls/${encodeURIComponent(id)}`);
  }

  callEvents(id: string): Promise<CallEventsResponse> {
    return this.request(`/v1/calls/${encodeURIComponent(id)}/events`);
  }

  callUsage(id: string): Promise<CallUsageResponse> {
    return this.request(`/v1/calls/${encodeURIComponent(id)}/usage`);
  }

  async streamChat(
    body: ChatRequest,
    onEvent: (event: ChatEvent) => void,
    signal?: AbortSignal,
  ): Promise<ChatQueued | void> {
    const headers = new Headers({ accept: "text/event-stream", "content-type": "application/json" });
    for (const [key, value] of Object.entries(this.options.headers?.() ?? {})) {
      headers.set(key, value);
    }
    const accessToken = await this.options.accessToken?.();
    if (accessToken) headers.set("authorization", `Bearer ${accessToken}`);
    const csrf = this.csrf();
    if (csrf) headers.set("x-boltrig-csrf", csrf);

    let response: Response;
    try {
      response = await this.fetcher(`${this.baseUrl}/v1/chat`, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        credentials: this.credentials(),
        signal,
      });
    } catch (error) {
      if (signal?.aborted) return;
      throw new BoltrigApiError(
        0,
        null,
        error instanceof Error ? error.message : "Chat connection failed",
      );
    }
    if (response.status === 202) return (await parseResponse(response)) as ChatQueued;
    if (!response.ok || !response.body) {
      throw new BoltrigApiError(response.status, await parseResponse(response));
    }
    try {
      await pumpSse(response.body, onEvent, signal);
    } catch (error) {
      if (!signal?.aborted) throw error;
    }
  }
}

function isCallCreateResponse(value: unknown): value is CallCreateResponse {
  if (!value || typeof value !== "object" || !("call" in value)) return false;
  const call = (value as { call?: unknown }).call;
  return Boolean(
    call
    && typeof call === "object"
    && "status" in call
    && typeof (call as { status?: unknown }).status === "string",
  );
}

export async function pumpSse(
  stream: ReadableStream<Uint8Array>,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  await pumpSseFrames<ChatEvent>(
    stream,
    (event) => {
      if (event.type !== "heartbeat") onEvent(event);
    },
    signal,
  );
}

async function pumpSseFrames<T>(
  stream: ReadableStream<Uint8Array>,
  onFrame: (frame: T) => void,
  signal?: AbortSignal,
): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (!signal?.aborted) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() ?? "";
      for (const frame of frames) {
        const data = frame
          .split(/\r?\n/)
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        if (!data) continue;
        onFrame(JSON.parse(data) as T);
      }
      if (done) break;
    }
  } finally {
    reader.releaseLock();
  }
}
