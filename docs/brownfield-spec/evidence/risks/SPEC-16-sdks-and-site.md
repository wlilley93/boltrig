# Risks harvested from SPEC-16-sdks-and-site.md

RISK: Both SDK packages ship complete test suites (38 and 78 cases) that no
Makefile target and no CI workflow ever runs; the only mention of `sdks` in
either is an existence check on one lockfile.
[`Makefile:446`](../../../Makefile)
`"@test -f apps/worker/pnpm-lock.yaml -a -f site/pnpm-lock.yaml -a -f sdks/node/pnpm-lock.yaml"`
(bounded: `rg -n "sdks" Makefile .github/`, 2026-08-24, pinned tree).

---

RISK: The Node SDK's `VerbError` status vocabulary is inert. It can emit
`_boltrig.status: "denied"`, but the consumer maps every `isError` result to
`ErrorClass.INVALID` and never reads `_boltrig.status`, and `ErrorClass` has no
`DENIED` member, so the distinction the SDK documents reaches no kernel
decision. [`boltrig/adapters/mcp_consumer.py:272`](../../../boltrig/adapters/mcp_consumer.py) `if result.get("isError"):` and
[`boltrig/adapters/base.py:52`](../../../boltrig/adapters/base.py) `NOT_FOUND = "not_found"`.

---

RISK: `VerbDef` has no `outputSchema` field and `tools/list` emits none, so
every verb published through the Node SDK renders its output as permanently
unavailable in the Worker's capability runner.
[`sdks/node/src/server.ts:290`](../../../sdks/node/src/server.ts) `"inputSchema: v.schema,"` against
[`sdks/web/src/capabilityInvocation.ts:658`](../../../sdks/web/src/capabilityInvocation.ts) `"has no closed output schema, so its payload"`

---

RISK: The kernel emits a replay `message_start` carrying no `run_id`, which the
SDK's own type declares as required and non-optional, and neither replay frame
declares the `replay: true` flag `docs/addons.md` promises consumers will see.
[`boltrig/fleet/chat_idempotency.py:120`](../../../boltrig/fleet/chat_idempotency.py) `{"type": "message_start", "conversation_id": conversation_id, "replay": True},`
against [`sdks/web/src/types.ts:820`](../../../sdks/web/src/types.ts) `"export interface ChatMessageStart {"` (bounded: `rg -n "replay" sdks/web/src/types.ts`,
2026-08-24, three hits, none of them a chat-event field).

---

RISK: The web SDK's SSE pump parses every frame with an unguarded `JSON.parse`,
so one malformed frame throws out of the pump and terminates the whole stream,
while the Node SDK's parser for the same wire format deliberately drops it.
[`sdks/web/src/client.ts:2654`](../../../sdks/web/src/client.ts) `"onFrame(JSON.parse(data) as T);"` against
[`sdks/node/src/head.ts:44`](../../../sdks/node/src/head.ts) `"try {"` returning null.

---

RISK: `buildCapabilityParams` compiles a registry-supplied `pattern` into a
`RegExp` and runs it against user input with no complexity or length bound,
which is the exact ReDoS shape the sibling Node SDK removed a regex to avoid
because it is "a PUBLISHED SDK".
[`sdks/web/src/capabilityInvocation.ts:460`](../../../sdks/web/src/capabilityInvocation.ts) `"!new RegExp(field.pattern).test(value)"` against
[`sdks/node/src/http.ts:58`](../../../sdks/node/src/http.ts) `"NO REGEX, deliberately."`

---

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

---

RISK: `FamiliarPhenotypeScalar` documents ten server scalars including
`attachment`, but `FamiliarPhenotypeV2` and `sanitizeFamiliarState` carry only
nine, so `attachment` is dropped between the phenotype response and the
renderer state contract.
[`sdks/web/src/familiarState.ts:38`](../../../sdks/web/src/familiarState.ts) `"The ten server phenotype scalars"` against
[`:50`](../../../sdks/web/src/familiarState.ts) `"export interface FamiliarPhenotypeV2 {"`.

---

