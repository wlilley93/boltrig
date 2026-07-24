import { test } from "node:test";
import assert from "node:assert/strict";
import {
  createBoltrigMcpServer,
  streamTurn,
  type FetchLike,
  type VerbContext,
  type VerbDef,
} from "../src/index.js";

// GAP G1 (per-user bearer reaches the verb handler) + GAP G2 (onBehalfBearer as a
// first-class streamTurn option). Both are additive: without resolveIdentity the
// server keeps its exact static-token behaviour, and without onBehalfBearer the
// chat body is unchanged.

const TOKEN_ENV = "BOLTRIG_G1G2_TEST_TOKEN";
const TOKEN = "static-token-value";

function captureVerb(sink: { ctx?: VerbContext | undefined }): VerbDef {
  return {
    name: "echo.ctx",
    description: "captures the ctx it was called with",
    schema: { type: "object", properties: {}, additionalProperties: true },
    handler: (_params, ctx) => {
      sink.ctx = ctx;
      return { identity: ctx?.identity ?? null };
    },
  };
}

// --- G1 ---------------------------------------------------------------------

test("G1: resolveIdentity authorizes a per-user bearer and passes identity to the handler", async () => {
  process.env[TOKEN_ENV] = TOKEN;
  const sink: { ctx?: VerbContext | undefined } = {};
  const server = await createBoltrigMcpServer({
    name: "t",
    version: "1",
    tokenEnv: TOKEN_ENV,
    verbs: [captureVerb(sink)],
    resolveIdentity: (bearer) =>
      bearer === "user-bearer" ? { bearer, actorId: "actor-1", workspaceId: "ws-1" } : null,
  });
  const resp = await server.handleRpc(
    { jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "echo.ctx", arguments: {} } },
    "user-bearer",
  );
  assert.equal(resp.error, undefined);
  assert.equal(sink.ctx?.bearer, "user-bearer");
  assert.equal(sink.ctx?.identity?.actorId, "actor-1");
  assert.equal(sink.ctx?.identity?.workspaceId, "ws-1");
  await server.close();
  delete process.env[TOKEN_ENV];
});

test("G1: resolveIdentity rejects an unresolvable bearer with -32001/401", async () => {
  process.env[TOKEN_ENV] = TOKEN;
  const server = await createBoltrigMcpServer({
    name: "t",
    version: "1",
    tokenEnv: TOKEN_ENV,
    verbs: [captureVerb({})],
    resolveIdentity: () => null,
  });
  const resp = await server.handleRpc(
    { jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "echo.ctx", arguments: {} } },
    "any-bearer",
  );
  assert.equal(resp.error?.code, -32001);
  assert.equal(resp.httpStatus, 401);
  await server.close();
  delete process.env[TOKEN_ENV];
});

test("G1: WITHOUT a hook the static-token path is unchanged and ctx is undefined", async () => {
  process.env[TOKEN_ENV] = TOKEN;
  const sink: { ctx?: VerbContext | undefined } = {};
  const server = await createBoltrigMcpServer({
    name: "t",
    version: "1",
    tokenEnv: TOKEN_ENV,
    verbs: [captureVerb(sink)],
  });
  // wrong token -> unauthorized (static compare unchanged)
  const bad = await server.handleRpc(
    { jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "echo.ctx", arguments: {} } },
    "wrong-token",
  );
  assert.equal(bad.error?.code, -32001);
  // right token -> ok, and the handler is called with ctx === undefined
  const good = await server.handleRpc(
    { jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "echo.ctx", arguments: {} } },
    TOKEN,
  );
  assert.equal(good.error, undefined);
  assert.equal(sink.ctx, undefined);
  await server.close();
  delete process.env[TOKEN_ENV];
});

// --- G2 ---------------------------------------------------------------------

function streamFetch(): { fetch: FetchLike; calls: Array<{ body: Record<string, unknown> }> } {
  const calls: Array<{ body: Record<string, unknown> }> = [];
  const fetch: FetchLike = async (_input, init) => {
    calls.push({
      body: init?.body ? (JSON.parse(init.body as string) as Record<string, unknown>) : {},
    });
    return {
      status: 200,
      headers: { get: () => null },
      body: new ReadableStream<Uint8Array>({ start: (c) => c.close() }),
      json: async () => ({}),
      text: async () => "",
    } as unknown as Awaited<ReturnType<FetchLike>>;
  };
  return { fetch, calls };
}

async function drain(gen: AsyncGenerator<unknown>): Promise<void> {
  const it = gen[Symbol.asyncIterator]();
  for (let r = await it.next(); !r.done; r = await it.next()) {
    /* empty stream */
  }
}

test("G2: onBehalfBearer rides in the chat turn body as on_behalf_bearer", async () => {
  const { fetch, calls } = streamFetch();
  await drain(streamTurn({ server: "http://k/", token: "t", fetch, message: "hi", onBehalfBearer: "OBO-1" }));
  assert.equal(calls[0]?.body.on_behalf_bearer, "OBO-1");
  assert.equal(calls[0]?.body.message, "hi");
});

test("G2: on_behalf_bearer is absent when onBehalfBearer is not set", async () => {
  const { fetch, calls } = streamFetch();
  await drain(streamTurn({ server: "http://k/", token: "t", fetch, message: "hi" }));
  assert.equal("on_behalf_bearer" in (calls[0]?.body ?? {}), false);
});
