/**
 * Server scaffold: expose an app's verbs as a Boltrig-consumable MCP server.
 *
 * The kernel side of this contract is `boltrig/adapters/mcp_consumer.py`. What
 * it actually sends (read before changing anything here):
 *
 *  - ONE plain JSON-RPC 2.0 POST per call to the registered URL, no
 *    `initialize` handshake, no SSE, no session headers (mcp_consumer.py:159-185).
 *  - Auth is the header `x-boltrig-mcp-token: <bearer>` where the bearer is
 *    resolved KERNEL-SIDE per call from the credential seam (mcp_consumer.py:183).
 *    This server never sees a raw token at registration time and must never
 *    log the one it receives.
 *  - It calls `tools/list` (discovery) and `tools/call` (execution), and parses
 *    the result envelope as (mcp_consumer.py:136-154):
 *      result._boltrig.output          -> structured verb output
 *      result.isError == true          -> typed failure, reason from
 *                                         result._boltrig.reason
 *      no _boltrig                     -> fallback: join content[] text blocks
 *                                         into {"text": ...}
 *
 * The envelope emitted here is byte-compatible with the kernel's own MCP face
 * (`boltrig/kernel/mcp.py`, `_ok` / `_call_tool`).
 *
 * Why not `@modelcontextprotocol/sdk`: its StreamableHTTP transport mandates
 * an `initialize` handshake and `Accept: application/json, text/event-stream`;
 * the consumer sends neither, so the official transport would 406 every call.
 * The kernel's own MCP face is likewise a thin hand-rolled JSON-RPC face
 * (kernel/mcp.py docstring), so this scaffold mirrors that idiom with zero
 * runtime dependencies.
 */

import { createHash, timingSafeEqual } from "node:crypto";
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";

export const PROTOCOL_VERSION = "2024-11-05"; // mirrors kernel/mcp.py

/** Reserved core verb prefixes (mirrors control_safety.py:_RESERVED_VERB_PREFIXES). */
const RESERVED_VERB_PREFIXES = ["boltrig.", "chat.", "control.", "kernel.", "system."];
/** Same charset rule as the kernel's adapter-id rule (control_safety.py:_ADAPTER_ID). */
const VERB_NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

/** A handler-raised, user-safe failure. Mapped to the typed error envelope the
 * consumer understands (`isError: true`, `_boltrig.reason`). Any OTHER throw is
 * reported as a generic "verb handler error" so internals never leak. */
export class VerbError extends Error {
  constructor(
    message: string,
    readonly status: "error" | "denied" = "error",
  ) {
    super(message);
    this.name = "VerbError";
  }
}

export type VerbHandler = (
  params: Record<string, unknown>,
) => unknown | Promise<unknown>;

export interface VerbDef {
  /** Dotted "noun.verb" id, e.g. "orders.list". The consumer derives the noun
   * as everything before the first dot (mcp_consumer.py:88). */
  name: string;
  description: string;
  /** JSON Schema for the params object; forwarded verbatim as the MCP
   * inputSchema and used by the KERNEL's param validation at dispatch. */
  schema: Record<string, unknown>;
  handler: VerbHandler;
  /** Declared consequence. NOTE: today's consumer maps every consumed verb to
   * consequence "low" (mcp_consumer.py:85-93 does not propagate it); this flag
   * is surfaced as MCP tool annotations and documented so an operator can
   * re-assert "high" kernel-side after activation (see README). */
  consequence?: "low" | "high";
}

export interface BoltrigMcpServerOptions {
  name: string;
  version: string;
  verbs: VerbDef[];
  /** Name of the env var holding the bearer token this server requires.
   * The VALUE is read from the environment and never logged. Defaults to
   * BOLTRIG_MCP_TOKEN. Fail-closed: the server refuses to start when unset. */
  tokenEnv?: string;
  /** Bind address. Default 127.0.0.1 - an app SDK server should not be
   * internet-facing; the kernel reaches it over the local/private network. */
  host?: string;
  port?: number;
}

export interface BoltrigMcpServer {
  /** The bound base URL to register with the kernel (e.g. http://127.0.0.1:8790/). */
  readonly url: string;
  /** Pure request path (no sockets) - the unit under test, and reusable by
   * anyone embedding the scaffold behind their own HTTP stack. `bearer` is the
   * already-extracted token value, or null when the request carried none. */
  handleRpc(request: unknown, bearer: string | null): Promise<JsonRpcResponse>;
  close(): Promise<void>;
}

type JsonRpcId = string | number | null;

