# 0008 - Memory Engine Selection (MEM-ENG-04)

Status: SUPERSEDED FOR BOLTRIG V2
Epic: MEM (Memory Engine)
Date: 2026-07-03
Gate: comparative validation + selection, before committing to any external semantic-memory engine

Superseded-by: 0011 for Boltrig v2 deployment defaults. This decision remains
the historical basis for the native/Cognee memory engines and kernel-side memory
invariants. Boltrig v2 now uses Mem0 as the primary operational memory
projection and Cognee as an optional graph/corpus projection behind the same
kernel ledger.

## 1. What this decides

Boltrig's memory subsystem is deliberately engine-agnostic: the engine is a
configuration choice behind one interface, never a code dependency of the kernel
(`boltrig/memory/__init__.py:20-25`, `boltrig/memory/engine.py:1-10`). This gate
answers a narrower question: of the current field of semantic-memory engines
(Cognee, Mem0, Zep / Graphiti, LightRAG) versus the engine Boltrig already ships
natively (Postgres + pgvector), which should be the DEFAULT production engine, and
which (if any) new external engine is worth adopting.

The honest answer, grounded in the code below, is: **keep the native
`PgVectorMemoryEngine` as the default production engine, and retain the
already-built `CogneeEngine` as the optional, flag-on graph upgrade. Do not adopt
Mem0, Zep / Graphiti, or LightRAG.** Reasoning follows.

## 2. Boltrig's actual memory contract (read from the code)

The requirements are not aspirational: they are already expressed as a Protocol and
enforced at the kernel boundary. Any engine is measured against these, not against
a feature list.

1. **The engine is subordinate to the kernel boundary.** `MemoryAdapter`
   (`boltrig/memory/adapter.py`) fronts whichever engine is configured and IS the
   isolation boundary. Every `memory.*` verb runs the unchanged dispatch chokepoint
   (grant check + audit + schema validation) and then the memory-specific controls
   the *kernel*, not the engine, owns. The engine's own isolation is explicitly
   "defence-in-depth, never the sole boundary" (`engine.py:6-9`,
   `adapter.py:9-13`). This single fact reshapes the whole comparison: an engine's
   built-in tenancy / ACL machinery is redundant to a rail the kernel already holds.

2. **Scoped recall (SEC-40).** Recall and forget MUST honour the `scopes` list the
   kernel passes; the adapter re-filters returned facts to permitted scopes even if
   the engine returns broader (`adapter.py:238-249`). Owner-scope is checked at
   ingestion too (`adapter.py:178-181`). Scopes are `user:<id> | department:<name>
   | org` (`engine.py:26`), resolved fail-closed to the caller's own user scope plus
   org (`adapter.py:66-75`).

3. **Cross-scope edge policy.** Edges leaving the caller's permitted scopes are
   dropped at ingestion when `cross_scope_edges: forbidden` (the manifest default,
   `manifest.example.yaml:311`, `adapter.py:208-215`). Graph traversal is
   scope-bounded by construction: `graph_completion` BFS never follows an
   out-of-scope neighbour (`pgvector.py:168-173,206-208`; `vector.py:85-101`).

4. **Provenance.** Every fact carries `source_kind` / `source_ref`; every
   `RecallHit` carries match `score`, `hops`, and the traversal `path`
   (`engine.py:34-42`). The DURABLE governance ledger is the kernel store's
   `memory_facts` table, written by the adapter on every remember
   (`adapter.py:223-227`) - not the engine. The engine's own index is a cache.

5. **Erasure / right-to-be-forgotten (SEC-44).** `forget` must remove the node AND
   its derived edges/facts and return the ids actually removed, for *verifiable,
   complete* erasure; every erasure is ledgered to `memory_erasure` and audited
   (`engine.py:77-88`, `adapter.py:262-283`). Scope-bounded: a caller may only erase
   within its scopes.

6. **Reweight-only improve (SEC-41 / [2026] VJS-COUNTY 5).** `improve` reweights a
   fact's recall boost from a feedback signal and "must never change a fact's scope
   or grant any authority" (`engine.py:72-74`). The delta is a simple +/-1
   (`engine.py:45-48`). Self-improvement never widens authority: the engine adjusts
   a scoring weight, nothing else.

