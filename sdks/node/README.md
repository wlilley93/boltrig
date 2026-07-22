# boltrig-app-sdk (Node)

The Node SDK for an external app (here: **Opbox**, a Node backend) that wants to
expose its verbs to a **Boltrig kernel** instance. The kernel stays the ONE
chokepoint — grants, HITL, idempotency, rate limits, credential resolution,
audit — and your app stays what it is: a capability that loads as DATA.

```
your app (this SDK)                     Boltrig kernel
┌───────────────────────┐   JSON-RPC    ┌────────────────────────────────────┐
│ createBoltrigMcpServer│◄── POST ──────│ McpConsumerAdapter (inert until    │
│  verbs: [...]         │  x-boltrig-   │ reviewed + activated, SEC-22)      │
│  handler(params)      │  mcp-token    │ executes via the full chokepoint   │
└───────────────────────┘               └────────────────────────────────────┘
        ▲  register.ts: control.mcp_server.register / control.adapter.activate
        ▲  head.ts: SSE chat + HITL respond/answer (port of chat_cli.py)
```

Zero runtime dependencies. Plain TypeScript + `tsc`, `node:test` for tests.

## Layout

- `src/server.ts` — the MCP-server scaffold: declarative verb table, the
  `_boltrig` result envelope, bearer auth middleware.
- `src/register.ts` — the registration client: owner login → PAT, governed
  `control.mcp_server.register`, `control.adapter.activate`, HITL respond,
  adapter inventory.
- `src/head.ts` — the head client: SSE chat consumer + HITL helpers, a faithful
  port of the pure parts of `boltrig/api/chat_cli.py` (no TTY code).
- `src/http.ts` — shared fetch plumbing; tokens never appear in errors.
- `examples/opbox-verbs/` — a worked 5-verb Opbox server.
- `tests/` — `node:test`, no network (envelope mapping, verb-table validation,
  SSE parser, registration request shaping against a mocked fetch).

```sh
npm install
npm test          # build + node:test
npm run example   # build + run the Opbox example (needs OPBOX_MCP_TOKEN set)
```

## 1. Expose your verbs

```ts
import { createBoltrigMcpServer, VerbError, type VerbDef } from "boltrig-app-sdk";

const verbs: VerbDef[] = [
  {
    name: "orders.list",                 // publishes as "<adapter-id>.orders.list" (see below)
    description: "List Opbox orders, optionally filtered by status.",
    schema: {                            // JSON Schema; the KERNEL validates params
      type: "object",                    // against this at dispatch
      properties: { status: { type: "string", enum: ["pending", "paid", "shipped"] } },
      additionalProperties: false,
    },
    handler: async (params) => ({ orders: await db.listOrders(params.status) }),
  },
  // ...
];

const server = await createBoltrigMcpServer({
  name: "opbox",
  version: "0.1.0",
  verbs,
  tokenEnv: "OPBOX_MCP_TOKEN",           // env var NAME; value never logged
  host: "127.0.0.1",
  port: 8790,
});
console.log(server.url);                 // register this URL with the kernel
```

Handler contract:

- Return any JSON-serialisable value → wrapped as
  `{ content: [{type:"text",text:<json>}], isError: false, _boltrig: {status:"ok", output} }`.
  The kernel's consumer reads `_boltrig.output` as the verb's structured output
  (`boltrig/adapters/mcp_consumer.py`); the `content` array is the standard-MCP fallback.
- Throw `VerbError("order not found")` →
  `{ isError: true, _boltrig: {status:"error", reason} }`, which the consumer maps
  onto its typed error taxonomy (same module). Any other throw is
  reported as a generic `"verb handler error"` — internals never cross the wire.

**Transport.** The kernel's consumer (`boltrig/adapters/mcp_transport.py`)
POSTs one JSON-RPC 2.0 body per call with an
`Accept: application/json, text/event-stream` header. A plain JSON-RPC door
like this scaffold is used as-is; a strict Streamable-HTTP server that demands
the `initialize` handshake and a session id gets them (lazily, on the server's
refusal), and SSE-framed answers are decoded. So EITHER shape works — this
scaffold serves plain JSON-RPC POST, mirroring the kernel's own MCP face
(`boltrig/kernel/mcp.py`, also a thin hand-rolled JSON-RPC face).
`initialize`/`ping` are still answered, so any standard MCP client can talk to
the server too.

**Auth (defense in depth).** Every method — including `tools/list` — requires
the bearer. The consumer presents it as BOTH `x-boltrig-mcp-token: <token>`
and `Authorization: Bearer <token>` (`mcp_transport.py`); either is accepted. The comparison is constant-time, the token comes from an env var whose
NAME you configure, the value is never logged, and the server refuses to start
when it is unset (an unauthenticated verb server would be a side door around
the chokepoint). Note this is *defense in depth behind* the kernel's credential
seam, not a replacement for it: the token never appears at registration time.

## 2. Register an instance

Registration is a governed control verb, not a side door: the client calls
`POST /v1/mcp/servers`, which dispatches `control.mcp_server.register` through
the kernel chokepoint (`platform_routes/adapters.py:46`).

```ts
import { login, mintPat, registerMcpServer, isPendingHuman } from "boltrig-app-sdk";

// One-time, operator step: session login as the owner, then mint a service PAT.
const { cookie } = await login({ server: "http://localhost:8000", email, password });
const pat = await mintPat({ server, cookie, name: "opbox-sdk", ttlDays: 90 });
// pat.secret is shown ONCE. Store it as the app's BOLTRIG_TOKEN; never log it.

const outcome = await registerMcpServer({
  server: "http://localhost:8000",
  token: pat.secret,                     // or rely on env BOLTRIG_TOKEN
  id: "opbox-acme",                      // ONE registration per app instance/tenant
  url: "http://127.0.0.1:8790/",
  // credentialRef: "OPBOX_MCP_TOKEN",   // binds the credential at registration
});
```

