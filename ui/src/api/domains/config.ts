// Admin configuration console endpoints.

import { request } from "@/api/transport";
import type {
  ConfigExportResponse,
  ConfigHistoryResponse,
  ConfigRollbackRequest,
  ConfigRollbackResponse,
  ConfigSectionResponse,
  CredentialsResponse,
  GovernedRouteResponse,
  PutConfigRequest,
  PutConfigResponse,
} from "@/api/types";

export const configApi = {
  getConfig(section: string): Promise<ConfigSectionResponse> {
    return request<ConfigSectionResponse>(
      `/v1/admin/config/${encodeURIComponent(section)}`,
      { tolerateStatus: true },
    );
  },

  putConfig(
    section: string,
    body: PutConfigRequest,
  ): Promise<GovernedRouteResponse<PutConfigResponse>> {
    return request<GovernedRouteResponse<PutConfigResponse>>(
      `/v1/admin/config/${encodeURIComponent(section)}`,
      { method: "PUT", body, tolerateStatus: true },
    );
  },

  configHistory(section: string): Promise<ConfigHistoryResponse> {
    return request<ConfigHistoryResponse>(
      `/v1/admin/config/${encodeURIComponent(section)}/history`,
      { tolerateStatus: true },
    );
  },

  configRollback(
    section: string,
    body: ConfigRollbackRequest,
  ): Promise<GovernedRouteResponse<ConfigRollbackResponse>> {
    return request<GovernedRouteResponse<ConfigRollbackResponse>>(
      `/v1/admin/config/${encodeURIComponent(section)}/rollback`,
      { method: "POST", body, tolerateStatus: true },
    );
  },

  configExport(): Promise<ConfigExportResponse> {
    return request<ConfigExportResponse>("/v1/admin/config/export", {
      method: "POST",
      tolerateStatus: true,
    });
  },

  adminCredentials(): Promise<CredentialsResponse> {
    return request<CredentialsResponse>("/v1/admin/credentials", {
      tolerateStatus: true,
    });
  },
};
