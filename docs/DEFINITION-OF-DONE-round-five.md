# Definition of Done - Round Five (memory & knowledge)

Status against the Round Five DoD (S R5 Ch.11). Markers: **done** (implemented +
bound to a test or a runnable check), **seam** (the code path is real; a live
external leg - the adopted engine, a model, or paid CI - is needed to exercise it
end to end).

Memory is opt-in per installation (`memory.enabled`). The governing principle
holds throughout: the kernel, not the engine, is the isolation boundary, and every
memory operation runs the dispatch chokepoint. The kernel dispatch sequence is
unchanged (NFR-MEM-05): `dispatch.py`/`grants.py`/`registry.py` are untouched -
memory is an adapter, routes, data, and an engine behind an interface.

## 1. Kernel-governed access

- [x] **done** Memory is reached only via the `memory.*` verbs through the
  chokepoint; the engine is unreachable directly; the `MemoryEngine` interface
  keeps the kernel/models engine-agnostic. Severability verified: the kernel core
  imports nothing from `boltrig.memory`. `boltrig/memory/{engine,local,cognee,adapter}.py`,
  `tests/security/test_round_five.py::test_memory_cannot_escalate` (FR-MEM-01/02,
  SEC-41).

## 2. Ingestion

- [x] **done** Conversation transcripts and documents cognify into the graph as a
  durable-or-local pipeline, with provenance, owner-scope assigned at ingestion,
  content screening, and a per-run `memory_ingestions` record. Sensitive ingestion
  routes to a local endpoint (a misroute is blocked + audited).
  `boltrig/memory/cognify.py`, `boltrig/memory/adapter.py`,
  `tests/security/test_round_five.py::test_ingestion_screens_poison`,
  `::test_sensitive_memory_stays_local` (FR-ING-01..06, SEC-40/42/43).
- [ ] **seam** Live durable cognify on a running Hatchet engine. The pipeline runs
  inline offline (P9) and uses the same durable-executor seam as Round Three
  workflows; a live engine is the inherited external leg.

## 3. Retrieval

- [x] **done** Scoped recall returns only permitted-scope facts with provenance,
  supports similarity and multi-hop graph-completion modes, and is grant-checked +
  audited. The reference engine bounds traversal to permitted scopes; the kernel
  re-filters regardless. `boltrig/memory/{local,adapter}.py`,
  `tests/security/test_round_five.py::test_kernel_is_the_isolation_boundary`,
  `::test_recall_is_audited_without_leaking_contents` (FR-RCL-01..04, SEC-40/45).

## 4. Learning & forgetting

- [x] **done** `memory.improve` reweights from a signal without changing scope or
  granting authority; `memory.forget` performs complete, engine-confirmed, audited
  erasure of a node and its derived edges/facts, recorded in the `memory_erasures`
  ledger (and marks transcript handling for a source erasure).
  `boltrig/memory/{local,adapter}.py`,
  `tests/security/test_round_five.py::test_complete_audited_erasure`
  (FR-LRN-01..04, SEC-44).

## 5. Isolation proven

- [x] **done** A hostile cross-scope fixture - including a multi-hop edge from an
  in-scope fact into another user's scope - shows recall cannot reach the
  out-of-scope fact; cross-scope edges are forbidden by config and dropped at
  ingestion. `tests/security/test_round_five.py::test_kernel_is_the_isolation_boundary`
  (SEC-40).

## 6. Site

- [x] **done** A scoped Memory panel (Recall with provenance, Browse, Remember,
  Ingest + ingestion status) shows what the caller is permitted to see; a permitted
  user can request erasure with a confirm. `ui/src/panels/MemoryPanel.tsx`. Build
  green (`tsc && vite build`). (FR-MUI-01..03)

## 7. Engine selection

- [x] **done** The engine is adopted behind the interface, not built: a local
  reference for dev/offline and a `CogneeEngine` seam that documents the adoption
  point and the MEM-ENG-04 selection criteria. `boltrig/memory/cognee.py`
  (MEM-ENG-01/02/03).
- [ ] **seam** The full Cognee adoption (wiring `cognee.add`/`cognify`/`search`/
  `prune`) and the validation against Mem0 / Zep-Graphiti / LightRAG is the
  external leg; the interface + seam are in place so the swap touches no core.

## 8. Governance & cost

- [x] **done** SEC-40..45 are bound to tests with catalogue entries;
  `python scripts/check_invariants.py` passes at binding-debt 0
  (`declared=64 bound_tests=82`). With memory disabled the offline suite stays
  green (the verbs simply are not registered). Ingestion is LLM-metered through the
  same cost path as any verb (the reference engine is free; a real engine's
  extraction/embedding cost is attributed via the chokepoint).
- [x] **done** Full offline suite green: `python -m pytest -q` -> 108 passed, 14
  skipped. Lint clean: `ruff check boltrig/ tests/ --select F,E9`.

## Operational

- [x] **done** Ordered Alembic migration `0003_round_five` chains from `0002`
  (single head) and adds `memory_facts`/`memory_ingestions`/`memory_erasures`; a
  fresh database gets them from the baseline replay of `schema.sql`.

## Supersession note

Round Three Epic MEM (the flat `memory_items` table + `/v1/memory/query`, bound by
SEC-31) is kept as the seed and remains green; Round Five adds the structured
`memory_facts` graph layer + the `memory.*` verbs beside it. A migration from
`memory_items` to `memory_facts` is the planned follow-on.

## Summary

Round Five is complete offline and bound at binding-debt 0. The open legs are
environmental, not code: the full Cognee adoption + comparative validation, live
durable cognify on a running Hatchet engine, and hosted CI (billing-blocked). This
closes the planned requirement rounds (One to Five); the remaining backlog is the
security-refinement consolidation (Security Batch 1 + Batch 2).