7. **Deployment constraint: ONE Postgres with pgvector.** `docker-compose.yml:36-50`
   runs `pgvector/pgvector:pg16` as the single durable store. The native engine
   keeps its vectors + edges in engine-owned tables (`memory_vectors`,
   `memory_vector_edges`) in that same Postgres, explicitly "no separate vector
   database" (`pgvector.py:1-21,39-63`). This is a consolidation rail, not a
   convenience (memory MEMORY.md `consolidation-over-fragmentation`).

8. **Air-gapped / local-only posture for sensitive data (SEC-43).** Sensitive
   memory MUST use a local endpoint; a misroute is blocked + audited
   (`adapter.py:202-207`). Embedding + extraction default to `local-sensitive`
   (`manifest.example.yaml:307-309`). The `ModelEmbedder` seam points at a local
   OpenAI-compatible endpoint and never follows redirects
   (`embeddings.py:92-142`). Secrets are refused at ingestion before they can reach
   ANY engine (`adapter.py:191-200`, and a second net in `cognee.py:139-148`).

9. **Severability.** The memory package imports only `boltrig.models`,
   `boltrig.adapters.base`, and the pgvector DSN helper; heavy backends are
   lazy-imported so `import boltrig.memory` stays offline-safe
   (`__init__.py:20-25`). Any adopted engine MUST preserve this: optional extra,
   lazy import, offline suite green without it. Cognee already does
   (`pyproject.toml:27-29`, `cognee.py:86-94`); the offline default is `local`
   (`manifest.example.yaml:305`, `bootstrap.py:94-118`).

The load-bearing consequence: **because the kernel owns scoping, provenance, and
erasure, the engine's job is narrow - store facts + edges, rank recall, support a
weight sidecar.** The native pgvector engine already does all of this, in the one
Postgres, offline-capable, air-gap-safe. That is the baseline every external engine
has to beat.

## 3. Comparison: engine x requirement

Verdicts are honest and specific. "Kernel-owned" means the requirement is satisfied
by the adapter regardless of engine, so the engine only needs to not fight it.