interface JsonRpcResponse {
  jsonrpc: "2.0";
  id: JsonRpcId;
  result?: Record<string, unknown>;
  error?: { code: number; message: string };
  /** Transport hint for the HTTP wrapper; not part of the wire body. */
  httpStatus?: number;
}

function ok(rid: JsonRpcId, result: Record<string, unknown>): JsonRpcResponse {
  return { jsonrpc: "2.0", id: rid, result };
}

function err(rid: JsonRpcId, code: number, message: string, httpStatus?: number): JsonRpcResponse {
  const resp: JsonRpcResponse = { jsonrpc: "2.0", id: rid, error: { code, message } };
  if (httpStatus !== undefined) resp.httpStatus = httpStatus;
  return resp;
}

/** The success/error result envelope, byte-compatible with kernel/mcp.py's
 * `_call_tool` and exactly what mcp_consumer.py's `_execute` parses. */
function toolResultOk(output: unknown): Record<string, unknown> {
  return {
    content: [{ type: "text", text: JSON.stringify(output ?? {}) }],
    isError: false,
    _boltrig: { status: "ok", output: output ?? {} },
  };
}

function toolResultError(status: string, reason: string): Record<string, unknown> {
  return {
    content: [{ type: "text", text: reason }],
    isError: true,
    _boltrig: { status, reason },
  };
}

export function validateVerbTable(verbs: VerbDef[]): void {
  if (!Array.isArray(verbs) || verbs.length === 0) {
    throw new Error("verbs must be a non-empty table");
  }
  const seen = new Set<string>();
  for (const verb of verbs) {
    if (!verb || typeof verb !== "object") throw new Error("each verb must be an object");
    if (typeof verb.name !== "string" || !VERB_NAME_RE.test(verb.name)) {
      throw new Error(`verb name is invalid: ${JSON.stringify(verb?.name)}`);
    }
    if (RESERVED_VERB_PREFIXES.some((p) => verb.name.startsWith(p))) {
      throw new Error(`verb name uses a reserved core prefix: ${verb.name}`);
    }
    if (seen.has(verb.name)) throw new Error(`duplicate verb name: ${verb.name}`);
    seen.add(verb.name);
    if (typeof verb.description !== "string" || !verb.description.trim()) {
      throw new Error(`verb ${verb.name}: description is required`);
    }
    const schema = verb.schema as Record<string, unknown> | null;
    if (!schema || typeof schema !== "object" || Array.isArray(schema) || schema.type !== "object") {
      throw new Error(`verb ${verb.name}: schema must be a JSON Schema object with "type": "object"`);
    }
    if (typeof verb.handler !== "function") {
      throw new Error(`verb ${verb.name}: handler must be a function`);
    }
    if (verb.consequence !== undefined && verb.consequence !== "low" && verb.consequence !== "high") {
      throw new Error(`verb ${verb.name}: consequence must be "low" or "high"`);
    }
  }
}

/** Constant-time token compare via digests (length-independent). Never logs. */
function tokenMatches(presented: string, expected: string): boolean {
  const a = createHash("sha256").update(presented).digest();
  const b = createHash("sha256").update(expected).digest();
  return timingSafeEqual(a, b);
}

