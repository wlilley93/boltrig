// Public API object assembled from per-domain modules. Each domain owns a
// single concern and contributes its methods to the shared `api` namespace.

import { adminUsersApi } from "@/api/domains/adminUsers";
import { authApi } from "@/api/domains/auth";
import { channelsApi } from "@/api/domains/channels";
import { configApi } from "@/api/domains/config";
import { coreApi } from "@/api/domains/core";
import { insightApi } from "@/api/domains/insight";
import { knowledgeApi } from "@/api/domains/knowledge";
import { meApi } from "@/api/domains/me";
import { memoryApi } from "@/api/domains/memory";
import { studioApi } from "@/api/domains/studio";
import { workspacesApi } from "@/api/domains/workspaces";

export const api = {
  ...coreApi,
  ...studioApi,
  ...configApi,
  ...channelsApi,
  ...insightApi,
  ...knowledgeApi,
  ...memoryApi,
  ...meApi,
  ...adminUsersApi,
  ...authApi,
  ...workspacesApi,
};
