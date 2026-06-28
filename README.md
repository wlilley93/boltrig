# Nankle

A self-hostable agent-orchestration platform: a thin, secure kernel and a
permanent agent fleet that spawns ephemeral workers to get work done. Nankle is
a clean-room reference implementation of the "Hermes Fleet" SRS (the kernel
doctrine: one dispatch chokepoint, stable nouns and verbs, everything-as-data).

The kernel core is implemented and tested (34 passing tests; a machine-checked
binding-invariant gate). Adapters, the fleet, the UI, and the deploy stack are
real but some external legs are seams (see "Implemented vs scaffolded" below).

## The three defining characteristics

1. **A thin core.** The kernel implements policy nowhere itself. It composes a
   dispatcher, grant checker, rate limiter, credential resolver, audit writer,
   HITL gate, and cost accountant, and it loads everything else (adapters,
   skills, workflows, capabilities) as data (`nankle/kernel/__init__.py`,
   `nankle/kernel/dispatch.py`). Adding an integration changes no core code.
2. **A permanent fleet that spawns ephemerals.** A durable hierarchy (a tier1
   chief-of-staff over tier2 department heads) takes in work and spawns
   short-lived child agents to do it, picking the cheapest capable runtime,
   reserving budget first, and enforcing recursion depth
   (`nankle/fleet/spawn.py`, `nankle/fleet/runtime.py`).
3. **The kernel abstracts actions behind nouns and verbs.** Agents reason in
   stable nouns (`ticket`) and verbs (`ticket.create`); the kernel resolves each
   verb to a concrete adapter or agent via a binding. The agent never learns
   which concrete system sits behind a verb (`nankle/kernel/registry.py`,
   `nankle/models/registry.py`).

## Governance: the doctrine and the consolidation ruling

Nankle implements, but does not author, a kernel doctrine. The **single source
of that doctrine (the K-1..K-30 invariant catalogue) is the `agent-kernel-doctrine`
repository.** Nankle conforms to it; it never redefines or forks it. Any change to
the meaning of a `K-*` invariant originates there, and Nankle tracks it.

Nankle exists as its own repository by the ruling of the VJS County Court,
**[2026] VJS-CC NANKLE-CONSOLIDATION 001** ("conditioned standalone"). The court
held that the single-source-of-law precedents govern unity of *law*, not the
coexistence of conforming *code* implementations of one doctrine, and permitted
Nankle to stand alone on binding conditions: it cites the doctrine as the single
source (above), keys its invariants to the doctrine's Appendix A, keeps the
binding-invariant gate at debt 0 in required CI, converges on (never competes
with) the doctrine's unified capability primitive, stays severable (the kernel
and models import nothing from sibling estate kernels), and forks no parallel
codebase of its own (the difference between installations is config, never a
forked Nankle, per P7). Breach of any condition routes Nankle to consolidation.
See `docs/decisions/0002-nankle-consolidation-ruling.md`.

## Quick start

### Run the tests + checks (no docker)

```bash
python -m venv .venv
.venv/bin/pip install -e ".[durable,inference]"
.venv/bin/pip install pytest pytest-asyncio aiosqlite ruff

make test         # the 34 kernel + security tests
make smoke        # offline, in-process demo of the kernel guarantees
make invariants   # the binding-invariant gate (every claim must have a test)
```

`make smoke` exercises the dispatch chokepoint end to end on an in-memory store:
a granted call, a denied call, a gated pause-then-approve, and a degraded call.

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

## Architecture

```
                          fleet manifest (manifest.yaml)        .env
                          who/auth/models/hierarchy/adapters     process wiring
                                       |                            |
   +---------+   HTTP    +-------------v----------------------------v----------+
   |   UI    |---------->|                    KERNEL                           |
   | Router  |  /v1/*    |  one dispatch chokepoint (P2), policy lives here:   |
   | Kanban  |<----------|  resolve -> validate -> grant -> HITL -> rate-limit |
   |Approvals|  202/403  |  -> idempotency -> resolve credential -> execute    |
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
`nankle/kernel/dispatch.py`, and every action writes exactly one append-only,
hash-chained audit row regardless of outcome. See `docs/ARCHITECTURE.md` for the
full component map, the dispatch contract, and where each principle (P1-P10) is
enforced.

## How "thinness" is preserved

Adding a new integration is data + libraries, never a core edit:

- a new **adapter** (`nankle/adapters/builtin/<x>.py` or a generated/manual one)
  declares its verbs, schemas, and recommended rate limits via `describe()`;
- new **skills** and **workflows** are YAML in `libraries/`;
- the **manifest** wires them to the tenant (credentials as refs, the agent org
  chart, spawn rules, HITL policy, network/privacy posture).

The kernel registers an adapter's verbs as rows (`KernelRegistry`), resolves them
through bindings, and dispatches them through the same chokepoint. No file under
`nankle/kernel/` changes to add Jira, Salesforce, or a new department.

## Implemented vs scaffolded (honesty section)

**Fully implemented and tested** (the load-bearing core):

- The dispatch chokepoint and its fixed order (`nankle/kernel/dispatch.py`):
  resolve, schema-validate, grant-check, HITL gate, rate-limit, idempotency,
  in-kernel credential resolution, execute, output-validate, audit.
- Grant semantics (deny-dominant, fail-closed, wildcard rules), the tenant
  ceiling intersection, tenant isolation, the HITL approval gate, the
  tamper-evident hash-chained audit, PII redaction, secret scrubbing, budget
  hard-stops, rate limiting, and graceful degradation. These are pinned by the
  binding-invariant catalogue (`docs/invariants.md`, `tests/invariants.yaml`)
  and the gate at `scripts/check_invariants.py`.
- The in-memory store (the reference Store implementation), the registry, the
  fleet spawner (skill inheritance, cheapest-runtime selection, depth + budget),
  the manifest loader/applier, and the kernel HTTP surface.

**Real, but with external seams** (the code is here; the live leg needs its
service or credentials to exercise):

- **Durable execution (Hatchet).** The fleet is built for durable resume; the
  `hatchet-engine` / `hatchet-dashboard` services and the `[durable]` extra wire
  it. Without Hatchet the fleet still runs and degrades (P9).
- **Live OIDC / SAML.** `nankle/identity/auth.py` ships a real `OidcVerifier`;
  it needs an issuer + JWKS to verify real tokens. The dev resolver trusts
  `x-nankle-*` headers and is for local dev only (SEC-01/02).
- **Live MS Graph / Jira / CRM adapters.** The builtin adapters are real HTTP/SQL
  clients but need credentials and reachable backends. The `memory-tickets`
  adapter is fully self-contained (used by the tests and `make smoke`).
- **On-box model (local inference).** The `local-model` compose profile runs a
  local OpenAI-compatible endpoint for sensitive data; it needs a model + (for
  vLLM) a GPU, or swap in Ollama for CPU.
- **Postgres-backed store + migrations.** `nankle/store/schema.sql` is the
  source of truth and is applied on first boot; an alembic migration set
  (`make migrate`) is the remaining packaging step. Tests + smoke run on the
  in-memory store.

## Layout

```
nankle/        kernel, models, store, adapters, fleet, skills, workflows,
               work, identity, config, observability
ui/            React console (Router, Kanban, Approvals)
libraries/     skills + workflows + prompts (data, not code)
deploy/        kernel.Dockerfile, fleet.Dockerfile
docs/          ARCHITECTURE, invariants, DEFINITION-OF-DONE, decisions/
scripts/       smoke.py, check_invariants.py
tests/         34 tests + invariants.yaml (the binding catalogue)
```
