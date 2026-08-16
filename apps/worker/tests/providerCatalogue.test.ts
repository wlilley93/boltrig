import { describe, expect, it } from "vitest";

import {
  AI_CATALOGUE_REVISION,
  AI_PROVIDERS,
  exactModelId,
  modelAcceptsVision,
} from "../src/components/onboarding/providerCatalogue";

const EXACT_MODEL = /^[A-Za-z0-9][A-Za-z0-9@_.:/-]{0,159}$/;
const MUTABLE = new Set([
  "auto", "beta", "current", "default", "experimental", "latest", "preview",
  "recommended", "stable",
]);

describe("onboarding provider catalogue", () => {
  it("ships the broad provider set plus Llama and reviewed supplements", () => {
    const ids = AI_PROVIDERS.map((provider) => provider.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids.length).toBeGreaterThanOrEqual(190);
    expect(ids).toEqual(expect.arrayContaining([
      "actual", "amazon-bedrock", "anthropic", "arcee", "azure", "byteplus",
      "custom", "google", "llama", "ollama", "ollama-cloud", "openai", "openrouter",
      "qianfan", "xai",
    ]));
    expect(AI_CATALOGUE_REVISION).toMatch(/^[0-9a-f]{40}$/);
  });

  it("keeps hosted and self-hosted Ollama distinct and explains the network boundary", () => {
    const ollama = AI_PROVIDERS.find((provider) => provider.id === "ollama");
    const cloud = AI_PROVIDERS.find((provider) => provider.id === "ollama-cloud");
    expect(ollama).toMatchObject({
      name: "Ollama",
      detail: "Self-hosted",
      requiresBaseUrl: true,
      models: [],
    });
    expect(ollama?.info).toMatch(/secured public HTTPS endpoint/);
    expect(ollama?.info).toMatch(/Never expose an unauthenticated Ollama port/);
    expect(ollama?.info).toMatch(/Boltrig Desktop/);
    expect(cloud?.name).toBe("Ollama Cloud");
    expect(cloud?.models.length).toBeGreaterThan(0);
  });

  it("projects only exact model ids that the kernel can accept", () => {
    for (const provider of AI_PROVIDERS) {
      for (const model of provider.models) {
        const value = exactModelId(provider.id, model.id);
        expect(value).toMatch(EXACT_MODEL);
        expect(value.split("/")).not.toContain("");
        expect(value.split(/[._:/-]/).some((part) => MUTABLE.has(part.toLowerCase())))
          .toBe(false);
      }
    }
  });

  it("retains declared vision capability without inferring it from a name", () => {
    const openai = AI_PROVIDERS.find((provider) => provider.id === "openai");
    expect(modelAcceptsVision(openai?.models.find((model) => model.id === "gpt-5.4") ?? null))
      .toBe(true);
    expect(modelAcceptsVision({ id: "contains-vision-in-name" })).toBe(false);
  });
});
