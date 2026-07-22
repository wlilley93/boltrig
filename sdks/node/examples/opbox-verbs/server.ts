/**
 * Worked example: "Opbox" exposes its verbs to a Boltrig kernel.
 *
 * Five verbs over in-memory demo data. `inventory.adjust` is declared
 * high-consequence (surfaced as MCP annotations; see the README for how to
 * re-assert "high" kernel-side after activation, since today's consumer maps
 * every consumed verb to consequence "low").
 *
 * Run:
 *   export OPBOX_MCP_TOKEN=$(openssl rand -hex 24)   # the bearer the KERNEL will present
 *   npm run build && node dist/examples/opbox-verbs/server.js
 *
 * The token comes from the environment and is never logged. The kernel does
 * not get this value at registration time - registration passes a
 * credential_ref NAMING a secret the kernel resolves per call.
 */

import { createBoltrigMcpServer, VerbError, type VerbDef } from "../../src/index.js";

interface Order {
  id: string;
  customerId: string;
  sku: string;
  quantity: number;
  status: "pending" | "paid" | "shipped";
}

const customers = new Map<string, { id: string; name: string; email: string }>([
  ["cust-1", { id: "cust-1", name: "Aster Clinic", email: "ops@aster.example" }],
  ["cust-2", { id: "cust-2", name: "Blue Finch Deli", email: "it@bluefinch.example" }],
]);

const orders = new Map<string, Order>([
  ["ord-1001", { id: "ord-1001", customerId: "cust-1", sku: "WIDGET-9", quantity: 12, status: "paid" }],
  ["ord-1002", { id: "ord-1002", customerId: "cust-2", sku: "GADGET-2", quantity: 3, status: "pending" }],
]);

const inventory = new Map<string, number>([
  ["WIDGET-9", 140],
  ["GADGET-2", 57],
]);

let orderSeq = 1003;

function asString(value: unknown, name: string): string {
  if (typeof value !== "string" || !value) throw new VerbError(`${name} must be a non-empty string`);
  return value;
}

function asInt(value: unknown, name: string): number {
  if (typeof value !== "number" || !Number.isInteger(value)) throw new VerbError(`${name} must be an integer`);
  return value;
}

const verbs: VerbDef[] = [
  {
    name: "orders.list",
    description: "List Opbox orders, optionally filtered by status.",
    schema: {
      type: "object",
      properties: {
        status: { type: "string", enum: ["pending", "paid", "shipped"] },
        limit: { type: "integer", minimum: 1, maximum: 100 },
      },
      additionalProperties: false,
    },
    handler: (params) => {
      const status = params.status === undefined ? null : asString(params.status, "status");
      const limit = params.limit === undefined ? 50 : asInt(params.limit, "limit");
      const rows = [...orders.values()]
        .filter((o) => status === null || o.status === status)
        .slice(0, limit);
      return { orders: rows, count: rows.length };
    },
  },
  {
    name: "orders.get",
    description: "Fetch one Opbox order by id.",
    schema: {
      type: "object",
      properties: { order_id: { type: "string" } },
      required: ["order_id"],
      additionalProperties: false,
    },
    handler: (params) => {
      const order = orders.get(asString(params.order_id, "order_id"));
      if (!order) throw new VerbError("order not found");
      return { order };
    },
  },
  {
    name: "orders.create",
    description: "Create an Opbox order for a known customer and SKU.",
    schema: {
      type: "object",
      properties: {
        customer_id: { type: "string" },
        sku: { type: "string" },
        quantity: { type: "integer", minimum: 1 },
      },
      required: ["customer_id", "sku", "quantity"],
      additionalProperties: false,
    },
    handler: (params) => {
      const customerId = asString(params.customer_id, "customer_id");
      const sku = asString(params.sku, "sku");
      const quantity = asInt(params.quantity, "quantity");
      if (!customers.has(customerId)) throw new VerbError("customer not found");
      if (quantity < 1) throw new VerbError("quantity must be at least 1");
      const stock = inventory.get(sku) ?? 0;
      if (stock < quantity) throw new VerbError("insufficient inventory");
      const id = `ord-${orderSeq++}`;
      const order: Order = { id, customerId, sku, quantity, status: "pending" };
      orders.set(id, order);
      inventory.set(sku, stock - quantity);
      return { order };
    },
  },
  {
    name: "customers.lookup",
    description: "Look up an Opbox customer by id or exact email.",
    schema: {
      type: "object",
      properties: {
        customer_id: { type: "string" },
        email: { type: "string" },
      },
      additionalProperties: false,
    },
    handler: (params) => {
      const byId = params.customer_id === undefined ? null : customers.get(asString(params.customer_id, "customer_id"));
      if (byId) return { customer: byId };
      if (params.email !== undefined) {
        const email = asString(params.email, "email");
        const found = [...customers.values()].find((c) => c.email === email);
        if (found) return { customer: found };
      }
      throw new VerbError("customer not found");
    },
  },
  {
    name: "inventory.adjust",
    description: "Adjust on-hand inventory for a SKU by a signed delta. HIGH CONSEQUENCE: changes stock levels.",
    consequence: "high",
    schema: {
      type: "object",
      properties: {
        sku: { type: "string" },
        delta: { type: "integer" },
        reason: { type: "string" },
      },
      required: ["sku", "delta", "reason"],
      additionalProperties: false,
    },
    handler: (params) => {
      const sku = asString(params.sku, "sku");
      const delta = asInt(params.delta, "delta");
      asString(params.reason, "reason"); // required; an audit trail is the app's job
      if (!inventory.has(sku)) throw new VerbError("unknown sku");
      const next = (inventory.get(sku) as number) + delta;
      if (next < 0) throw new VerbError("adjustment would drive inventory negative");
      inventory.set(sku, next);
      return { sku, on_hand: next };
    },
  },
];

const server = await createBoltrigMcpServer({
  name: "opbox",
  version: "0.1.0",
  verbs,
  tokenEnv: "OPBOX_MCP_TOKEN",
  host: "127.0.0.1",
  port: Number(process.env.OPBOX_PORT ?? "0") || 0,
});

// The URL is routing data, safe to print. The token never is.
console.log(`opbox MCP server listening at ${server.url} (verbs: ${verbs.map((v) => v.name).join(", ")})`);

for (const sig of ["SIGINT", "SIGTERM"] as const) {
  process.once(sig, () => {
    void server.close().then(() => process.exit(0));
  });
}
