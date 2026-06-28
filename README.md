# Nankle

[![GitHub repo](https://img.shields.io/badge/GitHub-wlilley93%2FNankle-181717?logo=github)](https://github.com/wlilley93/Nankle)
[![CI](https://github.com/wlilley93/Nankle/actions/workflows/ci.yml/badge.svg)](https://github.com/wlilley93/Nankle/actions/workflows/ci.yml)

A self-hostable agent-orchestration platform: a thin, secure kernel and a
permanent agent fleet that spawns ephemeral workers to get work done. Nankle is
a clean-room reference implementation of the "Hermes Fleet" SRS (the kernel
doctrine: one dispatch chokepoint, stable nouns and verbs, everything-as-data).

The kernel core is implemented and tested (74 passing tests + opt-in Postgres and
live-adapter suites; a machine-checked binding-invariant gate at debt 0).
Persistence (Postgres), real OIDC auth, sensitive->local model routing, and
durable HITL pauses are implemented and tested; the remaining external legs (a
live Hatchet engine, a live IdP, third-party adapter credentials, an on-box
model) are seams (see "Implemented vs scaffolded" below).

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
- Both Store implementations (in-memory + **Postgres**, `nankle/store/postgres.py`),
  the registry, the fleet spawner (skill inheritance, cheapest-runtime selection,
  depth + budget), the manifest loader/applier, and the kernel HTTP surface.
- **Real OIDC token verification** (`nankle/identity/auth.py`, RS256 against the
  issuer JWKS), with bootstrap selecting it when `OIDC_*` is set and failing
  closed otherwise; the header resolver only with `NANKLE_DEV_AUTH=1`.
- **Sensitive->local model routing guard** (`fleet/model_router.py`): sensitive
  data is blocked from non-local endpoints and the misroute is audited (SEC-12).
- **Durable HITL pause** (NFR-REL-01): a blocking pause survives a restart and
  resumes on approval over Postgres.

**Real, but with external seams** (the code is here; the live leg needs its
service or credentials to exercise):

- **Full live-Hatchet run-resume.** The durable HITL pause is done and tested; the
  full long/recursive run-resume needs a running Hatchet engine (the
  `hatchet-engine` service + `[durable]` extra). Without it the fleet still runs
  and degrades (P9); the local executor is the offline fallback.
- **Live IdP.** OIDC verification is implemented and tested against minted tokens;
  pointing it at a real Azure AD / Okta / Google issuer is the remaining leg.
- **Live MS Graph / Jira / CRM adapters.** The builtin adapters are real HTTP/SQL
  clients but need credentials and reachable backends (opt-in `make smoke` with
  `NANKLE_LIVE_SMOKE=1`). The `memory-tickets` adapter is fully self-contained.
- **On-box model (local inference).** The `local-model` compose profile runs a
  local OpenAI-compatible endpoint for sensitive data; it needs a model + (for
  vLLM) a GPU, or swap in Ollama for CPU. (The routing guard that *requires* it
  for sensitive data is done.)
- **Alembic migrations.** `schema.sql` is the source of truth and applied
  idempotently; an ordered alembic set (`make migrate`) is the remaining additive
  step.

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
