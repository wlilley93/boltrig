// Personal agent, notifications, and memory endpoints.
// The verb routes (recall/remember/forget/ingest) carry tolerateStatus so a
// 404 (memory disabled -> binding_not_found) or 403 (scope denied) renders as
// a message instead of throwing. The reads are scope-filtered server-side.

import { request } from "@/api/transport";
import type {
  ConfigurePersonalAgentRequest,
  ConfigurePersonalAgentResponse,
  InvokePersonalAgentRequest,
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
  SpawnResult,
} from "@/api/types";

export const memoryApi = {
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

  memoryQuery(body: MemoryQueryRequest): Promise<MemoryQueryResponse> {
    return request<MemoryQueryResponse>("/v1/memory/query", {
      method: "POST",
      body,
    });
  },

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
};