RISK: The marketing site ships an authenticated operations console at
`/console` that accepts a pasted bearer and posts it to an operator-supplied
cross-origin API base, on a statically exported site with no in-repo CSP, no
`headers()` configuration, and a `robots.txt` that allows all crawlers on `/`.
[`site/src/views/console/client.ts:20`](../../../site/src/views/console/client.ts) `"const token = settings.bearerToken.trim();"`,
[`site/next.config.ts:7`](../../../site/next.config.ts) `output: "export",`,
[`site/src/app/robots.ts:15`](../../../site/src/app/robots.ts) `allow: "/",`.

---

RISK: The site's console re-implements two kernel endpoints the SDK already
covers and carries its own narrower copy of the response types, with no drift
guard of any kind.
[`site/src/views/console/client.ts:6`](../../../site/src/views/console/client.ts) `"export function overviewUrl(apiBase: string, limit = 50)"` against
[`sdks/web/src/client.ts:971`](../../../sdks/web/src/client.ts) `"consoleOverview(limit = 20)"` and
[`sdks/web/src/client.ts:1375`](../../../sdks/web/src/client.ts) `"respondHitl(id: string, decision: string"`.

---

RISK: `site/eslint.config.mjs` disables eight rules including
`@typescript-eslint/no-explicit-any` and `no-unused-vars`, while the site's own
agent guide states rule 7 as "No `any`. Type everything. Run
`pnpm run lint:strict` before finishing" and `make site-quality` runs exactly
that command; `site/src` contains eight `any` usages that the strict lint
cannot see. [`site/eslint.config.mjs:18`](../../../site/eslint.config.mjs) `"\"@typescript-eslint/no-explicit-any\": \"off\","` against
[`site/AGENTS.md:37`](../../../site/AGENTS.md) `"7. **No `any`.** Type everything."` (bounded:
`rg -n ": any\b|<any>|as any" site/src`, 2026-08-24, eight hits).

---

RISK: `site/src/lib/api-client.ts` and `site/src/lib/api/index.ts` are
unreachable dead code: `output: "export"` forbids route handlers, there is no
`site/src/app/api` directory, and no file imports `apiFetch`, `ApiClientError`,
`handle` or `getServerEnv`.
[`site/src/lib/api/index.ts:37`](../../../site/src/lib/api/index.ts) `"export function handle<C extends RouteContext = RouteContext>("` (bounded:
`rg -n "apiFetch|ApiClientError|from \"@/lib/api\"|getServerEnv" site/src`,
2026-08-24: only their own definitions).

---

RISK: `site/README.md`, `site/AGENTS.md` and `site/HOW_TO_USE.md` are the
unmodified third-party starter's documents, describing a
"next16-claude-starter" and a "Neural Monitor" template rather than Boltrig's
site, and `HOW_TO_USE.md` prescribes `pnpm run start` on a project configured
for static export with no Node runtime in production.
[`site/README.md:1`](../../../site/README.md) `# next16-claude-starter`,
[`site/HOW_TO_USE.md:3`](../../../site/HOW_TO_USE.md) `"the complete source for the **Neural Monitor** project"`,
[`site/next.config.ts:5`](../../../site/next.config.ts) `"(no Node runtime on prod)"`.

---

RISK: `docs/SDK-CONTRACT-from-opbox.md` cites `ui/src/api/*` as the reference
implementation to extract, but no `ui/` directory exists in the pinned tree,
and it lists G1 and G2 as open gaps that shipped (`resolveIdentity` and
`onBehalfBearer` both exist with tests) and G5 as open when
`followConversation(since)` closed it.
[`docs/SDK-CONTRACT-from-opbox.md:496`](../../../docs/SDK-CONTRACT-from-opbox.md) `"G1. Per-user bearer never reaches the verb handler."` (bounded: `ls -d ui`
returns "No such file or directory", 2026-08-24, pinned tree).

---

