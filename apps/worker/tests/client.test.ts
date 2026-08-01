import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sdk = vi.hoisted(() => ({
  options: null as null | Record<string, unknown>,
}));

vi.mock("@wlilley93/boltrig-web-sdk", () => ({
  BoltrigClient: class {
    constructor(options: Record<string, unknown>) {
      sdk.options = options;
    }
  },
}));

beforeEach(() => {
  sdk.options = null;
  vi.resetModules();
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("Worker HTTP authentication boundary", () => {
  it("uses the cookie session without consulting the device keychain", async () => {
    await import("../src/client");

    expect(sdk.options).toEqual({ baseUrl: "" });
    expect(sdk.options).not.toHaveProperty("accessToken");
  });

  it("targets the configured API origin the desktop session is bound to", async () => {
    vi.stubEnv("VITE_API_BASE", "https://kernel.boltrig.test/");
    await import("../src/client");

    expect(sdk.options).toEqual({ baseUrl: "https://kernel.boltrig.test" });
  });
});
