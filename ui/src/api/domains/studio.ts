// Authoring studio: skills, nouns, verbs, adapters, and workflows.
// Writes carry tolerateStatus so a 403 (role lacks authoring) renders as a
// denial message instead of throwing.

import { request } from "@/api/transport";
import type {
  ActivateAdapterRequest,
  ActivateAdapterResponse,
  AdapterInventoryResponse,
  AdapterSourceResponse,
  GenerateAdapterRequest,
  GenerateAdapterResponse,
  RegisterMcpRequest,
  ScheduleWorkflowRequest,
  ScheduleWorkflowResponse,
  SetBindingRequest,
  SkillsResponse,
  SpawnResult,
  StatusAck,
  TestSpawnRequest,
  TriggerWorkflowRequest,
  UpsertNounRequest,
  UpsertSkillRequest,
  UpsertVerbRequest,
  UpsertWorkflowRequest,
  WorkflowDetail,
  WorkflowRunDescriptor,
  WorkflowRunRecord,
  WorkflowRunsResponse,
  WorkflowStatsResponse,
  WorkflowsResponse,
} from "@/api/types";

export const studioApi = {
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

  // Aggregated run stats per workflow (design brief 22.1): the REAL run_count /
  // success_rate / last_run_at the automations home cards merge over their
  // deterministic placeholders. Tenant-scoped server-side.
  workflowStats(): Promise<WorkflowStatsResponse> {
    return request<WorkflowStatsResponse>("/v1/workflow-stats");
  },
};
