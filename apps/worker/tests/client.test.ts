import { describe, expect, it, vi, beforeEach } from "vitest";
import { client } from "../src/client";
import { resetGatewayCache } from "../src/hermes/http";

describe("Worker HTTP authentication boundary", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    resetGatewayCache();
  });

  it("uses the browser cookie session without an access-token path", async () => {
    const MOCK_GW = "gate_123";
    (fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ tenant_gateway_id: MOCK_GW }),
    });
    (fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ settings: {} }),
    });

    await client.meSettings();

    expect(fetch).toHaveBeenCalledWith("/api/me", expect.any(Object));
    // Settings are a CONTROL-PLANE route, not a cell route: /api/settings is
    // absent from the proxy allowlist and 403s when sent through it.
    expect(fetch).toHaveBeenCalledWith("/api/settings", expect.any(Object));
    
    const calls = (fetch as any).mock.calls;
    calls.forEach(([url]: [string]) => {
      expect(url).not.toContain("access_token=");
    });
  });

  it("is strictly same-origin relative", async () => {
    (fetch as any).mockResolvedValue({
      ok: true,
      json: async () => ({ tenant_gateway_id: "gate_123" }),
    });
    
    await client.meSettings();
    expect(fetch).toHaveBeenCalledWith("/api/me", expect.any(Object));
  });
});
