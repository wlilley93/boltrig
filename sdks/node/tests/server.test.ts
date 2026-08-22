import { test } from "node:test";
import assert from "node:assert/strict";
import {
  createBoltrigMcpServer,
  validateVerbTable,
  VerbError,
  type VerbDef,
} from "../src/index.js";

const TOKEN_ENV = "BOLTRIG_SDK_TEST_TOKEN";
const TOKEN = "test-token-value";

function sampleVerbs(): VerbDef[] {
  return [
    {
      name: "orders.list",
      description: "List orders.",
      schema: { type: "object", properties: {} },
      handler: () => ({ orders: [], count: 0 }),
    },
    {
      name: "orders.get",
      description: "Get one order.",
      schema: { type: "object", properties: { order_id: { type: "string" } }, required: ["order_id"] },
      handler: (params) => {
        if (params.order_id === "missing") throw new VerbError("order not found");
        return { order: { id: params.order_id } };
      },
    },
    {
      name: "inventory.adjust",
      description: "Adjust stock.",
      consequence: "high",
      implements: "inventory.stock.adjust",
      schema: { type: "object", properties: { delta: { type: "integer" } } },
      handler: () => {
        throw new Error("boom: internal detail");
      },
    },
  ];
}

async function makeServer(): Promise<Awaited<ReturnType<typeof createBoltrigMcpServer>>> {
  process.env[TOKEN_ENV] = TOKEN;
  return createBoltrigMcpServer({
    name: "test-app",
    version: "0.0.1",
    verbs: sampleVerbs(),
    tokenEnv: TOKEN_ENV,
    port: 0,
  });
}

// --- verb-table validation -------------------------------------------------

test("validation: rejects an empty verb table", () => {
  assert.throws(() => validateVerbTable([]), /non-empty/);
});

test("validation: rejects bad names, reserved prefixes, duplicates", () => {
  const base = sampleVerbs()[0] as VerbDef;
  assert.throws(() => validateVerbTable([{ ...base, name: "not ok!" }]), /invalid/);
  assert.throws(() => validateVerbTable([{ ...base, name: "control.evil" }]), /reserved/);
  assert.throws(() => validateVerbTable([{ ...base, name: ".hidden" }]), /invalid/);
  assert.throws(() => validateVerbTable([base, { ...base }]), /duplicate/);
});

test("validation: requires description, object schema, handler", () => {
  const base = sampleVerbs()[0] as VerbDef;
  assert.throws(() => validateVerbTable([{ ...base, description: " " }]), /description/);
  assert.throws(
    () => validateVerbTable([{ ...base, schema: { type: "array" } }]),
    /"type": "object"/,
  );
  assert.throws(
    () => validateVerbTable([{ ...base, handler: 42 as unknown as VerbDef["handler"] }]),
    /handler/,
  );
  assert.throws(
    () => validateVerbTable([{ ...base, consequence: "spicy" as never }]),
    /consequence/,
  );
  assert.throws(
    () => validateVerbTable([{ ...base, implements: "not a capability" }]),
    /implements/,
  );
  // A pinned claim is refused rather than reinterpreted: a version this side has
  // not agreed to must not be silently read as the one it has.
  assert.throws(
    () => validateVerbTable([{ ...base, implements: "crm.contact.search@2" }]),
    /pin a version/,
  );
});

test("server refuses to start without its token env var (fail closed)", async () => {
  delete process.env[TOKEN_ENV];
  await assert.rejects(
    () =>
      createBoltrigMcpServer({
        name: "x",
        version: "1",
        verbs: sampleVerbs(),
        tokenEnv: TOKEN_ENV,
      }),
    /not set/,
  );
});

// --- envelope shape (what mcp_consumer.py parses) ---------------------------

test("tools/list maps the verb table to MCP tools with inputSchema", async () => {
  const server = await makeServer();
  const resp = await server.handleRpc(
    { jsonrpc: "2.0", id: 1, method: "tools/list", params: {} },
    TOKEN,
  );
  await server.close();
  const tools = (resp.result?.tools ?? []) as Array<Record<string, unknown>>;
  assert.deepEqual(
    tools.map((t) => t.name).sort(),
    ["inventory.adjust", "orders.get", "orders.list"],
  );
  const adjust = tools.find((t) => t.name === "inventory.adjust") as Record<string, unknown>;
  assert.equal((adjust.inputSchema as Record<string, unknown>).type, "object");
  // High consequence surfaces as the consumer's per-tool hint AND an annotation.
  assert.equal(adjust.consequence, "high");
  assert.equal((adjust.annotations as Record<string, unknown>).destructiveHint, true);
  // The capability claim travels too, unpinned. Boltrig records it as a PROPOSED
  // binding: it routes nothing and governs nothing until a human approves it.
  assert.equal(adjust.implements, "inventory.stock.adjust");
  assert.equal("implements" in (tools.find((t) => t.name === "orders.list") ?? {}), false);
  // An UNMARKED verb sends no consequence at all. It used to default to "low"
  // here, which turned "the app declared nothing" into a positive claim of
  // safety on the wire - and the consumer takes an explicit consequence at its
  // word, so that silently defeated its fail-closed rule (a tool publishing no
  // evidence reads HIGH and gets the human gate).
  const list = tools.find((t) => t.name === "orders.list") as Record<string, unknown>;
  assert.equal("consequence" in list, false);
  assert.equal(list.consequence, undefined);
});

