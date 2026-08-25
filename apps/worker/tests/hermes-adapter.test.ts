// @vitest-environment happy-dom

import { beforeEach, describe, expect, it, vi } from "vitest";

import { client, adapter } from "../src/hermes/client";
import { resetGatewayCache } from "../src/hermes/http";

const GATEWAY = "gate_1234567890abcdef1234567890abcdef";

function jsonOnce(body: unknown) {
  (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
    ok: true, status: 200, json: async () => body, clone: () => ({ json: async () => body }),
  });
}

function streamOnce(chunks: string[]) {
  (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
    ok: true,
    status: 200,
    body: new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk));
        controller.close();
      },
    }),
  });
}

/** The gateway lookup every cell call makes first. */
function gatewayOnce() {
  jsonOnce({ tenant_gateway_id: GATEWAY });
}

const calls = () => (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls;

describe("the Hermes adapter", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    vi.clearAllMocks();
    resetGatewayCache();
    sessionStorage.clear();
  });

  describe("what talks to the cell, and what does not", () => {
    it("sends a turn to the member's own cell", async () => {
      gatewayOnce();
      streamOnce(['event: run.started\ndata: {"run_id":"run_abc"}\n\n']);

      await adapter.streamChat({ conversation_id: "sess_1", message: "hello" }, vi.fn());

      expect(calls()[1][0]).toBe(`/api/cell/${GATEWAY}/api/sessions/sess_1/chat/stream`);
      expect(calls()[1][1]).toMatchObject({
        method: "POST", body: JSON.stringify({ content: "hello" }),
      });
    });

    it("remembers the run id, because nothing else can tell us it later", async () => {
      // No session response carries a run id and there is no run index: lose it
      // here and cancel, approvals and reattach are all unreachable.
      gatewayOnce();
      streamOnce(['event: run.started\ndata: {"run_id":"run_abc"}\n\n']);

      await adapter.streamChat({ conversation_id: "sess_1", message: "hi" }, vi.fn());

      expect(sessionStorage.getItem("boltrig_run_sess_1")).toBe("run_abc");
    });

    it("forgets the run id when the turn ends", async () => {
      gatewayOnce();
      streamOnce([
        'event: run.started\ndata: {"run_id":"run_abc"}\n\n',
        'event: run.completed\ndata: {"run_id":"run_abc"}\n\n',
      ]);

      await adapter.streamChat({ conversation_id: "sess_1", message: "hi" }, vi.fn());

      expect(sessionStorage.getItem("boltrig_run_sess_1")).toBeNull();
    });

    it("SETTINGS GO TO THE CONTROL PLANE, never through the cell proxy", async () => {
      // The regression this pins: /api/settings is a control-plane route and is
      // absent from cell_proxy.ALLOWED. Sent through /api/cell/{gw}/... it is
      // refused with 403 - and because AuthGate gates on meSettings(), that
      // presents as the whole application failing to render.
      jsonOnce({ user: { id: "u1", display_name: "Alice" } });
      jsonOnce({ settings: { "agent.character": "jarvis" } });

      const me = await adapter.meSettings();

      const urls = calls().map((call) => call[0]);
      expect(urls).toEqual(["/api/me", "/api/settings"]);
      expect(urls.some((url: string) => String(url).includes("/api/cell/"))).toBe(false);
      expect(me.profile.display_name).toBe("Alice");
      expect(me.settings["agent.character"]).toBe("jarvis");
    });

    it("says onboarding is already done, so the v1 wizard never opens", async () => {
      // The control plane ran its own onboarding before this bundle was served.
      // Without this key OnboardingGate reopens a six-step provider wizard that
      // configures nothing and cannot be completed.
      jsonOnce({ user: { id: "u1" } });
      jsonOnce({ settings: {} });

      const me = await adapter.meSettings();

      expect(me.settings["setup.onboarding_version"]).toBe(1);
    });

    it("signs in even when the settings endpoint is missing", async () => {
      jsonOnce({ user: { id: "u1", display_name: "Alice" } });
      (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        ok: false, status: 404, clone: () => ({ json: async () => ({}) }),
      });

      const me = await adapter.meSettings();

      expect(me.profile.display_name).toBe("Alice");
    });

    it("reads the cell's health, which is allowlisted", async () => {
      gatewayOnce();
      jsonOnce({ ok: true });

      await adapter.health();

      expect(calls()[1][0]).toBe(`/api/cell/${GATEWAY}/health/detailed`);
    });
  });

  describe("the absent-method policy", () => {
    it("reports a probed-but-unbacked method as ABSENT, not as an error", () => {
      // `typeof client.budgets !== "function"` is a synchronous property read
      // during render. Throwing there takes out the component; returning a
      // function makes the probe pass and the feature render itself broken.
      expect((client as unknown as Record<string, unknown>).budgets).toBeUndefined();
      expect(typeof (client as unknown as Record<string, unknown>).workspaces)
        .not.toBe("function");
    });

    it("rejects an unimplemented method rather than throwing on access", async () => {
      const call = (client as unknown as Record<string, () => Promise<unknown>>).auditTree;
      expect(typeof call).toBe("function");
      await expect(call()).rejects.toMatchObject({ status: 501 });
    });

    it("is not a thenable", async () => {
      // Awaiting the client, or returning it from an async function, reads
      // `.then`. A function there turns it into a promise that never settles.
      expect((client as unknown as Record<string, unknown>).then).toBeUndefined();
      await expect(Promise.resolve(client)).resolves.toBeDefined();
    });

    it("still answers the methods it does implement", () => {
      expect(typeof client.streamChat).toBe("function");
      expect(typeof client.meSettings).toBe("function");
    });
  });
});
