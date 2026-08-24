# SPEC-16: The SDKs and the marketing site

- **area**: 16 The SDKs and the marketing site
- **id-block**: BT-REQ-1600 to BT-REQ-1699
- **referent commit**: `19bcae7fa81663fe8998377c86451ba08fb16e48` (`origin/main`)
- **author-agent**: brownfield-spec author, area 16
- **date**: 2026-08-24

## Bound of this reading

Owned files: `sdks/node/` (5 source modules, 4 test files, 1 example),
`sdks/web/` (12 source modules, 12 test files), `site/` (101 TypeScript files,
98 of them under `site/src`), `docs/SDK-CONTRACT-from-opbox.md`,
`docs/extension-contract.md`, `docs/addons.md`.

Read exhaustively: every file in `sdks/node/src`, `sdks/node/examples`,
`sdks/web/src` except `types.ts` and `client.ts`, all three owned docs, and
every non-component file under `site/src` (`env.ts`, `lib/`, `data/`,
`views/console/`, `app/`, `eslint.config.mjs`, `next.config.ts`,
`vitest.config.ts`, `tsconfig.json`, `package.json`, `pnpm-workspace.yaml`).

Sampled systematically, not read line by line:

- `sdks/web/src/types.ts` (4459 lines, 498 top-level exports). Every `export`
  line was enumerated; the chat-event family (lines 629 to 1080), the
  governed-response family (lines 421 to 490) and the console family (line 3205)
  were read in full. The remaining round-three/four/five response shapes were
  read only at their section banners.
