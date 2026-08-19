import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
  AI_PROVIDERS,
  bifrostProviderId,
  isBifrostSupported,
  providerNeedsBaseUrl,
} from "../src/components/onboarding/providerCatalogue";

/**
 * The picker's NATIVE set and alias table are second copies of the kernel's
 * `BIFROST_PROVIDERS` / `_PROVIDER_ALIASES`. Two copies of a rule is one copy
 * and a disagreement, so these tests parse the Python authority and fail when
 * either drifts.
 *
 * The history matters to read these right. The picker once offered the whole
 * snapshot while the kernel bound 23, so 93% of choices failed AT SUBMIT; then
 * it was filtered to the 23, which fixed the lie by shrinking the product. The
 * kernel now binds any other catalogue provider as an OpenAI-compatible CUSTOM
 * provider through a base URL, so the full list is offered again - and what
 * these tests pin is no longer "picker == kernel set" but the two properties
 * the custom path stands on: the native set agrees, and every non-native entry
 * can actually deliver an address.
 */

const REPO = resolve(__dirname, "../../..");

function kernelProviders(): Set<string> {
  const source = readFileSync(
    resolve(REPO, "boltrig/identity/bifrost_user_admin.py"),
    "utf8",
  );
  const block = /BIFROST_PROVIDERS = frozenset\(\s*\{([\s\S]*?)\}\s*\)/.exec(source);
  if (!block) throw new Error("BIFROST_PROVIDERS not found in the kernel source");
  return new Set([...block[1].matchAll(/"([a-z]+)"/g)].map((m) => m[1]));
}

function kernelAliases(): Record<string, string> {
  const source = readFileSync(
    resolve(REPO, "boltrig/identity/bifrost_user_binding.py"),
    "utf8",
  );
  const block = /_PROVIDER_ALIASES = \{([\s\S]*?)\}/.exec(source);
  if (!block) throw new Error("_PROVIDER_ALIASES not found in the kernel source");
  return Object.fromEntries(
    [...block[1].matchAll(/"([a-z0-9-]+)":\s*"([a-z0-9-]+)"/g)].map((m) => [m[1], m[2]]),
  );
}

describe("the onboarding provider picker offers the full catalogue honestly", () => {
  it("agrees with the kernel about which providers are NATIVE", () => {
    const supported = kernelProviders();
    for (const id of supported) {
      expect(isBifrostSupported(id)).toBe(true);
    }
    // And the picker claims nothing native the kernel does not.
    for (const provider of AI_PROVIDERS) {
      if (isBifrostSupported(provider.id)) {
        expect(supported.has(bifrostProviderId(provider.id))).toBe(true);
      }
    }
  });

  it("offers the FULL models.dev catalogue, not a filtered corner of it", () => {
    // The regression this guards: a filter quietly reappearing and shrinking
    // the product back to the native set.
    expect(AI_PROVIDERS.length).toBeGreaterThan(150);
    const offered = new Set(AI_PROVIDERS.map((p) => p.id));
    for (const id of ["deepseek", "togetherai", "moonshotai", "zhipuai"]) {
      expect(offered.has(id)).toBe(true);
    }
  });

  it("every non-native provider can deliver an address, one way or the other", () => {
    // The custom binding cannot exist without a base URL. Either the catalogue
    // publishes one (submitted silently) or the picker must ask the user
    // (providerNeedsBaseUrl). A non-native entry with NEITHER is the old
    // fails-at-submit lie wearing a new shape.
    for (const provider of AI_PROVIDERS) {
      if (isBifrostSupported(provider.id)) continue;
      const hasAddress = typeof provider.api === "string" && provider.api.length > 0;
      expect(hasAddress || providerNeedsBaseUrl(provider.id)).toBe(true);
    }
  });

  it("agrees with the kernel's alias table, which is what normalises the submitted prefix", () => {
    const kernel = kernelAliases();
    for (const [from, to] of Object.entries(kernel)) {
      expect(bifrostProviderId(from)).toBe(to);
    }
  });

  it("still offers the providers a user is most likely to have a key for", () => {
    const offered = new Set(AI_PROVIDERS.map((p) => p.id));
    for (const id of ["openai", "anthropic", "google", "ollama", "openrouter", "groq"]) {
      expect(offered.has(id)).toBe(true);
    }
  });

  it("keeps self-hosted Ollama, which is the one that needs a base URL", () => {
    const ollama = AI_PROVIDERS.find((p) => p.id === "ollama");
    expect(ollama?.requiresBaseUrl).toBe(true);
    expect(ollama?.keyOptional).toBe(true);
  });

  it("offers Ollama Cloud as its own custom provider, never as an alias of self-hosted", () => {
    // It is a hosted API with its own base URL and a real key. It used to be
    // DROPPED to avoid aliasing it onto `ollama`; the custom path lets it
    // stand on its own address instead. The property that must survive is the
    // second assertion: it is not native, so it must never silently become
    // self-hosted Ollama.
    expect(isBifrostSupported("ollama-cloud")).toBe(false);
    const cloud = AI_PROVIDERS.find((p) => p.id === "ollama-cloud");
    expect(cloud).toBeDefined();
    expect(typeof cloud?.api).toBe("string");
  });

  it("leaves a non-empty picker", () => {
    expect(AI_PROVIDERS.length).toBeGreaterThan(5);
  });
});