RISK: `sdks/web/PUBLISHING.md` asserts a green drift guard at
`tests/drift.test.ts`, which does not exist anywhere in the tree, and logs a
release receipt for version `0.1.0` while `package.json` reads `0.2.0` with no
changelog to bridge them.
[`sdks/web/PUBLISHING.md:30`](../../../sdks/web/PUBLISHING.md) `"drift guard is green (`tests/drift.test.ts`)"` (bounded:
`find . -name "drift.test.ts" -not -path "./node_modules/*"`, 2026-08-24: no
result).

---

RISK: `sdks/node/README.md` still states the pre-2026-08-16 consequence rule,
"a tool's declared `consequence` hint propagates (capped at `\"high\"`, default
`\"low\"`)", which the kernel policy and the SDK's own source comment both
contradict. [`sdks/node/README.md:173`](../../../sdks/node/README.md) `"hint propagates (capped at"` against
[`sdks/node/src/server.ts:95`](../../../sdks/node/src/server.ts) `"since 2026-08-16 it fails CLOSED"`.

---

RISK: `sdks/node/src/server.ts`'s module docstring tells a reader the kernel
sends "no `initialize` handshake, no SSE, no session headers", which the
transport contradicts on all three counts (lazy handshake on 400/404,
`Accept: text/event-stream`, `Mcp-Session-Id` carried); the README in the same
package is correct and the docstring is not.
[`sdks/node/src/server.ts:8`](../../../sdks/node/src/server.ts) `"handshake, no SSE, no session headers"` against
[`boltrig/adapters/mcp_transport.py:12`](../../../boltrig/adapters/mcp_transport.py) `"The handshake is LAZY: the plain call goes out first."`

---

RISK: `sdks/web/src` is exempt from every structural ratchet in the repository.
The Worker's structure gate scans only `apps/worker/src` with a 400-line file
ceiling, while `types.ts` is 4459 lines and `client.ts` is 2661.
[`apps/worker/scripts/check-structure.mjs:21`](../../../apps/worker/scripts/check-structure.mjs) `const SOURCE_ROOT = "apps/worker/src";` and
[`:26`](../../../apps/worker/scripts/check-structure.mjs) `max_file_lines: 400,`.

---

RISK: Marketing copy is outside the Tier-0 claim ratchet. `build_claim_inventory.py`
scans only the `boltrig` package and compose files, so
`site/src/data/features.ts` (30 product claims) is checked by nothing but a
four-phrase substring blocklist in its own unit test.
[`scripts/build_claim_inventory.py:281`](../../../scripts/build_claim_inventory.py) `pkg = ROOT / "boltrig"` (bounded: `grep -c "site/" docs/claim-inventory.tsv`
returns 0, 2026-08-24).

---

RISK: Three site call-to-action links address `access@boltrig.io`, a mailbox on
the domain `docs/DEPLOYMENT.md` records as 301-redirected to `boltrig.ai` since
2026-08-18. [`site/src/components/common/site-header.tsx:47`](../../../site/src/components/common/site-header.tsx) `href="mailto:access@boltrig.io?subject=Boltrig%20access%20request"` against
[`docs/DEPLOYMENT.md:99`](../../../docs/DEPLOYMENT.md) `"301 to `https://boltrig.ai{uri}`"`.

---

RISK: The web SDK's character registry is a module-level mutable singleton in a
package the Worker resolves from source through two Vite aliases and one
tsconfig path; any consumer that reaches the package by a different resolution
(a subpath export, a `dist` install alongside the source alias) gets a second,
independent registry with no diagnostic.
[`sdks/web/src/characters.ts:200`](../../../sdks/web/src/characters.ts) `const REGISTRY = new Map<string, Character<never>>();` and
[`sdks/web/package.json:55`](../../../sdks/web/package.json) `"./characters": {`.

---

RISK: Two accepted decisions share the number 0030
(`0030-agents-tab-built-on-web-sdk.md` and `0030-familiar-modes-and-dials.md`),
so a citation to "decision 0030" is ambiguous.
[`docs/decisions/0030-agents-tab-built-on-web-sdk.md:1`](../../../docs/decisions/0030-agents-tab-built-on-web-sdk.md) `"# 0030 - Agents tab is built on the web SDK"`.

---
