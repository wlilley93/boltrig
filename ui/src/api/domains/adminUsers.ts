// Admin user and invitation management (org-admin / author roles).

import { request } from "@/api/transport";
import type {
  AdminInvitationsResponse,
  AdminUsersResponse,
  CreateInvitationRequest,
  CreateInvitationResponse,
  DeleteAck,
  PatchUserRequest,
  PatchUserResponse,
} from "@/api/types";

export const adminUsersApi = {
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