| Requirement | Native pgvector (shipped) | Cognee (built, flag-on) | Mem0 | Zep / Graphiti | LightRAG |
|---|---|---|---|---|---|
| **Scoped recall (SEC-40)** | Structural: `owner_scope = ANY($scopes)` in SQL, out-of-scope rows never read (`pgvector.py:137-141`). Kernel re-checks anyway. | (tenant, scope) -> one injective dataset; only requested datasets addressed (`cognee.py:73-76,185-197`). Kernel re-checks. | `user_id` / `agent_id` / `run_id` partitions [M1]. Would map to scope; kernel re-checks. | `group_id` partitions [Z1]. Kernel re-checks. | `workspace` isolation [L1]. Kernel re-checks. |
| **Cross-scope edges** | Edges loaded only if BOTH endpoints in scope; hostile multi-hop is structurally unfollowable (`pgvector.py:168-173`). | Engine's explicit `relates_to` edges traversed within scope; cognee's own graph not used for the RecallHit contract (see note). | No native scope-bounded edge traversal; graph memory needs Neo4j/Kuzu/Memgraph [M2]. Kernel would police it. | Temporal graph edges; scope enforced by `group_id`, not by an edge-endpoint rule. Kernel would police it. | AGE / Neo4j graph edges; no scope-bounded traversal primitive matching the contract. |
| **Provenance (source_ref, hops, path)** | Stored durably in-engine + in kernel ledger; RecallHit carries hops+path (`pgvector.py:195-209`). | Content durable in cognee; id/edge/provenance mapping is PER-PROCESS session cache - honest degradation, already documented (`cognee.py:26-29`). Kernel `memory_facts` is the durable ledger. | Returns memories with metadata; no hops/path graph-traversal provenance in the RecallHit shape. Kernel ledger still authoritative. | Rich temporal provenance (fact validity windows) [Z2], but shape != RecallHit; needs an adapter shim. | doc-id + entity provenance; no hops/path in contract shape. |
| **Erasure (SEC-44, complete + ledgered)** | Real SQL deletes + derived-edge pruning in one txn (`pgvector.py:225-292`). Kernel ledgers to `memory_erasure`. | REAL erasure: drop affected dataset + rebuild from survivors (`cognee.py:247-304`). | `delete` / `delete_all` by id / user_id [M1]. Real deletes. | **Concern:** temporal model INVALIDATES facts, does not delete them by default [Z2] - "old facts are invalidated, not deleted". Hard-delete for right-to-be-forgotten needs extra work. | `delete_by_doc_id` removes doc + associated entities [L2]; entity-level erasure across a shared graph is coarser. |
| **Reweight-only improve (SEC-41)** | Weight sidecar column; `weight = weight + delta`, scope untouched (`pgvector.py:211-223`). | No per-item reweight primitive; uses the SAME engine-level weight sidecar as the natives (`cognee.py:235-245`). | `update` mutates memory CONTENT via an LLM decision loop [M1] - that is more than a reweight; the pure-reweight rail would have to be re-imposed by us. | Temporal fact management, not a per-item feedback reweight. Same: we would re-impose the sidecar. | No feedback-reweight primitive. Same. |
| **Graph vs pure-vector - does it earn the complexity?** | Explicit-edge graph + vector recall in one engine, edges author-supplied (`relates_to`). Already a graph engine for the contract. | Adds LLM entity/relationship EXTRACTION (auto edges) + ontology. But its own GRAPH_COMPLETION returns LLM prose, not fact nodes, so the contract falls back to CHUNKS search + the engine's explicit edges anyway (`cognee.py:30-37,185-233`). Extraction is the real added value, not traversal. | Vector-first; graph memory is an add-on backend. | Graph-FIRST temporal engine - genuinely more capable graph, but see deployment. | Graph-RAG dual-level retrieval; genuinely graph-capable. |
| **Deployment fit (single Postgres + pgvector)** | PERFECT: lives in the existing Postgres, no new service (`pgvector.py:1-21`, `docker-compose.yml:36-50`). | Fits with effort: cognee is provider/store-agnostic and CAN target pgvector + relational, but its default graph store (networkx / Kuzu) and full dependency tree add weight; runs in-process, no mandatory new service. | Vector store CAN be pgvector [M1], BUT graph memory forces Neo4j / Kuzu / Memgraph [M2] - a NEW datastore. Server mode adds a service. | **Forces a new datastore + service:** requires Neo4j / FalkorDB / Kuzu / Neptune [Z3]; will NOT run on pgvector alone. Zep Community Edition is DEPRECATED [Z4], so self-hosting means operating Graphiti + a graph DB yourself. | Postgres "one-stop" is possible (KV + pgvector + Apache AGE) [L3], but AGE is a SEPARATE extension not in the `pgvector/pgvector` image - a new extension/image to operate. |
| **Licensing** | N/A (our code). | Apache 2.0 [C1]. | Apache 2.0 [M3]. | Graphiti core Apache 2.0 [Z5]; Zep platform is a hosted product. | MIT (HKUDS, EMNLP2025) [L4]. |
| **Maturity / operational burden** | Lowest burden: it is Boltrig code + one Postgres. | Mature OSS memory platform [C2]; adds a large dependency + LLM-driven cognify pipeline to operate. | Very popular (60k+ stars) [M4]; running graph memory adds a graph DB to operate. | Enterprise-grade but self-host path is heavier (graph DB + schema migrations) [Z3]. | Lightweight framework; multi-backend config surface to manage. |
| **Data residency / air-gap (SEC-43)** | Fully local: vectors computed via local `ModelEmbedder` endpoint or offline `HashingEmbedder`; nothing leaves the box (`embeddings.py:92-142`). | Provider-agnostic; local LLM/embedding endpoints supported (`cognee.py:43-52`), fastembed keyless local embeddings. Air-gap-capable. | Self-hostable, but ADD/UPDATE decisions and extraction assume an LLM; local-model config needed for air-gap. | Self-hostable; extraction is LLM-driven; graph DB adds a component to keep on-box. | Self-hostable; LLM extraction; local endpoints configurable. |

