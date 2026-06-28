# Nankle architecture

Nankle is a thin kernel with a fleet on top. The kernel owns policy and is the
only path to an external action; everything organisation-specific (adapters,
skills, workflows, the agent org chart, credentials) is data loaded from the
manifest and the libraries. This document maps the components, the dispatch
flow, the data model, the internal contracts (SRS S7), and where the binding
architectural principles P1-P10 are enforced.

## Component map

| Area | Package | Role |
| --- | --- | --- |
| Kernel | `nankle/kernel/` | The composition root (`__init__.py`) wiring the dispatch chokepoint (`dispatch.py`) and its policy components: grants (`grants.py`), rate limiting (`ratelimit.py`), credentials (`credentials.py`), audit (`audit.py`), HITL (`hitl.py`), cost (`cost.py`), registry (`registry.py`), PII (`pii.py`). HTTP surface in `app.py`. |
| Models | `nankle/models/` | Frozen domain dataclasses: registry (`registry.py`), grants (`grants.py`), context (`context.py`), audit (`audit.py`), hitl (`hitl.py`), identity (`identity.py`), libraries (`libraries.py`), work (`work.py`), and the error taxonomy (`errors.py`). |
| Store | `nankle/store/` | The `Store` Protocol (`base.py`), the reference `InMemoryStore` (`memory.py`), and the Postgres schema (`schema.sql`). |
| Adapters | `nankle/adapters/` | The single adapter Protocol (`base.py`), the loader (`loader.py`), builtin adapters (`builtin/`), and HTTP/SQL bases + a generator (`http_base.py`, `sql_base.py`, `generator.py`). |
| Fleet | `nankle/fleet/` | The durable hierarchy and ephemeral spawning: spawner (`spawn.py`), runtimes (`runtime.py`), chief-of-staff (`chief_of_staff.py`), department head (`department_head.py`), workers/Hatchet seam (`workers.py`). |
| Skills | `nankle/skills/` | Skill schema + loader (`schema.py`, `loader.py`) over `libraries/skills/`. |
| Workflows | `nankle/workflows/` | Precreated/generated workflow library (`library.py`, `generator.py`) over `libraries/workflows/`. |
| Work | `nankle/work/` | Source-agnostic work-item normalise/queue/store (`normalise.py`, `queue.py`, `store.py`). |
| Identity | `nankle/identity/` | Token verification + principal resolver (`auth.py`), IdP-group to role/scope (`rbac.py`), delegation (`delegation.py`). |
| Config | `nankle/config/` | Process settings from env (`settings.py`) and the fleet manifest loader/applier (`manifest.py`). |
| Observability | `nankle/observability/` | Execution-tree reconstruction from the audit log (`tree.py`). |
| UI | `ui/` | The React console: Router, Kanban, Approvals. |

## The dispatch flow (the fixed order)

Every verb invocation runs the same ordered path in
`nankle/kernel/dispatch.py` (`Dispatcher._invoke_inner`), and `invoke` always
writes one audit row in its `finally` block regardless of outcome:

| # | Step | Failure / signal | Pinned by |
| --- | --- | --- | --- |
| 1 | Resolve verb + binding (tenant-scoped) | `BindingNotFound` (fail-closed) | K-13, SEC-08 |
| 2 | Validate params against the verb input schema | `SchemaValidationError` | SEC-21 |
| 3 | Grant check (caller grants AND tenant ceiling) | `GrantMissing` | SEC-07, K-2 |
| 4 | Consequence / HITL gate (high or blocking verb) | `PendingHuman` (cannot be bypassed) | SEC-14 |
| 5 | Rate limit (per verb / per tenant) | `RateLimited` | FR-KER-05 |
| 6 | Idempotency replay (return the prior result) | (replay) | NFR-REL-02 |
| 7 | Resolve credential (inside the kernel only) | `CredentialResolution` | SEC-05, K-20 |
| 8 | Execute adapter or agent | degrade on `UNAVAILABLE` | P9 |
| 9 | Validate output against the verb output schema | `SchemaValidationError` | SEC-21 |
| 10 | Audit (always, hash-chained, scrubbed) | - | SEC-16, K-19, K-20 |

The order is load-bearing: validation precedes authorisation precedes the gate
precedes any side effect, and the credential is resolved last and never leaves
the kernel boundary.

## Data model summary

The durable state (`nankle/store/schema.sql`, PostgreSQL 16) carries `tenant_id`
on every table and is designed for `FORCE ROW LEVEL SECURITY` keyed on a
per-transaction `app.tenant_id` GUC (a null GUC yields zero rows, fail-closed).

- **Registry**: `nouns`, `verbs` (input/output schema, consequence,
  identity_mode, degraded_mode), `verb_bindings` (target_type adapter|agent,
  target_ref, rate_limit).