- `sdks/web/src/client.ts` (2661 lines, 256 public methods by the route ledger's own regex). All method
  signatures and every `/v1` path literal were enumerated; the transport core
  (lines 252 to 460), `followConversation` (515 to 581), `streamChat` and the
  SSE pump (2565 to 2661) were read in full. Individual one-line CRUD methods
  were not each read.
- `site/src/components/**` React components were enumerated but only
  `site-header.tsx`, `features-section.tsx` and `views/console/*` were read.
- `site/obsidian/**` (33 vault notes) was read only where a claim about the
  site's contract needed checking (`architecture/environment-variables.md`).

Cross-boundary files read to settle contracts that this area asserts:
`boltrig/adapters/mcp_consumer.py`, `mcp_transport.py`, `mcp_tool_policy.py`,
`mcp_discovery.py`, `boltrig/kernel/mcp.py`, `boltrig/kernel/conversation_live_routes.py`,
`boltrig/fleet/chat_idempotency.py`, `apps/worker/{package.json,tsconfig.json,
vite.config.ts,Dockerfile,src/client.ts,src/apiOrigin.ts,src/theme.ts,nginx.conf}`,
`tests/worker_surface_ledger.py`, `tests/security/test_worker_route_ledger.py`,
`Makefile`, `.github/workflows/ci.yml`, `docs/decisions/0030-agents-tab-built-on-web-sdk.md`.

---

## 2. Purpose

This area holds Boltrig's two public client libraries and its marketing site.
`sdks/node` (`boltrig-app-sdk`) is the backend seam: how a third-party app
publishes its own verbs to a Boltrig kernel as a governed, inert MCP adapter,
and how it registers, activates and streams chat against that kernel.
`sdks/web` (`@wlilley93/boltrig-web-sdk`) is the frontend seam: one typed client
over the kernel's whole `/v1` surface plus the `ChatEvent` frame union and the
`normalizeEvents` turn reducer, so every Boltrig frontend folds the same stream
into the same shape. `site/` is the static marketing site at `boltrig.ai`, built
from a third-party Next.js starter, which consumes neither SDK.

---

## 3. Boundaries

### What this area owns

| Thing | Owner file | Not owned by |
| --- | --- | --- |
| The app-side MCP verb server scaffold | `sdks/node/src/server.ts` | the kernel's own MCP face `boltrig/kernel/mcp.py` |
| Governed registration and activation calls | `sdks/node/src/register.ts` | the control verbs themselves (`control.mcp_server.register`) |
| A TypeScript port of the pure chat CLI | `sdks/node/src/head.ts` | `boltrig/api/chat_cli.py`, which remains the original |
| The `ChatEvent` union and every `/v1` response shape | `sdks/web/src/types.ts` | the kernel routes that emit them |
| The `/v1` client | `sdks/web/src/client.ts` | the Worker's `client` singleton, `apps/worker/src/client.ts` |
| The turn reducer | `sdks/web/src/chatTurnNormalizer.ts` | the components that render a `NormalizedTurn` |
| The display-object catalogue and browser validator | `sdks/web/src/displayObjects.ts`, `displayObjectValidation.ts` | the kernel's own catalogue, which this one is diffed against |
| The character registry and bundle parser | `sdks/web/src/characters.ts`, `characterBundle.ts` | `schemas/character-bundle/v1/character-bundle.schema.json` |
| The marketing site source | `site/src` | the host Caddy at `/srv/boltrig-marketing`, which is not in this repository |

### Forbidden imports, and by what rule

**The web SDK must have no framework dependency.** `sdks/web/package.json`
declares two devDependencies and no dependencies
([`sdks/web/package.json:70`](../../../sdks/web/package.json) `"devDependencies"`),
and every import in `sdks/web/src` resolves to a sibling module in the same
package (bounded: `grep -h 'from "' sdks/web/src/*.ts | grep -o 'from "[^"]*"' | sort -u`,
2026-08-24, pinned tree: 11 relative specifiers and nothing else). The rule is
stated in the source: the render callback is generic over the node type
"GENERIC OVER THE RENDERED NODE ON PURPOSE. This package is framework-agnostic"
([`sdks/web/src/characters.ts:11`](../../../sdks/web/src/characters.ts) `"This package is framework-agnostic"`).

**The Node SDK must have zero runtime dependencies.** It imports only
`node:crypto` and `node:http`
([`sdks/node/src/server.ts:32`](../../../sdks/node/src/server.ts) `"import { createHash, timingSafeEqual } from"`), and the README states the
reason: the official MCP SDK's StreamableHTTP transport "mandates an
`initialize` handshake", which the consumer historically did not send
([`sdks/node/src/server.ts:24`](../../../sdks/node/src/server.ts) `"its StreamableHTTP transport mandates"`).

**The site must not call a third-party API from the browser.** Stated in
[`site/src/lib/api-client.ts:6`](../../../site/src/lib/api-client.ts) `"The browser must only ever call same-origin"`. This rule is violated by the
console view, which fetches an operator-supplied cross-origin kernel base
directly ([`site/src/views/console/client.ts:51`](../../../site/src/views/console/client.ts) `"await fetch(overviewUrl(settings.apiBase)"`). See RISKS.

**Neither SDK may log a bearer.** Asserted at
[`sdks/node/src/http.ts:5`](../../../sdks/node/src/http.ts) `"NEVER part of an error message"` and enforced by
`raiseForStatus`, which builds messages only from `payload.reason` /
`payload.error` ([`sdks/node/src/http.ts:123`](../../../sdks/node/src/http.ts) `const reason = typeof payload.reason === "string" ? payload.reason`).

### The shared source tree, precisely

The web SDK's source tree is compiled directly into the Worker. Three
independent bindings do this, and all three point at `src`, not at `dist`:

1. `apps/worker/package.json` depends on it by path:
   [`apps/worker/package.json:24`](../../../apps/worker/package.json) `"@wlilley93/boltrig-web-sdk": "file:../../sdks/web"`.
2. TypeScript resolves the bare specifier to the SDK's `index.ts`:
   [`apps/worker/tsconfig.json:22`](../../../apps/worker/tsconfig.json) `"@wlilley93/boltrig-web-sdk": ["../../sdks/web/src/index.ts"]`.
3. Vite aliases it the same way for both bundles:
   [`apps/worker/vite.config.ts:416`](../../../apps/worker/vite.config.ts) `path.resolve(__dirname, "../../sdks/web/src/index.ts")` and
   [`apps/worker/familiar-island/vite.config.ts:83`](../../../apps/worker/familiar-island/vite.config.ts) `path.resolve(HERE, "../../../sdks/web/src/index.ts")`.

The Worker image copies the SDK source into the build context rather than
installing a published tarball:
[`apps/worker/Dockerfile:12`](../../../apps/worker/Dockerfile)
`"The Worker resolves the shared SDK from source"`, then
[`apps/worker/Dockerfile:15`](../../../apps/worker/Dockerfile)
`COPY sdks/web/src ./sdks/web/src`.

**Blast radius, measured.** 164 files under `apps/worker/src` import the SDK
(bounded: `rg -l "@wlilley93/boltrig-web-sdk" apps/worker/src | wc -l`,
2026-08-24, pinned tree). No file anywhere in the pinned tree imports a subpath
of the package (bounded: `rg -n "boltrig-web-sdk/" --no-heading -g '!*.yaml'`
returns nothing), so the seven subpath `exports` entries in
[`sdks/web/package.json:31`](../../../sdks/web/package.json) `"./types"` through
[`sdks/web/package.json:55`](../../../sdks/web/package.json) `"./characters"` are
declared but unexercised in tree.
An edit to `sdks/web/src` changes the Worker's typecheck, its two Vite bundles
and its published image, with no version bump and no lockfile change.

**The site shares nothing.** `site/package.json` lists no Boltrig dependency
([`site/package.json:15`](../../../site/package.json) `"dependencies"`), and
`site/src` contains no import of the SDK (bounded: the `rg` above). It carries
its own third copy of the console response contract in
[`site/src/views/console/types.ts:62`](../../../site/src/views/console/types.ts) `"export type ConsoleOverview = {"`.

---

## 4. Objects and contracts

### 4.1 `sdks/node`: the app-side verb server

Package identity:
[`sdks/node/package.json:2`](../../../sdks/node/package.json) `"name": "boltrig-app-sdk"`, `"private": true`, `"version": "0.1.0"`,
`"type": "module"`, `engines.node >= 20`. It is not published anywhere; there
is no `publishConfig` and no `files` array.

`index.ts` re-exports exactly four modules' surface
([`sdks/node/src/index.ts:2`](../../../sdks/node/src/index.ts) `"createBoltrigMcpServer,"`):

| Export | Kind | Module |
| --- | --- | --- |
| `createBoltrigMcpServer`, `validateVerbTable`, `VerbError`, `PROTOCOL_VERSION` | values | `server.ts` |
| `BoltrigMcpServer`, `BoltrigMcpServerOptions`, `VerbDef`, `VerbHandler`, `VerbContext`, `VerbIdentity` | types | `server.ts` |
| `login`, `mintPat`, `registerMcpServer`, `activateAdapter`, `respondToHitl`, `listAdapters`, `isPendingHuman` | values | `register.ts` |
| `ActivateOutcome`, `Activated`, `PendingHuman`, `RegisterOutcome`, `Registered`, `RegisterMcpServerOptions` | types | `register.ts` |
| `SseParser`, `parseSse`, `renderEvent`, `streamTurn`, `respondHitl`, `answerQuestion`, `ChatHeadError` | values | `head.ts` |
| `ChatEvent`, `StreamTurnOptions` | types | `head.ts` |
| `KernelApiError` | value | `http.ts` |
| `FetchLike`, `KernelRequestOptions` | types | `http.ts` |

**`VerbDef`** ([`sdks/node/src/server.ts:85`](../../../sdks/node/src/server.ts) `"export interface VerbDef {"`):

| Field | Type | Lifecycle |
| --- | --- | --- |
| `name` | `string` matching `/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/` | validated at construction; published to the kernel as `<adapter-id>.<name>` |
| `description` | non-empty `string` | fenced kernel-side as untrusted data before it reaches a model |
| `schema` | JSON Schema object, `type: "object"` required | forwarded verbatim as MCP `inputSchema`; validated by the kernel at dispatch |
| `handler` | `(params, ctx?) => unknown \| Promise<unknown>` | invoked per `tools/call` |
| `consequence` | `"low" \| "high"`, optional | omitted from the wire when undefined so absence travels as absence |
| `implements` | dotted capability id, optional, no `@` pin | a claim recorded kernel-side as a proposed binding that routes nothing |

**`VerbIdentity` and `VerbContext`**
([`sdks/node/src/server.ts:59`](../../../sdks/node/src/server.ts) `"export interface VerbIdentity {"`): `VerbIdentity` requires `bearer` and
allows any additional key (`[k: string]: unknown`); `VerbContext` is
`{bearer, identity}`. `ctx` is the handler's optional second argument, so
single-argument handlers written before the hook existed are unaffected
([`sdks/node/src/server.ts:81`](../../../sdks/node/src/server.ts) `"Additive - does not break existing handlers"`).

**The result envelope** is byte-compatible with the kernel's own MCP face.
Success: `{content: [{type:"text", text: JSON.stringify(output)}], isError:false,
_boltrig: {status:"ok", output}}`
([`sdks/node/src/server.ts:166`](../../../sdks/node/src/server.ts) `"function toolResultOk(output: unknown)"`). Failure:
`{content:[{type:"text",text:reason}], isError:true, _boltrig:{status, reason}}`
([`sdks/node/src/server.ts:174`](../../../sdks/node/src/server.ts) `"function toolResultError(status: string, reason: string)"`).

**Registration outcomes** are a two-member union per call
([`sdks/node/src/register.ts:47`](../../../sdks/node/src/register.ts) `"export type RegisterOutcome = Registered | PendingHuman;"`). `Registered`
carries `activated: false` and a prose `next` naming the SEC-22 review gate;
`PendingHuman` carries a `hitlRequestId` to be replayed as `approvalId`.

### 4.2 `sdks/web`: the frontend contract

Package identity:
[`sdks/web/package.json:2`](../../../sdks/web/package.json) `"name": "@wlilley93/boltrig-web-sdk"`, `"private": false`,
`"version": "0.2.0"`, `"license": "UNLICENSED"`, `"sideEffects": false`,
`main`/`types` pointing at `dist/src`, `publishConfig.registry` set to
`https://npm.pkg.github.com`, `files: ["dist/src"]`. `dist/` is gitignored
([`sdks/web/.gitignore:2`](../../../sdks/web/.gitignore) `dist/`), so the
published artifact is produced by `prepublishOnly` at publish time and no built
form of the package exists in the tree.

`index.ts` is the single public entry
([`sdks/web/src/index.ts:8`](../../../sdks/web/src/index.ts) `export * from "./types.js";`). Its surface:

| Re-export | Shape |
| --- | --- |
| `export *` from `types.js` | 498 top-level exports: 435 interfaces, 63 type aliases, no runtime values |
| `export *` from `capabilityInvocation.js` | 3 functions plus 5 types |
| `export *` from `chatTurnTypes.js` | 8 types, no values |
| `export *` from `displayObjects.js` | `DISPLAY_OBJECT_SCHEMA`, `DISPLAY_OBJECT_TEMPLATES`, `displayObjectTemplate`, `isDisplayObjectKind`, 5 types |
| named from `displayObjectValidation.js` | `parseDisplayObject` only |
| named from `chatTurnNormalizer.js` | `normalizeEvents` only |
| named from `client.js` | `BoltrigApiError`, `BoltrigClient`, `pumpSse`; types `BoltrigClientOptions`, `ChatFollowResult`, `ChatQueued` |
| named from `integrationCatalogue.js` | `WORKER_INTEGRATION_CATALOGUE` |
| named from `familiarState.js` | `RESTING_FAMILIAR_STATE_V2`, `sanitizeFamiliarState`, 8 types |
| named from `characters.js` | 7 registry functions, 13 types |
| named from `characterBundle.js` | `CHARACTER_BUNDLE_SCHEMA_VERSION`, `CharacterBundleError`, 8 `bundle*` readers, `exportCharacterBundle`, `parseCharacterBundle`, 13 types |

**`BoltrigClient`** ([`sdks/web/src/client.ts:326`](../../../sdks/web/src/client.ts) `"export class BoltrigClient {"`) exposes 256 public methods across 54 distinct
`/v1` path families. Distribution of path literals by first segment (top ten):
`/v1/me` 32, `/v1/workflows` 17, `/v1/channels` 12, `/v1/auth` 12,
`/v1/memory` 11, `/v1/mcp` 10, `/v1/knowledge` 10, `/v1/calls` 9,
`/v1/ai-keys` 9, `/v1/integrations` 8.

Construction options
([`sdks/web/src/client.ts:254`](../../../sdks/web/src/client.ts) `"export interface BoltrigClientOptions {"`):

| Option | Default | Effect |
| --- | --- | --- |
| `baseUrl` | `""` (same origin), trailing slash stripped | prefix for every path |
| `fetch` | `globalThis.fetch` bound | injection point for the desktop bridge |
| `accessToken` | absent | when present, sets `authorization: Bearer` and flips two other defaults |
| `csrfToken` | absent | explicit supplier always honoured |
| `headers` | absent | arbitrary extra headers per call |
| `credentials` | `"omit"` when `accessToken` is set, else `"include"` | whether the browser attaches cookies |

**Three request helpers** carry the whole policy:
`request<T>` throws `BoltrigApiError` on any non-2xx unless `tolerateStatus`
([`sdks/web/src/client.ts:355`](../../../sdks/web/src/client.ts) `"private async request<T>("`); `json<T>` is the plain mutation
([`:392`](../../../sdks/web/src/client.ts) `"private json<T>("`);
`governedJson<T>` adds `x-boltrig-approval-id` and always sets
`tolerateStatus: true`, so a 202 pending-human body reaches the caller instead
of throwing ([`sdks/web/src/client.ts:406`](../../../sdks/web/src/client.ts) `"private governedJson<T>("`). `governedJson` has 67 call sites, `json` 67, `request` 110, and `raw` (used for
artifact bytes) 2.

**The governed-response union**:
[`sdks/web/src/types.ts:477`](../../../sdks/web/src/types.ts) `"export type GovernedRouteResponse<T> = T | PendingHumanResponse;"`, with
`PendingHumanResponse = {status:"pending_human", hitl_request_id}` at
[`:465`](../../../sdks/web/src/types.ts).

**The `ChatEvent` union has 21 members**
([`sdks/web/src/types.ts:1047`](../../../sdks/web/src/types.ts) `"export type ChatEvent ="`): `message_start`, `text_delta`,
`reasoning_delta`, `tool_call`, `tool_result`, `subagent`, `subagent_end`,
`steer_queued`, `steer_consumed`, `hitl`, `question`, `heartbeat`,
`message_end`, `cancelled`, `workflow_step`, `workflow_run`, `model_routing`,
`artifact`, `artifact_rejected`, `display_object`, `event_unavailable`.

The bounded-vs-relay split is encoded in the types rather than in two unions:
`tool_call.input` and `tool_result.output` are optional and documented as
"full input rides only on the run relay"
([`sdks/web/src/types.ts:853`](../../../sdks/web/src/types.ts) `"full input rides only on the run relay"`).

**`NormalizedTurn`** ([`sdks/web/src/chatTurnTypes.ts:90`](../../../sdks/web/src/chatTurnTypes.ts) `"export interface NormalizedTurn {"`) is the reducer's output:
`{runId?, conversationId?, agentAddress?, text, reasoning, tools[],
subagents[], hitls[], questions[], displayObjects[], steps[], timeline[],
ended, cancelled, degraded, modelRouting?}`. `timeline` is a six-member
discriminated union preserving arrival order
([`:82`](../../../sdks/web/src/chatTurnTypes.ts)
`"export type TimelineEntry ="`).

**Display objects** are a closed catalogue of 64 template kinds across eight
families ([`sdks/web/src/displayObjects.ts:10`](../../../sdks/web/src/displayObjects.ts) `"export const DISPLAY_OBJECT_TEMPLATES = ["`), schema-tagged
`boltrig.display.v1` ([`:8`](../../../sdks/web/src/displayObjects.ts)).

**Character registry** is a module-level singleton
([`sdks/web/src/characters.ts:200`](../../../sdks/web/src/characters.ts) `"const REGISTRY = new Map<string, Character<never>>();"`) with a monotonic
revision counter and a listener set, so a framework adapter can drive
`useSyncExternalStore`. `registerCharacter` freezes the object it stores,
because "A JavaScript add-in can retain and mutate the object it passed us"
([`:265`](../../../sdks/web/src/characters.ts)).

**Character bundle** is the runtime half of
`schemas/character-bundle/v1/character-bundle.schema.json`
([`sdks/web/src/characterBundle.ts:3`](../../../sdks/web/src/characterBundle.ts) `"This is the runtime half of schemas/character-bundle"`), schema version 1.

### 4.3 The site

`site/package.json` is `boltrig-site`, private, version `0.1.0`, pnpm 11.5.0
([`site/package.json:45`](../../../site/package.json) `"packageManager": "pnpm@11.5.0"`).
Runtime stack: Next 16.3.1, React 19.2.8, three.js + `@react-three/fiber` for
the brain scene, `@react-spring/web` for all motion, `lenis` for smooth scroll,
Tailwind v4, `zod`, `zustand`.

Routes are six files under `site/src/app`: `page.tsx` (home),
`console/page.tsx`, `error.tsx`, `loading.tsx`, `not-found.tsx`, plus the
generated `robots.ts` and `sitemap.ts`. There is no `site/src/app/api`
directory.

`siteConfig` is the one SEO source of truth
([`site/src/lib/site.ts:9`](../../../site/src/lib/site.ts) `"export const siteConfig = {"`) with `url` defaulting to
`https://boltrig.ai`.

`FEATURE_GROUPS` is the marketing claim catalogue: six groups of five items
([`site/src/data/features.ts:26`](../../../site/src/data/features.ts) `"export const FEATURE_GROUPS: FeatureGroup[] = ["`).

---

## 5. Control flow

### 5.1 Publishing an app's verbs (Node SDK, happy path and every failure branch)

1. **Validate the verb table.** `createBoltrigMcpServer` calls
   `validateVerbTable(options.verbs)` before anything else
   ([`sdks/node/src/server.ts:236`](../../../sdks/node/src/server.ts) `validateVerbTable(options.verbs);`).
   *Failure:* a synchronous `throw` naming the offending verb. Eleven distinct
   refusals: empty table, non-object entry, bad name charset, reserved prefix
   (`boltrig.`, `chat.`, `control.`, `kernel.`, `system.`), duplicate name,
   missing description, schema that is not a `type:"object"` JSON Schema,
   non-function handler, out-of-vocabulary `consequence`, and a versioned
   `implements` ([`:182`](../../../sdks/node/src/server.ts)
   `"export function validateVerbTable(verbs: VerbDef[])"`). The `@` pin check
   runs first "so a versioned claim gets the message that explains it"
   ([`:211`](../../../sdks/node/src/server.ts)).
2. **Resolve the bearer env var.** `tokenEnv` defaults to `BOLTRIG_MCP_TOKEN`.
   *Failure:* the server refuses to start when the variable is unset, throwing
   a message that names the variable but never its value
   ([`sdks/node/src/server.ts:244`](../../../sdks/node/src/server.ts) `"is not set; refusing to start an unauthenticated server"`). Fail closed.
3. **Bind the socket.** `host` defaults to `127.0.0.1`, `port` to `0`
   ([`:388`](../../../sdks/node/src/server.ts) `const host = options.host ?? "127.0.0.1";`).
   *Failure:* a bind error rejects the promise; a non-INET address throws
   `"server failed to bind"` ([`:396`](../../../sdks/node/src/server.ts)).
4. **Per request: method gate.** Anything but `POST` gets `405` with an
   `allow: POST` header ([`:349`](../../../sdks/node/src/server.ts)
   `if (req.method !== "POST")`).
5. **Per request: body bound.** The body accumulates until 1,000,000 characters,
   then `413` ([`:359`](../../../sdks/node/src/server.ts)
   `if (raw.length > 1_000_000)`).
   *Failure:* a stream error yields `400 -32600 "cannot read request body"`; a
   JSON parse error yields `400 -32700 "parse error"`.
6. **Extract the bearer.** `x-boltrig-mcp-token` is preferred; a standard
   `Authorization: Bearer` is also accepted "for operators probing the server
   directly" ([`:337`](../../../sdks/node/src/server.ts)).
   *Failure:* neither header present yields `bearer = null`, which step 8
   refuses.
7. **Shape check.** `jsonrpc !== "2.0"` or a non-string `method` yields
   `-32600 "invalid JSON-RPC request"` at HTTP 200
   ([`:253`](../../../sdks/node/src/server.ts)).
8. **Authorize, before dispatch, for every method including `tools/list`.**
   With a `resolveIdentity` hook, the presented bearer is resolved to an
   identity and a null result is a refusal; without one, the bearer is compared
   constant-time against the env token
   ([`sdks/node/src/server.ts:263`](../../../sdks/node/src/server.ts) `if (options.resolveIdentity) {`).
   *Failure:* `-32001 "unauthorized"` carried out as HTTP 401 via the
   `httpStatus` transport hint ([`:266`](../../../sdks/node/src/server.ts)).
   The comparison hashes both sides with SHA-256 first, so it is
   length-independent ([`:225`](../../../sdks/node/src/server.ts)
   `"Constant-time token compare via digests"`).
9. **`initialize` / `notifications/initialized` / `ping`.** `initialize`
   answers `protocolVersion: "2024-11-05"`, `capabilities.tools.listChanged:false`
   and `serverInfo` ([`:275`](../../../sdks/node/src/server.ts)); the other two
   answer `{}`.
10. **`tools/list`.** Each verb becomes
    `{name, description, inputSchema, consequence?, implements?, annotations:{readOnlyHint:false,
    destructiveHint: consequence === "high"}}`
    ([`sdks/node/src/server.ts:287`](../../../sdks/node/src/server.ts) `"tools: options.verbs.map((v) => ({"`). `consequence` and `implements` are
    spread conditionally so an undeclared consequence sends no key at all:
    "ABSENCE TRAVELS AS ABSENCE" ([`:291`](../../../sdks/node/src/server.ts)).
    No `outputSchema` is ever emitted.
11. **`tools/call`.** Unknown verb yields a `toolResultError` at JSON-RPC
    success ([`:310`](../../../sdks/node/src/server.ts)
    `"unknown verb: ${name || \"(none given)\"}"`); non-object `arguments`
    yields `"arguments must be an object"`.
    *Failure of the handler:* a `VerbError` becomes
    `{isError:true, _boltrig:{status, reason}}`; any other throw becomes
    `{isError:true, _boltrig:{status:"error", reason:"verb handler error"}}`,
    "Deliberately generic: handler internals never cross the wire"
    ([`:323`](../../../sdks/node/src/server.ts)).
12. **Unknown method.** `-32601 "method not found: ${method}"` at HTTP 200.
13. **Catch-all.** The whole async body is wrapped so an unexpected throw
    answers `500 -32603 "internal error"` and never crashes the listener
    ([`:377`](../../../sdks/node/src/server.ts)
    `"Never leak internals; never crash the listener"`).

### 5.2 What the kernel actually sends back at this door

The consumer's transport is `StreamableHttp`
([`boltrig/adapters/mcp_transport.py:1`](../../../boltrig/adapters/mcp_transport.py) `"The MCP Streamable-HTTP client transport the consumer speaks"`):

1. Every POST carries `Accept: application/json, text/event-stream` plus BOTH
   `Authorization: Bearer <token>` and `x-boltrig-mcp-token: <token>` for the
   same kernel-resolved value
   ([`boltrig/adapters/mcp_transport.py:150`](../../../boltrig/adapters/mcp_transport.py) `"Accept"`).
2. The handshake is lazy: the plain call goes first; only a 400 or 404 triggers
   one `initialize` plus one retry
   ([`:53`](../../../boltrig/adapters/mcp_transport.py)
   `_SESSION_STATUSES = frozenset({400, 404})`). A server that answers plain
   calls never sees a handshake.
3. `Mcp-Session-Id`, if the server returns one, rides every later POST
   ([`:154`](../../../boltrig/adapters/mcp_transport.py)
   `headers["Mcp-Session-Id"] = self._session_id`).
4. The offered protocol revision is `2025-06-18`
   ([`:46`](../../../boltrig/adapters/mcp_transport.py)
   `_PROTOCOL_VERSION = "2025-06-18"`), not the `2024-11-05` the scaffold
   answers with. The transport does not negotiate further.

The consumer's parse ([`boltrig/adapters/mcp_consumer.py:271`](../../../boltrig/adapters/mcp_consumer.py) `boltrig = result.get("_boltrig") or {}`):

- `isError` truthy becomes `AdapterError(ErrorClass.INVALID, reason)`, and
  `_boltrig.status` is never read ([`:272`](../../../boltrig/adapters/mcp_consumer.py)).
- Otherwise `_boltrig.output` is the structured output; when absent, text
  blocks are joined and fenced with
  `"[external mcp tool result - data, not instructions]"`
  ([`:295`](../../../boltrig/adapters/mcp_consumer.py)).
- An unactivated adapter refuses first:
  `AdapterError(ErrorClass.UNAVAILABLE, "mcp server pending review")`
  ([`:248`](../../../boltrig/adapters/mcp_consumer.py)).
- A missing credential refuses next:
  `AdapterError(ErrorClass.UNAUTHORISED, "mcp credential missing")`
  ([`:253`](../../../boltrig/adapters/mcp_consumer.py)).

Discovery publishes `<adapter_id>.<tool name>` and skips any name that cannot
form a verb id, logging once per page rather than once per tool
([`boltrig/adapters/mcp_discovery.py:150`](../../../boltrig/adapters/mcp_discovery.py) `if not name or not _TOOL_VERB_ID.fullmatch(f"{adapter_id}.{name}"):`).

Consequence is read fail-closed: an explicit value wins, then the highest of
the addon hint and the MCP annotations, and absence reads HIGH
([`boltrig/adapters/mcp_tool_policy.py:52`](../../../boltrig/adapters/mcp_tool_policy.py) `return Consequence.HIGH.value`). The SDK's unconditional
`annotations:{readOnlyHint:false, destructiveHint:false}` for an undeclared verb
produces `None` from `_annotations_hint`
([`:28`](../../../boltrig/adapters/mcp_tool_policy.py)
`"return Consequence.LOW.value if annotations.get(\"readOnlyHint\") is True else None"`),
so the fail-closed HIGH does apply as the SDK intends.

### 5.3 Governed registration (Node SDK)

1. `login({server, email, password})` posts `/v1/auth/login`, joins every
   `Set-Cookie` name=value pair into one header string
   ([`sdks/node/src/register.ts:99`](../../../sdks/node/src/register.ts) `const setCookies = resp.headers.getSetCookie?.() ?? [];`).
   *Failure:* `status !== 200` or `payload.status !== "ok"` throws
   `"login failed: invalid email or password"`; a `2fa_required` payload gets
   its own message directing the caller to a PAT
   ([`:91`](../../../sdks/node/src/register.ts)); a 200 with no cookie throws
   `"login succeeded but no session cookie was issued"`.
2. `mintPat` posts `/v1/me/tokens` with the cookie.
   *Failure:* a response missing `secret` or `id` throws
   `"token mint returned an unexpected shape"`
   ([`:124`](../../../sdks/node/src/register.ts)).
3. `registerMcpServer` posts `/v1/mcp/servers` with `{id, url}` plus optional
   `credential_ref`/`credential_id`/`credential_store`/`credential_kind`/`approval_id`.
   There is no parameter that could carry secret material
   ([`sdks/node/src/register.ts:154`](../../../sdks/node/src/register.ts) `"Refs only, never material (control_mcp.py:38-43 refuses raw secrets)"`).
   *Branch:* HTTP 202 with `status === "pending_human"` returns
   `PendingHuman`; anything else goes through `raiseForStatus`.
4. `activateAdapter` posts `/v1/adapters/{id}/activate`, sending `approvalId`
   both in the body and as `x-boltrig-approval-id`
   ([`:193`](../../../sdks/node/src/register.ts)
   `headers["x-boltrig-approval-id"] = opts.approvalId;`).
5. `respondToHitl` posts `/v1/hitl/{id}/respond`; `listAdapters` reads
   `/v1/adapters` and coerces each row to `{id, runtime, activated, health}`
   with `String(...)` and `=== true`, so a malformed row degrades rather than
   throwing ([`:234`](../../../sdks/node/src/register.ts)
   `return adapters.map((a) => {`).

### 5.4 Streaming a chat turn (Node SDK head client)

1. `streamTurn` builds the body from `message` plus four optional fields:
   `conversation_id`, `on_behalf_bearer`, `idempotency_key`, `origin`
   ([`sdks/node/src/head.ts:172`](../../../sdks/node/src/head.ts) `const body: Record<string, unknown> = { message: opts.message };`).
2. A transport failure throws `ChatHeadError` naming the server but not the
   token: `"cannot reach the kernel at ${opts.server}"`
   ([`:189`](../../../sdks/node/src/head.ts)).
3. **HTTP 202 is an acceptance, not a failure.** The generator yields a
   synthetic `{type:"queued", detail}` and returns
   ([`sdks/node/src/head.ts:198`](../../../sdks/node/src/head.ts) `if (resp.status === 202) {`). This is a recorded regression fix
   ([`docs/findings/2026-07-25-queued-ack-read-as-failure.md:18`](../../../docs/findings/2026-07-25-queued-ack-read-as-failure.md) `"returns the ack, and the sender announces it"`).
4. 401/403 throws `"authentication failed (HTTP ${status}) - check the token"`;
   any other non-200 throws with `payload.reason` when present.
5. A 200 with no readable `body` throws `"chat response had no stream body"`.
6. Lines are split with a carried tail across chunks
   ([`:118`](../../../sdks/node/src/head.ts) `async function* streamLines(`),
   then fed to `SseParser`, which accumulates `data:` lines only, joins them
   with newlines on a blank line, and drops anything that is not a JSON object
   ([`sdks/node/src/head.ts:45`](../../../sdks/node/src/head.ts) `const event: unknown = JSON.parse(payload);`).
   *Failure:* a malformed frame returns `null` and is skipped; it is never fatal.

### 5.5 Streaming and reattaching (web SDK)

`streamChat` ([`sdks/web/src/client.ts:2565`](../../../sdks/web/src/client.ts) `async streamChat(`):

1. Headers: `accept: text/event-stream`, `content-type: application/json`,
   optional bearer, and `x-boltrig-csrf` whenever a CSRF token resolves.
2. A network throw with an aborted signal returns silently; otherwise
   `BoltrigApiError(0, null, "Chat connection failed")`.
3. **202 returns the `ChatQueued` body rather than throwing**
   ([`:2597`](../../../sdks/web/src/client.ts)
   `if (response.status === 202) return (await parseResponse(response)) as ChatQueued;`).
4. Any other non-ok, or a missing body, throws `BoltrigApiError`.
5. `pumpSse` drops `heartbeat` frames before the consumer sees them
   ([`sdks/web/src/client.ts:2627`](../../../sdks/web/src/client.ts) `if (event.type !== "heartbeat") onEvent(event);`).

`followConversation` ([`sdks/web/src/client.ts:515`](../../../sdks/web/src/client.ts) `async followConversation(`) is the resume path:

1. A `since` that is not a safe non-negative integer throws
   `BoltrigApiError(400, {reason:"invalid cursor"})` client-side before any
   request.
2. It GETs `/v1/conversations/{id}/events?follow=1&since=N`.
3. **HTTP 409 is idle, not an error**: it returns
   `{status:"idle", cursor: since}`
   ([`:550`](../../../sdks/web/src/client.ts)
   `if (response.status === 409) {`). The kernel returns exactly that when no
   run is active ([`boltrig/kernel/conversation_live_routes.py:204`](../../../boltrig/kernel/conversation_live_routes.py) `{"status": "idle", "conversation_id": conversation_id},`).
4. Each frame must carry a safe non-negative integer `cursor` and an `event`,
   or the pump throws `"Invalid chat follow frame"`; a cursor that goes
   backwards throws `"Chat follow cursor regressed"`
   ([`:571`](../../../sdks/web/src/client.ts)).
5. An abort at any point returns `{status:"aborted", cursor}` so the caller can
   resume from where it stopped.

### 5.6 Folding a stream into a turn

`normalizeEvents` is a single `forEach` over an exhaustive `switch`
([`sdks/web/src/chatTurnNormalizer.ts:55`](../../../sdks/web/src/chatTurnNormalizer.ts) `export function normalizeEvents(events: ChatEvent[]): NormalizedTurn {`). Seven
frame types are explicitly listed as no-ops so "the union stays exhaustive and a
future frame cannot be dropped by silence"
([`:103`](../../../sdks/web/src/chatTurnNormalizer.ts)): `heartbeat`,
`workflow_run`, `steer_queued`, `steer_consumed`, `artifact`,
`artifact_rejected`, `event_unavailable`.

Load-bearing pairing rules:

- `tool_result` matches its `tool_call` by `call_id`, searching in reverse;
  the fallback is the last pending entry with the same verb
  ([`:199`](../../../sdks/web/src/chatTurnNormalizer.ts)
  `const byId = ev.call_id`). An unmatched result creates its own entry rather
  than being lost.
- `subagent_end` matches on `child_run_id` and MUTATES the existing entry,
  because the entry is shared by reference with the timeline
  ([`:253`](../../../sdks/web/src/chatTurnNormalizer.ts)
  `"Matched on child_run_id, NOT on arrival order"`). A settle for a child
  never seen is ignored, not invented.
- A `hitl` frame with `kind === "question"` is routed to the questions list,
  not the approvals list, and is deduplicated by id
  ([`:277`](../../../sdks/web/src/chatTurnNormalizer.ts) `if (kind === "question") {`).
- A `hitl` carrying a `call_id` flips the matching tool to `"pending_human"`
  and, for an approval, raises its consequence to `"high"`
  ([`:270`](../../../sdks/web/src/chatTurnNormalizer.ts)).
- `workflow_step` upserts by `step_id` into one shared timeline card, so step
  rows settle in place instead of appending
  ([`:329`](../../../sdks/web/src/chatTurnNormalizer.ts)).

### 5.7 Compiling a capability form (web SDK)

`compileCapabilityForm(schema)` walks a registry-supplied JSON Schema and
returns either `{status:"ready", fields, required_object_paths}` or
`{status:"unavailable", reason}`
([`sdks/web/src/capabilityInvocation.ts:420`](../../../sdks/web/src/capabilityInvocation.ts) `export function compileCapabilityForm(schema: unknown)`). It refuses 25 schema
keywords outright ([`:1`](../../../sdks/web/src/capabilityInvocation.ts)
`const UNSUPPORTED_SCHEMA_KEYS = [`), bans three reserved property names
(`__proto__`, `prototype`, `constructor`), allows three string formats, four
scalar types, five nesting levels and 100 fields.

`buildCapabilityParams` re-validates each string value against the field's
constraints and returns `{status:"invalid", field_errors}` rather than throwing
([`:510`](../../../sdks/web/src/capabilityInvocation.ts)).

`projectCapabilityOutput` hides any payload whose schema is absent or empty:
`"The capability has no closed output schema, so its payload is not rendered here."`
([`sdks/web/src/capabilityInvocation.ts:658`](../../../sdks/web/src/capabilityInvocation.ts) `"has no closed output schema, so its payload"`).

### 5.8 The marketing site's console page

1. `/console` renders `ConsoleView`
   ([`site/src/app/console/page.tsx:4`](../../../site/src/app/console/page.tsx) `return <ConsoleView />;`).
2. On mount, `loadSettings()` reads only the API base from `sessionStorage`;
   the bearer is always returned empty
   ([`site/src/views/console/client.ts:32`](../../../site/src/views/console/client.ts) `bearerToken: "",`).
3. `fetchOverview` GETs `{apiBase}/v1/console/overview?limit=50` with an
   `authorization` header built from whatever the user typed
   ([`:50`](../../../site/src/views/console/client.ts)
   `export async function fetchOverview(settings: ConsoleSettings)`).
   *Failure:* a non-ok response throws `Console API returned ${status}`; the
   view catches it, shows the message and reopens the connection form
   ([`site/src/views/console/console-view.tsx:44`](../../../site/src/views/console/console-view.tsx) `setError(err instanceof Error ? err.message : "Console API failed");`).
4. A 30-second interval refetches
   ([`:59`](../../../site/src/views/console/console-view.tsx)
   `window.setInterval(() => void loadWith(settings), 30_000)`).
5. `respondApproval` POSTs `{apiBase}/v1/hitl/{id}/respond` with `{decision}`.
6. `saveSettings` persists only the base and actively removes any stored token
   key ([`site/src/views/console/client.ts:47`](../../../site/src/views/console/client.ts) `window.sessionStorage.removeItem(TOKEN_KEY);`).

---

## 6. Data

Neither SDK owns a database table, a migration, or an index. The only durable
state either touches is:

| Store | Key | Written by | Retention |
| --- | --- | --- | --- |
| Browser `sessionStorage` | `boltrig.console.apiBase` | `site/src/views/console/client.ts:46` `"setItem(API_BASE_KEY, settings.apiBase.trim())"` | tab lifetime |
| Browser `sessionStorage` | `boltrig.console.bearerToken` | never written; explicitly removed on every save ([`site/src/views/console/client.ts:47`](../../../site/src/views/console/client.ts) `removeItem(TOKEN_KEY)`) | n/a |
| Browser cookie (read only) | `boltrig_csrf` | read by `browserCsrfToken()` ([`sdks/web/src/client.ts:312`](../../../sdks/web/src/client.ts) `part.startsWith("boltrig_csrf=")`) | set by the kernel |
| In-process `Map` | character id to frozen `Character` | `registerCharacter` ([`sdks/web/src/characters.ts:276`](../../../sdks/web/src/characters.ts) `REGISTRY.set(character.id, registered`) | page lifetime |
| In-process `Map` | verb name to `VerbDef` | `createBoltrigMcpServer` ([`sdks/node/src/server.ts:248`](../../../sdks/node/src/server.ts) `const tools = new Map<string, VerbDef>(`) | process lifetime |

**Encryption:** none is performed in this area. Bearer material is held only in
memory and on the wire. The `sha256` in `tokenMatches` is used to equalise
lengths for `timingSafeEqual`, not as storage
([`sdks/node/src/server.ts:226`](../../../sdks/node/src/server.ts) `const a = createHash("sha256").update(presented).digest();`).

**Size bounds enforced in this area:**

| Bound | Value | Where |
| --- | --- | --- |
| JSON-RPC request body | 1,000,000 chars | [`sdks/node/src/server.ts:359`](../../../sdks/node/src/server.ts) `if (raw.length > 1_000_000) {` |
| Display object envelope | 65,536 bytes encoded | [`sdks/web/src/displayObjectValidation.ts:33`](../../../sdks/web/src/displayObjectValidation.ts) `const MAX_BYTES = 65_536;` |
| Display JSON depth / breadth | depth 6, 100 array items, 64 object keys, 32,768-char strings | [`sdks/web/src/displayObjectValidation.ts:262`](../../../sdks/web/src/displayObjectValidation.ts) `"function safeJSON(value: unknown, depth = 0)"` |
| Capability form fields / depth | 100 fields, depth 5 | [`sdks/web/src/capabilityInvocation.ts:32`](../../../sdks/web/src/capabilityInvocation.ts) `const MAX_FIELDS = 100;` |
| Capability output items / strings | 100 items, 10,000 chars | [`sdks/web/src/capabilityInvocation.ts:34`](../../../sdks/web/src/capabilityInvocation.ts) `const MAX_OUTPUT_ITEMS = 100;` |
| Character id / name / blurb | 64-char id grammar, 64-char name, 240-char blurb | [`sdks/web/src/characters.ts:202`](../../../sdks/web/src/characters.ts) `const CHARACTER_ID = /^[a-z][a-z0-9-]{0,63}$/;` |
| Familiar gesture duration | clamped to 60,000 ms | [`sdks/web/src/familiarState.ts:225`](../../../sdks/web/src/familiarState.ts) `"remainingMs: num(expression.remainingMs, 0, 60_000)"` |
| Familiar parallel workers | clamped to 64 | [`sdks/web/src/familiarState.ts:219`](../../../sdks/web/src/familiarState.ts) `parallelWorkers: count(activity.parallelWorkers, 64),` |

---

## 7. Configuration surface

### Node SDK

| Name | Default | Read at | If wrong |
| --- | --- | --- | --- |
| `BOLTRIG_MCP_TOKEN` (name overridable by `options.tokenEnv`) | none | [`sdks/node/src/server.ts:239`](../../../sdks/node/src/server.ts) `const expectedToken = process.env[tokenEnv];` | server refuses to start; fail closed |
| `BOLTRIG_TOKEN` | none | [`sdks/node/src/http.ts:46`](../../../sdks/node/src/http.ts) `process.env.BOLTRIG_TOKEN` | `KernelApiError` with status 0 and a message naming `/v1/me/tokens` |
| `BOLTRIG_CLI_TOKEN` | none | same line, second fallback | as above |
| `OPBOX_MCP_TOKEN`, `OPBOX_PORT` | none, `0` | [`sdks/node/examples/opbox-verbs/server.ts:174`](../../../sdks/node/examples/opbox-verbs/server.ts) `Number(process.env.OPBOX_PORT ?? "0") || 0` | example only |
| `options.host` | `127.0.0.1` | [`sdks/node/src/server.ts:388`](../../../sdks/node/src/server.ts) `const host = options.host ?? "127.0.0.1";` | binding a public address makes the verb server internet-facing; the comment forbids it |

### Web SDK

The package reads no environment variable. Every knob is a constructor option
(section 4.2). The one implicit input is `document.cookie`, used only when no
`csrfToken` supplier and no `accessToken` are configured
([`sdks/web/src/client.ts:350`](../../../sdks/web/src/client.ts) `private csrf(): string | null {`).

### Site

| Name | Default | Read at | If wrong |
| --- | --- | --- | --- |
| `NEXT_PUBLIC_SITE_URL` | `https://boltrig.ai` | [`site/src/lib/site.ts:23`](../../../site/src/lib/site.ts) `publicEnv.NEXT_PUBLIC_SITE_URL ?? "https://boltrig.ai"` | canonicals, OG urls, sitemap and JSON-LD all name the wrong origin |
| `NEXT_PUBLIC_BOLTRIG_API_BASE` | `""` (same origin) | [`site/src/views/console/client.ts:31`](../../../site/src/views/console/client.ts) `process.env.NEXT_PUBLIC_BOLTRIG_API_BASE ?? ""` | the console page defaults to same-origin `/v1`, which the static host does not serve |
| `CONTACT_ENDPOINT` | none | [`site/src/env.ts:20`](../../../site/src/env.ts) `CONTACT_ENDPOINT: z.url().optional()` | unreachable; `getServerEnv` has no caller |
| `NODE_ENV` | build-set | [`site/next.config.ts:16`](../../../site/next.config.ts) `process.env.NODE_ENV === "production"` | `console.*` survives into the production bundle |

`NEXT_PUBLIC_BOLTRIG_API_BASE` is absent from the validated `publicSchema`
([`site/src/env.ts:14`](../../../site/src/env.ts) `const publicSchema = z.object({`) and from the vault's environment table
([`site/obsidian/architecture/environment-variables.md:22`](../../../site/obsidian/architecture/environment-variables.md) `"Site origin (no trailing slash). Drives canonical URLs"`), and appears exactly once in the whole
tree (bounded: `rg -n "NEXT_PUBLIC_BOLTRIG_API_BASE"`, 2026-08-24, pinned tree).

### The Worker embed knobs (owned by `apps/worker`, consumed by a host)

| Name | Meaning | Where |
| --- | --- | --- |
| `VITE_API_BASE` | absolute API origin baked at build; empty on the web image | [`apps/worker/src/apiOrigin.ts:42`](../../../apps/worker/src/apiOrigin.ts) `const built = (import.meta.env.VITE_API_BASE ?? "")` |
| document pathname | derives the subpath mount when `VITE_API_BASE` is empty | [`apps/worker/src/apiOrigin.ts:27`](../../../apps/worker/src/apiOrigin.ts) `export function mountPrefix(): string {` |
| `?theme=light\|dark` | per-load theme override, never persisted | [`apps/worker/src/theme.ts:63`](../../../apps/worker/src/theme.ts) `export function forcedThemeOverride()` |
| `?embed=1` | host supplies the chrome | [`apps/worker/src/theme.ts:73`](../../../apps/worker/src/theme.ts) `"True when the page was opened with"` |

---

## 8. PROCESS

### 8.1 How a third party embeds Boltrig, as decided and as built

Decision 0030 originally ruled the Agents tab must be built Opbox-native on the
web SDK, with "No iframe anywhere in the combined product"
([`docs/decisions/0030-agents-tab-built-on-web-sdk.md:31`](../../../docs/decisions/0030-agents-tab-built-on-web-sdk.md) `"The Agents tab (and every Opbox-side Boltrig surface) is built"`). Its stated reasons were three
mechanical facts: the Worker's `X-Frame-Options: DENY`, Opbox's own `frame-src`
allowlist, and the fact that CSS custom properties do not cross a frame.

**The decision was amended on 2026-08-21 and the amendment is what shipped.**
"No iframe anywhere" narrowed to "no CROSS-ORIGIN iframe anywhere"
([`docs/decisions/0030-agents-tab-built-on-web-sdk.md:56`](../../../docs/decisions/0030-agents-tab-built-on-web-sdk.md) `"No iframe anywhere" narrows to "no CROSS-ORIGIN iframe`). The sanctioned mechanism
is a same-origin subpath mount:

1. The host serves the Worker at `<its-own-host>/boltrig` behind a stripping
   proxy, and frames it same-origin.
2. The Worker derives its API base from the document pathname, never from a
   declaration ([`apps/worker/src/apiOrigin.ts:13`](../../../apps/worker/src/apiOrigin.ts) `"the mount is DERIVED from the document, never declared"`). A directory
   path, an `/index.html`, or an extensionless path is a mount; a path whose
   final segment contains a dot means root.
3. The UI-serving layers relaxed to `SAMEORIGIN` and `frame-ancestors 'self'`
   ([`apps/worker/nginx.conf:24`](../../../apps/worker/nginx.conf) `add_header X-Frame-Options "SAMEORIGIN" always;`;
   [`deploy/Caddyfile.example:21`](../../../deploy/Caddyfile.example) `X-Frame-Options "SAMEORIGIN"`), pinned by invariant SEC-WRK-05
   ([`tests/invariants.yaml:2429`](../../../tests/invariants.yaml) `"forbids objects and framing"`).
4. The host passes `?theme=light&embed=1` per load.
5. The session cookie stays `SameSite=Strict`, which is the reason the
   same-origin mount was chosen over a cross-origin embed
   ([`docs/decisions/0030-agents-tab-built-on-web-sdk.md:63`](../../../docs/decisions/0030-agents-tab-built-on-web-sdk.md) `"a same-origin mount needs no cookie relaxation"`).

**None of the embed contract is exported by either SDK.** `mountPrefix`,
`forcedThemeOverride` and `isEmbedMode` live in `apps/worker/src`, are not
re-exported by `sdks/web/src/index.ts`, and have no counterpart there
(bounded: `grep -n "mountPrefix\|isEmbedMode\|forcedTheme" sdks/web/src/*.ts`
returns nothing, 2026-08-24, pinned tree). A third party embedding Boltrig
today uses the mount plus two query parameters, which are documented only in a
decision file and in `apps/worker` source comments.

The SDK-native path remains the long-run direction for host-owned VIEWS
([`docs/decisions/0030-agents-tab-built-on-web-sdk.md:74`](../../../docs/decisions/0030-agents-tab-built-on-web-sdk.md) `"Agents tab remains the long-run direction for"`).

### 8.2 How a third party publishes verbs to Boltrig

The full sequence, from `sdks/node/README.md`:

1. Build the verb table and `createBoltrigMcpServer`; print `server.url`.
2. Operator step, once: `login` as the owner, then `mintPat` and store the
   secret as the app's `BOLTRIG_TOKEN`. The secret is shown once.
3. `registerMcpServer({id, url, credentialRef})`. **The registration lands
   INERT** under the SEC-22 review gate: the row shows `activated: false` and
   execution refuses with `mcp server pending review`
   ([`sdks/node/README.md:137`](../../../sdks/node/README.md) `"lands **INERT** (the SEC-22 review gate)"`).
4. `activateAdapter`. This is high-consequence and pends a human. **Four eyes
   are enforced**: the requester may not approve their own request, so the
   `respondToHitl` call must come from a second principal
   ([`sdks/node/README.md:154`](../../../sdks/node/README.md) `"the requester may NOT approve their own request"`).
5. Re-call `activateAdapter` with `approvalId` set to the approved
   `hitlRequestId`.
6. Grants still have to cover the prefixed verb ids; activation publishes
   bindings, not authority
   ([`sdks/node/README.md:163`](../../../sdks/node/README.md) `"Activation publishes verb *bindings*; agents still need grants"`).

One adapter id per tenant or environment
([`sdks/node/README.md:251`](../../../sdks/node/README.md) `"One adapter id per app instance"`).

### 8.3 How each package is built, tested and released

| Package | Build | Test | Release |
| --- | --- | --- | --- |
| `sdks/node` | `tsc -p tsconfig.json` to `dist/` | [`sdks/node/package.json:13`](../../../sdks/node/package.json) `"npm run build && node --test"` | none: it is private, with no registry |
| `sdks/web` | `tsc -p tsconfig.json`, also run by `prepare` and `prepublishOnly` | [`sdks/web/package.json:66`](../../../sdks/web/package.json) `"npm run build && node --test"` | `npm publish` to GitHub Packages under `@wlilley93`, gated |
| `site` | `next build` with `output: "export"` | `vitest run --coverage` | manual copy to `/srv/boltrig-marketing` |

**The web SDK publish is a RESERVED act.** `wlilley93/boltrig` is public, so
publishing is a public release requiring a release warrant or Principal
authorisation plus a human checkpoint
([`sdks/web/PUBLISHING.md:9`](../../../sdks/web/PUBLISHING.md) `"Route decision (VJS-ACT 6 s1)"`). The authorised command
sequence is recorded in full
([`sdks/web/PUBLISHING.md:40`](../../../sdks/web/PUBLISHING.md) `cd sdks/web`),
and a release receipt for `@wlilley93/boltrig-web-sdk@0.1.0` is logged
([`:77`](../../../sdks/web/PUBLISHING.md)
`"Release receipt (VJS-ACT 6 s6)"`).

**What runs in CI.** `make quality` aggregates `public-product-validate`,
`python-quality`, `worker-quality`, `site-quality`, `compose-validate`,
`doctor-fixture`, `migration-parity`, `security-source`
([`Makefile:389`](../../../Makefile)
`quality: public-product-validate python-quality worker-quality site-quality`).
`site-quality` runs audit, `eslint --max-warnings=0`, `vitest run --coverage`
and `next build` ([`Makefile:259`](../../../Makefile)
`site-quality: site-install ## Audit, lint, test with coverage, and build the site`).
`worker-quality` runs the Worker's structure ratchets, audit, `tsc --noEmit`,
`vitest` and `vite build`, which typechecks and bundles the web SDK source
through the path alias ([`Makefile:241`](../../../Makefile)
`worker-quality: worker-structure`).

**Neither SDK package's own test suite is run by any repository gate.** The
only Makefile mention of either is an existence check on one lockfile
([`Makefile:446`](../../../Makefile)
`@test -f apps/worker/pnpm-lock.yaml -a -f site/pnpm-lock.yaml -a -f sdks/node/pnpm-lock.yaml`),
and `.github/` mentions `sdks` nowhere (bounded: `rg -n "sdks" Makefile .github/`,
2026-08-24, pinned tree, two hits total, both on that one line). That leaves
38 `node:test` cases in `sdks/node/tests` and 78 in `sdks/web/tests` invoked by
nothing.

**The site's deployment is out of repository.** The host Caddy on
`jellytot-prod` serves `boltrig.ai` and `www.boltrig.ai` from
`/srv/boltrig-marketing` and is "**not in this repository**"
([`docs/DEPLOYMENT.md:90`](../../../docs/DEPLOYMENT.md) `"/etc/caddy/Caddyfile`, which is **not in this"`). No script in the tree copies a build
there (bounded: `rg -n "boltrig-marketing|srv/boltrig" --no-heading`,
2026-08-24, pinned tree: one comment in `scripts/cf-wire-boltrig.py` and the
DEPLOYMENT table row).

### 8.4 Diagnosing a broken embed or a broken verb server

| Symptom | First check | Cited behaviour |
| --- | --- | --- |
| Every kernel call from a mounted console 404s | is the final path segment extensionless or a directory? | [`apps/worker/src/apiOrigin.ts:33`](../../../apps/worker/src/apiOrigin.ts) `const finalSegment = path.slice(path.lastIndexOf("/") + 1);` |
| Verb server 401s every call | is the bearer the static token, or an on-behalf bearer with no `resolveIdentity` hook? | [`sdks/node/src/server.ts:269`](../../../sdks/node/src/server.ts) `!tokenMatches(bearer, expectedToken as string)` |
| A verb is gated for approval that should not be | did the app omit `consequence`? absence reads HIGH | [`boltrig/adapters/mcp_tool_policy.py:52`](../../../boltrig/adapters/mcp_tool_policy.py) `return Consequence.HIGH.value` |
| A tool never appears in the registry | does `<adapter-id>.<tool>` form a legal verb id? | [`boltrig/adapters/mcp_discovery.py:177`](../../../boltrig/adapters/mcp_discovery.py) `log.warning(` once per page |
| A chat retry produced N answers | mint one `idempotency_key` per user MESSAGE, not per attempt | [`docs/addons.md:149`](../../../docs/addons.md) `"Mint the key once per user message, **not** per HTTP attempt"` |
| The Worker shows a capability's output as unavailable | the verb has no `outputSchema`; the Node SDK cannot declare one | [`sdks/web/src/capabilityInvocation.ts:658`](../../../sdks/web/src/capabilityInvocation.ts) `"has no closed output schema, so its payload"` |

---

## 9. Failure modes and posture

| Guard | Direction | Proof |
| --- | --- | --- |
| Missing verb-server token env var | **fail closed**: the process refuses to start | [`sdks/node/src/server.ts:240`](../../../sdks/node/src/server.ts) `if (!expectedToken) {` |
| Bearer absent or wrong on any JSON-RPC method | **fail closed**: `-32001` / HTTP 401 before dispatch, including `tools/list` | [`sdks/node/src/server.ts:266`](../../../sdks/node/src/server.ts) `return err(rid, -32001, "unauthorized", 401);` |
| `resolveIdentity` returns null | **fail closed**: same refusal | [`sdks/node/src/server.ts:266`](../../../sdks/node/src/server.ts) `return err(rid, -32001, "unauthorized", 401);` |
| Unexpected handler throw | **fail closed on information**: a fixed reason string | [`sdks/node/src/server.ts:324`](../../../sdks/node/src/server.ts) `return ok(rid, toolResultError("error", "verb handler error"));` |
| Undeclared verb consequence | **fail closed at the kernel**: reads HIGH | [`boltrig/adapters/mcp_tool_policy.py:41`](../../../boltrig/adapters/mcp_tool_policy.py) `"absence is not evidence"` |
| Versioned `implements` claim | **fail closed**: refused, never reinterpreted | [`sdks/node/src/server.ts:215`](../../../sdks/node/src/server.ts) `"implements must not pin a version"` |
| Malformed SSE frame, Node head client | **fail open, tolerant**: dropped, stream continues | [`sdks/node/src/head.ts:50`](../../../sdks/node/src/head.ts) `} catch {` returning null |
| Malformed SSE frame, web SDK | **fail closed on the whole stream**: `JSON.parse` throws out of the pump | [`sdks/web/src/client.ts:2654`](../../../sdks/web/src/client.ts) `onFrame(JSON.parse(data) as T);` |
| Chat follow cursor regression | **fail closed**: throws rather than replaying | [`sdks/web/src/client.ts:572`](../../../sdks/web/src/client.ts) `"Chat follow cursor regressed"` |
| Untrusted display object | **fail closed**: `parseDisplayObject` returns `null` on any violation | [`sdks/web/src/displayObjectValidation.ts:37`](../../../sdks/web/src/displayObjectValidation.ts) `value.schema !== DISPLAY_OBJECT_SCHEMA) return null;` |
| A non-https URL inside a display object | **fail closed**: any `url`/`href`/`image_url` key must parse as https with no credentials | [`sdks/web/src/displayObjectValidation.ts:279`](../../../sdks/web/src/displayObjectValidation.ts) `return parsed.protocol === "https:" && Boolean(parsed.hostname)` |
| Untrusted familiar state | **fail soft, per field**: each block falls back independently to the resting state | [`sdks/web/src/familiarState.ts:165`](../../../sdks/web/src/familiarState.ts) `"field falls back INDEPENDENTLY (a malformed voice block"` |
| Stale or reordered familiar state | **fail closed**: `null` when `seq <= lastSeq` | [`sdks/web/src/familiarState.ts:178`](../../../sdks/web/src/familiarState.ts) `"if (lastSeq !== undefined && raw.seq <= lastSeq)"` |
| Malformed character bundle | **fail closed and loud**: every check throws `CharacterBundleError` with the field name | [`sdks/web/src/characterBundle.ts:16`](../../../sdks/web/src/characterBundle.ts) `"FAILURE IS LOUD ON PURPOSE"` |
| Bundle export of derived state | **fail closed**: allow-list of 17 fields, and `travels:false` outranks caller consent | [`sdks/web/src/characterBundle.ts:467`](../../../sdks/web/src/characterBundle.ts) `"AN ALLOW-LIST, NOT A DENY-LIST"` |
| Duplicate character id or folded-case name | **fail closed**: `TypeError`, no silent replacement | [`sdks/web/src/characters.ts:258`](../../../sdks/web/src/characters.ts) `if (REGISTRY.has(character.id)) {` |
| A broken registry listener | **fail open by design**: caught and ignored, because registration is already committed | [`sdks/web/src/characters.ts:284`](../../../sdks/web/src/characters.ts) `} catch {` |
| Unresolvable character id | **fail soft**: it returns `undefined` rather than throwing | [`sdks/web/src/characters.ts:307`](../../../sdks/web/src/characters.ts) `export function characterFor<TNode = unknown>(` |
| Unsupported capability schema | **fail closed on the surface**: `{status:"unavailable", reason}`, no free-text JSON console | [`sdks/web/src/capabilityInvocation.ts:422`](../../../sdks/web/src/capabilityInvocation.ts) `"The registry did not provide an object input schema."` |
| Capability output with no closed schema | **fail closed**: hidden with a stated reason | [`sdks/web/src/capabilityInvocation.ts:658`](../../../sdks/web/src/capabilityInvocation.ts) `"has no closed output schema, so its payload"` |
| Governed 202 | **fail open by design**: `tolerateStatus:true` so the pending-human body reaches the caller instead of raising | [`sdks/web/src/client.ts:419`](../../../sdks/web/src/client.ts) `tolerateStatus: true,` |
| Cookie leakage to a bearer host | **fail closed**: credentials default to `"omit"` when `accessToken` is configured | [`sdks/web/src/client.ts:338`](../../../sdks/web/src/client.ts) `return this.options.accessToken ? "omit" : "include";` |
| CSRF token for a bearer client | **fail closed**: no `document.cookie` read at all | [`sdks/web/src/client.ts:352`](../../../sdks/web/src/client.ts) `return this.options.accessToken ? null : browserCsrfToken();` |
| Site console API failure | **fail soft**: message shown, connection form reopened, poll continues | [`site/src/views/console/console-view.tsx:45`](../../../site/src/views/console/console-view.tsx) `setShowConnection(true);` |
| Site console token persistence | **fail closed**: the token key is removed on every save | [`site/src/views/console/client.ts:47`](../../../site/src/views/console/client.ts) `window.sessionStorage.removeItem(TOKEN_KEY);` |

---

## 10. What is proven

### Tests inside the packages (real, and unrun by any gate)

| Suite | Cases | What it pins |
| --- | --- | --- |
| `sdks/node/tests/server.test.ts` | 11 | verb-table refusals, fail-closed startup, envelope shapes, constant-time auth on every method, `initialize`/`ping` parity, and that an unmarked verb sends NO `consequence` key ([`sdks/node/tests/server.test.ts:138`](../../../sdks/node/tests/server.test.ts) `assert.equal("consequence" in list, false);`) |
| `sdks/node/tests/head.test.ts` | 10 | `data:`-only parsing, multi-line joins, dropped malformed frames, render dispatch, HITL routes |
| `sdks/node/tests/register.test.ts` | 9 | request shaping (refs only), pending-human passthrough, approval header replay, refusal messages without the token |
| `sdks/node/tests/g1-g2-per-user-bearer.test.ts` | 8 | `resolveIdentity` authorises and reaches the handler, rejects unresolvable bearers, and leaves the static path byte-identical when absent; `onBehalfBearer`/`idempotencyKey`/`origin` ride the turn body |
| `sdks/web/tests/worker-contracts.test.ts` | 27 | transport posture (cookie vs bearer defaults, CSRF), the follow-cursor projection and its idle branch, the integration catalogue's size and uncertified default, the device-lease contract, and that every Worker parity method stays on its canonical scoped route |
| `sdks/web/tests/worker-extension-contracts.test.ts` | 15 | that every governed method replays its approval on its own exact canonical route with its exact body, across agents, MCP, adapters, fleet, knowledge, memory, work, channels and workflows |
| `sdks/web/tests/normalize.test.ts` | 10 | the reducer's accumulate/settle/ignore rules including `subagent_end` matching by `child_run_id` |
| `sdks/web/tests/{account,addon,audit-pagination,birth-profile,capability-invocation,character,displayObjects,familiar-state,federated-search}-contracts.test.ts` | 26 | the remaining per-module contracts |

### Cross-language gates that DO run

| Gate | Invariant | What it reads from this area |
| --- | --- | --- |
| `tests/security/test_worker_route_ledger.py::test_every_http_route_has_an_exact_worker_or_non_ui_classification` | SEC-WRK-22 | that all 306 served routes are classified ([`tests/worker_surface_ledger.py:856`](../../../tests/worker_surface_ledger.py) `EXPECTED_ROUTE_COUNT = 306`) |
| `::test_every_worker_route_names_a_real_sdk_contract_and_component_callsite` | SEC-WRK-22, SEC-WRK-30 | that each declared route names an existing public method in `sdks/web/src/client.ts` AND a Worker source that calls `client.<method>` ([`tests/security/test_worker_route_ledger.py:74`](../../../tests/security/test_worker_route_ledger.py) `assert surface.sdk_method in sdk_methods`) |
| `::test_every_sdk_method_is_used_by_worker_or_explicitly_classified` | SEC-WRK-22 | that the set of public SDK methods the Worker never calls equals exactly the eight classified entries ([`tests/security/test_worker_route_ledger.py:102`](../../../tests/security/test_worker_route_ledger.py) `assert sdk_only == set(SDK_ONLY_METHODS)`) |
| `tests/unit/test_display_objects.py::test_kernel_and_browser_template_catalogues_cannot_drift` | none (unbound) | that the browser catalogue's `kind` set equals the kernel's ([`tests/unit/test_display_objects.py:95`](../../../tests/unit/test_display_objects.py) `browser_kinds = set(re.findall(r'\{ kind: "([^"]+)"', source))`) |
| `tests/security/test_invoke_finalization.py::test_worker_runner_has_no_raw_authority_or_changed_request_replay_surface` | SEC-WRK-28 | two literal sentences inside `capabilityInvocation.ts` ([`tests/security/test_invoke_finalization.py:132`](../../../tests/security/test_invoke_finalization.py) `assert "secret-shaped fields require a purpose-built secure-input surface" in compiler`) |
| `tests/security/test_worker_network_policy.py::test_worker_contract_refuses_universal_coverage_or_raw_network_authoring` | SEC-WRK-35 | two literal declarations inside `types.ts` ([`tests/security/test_worker_network_policy.py:225`](../../../tests/security/test_worker_network_policy.py) `assert "universal_egress_control: false;" in sdk`) |
| `make worker-quality` | none | that `sdks/web/src` typechecks under `strict` and bundles, via the path alias |

The eight deliberately-unused SDK methods, each with a recorded classification
([`tests/worker_surface_ledger.py:817`](../../../tests/worker_surface_ledger.py) `SDK_ONLY_METHODS: dict[str, tuple[str, str]] = {`): `artifact`,
`artifactDownloadUrl`, `getCall`, `refreshCallMedia`,
`requestDeviceFileListLease`, `searchConversations`, `modelProfiles` and
`spawn`. The gate compares the SET exactly, not a count, so both a new
uncalled method and a newly-called classified one fail it.

### Site tests

Four test files, honestly measured. `site/vitest.config.ts` records the
re-baselined thresholds and states plainly what they mean: "this site has four
test files and almost no coverage. That is a real gap"
([`site/vitest.config.ts:34`](../../../site/vitest.config.ts) `"site has four test files and almost no coverage"`). Thresholds are
lines 1, statements 1, functions 2, branches 2
([`:38`](../../../site/vitest.config.ts) `lines: 1,`).

`site/src/data/features.test.ts` pins six groups of five, uniqueness, and a
four-phrase blocklist against advertising known seams
([`site/src/data/features.test.ts:29`](../../../site/src/data/features.test.ts) `for (const unsupportedClaim of [`).

---

## 11. RISKS

RISK: Both SDK packages ship complete test suites (38 and 78 cases) that no
Makefile target and no CI workflow ever runs; the only mention of `sdks` in
either is an existence check on one lockfile.
[`Makefile:446`](../../../Makefile)
`"@test -f apps/worker/pnpm-lock.yaml -a -f site/pnpm-lock.yaml -a -f sdks/node/pnpm-lock.yaml"`
(bounded: `rg -n "sdks" Makefile .github/`, 2026-08-24, pinned tree).

RISK: The Node SDK's `VerbError` status vocabulary is inert. It can emit
`_boltrig.status: "denied"`, but the consumer maps every `isError` result to
`ErrorClass.INVALID` and never reads `_boltrig.status`, and `ErrorClass` has no
`DENIED` member, so the distinction the SDK documents reaches no kernel
decision. [`boltrig/adapters/mcp_consumer.py:272`](../../../boltrig/adapters/mcp_consumer.py) `if result.get("isError"):` and
[`boltrig/adapters/base.py:52`](../../../boltrig/adapters/base.py) `NOT_FOUND = "not_found"`.

RISK: `VerbDef` has no `outputSchema` field and `tools/list` emits none, so
every verb published through the Node SDK renders its output as permanently
unavailable in the Worker's capability runner.
[`sdks/node/src/server.ts:290`](../../../sdks/node/src/server.ts) `"inputSchema: v.schema,"` against
[`sdks/web/src/capabilityInvocation.ts:658`](../../../sdks/web/src/capabilityInvocation.ts) `"has no closed output schema, so its payload"`

RISK: The kernel emits a replay `message_start` carrying no `run_id`, which the
SDK's own type declares as required and non-optional, and neither replay frame
declares the `replay: true` flag `docs/addons.md` promises consumers will see.
[`boltrig/fleet/chat_idempotency.py:120`](../../../boltrig/fleet/chat_idempotency.py) `{"type": "message_start", "conversation_id": conversation_id, "replay": True},`
against [`sdks/web/src/types.ts:820`](../../../sdks/web/src/types.ts) `"export interface ChatMessageStart {"` (bounded: `rg -n "replay" sdks/web/src/types.ts`,
2026-08-24, three hits, none of them a chat-event field).

RISK: The web SDK's SSE pump parses every frame with an unguarded `JSON.parse`,
so one malformed frame throws out of the pump and terminates the whole stream,
while the Node SDK's parser for the same wire format deliberately drops it.
[`sdks/web/src/client.ts:2654`](../../../sdks/web/src/client.ts) `"onFrame(JSON.parse(data) as T);"` against
[`sdks/node/src/head.ts:44`](../../../sdks/node/src/head.ts) `"try {"` returning null.

RISK: `buildCapabilityParams` compiles a registry-supplied `pattern` into a
`RegExp` and runs it against user input with no complexity or length bound,
which is the exact ReDoS shape the sibling Node SDK removed a regex to avoid
because it is "a PUBLISHED SDK".
[`sdks/web/src/capabilityInvocation.ts:460`](../../../sdks/web/src/capabilityInvocation.ts) `"!new RegExp(field.pattern).test(value)"` against
[`sdks/node/src/http.ts:58`](../../../sdks/node/src/http.ts) `"NO REGEX, deliberately."`

RISK: `parseCharacterBundle` spreads the raw manifest into its result and
validates only nine of the seventeen declared fields, so `prompts`, `identity`,
`voice`, `capabilities`, `distillation`, `credentials`, `provenance` and any
unknown key pass through unchecked, and `identity.anchorImages` /
`voice.selfHosted.*` asset paths never reach the `..`-and-absolute-path refusal
that visual assets do. The JSON Schema for the same object sets
`additionalProperties: false`.
[`sdks/web/src/characterBundle.ts:355`](../../../sdks/web/src/characterBundle.ts) `"...manifest,"` and
[`sdks/web/src/characterBundle.ts:195`](../../../sdks/web/src/characterBundle.ts) `"function assetRef(value: unknown, field: string)"` (bounded:
`grep -n "assetRef(" sdks/web/src/characterBundle.ts` shows five call sites, all
under `visual`).

RISK: `FamiliarPhenotypeScalar` documents ten server scalars including
`attachment`, but `FamiliarPhenotypeV2` and `sanitizeFamiliarState` carry only
nine, so `attachment` is dropped between the phenotype response and the
renderer state contract.
[`sdks/web/src/familiarState.ts:38`](../../../sdks/web/src/familiarState.ts) `"The ten server phenotype scalars"` against
[`:50`](../../../sdks/web/src/familiarState.ts) `"export interface FamiliarPhenotypeV2 {"`.

RISK: The marketing site ships an authenticated operations console at
`/console` that accepts a pasted bearer and posts it to an operator-supplied
cross-origin API base, on a statically exported site with no in-repo CSP, no
`headers()` configuration, and a `robots.txt` that allows all crawlers on `/`.
[`site/src/views/console/client.ts:20`](../../../site/src/views/console/client.ts) `"const token = settings.bearerToken.trim();"`,
[`site/next.config.ts:7`](../../../site/next.config.ts) `output: "export",`,
[`site/src/app/robots.ts:15`](../../../site/src/app/robots.ts) `allow: "/",`.

RISK: The site's console re-implements two kernel endpoints the SDK already
covers and carries its own narrower copy of the response types, with no drift
guard of any kind.
[`site/src/views/console/client.ts:6`](../../../site/src/views/console/client.ts) `"export function overviewUrl(apiBase: string, limit = 50)"` against
[`sdks/web/src/client.ts:971`](../../../sdks/web/src/client.ts) `"consoleOverview(limit = 20)"` and
[`sdks/web/src/client.ts:1375`](../../../sdks/web/src/client.ts) `"respondHitl(id: string, decision: string"`.

RISK: `site/eslint.config.mjs` disables eight rules including
`@typescript-eslint/no-explicit-any` and `no-unused-vars`, while the site's own
agent guide states rule 7 as "No `any`. Type everything. Run
`pnpm run lint:strict` before finishing" and `make site-quality` runs exactly
that command; `site/src` contains eight `any` usages that the strict lint
cannot see. [`site/eslint.config.mjs:18`](../../../site/eslint.config.mjs) `"@typescript-eslint/no-explicit-any"` against
[`site/AGENTS.md:37`](../../../site/AGENTS.md) `"7. **No `any`.** Type everything."` (bounded:
`rg -n ": any\b|<any>|as any" site/src`, 2026-08-24, eight hits).

RISK: `site/src/lib/api-client.ts` and `site/src/lib/api/index.ts` are
unreachable dead code: `output: "export"` forbids route handlers, there is no
`site/src/app/api` directory, and no file imports `apiFetch`, `ApiClientError`,
`handle` or `getServerEnv`.
[`site/src/lib/api/index.ts:37`](../../../site/src/lib/api/index.ts) `"export function handle<C extends RouteContext = RouteContext>("` (bounded:
`rg -n "apiFetch|ApiClientError|from \"@/lib/api\"|getServerEnv" site/src`,
2026-08-24: only their own definitions).

RISK: `site/README.md`, `site/AGENTS.md` and `site/HOW_TO_USE.md` are the
unmodified third-party starter's documents, describing a
"next16-claude-starter" and a "Neural Monitor" template rather than Boltrig's
site, and `HOW_TO_USE.md` prescribes `pnpm run start` on a project configured
for static export with no Node runtime in production.
[`site/README.md:1`](../../../site/README.md) `# next16-claude-starter`,
[`site/HOW_TO_USE.md:3`](../../../site/HOW_TO_USE.md) `"the complete source for the **Neural Monitor** project"`,
[`site/next.config.ts:5`](../../../site/next.config.ts) `"(no Node runtime on prod)"`.

RISK: `docs/SDK-CONTRACT-from-opbox.md` cites `ui/src/api/*` as the reference
implementation to extract, but no `ui/` directory exists in the pinned tree,
and it lists G1 and G2 as open gaps that shipped (`resolveIdentity` and
`onBehalfBearer` both exist with tests) and G5 as open when
`followConversation(since)` closed it.
[`docs/SDK-CONTRACT-from-opbox.md:496`](../../../docs/SDK-CONTRACT-from-opbox.md) `"G1. Per-user bearer never reaches the verb handler."` (bounded: `ls -d ui`
returns "No such file or directory", 2026-08-24, pinned tree).

RISK: `sdks/web/PUBLISHING.md` asserts a green drift guard at
`tests/drift.test.ts`, which does not exist anywhere in the tree, and logs a
release receipt for version `0.1.0` while `package.json` reads `0.2.0` with no
changelog to bridge them.
[`sdks/web/PUBLISHING.md:30`](../../../sdks/web/PUBLISHING.md) `"drift guard is green (`tests/drift.test.ts`)"` (bounded:
`find . -name "drift.test.ts" -not -path "./node_modules/*"`, 2026-08-24: no
result).

RISK: `sdks/node/README.md` still states the pre-2026-08-16 consequence rule,
"a tool's declared `consequence` hint propagates (capped at `\"high\"`, default
`\"low\"`)", which the kernel policy and the SDK's own source comment both
contradict. [`sdks/node/README.md:173`](../../../sdks/node/README.md) `"hint propagates (capped at"` against
[`sdks/node/src/server.ts:95`](../../../sdks/node/src/server.ts) `"since 2026-08-16 it fails CLOSED"`.

RISK: `sdks/node/src/server.ts`'s module docstring tells a reader the kernel
sends "no `initialize` handshake, no SSE, no session headers", which the
transport contradicts on all three counts (lazy handshake on 400/404,
`Accept: text/event-stream`, `Mcp-Session-Id` carried); the README in the same
package is correct and the docstring is not.
[`sdks/node/src/server.ts:8`](../../../sdks/node/src/server.ts) `"handshake, no SSE, no session headers"` against
[`boltrig/adapters/mcp_transport.py:12`](../../../boltrig/adapters/mcp_transport.py) `"The handshake is LAZY: the plain call goes out first."`

RISK: `sdks/web/src` is exempt from every structural ratchet in the repository.
The Worker's structure gate scans only `apps/worker/src` with a 400-line file
ceiling, while `types.ts` is 4459 lines and `client.ts` is 2661.
[`apps/worker/scripts/check-structure.mjs:21`](../../../apps/worker/scripts/check-structure.mjs) `const SOURCE_ROOT = "apps/worker/src";` and
[`:26`](../../../apps/worker/scripts/check-structure.mjs) `max_file_lines: 400,`.

RISK: Marketing copy is outside the Tier-0 claim ratchet. `build_claim_inventory.py`
scans only the `boltrig` package and compose files, so
`site/src/data/features.ts` (30 product claims) is checked by nothing but a
four-phrase substring blocklist in its own unit test.
[`scripts/build_claim_inventory.py:281`](../../../scripts/build_claim_inventory.py) `pkg = ROOT / "boltrig"` (bounded: `grep -c "site/" docs/claim-inventory.tsv`
returns 0, 2026-08-24).

RISK: Three site call-to-action links address `access@boltrig.io`, a mailbox on
the domain `docs/DEPLOYMENT.md` records as 301-redirected to `boltrig.ai` since
2026-08-18. [`site/src/components/common/site-header.tsx:47`](../../../site/src/components/common/site-header.tsx) `href="mailto:access@boltrig.io?subject=Boltrig%20access%20request"` against
[`docs/DEPLOYMENT.md:99`](../../../docs/DEPLOYMENT.md) `"301 to `https://boltrig.ai{uri}`"`.

RISK: The web SDK's character registry is a module-level mutable singleton in a
package the Worker resolves from source through two Vite aliases and one
tsconfig path; any consumer that reaches the package by a different resolution
(a subpath export, a `dist` install alongside the source alias) gets a second,
independent registry with no diagnostic.
[`sdks/web/src/characters.ts:200`](../../../sdks/web/src/characters.ts) `const REGISTRY = new Map<string, Character<never>>();` and
[`sdks/web/package.json:55`](../../../sdks/web/package.json) `"./characters"`.

RISK: 94 of this area's 100 requirements bind to no invariant id, including
every fail-closed guard inside both SDK packages. Only six bind, all through
`tests/invariants.yaml`'s Worker entries (SEC-WRK-05, SEC-WRK-22, SEC-WRK-28,
SEC-WRK-30, SEC-WRK-35), and those bind the WORKER's use of the SDK rather than
the SDK's own behaviour. The published client contract has no invariant of its
own. [`tests/invariants.yaml:2594`](../../../tests/invariants.yaml) `"SEC-WRK-22:"`.

