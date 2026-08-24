# Index of the Boltrig brownfield specification

Twenty areas, one file each, all written against commit `19bcae7f`. Start with
`BIBLE.md` if you do not already know which area you need.

| # | area | spec | lines | reqs |
| --- | --- | --- | --- | --- |
| 01 | The kernel dispatch chokepoint | [`SPEC-01-kernel-dispatch.md`](specs/SPEC-01-kernel-dispatch.md) | 1373 | 100 |
| 02 | The kernel HTTP surface | [`SPEC-02-kernel-http-surface.md`](specs/SPEC-02-kernel-http-surface.md) | 1544 | 96 |
| 03 | The permanent fleet: hierarchy, spawn, budget | [`SPEC-03-fleet-core.md`](specs/SPEC-03-fleet-core.md) | 1350 | 100 |
| 04 | The runtime protocol and the Codex lane | [`SPEC-04-fleet-runtime-codex.md`](specs/SPEC-04-fleet-runtime-codex.md) | 1052 | 100 |
| 05 | Persistence: the store layer and the migration ledger | [`SPEC-05-store-persistence.md`](specs/SPEC-05-store-persistence.md) | 1290 | 89 |
| 06 | Adapters, egress policy, and MCP consumption | [`SPEC-06-adapters-mcp.md`](specs/SPEC-06-adapters-mcp.md) | 1169 | 100 |
| 07 | Identity, authentication, seats and capabilities | [`SPEC-07-identity-auth-capabilities.md`](specs/SPEC-07-identity-auth-capabilities.md) | 1373 | 100 |
| 08 | Memory planes, the Knowledge extension, and distillation | [`SPEC-08-memory-knowledge-distill.md`](specs/SPEC-08-memory-knowledge-distill.md) | 1411 | 100 |
| 09 | Workflows, work items, skills and the YAML libraries | [`SPEC-09-workflows-work-skills.md`](specs/SPEC-09-workflows-work-skills.md) | 1405 | 100 |
| 10 | Model catalogue, routing, and the sensitive-to-local rule | [`SPEC-10-models-routing.md`](specs/SPEC-10-models-routing.md) | 1043 | 100 |
| 11 | Configuration: the manifest, the environment, and release mode | [`SPEC-11-config-manifest.md`](specs/SPEC-11-config-manifest.md) | 1083 | 63 |
| 12 | Observability, readiness, doctor and log safety | [`SPEC-12-observability-doctor.md`](specs/SPEC-12-observability-doctor.md) | 1381 | 100 |
| 13 | Process composition, bootstrap and the CLI surfaces | [`SPEC-13-api-composition-bootstrap.md`](specs/SPEC-13-api-composition-bootstrap.md) | 1274 | 88 |
| 14 | Presence, devices, camera, emotion and the Familiar | [`SPEC-14-presence-camera-familiar.md`](specs/SPEC-14-presence-camera-familiar.md) | 1489 | 100 |
| 15 | The worker UI: the primary surface | [`SPEC-15-worker-ui.md`](specs/SPEC-15-worker-ui.md) | 1019 | 63 |
| 16 | The SDKs and the marketing site | [`SPEC-16-sdks-and-site.md`](specs/SPEC-16-sdks-and-site.md) | 1199 | 100 |
| 17 | The channel gateway, messaging bridges and calls | [`SPEC-17-channels-and-calls.md`](specs/SPEC-17-channels-and-calls.md) | 1241 | 100 |
| 18 | The iOS companion application | [`SPEC-18-ios-app.md`](specs/SPEC-18-ios-app.md) | 1490 | 199 |
| 19 | Deployment topology, the release train and recovery | [`SPEC-19-deploy-and-release.md`](specs/SPEC-19-deploy-and-release.md) | 1130 | 100 |
| 20 | Governance: invariants, gates, decisions and the court | [`SPEC-20-governance-and-gates.md`](specs/SPEC-20-governance-and-gates.md) | 1131 | 100 |

Totals: 25447 lines, 1998 requirement rows.

## What each area is

**01 The kernel dispatch chokepoint**  
The single ordered function every external Boltrig action passes through: it
resolves a verb to one binding (or collapses many capability bindings to one
execution plan), runs grant, schema, idempotency, human-approval, throttle and
in-kernel credential gates in a fixed order, executes exactly one adapter or
agent, and writes one hash-chained audit row whatever the outcome.

**02 The kernel HTTP surface**  
The kernel's single FastAPI front door: 294 routes plus a five-layer edge-
hardening middleware stack that authenticate a caller into a Principal and
hand typed requests to the kernel, the fleet or the store, with 93 of its 161
state-changing routes going through the dispatcher and 68 going around it.

**03 The permanent fleet: hierarchy, spawn, budget**  
The fleet core is the durable flat roster of tier-1 named peers plus the
ephemeral spawn path that composes skills, picks the cheapest capable runtime,
reserves budget before anything runs, fans out under atomic per-tree caps, and
walks each work item to a terminal state under a claim-time lease fence.

**04 The runtime protocol and the Codex lane**  
The vendor-neutral runtime seam and the supervised Codex lane: two disjoint
contracts (one-shot Runtime, bounded-phase AgentRuntime), exactly one model-
backed implementation (trusted Codex behind a dev-only posture wall, a digest-
pinned 0.144.3 binary, a read-only sandboxed cell and a per-cell model proxy),
a deterministic ScriptRuntime, and a typed unavailable result for every
retired runtime name.

**05 Persistence: the store layer and the migration ledger**  
One `Store` Protocol assembled from 23 contract fragments, satisfied method-
for-method by an in-process dictionary store and an asyncpg PostgreSQL store
over a 138-table catalogue, fenced by an opt-in FORCE-RLS overlay, sealed at
the credential seam, and moved forward only by an 88-revision Alembic ledger
whose head is `0086_conversation_addressing`.