Sources: [C*] Cognee, [M*] Mem0, [Z*] Zep/Graphiti, [L*] LightRAG - see Section 8.

## 4. Recommendation

**Default production engine: keep the native `PgVectorMemoryEngine`. Retain the
already-built `CogneeEngine` as an optional, flag-on upgrade. Adopt no new external
engine (reject Mem0, Zep / Graphiti, LightRAG).**

Why the native engine wins the default slot:

- It is the ONLY engine that satisfies the single-Postgres deployment rail with zero
  new datastore or service - it already lives in `pgvector/pgvector:pg16`
  (`pgvector.py:1-21`). Every other engine either forces a graph DB (Zep/Graphiti,
  and Mem0's graph mode), forces a new Postgres extension (LightRAG's AGE), or adds
  a heavy dependency tree (Cognee).
- The kernel, not the engine, owns the hard requirements - scoped recall,
  provenance ledger, complete ledgered erasure, reweight-only improve
  (`adapter.py` throughout). The native engine implements the narrow remainder
  (store, rank, sidecar) cleanly and STRUCTURALLY: scope isolation and cross-scope
  edge safety are enforced in SQL by construction, which is the strongest possible
  form of "does not cheat" (`pgvector.py:137-173`). An external engine's built-in
  tenancy is redundant to a rail we already hold, so it buys little and costs a
  datastore.
- It is air-gap-native (SEC-43): local embedder, nothing egresses
  (`embeddings.py:92-142`). The external engines all lean on LLM extraction and, for
  air-gap, need local-model wiring - achievable, but strictly more to get wrong.
- Erasure is a real SQL delete, verifiable and complete (`pgvector.py:225-292`).
  Notably, **Zep / Graphiti's temporal model invalidates rather than deletes facts
  by default** [Z2], which is an active liability against Boltrig's ledgered
  right-to-be-forgotten (SEC-44) - a point AGAINST adopting it, not for.

Why Cognee stays as the flag-on option (and is NOT displaced):

- It is already ADOPTED, built, tested, gated, and severable
  (`cognee.py`, `pyproject.toml:27-29`, `bootstrap.py:95-99`,
  `tests/integration/test_cognee_engine.py`). It costs nothing to keep and gives
  deployments that genuinely want automatic LLM entity/relationship EXTRACTION +
  ontology a supported path, Apache-2.0 and self-hostable [C1], provider-agnostic so
  sensitive data uses a local endpoint (`cognee.py:43-52`).
- But note the honest ceiling already documented in the engine: cognee's own
  GRAPH_COMPLETION returns LLM prose, not fact nodes, so the RecallHit contract
  falls back to CHUNKS search plus OUR explicit edges (`cognee.py:30-37`), and its
  provenance/improve are the same in-process sidecar the natives use
  (`cognee.py:26-29,235-245`). So Cognee's real added value is extraction, not the
  graph traversal or the reweight - which is exactly the slice a deployment should
  opt into deliberately, not by default.

Why the three new candidates are rejected:

- **Zep / Graphiti** - forces a new graph datastore (Neo4j / FalkorDB / Kuzu /
  Neptune) [Z3], the Community Edition is deprecated [Z4], and its temporal model
  invalidates rather than hard-deletes [Z2], which fights SEC-44. Highest cost,
  worst deployment fit, an erasure semantics mismatch. No.
- **Mem0** - permissive (Apache 2.0) [M3] and pgvector-capable for the vector
  store [M1], but its differentiator (graph memory + LLM ADD/UPDATE/DELETE decision
  loop) both forces a graph DB [M2] and mutates memory content beyond a reweight
  [M1], which we would have to fence back to the SEC-41 reweight-only rail. It adds
  a datastore and a rail we would have to re-impose, for capability the kernel
  already brackets. No.
- **LightRAG** - MIT [L4] and the closest deployment fit (Postgres one-stop via
  pgvector + Apache AGE) [L3], but AGE is a separate extension outside the current
  image, entity-level erasure across a shared graph is coarser than our per-fact
  ledgered delete [L2], and it brings no capability the native engine + optional
  Cognee do not already cover. Not worth a second graph substrate. No.

