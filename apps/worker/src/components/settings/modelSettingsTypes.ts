import type { BifrostModelView, ModelEndpointInfo } from "@wlilley93/boltrig-web-sdk";

export type ModelReferences = {
  capabilities: string[];
  fallbacks: string[];
};

export type ModelView = "text" | "vision" | "voice";
export type EndpointModality = "text" | "vision" | "stt" | "tts" | "realtime";

export function modelEndpointLabel(
  endpoint: Pick<ModelEndpointInfo, "model">,
): string {
  return endpoint.model.trim() || "Model name unavailable";
}

export function supportsCatalogueModality(model: BifrostModelView, view: ModelView): boolean {
  const modalities = model.input_modalities ?? [];
  if (view === "text") return modalities.includes("text");
  if (view === "vision") {
    return modalities.includes("vision") || modalities.includes("image");
  }
  return false;
}

export function supportsCatalogueModalities(
  model: BifrostModelView,
  modalities: readonly EndpointModality[],
): boolean {
  return modalities
    .filter((modality): modality is "text" | "vision" => (
      modality === "text" || modality === "vision"
    ))
    .every((modality) => supportsCatalogueModality(model, modality));
}

export function supportsEndpointView(endpoint: ModelEndpointInfo, view: ModelView): boolean {
  const modalities = endpoint.modalities ?? ["text"];
  if (view === "voice") {
    return modalities.some((modality) => ["stt", "tts", "realtime"].includes(modality));
  }
  return modalities.includes(view);
}
