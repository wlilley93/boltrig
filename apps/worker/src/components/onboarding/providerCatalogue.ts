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
  /** The provider's API base URL from models.dev, when it publishes one. */
  api?: string;
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

/**
 * The providers Bifrost drives with a NATIVE driver.
 *
 * This set used to be the whole picker: everything else was filtered out,
 * because submitting an unlisted provider failed at the kernel with "the
 * selected provider is not supported by Bifrost". The kernel now binds any
 * OTHER catalogue provider as an OpenAI-compatible CUSTOM provider through
 * its published base URL (`api` in the snapshot, or one the user types), so
 * the full models.dev list is offered again and the set below only decides
 * WHICH PATH a provider takes, not whether it is offered.
 *
 * THIS SET IS STILL A SECOND COPY OF `BIFROST_PROVIDERS` in
 * `boltrig/identity/bifrost_user_admin.py`, which is the authority, and
 * `apps/worker/tests/providerCatalogue.test.ts` parses the Python source and
 * fails if the two ever disagree. Add a native provider there first.
 */
const BIFROST_SUPPORTED = new Set([
  "anthropic", "azure", "bedrock", "cerebras", "cohere", "elevenlabs",
  "fireworks", "gemini", "groq", "huggingface", "mistral", "nebius",
  "ollama", "openai", "openrouter", "parasail", "perplexity", "replicate",
  "runway", "sgl", "vertex", "vllm", "xai",
]);

/** models.dev spells three of them differently. Mirrors the kernel's aliases. */
const CATALOGUE_ALIASES: Record<string, string> = {
  "google": "gemini",
  "google-generative-ai": "gemini",
  "x-ai": "xai",
  "amazon-bedrock": "bedrock",
  "fireworks-ai": "fireworks",
  "google-vertex": "vertex",
};

export function bifrostProviderId(catalogueId: string): string {
  const id = catalogueId.trim().toLowerCase();
  return CATALOGUE_ALIASES[id] ?? id;
}

export function isBifrostSupported(catalogueId: string): boolean {
  return BIFROST_SUPPORTED.has(bifrostProviderId(catalogueId));
}

// The FULL catalogue, unfiltered. Ollama Cloud stays distinct from self-hosted
// `ollama` -- it is a hosted API with its own base URL and a real key, and it
// now stands on its own custom binding rather than being dropped.
export const AI_PROVIDERS = catalogue.providers
  .flatMap((provider) => (
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

/** The catalogue's published base URL for a provider, if it has one. */
export function providerApiBaseUrl(providerId: string): string | undefined {
  return AI_PROVIDERS.find((provider) => provider.id === providerId)?.api;
}

/**
 * Whether the user must TYPE a base URL: self-hosted entries always, and any
 * non-native provider the catalogue publishes no `api` URL for. A non-native
 * provider WITH a published URL submits it silently -- the custom binding
 * needs an address, and the catalogue already knows it.
 */
export function providerNeedsBaseUrl(providerId: string): boolean {
  const provider = AI_PROVIDERS.find((entry) => entry.id === providerId);
  if (!provider) return false;
  if (provider.requiresBaseUrl === true) return true;
  return !isBifrostSupported(provider.id) && !provider.api;
}

export function providerKeyOptional(providerId: string): boolean {
  return AI_PROVIDERS.some((provider) => (
    provider.id === providerId && provider.keyOptional === true
  ));
}
