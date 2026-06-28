# Nankle - Requirements, Round Five

## Memory & Knowledge: Conversation History and a Structured, Kernel-Governed Memory Layer

**Document type:** Requirements addendum to the Nankle SRS (Rounds One to Four)
and the Security Hardening Specification. **Status:** build-ready. **Supersedes
Round Three Epic MEM** (which was optional and specified only a flat embedding
store) and replaces it with a structured knowledge-graph memory layer. Memory
remains an **opt-in capability** per installation, but where enabled it is
specified to this depth.

**Inherited conventions.** Requirement ids (`FR-AREA-NN`, `US-AREA-NN`, `SEC-NN`
continuing from SEC-39), the ten architectural principles, the Round-Three
cross-cutting rules (C1 manifest-as-source-of-truth; C2 authoring writes
versioned data not code; C3 RBAC-gated + audited; C4 actions pass the chokepoint;
C5 scope-filtered views), and the governance ratchet (every guarantee
invariant-bound, binding-debt 0, no `K-*` invention, severability preserved) all
apply unchanged. New area codes: **MEM** (memory core), **ING** (ingestion),
**RCL** (retrieval), **LRN** (learning/forgetting/provenance), **MUI** (memory in
the site).

**The principle that governs this whole round:** memory is powerful precisely
because it fuses facts across conversations, documents, users, and departments,
which is also exactly what leaks across boundaries if isolation is weak, and a
graph makes leakage worse because multi-hop traversal connects facts in
non-obvious ways. Therefore **the kernel, not the memory engine, is the isolation
boundary**, and every memory operation runs the dispatch chokepoint.

---

# Chapter 1 - Two Distinct Layers

This round draws a hard line between two layers that are easy to conflate.

## 1.1 Conversation history (transcript layer) - already built

Round Two's `conversations` + `conversation_messages` tables are the **verbatim
transcript** of human/fleet threads: what was said, when, by whom, linked to
runs, owner-scoped, with Round Four export/delete. This layer is the **source of
truth for conversations** and is adequate for listing, continuing, and exporting
threads. It is **not** memory in the cognition sense, it does not let an agent
recall a decision made weeks ago across different conversations without re-reading
transcripts. This round does not change the transcript layer; it **derives** the
memory layer from it.

## 1.2 Structured memory (knowledge layer) - this round