**06 Adapters, egress policy, and MCP consumption**  
The single adapter Protocol plus its two runtime bases, the shared SSRF/DNS-
pinning egress guard, the deterministic OpenAPI adapter generator, the live-
instance loader, and the external-MCP consumer family: the one layer through
which Boltrig touches anything outside itself, publishing every integration's
capabilities as data so the kernel registers new verbs without a kernel code
change.

**07 Identity, authentication, seats and capabilities**  
The layer that turns a bearer, cookie or edge assertion into a Principal
carrying a GrantSet, narrows that authority by org, workspace and role, and
owns every first-party credential lifecycle (invite, password, TOTP, recovery,
session, personal access token) plus the per-scope AI-provider and per-user
integration credentials the kernel later spends.

**08 Memory planes, the Knowledge extension, and distillation**  
Boltrig's durable knowing: a governed memory ledger with three writable typed
planes behind a deterministic write gate, a canonical Knowledge catalogue
pairing an immutable ObjectVault with a Postgres/pgvector citation index, and
a sleep-distillation loop that turns the governed record into a LoRA candidate
no mechanical gate will promote unearned.

**09 Workflows, work items, skills and the YAML libraries**  
The data plane for behaviour: a JSON DAG interpreter that walks a stored
workflow's steps and dispatches every one through the kernel chokepoint, plus
the skill library (prompt fragment, requested grants, context schema), the
work-item normaliser, and the on-disk YAML libraries and versioned external
schemas those three read.

**10 Model catalogue, routing, and the sensitive-to-local rule**  
The tenant-scoped model endpoint catalogue plus the router that decides which
endpoint a call may reach, enforcing the sensitive-to-local residency rule as
an audited refusal rather than a fallback, with Bifrost as an optional
standard-traffic gateway and a per-model price table feeding cost accounting.

**11 Configuration: the manifest, the environment, and release mode**  
The configuration subsystem is the two-file seam that makes one image serve
many tenants: .env becomes a frozen per-process Settings, manifest.yaml
becomes a frozen per-tenant FleetManifest with ${ENV} interpolation that seeds
the store, and BOLTRIG_RELEASE_MODE fixes which of the two admitted release
postures the build and its readiness gates are held to.

**12 Observability, readiness, doctor and log safety**  
The subsystem that decides and publishes what Boltrig says about itself: one
hash-chained, secret-scrubbed audit log as the record of record, a log-
injection-safe logging layer, and three deliberately separate verdicts (static
doctor for configuration, cached /healthz for liveness, fail-closed /readyz
for whether the deployment can actually serve), plus bounded content-free
projections that name in their own fields exactly how little they prove.

**13 Process composition, bootstrap and the CLI surfaces**  
The composition root: the four shipped entrypoints (ASGI app, fleet worker,
Hatchet worker, boltrig CLI), the single-provider single-snapshot rule that
binds every spawner a process owns, the HITL answer bridge that replays a
durably recorded held write, and the shell-level audit-chain verifier.

**14 Presence, devices, camera, emotion and the Familiar**  
The signed-lease plane by which a cloud kernel acts on an enrolled desktop's
files, shell and USB camera without holding a socket into it, the consent
surface that decides whether anything watches at all, and the Familiar body
that renders the machine's measured mood while being structurally unable to
influence any decision it makes.

**15 The worker UI: the primary surface**  
The Worker is Boltrig's only first-party browser surface and the Tauri desktop
payload: a React 19 hash-routed SPA over sixteen routes that renders
conversations, live SSE turns, approvals, artifacts and every governed control
plane, holding no authority of its own and reaching the kernel only through
the typed web SDK plus one WebSocket for live voice.

**16 The SDKs and the marketing site**  
Boltrig's two public client libraries plus its marketing site: `sdks/node` is
the backend seam by which a third-party app publishes its verbs to a kernel as
a governed inert MCP adapter, `sdks/web` is the typed `/v1` client and the
shared `ChatEvent` frame union plus turn reducer that is compiled into the
Worker directly from source, and `site/` is a statically exported Next.js site
at boltrig.ai that consumes neither.

**17 The channel gateway, messaging bridges and calls**  
Boltrig's one message edge: nine channel providers terminated in two transport
classes (webhook routes in-kernel, socket channels in a severed lease-owned
gateway daemon) that converge on a single signed intake where a verified
external sender becomes a grant-ceilinged Principal, plus the durable outbound
outbox, the notification round trip, and the realtime voice call surface built
on the same channel machinery.

**18 The iOS companion application**  
A native SwiftUI iPhone client, Familiar only, that signs one person in to one
Boltrig instance over a cookie ceremony, keeps a single 90-day personal access
token in the Keychain, and gives Today, a governed streaming Chat with
Familiar's WebGL presence and spoken replies, and Settings, entirely over the
existing /v1 HTTP surface with no local persistence and no offline mode.

**19 Deployment topology, the release train and recovery**  
The Compose service topology (fifteen services, three networks, eleven
volumes, one hardening anchor), the six overlays that specialise it, the tag-
to-running-stack release train with its four digest-pinned signed images, and
the backup, recovery-set verification and restore procedures that let a
deployment survive its disk.

**20 Governance: invariants, gates, decisions and the court**  
Boltrig's self-verification machinery: a 421-invariant catalogue at binding
debt zero, roughly two dozen gate scripts wired through four Makefile
aggregates into two required CI contexts, a filed court record of 24 binding
orders and 163 directives, and a decision record that is a filename convention
with no gate behind it.

