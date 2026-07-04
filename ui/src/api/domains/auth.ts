// First-party auth and active context switching.
// login/accept are public (no principal); logout requires the session. All carry
// tolerateStatus so a 401 (generic), 429 (throttled) or 400 (bad token / weak
// password) renders faithfully instead of throwing.

import { request } from "@/api/transport";
import type {
  AcceptInviteRequest,
  AcceptInviteResponse,
  LoginRequest,
  LoginResponse,
  StatusAck,
  SwitchContextResponse,
  TwoFactorChallengeRequest,
  TwoFactorChallengeResponse,
  TwoFactorDisableRequest,
  TwoFactorEnrollBeginResponse,
  TwoFactorVerifyEnrollRequest,
  TwoFactorVerifyEnrollResponse,
} from "@/api/types";

export const authApi = {
  login(body: LoginRequest): Promise<LoginResponse> {
    return request<LoginResponse>("/v1/auth/login", {
      method: "POST",
      body,
      tolerateStatus: true,
    });
  },

  acceptInvite(body: AcceptInviteRequest): Promise<AcceptInviteResponse> {
    return request<AcceptInviteResponse>("/v1/auth/accept-invite", {
      method: "POST",
      body,
      tolerateStatus: true,
    });
  },

  logout(): Promise<StatusAck> {
    return request<StatusAck>("/v1/auth/logout", {
      method: "POST",
      tolerateStatus: true,
    });
  },

  twoFactorChallenge(body: TwoFactorChallengeRequest): Promise<TwoFactorChallengeResponse> {
    return request<TwoFactorChallengeResponse>("/v1/auth/2fa/challenge", {
      method: "POST",
      body,
      tolerateStatus: true,
    });
  },

  twoFactorEnrollBegin(): Promise<TwoFactorEnrollBeginResponse> {
    return request<TwoFactorEnrollBeginResponse>("/v1/auth/2fa/enroll", {
      method: "POST",
      tolerateStatus: true,
    });
  },

  twoFactorVerifyEnroll(
    body: TwoFactorVerifyEnrollRequest,
  ): Promise<TwoFactorVerifyEnrollResponse> {
    return request<TwoFactorVerifyEnrollResponse>("/v1/auth/2fa/verify-enroll", {
      method: "POST",
      body,
      tolerateStatus: true,
    });
  },

  twoFactorDisable(body: TwoFactorDisableRequest): Promise<StatusAck> {
    return request<StatusAck>("/v1/auth/2fa/disable", {
      method: "POST",
      body,
      tolerateStatus: true,
    });
  },

  // Active context (COUNTY 8): switch the session's active workspace.
  // The switch is re-authorized against membership server-side (404 unknown, 403
  // non-member, no write); tolerateStatus so those render as a message.
  switchActiveContext(workspaceId: string): Promise<SwitchContextResponse> {
    return request<SwitchContextResponse>("/v1/me/active-context", {
      method: "POST",
      body: { workspace_id: workspaceId },
      tolerateStatus: true,
    });
  },
};