RISK: The one gate that proves the browser and kernel display-object catalogues
cannot drift carries no invariant marker, so it is a test with no recorded
obligation behind it. [`tests/unit/test_display_objects.py:93`](../../../tests/unit/test_display_objects.py) `"def test_kernel_and_browser_template_catalogues_cannot_drift"` (bounded: `grep -n "invariant(" tests/unit/test_display_objects.py`, 2026-08-24, two markers, both SEC-WRK-31, neither on this test).

RISK: Two accepted decisions share the number 0030
(`0030-agents-tab-built-on-web-sdk.md` and `0030-familiar-modes-and-dials.md`),
so a citation to "decision 0030" is ambiguous.
[`docs/decisions/0030-agents-tab-built-on-web-sdk.md:1`](../../../docs/decisions/0030-agents-tab-built-on-web-sdk.md) `"# 0030 - Agents tab is built on the web SDK"`.

---

## 12. OPEN QUESTIONS

1. **Is `@wlilley93/boltrig-web-sdk@0.2.0` actually published?** The tree
   records a receipt for `0.1.0` only
   ([`sdks/web/PUBLISHING.md:79`](../../../sdks/web/PUBLISHING.md) `"release id: `@wlilley93/boltrig-web-sdk@0.1.0`"`) while `package.json`
   reads `0.2.0`. Settled by querying `npm view @wlilley93/boltrig-web-sdk versions`
   against GitHub Packages, which this reading must not do.
