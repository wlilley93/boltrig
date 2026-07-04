// Insight, evaluation, and run visibility (scope-filtered server-side, SEC-33).

import { request } from "@/api/transport";
import type {
  AuditExportResponse,
  AuditSearchResponse,
  BudgetsResponse,
  CostResponse,
  CreateEvalCaseRequest,
  EvalRunResult,
  EvalRunsResponse,
  RunEvalRequest,
  RunsResponse,
  StatusAck,
} from "@/api/types";

export const insightApi = {
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
