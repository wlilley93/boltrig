# 0029 - Typed memory planes: a governed write gate around the memory ledger

- Status: accepted
- Date: 2026-08-16
- Implements: the "governed agent memory" direction (external spec, 2026-08-15),
  adapted to Boltrig doctrine

## Context

Round Five shipped governed but UNTYPED memory: `memory.remember` accepts any
content, mints a fresh opaque id, and everything is born active. Ultracode
filters recall by `source_ref` provenance keys as a post-hoc heuristic; session
distillation emulates replacement via forget-then-remember. Nothing in the
system distinguishes "what is true now" from "what happened before" from "how
must I act" - the three questions whose answers need different authority,
lifecycle and retrieval.

The external spec proposing a Cognee-centred redesign assumes a stack
(Mastra orchestration, Rivet sandboxes, Herdr inspector, a standalone memory
gateway service, `add_data_points`/sessions/improve Cognee APIs) that this
repository has retired or never adopted (decisions 0012, 0015, 0020): Codex is
the only runtime, the kernel ledger is the memory authority, and Cognee is a
rebuildable projection/compiler - not the policy holder.

## Decision

Adopt the spec's GOVERNANCE MODEL, not its architecture. Memory type becomes
how information BEHAVES, expressed inside the existing kernel-verb + ledger +
projection discipline:

1. **Five planes, three writable.** Semantic (current facts, one active value
   per slot), episodic (append-only experience from terminal runs), procedural
   (versioned governance, activated only by review). Source knowledge stays in
   the existing knowledge/document paths; working state is NEVER memory - it is
   pass-through bundle context.

2. **A typed write gate** (`memory.propose`): the model or a human proposes;
   deterministic code decides - ACCEPT_NEW / CONFIRM_EXISTING /
   SUPERSEDE_EXISTING / REJECT_TRANSIENT / REJECT_LOWER_AUTHORITY /
   REJECT_NOT_TERMINAL / REQUEST_HUMAN_REVIEW. Closed predicate registries,
   source-authority precedence, transient-wording rejection, supersession with
   retained history, per-slot asyncio locks with the DB partial unique index as
   the authoritative arbitrator (migration 0076).

3. **Procedures are authority, not similarity.** `memory.bundle` resolves
   active procedures deterministically by role/workflow specificity ranking;
   unapproved candidates can never govern; activation rides
   `memory.candidates.review` - a HIGH-consequence verb, so the HITL gate
   enforces that a human answers before anything governs.

4. **The bundle is the unit of consumption.** Procedures, current facts,
   source evidence, advisory episodes and working state - each lane budgeted,
   each authority-labelled in the rendered prompt (only `<active_procedures>`
   may instruct; episodes are wrapped `advisory="true"`). Plane toggles
   (`memory.typed` manifest block, per-call `config` overrides) exist for the
   ablation harness.

5. **Everything rides existing rails.** The gate is store-only; the adapter
   orchestrates engine writes and projection fanout ledger-first with
   compensation (the Round Five discipline). SEC-40 scope fencing, SEC-42
   screening, SEC-45 metadata-only recall audits and SEC-44 erasure apply to
   the typed paths unchanged.

## Non-goals (deliberately not adopted from the spec)

- A standalone memory-gateway service; the kernel adapter IS the gateway.
- Cognee sessions, `add_data_points`, `improve()`/self-improvement bridging -
  cognee stays at 1.4.0 with the existing five-API surface (dataset-per-scope,
  CHUNKS search), and typed facts project through the EXISTING engine/projection
  paths as ordinary scoped facts.
- New datasets/NodeSets; the (tenant, owner_scope) dataset mapping is unchanged.
- An ablation harness, LLM extraction contracts and a shadow-deployment
  scorecard - the toggles and budgets exist, the harness is future work.

## Binding conditions

1. One active value per semantic/procedural slot - DB-enforced (partial unique
   indexes, migration 0076), store-parity tested (MEM-TYP-01).
2. Unapproved procedures never govern; review is the only activation path and
   is HITL-gated (MEM-TYP-03, MEM-TYP-06).
3. Present-state wording is rejected as non-durable unless explicitly asserted
   (MEM-TYP-02); episodes only from terminal runs (MEM-TYP-04).
4. Working state never persists to memory and cannot be recalled by a later
   run (MEM-TYP-05); budgets clip with warnings, never silently.
5. Every gate decision appends a policy-versioned `memory_events` row.

## Consequences

- `memory_facts` grows typed columns (nullable; legacy rows are untouched
  first-class citizens) plus the `memory_events` table - RLS-fenced, both
  stores, migration 0076, alembic head bumped (readiness pin included).
- New verbs: `memory.propose` (low), `memory.bundle` (low), `memory.resolve`
  (low), `memory.candidates.review` (high). New routes: `POST
  /v1/memory/propose`, `POST /v1/memory/bundle`, `POST
  /v1/memory/candidates/{id}/review`, `GET /v1/memory/resolve`, `GET
  /v1/memory/candidates`, `GET /v1/memory/timeline`.
- Existing `memory.remember`/`recall`/`ingest` are unchanged: the untyped path
  remains the ordinary one; the typed path is additive.

## Implemented vs seams (honesty)

Implemented and offline-verified: typology, write gate, bundle builder, verb
wiring, routes, store parity (in-memory + real Postgres via the disposable
container), migration parity, six MEM-TYP invariants plus the SEC-40 typed-path
extension.

Seams / not built: LLM-side extraction contracts (the caller of
`memory.propose` is responsible for candidates - no model does this
automatically today); the Codex runtime does not yet CONSUME
`memory.bundle` in its prompt assembly; no ablation harness or scorecard; the
Worker/inspector has no candidate-queue or timeline UI yet; per-plane token
budgets are character approximations; Cognee typed projections ride the
existing optional projection config, which ships disabled
(`memory.projections: []`).
