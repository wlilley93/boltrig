import { vi } from "vitest";
import { api } from "@/api/client";

/**
 * Minimal mock helper for the typed API client. Accepts a map of method names
 * to resolved values; every other method returns a permissive empty object.
 * This keeps characterization tests fast and offline.
 */
export function mockApi(
  stubs: Partial<Record<keyof typeof api, unknown>> = {},
): void {
  for (const key of Object.keys(api) as Array<keyof typeof api>) {
    const value = key in stubs ? stubs[key] : {};
    vi.spyOn(api, key).mockResolvedValue(value as never);
  }
}

/**
 * Reset all API mocks between tests.
 */
export function clearApiMocks(): void {
  vi.restoreAllMocks();
}
