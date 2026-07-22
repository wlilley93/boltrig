import {
  ApiError,
  BASE,
  csrfHeaders,
  identityHeaders,
  parseBody,
  request,
} from "@/api/transport";
import type {
  KnowledgeAssetsResponse,
  KnowledgeMutationResponse,
  KnowledgeProvidersResponse,
  KnowledgeSearchResponse,
  KnowledgeUploadResponse,
} from "@/api/types";

async function raw(path: string, options: RequestInit): Promise<Response> {
  const method = String(options.method ?? "GET");
  const response = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      ...identityHeaders(),
      ...csrfHeaders(method),
      ...(options.headers ?? {}),
    },
  });
  if (!response.ok) {
    const body = await parseBody(response);
    throw new ApiError(response.status, `${method} ${path} -> ${response.status}`, body);
  }
  return response;
}

async function uploadKnowledge(file: File, title: string): Promise<KnowledgeUploadResponse> {
  const begun = await request<{ upload_id: string }>("/v1/knowledge/uploads", {
    method: "POST",
    body: {
      title: title.trim() || file.name,
      filename: file.name,
      media_type: file.type || "application/octet-stream",
    },
  });
  await raw(`/v1/knowledge/uploads/${encodeURIComponent(begun.upload_id)}`, {
    method: "PUT",
    body: file,
    headers: { "content-type": file.type || "application/octet-stream" },
  });
  return request<KnowledgeUploadResponse>(
    `/v1/knowledge/uploads/${encodeURIComponent(begun.upload_id)}/commit`,
    { method: "POST" },
  );
}

async function knowledgeOriginal(assetId: string): Promise<Blob> {
  const response = await raw(
    `/v1/knowledge/assets/${encodeURIComponent(assetId)}/original`,
    { method: "GET" },
  );
  return response.blob();
}

export const knowledgeApi = {
  knowledgeAssets(): Promise<KnowledgeAssetsResponse> {
    return request<KnowledgeAssetsResponse>("/v1/knowledge/assets");
  },
  knowledgeSearch(query: string, limit = 12): Promise<KnowledgeSearchResponse> {
    return request<KnowledgeSearchResponse>("/v1/knowledge/search", {
      method: "POST",
      body: { query, limit },
    });
  },
  knowledgeProviders(): Promise<KnowledgeProvidersResponse> {
    return request<KnowledgeProvidersResponse>("/v1/knowledge/providers");
  },
  setKnowledgeProvider(providerId: string, enabled: boolean): Promise<KnowledgeMutationResponse> {
    return request<KnowledgeMutationResponse>(
      `/v1/knowledge/providers/${encodeURIComponent(providerId)}`,
      { method: "POST", body: { enabled }, tolerateStatus: true },
    );
  },
  eraseKnowledgeAsset(assetId: string): Promise<KnowledgeMutationResponse> {
    return request<KnowledgeMutationResponse>(
      `/v1/knowledge/assets/${encodeURIComponent(assetId)}`,
      { method: "DELETE", tolerateStatus: true },
    );
  },
  uploadKnowledge,
  knowledgeOriginal,
};
