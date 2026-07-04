// Workspace, organisation, and AI key management (COUNTY 8).
// AI keys are per-org / workspace / user and sealed once: GET returns has_key
// only; PUT accepts the key once; DELETE drops the row + sealed credential.

import { request } from "@/api/transport";
import type {
  AddWorkspaceMemberRequest,
  AddWorkspaceMemberResponse,
  AiKeysResponse,
  CreateWorkspaceRequest,
  CurrentOrgResponse,
  DeleteAck,
  DeleteAiKeyResponse,
  OrgMembersResponse,
  SetAiKeyRequest,
  SetAiKeyResponse,
  UpdateOrgRequest,
  UpdateOrgResponse,
  UpdateWorkspaceRequest,
  WorkspaceMembersResponse,
  WorkspaceMutationResponse,
  WorkspacesResponse,
} from "@/api/types";

export const workspacesApi = {
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

  // === Organisation: the caller's org handle + policy flags ===

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
