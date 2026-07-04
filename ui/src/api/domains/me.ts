// Caller-scoped account endpoints: settings, activity, export, conversations,
// tokens, sessions, notifications, and personal agent status.
// Writes carry tolerateStatus so a 400 (bad input), 403 (admin-only) or 404
// (not found) renders as a message instead of throwing.

import { request } from "@/api/transport";
import type {
  ConnectionsResponse,
  DeleteAck,
  MeActivityResponse,
  MeAgentResponse,
  MeExportResponse,
  MeNotificationsResponse,
  MeSettingsResponse,
  MintTokenRequest,
  MintTokenResponse,
  PutMeNotificationRequest,
  PutSettingsRequest,
  PutSettingsResponse,
  RenameConversationRequest,
  SessionsResponse,
  TokensResponse,
} from "@/api/types";

export const meApi = {
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

  putMeNotification(body: PutMeNotificationRequest): Promise<DeleteAck> {
    return request<DeleteAck>("/v1/me/notifications", {
      method: "PUT",
      body,
      tolerateStatus: true,
    });
  },

  meAgent(): Promise<MeAgentResponse> {
    return request<MeAgentResponse>("/v1/me/agent", { tolerateStatus: true });
  },
};
