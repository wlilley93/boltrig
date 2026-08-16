import snapshot from "./modelsDevCatalogue.json";

export interface CatalogueModel {
  id: string;
  name?: string;
  vision?: true;
}

export interface CatalogueProvider {
  id: string;
  name: string;
  models: CatalogueModel[];
  detail?: string;
  info?: string;
  requiresBaseUrl?: true;
  /** The server authenticates nothing, so the key field is optional. */
  keyOptional?: true;
}

interface CatalogueSnapshot {
  source: string;
  revision: string;
  license: string;
  providers: CatalogueProvider[];
}

const catalogue = snapshot as CatalogueSnapshot;

const SELF_HOSTED_OLLAMA: CatalogueProvider = {
  id: "ollama",
  name: "Ollama",
  detail: "Self-hosted",
  info: "Hosted Boltrig can use Ollama through a secured public HTTPS endpoint. Never expose an unauthenticated Ollama port. Use Boltrig Desktop to keep Ollama local to your computer.",
  models: [],
  requiresBaseUrl: true,
  keyOptional: true,
};

export const AI_PROVIDERS = catalogue.providers.flatMap((provider) => (
  provider.id === "ollama-cloud" ? [SELF_HOSTED_OLLAMA, provider] : [provider]
));
export const AI_CATALOGUE_REVISION = catalogue.revision;

export function exactModelId(providerId: string, modelId: string): string {
  const provider = providerId.trim();
  const model = modelId.trim();
  if (!provider || provider === "custom" || model.startsWith(`${provider}/`)) return model;
  return `${provider}/${model}`;
}

export function modelAcceptsVision(model: CatalogueModel | null): boolean {
  return model?.vision === true;
}

export function providerNeedsBaseUrl(providerId: string): boolean {
  return AI_PROVIDERS.some((provider) => (
    provider.id === providerId && provider.requiresBaseUrl === true
  ));
}

export function providerKeyOptional(providerId: string): boolean {
  return AI_PROVIDERS.some((provider) => (
    provider.id === providerId && provider.keyOptional === true
  ));
}