2. **Is there a stability promise at all?** Neither package carries a
   CHANGELOG, a semver policy, or a deprecation process (bounded:
   `find . -iname "CHANGELOG*"`, 2026-08-24: one hit, `site/obsidian/meta/changelog.md`,
   which is the starter's vault note). Settled by an owner statement, not by
   the tree.
3. **Does any consumer outside this repository import the web SDK?** The
   subpath exports exist and the package is public-scoped, but nothing in tree
   uses them. Settled by registry download stats or by naming the consumers.
4. **Does the site's `/console` page exist deliberately, or is it a
   development leftover?** It is linked from the persistent header as the
   product's "Open console"
   ([`site/src/components/common/site-header.tsx:41`](../../../site/src/components/common/site-header.tsx) `href="/console"`) while `app.boltrig.ai` is what two other CTAs point at.
   Settled by an owner decision about which console the marketing site should
   send a returning user to.
5. **Who copies `site/` build output to `/srv/boltrig-marketing`, and with what
   check?** No script in the tree does it. Settled by the host's own runbook,
   which is outside the pinned tree by design.
6. **Was the `sdks/node` package meant to stay `private: true`?** The
   SDK-CONTRACT calls it "the third-party plugin path"
   ([`docs/decisions/0038-opbox-is-a-client-of-boltrig.md:82`](../../../docs/decisions/0038-opbox-is-a-client-of-boltrig.md) `"`sdks/node` remains the third-party plugin path"`), which a private,
   unpublished package cannot serve. Settled by an owner decision.
7. **Should the web SDK's chat-event union declare `replay`?** The kernel emits
   it and `docs/addons.md` promises it; adding it is a contract change and
   therefore an owner call, not a reading.

---

## 13. Requirements

| id | statement | status | evidence | invariant |
| --- | --- | --- | --- | --- |
| BT-REQ-1600 | The Node SDK ships as the private, unpublished package `boltrig-app-sdk` at version 0.1.0 requiring Node 20 or later. | IMPLEMENTED-UNTESTED | `sdks/node/package.json:2` `"name": "boltrig-app-sdk"` | - |
| BT-REQ-1601 | The Node SDK has zero runtime dependencies and imports only `node:crypto` and `node:http`. | IMPLEMENTED-UNTESTED | `sdks/node/src/server.ts:32` `"import { createHash, timingSafeEqual }"` | - |
| BT-REQ-1602 | `createBoltrigMcpServer` refuses to start when the configured token environment variable is unset. | IMPLEMENTED | `sdks/node/tests/server.test.ts:95` `"server refuses to start without its token env var"` | - |
| BT-REQ-1603 | Every JSON-RPC method, including `tools/list` and `initialize`, requires the bearer before any dispatch. | IMPLEMENTED | `sdks/node/tests/server.test.ts:206` `"auth: every method requires the bearer"` | - |
| BT-REQ-1604 | An unauthorized call is answered `-32001 "unauthorized"` carried out as HTTP 401. | IMPLEMENTED | `sdks/node/src/server.ts:266` `return err(rid, -32001, "unauthorized", 401);` | - |
| BT-REQ-1605 | The static token comparison hashes both sides with SHA-256 so it is constant time and length independent. | IMPLEMENTED | `sdks/node/src/server.ts:226` `createHash("sha256").update(presented).digest()` | - |
| BT-REQ-1606 | Supplying `resolveIdentity` replaces the static compare, resolves the presented bearer to an identity, and passes `{bearer, identity}` to the handler. | IMPLEMENTED | `sdks/node/tests/g1-g2-per-user-bearer.test.ts:33` `"resolveIdentity authorizes a per-user bearer"` | - |
| BT-REQ-1607 | Omitting `resolveIdentity` leaves the static-token behaviour byte-identical and passes no context to handlers. | IMPLEMENTED | `sdks/node/tests/g1-g2-per-user-bearer.test.ts:75` `"WITHOUT a hook the static-token path is unchanged"` | - |
| BT-REQ-1608 | `validateVerbTable` refuses an empty table, a bad name charset, a reserved core prefix, a duplicate name, a missing description, a non-object schema and a non-function handler. | IMPLEMENTED | `sdks/node/tests/server.test.ts:60` `"rejects bad names, reserved prefixes, duplicates"` | - |
| BT-REQ-1609 | A verb declaring `implements` with an `@` version pin is refused rather than reinterpreted. | IMPLEMENTED-UNTESTED | `sdks/node/src/server.ts:215` `"implements must not pin a version"` | - |
| BT-REQ-1610 | `tools/list` omits the `consequence` key entirely for a verb that declares none, so absence travels as absence. | IMPLEMENTED | `sdks/node/tests/server.test.ts:138` `assert.equal("consequence" in list, false);` | - |
| BT-REQ-1611 | The kernel reads a tool carrying no consequence, no addon risk class and no annotation as HIGH consequence. | IMPLEMENTED-UNTESTED | `boltrig/adapters/mcp_tool_policy.py:52` `return Consequence.HIGH.value` | - |
| BT-REQ-1612 | A successful handler return is wrapped as `{content, isError:false, _boltrig:{status:"ok", output}}`. | IMPLEMENTED | `sdks/node/tests/server.test.ts:142` `"tools/call success wraps output in the _boltrig envelope"` | - |
| BT-REQ-1613 | A thrown `VerbError` becomes `{isError:true, _boltrig:{status, reason}}` and any other throw becomes the fixed reason `"verb handler error"`. | IMPLEMENTED | `sdks/node/tests/server.test.ts:175` `"unexpected handler throws map to a generic reason"` | - |
| BT-REQ-1614 | `VerbError`'s `"denied"` status reaches no kernel decision: the consumer maps every `isError` result to `ErrorClass.INVALID` and never reads `_boltrig.status`. | IMPLEMENTED-UNTESTED | `boltrig/adapters/mcp_consumer.py:272` `if result.get("isError"):` | - |
| BT-REQ-1615 | `VerbDef` cannot declare an output schema and `tools/list` never emits one. | IMPLEMENTED-UNTESTED | `sdks/node/src/server.ts:290` `inputSchema: v.schema,` | - |
| BT-REQ-1616 | The HTTP wrapper accepts POST only, answering 405 with an `allow: POST` header otherwise. | IMPLEMENTED-UNTESTED | `sdks/node/src/server.ts:349` `if (req.method !== "POST") {` | - |
| BT-REQ-1617 | The request body is bounded at 1,000,000 characters, answered 413 beyond it. | IMPLEMENTED-UNTESTED | `sdks/node/src/server.ts:359` `if (raw.length > 1_000_000)` | - |
| BT-REQ-1618 | The bearer is read from `x-boltrig-mcp-token` first and from `Authorization: Bearer` second. | IMPLEMENTED-UNTESTED | `sdks/node/src/server.ts:333` `const mcpToken = req.headers["x-boltrig-mcp-token"];` | - |
| BT-REQ-1619 | The server binds `127.0.0.1` by default because an app SDK verb server must not be internet facing. | IMPLEMENTED-UNTESTED | `sdks/node/src/server.ts:388` `const host = options.host ?? "127.0.0.1";` | - |
| BT-REQ-1620 | The scaffold answers `initialize` with protocol version `2024-11-05`, mirroring the kernel's own MCP face. | IMPLEMENTED | `sdks/node/tests/server.test.ts:223` `"initialize / ping mirror the kernel face shapes"` | - |
| BT-REQ-1621 | `registerMcpServer` sends credential REFERENCES only and has no parameter capable of carrying secret material. | IMPLEMENTED | `sdks/node/tests/register.test.ts:53` `"shapes the governed call: /v1/mcp/servers, refs only"` | - |
| BT-REQ-1622 | Registration and activation return `PendingHuman` on HTTP 202 rather than raising. | IMPLEMENTED | `sdks/node/tests/register.test.ts:81` `"passes a pending_human (HITL-gated) outcome through"` | - |
| BT-REQ-1623 | A previously approved HITL request is replayed as both an `approval_id` body field and an `x-boltrig-approval-id` header. | IMPLEMENTED | `sdks/node/tests/register.test.ts:113` `"re-applies an approval via the x-boltrig-approval-id header"` | - |
| BT-REQ-1624 | Kernel refusals are surfaced without the token appearing in the message. | IMPLEMENTED | `sdks/node/tests/register.test.ts:97` `"surfaces kernel refusals without the token"` | - |
| BT-REQ-1625 | A login requiring a second factor is mapped to a distinct message directing the caller to a PAT. | IMPLEMENTED | `sdks/node/tests/register.test.ts:174` `"login maps 2fa_required to a clear error"` | - |
| BT-REQ-1626 | `baseUrl` trims trailing slashes with a character loop rather than a regex, because a published SDK cannot assume its callers. | IMPLEMENTED-UNTESTED | `sdks/node/src/http.ts:58` `"NO REGEX, deliberately."` | - |
| BT-REQ-1627 | A missing token resolves through `BOLTRIG_TOKEN` then `BOLTRIG_CLI_TOKEN`, and otherwise raises a `KernelApiError` naming `/v1/me/tokens`. | IMPLEMENTED-UNTESTED | `sdks/node/src/http.ts:46` `process.env.BOLTRIG_TOKEN ?? process.env.BOLTRIG_CLI_TOKEN` | - |
| BT-REQ-1628 | `streamTurn` treats HTTP 202 as an acceptance and yields a synthetic `queued` event instead of reporting a failure. | IMPLEMENTED-UNTESTED | `sdks/node/src/head.ts:198` `if (resp.status === 202) {` | - |
| BT-REQ-1629 | `SseParser` accumulates `data:` lines only and drops comments and malformed or non-object payloads without dying. | IMPLEMENTED | `sdks/node/tests/head.test.ts:33` `"malformed JSON and non-object payloads are dropped, never fatal"` | - |
| BT-REQ-1630 | `streamTurn` carries `onBehalfBearer`, `idempotencyKey` and `origin` as first-class options that ride the turn body. | IMPLEMENTED | `sdks/node/tests/g1-g2-per-user-bearer.test.ts:127` `"onBehalfBearer rides in the chat turn body"` | - |
| BT-REQ-1631 | `origin` is a label only: it reaches no authority or routing decision and an unusable value is dropped rather than failing the message. | IMPLEMENTED-UNTESTED | `sdks/node/src/head.ts:159` `"A LABEL: it reaches no authority or routing decision"` | - |
| BT-REQ-1632 | `renderEvent` is a reference rendering that returns null for `message_start`, `heartbeat` and unknown types. | IMPLEMENTED | `sdks/node/tests/head.test.ts:86` `"subagent, cancelled, message_end, and null-rendered types"` | - |
| BT-REQ-1633 | The web SDK ships as the public-scoped package `@wlilley93/boltrig-web-sdk` at version 0.2.0 with `sideEffects:false` and a GitHub Packages registry. | IMPLEMENTED-UNTESTED | `sdks/web/package.json:2` `"@wlilley93/boltrig-web-sdk"` | - |
| BT-REQ-1634 | The web SDK has zero runtime dependencies and every import in its source resolves to a sibling module. | IMPLEMENTED-UNTESTED | `sdks/web/package.json:70` `"devDependencies"` | - |
| BT-REQ-1635 | The web SDK declares seven subpath exports beyond the root, none of which any file in the repository imports. | IMPLEMENTED-UNTESTED | `sdks/web/package.json:31` `"./types"` | - |
| BT-REQ-1636 | Publishing the web SDK is a RESERVED act requiring a release warrant or Principal authorisation plus a human checkpoint. | IMPLEMENTED-UNTESTED | `sdks/web/PUBLISHING.md:9` `"status: RESERVED"` | - |
| BT-REQ-1637 | The web SDK ships no built artefact in the tree: `dist/` is gitignored and produced by `prepublishOnly`. | IMPLEMENTED-UNTESTED | `sdks/web/.gitignore:2` `dist/` | - |
| BT-REQ-1638 | `BoltrigClient` is the single typed client over the kernel `/v1` surface, and the route-ledger gate enumerates every one of its public methods from its source. | IMPLEMENTED | `tests/security/test_worker_route_ledger.py:39` `def _public_sdk_methods(source: str) -> set[str]:` | SEC-WRK-22 |
| BT-REQ-1639 | Every served HTTP route names either a real SDK method with a Worker call site, a documented richer projection, or one explicit non-UI classification. | IMPLEMENTED | `tests/security/test_worker_route_ledger.py:68` `"names_a_real_sdk_contract_and_component_callsite"` | SEC-WRK-22 |
| BT-REQ-1640 | The eight public SDK methods the Worker does not call are each enumerated with a classification and a rationale, and a new uncalled method fails the gate. | IMPLEMENTED | `tests/security/test_worker_route_ledger.py:102` `assert sdk_only == set(SDK_ONLY_METHODS)` | SEC-WRK-22 |
| BT-REQ-1641 | A client configured with `accessToken` omits cookies and reads no cookie CSRF token; a cookie client is unchanged; an explicit setting wins over both. | IMPLEMENTED | `sdks/web/tests/worker-contracts.test.ts:1002` `"a bearer client sends no cookie and reaches for no cookie CSRF token"` | - |
| BT-REQ-1642 | Every mutating request carries the `x-boltrig-csrf` double-submit header when a token resolves. | IMPLEMENTED | `sdks/web/tests/worker-contracts.test.ts:51` `"browser transport sends cookie credentials, CSRF"` | - |
| BT-REQ-1643 | Governed writes tolerate a non-2xx status so a 202 pending-human body reaches the caller as a value rather than an exception. | IMPLEMENTED | `sdks/web/src/client.ts:419` `tolerateStatus: true,` | - |
| BT-REQ-1644 | Every governed SDK method replays an approval through its own exact route with its exact body and the internal approval id. | IMPLEMENTED | `sdks/web/tests/worker-extension-contracts.test.ts:671` `"fixed governed SDK methods replay through their same route"` | - |
| BT-REQ-1645 | `streamChat` returns the `ChatQueued` body on HTTP 202 rather than raising. | IMPLEMENTED-UNTESTED | `sdks/web/src/client.ts:2596` `if (response.status === 202) return` | - |
| BT-REQ-1646 | `followConversation` resumes from a caller-supplied cursor, rejects a non-safe-integer cursor client-side, and treats HTTP 409 as an idle conversation rather than an error. | IMPLEMENTED | `sdks/web/tests/worker-contracts.test.ts:542` `"reports an idle active-run lookup without inventing a run"` | - |
| BT-REQ-1647 | A follow frame whose cursor regresses aborts the stream rather than replaying. | IMPLEMENTED-UNTESTED | `sdks/web/src/client.ts:572` `"Chat follow cursor regressed"` | - |
| BT-REQ-1648 | Heartbeat frames are dropped inside the SSE pump and never reach a consumer. | IMPLEMENTED | `sdks/web/tests/worker-contracts.test.ts:453` `"uses projected cursor frames and ignores heartbeats"` | - |
| BT-REQ-1649 | A malformed SSE frame terminates the web SDK's stream, because the pump parses each frame with an unguarded `JSON.parse`. | IMPLEMENTED-UNTESTED | `sdks/web/src/client.ts:2654` `onFrame(JSON.parse(data) as T);` | - |
| BT-REQ-1650 | The `ChatEvent` union has exactly twenty one members and `normalizeEvents` handles every one, listing the seven lifecycle-only frames explicitly so none is dropped by silence. | IMPLEMENTED | `sdks/web/tests/normalize.test.ts:113` `"steer frames are lifecycle, not turn content"` | - |
| BT-REQ-1651 | A `tool_result` is paired to its `tool_call` by `call_id`, falling back to the last pending entry with the same verb. | IMPLEMENTED-UNTESTED | `sdks/web/src/chatTurnNormalizer.ts:199` `const byId = ev.call_id` | - |
| BT-REQ-1652 | `subagent_end` settles the matching delegation node in place by `child_run_id`, and a settle for an unseen child is ignored rather than invented. | IMPLEMENTED | `sdks/web/tests/normalize.test.ts:104` `"a settle for an unseen child is ignored, not invented"` | - |
| BT-REQ-1653 | `message_end` carries no token usage, so no consumer can reconcile actual model spend from the stream. | IMPLEMENTED-UNTESTED | `sdks/web/src/types.ts:930` `"export interface ChatMessageEnd {"` | - |
| BT-REQ-1654 | The replay frames the kernel emits for an accepted duplicate message carry a `replay` flag and no `run_id`, neither of which the SDK's chat-event types declare. | IMPLEMENTED-UNTESTED | `boltrig/fleet/chat_idempotency.py:120` `conversation_id, "replay": True},` | - |
| BT-REQ-1655 | The browser display-object catalogue holds exactly the kinds the kernel catalogue holds. | IMPLEMENTED | `tests/unit/test_display_objects.py:93` `"test_kernel_and_browser_template_catalogues_cannot_drift"` | - |
| BT-REQ-1656 | `parseDisplayObject` returns null on any contract violation and never coerces an invalid envelope into a renderable one. | IMPLEMENTED | `sdks/web/tests/displayObjects.test.ts:2` `import test from "node:test";` (5 cases) | - |
| BT-REQ-1657 | Any `url`, `href` or `image_url` inside a display object must parse as an https URL with a hostname and no embedded credentials. | IMPLEMENTED-UNTESTED | `sdks/web/src/displayObjectValidation.ts:279` `return parsed.protocol === "https:" && Boolean(parsed.hostname)` | - |
| BT-REQ-1658 | A display-object envelope is refused beyond 65,536 encoded bytes, depth 6, 100 array items, 64 object keys or 32,768-character strings. | IMPLEMENTED-UNTESTED | `sdks/web/src/displayObjectValidation.ts:33` `const MAX_BYTES = 65_536;` | - |
| BT-REQ-1659 | `compileCapabilityForm` refuses 25 JSON Schema keywords, three reserved property names and any schema exceeding 100 fields or depth 5, returning a typed unavailable reason. | IMPLEMENTED | `sdks/web/tests/capability-invocation-contracts.test.ts:2` `"import { test } from"` (6 cases) | - |
| BT-REQ-1660 | Secret-shaped and open-map schema fields are refused with a stated reason rather than given an input seam. | IMPLEMENTED | `tests/security/test_invoke_finalization.py:132` `"secret-shaped fields require a purpose-built secure-input surface"` | SEC-WRK-28 |
| BT-REQ-1661 | A capability output with no closed schema is hidden with an explicit reason rather than rendered generically. | IMPLEMENTED-UNTESTED | `sdks/web/src/capabilityInvocation.ts:658` `"has no closed output schema, so its payload"` | - |
| BT-REQ-1662 | A registry-supplied `pattern` is compiled to a browser `RegExp` and executed against user input with no complexity or length bound. | IMPLEMENTED-UNTESTED | `sdks/web/src/capabilityInvocation.ts:460` `!new RegExp(field.pattern).test(value)` | - |
| BT-REQ-1663 | `sanitizeFamiliarState` bounds every field independently, clamps non-finite numbers, maps unknown enum values to the calm default, and returns null only on a wrong envelope or a stale sequence. | IMPLEMENTED | `sdks/web/tests/familiar-state-contracts.test.ts:2` `"import { test } from"` (4 cases) | - |
| BT-REQ-1664 | The Familiar v2 renderer state carries nine phenotype scalars while the phenotype response type names ten, so `attachment` does not reach a renderer. | IMPLEMENTED-UNTESTED | `sdks/web/src/familiarState.ts:38` `"The ten server phenotype scalars"` | - |
| BT-REQ-1665 | `registerCharacter` validates the id grammar, the name, the blurb, the phenotype flag, the render function and every voice id, and refuses a duplicate id or a case-folded duplicate name. | IMPLEMENTED | `sdks/web/tests/character-contracts.test.ts:2` `"import { test } from"` (4 cases) | - |
| BT-REQ-1666 | A registered character is stored frozen, so a JavaScript add-in cannot mutate its id, name or render after validation. | IMPLEMENTED-UNTESTED | `sdks/web/src/characters.ts:270` `const registered = Object.freeze({` | - |
| BT-REQ-1667 | A throwing registry listener does not fail the registration that already committed. | IMPLEMENTED-UNTESTED | `sdks/web/src/characters.ts:281` `for (const listener of LISTENERS) {` | - |
| BT-REQ-1668 | The character registry is a module-level mutable singleton, so two module instances produce two independent registries. | IMPLEMENTED-UNTESTED | `sdks/web/src/characters.ts:200` `const REGISTRY = new Map<string, Character<never>>();` | - |
| BT-REQ-1669 | A character bundle carries no executable code: every field of the manifest is JSON. | IMPLEMENTED-UNTESTED | `sdks/web/src/characterBundle.ts:9` `"A BUNDLE CARRIES NO EXECUTABLE CODE."` | - |
| BT-REQ-1670 | A bundle asset path that is absolute or contains a `..` segment is refused rather than normalised, for the visual assets `assetRef` guards. | IMPLEMENTED-UNTESTED | `sdks/web/src/characterBundle.ts:192` `"is a refusal rather than something to"` | - |
| BT-REQ-1671 | `parseCharacterBundle` validates nine manifest fields and passes the remaining eight plus any unknown key through unchecked via the object spread. | IMPLEMENTED-UNTESTED | `sdks/web/src/characterBundle.ts:355` `"...manifest,"` | - |
| BT-REQ-1672 | `exportCharacterBundle` carries only the seventeen allow-listed fields out of an install, and a bundle's own `travels:false` outranks the caller's consent to export derived state. | IMPLEMENTED-UNTESTED | `sdks/web/src/characterBundle.ts:472` `const EXPORTABLE_BUNDLE_FIELDS = [` | - |
| BT-REQ-1673 | The enrolled face never travels in a bundle: it has no field in the manifest schema at all, so the exclusion is structural rather than a filtering step. | IMPLEMENTED-UNTESTED | `sdks/web/src/characterBundle.ts:479` `"THE ENROLLED FACE IS KERNEL DATA AND NEVER TRAVELS."` | - |
| BT-REQ-1674 | `bundleVoiceId` returns undefined when a bundle names no voice for a provider, and callers must not substitute another character's voice. | IMPLEMENTED-UNTESTED | `sdks/web/src/characterBundle.ts:393` `"never another character's voice"` | - |
| BT-REQ-1675 | `WORKER_INTEGRATION_CATALOGUE` is frozen presentation metadata whose every entry begins `uncertified`, and it is never a connection registry. | IMPLEMENTED | `sdks/web/tests/worker-contracts.test.ts:11` `"the reviewed Worker catalogue has forty explicit, uncertified entries"` | - |
| BT-REQ-1676 | The web SDK's source tree is compiled directly into the Worker through a `file:` dependency, a tsconfig path and two Vite aliases, all pointing at `src` rather than `dist`. | IMPLEMENTED-UNTESTED | `apps/worker/tsconfig.json:22` `["../../sdks/web/src/index.ts"]` | - |
| BT-REQ-1677 | The Worker image copies `sdks/web/src` into its build context rather than installing a published tarball. | IMPLEMENTED-UNTESTED | `apps/worker/Dockerfile:15` `COPY sdks/web/src ./sdks/web/src` | - |
| BT-REQ-1678 | 164 Worker source files import the SDK, so an SDK source edit changes the Worker's typecheck, both its bundles and its image with no version bump. | IMPLEMENTED-UNTESTED | `apps/worker/package.json:24` `"file:../../sdks/web"` | - |
| BT-REQ-1679 | `make worker-quality` typechecks and bundles the web SDK source, which is the only automated check either SDK package receives. | IMPLEMENTED-UNTESTED | `Makefile:241` `worker-quality: worker-structure` | - |
| BT-REQ-1680 | No Makefile target and no CI workflow runs either SDK package's own test suite. | IMPLEMENTED-UNTESTED | `Makefile:446` `-a -f sdks/node/pnpm-lock.yaml` | - |
| BT-REQ-1681 | `sdks/web/src` is outside every structural ratchet: the Worker's 400-line file ceiling scans only `apps/worker/src`. | IMPLEMENTED-UNTESTED | `apps/worker/scripts/check-structure.mjs:21` `const SOURCE_ROOT = "apps/worker/src";` | - |
| BT-REQ-1682 | A third party embeds Boltrig by serving the Worker at a same-origin subpath behind a stripping proxy and framing it, not by using the web SDK. | IMPLEMENTED-UNTESTED | `docs/decisions/0030-agents-tab-built-on-web-sdk.md:52` `"sanctioned mechanism is the subpath mount this decision"` | SEC-WRK-05 |
| BT-REQ-1683 | The Worker derives its API base from the document pathname when no absolute base is baked in, so a mounted console routes every `/v1` call back through the mount. | IMPLEMENTED-UNTESTED | `apps/worker/src/apiOrigin.ts:27` `export function mountPrefix(): string {` | - |
| BT-REQ-1684 | The UI-serving layers permit same-origin framing only: `X-Frame-Options: SAMEORIGIN` and `frame-ancestors 'self'`, on both the nginx image and the production Caddy edge. | IMPLEMENTED | `apps/worker/nginx.conf:24` `add_header X-Frame-Options "SAMEORIGIN" always;` | SEC-WRK-05 |
| BT-REQ-1685 | An embedding host passes `?theme=light&embed=1` per page load, and neither value touches local storage or kernel settings. | IMPLEMENTED-UNTESTED | `apps/worker/src/theme.ts:53` `"per-load, never persisted"` | - |
| BT-REQ-1686 | The embed contract lives entirely in `apps/worker` and is exported by neither SDK. | IMPLEMENTED-UNTESTED | `apps/worker/src/theme.ts:73` `"opened with `?embed=1`"` | - |
| BT-REQ-1687 | The marketing site is a Next 16 static export served as files, with no Node runtime in production and no `headers()` configuration. | IMPLEMENTED-UNTESTED | `site/next.config.ts:7` `output: "export",` | - |
| BT-REQ-1688 | The marketing site consumes neither SDK: it declares no Boltrig dependency and imports none. | IMPLEMENTED-UNTESTED | `site/package.json:15` `"dependencies"` | - |
| BT-REQ-1689 | The site's `/console` page calls the kernel's `/v1/console/overview` and `/v1/hitl/{id}/respond` with hand-rolled fetches against an operator-supplied base. | IMPLEMENTED | `site/src/views/console/client.test.ts:14` `"joins API base and clamps the limit"` | - |
| BT-REQ-1690 | The site console never persists a bearer token: it stores only the API base and actively removes any stored token key. | IMPLEMENTED | `site/src/views/console/client.test.ts:26` `"persists the API base but never stores bearer tokens"` | - |
| BT-REQ-1691 | The site carries its own narrower copy of the console response contract with no drift guard against the SDK's. | IMPLEMENTED-UNTESTED | `site/src/views/console/types.ts:62` `export type ConsoleOverview = {` | - |
| BT-REQ-1692 | The site's `NEXT_PUBLIC_BOLTRIG_API_BASE` bypasses the validated environment schema and is documented nowhere. | IMPLEMENTED-UNTESTED | `site/src/views/console/client.ts:31` `process.env.NEXT_PUBLIC_BOLTRIG_API_BASE ?? ""` | - |
| BT-REQ-1693 | `site/src/lib/api-client.ts` and `site/src/lib/api/index.ts` are unreachable: static export forbids route handlers and nothing imports either module. | DEAD | `site/src/lib/api/index.ts:37` `export function handle<C extends RouteContext` | - |
| BT-REQ-1694 | The site's coverage thresholds are 1 to 2 percent, recorded deliberately as the true figures rather than a number picked to pass. | IMPLEMENTED | `site/vitest.config.ts:38` `lines: 1,` | - |
| BT-REQ-1695 | The site's strict lint cannot enforce its own stated no-`any` rule, because the config disables `@typescript-eslint/no-explicit-any`. | IMPLEMENTED-UNTESTED | `site/eslint.config.mjs:18` `"@typescript-eslint/no-explicit-any"` | - |
| BT-REQ-1696 | The site's product claims are pinned only by a six-group, five-item shape check and a four-phrase blocklist, and are outside the repository's Tier-0 claim inventory. | IMPLEMENTED | `site/src/data/features.test.ts:26` `"does not advertise known seams as active product behaviour"` | - |
| BT-REQ-1697 | The marketing site is delivered to `/srv/boltrig-marketing` by a host Caddy that is not in this repository, and no repository script performs the copy. | SEAM | `docs/DEPLOYMENT.md:96` `"the marketing site from `/srv/boltrig-marketing`"` | - |
| BT-REQ-1698 | Neither SDK carries a changelog, a semver policy or a deprecation process, so no stability promise is recorded in the tree. | IMPLEMENTED-UNTESTED | `sdks/web/PUBLISHING.md:77` `"Release receipt (VJS-ACT 6 s6)"` | - |
| BT-REQ-1699 | `docs/SDK-CONTRACT-from-opbox.md` remains the design brief for both SDKs and is stale on three counts: the `ui/` reference tree, the G1 and G2 gaps, and the G5 resume cursor. | IMPLEMENTED-UNTESTED | `docs/SDK-CONTRACT-from-opbox.md:496` `"G1. Per-user bearer never reaches the verb handler."` | - |