test("tools/call success wraps output in the _boltrig envelope", async () => {
  const server = await makeServer();
  const resp = await server.handleRpc(
    { jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "orders.get", arguments: { order_id: "ord-1" } } },
    TOKEN,
  );
  await server.close();
  const result = resp.result as Record<string, unknown>;
  assert.equal(result.isError, false);
  const boltrig = result._boltrig as Record<string, unknown>;
  assert.equal(boltrig.status, "ok");
  // The consumer reads result._boltrig.output verbatim (mcp_consumer.py:142).
  assert.deepEqual(boltrig.output, { order: { id: "ord-1" } });
  // The content fallback holds the same output as JSON text.
  const content = result.content as Array<Record<string, unknown>>;
  assert.equal(content[0]?.type, "text");
  assert.deepEqual(JSON.parse(String(content[0]?.text)), { order: { id: "ord-1" } });
});

test("VerbError maps to isError + _boltrig.reason (consumer's typed failure)", async () => {
  const server = await makeServer();
  const resp = await server.handleRpc(
    { jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "orders.get", arguments: { order_id: "missing" } } },
    TOKEN,
  );
  await server.close();
  const result = resp.result as Record<string, unknown>;
  assert.equal(result.isError, true);
  const boltrig = result._boltrig as Record<string, unknown>;
  // The consumer maps this to ErrorClass.INVALID with this reason (mcp_consumer.py:138-141).
  assert.equal(boltrig.reason, "order not found");
});

test("unexpected handler throws map to a generic reason (no internal leak)", async () => {
  const server = await makeServer();
  const resp = await server.handleRpc(
    { jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "inventory.adjust", arguments: {} } },
    TOKEN,
  );
  await server.close();
  const boltrig = (resp.result as Record<string, unknown>)._boltrig as Record<string, unknown>;
  assert.equal(boltrig.reason, "verb handler error");
  assert.ok(!JSON.stringify(resp).includes("boom"));
});

test("unknown verb / unknown method / bad request shapes", async () => {
  const server = await makeServer();
  const unknownVerb = await server.handleRpc(
    { jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "nope", arguments: {} } },
    TOKEN,
  );
  assert.equal((unknownVerb.result as Record<string, unknown>).isError, true);

  const unknownMethod = await server.handleRpc(
    { jsonrpc: "2.0", id: 9, method: "resources/list", params: {} },
    TOKEN,
  );
  assert.equal(unknownMethod.error?.code, -32601);

  const badRequest = await server.handleRpc({ method: "tools/list" }, TOKEN);
  assert.equal(badRequest.error?.code, -32600);
  await server.close();
});

test("auth: every method requires the bearer, compared in constant time", async () => {
  const server = await makeServer();
  for (const bearer of [null, "wrong-token"]) {
    const resp = await server.handleRpc(
      { jsonrpc: "2.0", id: 1, method: "tools/list", params: {} },
      bearer,
    );
    assert.equal(resp.error?.code, -32001);
    assert.equal(resp.httpStatus, 401);
    assert.equal(resp.result, undefined);
  }
  // Even initialize is gated (defense in depth).
  const init = await server.handleRpc({ jsonrpc: "2.0", id: 1, method: "initialize" }, null);
  assert.equal(init.error?.code, -32001);
  await server.close();
});

test("initialize / ping mirror the kernel face shapes", async () => {
  const server = await makeServer();
  const init = await server.handleRpc({ jsonrpc: "2.0", id: 1, method: "initialize" }, TOKEN);
  const result = init.result as Record<string, unknown>;
  assert.equal(result.protocolVersion, "2024-11-05");
  assert.equal((result.serverInfo as Record<string, unknown>).name, "test-app");
  const ping = await server.handleRpc({ jsonrpc: "2.0", id: 3, method: "ping" }, TOKEN);
  assert.deepEqual(ping.result, {});
  await server.close();
});
