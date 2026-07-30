import { beforeEach, describe, expect, it, vi } from "vitest";

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

describe("Worker HTTP authentication boundary", () => {
  it("uses the cookie session without consulting the device keychain", async () => {
    await import("../src/client");

    expect(sdk.options).toEqual({ baseUrl: "" });
    expect(sdk.options).not.toHaveProperty("accessToken");
  });
});