Net: adopting any of the three would trade Boltrig's single-Postgres, air-gap-native,
structurally-isolated baseline for a new datastore and redundant machinery, with no
requirement it uniquely satisfies. That is a consolidation regression
(MEMORY.md `consolidation-over-fragmentation`), so the gate closes on the native
engine.

## 5. If an external engine WERE adopted - the concrete flip requirements

Recorded so a future adoption is a config flip, not a rebuild. The seam already
exists; this is what each engine would need.

Common to any engine (the existing seam):
- Selection is by manifest `memory.engine` (`manifest.example.yaml:305`), dispatched
  in `bootstrap.py:94-118` (`local | vector | pgvector | cognee` today). A new
  engine adds one `elif` branch there plus a class implementing the `MemoryEngine`
  Protocol (`engine.py:51-92`).
- It MUST be an optional extra in `pyproject.toml:21-29` and lazy-imported inside
  methods (like `cognee.py:86-94`) so `import boltrig.memory` stays offline-safe and
  the offline suite stays green without it (`__init__.py:20-25`).
- It MUST honour `scopes` on recall/forget and support an engine-level weight
  sidecar for `improve` (no external engine has a native reweight-only primitive;
  the natives and Cognee all use the same sidecar).

Cognee (already built - this is the LIVE example of the pattern):
- Package: `pip install 'boltrig[cognee]'` (`cognee>=1.2`, `pyproject.toml:29`).
- Config: `memory.engine: cognee` plus `llm` / `embedding` blocks mapped to cognee's
  env (`LLM_PROVIDER/MODEL/ENDPOINT/API_KEY`, `EMBEDDING_*`) and `cognee_root`
  (`cognee.py:43-53,111-127`). For air-gap, point both at a local endpoint / use
  `fastembed`.
- Datastore/service: runs in-process; default graph store is networkx / Kuzu on
  disk under `cognee_root`. No mandatory new network service, but a real dependency
  footprint.
- **Existing gating (the BOLTRIG_COGNEE_LIVE-style rail already present):** live
  cognee legs are gated by `BOLTRIG_COGNEE_LIVE=1` AND the package installed AND LLM
  env set (`tests/integration/test_cognee_engine.py:39-46`); without them the
  always-run tests assert honest degradation - `health()` returns `down` /
  `degraded` with a reason and operations raise a typed error
  (`cognee.py:306-324`). Any new engine should copy this exact three-part gate.

Mem0 (hypothetical): extra `mem0 = ["mem0ai>=..."]`; `memory.engine: mem0`; vector
store configured to the existing pgvector DSN; would NEED a graph DB (Neo4j / Kuzu)
only if graph memory is used - prefer vector-only to preserve single-Postgres; must
fence `update` back to reweight-only.

Zep / Graphiti (hypothetical): extra `graphiti = ["graphiti-core>=..."]`;
`memory.engine: graphiti`; REQUIRES a new graph service (Neo4j / FalkorDB) in
`docker-compose.yml` - this is the blocker; plus a `forget` shim that HARD-deletes
rather than invalidates, to meet SEC-44.

LightRAG (hypothetical): extra `lightrag = ["lightrag-hku>=..."]`;
`memory.engine: lightrag`; add the Apache AGE extension to the Postgres image (new
image or init), configure Postgres KV + pgvector + AGE; map `delete_by_doc_id` onto
scope-bounded `forget`.

## 6. Open risks

- **Native engine embedding quality.** The offline default `HashingEmbedder` is
  lexical, not semantic (`embeddings.py:1-16,58-89`). Production recall quality
  depends on wiring a real local `ModelEmbedder` (SEC-43). Risk: if no model
  embedder is configured, "semantic" recall degrades to lexical overlap silently.
  Mitigation is config, not code, but should be a deployment checklist item.
- **Graph value left on the table.** The native engine's edges are author-supplied
  (`relates_to`), not auto-extracted. If a deployment's value depends on
  discovering relationships from unstructured corpora, the native engine will not
  surface them and Cognee's extraction becomes the reason to flip. This gate does
  not close that door - it keeps Cognee ready.