A **derived, structured memory**: entities and relationships extracted from
transcripts and documents into a knowledge graph combined with vector embeddings,
supporting semantic recall and multi-hop reasoning ("what did we decide about the
migration, and who owns the follow-up?"). This is the layer Round Three Epic MEM
only sketched as flat RAG; this round specifies it as a graph-vector hybrid behind
kernel-governed verbs.

**Relationship between the layers.** Transcripts are verbatim and authoritative;
memory is derived and refined. Deleting a memory fact does not delete the
transcript, and vice versa, but **erasure (right-to-be-forgotten) must address
both** (LRN/PRIV-04). Memory always carries provenance back to its
transcript/document source.

---

# Chapter 2 - Scope of This Round

### In scope
- A kernel-governed **memory verb surface** (`memory.remember`, `memory.recall`,
  `memory.improve`, `memory.forget`) bound to a swappable **Memory Engine**.
- The **cognify pipeline**: turning conversation transcripts and ingested
  documents into the structured graph, incrementally and at session end, as a
  durable workflow.
- **Two-tier memory**: per-conversation session/working memory and long-lived
  permanent memory.
- **Retrieval and reasoning**: scoped semantic + graph-traversal recall, returning
  provenance.
- **Learning and forgetting**: usage/feedback-driven refinement and complete,
  verifiable erasure.
- **Scope isolation, poisoning defence, sensitive routing, and provenance**,
  enforced at the kernel.
- **Memory surfaces in the site**: a scoped memory browser and management.

### In scope but engine-agnostic (decision point)
- The **Memory Engine** is adopted, not built (build-vs-adopt, Chapter 4);
  requirements are written against an engine-agnostic interface with **Cognee as
  the reference implementation** and Mem0 / Zep-Graphiti / LightRAG as evaluated
  alternatives.

### Out of scope (deferred)
- Cross-installation/federated memory sharing.
- Training or fine-tuning models on memory.
- Fully autonomous, unreviewed memory-driven actions (memory informs reasoning; it
  does not bypass grants or the HITL gate).

---

# Chapter 3 - Architecture

```
   Conversation transcripts (Round 2)      Documents (Graph/file adapters)
                 |                                   |
                 v                                   v
        +-----------------------------------------------------+
        |  COGNIFY PIPELINE  (durable Hatchet workflow)       |   [ING]
        |  classify -> permission/scope -> extract chunks ->  |
        |  LLM entity+relationship extraction -> summarise -> |
        |  embed -> commit nodes/edges  (sensitive->local)    |
        +---------------------------+-------------------------+
                                    | writes (scoped, provenance-tagged)
        +---------------------------v-------------------------+
        |  MEMORY ENGINE  (adopted, swappable; Cognee ref)    |
        |  permanent: knowledge graph + vectors (on Postgres) |
        |  session:   per-conversation working memory         |
        +---------------------------^-------------------------+
                                    | engine adapter (one interface)
        +---------------------------+-------------------------+
        |  KERNEL - memory.* verbs run the dispatch chokepoint|   [MEM]
        |  grant check . scope enforcement . audit . provenance|
        +---------------------------^-------------------------+
                                    | memory.remember / recall / improve / forget
                 +------------------+------------------+
                 |  FLEET agents (and headless clients)|
                 |  never touch the engine directly    |
                 +-------------------------------------+
```

**Key properties of the architecture:**

- **Memory is verbs behind the chokepoint (P2, C4).** Agents and headless clients
  reach memory only through `memory.*` verbs; the kernel resolves them to the
  Memory Engine adapter and enforces grants, scope, and audit on every call. The
  engine is never directly reachable by an agent.
- **The engine is a swappable adapter.** A `MemoryEngine` interface (the memory
  analogue of the `Adapter` protocol) abstracts the engine; Cognee is the
  reference; the interface is the contract so the engine can change without
  touching the kernel or fleet (P1).
- **Two tiers.** *Session memory* is per-conversation working context (fast,
  short-lived, scoped to the thread). *Permanent memory* is the long-lived
  knowledge graph. Session traces are promoted into permanent memory by the
  pipeline.
- **The cognify pipeline is a durable workflow.** Ingestion runs as a Hatchet
  workflow (durable, schedulable, fan-out), incrementally as conversations
  progress and/or at session end, processing only new/updated sources.
- **Provenance everywhere.** Every fact links back to its source (conversation id,
  document, verb result) and the scope and time it was learned, so any recalled
  fact is traceable and erasable.
- **Reuses Postgres.** The reference engine runs its graph+vector+session store on
  the existing PostgreSQL instance, no new datastore is mandated (an installation
  may point the engine elsewhere via config).

---

# Chapter 4 - Engine Selection (Build vs. Adopt)

- **MEM-ENG-01 - Adopt, do not build.** Nankle MUST NOT build a knowledge-graph
  memory engine; entity extraction, graph construction, multi-hop retrieval, and
  edge reweighting are a deep specialised problem. An existing engine is adopted
  behind the `MemoryEngine` interface.
- **MEM-ENG-02 - Engine-agnostic interface.** All memory requirements are
  expressed against the engine-agnostic interface (remember / recall / improve /
  forget plus pipeline hooks). The engine is a configuration choice, not a code
  dependency of the kernel or fleet (severability and P1 preserved).
- **MEM-ENG-03 - Reference implementation and evaluation.** **Cognee** is the
  reference implementation (self-hostable, Postgres-capable, permissively
  licensed, MCP-/agent-SDK-integrable, with built-in tenant isolation). The
  selection MUST be validated against alternatives (Mem0, Zep/Graphiti, LightRAG)
  on the criteria below before commitment.
- **MEM-ENG-04 - Selection criteria (weighted to Nankle's needs).** Strength of
  **multi-tenant/scope isolation**; **complete erasure** (forget a node and its
  derived edges/facts); **self-hosting and data residency**;
  **provenance/traceability**; **sensitive-data handling** (provider-agnostic
  embedding/extraction so sensitive data can use a local endpoint); operational
  footprint (ideally no new datastore); licence; and retrieval quality
  (graph-traversal/multi-hop, not just similarity).

---

# Chapter 5 - Data Model Additions

The engine owns the graph/vector store internally; Nankle persists the
**governance and provenance metadata** it must control independently of the
engine.

```sql
-- Memory facts Nankle governs (mirrors/links engine nodes; the kernel's control plane)
CREATE TABLE memory_facts (
    id            TEXT PRIMARY KEY,        -- Nankle id, mapped to the engine node id
    tenant_id     TEXT NOT NULL,
    owner_scope   TEXT NOT NULL,           -- 'user:<id>' | 'department:<name>' | 'org' (the RBAC boundary)
    engine_ref    TEXT NOT NULL,           -- the engine's node/record identifier
    kind          TEXT NOT NULL,           -- 'entity' | 'relationship' | 'summary' | 'document_chunk'
    data_class    TEXT NOT NULL DEFAULT 'standard',  -- standard | sensitive
    source_kind   TEXT NOT NULL,           -- 'conversation' | 'document' | 'verb_result' | 'feedback'
    source_ref    TEXT,                    -- conversation id / document id / run id
    created_at    TIMESTAMPTZ NOT NULL,
    redacted      BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX ON memory_facts (tenant_id, owner_scope, kind);
CREATE INDEX ON memory_facts (source_kind, source_ref);

-- Ingestion runs (the cognify pipeline; durable workflow records)
CREATE TABLE memory_ingestions (
    id            TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    source_kind   TEXT NOT NULL,
    source_ref    TEXT NOT NULL,
    owner_scope   TEXT NOT NULL,
    status        TEXT NOT NULL,           -- pending | screening | cognifying | done | failed | rejected
    hatchet_run_id TEXT,
    facts_added   INT DEFAULT 0,
    screened      BOOLEAN NOT NULL DEFAULT false,  -- injection/malware screen passed
    created_at    TIMESTAMPTZ NOT NULL
);

-- Erasure ledger (right-to-be-forgotten; verifiable completeness)
CREATE TABLE memory_erasures (
    id            TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    requested_by  TEXT NOT NULL,
    target        TEXT NOT NULL,           -- a fact id, a source_ref, a subject, or a scope
    scope         TEXT NOT NULL,
    engine_confirmed BOOLEAN NOT NULL DEFAULT false,  -- engine reported deletion of node+derived edges
    transcript_handled BOOLEAN NOT NULL DEFAULT false,-- linked transcripts handled per policy
    completed_at  TIMESTAMPTZ
);
```

Conversation transcripts (`conversations`/`conversation_messages`) and document
sources are unchanged; `memory_facts.source_ref` links memory back to them.

---

# Chapter 6 - Interface Additions

All RBAC-gated (C3), scope-filtered (C5), audited, and run through the dispatch
chokepoint (C4).

```
# Memory verbs (bound to the Memory Engine adapter)
memory.remember   { content, owner_scope, source_ref, data_class }  -> fact ids
memory.recall     { query, scope, mode?, limit? }                   -> facts + provenance
memory.improve    { signal, target }                                -> updated weighting
memory.forget     { target, scope }                                 -> erasure record

# HTTP surface (also drivable headless / via MCP, Round Four HEAD)
POST /v1/memory/recall          scoped query (the read path; mode selects similarity vs graph traversal)
POST /v1/memory/remember        explicit write (usually the pipeline writes; this is for direct facts)
POST /v1/memory/forget          erasure request -> memory_erasures
GET  /v1/memory/facts           browse facts the caller is permitted to see (provenance included)
POST /v1/memory/ingest          enqueue a cognify run for a conversation/document (pipeline)
GET  /v1/memory/ingestions      ingestion run status
```

The `memory.recall` verb returns each fact **with its provenance and scope**, so
the agent (and the UI) can show *why* something is known and from where.

---

# Chapter 7 - Functional Requirements

## Epic MEM - Memory core & the verb surface

**US-MEM-01 - Memory is reached only through kernel verbs.** Every memory
operation passes the chokepoint, so grants, scope, and audit always apply.
Acceptance: agents/headless clients access memory only via `memory.*` verbs; the
engine is unreachable directly; each call runs grant check, scope enforcement, and
audit. Maps: FR-MEM-01. Invariant-bound.

**US-MEM-02 - Swappable engine behind one interface.** Acceptance: a
`MemoryEngine` interface fronts the engine; the kernel/models import nothing
engine-specific (severability); swapping the engine requires no core change. Maps:
FR-MEM-02.

**US-MEM-03 - Two-tier memory.** Acceptance: session memory scopes to the
conversation and resolves intra-thread references; permanent memory persists
across sessions; promotion from session to permanent occurs via the pipeline.
Maps: FR-MEM-03.

**US-MEM-04 - Memory informs, never overrides authority.** Acceptance: memory
content cannot alter an agent's grants, identity, budget, or the HITL gate; a
recalled "fact" that is actually an instruction is treated as data, not a command.
Maps: FR-MEM-04, SEC-41.

## Epic ING - Ingestion & the cognify pipeline

**US-ING-01 - Chat history feeds memory.** Acceptance: conversation transcripts
are cognified into the graph incrementally and/or at session end; only new/updated
content is processed; each derived fact carries provenance back to the
conversation and turn. Maps: FR-ING-01.

**US-ING-02 - Documents feed memory.** Acceptance: documents ingested via the
Graph/file adapters are cognified with page/section provenance; re-ingestion
updates only changed content. Maps: FR-ING-02.

**US-ING-03 - Ingestion is a durable workflow.** Acceptance: the pipeline runs as
a Hatchet workflow with resume, fan-out, and optional scheduling; status is
tracked in `memory_ingestions`. Maps: FR-ING-03.

**US-ING-04 - Scope assigned at ingestion.** Acceptance: each ingested fact is
assigned an `owner_scope` derived from its source (the conversation's
owner/department, the document's classification); cross-scope edges are forbidden
or explicitly governed. Maps: FR-ING-04, SEC-40.

**US-ING-05 - Ingestion-time screening (anti-poisoning).** Acceptance: content is
screened for prompt-injection payloads and malware before cognify; flagged content
is rejected (status `rejected`) and not committed. Maps: FR-ING-05, SEC-42
(security-spec CONV-02).

**US-ING-06 - Sensitive ingestion stays local.** Acceptance: entity extraction
and embedding for `sensitive` data use the local endpoint; sensitive facts and
their embeddings are stored within the boundary. Maps: FR-ING-06, SEC-43
(security-spec AGT-11/SEC-31).

## Epic RCL - Retrieval & reasoning

**US-RCL-01 - Scoped recall.** Acceptance: `memory.recall` returns facts only
within the requesting context's permitted `owner_scope`(s); traversal may not
cross into impermissible scopes; results include provenance. Maps: FR-RCL-01,
SEC-40.

**US-RCL-02 - Multiple retrieval modes.** Acceptance: recall supports at least
vector-similarity and graph-completion (multi-hop) modes; the mode is selectable;
multi-hop answers traverse explicit relationships, not flat similarity. Maps:
FR-RCL-02.

**US-RCL-03 - Session continuity.** Acceptance: intra-conversation
pronoun/reference resolution uses session memory scoped to the thread. Maps:
FR-RCL-03.

**US-RCL-04 - Recall is a chokepoint verb.** Acceptance: `memory.recall` runs the
dispatch sequence; the query, the scope, and the count of facts returned are
audited (the fact contents are handled per logging-privacy rules). Maps: FR-RCL-04.

## Epic LRN - Learning, forgetting & provenance

**US-LRN-01 - Memory improves with use.** Acceptance: `memory.improve` reweights
edges/derives facts from usage and feedback signals (success/failure traces);
improvement cannot change a fact's scope or grant any authority. Maps: FR-LRN-01.

**US-LRN-02 - Complete, verifiable forgetting.** Acceptance: `memory.forget`
removes the target node and its derived edges/facts from the engine, records a
`memory_erasures` entry, and marks `engine_confirmed`; the operation is
verifiable. Maps: FR-LRN-02, SEC-44.

**US-LRN-03 - Erasure spans both layers.** Acceptance: an erasure targeting a
subject/source handles linked transcripts per retention/legal-hold policy and the
derived memory facts, recording both in the ledger. Maps: FR-LRN-03 (links Round
Three PRIV-04, TEN-04).

**US-LRN-04 - Provenance on every fact.** Acceptance: every fact carries source
kind, source ref, scope, and time learned; recall and the UI surface this
provenance. Maps: FR-LRN-04.

## Epic MUI - Memory in the site

**US-MUI-01 - Scoped memory browser.** Acceptance: a memory view lists/queries
facts within the caller's scope, with provenance and source links; nothing
out-of-scope is shown. Maps: FR-MUI-01.

**US-MUI-02 - Manage and forget.** Acceptance: a permitted user can request
erasure of a fact/source from the UI (LRN-02/03), with confirmation; the action is
audited. Maps: FR-MUI-02.

**US-MUI-03 - Memory health (admin).** Acceptance: ingestion runs, fact counts by
scope, and erasure activity are visible to admins (scope-filtered); links to cost
(ingestion is LLM-metered). Maps: FR-MUI-03.

---

# Chapter 8 - Non-Functional Additions

- **NFR-MEM-01 - Ingestion cost is explicit and bounded.** Cognify is LLM-metered;
  ingestion cost is attributed (Round Three OBS) and subject to budgets; the
  upfront-ingestion / cheaper-recall tradeoff is surfaced so operators can reason
  about it.
- **NFR-MEM-02 - Recall latency.** Scoped recall returns within an interactive
  latency budget; session memory is fast-path; permanent graph traversal is
  bounded (depth/result caps).
- **NFR-MEM-03 - Scalability.** Memory scales to the organisation's corpus;
  ingestion is incremental (only new/changed sources) and parallelisable via the
  durable pipeline.
- **NFR-MEM-04 - Offline-safe.** With memory disabled or the engine/model absent,
  the fleet operates normally (memory verbs degrade cleanly, P9); the offline test
  suite stays green.
- **NFR-MEM-05 - Core unchanged.** Memory adds verbs, an engine adapter, a
  pipeline, data, and UI over existing services; the kernel dispatch sequence is
  unchanged (verified by diff).

---

# Chapter 9 - Security Additions

Continues the SRS `SEC-*` sequence and cross-references the Security Hardening
Specification (CONV-*, SEC-31, PRIV-04, AGT-11). These are the hardest controls in
this round; each is invariant-bound at binding-debt 0.

- **SEC-40 - The kernel is the isolation boundary (ingestion + retrieval).** Scope
  isolation is enforced by the kernel at **both** ingestion (every fact assigned
  an `owner_scope`) and retrieval (recall traverses only permitted scopes); the
  engine's own tenant isolation is defence-in-depth, never the sole boundary.
  Cross-scope edges are forbidden unless an explicit, audited policy permits them.
  Tested with a hostile cross-scope fixture. *(Security-spec CONV-03/SEC-31,
  deepened for a graph.)*
- **SEC-41 - Memory cannot escalate or instruct.** Recalled content can never
  alter an agent's grants, identity, budget, or the HITL gate, and is treated as
  data, not commands (US-MEM-04). *(Security-spec CONV-01.)*
- **SEC-42 - Poisoning resistance at ingestion.** Content is screened for
  injection/malware before it becomes memory; injected instructions cannot persist
  into the graph or propagate via relationships into a future privileged turn.
  *(Security-spec CONV-02.)*
- **SEC-43 - Sensitive memory respects residency.** Extraction, embedding, and
  storage of `sensitive`-classified memory use local endpoints and stay within the
  boundary; a misroute is blocked and audited. *(Security-spec AGT-11/SEC-31.)*
- **SEC-44 - Complete, audited erasure.** `memory.forget` removes a node and its
  derived edges/facts (verified via the engine), records an erasure-ledger entry,
  and, for subject erasure, addresses linked transcripts per policy; erasure is
  auditable. *(Round Three PRIV-04, deepened for a graph.)*
- **SEC-45 - Recall is least-privilege and audited.** Recall is grant-checked and
  scope-filtered; the query, scope, and result count are audited; fact contents in
  logs follow logging-privacy rules (no sensitive leakage). *(Security-spec
  DET-02/AZ-03.)*

---

# Chapter 10 - Manifest Additions

```yaml
memory:
  enabled: false                      # opt-in per installation
  engine: cognee                      # reference engine; swappable behind MemoryEngine
  store: postgres                     # reuse the existing Postgres instance (or point elsewhere)
  embedding_endpoint: local-vllm      # sensitive-safe default (SEC-43)
  extraction_endpoint: local-vllm     # entity/relationship extraction model
  default_owner_scope: user           # user | department | org
  cross_scope_edges: forbidden        # forbidden | governed
  ingest:
    on_session_end: true              # cognify a conversation when it closes
    incremental: true                 # process only new/changed content
    schedule: null                    # optional tz-aware cron for document corpora
    screen_content: true              # anti-poisoning screen (SEC-42)
  retrieval:
    default_mode: graph_completion    # similarity | graph_completion (multi-hop)
    max_hops: 4
    max_results: 20
  retention_days: 365
```

Existing sections are unchanged; `memory` is additive and inert when
`enabled: false`.

---

# Chapter 11 - Definition of Done (Round Five)

In addition to prior rounds' definitions of done, this round is complete when:

1. **Kernel-governed access** - memory is reachable only via `memory.*` verbs
   through the dispatch chokepoint; the engine is unreachable directly; the
   `MemoryEngine` interface keeps the kernel/models engine-agnostic (severability
   holds, verified by diff).
2. **Ingestion** - conversation transcripts and documents cognify into the graph
   incrementally and at session end as a durable workflow, with provenance, scope
   assigned at ingestion, content screening, and sensitive ingestion routed to
   local endpoints.
3. **Retrieval** - scoped recall returns only permitted-scope facts with
   provenance, supports similarity and multi-hop graph-completion modes, and
   resolves intra-conversation references via session memory; recall is
   grant-checked and audited.
4. **Learning & forgetting** - memory improves from usage/feedback without
   changing scope or granting authority; `memory.forget` performs complete,
   engine-confirmed, audited erasure that addresses both memory and linked
   transcripts for subject erasure.
5. **Isolation proven** - a hostile cross-scope test shows recall (including
   multi-hop traversal) cannot reach facts outside the requesting context's scope;
   cross-scope edges are forbidden (or governed by explicit audited policy).
6. **Site** - a scoped memory browser shows what a user is permitted to see with
   provenance; users/admins can request erasure; admins see ingestion/health and
   cost.
7. **Engine selection** - Cognee (or an evaluated equivalent) is validated against
   the selection criteria (isolation, complete erasure, self-hosting/residency,
   provenance, sensitive handling, footprint, licence, retrieval quality) and
   adopted behind the interface.
8. **Governance & cost** - SEC-40..45 are bound to tests with catalogue entries;
   `check_invariants.py` passes at binding-debt 0; ingestion cost is attributed and
   budget-bound; with memory disabled the offline suite stays green.

---

# Chapter 12 - Suggested Build Order

1. **MemoryEngine interface + engine evaluation (MEM-ENG, MEM-02)** - define the
   contract and validate Cognee against alternatives on the selection criteria
   before committing.
2. **Memory verbs + chokepoint integration (Epic MEM)** - `memory.*` verbs bound
   to the engine adapter, with grant/scope/audit; prove kernel-governed access and
   that memory cannot escalate (SEC-41).
3. **Scope model at ingestion and retrieval (SEC-40, ING-04, RCL-01)** - the
   isolation boundary first, with the hostile cross-scope test, before any real
   corpus is loaded.
4. **Cognify pipeline (Epic ING)** - the durable workflow, chat-history bridge,
   document ingestion, screening (SEC-42), and sensitive routing (SEC-43).
5. **Retrieval & reasoning (Epic RCL)** - scoped recall, multi-hop, session
   continuity, provenance in results.
6. **Forgetting & provenance (Epic LRN)** - complete erasure with the ledger,
   improve/memify, two-layer erasure.
7. **Memory in the site (Epic MUI)** - the scoped browser, management, and admin
   health/cost.

Rationale: pin the engine contract and the isolation boundary **before** loading
any data, because the failure that matters most here is cross-scope leakage
through a fused graph, and it is far cheaper to prevent at the boundary than to
remediate after a corpus exists.

---

*Memory is what turns a fleet of capable-but-forgetful agents into an organisation
that accumulates knowledge, and it is also the single largest new data-isolation
and privacy surface the platform has. This round adds the capability the way the
rest of Nankle is built: the engine is adopted, not invented; it sits behind
kernel-governed verbs; every fact is scoped and provenanced; and the kernel, never
the engine alone, is the boundary that decides who may recall what.*

> **Note (supersession):** this round supersedes Round Three Epic MEM. The Round
> Three flat `memory_items` table + `/v1/memory/query` are the seed; Round Five
> replaces them with `memory_facts` / `memory_ingestions` / `memory_erasures`, the
> `memory.*` verb surface behind the chokepoint, and the swappable `MemoryEngine`
> adapter (Cognee reference). Plan a migration from `memory_items` to
> `memory_facts` when this round is built.
