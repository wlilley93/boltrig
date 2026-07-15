// Insight, evaluation, and run visibility (scope-filtered server-side, SEC-33).

import { request } from "@/api/transport";
import type {
  AuditExportResponse,
  AuditSearchResponse,
  BudgetsResponse,
  CostResponse,
  ConsoleOverviewResponse,
  CreateEvalCaseRequest,
  EvalCasesResponse,
  EvalRunResult,
  EvalRunsResponse,
  RunEvalRequest,
  RunsResponse,
  StatusAck,
} from "@/api/types";

export const insightApi = {
  consoleOverview(limit = 20): Promise<ConsoleOverviewResponse> {
    return request<ConsoleOverviewResponse>(
      `/v1/console/overview?limit=${encodeURIComponent(String(limit))}`,
    );
  },

  cost(): Promise<CostResponse> {
    return request<CostResponse>("/v1/cost");
  },

  budgets(): Promise<BudgetsResponse> {
    return request<BudgetsResponse>("/v1/budgets");
  },

  auditSearch(
    params: {
      actor?: string;
      verb?: string;
      run?: string;
      resource?: string;
      status?: string;
      since?: string;
      until?: string;
      security?: boolean;
      eventType?: string;
    } = {},
  ): Promise<AuditSearchResponse> {
    const q = new URLSearchParams();
    if (params.actor) q.set("actor", params.actor);
    if (params.verb) q.set("verb", params.verb);
    if (params.run) q.set("run", params.run);
    if (params.resource) q.set("resource", params.resource);
    if (params.status) q.set("status", params.status);
    if (params.since) q.set("since", params.since);
    if (params.until) q.set("until", params.until);
    if (params.security) q.set("security", "1");
    if (params.eventType) q.set("event_type", params.eventType);
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

  evalCases(): Promise<EvalCasesResponse> {
    return request<EvalCasesResponse>("/v1/eval/cases");
  },

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
};