- **Cognee provenance is a per-process cache** (`cognee.py:26-29`). Acceptable
  because the kernel ledger is authoritative, but a multi-process cognee deployment
  loses the in-instance id/edge/weight map on restart. A follow-on would need to
  persist that sidecar if Cognee ever became the default.
- **Field moves fast.** The 2026 OSS memory landscape is active; this verdict is
  as-of 2026-07-03 and should be revisited if the single-Postgres constraint is ever
  relaxed by a separate decision.

## 7. Follow-on spike (to confirm, only if a flip is contemplated)

A spike is NOT needed to keep the native engine (it is already the shipped, tested
baseline). A spike WOULD be needed before flipping the default to Cognee or adopting
any external engine, and would need to confirm:

1. Recall quality delta on a representative Boltrig corpus: native pgvector +
   real local `ModelEmbedder` vs Cognee extraction, on the SAME facts, measuring
   whether auto-extracted edges beat author-supplied `relates_to` for the actual
   `graph_completion` queries agents issue.
2. Erasure completeness under the candidate engine on a live store (a recall after
   forget must return nothing from any layer - the property `pgvector.py:225-292`
   and `cognee.py:247-304` already assert), with special scrutiny of any engine that
   invalidates rather than deletes (Zep/Graphiti).
3. Air-gap proof: the engine performs a full remember -> cognify -> recall -> forget
   cycle with NO network egress (local LLM + local embeddings), audited.
4. Operational cost: what new container(s) / extension(s) the engine adds to
   `docker-compose.yml` and the backup/restore story for them.

## 8. Sources

Boltrig code read for the requirements (all paths relative to repo root):
`boltrig/memory/__init__.py`, `boltrig/memory/engine.py`,
`boltrig/memory/adapter.py`, `boltrig/memory/local.py`, `boltrig/memory/vector.py`,
`boltrig/memory/pgvector.py`, `boltrig/memory/cognee.py`,
`boltrig/memory/embeddings.py`, `boltrig/api/bootstrap.py` (lines 84-121),
`manifest.example.yaml` (memory block, lines 303-321), `docker-compose.yml`
(postgres service, lines 36-50), `pyproject.toml` (lines 21-29),
`tests/integration/test_cognee_engine.py` (gating, lines 39-46).

External engine facts (as-of 2026-07-03):
- [C1][C2] Cognee - Apache 2.0, self-hostable, native tenant/user isolation,
  provider-agnostic, hybrid graph+vector:
  https://github.com/topoteretes/cognee ,
  https://www.cognee.ai/ ,
  https://tryxlr8.ai/blogs/best-open-source-ai-memory-frameworks-2026
- [M1][M2][M3][M4] Mem0 - Apache 2.0, user_id/agent_id/run_id partitions, pgvector
  supported (graph memory needs Neo4j/Kuzu/Memgraph), delete/update API:
  https://github.com/mem0ai/mem0 ,
  https://docs.mem0.ai/open-source/overview ,
  https://mem0.ai/blog/graph-memory-solutions-ai-agents
- [Z1][Z2][Z3][Z4][Z5] Zep / Graphiti - Graphiti core Apache 2.0, requires
  Neo4j/FalkorDB/Kuzu/Neptune, temporal facts are invalidated not deleted, Zep
  Community Edition deprecated:
  https://github.com/getzep/graphiti ,
  https://help.getzep.com/graphiti/getting-started/welcome ,
  https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/ ,
  https://callsphere.ai/blog/vw3g-zep-memory-v2-temporal-knowledge-graph-graphiti-2026
- [L1][L2][L3][L4] LightRAG - MIT (HKUDS, EMNLP2025), Postgres one-stop via
  pgvector + Apache AGE, delete_by_doc_id, workspace isolation:
  https://github.com/hkuds/lightrag ,
  https://github.com/HKUDS/LightRAG/issues/661 ,
  https://pypi.org/project/lightrag-hku/

Governing precedent / rails: SEC-40..45 (memory isolation, residency, erasure,
least-privilege audit) as implemented in `boltrig/memory/adapter.py`; [2026]
VJS-COUNTY 5 (self-improvement never widens authority) as implemented by the
reweight-only `improve` / `signal_delta`; the consolidation-over-fragmentation
steering principle (single Postgres, no new datastore without demonstrated need).
