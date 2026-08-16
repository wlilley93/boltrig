// @vitest-environment happy-dom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const tauri = vi.hoisted(() => ({
  Channel: class {
    onmessage: ((event: unknown) => void) | null = null;
  },
  invoke: vi.fn(),
  listen: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({
  Channel: tauri.Channel,
  invoke: tauri.invoke,
}));
vi.mock("@tauri-apps/api/event", () => ({ listen: tauri.listen }));

const enrollment = {
  authorization_code: "one-time-code",
  expires_at: "2030-01-01T00:00:00Z",
  verification_uri: "/#/settings",
  lease_verifier: {
    algorithm: "Ed25519",
    key_id: "a".repeat(64),
    public_key: "exact-public-key",
  },
};

beforeEach(() => {
  vi.resetModules();
  vi.stubEnv("VITE_API_BASE", "https://kernel.boltrig.test/");
  Object.defineProperty(window, "__TAURI_INTERNALS__", {
    value: {
      transformCallback: vi.fn(() => 7),
    },
    configurable: true,
  });
});

afterEach(() => {
  Reflect.deleteProperty(window, "__TAURI_INTERNALS__");
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

describe("narrow Worker desktop wrappers", () => {
  it("uses fixed native account commands without exposing an API origin or session secret", async () => {
    tauri.invoke
      .mockResolvedValueOnce({
        http_status: 200,
        body: { status: "ok", csrf_token: "csrf-from-native" },
      })
      .mockResolvedValueOnce({
        http_status: 200,
        body: { status: "ok", csrf_token: "rotated-csrf" },
      });
    const desktop = await import("../src/desktop");

    expect(await desktop.desktopAccountLogin(
      "owner@example.test",
      "account-password",
    )).toMatchObject({ status: "ok", csrf_token: "csrf-from-native" });
    expect(await desktop.desktopAccountRefresh())
      .toMatchObject({ status: "ok", csrf_token: "rotated-csrf" });

    expect(tauri.invoke).toHaveBeenNthCalledWith(1, "desktop_account_login", {
      email: "owner@example.test",
      password: "account-password",
    });
    expect(tauri.invoke).toHaveBeenNthCalledWith(2, "desktop_account_refresh");
    const serialized = JSON.stringify(tauri.invoke.mock.calls);
    expect(serialized).not.toContain("apiOrigin");
    expect(serialized).not.toContain("session_token");
  });

  it("uses fixed challenge and logout commands and preserves typed HTTP failures", async () => {
    tauri.invoke
      .mockResolvedValueOnce({
        http_status: 200,
        body: { status: "ok", csrf_token: "challenge-csrf" },
      })
      .mockResolvedValueOnce({
        http_status: 401,
        body: { status: "error", reason: "session expired" },
      })
      .mockResolvedValueOnce({
        http_status: 200,
        body: { status: "ok" },
      });
    const desktop = await import("../src/desktop");

    await expect(desktop.desktopAccountChallenge("opaque-challenge", "123456"))
      .resolves.toMatchObject({ status: "ok", csrf_token: "challenge-csrf" });
    await expect(desktop.desktopAccountRefresh()).rejects.toMatchObject({
      status: 401,
      body: { status: "error", reason: "session expired" },
    });
    await expect(desktop.desktopAccountLogout()).resolves.toEqual({ status: "ok" });

    expect(tauri.invoke.mock.calls).toEqual([
      ["desktop_account_challenge", {
        challengeToken: "opaque-challenge",
        code: "123456",
      }],
      ["desktop_account_refresh"],
      ["desktop_account_logout"],
    ]);
  });

  it("returns same-origin API responses through the bounded native session transport", async () => {
    tauri.invoke.mockImplementation(async (command, args) => {
      if (command !== "desktop_api_request") return undefined;
      const metadata = new TextEncoder().encode(JSON.stringify({
        status: 200,
        status_text: "OK",
        headers: [["content-type", "application/json"]],
      }));
      const body = new TextEncoder().encode('{"status":"ok"}');
      const envelope = new Uint8Array(8 + metadata.byteLength + body.byteLength);
      envelope.set([0x42, 0x41, 0x50, 0x49]);
      new DataView(envelope.buffer).setUint32(4, metadata.byteLength, true);
      envelope.set(metadata, 8);
      envelope.set(body, 8 + metadata.byteLength);
      return envelope;
    });
    const desktop = await import("../src/desktop");

    const response = await desktop.desktopApiFetch(
      "https://kernel.boltrig.test/v1/devices?limit=10",
      { headers: { accept: "application/json" } },
    );
    await expect(response.json()).resolves.toEqual({ status: "ok" });
    expect(response.url).toBe("https://kernel.boltrig.test/v1/devices?limit=10");
    expect(tauri.invoke).toHaveBeenCalledWith("desktop_api_request", expect.objectContaining({
      method: "GET",
      path: "/v1/devices?limit=10",
      headers: [["accept", "application/json"]],
      body: [],
    }));
    expect(JSON.stringify(tauri.invoke.mock.calls)).not.toContain("boltrig_session");
  });

  it("refuses cross-origin and non-API native requests before invoking Rust", async () => {
    const desktop = await import("../src/desktop");
    await expect(desktop.desktopApiFetch("https://attacker.invalid/v1/devices"))
      .rejects.toThrow("desktop_api_path_invalid");
    await expect(desktop.desktopApiFetch("https://kernel.boltrig.test/healthz"))
      .rejects.toThrow("desktop_api_path_invalid");
    expect(tauri.invoke).not.toHaveBeenCalled();
  });

  it("rejects malformed native response envelopes and pre-aborted requests", async () => {
    tauri.invoke.mockResolvedValue(new Uint8Array([0x42, 0x41, 0x44, 0x21]));
    const desktop = await import("../src/desktop");
    await expect(desktop.desktopApiFetch("https://kernel.boltrig.test/v1/devices"))
      .rejects.toThrow("desktop_api_response_invalid");

    tauri.invoke.mockClear();
    const abort = new AbortController();
    abort.abort();
    await expect(desktop.desktopApiFetch(
      "https://kernel.boltrig.test/v1/devices",
      { signal: abort.signal },
    )).rejects.toMatchObject({ name: "AbortError" });
    expect(tauri.invoke).not.toHaveBeenCalled();
  });

  it("passes the one-time code and exact verifier only to native enrollment", async () => {
    tauri.invoke.mockResolvedValue({
      device_id: "device_1",
      label: "Office Mac",
      public_key_fingerprint: "f".repeat(64),
      session_expires_at: "2030-01-02T00:00:00Z",
      lease_verifier_key_id: enrollment.lease_verifier.key_id,
    });
    const desktop = await import("../src/desktop");
    await desktop.completeDesktopEnrollment(enrollment);
    expect(tauri.invoke).toHaveBeenCalledWith("complete_device_enrollment", {
      apiOrigin: "https://kernel.boltrig.test",
      authorizationCode: "one-time-code",
      expectedVerifier: enrollment.lease_verifier,
    });
    expect(JSON.stringify(tauri.invoke.mock.calls[0])).not.toContain("session_token");
  });

  it("subscribes only to the native status and bounded lease-terminal events", async () => {
    tauri.listen.mockResolvedValue(vi.fn());
    const desktop = await import("../src/desktop");
    await desktop.listenDesktopDeviceStatus(vi.fn());
    await desktop.listenDeviceLeaseTerminals(vi.fn());
    expect(tauri.listen.mock.calls.map((call) => call[0])).toEqual([
      "boltrig://device-agent-status",
      "boltrig://device-lease-terminal",
    ]);
  });

  it("uses only fixed native updater commands and an exact reported version", async () => {
    tauri.invoke
      .mockResolvedValueOnce({
        state: "ready",
        current_version: "0.1.0",
        target: "linux-x86_64",
        endpoint_origin: "https://releases.boltrig.test",
        public_key_fingerprint: "f".repeat(64),
        reason: null,
      })
      .mockResolvedValueOnce({
        status: "available",
        current_version: "0.1.0",
        version: "0.2.0",
        notes: "Security update",
        published_at: null,
      })
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce(undefined);
    const desktop = await import("../src/desktop");

    await desktop.desktopUpdateReadiness();
    await desktop.checkDesktopUpdate();
    await desktop.installDesktopUpdate("0.2.0", vi.fn());
    await desktop.restartDesktopAfterUpdate();

    expect(tauri.invoke.mock.calls.map((call) => call[0])).toEqual([
      "desktop_update_readiness",
      "check_desktop_update",
      "install_desktop_update",
      "restart_desktop_after_update",
    ]);
    expect(tauri.invoke.mock.calls[2]?.[1]).toMatchObject({
      expectedVersion: "0.2.0",
    });
    expect(tauri.invoke.mock.calls[2]?.[1]).not.toHaveProperty("endpoint");
    expect(tauri.invoke.mock.calls[2]?.[1]).not.toHaveProperty("publicKey");
    expect(tauri.invoke.mock.calls[2]?.[1]).not.toHaveProperty("signature");
  });

  it("distinguishes a saved artifact, native cancellation, and web fallback", async () => {
    tauri.invoke
      .mockResolvedValueOnce("opaque-native-handle")
      .mockResolvedValueOnce(null);
    const desktop = await import("../src/desktop");

    expect(await desktop.materializeArtifact(
      "brief.md",
      new Uint8Array([1, 2, 3]),
    )).toEqual({
      status: "saved",
      handle: "opaque-native-handle",
    });
    expect(await desktop.materializeArtifact(
      "brief.md",
      new Uint8Array([1, 2, 3]),
    )).toEqual({ status: "cancelled" });

    expect(tauri.invoke.mock.calls.map((call) => call[0])).toEqual([
      "materialize_artifact",
      "materialize_artifact",
    ]);
  });

  it("uses only an exact opaque state for the native OAuth return channel", async () => {
    const opaqueState = "s".repeat(48);
    tauri.invoke
      .mockResolvedValueOnce({
        state: "ready",
        callback_uri: "boltrig-worker://oauth/callback",
        provider_exchange: "unavailable",
        reason: null,
      })
      .mockResolvedValueOnce(undefined)
      .mockResolvedValueOnce({
        status: "authorization_returned",
        integration_id: "tickets",
        state: opaqueState,
        result: "r".repeat(48),
        provider_exchange: "unavailable",
      })
      .mockResolvedValueOnce(undefined);
    const desktop = await import("../src/desktop");

    await desktop.desktopOAuthReturnReadiness();
    await desktop.armDesktopOAuthReturn(
      "tickets",
      opaqueState,
      "2030-01-01T00:05:00Z",
    );
    await desktop.takeDesktopOAuthReturn("tickets", opaqueState);
    await desktop.cancelDesktopOAuthReturn("tickets", opaqueState);
    await desktop.listenDesktopOAuthReturns(vi.fn());

    expect(tauri.invoke.mock.calls.map((call) => call[0])).toEqual([
      "desktop_oauth_return_readiness",
      "arm_desktop_oauth_return",
      "take_desktop_oauth_return",
      "cancel_desktop_oauth_return",
    ]);
    expect(tauri.listen).toHaveBeenCalledWith(
      "boltrig://oauth-return",
      expect.any(Function),
    );
    const serialized = JSON.stringify(tauri.invoke.mock.calls);
    expect(serialized).not.toContain("authorizationUrl");
    expect(serialized).not.toContain("accessToken");
    expect(serialized).not.toContain("refreshToken");
    expect(serialized).not.toContain("providerCode");
  });

  it("does not call native commands from a browser runtime", async () => {
    Reflect.deleteProperty(window, "__TAURI_INTERNALS__");
    const desktop = await import("../src/desktop");
    expect(desktop.hasDesktopRuntime()).toBe(false);
    expect(await desktop.desktopDeviceStatus()).toBeNull();
    expect(await desktop.takeDesktopReadResult("lease_1")).toBeNull();
    expect(await desktop.desktopUpdateReadiness()).toEqual({
      runtime: "web",
      state: "unavailable",
      current_version: "0.1.0-beta.1",
      target: null,
      endpoint_origin: null,
      public_key_fingerprint: null,
      reason: "desktop_runtime_required",
    });
    expect(await desktop.desktopOAuthReturnReadiness()).toEqual({
      runtime: "web",
      state: "unavailable",
      callback_uri: null,
      provider_exchange: "unavailable",
      reason: "desktop_runtime_required",
    });
    expect(await desktop.materializeArtifact(
      "brief.md",
      new Uint8Array([1]),
    )).toEqual({ status: "web_fallback" });
    expect(tauri.invoke).not.toHaveBeenCalled();
  });
});
