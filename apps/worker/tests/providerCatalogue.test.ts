import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
  AI_PROVIDERS,
  bifrostProviderId,
  isBifrostSupported,
} from "../src/components/onboarding/providerCatalogue";

/**
 * The onboarding picker's provider list is a second copy of the kernel's
 * `BIFROST_PROVIDERS`. Two copies of a rule is one copy and a disagreement, so
 * these tests parse the Python authority and fail when the two drift.
 *
 * The defect they exist for: the picker was generated from the whole vendored
 * models.dev snapshot, 191 providers, while the kernel binds 23. Picking any of
 * the other 168 got "the selected provider is not supported by Bifrost" at
 * submit, after the key had been typed.
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

describe("the onboarding provider picker only offers what Bifrost can bind", () => {
  it("offers no provider the kernel would refuse", () => {
    const supported = kernelProviders();
    const refused = AI_PROVIDERS.map((p) => p.id).filter(
      (id) => !supported.has(bifrostProviderId(id)),
    );
    expect(refused).toEqual([]);
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

  it("drops Ollama Cloud rather than pretending self-hosted Ollama serves it", () => {
    // It is a hosted API with its own base URL and a real key. Aliasing it to
    // `ollama` without a live binding to prove it would put the lie back.
    expect(isBifrostSupported("ollama-cloud")).toBe(false);
    expect(AI_PROVIDERS.some((p) => p.id === "ollama-cloud")).toBe(false);
  });

  it("leaves a non-empty picker", () => {
    expect(AI_PROVIDERS.length).toBeGreaterThan(5);
  });
});