`credentialRef` names a secret the KERNEL resolves per call
(`control_mcp.py:26-55`). With the default `env` secret store that means an
**environment variable readable by the kernel process** (the value may be a raw
string or a JSON object with `token`/`api_key`/`value`). Raw secret material in
the params is refused kernel-side outright — this client has no field that
could carry it.

> The verb spec (`control_specs.py`, `control.mcp_server.register`) declares
> `credential_ref` (and `allow_internal` for an operator-vetted internal URL),
> so registration can bind the credential in one call. Without it no credential
> is bound and calls fail closed with `mcp credential missing`
> (`mcp_consumer.py`) until one is bound kernel-side.

The registration lands **INERT** (the SEC-22 review gate): the adapter row is
visible in `GET /v1/adapters` with `activated: false`, and execution refuses
with `mcp server pending review` until a human reviews and activates.

If your tenant's HITL policy gates even low-consequence control verbs, the
outcome is `{ status: "pending_human", hitlRequestId }` instead — approve it
(see below) and re-call with `approvalId`.

## 3. Review gate, activation, grants, HITL semantics

```ts
import { activateAdapter, respondToHitl, listAdapters } from "boltrig-app-sdk";

// Activation is HIGH consequence and drives HITL:
let act = await activateAdapter({ server, token, adapterId: "opbox-acme" });
if (isPendingHuman(act)) {
  // A human reviews — in the console, or programmatically. FOUR-EYES (verified
  // live): the requester may NOT approve their own request
  // (hitl_response_auth.py:136-145 answers 403 "cannot approve your own
  // request"), so this respond must come from a SECOND principal:
  await respondToHitl({ server, token: reviewerToken, requestId: act.hitlRequestId, decision: "approve" });
  act = await activateAdapter({ server, token, adapterId: "opbox-acme", approvalId: act.hitlRequestId });
}
// act.verbs — the published verb ids, namespaced "<adapter-id>.<tool>"
```

- **Grants.** Activation publishes verb *bindings*; agents still need grants
  covering the verbs. The tenant ceiling intersects every run's grants — the
  chokepoint enforces both.
- **HITL per call.** Verbs the kernel treats as high-consequence pend a human
  at dispatch (`PendingHuman`); the head client surfaces them as `hitl` SSE
  events and `respondHitl` answers them.
- **Namespacing.** Verbs publish as `<adapter-id>.<tool name>` under the
  noun `<adapter-id>` (e.g. adapter `opbox-acme` → verb `opbox-acme.orders.list`);
  grants must cover the prefixed ids. Tool names that can't be verb ids after
  prefixing (a `/`, whitespace, empty) are skipped with a warning, not published.
- **Consequence.** A tool's declared `consequence` hint propagates (capped at
  `"high"`, default `"low"`), as do the standard MCP annotations
  (`destructiveHint` → high, `readOnlyHint` → low) this SDK emits. Discovery
  (`connect()` → `tools/list`) runs at activation with the kernel-resolved
  credential, so the published verbs are the server's actual tools.

## 4. Auth model: service PAT, on_behalf_of

- **Service PAT.** Mint a PAT from the owner (or a dedicated service user) and
  hand it to the app as `BOLTRIG_TOKEN`. The PAT's scope is capped at the
  minting user's grants (`access_routes.py:390-410`, SEC-34) and resolves
  against the user's *current* role/scope/status on every call — disabling the
  user kills the token's power. Register per app instance (one adapter id per
  tenant/environment), so per-tenant grants, HITL policy, and audit stay
  separable.
- **on_behalf_of.** When the app acts for an end user, the kernel's invocation
  context carries `on_behalf_of` (the MCP face threads it through,
  `kernel/mcp.py:61-63,147`), so the audit row records the human the action was
  performed for. User-scoped attribution rides the kernel's context; the app
  never mints its own authority.

## 5. The head client (chat + HITL)

A faithful port of the pure parts of `boltrig/api/chat_cli.py` — same SSE
parsing rules, same render dispatch, same endpoints:

```ts
import { streamTurn, renderEvent, respondHitl, answerQuestion } from "boltrig-app-sdk";

let conversationId: string | undefined;
for await (const event of streamTurn({ server, token, message: "List paid orders", conversationId })) {
  if (event.type === "message_start") conversationId = event.conversation_id as string;
  const chunk = renderEvent(event);      // reference rendering; or dispatch yourself
  if (chunk) process.stdout.write(chunk);
  if (event.type === "hitl") {
    await respondHitl({ server, token, requestId: event.hitl_request_id as string, decision: "approve" });
  }
  if (event.type === "question") {
    await answerQuestion({ server, token, questionId: event.question_id as string, answer: "WIDGET-9" });
  }
}
```

`SseParser` is `data:`-only and drops comments/malformed frames without dying;
`streamTurn` POSTs `/v1/chat` and yields events as they arrive. No TTY
assumptions — bring your own UI.

## Per-instance (per-tenant) registration

One adapter id per app instance: `opbox-acme`, `opbox-globex`, … Each
registration is a row in that tenant's inventory, with its own `credential_ref`,
its own review/activation, and its own audit trail. The same Opbox binary serves
every tenant; the kernel keeps their governance separate.

## Security notes

- The bearer token, the PAT, and the owner password are never logged by this
  SDK and never included in error messages.
- The scaffold fails closed: no token env var → no server; wrong token →
  JSON-RPC `-32001` with HTTP 401 before any dispatch.
- All kernel mutations go through governed control verbs; nothing here writes
  to the kernel's store directly.
