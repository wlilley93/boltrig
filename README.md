# Boltrig

[![GitHub repo](https://img.shields.io/badge/GitHub-wlilley93%2FBoltrig-181717?logo=github)](https://github.com/wlilley93/Boltrig)
[![CI](https://github.com/wlilley93/Boltrig/actions/workflows/ci.yml/badge.svg)](https://github.com/wlilley93/Boltrig/actions/workflows/ci.yml)

A self-hostable agent-orchestration platform: a thin, secure kernel and a
permanent agent fleet that spawns ephemeral workers to get work done. Boltrig is
a clean-room reference implementation of the "Hermes Fleet" SRS (the kernel
doctrine: one dispatch chokepoint, stable nouns and verbs, everything-as-data).

> **Runtime direction (2026-07-21):** Codex is the only target agent runtime
> under decision 0012. Its supervised proxy/event contract is wired, but the
> production cutover and Codex-native collaboration admission are not yet green.
> The executable blockers and closure order are recorded in
> `docs/CODEX-PRODUCTION-ADMISSION.md`.
> Pi, Hermes, OpenCode, and related paths remain staged rollback residue, not
> alternate product runtimes.

The kernel core is implemented and tested with the Python suite, opt-in Postgres
and live-adapter legs, and a machine-checked binding-invariant gate at debt 0.
Persistence (Postgres), real OIDC auth, sensitive->local model routing, and
durable HITL pauses are implemented and tested; the remaining external legs (a
live Hatchet engine, a live IdP, third-party adapter credentials, an on-box
model) are seams (see "Implemented vs scaffolded" below).

## The three defining characteristics

1. **A thin core.** The kernel implements policy nowhere itself. It composes a
   dispatcher, grant checker, rate limiter, credential resolver, audit writer,
   HITL gate, and cost accountant, and it loads everything else (adapters,
   skills, workflows, capabilities) as data (`boltrig/kernel/__init__.py`,
   `boltrig/kernel/dispatch.py`). Adding an integration changes no core code.
2. **A permanent fleet that spawns ephemerals.** A durable hierarchy (a tier1
   chief-of-staff over tier2 department heads) takes in work and spawns
   short-lived child agents to do it, picking the cheapest capable runtime,
   reserving budget first, and enforcing recursion depth
   (`boltrig/fleet/spawn.py`, `boltrig/fleet/runtime.py`).
3. **The kernel abstracts actions behind nouns and verbs.** Agents reason in
   stable nouns (`ticket`) and verbs (`ticket.create`); the kernel resolves each
   verb to a concrete adapter or agent via a binding. The agent never learns
   which concrete system sits behind a verb (`boltrig/kernel/registry.py`,
   `boltrig/models/registry.py`).

## Citable Knowledge for Codex

The first-party Knowledge extension stores canonical text, Markdown, and PDF
originals in a filesystem or S3-compatible ObjectVault, with identity,
revisions, source occurrences, permission scopes, passages, full-text search,
and pgvector embeddings in Postgres. Every result carries an immutable revision
and segment citation.

Cognee is bundled and enabled as a rebuildable knowledge compiler. If its model
configuration is absent or unhealthy, the canonical commit remains successful
and the provider reports degraded. Supermemory and Mem0 are disabled governed
catalogue add-ons; enabling them never changes canonical authority and they need
their credential-backed external connection before processing data.

Codex receives the read-only `knowledge/retrieval` skill plus granted
`knowledge.*` MCP tools and `boltrig://knowledge/assets/{id}` resources. MCP
resource list/read calls still invoke the registered verbs through the complete
dispatcher and audit path.

## Governance: the doctrine and the consolidation ruling

Boltrig implements, but does not author, a kernel doctrine. The **single source
of that doctrine (the K-1..K-30 invariant catalogue) is the `agent-kernel-doctrine`
repository.** Boltrig conforms to it; it never redefines or forks it. Any change to
the meaning of a `K-*` invariant originates there, and Boltrig tracks it.

Boltrig exists as its own repository by the ruling of the VJS County Court,
**[2026] VJS-CC NANKLE-CONSOLIDATION 001** ("conditioned standalone"). The court
held that the single-source-of-law precedents govern unity of *law*, not the
coexistence of conforming *code* implementations of one doctrine, and permitted
Boltrig to stand alone on binding conditions: it cites the doctrine as the single
source (above), keys its invariants to the doctrine's Appendix A, keeps the
binding-invariant gate at debt 0 in required CI, converges on (never competes
with) the doctrine's unified capability primitive, stays severable (the kernel
and models import nothing from sibling estate kernels), and forks no parallel
codebase of its own (the difference between installations is config, never a
forked Boltrig, per P7). Breach of any condition routes Boltrig to consolidation.
See `docs/decisions/0002-nankle-consolidation-ruling.md`.

## Round Two: conversation, Pi, MCP

Three additions sit on the same thin core (the dispatch sequence is unchanged):

- **MCP server face** (`boltrig/kernel/mcp.py`, `POST /v1/mcp`): granted verbs are
  advertised as MCP tools and adapter-declared resources over a run-scoped token;
  every call runs the full chokepoint. Any MCP-capable client can use the same
  governed surface without bespoke glue.
- **Codex is the one target agent runtime.** The Pi sidecar lane that used to sit
  here is RETIRED (`docs/decisions/0020-retire-the-pi-lane.md`, on the authority of
  [2026] VJS-PC 20 L1). The multi-runtime routing seam stays live and five
  non-Codex lanes remain re-wirable by configuration alone, which is the condition
  that grant carries. Production readiness still fails closed until the pinned
  Codex binary, identity/proxy, cancellation and acceptance gates pass; native
  Codex collaboration remains admission-disabled while its lifetime/depth/thread,
  effort, drain, bearer-revocation and durable-projection guarantees are completed.
- **Conversational layer** (`boltrig/fleet/chat.py`, `POST /v1/chat` + a fourth
  Chat panel): a turn routes through the fleet and streams reasoning/tool/
  sub-agent/inline-HITL events; conversations persist and are owner-scoped.

See `docs/DEFINITION-OF-DONE-round-two.md`.

## Quick start

### Run the tests + checks (no docker)

```bash
python -m venv .venv
.venv/bin/pip install -e ".[durable,inference,cognee]"
.venv/bin/pip install pytest pytest-asyncio aiosqlite ruff==0.15.20 \
  mypy==2.1.0 types-jsonschema==4.26.0.20260518

make check        # invariants, ruff, scoped mypy, pytest
make smoke        # offline, in-process demo of the kernel guarantees
make live-check   # opt-in live legs; requires real services/credentials
```

`make smoke` exercises the dispatch chokepoint end to end on an in-memory store:
a granted call, a denied call, a gated pause-then-approve, and a degraded call.
`make live-check` groups the tests that intentionally skip offline. Export the
service-specific inputs first, for example `HATCHET_CLIENT_TOKEN`, `DATABASE_URL`,
`BOLTRIG_TEST_DATABASE_URL`, `BOLTRIG_COGNEE_LIVE=1`, model credentials, and the
adapter credential env vars documented in `tests/adapters/test_live_smoke.py`.

### Run the stack (docker)

```bash
cp .env.example .env                 # then edit secrets
cp manifest.example.yaml manifest.yaml
make up                              # docker compose up -d --build
# on-box inference for sensitive data:
make up ARGS="--profile local"
```

The kernel API comes up on `:8000`, the console UI on `:8080`. The same images
run in every environment; only `.env` and `manifest.yaml` differ (P7).

### Bring your own model gateway

The published template contains no personal provider, model identity, API key,
webhook, or tenant data. Run/configure your own Bifrost instance, keep its
provider keys in Bifrost's secret/admin surface, then choose one of its
advertised text models in Worker **Settings → Models**. Boltrig receives only
the opaque, governed route and exact model name; provider keys never enter the
browser or the checked-in `.env.example`. The stock Stage ships with Familiar
and Jarvis only; additional companions are not part of the production bundle.

## Architecture

```
                          fleet manifest (manifest.yaml)        .env
                          who/auth/models/hierarchy/adapters     process wiring
                                       |                            |
   +---------+   HTTP    +-------------v----------------------------v----------+
   |   UI    |---------->|                    KERNEL                           |
   | Router  |  /v1/*    |  one dispatch chokepoint (P2), policy lives here:   |
   | Kanban  |<----------|  resolve -> validate -> grant -> idempotency       |
   |Approvals|  202/403  |  -> HITL -> rate-limit -> credential -> execute     |
   +---------+  503/200  |  -> validate output -> audit (always)               |
                         +---+----------------------+-----------------------+--+
                             | nouns/verbs/bindings | credential refs       |
            +----------------v---+        +---------v--------+      +--------v-------+
            |   ADAPTERS (data)  |        |  SECRET STORE    |      |  FLEET         |
            | ms-graph jira      |        | vault/kms/env    |      | tier1 + tier2  |
            | crm-sql memory     |        | (refs in DB only)|      | spawns         |
            +----------+---------+        +------------------+      | ephemerals     |
                       |                                            +-------+--------+
                       v                                                    |
            external systems                              durable runs (Hatchet, optional)
                                                                            |
   +------------------------- STORE (Postgres / in-memory) ------------------+
   | registry | work items | hitl | audit (hash-chained) | budgets | creds  |
   +------------------------------------------------------------------------+
```

Every external action funnels through one ordered path in
`boltrig/kernel/dispatch.py`, and every action writes exactly one append-only,
hash-chained audit row regardless of outcome. See `docs/ARCHITECTURE.md` for the
full component map, the dispatch contract, and where each principle (P1-P10) is
enforced.

## How "thinness" is preserved

Adding a new integration is data + libraries, never a core edit:

- a new **adapter** (`boltrig/adapters/builtin/<x>.py` or a generated/manual one)
  declares its verbs, schemas, and recommended rate limits via `describe()`;
- new **skills** and **workflows** are YAML in `libraries/`;
- the **manifest** wires them to the tenant (credentials as refs, the agent org
  chart, spawn rules, HITL policy, network/privacy posture).

The kernel registers an adapter's verbs as rows (`KernelRegistry`), resolves them
through bindings, and dispatches them through the same chokepoint. No file under
`boltrig/kernel/` changes to add Jira, Salesforce, or a new department.

## Implemented vs scaffolded (honesty section)

**Fully implemented and tested** (the load-bearing core):

- The dispatch chokepoint and its fixed order (`boltrig/kernel/dispatch.py`):
  resolve, schema-validate, grant-check, idempotency replay, HITL gate, rate-limit,
  in-kernel credential resolution, execute, output-validate, audit.
- Grant semantics (deny-dominant, fail-closed, wildcard rules), the tenant
  ceiling intersection, tenant isolation, the HITL approval gate, the
  tamper-evident hash-chained audit, PII redaction, secret scrubbing, budget
  hard-stops, rate limiting, and graceful degradation. These are pinned by the
  binding-invariant catalogue (`docs/invariants.md`, `tests/invariants.yaml`)
  and the gate at `scripts/check_invariants.py`.
- Both Store implementations (in-memory + **Postgres**, `boltrig/store/postgres.py`),
  the registry, the fleet spawner (skill inheritance, cheapest-runtime selection,
  depth + budget), the manifest loader/applier, and the kernel HTTP surface.
- **Real OIDC token verification** (`boltrig/identity/auth.py`, RS256 against the
  issuer JWKS), with bootstrap selecting it when `OIDC_*` is set and failing
  closed otherwise; the header resolver only with `BOLTRIG_DEV_AUTH=1`.
- **Sensitive->local model routing guard** (`fleet/model_router.py`): sensitive
  data is blocked from non-local endpoints and the misroute is audited (SEC-12).
- **Durable HITL pause** (NFR-REL-01): a blocking pause survives a restart and
  resumes on approval over Postgres.
- **Knowledge first slice**: bounded text/Markdown/PDF upload, filesystem and
  S3-compatible ObjectVault implementations, Postgres/pgvector catalogue and
  search, source/embedding provenance, stable citations, governed HTTP/MCP
  tools and resources, Codex skill, provider catalogue, UI, and reference-safe
  erasure.

**Real, but with external seams** (the code is here; the live leg needs its
service or credentials to exercise):

- **Full live-Hatchet run-resume.** The durable HITL pause is done and tested; the
  full long/recursive run-resume needs a running Hatchet engine (the
  `hatchet-engine` service + `[durable]` extra). Without it the fleet still runs
  and degrades (P9); the local executor is the offline fallback.
- **Worker primary surface.** The task-first Worker client and reversible signed
  release overlay are implemented, with the canonical coverage ledger in
  `docs/WORKER-PARITY.md`. Production-primary status still depends on Codex,
  connector, voice, desktop-action and staging acceptance.
- **Desktop device actions.** Owner enrollment, opaque roots, stable Ed25519
  verifier bootstrap, exact-action leases, atomic claim/settlement, revocation,
  Postgres/RLS and provisioning are implemented and tested. Ordinary dispatcher
  bindings plus the Tauri verifier/executor and staging run remain the
  end-to-end leg.
- **Realtime voice.** Governed calls, HITL hold/resume, channel-gateway media,
  transcript/events and usage receipts are implemented; credentialed xAI,
  multi-call and Tauri staging remain.
- **Live IdP.** OIDC verification is implemented and tested against minted tokens;
  pointing it at a real Azure AD / Okta / Google issuer is the remaining leg.
- **Live MS Graph / Jira / CRM adapters.** The builtin adapters are real HTTP/SQL
  clients but need credentials and reachable backends (opt-in `make live-check`).
  The `memory-tickets` adapter is fully self-contained.
- **On-box model (local inference).** The `local-model` compose profile runs a
  local OpenAI-compatible endpoint for sensitive data; it needs a model + (for
  vLLM) a GPU, or swap in Ollama for CPU. (The routing guard that *requires* it
  for sensitive data is done.)
- **Sleep distillation** (decision 0023, DIS-1..8). The governed loop is
  implemented and tested: erasure-filtered digest-pinned corpus derivation,
  the five `distill.*` verbs, mechanical craft/register gates, audit-receipt
  promotion with same-act pricing, and the native trainer/scorer sidecar
  (`services/distill_sidecar/`, exercised end-to-end against mlx-lm on a toy
  corpus). The remaining legs: a production-scale corpus over live Postgres
  history, a department eval-case library for the craft gate, serving a
  promoted adapter through the Codex composition's sensitive role, and the
  scheduled nightly itself (a runbook act -
  `docs/proposals/sleep-distillation.md`).
- **Cognee model configuration.** Cognee ships in the first-party image and is
  enabled as a Knowledge compiler, but compilation reports degraded until an
  approved LLM and embedding configuration is available. Canonical Knowledge
  does not depend on that live leg.
- **Schema management.** `schema.sql` remains the idempotent first-boot schema for
  fresh stacks; the ordered Alembic set under `migrations/versions/` carries
  production upgrades through `make migrate`.

## Layout

```
boltrig/        kernel, models, store, adapters, fleet, skills, workflows,
               knowledge, work, identity, config, observability
apps/worker/   task-first React/Tauri client (the first-party browser surface)
site/          Next.js site + lightweight console overview
libraries/     skills + workflows + prompts (data, not code)
deploy/        kernel.Dockerfile, fleet.Dockerfile
docs/          ARCHITECTURE, invariants, DEFINITION-OF-DONE, decisions/
scripts/       smoke.py, check_invariants.py
tests/         pytest suite + invariants.yaml (the binding catalogue)
```
