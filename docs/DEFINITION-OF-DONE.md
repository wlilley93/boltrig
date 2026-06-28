# Definition of Done (SRS S13)

The SRS S13 Definition of Done, restated as a checklist and assessed honestly
against this build. Each item is marked:

- **done** - implemented and covered by tests / a runnable check;
- **seam** - the code path is implemented but a live external leg (a service,
  credentials, or a model) is required to exercise it end to end;
- **deferred** - acknowledged, not built in this iteration.

## Core kernel

- [x] **done** Single dispatch chokepoint with a fixed, audited order (P2). `nankle/kernel/dispatch.py`; `tests/kernel/test_dispatch.py`.
- [x] **done** Stable nouns / verbs resolved via bindings; agents never see the backend (P4). `kernel/registry.py`; `tests/kernel/test_app.py::test_discovery_is_role_scoped`.
- [x] **done** Schema validation of params and output (SEC-21). `tests/kernel/test_dispatch.py::test_invalid_params_rejected_before_dispatch`.
- [x] **done** Fail-closed on unknown verb / missing binding (K-13). `tests/kernel/test_dispatch.py::test_unknown_verb_fails_closed`.
- [x] **done** Idempotency replay for side-effecting verbs (NFR-REL-02). `dispatch.py` step 6; `store` idempotency keys.

## Security + identity

- [x] **done** Grant enforcement: caller grants intersect the tenant ceiling, deny-dominant (SEC-07, K-2, K-5, K-9). `kernel/grants.py`; `tests/security/test_grant_enforcement.py`, `tests/unit/test_grants_model.py`.
- [x] **done** Tenant isolation, fail-closed (SEC-08). `tests/security/test_tenant_isolation.py`. Postgres RLS scaffolded in `store/schema.sql`.
- [x] **done** Credentials resolved only inside the kernel; never returned or audited (SEC-05, K-20). `kernel/credentials.py`; `tests/security/test_credential_isolation.py`.
- [x] **done** Append-only, hash-chained, tamper-evident audit (SEC-16, K-19). `kernel/audit.py`; `tests/kernel/test_audit_chain.py`.
- [x] **done** PII redaction + secret scanning (SEC-13). `kernel/pii.py`; `tests/security/test_budget_and_pii.py`.
- [~] **seam** Live OIDC / SAML token verification (SEC-01/02). `OidcVerifier` is implemented (`identity/auth.py`); it needs an issuer + JWKS. The dev resolver trusts headers for local dev only.

## Fleet + execution

- [x] **done** Spawn pipeline: skill inheritance, cheapest-capable runtime, depth limit, budget-before-run, audited (US-FLT-03/04, FR-EXE-03). `fleet/spawn.py`.
- [x] **done** Graceful degradation: a runtime/backend failure degrades, never crashes (P9). `dispatch.py` (`_degrade_or_fail`), `fleet/spawn.py`; `tests/kernel/test_ratelimit_degraded.py::test_degraded_mode_when_backend_down`.
- [~] **seam** Durable, resumable execution over Hatchet (P6, US-FLT-06). The seam + `[durable]` extra + compose services are in place; needs a running Hatchet engine.
- [x] **done** Source-agnostic work normalisation to one WorkItem (P10). `work/normalise.py`, `work/store.py`.

## Cost + HITL + observability

- [x] **done** Budget hard-stop and soft-overage accounting (FR-COST-02). `kernel/cost.py`; `tests/security/test_budget_and_pii.py`.
- [x] **done** Per-verb / per-tenant rate limiting (FR-KER-05). `kernel/ratelimit.py`; `tests/kernel/test_ratelimit_degraded.py::test_rate_limit_enforced`.
- [x] **done** HITL approval gate on high-consequence / blocking verbs, with resume (SEC-14, US-HIL-01). `kernel/hitl.py`, `dispatch.py` step 4; `tests/security/test_hitl_gate.py`.
- [x] **done** Execution-tree reconstruction from the audit log (US-OBS-02). `observability/tree.py`; surfaced at `/v1/audit/tree/{run_id}`.

## Adapters + libraries

- [x] **done** One adapter interface, dynamically loaded; verbs registered as data (P1, S7.3). `adapters/base.py`, `adapters/loader.py`, `kernel/registry.py`.
- [x] **done** A self-contained builtin adapter exercised end to end (`memory-tickets`). `adapters/builtin/memory_tickets.py`; used by the suite and `scripts/smoke.py`.
- [~] **seam** Live MS Graph / Jira / CRM adapters. The clients are real (`adapters/builtin/*`, `http_base.py`, `sql_base.py`) but need credentials and reachable backends.
- [x] **done** Skills + workflows as data, with skill `extends` inheritance (S7.4). `skills/`, `workflows/`, `libraries/`.

## Deployment + packaging

- [x] **done** One self-hostable stack; identical images, config via env + manifest (S11.1, P7, NFR-PORT-01). `docker-compose.yml`, `deploy/*.Dockerfile`, `.env.example`, `manifest.example.yaml`.
- [x] **done** Corporate proxy + CA bundle support at build/runtime (US-DEP-04). `deploy/kernel.Dockerfile`, `deploy/fleet.Dockerfile`.
- [~] **seam** On-box inference for sensitive data (SEC-12). The `local-model` compose profile + manifest `sensitive_endpoint` are wired; needs a model (and a GPU for vLLM, or swap to Ollama).
- [~] **seam** Postgres-backed store + migrations. `store/schema.sql` is the source of truth (applied on first boot); the alembic migration set behind `make migrate` is the remaining packaging step. Tests + smoke run on the in-memory store.

## Quality gate

- [x] **done** Test suite green (34 tests). `make test`.
- [x] **done** Offline, in-process smoke of the kernel guarantees. `make smoke` (4/4 steps pass).
- [x] **done** Binding-invariant gate at debt 0 (16 declared, 16 bound). `make invariants`; `docs/invariants.md`, `tests/invariants.yaml`, `scripts/check_invariants.py`.
- [~] **seam** UI end-to-end against a live kernel. The React console (Router, Kanban, Approvals) is built and proxies `/v1`; full e2e needs the running stack.
