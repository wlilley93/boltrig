// Core runtime API surface: health, capabilities, invoke, spawn, work, HITL,
// conversations, and run lifecycle.

import { request } from "@/api/transport";
import type {
  AnswerQuestionResponse,
  AuditTreeResponse,
  CancelRunResponse,
  CapabilityChangelogResponse,
  CapabilitiesResponse,
  ConversationResponse,
  ConversationSearchResponse,
  ConversationsPageResponse,
  ConversationsResponse,
  HealthResponse,
  HITLListResponse,
  InvokeRequest,
  InvokeResult,
  ModelEndpointsResponse,
  ReadinessResponse,
  RegenerateResponse,
  RespondResult,
  SpawnRequest,
  WorkResponse,
  WorkDetailResponse,
  WorkStatus,
} from "@/api/types";

export const coreApi = {
  health(): Promise<HealthResponse> {
    return request<HealthResponse>("/healthz");
  },

  readiness(): Promise<ReadinessResponse> {
    return request<ReadinessResponse>("/readyz", { tolerateStatus: true });
  },

  capabilities(noun?: string): Promise<CapabilitiesResponse> {
    const q = noun ? `?noun=${encodeURIComponent(noun)}` : "";
    return request<CapabilitiesResponse>(`/v1/capabilities${q}`);
  },

  modelEndpoints(): Promise<ModelEndpointsResponse> {
    return request<ModelEndpointsResponse>("/v1/model-endpoints");
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

  workDetail(id: string): Promise<WorkDetailResponse> {
    return request<WorkDetailResponse>(`/v1/work/${encodeURIComponent(id)}`);
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
};
