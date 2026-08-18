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

/**
 * The providers Bifrost can actually bind a key for.
 *
 * The vendored models.dev snapshot lists 191 providers. The kernel binds 23 of
 * them, and offering the rest produced a picker where 93% of the choices failed
 * at submit with "the selected provider is not supported by Bifrost" -- a
 * configuration path that looks successful right up until it is not, which is
 * the thing this product does not do.
 *
 * THIS SET IS A SECOND COPY OF `BIFROST_PROVIDERS` in
 * `boltrig/identity/bifrost_user_admin.py`, which is the authority. It is
 * duplicated because no route exposes it to the browser, and
 * `apps/worker/tests/providerCatalogue.test.ts` parses the Python source and
 * fails if the two ever disagree. Add a provider there first.
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

export const AI_PROVIDERS = catalogue.providers
  .flatMap((provider) => (
    provider.id === "ollama-cloud" ? [SELF_HOSTED_OLLAMA, provider] : [provider]
  ))
  // Ollama Cloud is deliberately NOT aliased to self-hosted `ollama`: it is a
  // hosted API with its own base URL and a real key, and inventing that mapping
  // without a live binding to prove it is how a picker starts lying again.
  .filter((provider) => isBifrostSupported(provider.id));
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