export async function createBoltrigMcpServer(
  options: BoltrigMcpServerOptions,
): Promise<BoltrigMcpServer> {
  if (!options.name?.trim()) throw new Error("server name is required");
  if (!options.version?.trim()) throw new Error("server version is required");
  validateVerbTable(options.verbs);

  const tokenEnv = options.tokenEnv ?? "BOLTRIG_MCP_TOKEN";
  const expectedToken = process.env[tokenEnv];
  if (!expectedToken) {
    // Fail closed: an unauthenticated verb server is a side door around the
    // kernel chokepoint. The token NAME is safe to print; the value never is.
    throw new Error(
      `bearer token env var ${tokenEnv} is not set; refusing to start an unauthenticated server`,
    );
  }

  const tools = new Map<string, VerbDef>(options.verbs.map((v) => [v.name, v]));

  async function handleRpc(request: unknown, bearer: string | null): Promise<JsonRpcResponse> {
    const req = (request ?? {}) as Record<string, unknown>;
    const rid = (typeof req.id === "string" || typeof req.id === "number" ? req.id : null) as JsonRpcId;
    if (req.jsonrpc !== "2.0" || typeof req.method !== "string") {
      return err(rid, -32600, "invalid JSON-RPC request");
    }
    // Defense in depth behind the kernel's own credential seam: every method
    // (including initialize/tools/list) requires the bearer. -32001 mirrors
    // the kernel face's invalid-token error (kernel/mcp.py:169).
    if (bearer === null || !tokenMatches(bearer, expectedToken as string)) {
      return err(rid, -32001, "unauthorized", 401);
    }
    const method = req.method;
    const params = (req.params ?? {}) as Record<string, unknown>;

    if (method === "initialize") {
      return ok(rid, {
        protocolVersion: PROTOCOL_VERSION,
        capabilities: { tools: { listChanged: false } },
        serverInfo: { name: options.name, version: options.version },
      });
    }
    if (method === "notifications/initialized" || method === "ping") {
      return ok(rid, {});
    }
    if (method === "tools/list") {
      return ok(rid, {
        tools: options.verbs.map((v) => ({
          name: v.name,
          description: v.description,
          inputSchema: v.schema,
          // Per-tool consequence hint the consumer propagates to the verb row
          // (mcp_consumer.py:_consequence_hint; absent/bogus -> "low").
          consequence: v.consequence ?? "low",
          annotations: {
            readOnlyHint: false,
            destructiveHint: v.consequence === "high",
          },
        })),
      });
    }
    if (method === "tools/call") {
      const name = typeof params.name === "string" ? params.name : "";
      const verb = tools.get(name);
      if (verb === undefined) {
        return ok(rid, toolResultError("error", `unknown verb: ${name || "(none given)"}`));
      }
      const args = params.arguments ?? {};
      if (typeof args !== "object" || args === null || Array.isArray(args)) {
        return ok(rid, toolResultError("error", "arguments must be an object"));
      }
      try {
        const output = await verb.handler(args as Record<string, unknown>);
        return ok(rid, toolResultOk(output));
      } catch (exc) {
        if (exc instanceof VerbError) {
          return ok(rid, toolResultError(exc.status, exc.message));
        }
        // Deliberately generic: handler internals never cross the wire.
        return ok(rid, toolResultError("error", "verb handler error"));
      }
    }
    return err(rid, -32601, `method not found: ${method}`);
  }

  // --- thin HTTP wrapper around handleRpc (plain JSON-RPC POST, no SSE) ---
  function extractBearer(req: IncomingMessage): string | null {
    // Primary: what the kernel's consumer actually sends (mcp_consumer.py:183).
    const mcpToken = req.headers["x-boltrig-mcp-token"];
    if (typeof mcpToken === "string" && mcpToken) return mcpToken;
    // Also accept a standard bearer for operators probing the server directly.
    const auth = req.headers.authorization ?? "";
    const [scheme, value] = auth.split(" ", 2);
    if (scheme?.toLowerCase() === "bearer" && value?.trim()) return value.trim();
    return null;
  }

  const server: Server = createServer((req: IncomingMessage, res: ServerResponse) => {
    void (async () => {
      const send = (status: number, body: JsonRpcResponse) => {
        const { httpStatus: _hint, ...wire } = body;
        res.writeHead(status, { "content-type": "application/json" });
        res.end(JSON.stringify(wire));
      };
      if (req.method !== "POST") {
        res.writeHead(405, { allow: "POST" });
        res.end();
        return;
      }
      const bearer = extractBearer(req);
      let raw = "";
      try {
        for await (const chunk of req) {
          raw += chunk;
          if (raw.length > 1_000_000) {
            send(413, err(null, -32600, "request too large"));
            return;
          }
        }
      } catch {
        send(400, err(null, -32600, "cannot read request body"));
        return;
      }
      let parsed: unknown;
      try {
        parsed = JSON.parse(raw);
      } catch {
        send(400, err(null, -32700, "parse error"));
        return;
      }
      const response = await handleRpc(parsed, bearer);
      send(response.httpStatus ?? 200, response);
    })().catch(() => {
      // Never leak internals; never crash the listener.
      if (!res.headersSent) {
        res.writeHead(500, { "content-type": "application/json" });
        res.end(JSON.stringify({ jsonrpc: "2.0", id: null, error: { code: -32603, message: "internal error" } }));
      } else {
        res.end();
      }
    });
  });

  const host = options.host ?? "127.0.0.1";
  const port = options.port ?? 0;
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, host, () => resolve());
  });
  const address = server.address();
  if (address === null || typeof address === "string") {
    throw new Error("server failed to bind");
  }

  return {
    url: `http://${host}:${address.port}/`,
    handleRpc,
    close: () =>
      new Promise<void>((resolve, reject) => {
        server.close((error) => (error ? reject(error) : resolve()));
      }),
  };
}
