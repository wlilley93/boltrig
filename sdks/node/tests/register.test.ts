import { test } from "node:test";
import assert from "node:assert/strict";
import {
  activateAdapter,
  isPendingHuman,
  listAdapters,
  login,
  mintPat,
  registerMcpServer,
  KernelApiError,
  type FetchLike,
} from "../src/index.js";

interface RecordedCall {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: Record<string, unknown>;
}

/** A mocked fetch: records the call, replies with the queued responses. */
function mockFetch(...replies: Array<{ status: number; payload: unknown; setCookies?: string[] }>): {
  fetch: FetchLike;
  calls: RecordedCall[];
} {
  const calls: RecordedCall[] = [];
  const queue = [...replies];
  const fetchMock: FetchLike = async (input, init) => {
    const reply = queue.shift();
    if (!reply) throw new Error("mock fetch: no reply queued");
    calls.push({
      url: input,
      method: init?.method ?? "GET",
      headers: init?.headers ?? {},
      body: init?.body ? (JSON.parse(init.body) as Record<string, unknown>) : {},
    });
    return {
      status: reply.status,
      headers: {
        get: () => null,
        getSetCookie: () => reply.setCookies ?? [],
      },
      json: async () => reply.payload,
      text: async () => JSON.stringify(reply.payload),
    };
  };
  return { fetch: fetchMock, calls };
}

const SERVER = "http://kernel.test/";
const TOKEN = "pat-secret";

test("registerMcpServer shapes the governed call: /v1/mcp/servers, refs only", async () => {
  const { fetch: f, calls } = mockFetch({
    status: 200,
    payload: { status: "ok", registered: "mcp_server", id: "opbox-acme", activated: false },
  });
  const outcome = await registerMcpServer({
    server: SERVER,
    token: TOKEN,
    fetch: f,
    id: "opbox-acme",
    url: "http://127.0.0.1:8790/",
    credentialRef: "OPBOX_MCP_TOKEN",
  });
  const call = calls[0] as RecordedCall;
  // No trailing-slash double path; the governed control route, not a side door.
  assert.equal(call.url, "http://kernel.test/v1/mcp/servers");
  assert.equal(call.method, "POST");
  assert.equal(call.headers.authorization, `Bearer ${TOKEN}`);
  assert.deepEqual(call.body, { id: "opbox-acme", url: "http://127.0.0.1:8790/", credential_ref: "OPBOX_MCP_TOKEN" });
  // No parameter could carry raw secret material.
  assert.ok(!("token" in call.body) && !("credential" in call.body));
  assert.equal(outcome.status, "ok");
  if (outcome.status === "ok") {
    assert.equal(outcome.activated, false);
    assert.match(outcome.next, /INERT/);
  }
});

test("registerMcpServer passes a pending_human (HITL-gated) outcome through", async () => {
  const { fetch: f } = mockFetch({
    status: 202,
    payload: { status: "pending_human", hitl_request_id: "hitl-123" },
  });
  const outcome = await registerMcpServer({
    server: SERVER,
    token: TOKEN,
    fetch: f,
    id: "opbox-acme",
    url: "http://127.0.0.1:8790/",
  });
  assert.ok(isPendingHuman(outcome));
  if (isPendingHuman(outcome)) assert.equal(outcome.hitlRequestId, "hitl-123");
});

test("registerMcpServer surfaces kernel refusals without the token", async () => {
  const { fetch: f } = mockFetch({
    status: 403,
    payload: { status: "error", reason: "grant denied" },
  });
  await assert.rejects(
    () => registerMcpServer({ server: SERVER, token: TOKEN, fetch: f, id: "x", url: "http://y/" }),
    (error: unknown) => {
      assert.ok(error instanceof KernelApiError);
      assert.match(error.message, /authentication failed \(HTTP 403\)/);
      assert.ok(!error.message.includes(TOKEN));
      return true;
    },
  );
});

test("activateAdapter re-applies an approval via the x-boltrig-approval-id header", async () => {
  const { fetch: f, calls } = mockFetch({
    status: 200,
    payload: { status: "ok", id: "opbox-acme", activated: true, verbs: ["opbox-acme.orders.list"] },
  });
  const outcome = await activateAdapter({
    server: SERVER,
    token: TOKEN,
    fetch: f,
    adapterId: "opbox-acme",
    approvalId: "hitl-123",
  });
  const call = calls[0] as RecordedCall;
  assert.equal(call.url, "http://kernel.test/v1/adapters/opbox-acme/activate");
  assert.equal(call.headers["x-boltrig-approval-id"], "hitl-123");
  assert.equal(outcome.status, "ok");
  if (outcome.status === "ok") assert.deepEqual(outcome.verbs, ["opbox-acme.orders.list"]);
});

test("activateAdapter passes pending_human through (the review gate drives HITL)", async () => {
  const { fetch: f } = mockFetch({
    status: 202,
    payload: { status: "pending_human", hitl_request_id: "hitl-9" },
  });
  const outcome = await activateAdapter({ server: SERVER, token: TOKEN, fetch: f, adapterId: "opbox-acme" });
  assert.ok(isPendingHuman(outcome));
});

test("mintPat posts to /v1/me/tokens with the session cookie", async () => {
  const { fetch: f, calls } = mockFetch({
    status: 200,
    payload: { status: "ok", id: "pat-1", name: "opbox-sdk", scope: ["invoke"], secret: "shown-once" },
  });
  const pat = await mintPat({
    server: SERVER,
    cookie: "boltrig_session=abc; boltrig_csrf=def",
    fetch: f,
    name: "opbox-sdk",
    ttlDays: 30,
  });
  const call = calls[0] as RecordedCall;
  assert.equal(call.url, "http://kernel.test/v1/me/tokens");
  assert.equal(call.headers.cookie, "boltrig_session=abc; boltrig_csrf=def");
  assert.equal(call.headers.authorization, undefined);
  assert.deepEqual(call.body, { name: "opbox-sdk", ttl_days: 30 });
  assert.equal(pat.secret, "shown-once");
});

test("login posts credentials once and returns the session cookie", async () => {
  const { fetch: f, calls } = mockFetch({
    status: 200,
    payload: { status: "ok", user: { id: "u-1" } },
    setCookies: ["boltrig_session=abc; HttpOnly; Path=/", "boltrig_csrf=def; Path=/"],
  });
  const session = await login({ server: SERVER, email: "owner@example.com", password: "pw", fetch: f });
  const call = calls[0] as RecordedCall;
  assert.equal(call.url, "http://kernel.test/v1/auth/login");
  assert.deepEqual(call.body, { email: "owner@example.com", password: "pw" });
  assert.equal(session.cookie, "boltrig_session=abc; boltrig_csrf=def");
});

test("login maps 2fa_required to a clear error", async () => {
  const { fetch: f } = mockFetch({ status: 200, payload: { status: "2fa_required", challenge_token: "x" } });
  await assert.rejects(
    () => login({ server: SERVER, email: "o@e.com", password: "pw", fetch: f }),
    /second factor/,
  );
});

test("listAdapters reads the inventory (registration rows + review-gate state)", async () => {
  const { fetch: f } = mockFetch({
    status: 200,
    payload: {
      adapters: [{ id: "opbox-acme", runtime: "mcp", version: "1.0.0", source: "manual", activated: false, health: "unknown" }],
    },
  });
  const adapters = await listAdapters({ server: SERVER, token: TOKEN, fetch: f });
  assert.deepEqual(adapters, [{ id: "opbox-acme", runtime: "mcp", activated: false, health: "unknown" }]);
});