- **Libraries**: `adapters`, `skills` (prompt_fragment, tool_grants,
  context_requirements, extends), `agent_capabilities`, `workflow_definitions`,
  `model_endpoints` (data_class standard|sensitive).
- **Work**: `work_items` (intent, confidence, convergent, status, parent_id,
  hatchet_run_id, depth, on_behalf_of).
- **HITL**: `hitl_requests`, `hitl_responses`.
- **Identity / audit / cost**: `users`, `role_mappings`, `audit_log` (per-tenant
  monotonic `seq`, `prev_hash` -> `hash` chain), `idempotency_keys`, `budgets`
  (token/cost limit, hard_stop, window), `credential_refs` (refs only, never
  plaintext).

## Internal contracts (SRS S7)

- **S7.1 Invocation context + dispatch contract.** `InvocationContext`
  (`models/context.py`) travels with every call; identity is stamped from the
  verified bearer, never read from the body (K-3). Outcomes map 1:1 to the error
  taxonomy (`models/errors.py`) and to HTTP status codes in `kernel/app.py`
  (200 ok, 202 pending_human, 400 schema/context, 403 denied, 429
  rate/budget/depth, 503 degraded).
- **S7.2 Registry + discovery.** `KernelRegistry` (`kernel/registry.py`)
  registers an adapter's verbs as data and returns only the verbs a caller is
  scoped to see.
- **S7.3 Adapter interface.** One `Adapter` Protocol (`adapters/base.py`):
  `describe() -> [VerbSpec]`, `execute(verb, params, credential, context) ->
  Result`, `health()`. Errors map onto a common `ErrorClass`; `Credential`
  material is repr-suppressed.
- **S7.4 Skills + inheritance.** `Skill` (`models/libraries.py`) with
  parent-first `extends` resolution in `fleet/spawn.py` (`_resolve_skill_chain`):
  prompts concatenate, grants union, context_requirements merge.
- **S7.5 Spawn seam.** `Spawner.spawn` (`fleet/spawn.py`) composes skills,
  validates context, selects the cheapest capable runtime, enforces depth,
  reserves budget, runs, and audits. `make_agent_invoker` lets the kernel
  dispatch a reasoning-bound verb to a child without importing the fleet.
- **S7.6 Store Protocol.** `Store` (`store/base.py`) is the kernel's only
  persistence seam; `InMemoryStore` and a Postgres store satisfy it identically.
- **S7.7 Work queue.** Source-agnostic inbox/sink draining raw payloads into
  normalised `WorkItem`s (`work/queue.py`, `work/normalise.py`).

## Binding architectural principles (P1-P10) and where they are enforced

| Principle | Statement | Enforced in |
| --- | --- | --- |
| **P1** | Thin core: policy lives in kernel components; integrations are data. | `kernel/__init__.py`, `kernel/registry.py`, `adapters/loader.py` |
| **P2** | One dispatch chokepoint: every external action funnels through one ordered path. | `kernel/dispatch.py` |
| **P3** | A verb binds to a deterministic adapter OR a reasoning agent; credentials resolve only inside the kernel. | `models/registry.py` (TargetType), `kernel/credentials.py` |
| **P4** | Backend opacity + pluggable inference: agents reason in nouns/verbs and never learn the concrete system. | `kernel/registry.py` (discover), `kernel/grants.py` (reason hides backend), `fleet/runtime.py` |
| **P5** | Human-in-the-loop on high-consequence work; a gated verb cannot be bypassed. | `kernel/hitl.py`, `kernel/dispatch.py` (step 4) |
| **P6** | Durable, resumable execution over the Hatchet seam (plus idempotency). | `fleet/workers.py`, `kernel/dispatch.py` (step 6) |
| **P7** | Config-as-data: one image, many tenants; everything org-specific is manifest + env. | `config/manifest.py`, `config/settings.py` |
| **P8** | Least privilege: caller grants intersect the tenant ceiling, deny-dominant, fail-closed. | `kernel/grants.py`, `models/grants.py` |
| **P9** | Graceful degradation: unavailability yields a degraded result, never a crash. | `kernel/dispatch.py` (`_degrade_or_fail`), `models/errors.py` (DegradedMode) |
| **P10** | Source-agnostic work: heterogeneous inputs normalise to one WorkItem the fleet reasons over. | `work/normalise.py`, `work/store.py`, `models/work.py` |

## Front doors are dumb mouths over one smart engine

The HTTP API (`kernel/app.py`) reads no policy: it authenticates a `Principal`
(pluggable resolver, K-3), builds an `InvocationContext`, and calls
`kernel.invoke` / `kernel.discover` / the spawner. In-process callers (tests,
`scripts/smoke.py`) and a future MCP front door use the same engine, so the
guarantees hold no matter which mouth speaks.
