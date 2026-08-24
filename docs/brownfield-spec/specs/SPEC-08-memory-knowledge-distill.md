---
area: 08 Memory planes, the Knowledge extension, and distillation
id-block: BT-REQ-0800..BT-REQ-0899
referent commit: 19bcae7fa81663fe8998377c86451ba08fb16e48 (origin/main)
author-agent: brownfield-spec author, area 08
date: 2026-08-24
---

## Bound of this reading

Read exhaustively (every line, in the pinned tree): all 29 files of
`boltrig/memory/`, all 15 of `boltrig/knowledge/`, all 11 of `boltrig/distill/`,
all four of `services/distill_sidecar/`, `scripts/distill_corpus_dump.py`, and
decisions 0007, 0008, 0011, 0015, 0023-sleep-distillation, 0029.

Read in full where they carry this area's contract: `migrations/versions/0076_typed_memory_ledger.py`,
`migrations/versions/0034_knowledge_fabric.py`, `boltrig/models/memory.py`,
`boltrig/kernel/memory_read_routes.py`, `boltrig/kernel/memory_mutation_routes.py`,
`boltrig/kernel/platform_routes/knowledge.py`, `boltrig/fleet/reflection.py`,
`boltrig/fleet/chat_compaction.py`, `boltrig/fleet/continuity.py` (compaction half only),
`libraries/skills/knowledge/retrieval.yaml`,
`libraries/workflows/sleep-distillation-craft.yaml`, and the memory/knowledge/distill
sections of `manifest.example.yaml`, `boltrig/store/rls.sql`, `tests/invariants.yaml`.

Sampled, not read exhaustively: `boltrig/store/postgres.py` and `boltrig/store/memory.py`
(only the memory-fact, memory-event, memory-projection and audit-query methods),
`boltrig/store/schema.sql` (only the memory and knowledge table blocks),
`boltrig/kernel/dispatch.py` (only the adapter-exception path),
`boltrig/identity/rbac.py` and `boltrig/identity/ai_keys.py` (only the scope and
key-resolution functions this area calls), `apps/worker/src/components/MemorySurface.tsx`
(only the review submission path). Anything not listed here is not a claim in this file.

Not read at all, and therefore not claimed on: the Cognee package itself, mlx-lm,
`docs/proposals/codex-native-knowledge-extension.md` beyond its existence, and any
deployed stack.

## 2. Purpose

This subsystem is Boltrig's durable knowing: a governed memory ledger with three
writable typed planes behind a deterministic write gate, a canonical Knowledge
catalogue that stores immutable original bytes in an ObjectVault and every derived
passage as a citable segment in Postgres/pgvector, and a nightly sleep-distillation
loop that turns the governed record into a LoRA candidate and refuses to promote it
without a mechanical gate. Every operation crosses the kernel dispatcher as a
`memory.*`, `knowledge.*` or `distill.*` verb, so grants, HITL, audit and schema
validation apply unchanged. External engines (Cognee) and external weights (a promoted
adapter) are projections of the ledger, never authorities over it.

## 3. Boundaries

**Owns.** The `memory.*` verb surface and its ledger tables (`memory_facts`,
`memory_events`, `memory_ingestions`, `memory_erasures`, `memory_projection_statuses`,
`memory_vectors`, `memory_vector_edges`); the four memory engines; the typed write gate
and bundle; the memory projection fanout; the whole `knowledge_*` table family, the two
ObjectVault implementations, extraction, and the Cognee compile/erase projection; the
distillation corpus derivation, the promotion gates, and the trainer sidecar contract.

**Must not touch.** The kernel core never imports this package: severability is stated
at [`boltrig/memory/__init__.py:20`](../../../boltrig/memory/__init__.py) `"Severability (MEM-ENG-02): this package imports only"`
and the distill package repeats it at
[`boltrig/distill/__init__.py:5`](../../../boltrig/distill/__init__.py) `"may import from here - the kernel's one distillation surface"`.
Heavy backends are lazy-imported inside methods so `import boltrig.memory` stays
offline-safe ([`boltrig/memory/cognee.py:7`](../../../boltrig/memory/cognee.py) `"lazy-imports inside methods so the rest of Boltrig is import-safe"`).

**Forbidden by rule.** A memory backend is never an authority boundary
(decision 0011 §"Rules" 1, [`docs/decisions/0011-boltrig-v2-memory-topology.md:45`](../../../docs/decisions/0011-boltrig-v2-memory-topology.md) `"One source of truth."`).
Cognee is a rebuildable compiler, not the policy holder
([`docs/decisions/0029-typed-memory-planes.md:23`](../../../docs/decisions/0029-typed-memory-planes.md) `"rebuildable projection/compiler - not the policy holder."`).
Working state is never memory ([`boltrig/memory/typology.py:13`](../../../boltrig/memory/typology.py) `"working state is NEVER memory"`).
Facts never enter LoRA weights ([`docs/decisions/0023-sleep-distillation-and-the-adapter-seam.md:149`](../../../docs/decisions/0023-sleep-distillation-and-the-adapter-seam.md) `"Facts never enter the weights."`).

**Registration.** All three subsystems are composed from manifest sections rather than
the `adapters:` module_ref list, because each needs the store, the audit writer, or the
cost accountant: [`boltrig/api/bootstrap.py:281`](../../../boltrig/api/bootstrap.py) `"await _register_memory(kernel, manifest.tenant_id"`,
`:282` `"await register_knowledge(kernel, manifest.tenant_id"`, `:283` `"await register_distill(kernel, manifest.tenant_id"`.

## 4. Objects and contracts

### 4.1 The five planes (decision 0029)

Five planes are named; three are writable through the gate
([`boltrig/memory/typology.py:25`](../../../boltrig/memory/typology.py) `"SEMANTIC = \"semantic\""`,
`:28` `"WRITABLE_PLANES = frozenset({SEMANTIC, EPISODIC, PROCEDURAL})"`).

| plane | question | lifecycle | slot key | retrieval |
| --- | --- | --- | --- | --- |
| semantic | what is true now | one active value per slot, supersession with retained history | `{subject_type}::{subject_id}::{predicate}::{owner_scope}` ([`boltrig/memory/typology.py:54`](../../../boltrig/memory/typology.py) `"def semantic_memory_key"`) | keyed, by subject |
| episodic | what happened | append-only, no key, terminal runs only | none ([`boltrig/memory/write_gate_planes.py:56`](../../../boltrig/memory/write_gate_planes.py) `"unset, no supersession path."`) | similarity over `retrieval_text` |
| procedural | how must I act | versioned, activated only by review | `procedure::{procedure_key}::{owner_scope}` ([`boltrig/memory/typology.py:66`](../../../boltrig/memory/typology.py) `"def procedure_memory_key"`) | deterministic role/workflow ranking |
| source knowledge | what does the record say | the Knowledge catalogue (section 4.4) | asset/revision/segment ids | lexical + vector |
| working state | what is in flight | never persisted, pass-through only | none | caller-supplied |

`memory.propose` refuses anything outside the writable three
([`boltrig/memory/typed_verbs.py:65`](../../../boltrig/memory/typed_verbs.py) `"plane must be one of {sorted(WRITABLE_PLANES)}; source and working"`).

### 4.2 `MemoryFact` and `MemoryEvent`

`MemoryFact` carries the pre-0029 governance columns plus the typed columns, all
nullable so legacy rows stay first-class
([`boltrig/models/memory.py:41`](../../../boltrig/models/memory.py) `"memory_key: str | None = None"`,
`:42` `"status: str = \"active\"  # candidate | active | superseded | rejected"`,
`:48` `"supersedes_id: str | None = None"`). `content` is only a 200-character label; the
engine holds the body ([`boltrig/models/memory.py:31`](../../../boltrig/models/memory.py) `"a short human-readable label (the engine holds the rest)"`),
truncated at write time ([`boltrig/memory/adapter_writes.py:162`](../../../boltrig/memory/adapter_writes.py) `"content=fact.content[:200]"`).

`MemoryEvent` is the append-only gate-decision trail. It records what the gate decided
and under which policy version, never the memory content
([`boltrig/models/memory.py:56`](../../../boltrig/models/memory.py) `"Events record WHAT the gate decided"`;
policy version pinned at [`boltrig/memory/write_gate.py:51`](../../../boltrig/memory/write_gate.py) `"POLICY_VERSION = \"typed-write-v1\""`).
Six event kinds are enumerated in the DB CHECK constraint
([`migrations/versions/0076_typed_memory_ledger.py:60`](../../../migrations/versions/0076_typed_memory_ledger.py) `"event          TEXT NOT NULL CHECK (event IN ("`).

### 4.3 The decision vocabulary

Ten decision codes are defined
([`boltrig/memory/typology.py:86`](../../../boltrig/memory/typology.py) `"ACCEPT_NEW = \"ACCEPT_NEW\""` through `:95` `"REQUEST_HUMAN_REVIEW"`),
partitioned into `ACCEPTED_DECISIONS` (accept / confirm / supersede) and
`REJECTED_DECISIONS` ([`boltrig/memory/typology.py:97`](../../../boltrig/memory/typology.py) `"ACCEPTED_DECISIONS = frozenset({ACCEPT_NEW, CONFIRM_EXISTING, SUPERSEDE_EXISTING})"`).
`REQUEST_HUMAN_REVIEW` sits in neither set: it is the parked-candidate outcome, which is
why `_propose` treats it as persisted-but-not-committed
([`boltrig/memory/typed_verbs.py:78`](../../../boltrig/memory/typed_verbs.py) `"if outcome.decision not in ACCEPTED_DECISIONS or outcome.fact is None"`).

Supporting registries, all closed and deterministic:

- subject types: six ([`boltrig/memory/typology.py:31`](../../../boltrig/memory/typology.py) `"SUBJECT_TYPES = frozenset({\"repository\", \"project\""`);
- predicates: a per-subject-type frozenset with an `other` escape in each
  ([`boltrig/memory/typology.py:33`](../../../boltrig/memory/typology.py) `"PREDICATES: dict[str, frozenset[str]] = {"`);
- source authority: five ranks 5..1, defaulting to `unverified_inference`
  ([`boltrig/memory/typology.py:71`](../../../boltrig/memory/typology.py) `"SOURCE_AUTHORITY: dict[str, int] = {"`);
- transient markers: thirteen literal phrases
  ([`boltrig/memory/typology.py:114`](../../../boltrig/memory/typology.py) `"TRANSIENT_MARKERS: tuple[str, ...] = ("`);
- confidence floors: 0.75 auto-accept, 0.50 review floor
  ([`boltrig/memory/typology.py:130`](../../../boltrig/memory/typology.py) `"CONFIDENCE_ACCEPT = 0.75"`);
- episode outcomes: four ([`boltrig/memory/typology.py:133`](../../../boltrig/memory/typology.py) `"EPISODE_OUTCOMES = frozenset({\"succeeded\", \"partially_succeeded\""`).

### 4.4 The Knowledge canonical hierarchy

Nine frozen dataclasses model decision 0015's hierarchy
([`boltrig/knowledge/models.py`](../../../boltrig/knowledge/models.py)):
`UploadSession` (begun / staged / committed) -> `Blob` (content-addressed by sha256) ->
`Asset` -> `Revision` (`version`, `blob_digest`) -> `Representation` (kind, format,
generator, generator_version, content_hash) -> `SourceOccurrence` (external_id,
external_path) -> `Segment` (sequence, text, `locator`, `content_hash`) -> `Embedding`
(model provider/name/version, dimensions, distance_metric, vector). `IngestionBundle`
is the single transactional unit ([`boltrig/knowledge/models.py:137`](../../../boltrig/knowledge/models.py) `"class IngestionBundle"`).

`SearchHit.public()` attaches a citation object to every result carrying asset_id,
revision_id, segment_id, locator, source_kind, source_ref and content_hash
([`boltrig/knowledge/models.py:162`](../../../boltrig/knowledge/models.py) `"def public(self) -> dict[str, Any]:"` and `:164` `"\"citation\": {"`).
That is the mechanism behind the README's "every result carries an immutable revision and
segment citation": it is true, and it is a dataclass method, not a convention.

Segment and representation ids are content-derived and therefore stable across rebuilds
([`boltrig/knowledge/service_public.py:11`](../../../boltrig/knowledge/service_public.py) `"def stable_id(prefix: str, *parts: str)"`,
used at [`boltrig/knowledge/service.py:219`](../../../boltrig/knowledge/service.py) `"id=stable_id(\"seg\", revision.id, str(sequence), content_hash)"`).

### 4.5 Ports

`ObjectVault` is a four-method Protocol: `stage`, `commit`, `read`, `erase`
([`boltrig/knowledge/ports.py:36`](../../../boltrig/knowledge/ports.py) `"class ObjectVault(Protocol):"`).
`KnowledgeRepository` is a sixteen-method Protocol covering uploads, ingestion, reads,
search, erasure and providers ([`boltrig/knowledge/ports.py:46`](../../../boltrig/knowledge/ports.py) `"class KnowledgeRepository(Protocol):"`).
Two vault implementations and two repository implementations satisfy them:
`FilesystemObjectVault` / `S3ObjectVault`, `InMemoryKnowledgeRepository` /
`PostgresKnowledgeRepository`.

`MemoryEngine` is a five-method Protocol: `remember`, `recall`, `improve`, `forget`,
`health` ([`boltrig/memory/engine.py:52`](../../../boltrig/memory/engine.py) `"class MemoryEngine(Protocol):"`),
with `EngineFact` and `RecallHit` as its data ([`boltrig/memory/engine.py:19`](../../../boltrig/memory/engine.py) `"class EngineFact:"`,
`:35` `"class RecallHit:"`). The interface contract requires the engine to honour the
scopes the kernel passes and states that the engine's own isolation is defence in depth,
never the sole boundary ([`boltrig/memory/engine.py:9`](../../../boltrig/memory/engine.py) `"never the sole boundary (SEC-40)"`).

### 4.6 The corpus objects

`SftRecord` and `PrefRecord` are the two supervision shapes, and `Corpus` binds them to a
base pin, a held-out split, an erasure watermark and a digest
([`boltrig/distill/corpus.py:64`](../../../boltrig/distill/corpus.py) `"class SftRecord:"`,
`:78` `"class PrefRecord:"`, `:92` `"class Corpus:"`). `Corpus.signal_counts` is the
composition receipt ([`boltrig/distill/corpus.py:107`](../../../boltrig/distill/corpus.py) `"def signal_counts(self) -> dict[str, int]:"`).
`GateVerdict` carries promote/reason/scores plus both diversity measurements
([`boltrig/distill/gate.py:32`](../../../boltrig/distill/gate.py) `"class GateVerdict:"`).

## 5. Control flow

### 5.1 `memory.propose` (the typed write path)

1. Adapter dispatch resolves the verb
   ([`boltrig/memory/adapter.py:105`](../../../boltrig/memory/adapter.py) `"if verb == \"memory.propose\""`).
   **Failure branch:** an unknown verb returns `ErrorClass.INVALID` ([`boltrig/memory/adapter.py:113`](../../../boltrig/memory/adapter.py) `"return Result.failure(AdapterError(ErrorClass.INVALID,"`).
2. Plane check against `WRITABLE_PLANES`
   ([`boltrig/memory/typed_verbs.py:61`](../../../boltrig/memory/typed_verbs.py) `"if plane not in WRITABLE_PLANES:"`).
   **Failure:** `Result.failure(INVALID)`, no ledger row.
3. Owner-scope check: the requested scope must be in the caller's permitted scopes
   ([`boltrig/memory/typed_verbs.py:71`](../../../boltrig/memory/typed_verbs.py) `"raise GrantMissing(f\"cannot write memory to scope {owner_scope}\")"`).
   **Failure:** `GrantMissing` propagates out of the adapter (an exception, not a Result).
4. Content screen on the plane's primary text
   ([`boltrig/memory/typed_verbs.py:73`](../../../boltrig/memory/typed_verbs.py) `"refused = await self._refuse_unsafe_content(text, owner_scope, context, scopes)"`);
   the text is `statement` (semantic), `retrieval_text` (episodic), or `title + summary`
   (procedural) ([`boltrig/memory/typed_verbs.py:34`](../../../boltrig/memory/typed_verbs.py) `"def _plane_text(plane: str, params: dict) -> str:"`).
   **Failure:** injection marker or secret gives `INVALID` plus a denied audit row
   ([`boltrig/memory/adapter_writes.py:119`](../../../boltrig/memory/adapter_writes.py) `"reason = screen_content(content)"`,
   `:128` `"secret_kind = contains_secret(content)"`).
5. Per-plane proposer unpacks params into the gate's typed keyword contract
   ([`boltrig/memory/proposers.py:98`](../../../boltrig/memory/proposers.py) `"def proposer_for(gate, plane: str):"`).
6. The gate decides (5.2 / 5.3 / 5.4).
7. If the decision is not in `ACCEPTED_DECISIONS`, the adapter audits with status
   `rejected` or `review_required` and returns the decision as a SUCCESS result carrying
   `persisted` ([`boltrig/memory/typed_verbs.py:87`](../../../boltrig/memory/typed_verbs.py) `"status=\"rejected\" if outcome.fact is None else \"review_required\""`).
   A rejection is therefore an HTTP 200 with `decision` set, not an error.
8. `CONFIRM_EXISTING` short-circuits with `persisted: False`
   ([`boltrig/memory/typed_verbs.py:102`](../../../boltrig/memory/typed_verbs.py) `"{\"decision\": CONFIRM_EXISTING, \"reasons\": outcome.reasons, \"persisted\": False}"`).
9. Otherwise `_commit_accepted` writes the engine node, then updates `engine_ref`, then
   fans out projections, then retires the superseded node
   ([`boltrig/memory/typed_verbs.py:106`](../../../boltrig/memory/typed_verbs.py) `"async def _commit_accepted"`).
   **Failure:** an engine exception triggers `_compensate`, which deletes the new ledger
   row and restores the previous row to `active`
   ([`boltrig/memory/typed_verbs.py:328`](../../../boltrig/memory/typed_verbs.py) `"async def _compensate(self, tenant, outcome) -> None:"`),
   and returns `UNAVAILABLE, retryable=True`.

### 5.2 The semantic gate

1. Lock-free preflight: predicate registry, then durability, then confidence floor
   ([`boltrig/memory/write_gate.py:109`](../../../boltrig/memory/write_gate.py) `"def _semantic_preflight("`).
   **Failures:** `REJECT_INVALID_PREDICATE`, `REJECT_TRANSIENT`, `REJECT_UNSUPPORTED`.
   The transient screen fires only when the caller made no explicit durability assertion
   ([`boltrig/memory/write_gate.py:122`](../../../boltrig/memory/write_gate.py) `"if is_durable is False or (is_durable is None and looks_transient(statement)):"`).
2. Compute the slot key, take the per-slot in-process lock
   ([`boltrig/memory/write_gate.py:178`](../../../boltrig/memory/write_gate.py) `"async with self._lock(tenant, key):"`).
3. Read the current active row for the slot
   ([`boltrig/memory/write_gate.py:179`](../../../boltrig/memory/write_gate.py) `"current = await self._store.get_active_memory_fact(tenant, key)"`).
4. If the normalised incoming value equals the active value, emit `CONFIRM_EXISTING` and
   stop ([`boltrig/memory/write_gate.py:327`](../../../boltrig/memory/write_gate.py) `"async def _maybe_confirm"`).
5. Otherwise compare authority ranks
   ([`boltrig/memory/write_gate.py:94`](../../../boltrig/memory/write_gate.py) `"def _current_value_verdict"`):
   strictly lower rank gives `REJECT_LOWER_AUTHORITY` with both ranks in the event
   detail; equal rank parks a candidate with reason "equal-authority conflict"; strictly
   higher rank proceeds.
6. On an empty slot, auto-accept requires rank >= 3 (`human_statement` or better) or
   rank >= 2 with confidence >= 0.75
   ([`boltrig/memory/write_gate.py:214`](../../../boltrig/memory/write_gate.py) `"auto_accept = authority_rank(source_authority) >= 3 or ("`);
   otherwise a candidate is parked with "new slot from weak authority".
7. `accept_semantic` closes the previous row (`status='superseded'`, `valid_to=now`) then
   inserts the new row at `version + 1` with `supersedes_id` set
   ([`boltrig/memory/write_gate_outcomes.py:31`](../../../boltrig/memory/write_gate_outcomes.py) `"current.status = \"superseded\""`,
   `:45` `"version=(current.version + 1) if current else 1"`).
   Two or three `memory_events` rows follow: activated, and superseded when there was a
   previous ([`boltrig/memory/write_gate_outcomes.py:33`](../../../boltrig/memory/write_gate_outcomes.py) `"await store.update_memory_fact(current)"`).
   **Failure:** these are two separate awaits with no transaction. See RISK 08-R05.

### 5.3 The episodic gate

1. `episodic_preflight` checks terminality first
   ([`boltrig/memory/write_gate_planes.py:36`](../../../boltrig/memory/write_gate_planes.py) `"return REJECT_NOT_TERMINAL, [\"run has not reached a terminal/reviewable state\"]"`),
   then non-empty `retrieval_text`, then outcome vocabulary, then confidence floor.
2. An accepted episode is written with `memory_key` unset and `status='active'` at once,
   with no lock and no supersession
   ([`boltrig/memory/write_gate_planes.py:56`](../../../boltrig/memory/write_gate_planes.py) `"unset, no supersession path."`).
3. One `memory_activated` event with `decision=ACCEPT_NEW` is appended.

The only automatic producer of episodes in the tree is post-run reflection, which builds
a deterministic template (no model call) from a terminal work item
([`boltrig/fleet/reflection.py:51`](../../../boltrig/fleet/reflection.py) `"def episode_proposal(item: WorkItem, terminal_status: str, outcome: dict) -> dict:"`)
and dispatches it on the narrow reflection seat
([`boltrig/fleet/authority.py:47`](../../../boltrig/fleet/authority.py) `"REFLECTION_GRANTS = GrantSet.of([\"memory.remember\", \"memory.propose\"])"`).
A gate rejection there is counted as success, not failure
([`boltrig/fleet/reflection.py:112`](../../../boltrig/fleet/reflection.py) `"rejection from the write gate (duplicate, below floor) is an"`).

### 5.4 The procedural gate

1. `procedure_key` shape check: `::`-separated, at least three non-empty parts, at most
   160 characters ([`boltrig/memory/typology.py:151`](../../../boltrig/memory/typology.py) `"def valid_procedure_key"`).
   **Failure:** `REJECT_INVALID_PREDICATE`.
2. The row is written with `status='candidate'` unconditionally
   ([`boltrig/memory/write_gate_planes.py:108`](../../../boltrig/memory/write_gate_planes.py) `"No amount of confidence activates a procedure: always a candidate."`).
3. A `candidate_created` event with `decision=REQUEST_HUMAN_REVIEW` is appended, and the
   outcome is `REQUEST_HUMAN_REVIEW` with the fact attached.

### 5.5 `memory.candidates.review` (the only activation path)

1. The verb is declared `consequence="high"`
   ([`boltrig/memory/adapter_specs.py:263`](../../../boltrig/memory/adapter_specs.py) `"consequence=\"high\","`),
   so the kernel HITL gate creates an approval before it runs
   ([`boltrig/kernel/hitl.py:4`](../../../boltrig/kernel/hitl.py) `"creates an approval before a high-consequence verb runs"`).
2. The adapter re-reads the candidate and refuses when it is out of scope, making hidden
   and missing indistinguishable
   ([`boltrig/memory/typed_verbs.py:261`](../../../boltrig/memory/typed_verbs.py) `"# Hidden and missing are indistinguishable (SEC-40)."`).
3. `review_candidate` refuses anything whose status is not `candidate`
   ([`boltrig/memory/write_gate_review.py:21`](../../../boltrig/memory/write_gate_review.py) `"if candidate is None or candidate.status != \"candidate\":"`),
   which is what stops a rejected candidate being re-activated.
4. Reject: `status='rejected'` plus a `candidate_rejected` event with decision
   `REVIEW_REJECTED` ([`boltrig/memory/write_gate_review.py:26`](../../../boltrig/memory/write_gate_review.py) `"candidate.status = \"rejected\""`).
5. Approve: take the slot lock, supersede the previous active row, set the candidate to
   `active` with the incremented version, stamp `approved_by` into the payload, and append
   the approved / activated / superseded event triple
   ([`boltrig/memory/write_gate_review.py:49`](../../../boltrig/memory/write_gate_review.py) `"candidate.status = \"active\""`).
6. `_project_reviewed_fact` then writes the engine node and projections
   ([`boltrig/memory/typed_verbs.py:291`](../../../boltrig/memory/typed_verbs.py) `"async def _project_reviewed_fact"`).
   **Failure:** an engine exception returns `UNAVAILABLE` and does NOT compensate
   ([`boltrig/memory/typed_verbs.py:317`](../../../boltrig/memory/typed_verbs.py) `"f\"memory engine write failed: {type(exc).__name__}\","`). See RISK 08-R04.

### 5.6 `memory.bundle` (the read path)

1. Build the effective `MemoryConfig` by merging manifest defaults with per-call
   overrides ([`boltrig/memory/typed_verbs.py:165`](../../../boltrig/memory/typed_verbs.py) `"config = config_from_overrides("`;
   merge point [`boltrig/memory/bundle_config.py:64`](../../../boltrig/memory/bundle_config.py) `"def config_from_overrides"`).
   An unknown `recall_mode` silently falls back to `typed` ([`boltrig/memory/bundle_config.py:70`](../../../boltrig/memory/bundle_config.py) `"if mode not in {RecallMode.TYPED, RecallMode.LEGACY, RecallMode.NONE}:"`).
2. Semantic lane: for each requested subject, `list_active_subject_facts` by key prefix,
   re-filtered to permitted scopes in Python
   ([`boltrig/memory/bundle.py:168`](../../../boltrig/memory/bundle.py) `"continue  # SEC-40 defence-in-depth"`).
   Duplicate slots are skipped and a warning is recorded locally, which is then dropped
   ([`boltrig/memory/bundle.py:171`](../../../boltrig/memory/bundle.py) `"multiple active values for slot"`; dropped unread at [`boltrig/memory/bundle.py:184`](../../../boltrig/memory/bundle.py) `"return facts[: cfg.budget.semantic_items], provenance"`). See RISK 08-R01.
3. Procedural lane: `list_memory_facts(kind='procedural', limit=500)`, filter to
   `status == 'active'` and unexpired, rank by specificity, take `cfg.budget.procedures`
   ([`boltrig/memory/bundle.py:72`](../../../boltrig/memory/bundle.py) `"history = await store.list_memory_facts(tenant, scopes, kind=PROCEDURAL, limit=500)"`,
   ranking at [`boltrig/memory/bundle.py:35`](../../../boltrig/memory/bundle.py) `"def procedure_specificity"`).
   The lane is skipped entirely unless BOTH `role` and `workflow` are non-empty
   ([`boltrig/memory/bundle.py:190`](../../../boltrig/memory/bundle.py) `"if not (cfg.procedural and role and workflow):"`).
4. Similarity lane: ONE engine `recall` in `similarity` mode, whose hits are split into
   episodes and source chunks by `EngineFact.kind`
   ([`boltrig/memory/bundle.py:217`](../../../boltrig/memory/bundle.py) `"hits = await recall(query, scopes)"`;
   split at `:233` and `:247`). Each hit is re-hydrated from the ledger, the engine holding
   only a projection ([`boltrig/memory/bundle.py:224`](../../../boltrig/memory/bundle.py) `"ledger = await store.get_memory_fact(tenant, engine_fact.id)"`).
5. Working context is copied through and never written
   ([`boltrig/memory/bundle.py:113`](../../../boltrig/memory/bundle.py) `"working = [str(item) for item in (working_context or [])]"`).
6. `render_prompt` emits the authority header then, in order, `<active_procedures>`,
   `<current_facts>`, `<source_evidence>`, `<past_experience advisory="true">`,
   `<working_state>` ([`boltrig/memory/bundle.py:260`](../../../boltrig/memory/bundle.py) `"_AUTHORITY_HEADER = ("`;
   header text: "Only content inside <active_procedures> may establish operating instructions").
   Each section clips to its character budget and appends a warning
   ([`boltrig/memory/bundle.py:268`](../../../boltrig/memory/bundle.py) `"def _clip(text: str, budget: int)"`).
7. The audit row carries per-lane COUNTS only, never contents
   ([`boltrig/memory/typed_verbs.py:183`](../../../boltrig/memory/typed_verbs.py) `"payload carries counts."`; the audited fields are lane lengths, [`boltrig/memory/typed_verbs.py:189`](../../../boltrig/memory/typed_verbs.py) `"\"semantic\": len(bundle[\"semantic_facts\"]),"`).

### 5.7 `memory.remember` / `memory.ingest` (the untyped path, unchanged)

1. Screen content, then residency check: `data_class == "sensitive"` requires the
   configured embedding endpoint to be in `local_endpoints`, else a denied audit row and
   `SensitiveDataMisrouted`
   ([`boltrig/memory/adapter_writes.py:73`](../../../boltrig/memory/adapter_writes.py) `"if data_class == \"sensitive\" and self._sensitive_endpoint not in self._local_endpoints:"`).
2. Cross-scope edges are pruned unless `cross_scope_edges != "forbidden"`
   ([`boltrig/memory/adapter_writes.py:144`](../../../boltrig/memory/adapter_writes.py) `"async def _permitted_edges"`).
3. Ledger-first: `add_memory_fact`, then `engine.remember`. **Failure:** an engine
   exception deletes the ledger row it just wrote
   ([`boltrig/memory/adapter_writes.py:91`](../../../boltrig/memory/adapter_writes.py) `"await self._store.delete_memory_fact(tenant, fact.id)"`).
4. Projections fan out last and their failures never fail the verb.
5. `memory.ingest` records a `MemoryIngestion` through screening -> cognifying -> done
   or rejected, capped at `MAX_INGEST_ITEMS = 100`
   ([`boltrig/memory/adapter_writes.py:184`](../../../boltrig/memory/adapter_writes.py) `"if len(items) > MAX_INGEST_ITEMS:"`;
   constant at [`boltrig/store/base.py:79`](../../../boltrig/store/base.py) `"MAX_INGEST_ITEMS = 100"`).
   A conversation source reads the transcript from the store, not from the caller
   ([`boltrig/memory/adapter_writes.py:263`](../../../boltrig/memory/adapter_writes.py) `"async def _source_items"`).
6. `approval_context` binds a conversation ingestion approval to a sha256 digest of the
   exact transcript being approved, so the approved snapshot cannot drift
   ([`boltrig/memory/adapter.py:115`](../../../boltrig/memory/adapter.py) `"async def approval_context("`).

A second, older ingestion entry point exists as a free function that drives the same
verb through `kernel.invoke`
([`boltrig/memory/cognify.py:29`](../../../boltrig/memory/cognify.py) `"async def cognify("`),
optionally on a durable executor step ([`boltrig/memory/cognify.py:92`](../../../boltrig/memory/cognify.py) `"added = await executor.run_step(\"cognify\", _commit_all"`). It deliberately re-raises
`PendingHuman` so an approval pause is not mistaken for a bad item
([`boltrig/memory/cognify.py:81`](../../../boltrig/memory/cognify.py) `"except PendingHuman:"`).

### 5.8 `memory.recall` and erasure

`_recall` prefers the primary projection when one is configured, falls back to the
engine, and re-filters every hit to the permitted scopes regardless of source
([`boltrig/memory/adapter.py:201`](../../../boltrig/memory/adapter.py) `"# SEC-40 defence-in-depth: re-filter to permitted scopes even if the engine"`).
Every returned fact is labelled with its projection source and
`"authority": "kernel_ledger"` ([`boltrig/memory/adapter.py:220`](../../../boltrig/memory/adapter.py) `"\"authority\": \"kernel_ledger\","`).
The audit row records query, mode, scopes and count only
([`boltrig/memory/adapter.py:230`](../../../boltrig/memory/adapter.py) `"{\"query\": query, \"mode\": mode, \"scopes\": scopes, \"count\": len(facts)}"`).

`memory.forget` refuses an empty erasure outright
([`boltrig/memory/adapter.py:96`](../../../boltrig/memory/adapter.py) `"if not params.get(\"target\") and not params.get(\"source_ref\"):"`),
asks the engine to remove the node and its derived edges, deletes the matching ledger
rows, writes a `MemoryErasure` row with `facts_removed` and `engine_confirmed=True`, then
fans the deletion out to projections
([`boltrig/memory/adapter.py:263`](../../../boltrig/memory/adapter.py) `"erasure = MemoryErasure("`).
Note that `engine_confirmed` is set to the literal `True` rather than derived from the
engine's answer (RISK 08-R06).

### 5.9 Projection fanout

Two fanouts share one status vocabulary: `remember` may end `written` or `failed`;
`forget` may end `deleted` or `delete_failed`
([`boltrig/memory/projections.py:26`](../../../boltrig/memory/projections.py) `"_FINAL_STATUSES = {"`).
A backend returning an out-of-vocabulary status is recorded as a contract violation and
never retried, because retrying a call that may have succeeded would double-write
([`boltrig/memory/projections.py:189`](../../../boltrig/memory/projections.py) `"# A backend that RETURNS an out-of-vocabulary status is a"`).

Inline mode gives a failed call exactly one bounded reattempt when `retry_failed` is
true, and records the budget that applied on the row so a reader can tell "we tried twice
and it is down" from "fast-fail was chosen"
([`boltrig/memory/projection_retry.py:70`](../../../boltrig/memory/projection_retry.py) `"budget = 2 if self._retry_failed else 1"`,
`:55` `"max_operation_attempts=2 if self._retry_failed else 1,"`).

Queued mode turns each backend operation into one executor task payload and fences the
payload tenant against the context envelope tenant before running it
([`boltrig/memory/projection_queue.py:205`](../../../boltrig/memory/projection_queue.py) `"def _fence(payload: dict[str, Any]) -> None:"`).
Retries there are a real budget of 1..5, default 3
([`boltrig/memory/projection_queue.py:30`](../../../boltrig/memory/projection_queue.py) `"_DEFAULT_MAX_OPERATION_ATTEMPTS = 3"`),
and an already-final row short-circuits so a redelivered task is idempotent
([`boltrig/memory/projection_delivery_attempts.py:88`](../../../boltrig/memory/projection_delivery_attempts.py) `"previous.status in {\"written\", \"failed\", \"deleted\", \"delete_failed\"}"`).
`projection_delivery_posture()` reports what the queue seam really is, including
`"proves_worker_liveness": False`
([`boltrig/memory/projection_queue.py:89`](../../../boltrig/memory/projection_queue.py) `"\"proves_worker_liveness\": False,"`).

`recall` through the fanout goes to the primary projection only, re-hydrates each hit
from the ledger, drops anything out of scope, and returns `None` on ANY exception so the
adapter silently falls back to the engine
([`boltrig/memory/projections.py:294`](../../../boltrig/memory/projections.py) `"except Exception:"` then `"return None"`).

### 5.10 Knowledge upload -> commit

1. `knowledge.upload.begin` validates title and filename (no path separators), resolves
   the owner scope from the principal, and inserts a `begun` row
   ([`boltrig/knowledge/service.py:67`](../../../boltrig/knowledge/service.py) `"filename must be a plain name of at most 240 characters"`).
   **Failure:** `PermissionError` for an unpermitted owner scope ([`boltrig/knowledge/service.py:73`](../../../boltrig/knowledge/service.py) `"owner scope {owner_scope!r} is not permitted"`).
2. `knowledge.upload.stage` bounds the body at 25 MiB, writes it to the vault staging
   key, and records digest and byte size
   ([`boltrig/knowledge/service.py:92`](../../../boltrig/knowledge/service.py) `"raise ValueError(f\"upload exceeds {MAX_UPLOAD_BYTES} bytes\")"`).
   The filesystem vault writes with `open("xb")` then `os.replace`, chmod 0600
   ([`boltrig/knowledge/filesystem_vault.py:53`](../../../boltrig/knowledge/filesystem_vault.py) `"def _write_once(path: Path, data: bytes) -> None:"`).
3. `knowledge.upload.commit` takes a per-upload asyncio lock, re-reads the row, returns
   `replayed: True` if already committed, re-verifies the staged bytes against the
   recorded digest and length, extracts, promotes the blob to its content-addressed key,
   and saves the whole bundle in one transaction
   ([`boltrig/knowledge/service.py:113`](../../../boltrig/knowledge/service.py) `"lock = self._commit_locks.setdefault((context.tenant_id, upload_id), asyncio.Lock())"`,
   `:121` `"if hashlib.sha256(data).hexdigest() != upload.digest or len(data) != upload.byte_size:"`).
   **Failure:** a lost cross-instance race (the Postgres `FOR UPDATE` path) is answered as
   an idempotent replay rather than an error ([`boltrig/knowledge/service.py:131`](../../../boltrig/knowledge/service.py) `"answer with the idempotent replay, not an error."`).
4. The Postgres transaction binds the connection to the tenant, takes `FOR UPDATE` on the
   upload row, refuses unless status is `staged`, inserts blob/asset/revision/
   representation/occurrence/segments/embeddings/access/job, then flips the upload to
   `committed` ([`boltrig/knowledge/postgres_repository.py:87`](../../../boltrig/knowledge/postgres_repository.py) `"SELECT status FROM knowledge_uploads WHERE tenant_id=$1 AND id=$2 FOR UPDATE"`;
   inserts at [`boltrig/knowledge/postgres_writes.py:8`](../../../boltrig/knowledge/postgres_writes.py) `"async def insert_bundle(connection, bundle) -> None:"`).
5. ONLY THEN, outside the lock and outside the transaction, the compiler projection runs
   ([`boltrig/knowledge/service.py:136`](../../../boltrig/knowledge/service.py) `"projections = await self.projections.compile("`).
   This ordering is the whole mechanism behind the "degraded compiler cannot roll back the
   canonical commit" claim. See 9.3 for the proof and its one hole.

Access scopes written for the asset are the owner scope plus, when present, the
workspace scope ([`boltrig/knowledge/service.py:195`](../../../boltrig/knowledge/service.py) `"scopes = {upload.owner_scope}"`).

### 5.11 Knowledge retrieval

`permitted_scopes` derives scopes from the authenticated principal only, never from
caller-supplied `extra` keys, with `principal_scope` accepted only when it is a dict
([`boltrig/knowledge/service.py:40`](../../../boltrig/knowledge/service.py) `"keys; missing principal fields fail closed."`;
derivation at [`boltrig/identity/rbac.py:284`](../../../boltrig/identity/rbac.py) `"def knowledge_scopes("`).
The `org` scope is added only for `superadmin`, `admin` or `org-admin`
([`boltrig/identity/rbac.py:281`](../../../boltrig/identity/rbac.py) `"KNOWLEDGE_ORG_ROLES: frozenset[str] = frozenset({\"superadmin\", \"admin\", \"org-admin\"})"`).

Postgres search is a single hybrid query. The access predicate is an `EXISTS` over
`knowledge_asset_access` inside the WHERE clause, so a candidate outside scope is never
scored ([`boltrig/knowledge/postgres_repository.py:242`](../../../boltrig/knowledge/postgres_repository.py) `"AND EXISTS (SELECT 1 FROM knowledge_asset_access x"`).
The score is `exact-title 3 / substring-title 2` plus `ts_rank_cd(search_vector, plainto_tsquery('simple', q))`
plus `GREATEST(0, 1 - (e.vector <=> q))*0.35`
([`boltrig/knowledge/postgres_repository.py:227`](../../../boltrig/knowledge/postgres_repository.py) `"WHEN lower(a.title)=lower($4) THEN 3"`).
The embedding is picked by `JOIN LATERAL ... ORDER BY e0.created_at DESC LIMIT 1`, an
INNER lateral join ([`boltrig/knowledge/postgres_repository.py:235`](../../../boltrig/knowledge/postgres_repository.py) `"JOIN LATERAL ("`).

`knowledge.context.build` wraps search hits in a typed envelope with
`"authority": "original_revision"`, `"trust": "untrusted_source_content"`, an omissions
count, and a sha256 `context_hash` over the whole envelope
([`boltrig/knowledge/service.py:318`](../../../boltrig/knowledge/service.py) `"\"authority\": \"original_revision\","`,
`:331` `"envelope[\"context_hash\"] = hashlib.sha256("`). It is bounded at 20 items and
80 000 characters ([`boltrig/knowledge/models.py:14`](../../../boltrig/knowledge/models.py) `"MAX_CONTEXT_ITEMS = 20"`).

### 5.12 Knowledge erasure

`erase_asset` deletes the asset row (cascading segments, representations, occurrences,
access and embeddings by FK), then deletes the blob ONLY when no surviving revision
references its digest, then erases the object from the vault, then asks the compiler to
erase its projection
([`boltrig/knowledge/postgres_repository.py:282`](../../../boltrig/knowledge/postgres_repository.py) `"DELETE FROM knowledge_blobs b WHERE b.tenant_id=$1 AND b.digest=$2"` with
`"AND NOT EXISTS (SELECT 1 FROM knowledge_revisions r"`;
vault call at [`boltrig/knowledge/service.py:346`](../../../boltrig/knowledge/service.py) `"await self.vault.erase(key)"`).
The verb is `consequence="high"`
([`boltrig/knowledge/adapter.py:175`](../../../boltrig/knowledge/adapter.py) `"consequence=\"high\","`).

### 5.13 The night: `distill.night`

1. Organisation consent check FIRST, before any corpus work or sidecar call
   ([`boltrig/distill/adapter.py:89`](../../../boltrig/distill/adapter.py) `"if not await overnight_enabled(self._store, context.tenant_id):"`;
   the setting is `behaviour.overnight.enabled` and must be exactly `True`
   ([`boltrig/distill/policy.py:16`](../../../boltrig/distill/policy.py) `"return organisation.settings.get(OVERNIGHT_ENABLED_SETTING) is True"`)).
   **Failure:** `UNAUTHORISED`, non-retryable.
2. `_corpus_build`: resolve the target endpoint, derive the corpus, PUT it to the sidecar
   keyed by digest ([`boltrig/distill/adapter.py:168`](../../../boltrig/distill/adapter.py) `"shipped = await self._call(client, \"PUT\", f\"/corpus/{corpus.digest}\", body)"`).
   **Failures:** endpoint not found (`NOT_FOUND`); tenant or data-class refusal
   (`INVALID`, from `CorpusTenantMismatch` / `CorpusDataClassRefused`); sidecar unreachable
   (`UNAVAILABLE`, retryable).
3. Zero records is a quiet night: the verb returns success with `reason: "empty_corpus"`
   and never trains ([`boltrig/distill/adapter_night.py:47`](../../../boltrig/distill/adapter_night.py) `"\"reason\": \"empty_corpus\","`).
4. `_train`: POST `/train` with `{corpus_digest, adapter_kind, base_pin}`. The response is
   checked against the composed pin and refused on drift
   ([`boltrig/distill/adapter.py:204`](../../../boltrig/distill/adapter.py) `"if str(trained.get(\"base_pin\") or \"\") != self._base_pin:"`).
5. `_gate`: register lane calls the sidecar twice per model (`/loglik` then `/diversity`)
   and applies `register_verdict`; craft lane returns a fail-closed `UNAVAILABLE`
   ([`boltrig/distill/adapter_gates.py:57`](../../../boltrig/distill/adapter_gates.py) `"async def craft_gate() -> GateVerdict | AdapterError:"`).
   A sidecar that answers `/loglik` but not `/diversity` FAILS the gate rather than
   waiving the entropy guard ([`boltrig/distill/adapter_gates.py:34`](../../../boltrig/distill/adapter_gates.py) `"# The entropy guard is deliberately STRICT: a sidecar that cannot"`).
6. Every gate run writes one hash-chained `AuditEvent` with status
   `distill_gate_promote` or `distill_gate_hold`, carrying digest, base pin, both scores,
   both diversities and the reason
   ([`boltrig/distill/adapter.py:251`](../../../boltrig/distill/adapter.py) `"status=\"distill_gate_promote\" if verdict.promote else \"distill_gate_hold\","`).
7. Promotion is NOT part of the night unless `auto_promote` is explicitly set
   ([`boltrig/distill/adapter_night.py:78`](../../../boltrig/distill/adapter_night.py) `"if bool(params.get(\"auto_promote\")) and gated.output.get(\"promote\"):"`).

### 5.14 `distill.promote`

1. Resolve the endpoint. **Failure:** `NOT_FOUND`.
2. Find the newest `distill_gate_promote` audit row matching BOTH the corpus digest and
   the endpoint's model, scanning the newest 500 audit rows
   ([`boltrig/distill/adapter.py:339`](../../../boltrig/distill/adapter.py) `"async def _gate_receipt(self, tenant_id: str, digest: str, model: str)"`;
   scan width at `:35` `"_GATE_AUDIT_SCAN = 500  # how far back promote looks for its gate receipt"`).
   **Failure:** no receipt gives `INVALID` and nothing is activated.
3. Flip `is_active` on the endpoint, then install the per-model price into the cost
   accountant in the same act
   ([`boltrig/distill/adapter.py:309`](../../../boltrig/distill/adapter.py) `"self._cost.set_price(endpoint.model, price)"`).
4. Write a `distill_promote` audit row carrying the gate reason.

### 5.15 Conversation compaction (decision 0007)

1. After a turn is fully persisted, `_maybe_compact` runs
   ([`boltrig/fleet/chat_turn_flow.py:271`](../../../boltrig/fleet/chat_turn_flow.py) `"await service._maybe_compact(request.tenant_id, conversation.id)"`,
   and again after regenerate at [`boltrig/fleet/chat.py:358`](../../../boltrig/fleet/chat.py) `"await self._maybe_compact(tenant_id, conversation_id)"`).
2. Compaction engages only when threshold > 0, keep_recent > 0 and keep_recent < threshold
   ([`boltrig/fleet/continuity.py:236`](../../../boltrig/fleet/continuity.py) `"def compaction_enabled(config: Any) -> bool:"`).
3. `plan_compaction` returns everything except the most recent `keep_recent` LIVE turns,
   and only once the live count reaches the threshold
   ([`boltrig/fleet/continuity.py:286`](../../../boltrig/fleet/continuity.py) `"def plan_compaction("`).
4. A new summary row is appended ONLY when it would cover strictly more messages than the
   latest one ([`boltrig/fleet/chat_compaction.py:35`](../../../boltrig/fleet/chat_compaction.py) `"if latest is not None and len(older) <= latest.covered_count:"`).
5. The summariser is deterministic and offline; an optional model seam is tried first and
   any failure or empty answer falls back
   ([`boltrig/fleet/chat_compaction.py:12`](../../../boltrig/fleet/chat_compaction.py) `"async def summarise(service, older: list[ConversationMessage]) -> str:"`).
6. The composer splits older-vs-tail by matching `up_to_message_id`; if that boundary
   message is no longer live it falls through to the full verbatim render rather than
   crashing or dropping a turn
   ([`boltrig/fleet/continuity.py:346`](../../../boltrig/fleet/continuity.py) `"idx = next("` and the comment "fail-safe, never a crash or a dropped turn").
7. The summary re-enters the task inside a typed untrusted envelope
   ([`boltrig/fleet/continuity.py:276`](../../../boltrig/fleet/continuity.py) `"def render_summary_block(summary_text: str) -> str:"`).

### 5.16 Session distillation (the memory half of the same idea)

A slow background sweep turns a thread that has been idle for the configured window into
one governed memory write.

1. Policy comes from `memory.ingest.on_session_end`, defaulting OFF, with a 60 minute
   idle window ([`boltrig/memory/session_distillation.py:54`](../../../boltrig/memory/session_distillation.py) `"def policy_from_manifest"`).
2. Selection pushes the idle and grown predicates into the STORE query, deliberately, so
   a page of unchanged threads cannot wedge the sweep
   ([`boltrig/memory/session_distillation.py:81`](../../../boltrig/memory/session_distillation.py) `"The growth predicate lives in the STORE query, not here"`).
3. Each thread is distilled under a seat built PER THREAD with `on_behalf_of` set to the
   thread owner, holding exactly `memory.remember` and `memory.forget`
   ([`boltrig/memory/session_distillation.py:116`](../../../boltrig/memory/session_distillation.py) `"grants=GrantSet.of([\"memory.remember\", \"memory.forget\"])"`).
4. Idempotence is by receipt: a prior `MemoryIngestion` whose `content_sha256` matches the
   new summary advances the baseline and writes nothing
   ([`boltrig/memory/session_distillation.py:148`](../../../boltrig/memory/session_distillation.py) `"if prior is not None and prior.detail.get(\"content_sha256\") == digest:"`).
5. Re-distillation RETIRES the old summary first (`memory.forget` by `source_ref`) then
   remembers the new one, so a crash leaves the thread summary-less (repairable) rather
   than double-summarised (undetectable)
   ([`boltrig/memory/session_distillation.py:165`](../../../boltrig/memory/session_distillation.py) `"\"memory\", \"memory.forget\", {\"source_ref\": conv.id}, context"`).
6. The receipt is written only AFTER the governed write succeeds
   ([`boltrig/memory/session_distillation.py:180`](../../../boltrig/memory/session_distillation.py) `"# The receipt is written only AFTER the governed write succeeds."`).
7. Each cycle records a durable background-job receipt in addition to the log line
   ([`boltrig/memory/session_distillation.py:302`](../../../boltrig/memory/session_distillation.py) `"await record_background_attempt("`).

## 6. Data

### 6.1 Memory ledger tables

`memory_facts` predates decision 0029; migration 0076 adds eight nullable typed columns,
a status CHECK, two partial unique indexes and two ordinary indexes
([`migrations/versions/0076_typed_memory_ledger.py:26`](../../../migrations/versions/0076_typed_memory_ledger.py) `"ALTER TABLE memory_facts"`).

| object | shape | note |
| --- | --- | --- |
| `memory_facts.memory_key` | TEXT NULL | the logical slot; NULL for episodes and every legacy row |
| `memory_facts.status` | TEXT NOT NULL DEFAULT 'active', CHECK in candidate/active/superseded/rejected | `:38` `"ADD CONSTRAINT memory_facts_status_check"` |
| `memory_facts.version` | INTEGER NOT NULL DEFAULT 1 | monotonic per slot |
| `memory_facts.confidence` | REAL NULL | |
| `memory_facts.valid_from` / `valid_to` | TIMESTAMPTZ NULL | expiry excludes a row from "current" |
| `memory_facts.payload` | JSONB NOT NULL DEFAULT '{}' | subject/predicate/value/source_authority, or the episode/procedure body |
| `memory_facts.supersedes_id` | TEXT NULL | the closed previous version |
| `one_active_semantic_fact_per_slot` | UNIQUE (tenant_id, memory_key) WHERE kind='semantic' AND status='active' | `:43` |
| `one_active_procedure_per_slot` | UNIQUE (tenant_id, memory_key) WHERE kind='procedural' AND status='active' | `:46` |
| `memory_facts_slot_idx` | (tenant_id, memory_key, kind, status) | `:50` |
| `memory_facts_candidate_idx` | (tenant_id, status) WHERE status='candidate' | `:52` |

Legacy rows carry NULL `memory_key`, which the partial unique indexes treat as distinct,
so they never collide with typed slots
([`0076:8`](../../../migrations/versions/0076_typed_memory_ledger.py) `"Existing rows are untouched: they keep status='active'"`).

`memory_events` is new in 0076: PK (tenant_id, id), a six-value CHECK on `event`,
`decision`, `policy_version` defaulting to `typed-write-v1`, JSONB `detail`, and two
indexes on (tenant, memory_id, created_at) and (tenant, memory_key, created_at)
([`0076:55`](../../../migrations/versions/0076_typed_memory_ledger.py) `"CREATE TABLE IF NOT EXISTS memory_events ("`).
Both are mirrored verbatim in the first-boot schema
([`boltrig/store/schema.sql:2028`](../../../boltrig/store/schema.sql) `"CREATE UNIQUE INDEX IF NOT EXISTS one_active_semantic_fact_per_slot"`,
`:2040` `"CREATE TABLE IF NOT EXISTS memory_events ("`), so first boot and upgrade agree.

The engine-owned vector tables are created idempotently by the engine itself and mirrored
in `schema.sql`: `memory_vectors` (PK tenant_id+id, `embedding vector(256)`, `weight`) and
`memory_vector_edges` (PK tenant_id+src+dst)
([`boltrig/memory/pgvector.py:39`](../../../boltrig/memory/pgvector.py) `"_ENGINE_SCHEMA = f\"\"\""`).
The only index is `memory_vectors_scope_idx (tenant_id, owner_scope, kind)`
([`boltrig/memory/pgvector.py:55`](../../../boltrig/memory/pgvector.py) `"CREATE INDEX IF NOT EXISTS memory_vectors_scope_idx"`), the only index the engine schema creates (bounded: `grep -n "CREATE INDEX" boltrig/memory/pgvector.py`, 2026-08-24, pinned tree: one hit). There is NO ANN index (see RISK 08-R02).

Retention: `memory.retention_days: 365` is advertised in the manifest but is not read by
this subsystem; the value that is read belongs to conversation retention
([`boltrig/api/worker.py:181`](../../../boltrig/api/worker.py) `"days = retention_days_from_manifest(manifest)"`).

### 6.2 Knowledge tables (migration 0034)

Thirteen tables, all keyed `(tenant_id, id)` and all FK-chained to the asset with
`ON DELETE CASCADE` except `knowledge_revisions -> knowledge_blobs`, which is
`ON DELETE RESTRICT` so bytes cannot be orphaned by a cascade
([`migrations/versions/0034_knowledge_fabric.py:57`](../../../migrations/versions/0034_knowledge_fabric.py) `"FOREIGN KEY (tenant_id,blob_digest) REFERENCES knowledge_blobs(tenant_id,digest)"`).

- `knowledge_uploads` with a status CHECK in begun/staged/committed (`:23`);
- `knowledge_blobs`, PK (tenant, digest), UNIQUE (tenant, object_key) (`:31`);
- `knowledge_assets` with `deleted_at` (soft-delete column, see below);
- `knowledge_source_occurrences`, indexed by (tenant, asset, observed_at);
- `knowledge_revisions`, UNIQUE (tenant, asset_id, version);
- `knowledge_representations`;
- `knowledge_segments`, UNIQUE (tenant, representation_id, sequence), with a GENERATED
  STORED `search_vector TSVECTOR` over the text and a GIN index
  ([`0034:73`](../../../migrations/versions/0034_knowledge_fabric.py) `"search_vector TSVECTOR GENERATED ALWAYS AS"`);
- `knowledge_embeddings`, `vector vector(256) NOT NULL`, UNIQUE
  (tenant, subject_id, provider, model, version) (`:88`);
- `knowledge_asset_access` (tenant, asset_id, scope) with a scope-first index (`:100`);
- `knowledge_providers`, `knowledge_projection_statuses` (PK includes operation, so a
  compile status and an erase status coexist), `knowledge_jobs`;
- `knowledge_projection_outbox` (`:129`) which nothing reads or writes.

`deleted_at` is filtered by every read (`a.deleted_at IS NULL`) but the erase path issues
a hard `DELETE FROM knowledge_assets`
([`boltrig/knowledge/postgres_repository.py:277`](../../../boltrig/knowledge/postgres_repository.py) `"\"DELETE FROM knowledge_assets WHERE tenant_id=$1 AND id=$2\","`),
so the soft-delete column is present and never set.

Encryption: none of these tables is encrypted at rest by this subsystem. Original bytes
live outside Postgres in the vault, at mode 0600 under a 0700 root for the filesystem
implementation ([`boltrig/knowledge/filesystem_vault.py:17`](../../../boltrig/knowledge/filesystem_vault.py) `"self.root.mkdir(parents=True, exist_ok=True, mode=0o700)"`).

### 6.3 RLS

Every memory and knowledge table is in the opt-in RLS overlay's scoped list, including
`memory_events`, `memory_vectors`, `memory_vector_edges`, and all thirteen knowledge
tables ([`boltrig/store/rls.sql:107`](../../../boltrig/store/rls.sql) `"'memory_vectors','memory_vector_edges','memory_events',"`,
`:171` `"'knowledge_uploads','knowledge_blobs','knowledge_assets',"`).
The policy is `tenant_id = current_setting('app.tenant_id', true)` with FORCE, so an
unbound connection sees zero rows.
`PostgresKnowledgeRepository` is decorated to bind the tenant on every store method,
because it holds an `_RlsPool` outside the `PostgresStore` MRO
([`boltrig/knowledge/postgres_repository.py:38`](../../../boltrig/knowledge/postgres_repository.py) `"@bind_tenant_on_store_methods"`,
with the incident recorded in the comment above it).

### 6.4 Distillation artefacts

Nothing about distillation is stored in a new table. Promotion state is DERIVED from the
hash-chained audit log; the corpus lives only as a JSONL file on the sidecar keyed by its
digest ([`services/distill_sidecar/app.py:119`](../../../services/distill_sidecar/app.py) `"_confined(corpora_dir(), f\"{digest}.jsonl\").write_text(jsonl, encoding=\"utf-8\")"`),
and the adapter under `~/.local/state/boltrig-distill/adapters/<kind>-<digest12>` with a
`boltrig.json` metadata file ([`services/distill_sidecar/app.py:249`](../../../services/distill_sidecar/app.py) `"(adapter_path / \"boltrig.json\").write_text(json.dumps(meta)"`).
The corpus digest folds record CONTENT hashes, the base pin and the erasure watermark
([`boltrig/distill/corpus_identity.py:63`](../../../boltrig/distill/corpus_identity.py) `"def corpus_digest("`).

### 6.5 Conversation summaries

`conversation_summaries` is INSERT-only, tenant and owner scoped through its parent
conversation, RLS-listed ([`boltrig/store/rls.sql:95`](../../../boltrig/store/rls.sql) `"'conversation_summaries',"`),
and purged with the conversation on erasure
([`boltrig/store/postgres.py:1007`](../../../boltrig/store/postgres.py) `"DELETE FROM conversation_summaries"`).

## 7. Configuration surface

### 7.1 `memory:` manifest section

| key | default | read at | what breaks if wrong |
| --- | --- | --- | --- |
| `enabled` | false in code, `true` in the example | [`boltrig/memory/bootstrap.py:20`](../../../boltrig/memory/bootstrap.py) `"if not memory_cfg or not _bool(memory_cfg.get(\"enabled\"))"` | absent: no `memory.*` verbs exist at all |
| `engine` | `local` | [`boltrig/memory/bootstrap.py:25`](../../../boltrig/memory/bootstrap.py) `"engine_kind = memory_cfg.get(\"engine\", \"local\")"` | an unknown value silently selects `LocalMemoryEngine` (the else branch), so a typo downgrades production recall to keyword overlap with no error |
| `database_url` | `$DATABASE_URL` | [`boltrig/memory/bootstrap.py:34`](../../../boltrig/memory/bootstrap.py) `"memory_cfg.get(\"database_url\") or os.environ.get(\"DATABASE_URL\", \"\")"` | pgvector engine cannot connect |
| `embedding.base_url` + `embedding.model` | absent | [`boltrig/memory/embeddings.py:172`](../../../boltrig/memory/embeddings.py) `"def build_embedder"` | absent: `HashingEmbedder` (lexical, not semantic) |
| `embedding.dim` | 256 | [`boltrig/memory/embeddings.py:30`](../../../boltrig/memory/embeddings.py) `"DEFAULT_DIM = 256"` | must match `vector(256)` in both schemas or every insert fails |
| `embedding_endpoint` | `local-sensitive` | [`boltrig/memory/adapter.py:300`](../../../boltrig/memory/adapter.py) `"sensitive = cfg.get(\"embedding_endpoint\", \"local-sensitive\")"` | if not in `local_endpoints`, every sensitive write raises `SensitiveDataMisrouted` |
| `local_endpoints` | `[embedding_endpoint, extraction_endpoint]` | [`boltrig/memory/adapter.py:302`](../../../boltrig/memory/adapter.py) `"cfg.get(\"local_endpoints\") or [sensitive,"` | too wide defeats SEC-43 residency |
| `cross_scope_edges` | `forbidden` | [`boltrig/memory/adapter.py:311`](../../../boltrig/memory/adapter.py) `"cross_scope_edges=cfg.get(\"cross_scope_edges\", \"forbidden\"),"` | any other value stops pruning out-of-scope edges at write time |
| `retrieval.max_hops` | 4 | [`boltrig/memory/adapter.py:312`](../../../boltrig/memory/adapter.py) `"max_hops=int(retrieval.get(\"max_hops\", 4)),"` | traversal depth |
| `retrieval.max_results` | 20 | [`boltrig/memory/adapter.py:313`](../../../boltrig/memory/adapter.py) `"max_results=int(retrieval.get(\"max_results\", 20)),"` | also the bundle's similarity-lane limit |
| `typed.*` | all planes on, budgets 4800/6000/10000/12000 chars | [`boltrig/memory/adapter.py:315`](../../../boltrig/memory/adapter.py) `"typed_config=cfg.get(\"typed\") or None,"` merged at [`boltrig/memory/bundle_config.py:64`](../../../boltrig/memory/bundle_config.py) `"def config_from_overrides"` | a plane switched off vanishes from every bundle silently |
| `projections[]` | `[]` | [`boltrig/memory/projection_adapters.py:80`](../../../boltrig/memory/projection_adapters.py) `"for entry in cfg.get(\"projections\") or []:"` | only `id: cognee` is recognised; any other id is silently ignored |
| `fanout.execution` | `inline` | [`boltrig/memory/projection_adapters.py:94`](../../../boltrig/memory/projection_adapters.py) `"if is_queued_projection_mode(fanout_cfg.get(\"execution\")):"` (accepts async/queue/queued/worker/workers) | anything else is inline |
| `fanout.retry_failed` | `true` | [`boltrig/memory/projection_adapters.py:92`](../../../boltrig/memory/projection_adapters.py) `"retry_failed = _as_bool(fanout_cfg.get(\"retry_failed\", True))"` | false collapses both modes to one attempt |
| `primary_projection` | `cognee` | [`boltrig/memory/projection_adapters.py:93`](../../../boltrig/memory/projection_adapters.py) `"primary = str(cfg.get(\"primary_projection\") or \"cognee\")"` | names the projection `memory.recall` prefers |
| `ingest.on_session_end` | false | [`boltrig/memory/session_distillation.py:65`](../../../boltrig/memory/session_distillation.py) `"if not isinstance(ingest, dict) or ingest.get(\"on_session_end\") is not True"` | on: threads are copied into 365-day memory |
| `ingest.session_idle_minutes` | 60 | [`boltrig/memory/session_distillation.py:68`](../../../boltrig/memory/session_distillation.py) `"minutes = raw if isinstance(raw, int) and raw > 0 else _DEFAULT_IDLE_MINUTES"` | a non-int or non-positive value silently reverts to 60 |
| `ingest.incremental` | true | [`boltrig/memory/session_distillation.py:72`](../../../boltrig/memory/session_distillation.py) `"incremental=ingest.get(\"incremental\") is not False,"` | false freezes each thread's first summary forever |

**Advertised and read by NOTHING** (bounded: `rg -n "default_owner_scope" .`;
`rg -n "default_mode" boltrig/`; `rg -n '"schedule"' boltrig/memory/ boltrig/api/`;
`rg -n 'cfg.get\("store"\)|memory_cfg.get\("store"\)' boltrig/`; pinned tree, 2026-08-24):
`memory.store`, `memory.authority`, `memory.default_owner_scope`,
`memory.retrieval.default_mode`, `memory.fanout.mode`, `memory.ingest.schedule`,
`memory.retention_days`. The recall default mode is hard-coded `graph_completion`
([`boltrig/memory/adapter.py:178`](../../../boltrig/memory/adapter.py) `"mode = params.get(\"mode\", \"graph_completion\")"`).
`memory.ingest.screen_content` is read ONLY by the readiness doctor as a warning
([`boltrig/api/doctor.py:494`](../../../boltrig/api/doctor.py) `"if not is_truthy(str((memory.get(\"ingest\") or {}).get(\"screen_content\", False)))"`);
screening itself is unconditional in the adapter, so setting it false disables nothing.

### 7.2 `knowledge:` manifest section and environment

| key | default | read at | what breaks |
| --- | --- | --- | --- |
| `enabled` | **false** | [`boltrig/knowledge/bootstrap.py:31`](../../../boltrig/knowledge/bootstrap.py) `"value = config.get(\"enabled\", False)"` | default OFF so a manifest without the section never spins a vault under $HOME |
| `vault.kind` | `filesystem` | [`boltrig/knowledge/bootstrap.py:69`](../../../boltrig/knowledge/bootstrap.py) `"def _vault(config: dict[str, Any]):"` | `s3` requires `bucket` or `S3ObjectVault` raises |
| `vault.root` | platform data dir | [`boltrig/knowledge/bootstrap.py:79`](../../../boltrig/knowledge/bootstrap.py) `"return FilesystemObjectVault(cfg.get(\"root\") or _default_root())"` | |
| `vault.bucket` / `prefix` / `endpoint_url` | -, `boltrig`, - | [`boltrig/knowledge/bootstrap.py:76`](../../../boltrig/knowledge/bootstrap.py) `"prefix=str(cfg.get(\"prefix\") or \"boltrig\"),"` | wrong prefix makes `_object_key` reject every read |
| `providers[].id/enabled` | cognee enabled | [`boltrig/knowledge/projections.py:24`](../../../boltrig/knowledge/projections.py) `"def provider_defaults(tenant_id: str, config"` | only `cognee` is ever constructed |
| `cognee.cognee_root` | platform data dir | [`boltrig/knowledge/bootstrap.py:92`](../../../boltrig/knowledge/bootstrap.py) `"cognee_config.setdefault(\"cognee_root\", str(_default_cognee_root()))"` | Cognee writes outside the mounted volume |
| `cognee.llm.*` / `cognee.embedding.*` | absent | [`boltrig/memory/cognee.py:106`](../../../boltrig/memory/cognee.py) `"def _prime_env(self) -> None:"` | the static-server fallback path only |
| `BOLTRIG_KNOWLEDGE_VAULT` | - | [`boltrig/knowledge/bootstrap.py:36`](../../../boltrig/knowledge/bootstrap.py) `"configured = os.environ.get(\"BOLTRIG_KNOWLEDGE_VAULT\")"` | overrides the vault root |
| `BOLTRIG_COGNEE_ROOT` | - | [`boltrig/knowledge/bootstrap.py:45`](../../../boltrig/knowledge/bootstrap.py) `"configured = os.environ.get(\"BOLTRIG_COGNEE_ROOT\")"` | overrides the cognee root |

The compose stack sets both env vars and mounts a named volume for each
([`docker-compose.yml:161`](../../../docker-compose.yml) `"BOLTRIG_KNOWLEDGE_VAULT: ${BOLTRIG_KNOWLEDGE_VAULT:-/var/lib/boltrig/knowledge}"`,
`:177` `"- knowledge_data:/var/lib/boltrig/knowledge"`), and the image pre-creates both
directories owned by the unprivileged user
([`deploy/kernel.Dockerfile:222`](../../../deploy/kernel.Dockerfile) `"/var/lib/boltrig/knowledge \\"`).

Note there is NO manifest or env key for the Knowledge embedder. See RISK 08-R03.

### 7.3 `distill:` manifest section and sidecar environment

| key | default | read at | what breaks |
| --- | --- | --- | --- |
| `enabled` | **false** | [`boltrig/distill/bootstrap.py:39`](../../../boltrig/distill/bootstrap.py) `"if not distill_cfg or not _bool(distill_cfg.get(\"enabled\"))"` | |
| `base_pin` | none | [`boltrig/distill/bootstrap.py:41`](../../../boltrig/distill/bootstrap.py) `"base_pin = str(distill_cfg.get(\"base_pin\") or \"\").strip()"` | MISSING: the adapter is not registered at all and a warning is logged ([`boltrig/distill/bootstrap.py:46`](../../../boltrig/distill/bootstrap.py) `"distill enabled but base_pin missing; not registering"`) |
| `sidecar_url` | `$BOLTRIG_DISTILL_URL` then `http://host.orb.internal:8930` | [`boltrig/distill/bootstrap.py:52`](../../../boltrig/distill/bootstrap.py) `"or os.environ.get(\"BOLTRIG_DISTILL_URL\")"` | wrong target: every verb returns UNAVAILABLE |
| `timeout_seconds` | 1800 | [`boltrig/distill/bootstrap.py:62`](../../../boltrig/distill/bootstrap.py) `"timeout=float(distill_cfg.get(\"timeout_seconds\") or 1800),"` | a 7B nightly train outlives a shorter HTTP timeout |
| `BOLTRIG_DISTILL_STATE` | `~/.local/state/boltrig-distill` | [`services/distill_sidecar/app.py:51`](../../../services/distill_sidecar/app.py) `"STATE_DIR = Path("` | corpora and adapters location |
| `BOLTRIG_DISTILL_MLX_PYTHON` | `sys.executable` | [`services/distill_sidecar/app.py:55`](../../../services/distill_sidecar/app.py) `"MLX_PYTHON = os.environ.get(\"BOLTRIG_DISTILL_MLX_PYTHON\") or sys.executable"` | wrong interpreter: `/health` reports mlx false and train answers 503 |
| `BOLTRIG_DISTILL_PORT` | 8930 | [`services/distill_sidecar/app.py:56`](../../../services/distill_sidecar/app.py) `"PORT = int(os.environ.get(\"BOLTRIG_DISTILL_PORT\") or \"8930\")"` | |
| `BOLTRIG_DISTILL_BIND` | `127.0.0.1` | [`services/distill_sidecar/app.py:60`](../../../services/distill_sidecar/app.py) `"BIND = os.environ.get(\"BOLTRIG_DISTILL_BIND\") or \"127.0.0.1\""` | widening exposes an UNAUTHENTICATED trainer to the LAN |

The organisation setting `behaviour.overnight.enabled` is not manifest config: it is a
governed org row and must be exactly `True`
([`boltrig/distill/policy.py:7`](../../../boltrig/distill/policy.py) `"OVERNIGHT_ENABLED_SETTING = \"behaviour.overnight.enabled\""`).

### 7.4 Compaction (`chat:` section)

`compaction.threshold` (default 40) and `compaction.keep_recent` (default 12) are
TIGHTEN-ONLY: `_tighten_cap` lets a manifest lower them but never raise them past the code
ceiling ([`boltrig/config/manifest.py:788`](../../../boltrig/config/manifest.py) `"compaction_threshold=_tighten_cap("`;
defaults at `:286` `"DEFAULT_COMPACTION_THRESHOLD = 40"`). `threshold: 0` disables
compaction and restores full-verbatim continuity exactly.

## 8. PROCESS

### 8.1 Bringing memory up

1. Set `memory.enabled: true` and pick `memory.engine`. There are four:
   `local` (keyword overlap, dev only), `vector` (in-process cosine),
   `pgvector` (the production native engine), `cognee` (the graph upgrade)
   ([`boltrig/memory/bootstrap.py:26`](../../../boltrig/memory/bootstrap.py) `"if engine_kind == \"cognee\":"`).
2. For `pgvector`, ensure `DATABASE_URL` or `memory.database_url`. The engine applies its
   own idempotent DDL on first pool acquisition
   ([`boltrig/memory/pgvector.py:88`](../../../boltrig/memory/pgvector.py) `"if self._apply_schema:"`).
3. Run `make migrate` for 0076 if the deployment predates typed planes; a fresh stack gets
   the same objects from `schema.sql`.
4. Verify with `make doctor`: it checks that every memory endpoint is local-sensitive and
   warns when ingest screening is configured off ([`boltrig/api/doctor.py:492`](../../../boltrig/api/doctor.py) `"Memory endpoints are local-sensitive."`; [`boltrig/api/doctor.py:495`](../../../boltrig/api/doctor.py) `"Memory ingest content screening is disabled."`).
5. Registration is logged with the engine and whether projections exist
   ([`boltrig/memory/bootstrap.py:54`](../../../boltrig/memory/bootstrap.py) `"log.info(\"memory subsystem enabled (engine=%s, projections=%s)\""`).

### 8.2 The typed-memory review loop (the human procedure)

1. An agent, a human, or post-run reflection calls `memory.propose`. Everything with
   equal-authority conflict, weak authority on an empty slot, or any procedural content
   lands as a CANDIDATE.
2. The queue is read at `GET /v1/memory/candidates`, scope-filtered
   ([`boltrig/kernel/memory_read_routes.py:74`](../../../boltrig/kernel/memory_read_routes.py) `"@app.get(\"/v1/memory/candidates\")"`).
3. The slot's history is read at `GET /v1/memory/timeline`, by `memory_key` or by
   subject/predicate/scope, with the version chain, valid_from/valid_to and
   `supersedes_id` ([`boltrig/kernel/memory_read_routes.py:109`](../../../boltrig/kernel/memory_read_routes.py) `"@app.get(\"/v1/memory/timeline\")"`).
4. A reviewer approves or rejects at
   `POST /v1/memory/candidates/{candidate_id}/review`
   ([`boltrig/kernel/memory_mutation_routes.py:78`](../../../boltrig/kernel/memory_mutation_routes.py) `"@app.post(\"/v1/memory/candidates/{candidate_id}/review\")"`).
   Because the verb is high-consequence, the first call returns HTTP 202 with an
   `hitl_request_id`; the caller must answer that approval and REPLAY the review carrying
   `x-boltrig-approval-id`
   ([`boltrig/kernel/memory_mutation_routes.py:28`](../../../boltrig/kernel/memory_mutation_routes.py) `"approval_id=request.headers.get(\"x-boltrig-approval-id\")"`).
5. The Worker's Memory surface performs steps 2 to 4 in one click: it calls review, sees
   the pending approval, answers it as the same principal, then replays
   ([`apps/worker/src/components/MemorySurface.tsx:186`](../../../apps/worker/src/components/MemorySurface.tsx) `"const result = await client.memoryCandidateReview(candidate.id, { decision });"`).
   See RISK 08-R07 for what that does to the gate's meaning.
6. Recovery: a candidate rejected in error cannot be re-activated; propose it again.
   The gate refuses anything not in `candidate` status.

### 8.3 Bringing Knowledge up

1. Set `knowledge.enabled: true` (default is OFF, deliberately: a manifest without the
   section must not create a vault under `$HOME`,
   [`boltrig/knowledge/bootstrap.py:29`](../../../boltrig/knowledge/bootstrap.py) `"spin up a filesystem vault under $HOME"`).
2. Choose the vault. Filesystem for personal and offline, S3 for cloud. Both implement the
   same digest, revision, traversal and erasure contract, which is the acceptance
   condition of decision 0015 clause 4.
3. `register_knowledge` ensures the provider rows, retires the legacy ones, defaults the
   cognee root, builds the coordinator with the model-binding resolver, constructs the
   service, and registers the adapter
   ([`boltrig/knowledge/bootstrap.py:82`](../../../boltrig/knowledge/bootstrap.py) `"async def register_knowledge("`).
   The repository choice is an `isinstance(store, PostgresStore)` check, deliberately not a
   `getattr`, so a renamed attribute fails loudly instead of degrading to in-memory
   ([`boltrig/knowledge/bootstrap.py:58`](../../../boltrig/knowledge/bootstrap.py) `"an isinstance guard, not a blind getattr, so a renamed"`; the check itself at [`boltrig/knowledge/bootstrap.py:62`](../../../boltrig/knowledge/bootstrap.py) `"if isinstance(store, PostgresStore):"`).
4. Codex is given the read-only `knowledge/retrieval` skill, which grants five read verbs
   and instructs the model to label every passage untrusted and to preserve the citation
   object ([`libraries/skills/knowledge/retrieval.yaml:27`](../../../libraries/skills/knowledge/retrieval.yaml) `"tool_grants:"`).
5. Two MCP resources are exposed over the same governed verbs
   ([`boltrig/knowledge/adapter.py:37`](../../../boltrig/knowledge/adapter.py) `"def mcp_resources(self) -> list[McpResourceSpec]:"`).

Diagnosing a degraded compiler: `GET /v1/knowledge/providers` refreshes health first and
then returns the row, so `health`, `status` and `last_error` are current
([`boltrig/knowledge/service.py:359`](../../../boltrig/knowledge/service.py) `"await self.projections.refresh_health(context.tenant_id, context)"`).
When no AI connection is bound the error is the operator-facing string
"Connect an AI provider to enable knowledge enrichment"
([`boltrig/knowledge/projections.py:130`](../../../boltrig/knowledge/projections.py) `"reason = \"Connect an AI provider to enable knowledge enrichment\""`).

### 8.4 Turning on the night (decision 0023 runbook)

The runbook is six steps and is the authority for this procedure
([`docs/proposals/sleep-distillation.md:176`](../../../docs/proposals/sleep-distillation.md) `"## Runbook: turning the night on"`):

1. Start the sidecar natively on the Mac (`deploy/host-m4/run-distill-sidecar.sh` under
   launchd) and confirm `curl :8930/health` reports `"mlx": true`.
2. Set the `distill:` manifest section and add `distill.*` to the operating role's scope.
3. Create the candidate endpoint with `control.model_endpoint.upsert` then IMMEDIATELY
   `control.model_endpoint.retire`, because upsert re-defaults to active.
4. Run ONE manual `distill.night` and read the gate receipt in the audit.
5. Schedule it with `control.workflow.upsert` of
   `libraries/workflows/sleep-distillation-craft.yaml` then `control.workflow.schedule`,
   **as a real user holding `control.workflow.trigger`**: a schedule created by a service
   principal persists as `needs_action` and never runs
   ([`libraries/workflows/sleep-distillation-craft.yaml:15`](../../../libraries/workflows/sleep-distillation-craft.yaml) `"AS A REAL USER holding"`).
   Nothing scans `libraries/workflows/` at boot; the file is authoring data ([`libraries/workflows/sleep-distillation-craft.yaml:12`](../../../libraries/workflows/sleep-distillation-craft.yaml) `"NOTE this file is authoring data, not a boot-time load"`).
6. Keep promotion manual until the loop has earned `auto_promote: true`.

Additionally, and NOT in that runbook: the organisation setting
`behaviour.overnight.enabled` must be exactly `True` or `distill.night` refuses before
any work (DIS-10).

Inspecting a corpus without training anything:
`scripts/distill_corpus_dump.py --tenant X --base-pin Y --database-url Z` runs the same
derivation the verb runs and prints JSONL plus a record/held-out/digest/watermark line on
stderr. It refuses to run without a database URL, because an empty in-memory corpus proves
nothing ([`scripts/distill_corpus_dump.py:42`](../../../scripts/distill_corpus_dump.py) `"print(\"error: --database-url (or BOLTRIG_TEST_DATABASE_URL) is required\","`).

Serving a promoted adapter is `mlx_lm.server` with `--adapter-path`, and the promoted
`ModelEndpoint` points at it with `kind: openai`, `data_class: sensitive`
([`services/distill_sidecar/README.md:32`](../../../services/distill_sidecar/README.md) `"## Serving a promoted adapter"`).

Recovery paths:
- a held night leaves a `distill_gate_hold` receipt and changes nothing;
- a bad promotion is reversed by retiring the endpoint (`is_active=False`), which the
  store enforces at serving time;
- an erasure is honoured by EXCLUSION at the next rebuild, never by editing weights; the
  watermark on each corpus answers "does this adapter predate that erasure"
  ([`docs/decisions/0023-sleep-distillation-and-the-adapter-seam.md:142`](../../../docs/decisions/0023-sleep-distillation-and-the-adapter-seam.md) `"Erasure is satisfied by exclusion at"`).

### 8.5 Running the session-distillation sweep

The worker starts the loop only when the manifest asks for it, and LOGS WHICH, so "off" is
a decision on the record ([`boltrig/api/worker.py:222`](../../../boltrig/api/worker.py) `"log.info(\"session distillation disabled (memory.ingest.on_session_end)\")"`).
Each cycle reports seen / acted / pending, where `pending` is computed by a query that
shares no logic with selection, so a bug inside selection cannot also zero the number
([`boltrig/memory/session_distillation.py:223`](../../../boltrig/memory/session_distillation.py) `"# pending comes from a count that shares no logic with selection, so a bug"`).
Diagnose a wedged sweep by comparing `pending` against `seen`.

### 8.6 Live legs that need services

`make live-check` runs the opt-in integration legs including
`tests/integration/test_cognee_engine.py` and `tests/integration/test_pgvector_engine.py`
([`Makefile:463`](../../../Makefile) `"live-check: ## Run opt-in live integration legs; requires services and credentials"`).
The Cognee live tests are gated behind `BOLTRIG_COGNEE_LIVE=1` plus the package plus LLM
env; offline they are declared gated-not-verified in the invariant file itself
([`tests/invariants.yaml:1090`](../../../tests/invariants.yaml) `"# These bindings only execute behind the cognee live gate"`).

## 9. Failure modes and fail-open/fail-closed posture

### 9.1 Fail-CLOSED guards

| guard | proof |
| --- | --- |
| write-gate preflights | every rejection path returns before any fact row is written ([`boltrig/memory/write_gate.py:167`](../../../boltrig/memory/write_gate.py) `"preflight = _semantic_preflight("`) |
| procedural activation | born `candidate` unconditionally; review is the only transition ([`boltrig/memory/write_gate_planes.py:108`](../../../boltrig/memory/write_gate_planes.py) `"No amount of confidence activates a procedure"`) |
| re-activation of a rejected candidate | status guard ([`boltrig/memory/write_gate_review.py:21`](../../../boltrig/memory/write_gate_review.py) `"if candidate is None or candidate.status != \"candidate\":"`) |
| owner-scope on write | `GrantMissing` raised, not returned ([`boltrig/memory/adapter_writes.py:118`](../../../boltrig/memory/adapter_writes.py) `"raise GrantMissing(f\"cannot write memory to scope {owner_scope}\")"`) |
| injection and secret screening | `INVALID` plus denied audit; nothing persisted ([`boltrig/memory/adapter_writes.py:127`](../../../boltrig/memory/adapter_writes.py) `"content rejected: {reason}"` and [`boltrig/memory/adapter_writes.py:139`](../../../boltrig/memory/adapter_writes.py) `"content contains a secret ({secret_kind}); memory ingestion blocked"`) |
| Cognee secret screen | raises BEFORE the cognee import ([`boltrig/memory/cognee.py:156`](../../../boltrig/memory/cognee.py) `"for f in facts:"` with `"refusing to persist into cognee (SEC-42)"` at `:161`) |
| sensitive residency | `SensitiveDataMisrouted` raised and audited ([`boltrig/memory/adapter_writes.py:80`](../../../boltrig/memory/adapter_writes.py) `"raise SensitiveDataMisrouted("`, audit row at [`boltrig/memory/adapter_writes.py:76`](../../../boltrig/memory/adapter_writes.py) `"\"memory.residency.blocked\","`) |
| empty erasure | `INVALID` ([`boltrig/memory/adapter.py:98`](../../../boltrig/memory/adapter.py) `"AdapterError("`, message "an empty erasure must never be a silent no-op") |
| knowledge scopes | derived from the principal; a caller-supplied `principal_scope` that is not a dict is discarded ([`boltrig/knowledge/service.py:48`](../../../boltrig/knowledge/service.py) `"principal_scope if isinstance(principal_scope, dict) else None,"`) |
| vault traversal | filesystem `_path` rejects escapes; S3 `_object_key` requires the tenants prefix and rejects `.`/`..` segments ([`boltrig/knowledge/s3_vault.py:41`](../../../boltrig/knowledge/s3_vault.py) `"def _object_key(self, key: str) -> str:"`) |
| staged-blob integrity | digest and length re-verified at commit AND again inside `_promote` ([`boltrig/knowledge/filesystem_vault.py:69`](../../../boltrig/knowledge/filesystem_vault.py) `"if hashlib.sha256(data).hexdigest() != digest:"`) |
| content-addressed collision | a destination whose bytes hash differently is a hard error ([`boltrig/knowledge/filesystem_vault.py:74`](../../../boltrig/knowledge/filesystem_vault.py) `"raise ValueError(\"content-addressed object collision\")"`) |
| extraction bounds | unsupported media, no extractable text, > 5000 segments, > 5 000 000 chars all raise ([`boltrig/knowledge/extraction.py:133`](../../../boltrig/knowledge/extraction.py) `"if len(parts) > MAX_SEGMENTS:"`) |
| corpus tenant / data class | refusal, never a filter ([`boltrig/distill/corpus.py:214`](../../../boltrig/distill/corpus.py) `"if target_tenant_id != tenant_id:"`, `:219` `"if target_data_class != \"sensitive\":"`) |
| corpus secret material | the whole RECORD is dropped, and one secret in the prompt poisons the record ([`boltrig/distill/corpus.py:382`](../../../boltrig/distill/corpus.py) `"return None  # one secret poisons the whole record - refuse it"`) |
| adapter-on-adapter training | unrepresentable at the schema (`additionalProperties: false` with no resume field, [`boltrig/distill/adapter_specs.py:36`](../../../boltrig/distill/adapter_specs.py) `"# Deliberately NO base/adapter/resume field (DIS-4)."`) and refused server-side on pin mismatch ([`services/distill_sidecar/app.py:208`](../../../services/distill_sidecar/app.py) `"return 409, {\"error\": \"corpus base_pin does not match the requested base_pin\"}"`) |
| craft gate | always `UNAVAILABLE` ([`boltrig/distill/adapter_gates.py:57`](../../../boltrig/distill/adapter_gates.py) `"async def craft_gate()"`) |
| entropy guard | a sidecar that cannot measure diversity fails the gate rather than waiving DIS-9 ([`boltrig/distill/adapter_gates.py:34`](../../../boltrig/distill/adapter_gates.py) `"# The entropy guard is deliberately STRICT: a sidecar that cannot"`) |
| promotion | no matching passing receipt means no activation ([`boltrig/distill/adapter.py:298`](../../../boltrig/distill/adapter.py) `"# DIS-5: only a passing gate flips is_active - no receipt, no seat."`) |
| overnight consent | absent or corrupt org settings fail toward off ([`boltrig/distill/policy.py:11`](../../../boltrig/distill/policy.py) `"\"\"\"Fail toward off when the organisation or its setting is absent/corrupt.\"\"\""`) |
| missing base pin | the distill adapter is not registered at all ([`boltrig/distill/bootstrap.py:46`](../../../boltrig/distill/bootstrap.py) `"distill enabled but base_pin missing; not registering"`) |
| RLS null GUC | policy predicate is NULL, so zero rows ([`boltrig/store/rls.sql:12`](../../../boltrig/store/rls.sql) `"-- A null GUC makes the policy predicate NULL -> never true -> zero rows"`) |

### 9.2 Fail-OPEN behaviours (deliberate, and their blast radius)

| behaviour | proof | consequence |
| --- | --- | --- |
| projection recall falls back to the engine on ANY exception, silently | [`boltrig/memory/projections.py:294`](../../../boltrig/memory/projections.py) `"except Exception:"` then `return None` | a broken primary projection is invisible to the caller; the answer changes source without saying so beyond the `projection_source` field |
| projection write failures never fail the verb | [`boltrig/memory/adapter_writes.py:100`](../../../boltrig/memory/adapter_writes.py) `"if self._projections is not None:"` after the ledger write | correct by decision 0011 §5, but a permanently failing backend only shows up in `memory_projection_statuses` |
| reflection swallows every exception | [`boltrig/fleet/reflection.py:120`](../../../boltrig/fleet/reflection.py) `"except Exception:  # reflection is best-effort; never fail the run (P9)"` | logged at WARNING with a counter, so idle and broken are distinguishable |
| session distillation swallows per-thread failures | [`boltrig/memory/session_distillation.py:241`](../../../boltrig/memory/session_distillation.py) `"except Exception:  # one bad thread must not stall the rest"` | a thread with no receipt is retried next sweep |
| cognify drops a single bad item | [`boltrig/memory/cognify.py:86`](../../../boltrig/memory/cognify.py) `"except BoltrigError:"` | counted in `detail.failed_items`; `PendingHuman` is deliberately re-raised so an approval pause is not reported as `done` with zero facts |
| the summariser seam falls back on any exception | [`boltrig/fleet/chat_compaction.py:18`](../../../boltrig/fleet/chat_compaction.py) `"except Exception:"` | the deterministic digest stands in; prefix stability is preserved |
| compaction boundary no longer live | [`boltrig/fleet/continuity.py:349`](../../../boltrig/fleet/continuity.py) `"if idx is not None and idx < len(live) - 1:"` | falls through to full verbatim: expensive, never wrong |
| `KnowledgeAdapter` catches every exception | [`boltrig/knowledge/adapter.py:64`](../../../boltrig/knowledge/adapter.py) `"except Exception as exc:  # a bad adapter must never crash the kernel (US-ADP-06)"` | the message is the TYPE NAME only, so boto3/asyncpg strings cannot leak endpoints or DSNs |
| unknown `recall_mode` | [`boltrig/memory/bundle_config.py:70`](../../../boltrig/memory/bundle_config.py) `"if mode not in {RecallMode.TYPED, RecallMode.LEGACY, RecallMode.NONE}:"` | silently becomes `typed`; an ablation run configured wrongly reports the wrong label |
| unknown `memory.engine` | [`boltrig/memory/bootstrap.py:44`](../../../boltrig/memory/bootstrap.py) `"engine = LocalMemoryEngine()"` | silently `LocalMemoryEngine`; production recall degrades to keyword overlap with no signal |

### 9.3 The load-bearing claim, tested

**Claim (README, decision 0015):** "If its model configuration is absent or unhealthy, the
canonical commit remains successful and the provider reports degraded."

**Verdict: TRUE on the paths the code enumerates, with one unenumerated hole.**

Proof of the true half, in order:
1. The canonical write completes and the upload flips to `committed` inside the
   transaction, before any compiler call
   ([`boltrig/knowledge/service.py:128`](../../../boltrig/knowledge/service.py) `"await self.repository.save_ingestion(context.tenant_id, upload_id, bundle)"`).
2. `compile` is called after the lock is released and returns a list of statuses; it does
   not raise on a degraded compiler
   ([`boltrig/knowledge/projections.py:152`](../../../boltrig/knowledge/projections.py) `"async def compile("`).
3. Inside `_compile_cognee`, a missing model binding is caught and turned into a
   `failed` ProjectionStatus plus a `degraded` provider row
   ([`boltrig/knowledge/projections.py:188`](../../../boltrig/knowledge/projections.py) `"except CogneeModelUnavailable as error:"`).
4. An unhealthy compiler (`health != "ok"`) short-circuits the same way
   ([`boltrig/knowledge/projections.py:200`](../../../boltrig/knowledge/projections.py) `"if health != \"ok\":"`).
5. A raising `cognee.remember` is caught, and the error text is collapsed to the exception
   TYPE NAME unless it is a deliberate ValueError/LookupError, so endpoint URLs and bucket
   names cannot reach the agent or the audit
   ([`boltrig/knowledge/projections.py:231`](../../../boltrig/knowledge/projections.py) `"except Exception as exc:"`; policy at
   `:321` `"def _error_text(exc: Exception) -> str:"`).
6. `commit_upload` returns `status: "committed"` with the projection statuses attached
   regardless ([`boltrig/knowledge/service.py:142`](../../../boltrig/knowledge/service.py) `"\"status\": \"committed\","`; the statuses attached at [`boltrig/knowledge/service.py:145`](../../../boltrig/knowledge/service.py) `"\"projections\": projections,"`).

The hole: `_compile_cognee` catches ONLY `CogneeModelUnavailable` around
`self._runtime_model(...)` ([`boltrig/knowledge/projections.py:188`](../../../boltrig/knowledge/projections.py) `"except CogneeModelUnavailable as error:"`). `CogneeModelBindingResolver.resolve`
converts `BifrostUserBindingUnavailable` into that type
([`boltrig/memory/cognee_model_binding.py:68`](../../../boltrig/memory/cognee_model_binding.py) `"except BifrostUserBindingUnavailable as error:"`),
but any other exception from `resolve_ai_key`, `load_ai_key_material` or
`gateway.ensure` propagates out of `compile`, out of `commit_upload`, and is converted by
the adapter into an INTERNAL failure. The asset is still committed and a retry answers
`replayed: True`, so no data is lost, but the caller is told the commit failed. Recorded as
RISK 08-R08.

**Claim (README):** "Supermemory and Mem0 are disabled governed catalogue add-ons;
enabling them never changes canonical authority."

**Verdict: FALSE as written; they are RETIRED and cannot be enabled.**
`SUPPORTED_PROVIDER_IDS` is exactly `{"cognee"}`
([`boltrig/knowledge/projections.py:19`](../../../boltrig/knowledge/projections.py) `"SUPPORTED_PROVIDER_IDS = frozenset({\"cognee\"})"`);
`provider_defaults` constructs only Cognee (`:56`); `list_providers` filters everything
else out of public reads ([`boltrig/knowledge/service.py:363`](../../../boltrig/knowledge/service.py) `"provider.public() for provider in providers if provider.id in SUPPORTED_PROVIDER_IDS"`);
`set_provider` raises `LookupError("provider not found")` for any other id
([`boltrig/knowledge/service.py:370`](../../../boltrig/knowledge/service.py) `"raise LookupError(\"provider not found\")"`); and `retire_legacy_providers` rewrites any persisted mem0 or
supermemory row to `enabled=False, health="retired", status="retired"` on every boot
([`boltrig/knowledge/projections.py:60`](../../../boltrig/knowledge/projections.py) `"async def retire_legacy_providers(repository, tenant_id: str) -> None:"`).
The optional Mem0 package is absent from `pyproject.toml` (bounded:
`grep -n -A 30 "optional-dependencies" pyproject.toml`, which lists only
`durable`, `sql-adapters`, `cognee`, `s3`). This is exactly what decision 0015's
2026-08-15 amendment ordered
([`docs/decisions/0015-codex-native-knowledge-extension.md:109`](../../../docs/decisions/0015-codex-native-knowledge-extension.md) `"Mem0 and Supermemory are removed from the shipped catalogue."`);
the README was not updated. RISK 08-R09.

**Claim (decision 0011):** "Mem0 is the primary operational memory projection."

**Verdict: SUPERSEDED and absent from the tree.** The only projection class that exists is
`CogneeProjection` ([`boltrig/memory/projection_adapters.py:28`](../../../boltrig/memory/projection_adapters.py) `"class CogneeProjection:"`),
and `build_memory_projection_fanout` constructs a projection only for `id == "cognee"`
([`boltrig/memory/projection_adapters.py:84`](../../../boltrig/memory/projection_adapters.py) `"if entry.get(\"id\") == \"cognee\":"`). Decision 0011 itself carries the supersession note
([`docs/decisions/0011-boltrig-v2-memory-topology.md:3`](../../../docs/decisions/0011-boltrig-v2-memory-topology.md) `"- Status: superseded by 0015"`).
The shipped example manifest ships `projections: []`, so by default there is no fanout at
all and `build_memory_projection_fanout` returns `None`
([`boltrig/memory/projection_adapters.py:86`](../../../boltrig/memory/projection_adapters.py) `"if not projections:"`).

**Claim (`pgvector.py` docstring):** "recall is backed by an ANN index at scale."

**Verdict: FALSE.** No `hnsw`, `ivfflat`, `vector_cosine_ops` or `vector_l2_ops` exists
anywhere in the tree (bounded: `rg -ni "hnsw|ivfflat|vector_cosine_ops|vector_l2_ops" .`
excluding node_modules and lockfiles, 2026-08-24, pinned tree; the single hit is a comment
in `embeddings.py`). Worse for scale, `PgVectorMemoryEngine.recall` first SELECTs EVERY
in-scope row into Python before scoring
([`boltrig/memory/pgvector.py:137`](../../../boltrig/memory/pgvector.py) `"rows = await conn.fetch("` with no LIMIT), so
recall is O(facts in scope) per call whatever the index situation. RISK 08-R02.

## 10. What is proven

Twenty-six invariants in [`tests/invariants.yaml`](../../../tests/invariants.yaml) bind this area.

**Memory governance (Round Five).** SEC-40 kernel-is-the-isolation-boundary, bound by four
tests including a multi-hop cross-scope case on both the in-process vector engine and real
pgvector ([`tests/invariants.yaml:1018`](../../../tests/invariants.yaml) `"The kernel is the memory isolation boundary at ingestion AND retrieval"`; four bindings, the pgvector one at [`tests/invariants.yaml:1022`](../../../tests/invariants.yaml) `"test_pgvector_recall_is_scope_bounded_multihop"`). SEC-41 recall cannot escalate. SEC-42 injection and
secret screening, six tests including PEM, Google, Slack, Stripe, Anthropic and a
high-entropy fallback, plus a direct Cognee-engine refusal test (`:1033`). SEC-43 sensitive
memory stays local. SEC-44 complete audited erasure, native and pgvector. SEC-45 recall
audited without contents. MEM-VEC-01 cosine ranking agrees between the in-process and
pgvector engines (`:1024`).

**Typed planes (decision 0029).** MEM-TYP-01 slot lifecycle, bound by a supersession test
AND a both-stores parity test (`:1057`). MEM-TYP-02 transient rejection. MEM-TYP-03
unapproved procedures never govern and selection is deterministic. MEM-TYP-04 episodes
retrieved by problem not resolution. MEM-TYP-05 budgets clip and working state never
persists. MEM-TYP-06 review is the only activation path, plus a `memory_events` parity
test. SEC-40 gains a typed-path extension
(`tests/security/test_typed_memory.py::test_typed_recall_is_scope_fenced`).

**Cognee.** MEM-ENG-03 dataset mapping is per (tenant, scope) and injective, and erasure is
real. Only the mapping test runs offline; the three live tests are DECLARED
service-gated in the invariant file itself ([`tests/invariants.yaml:1091`](../../../tests/invariants.yaml) `"offline they are gated-not-verified."`), so MEM-ENG-03's
erasure half is gated-not-verified in an ordinary run. KNO-05 binds the model-binding
contract with eight tests covering request-local configs, no plaintext retention, and
concurrent-tenant isolation.

**Knowledge.** KNO-01 content-addressed immutable originals, stable citations, and
dispatch-chokepoint entry, bound by eleven tests including both vaults, the Codex skill,
MCP resources and Postgres (`:2219`). SEC-KNO-01 scope filtering before ranking, six tests
including "caller-supplied extra scopes are not authority" and the Postgres twin. KNO-02
compiler degradation never rolls back canonical ingest. KNO-03 blob survives until the last
reference. KNO-04 Cognee is the only shipped compiler and retired rows stay hidden, four
tests including a compose-hardening test for persistent storage.

**Distillation.** DIS-1 tenant fence by refusal. DIS-2 sensitive-only target. DIS-3
erasure exclusion plus watermark-in-digest, two tests. DIS-4 schema-closed base pin, two
tests. DIS-5 promotion requires a matching passing receipt, three tests including "a
holding receipt does not authorise". DIS-6 craft gate fails closed. DIS-7 receipt on hold
and on promote. DIS-8 priced in the same act. DIS-9 entropy collapse holds despite better
likelihood, two tests. DIS-10 organisation consent refuses before any sidecar work.

**Compaction.** SEC-90 never mutates a frozen message. SEC-91 prefix stability until the
next compaction. SEC-92 superseded stays excluded. SEC-93 below-threshold composition is
byte-identical to the pre-compaction render. FR-CONV-08 the owner-facing projection
reports the exact compaction state and says "inactive" rather than inventing a boundary
([`tests/invariants.yaml:1540`](../../../tests/invariants.yaml) `"It reports inactive rather than inventing a boundary"`).

**Tested but UNBOUND.** Session distillation has nineteen tests across
`tests/unit/test_session_distillation.py` and `tests/unit/test_session_redistillation.py`
and NO invariant id (bounded: `rg -n "session_distillation|session_redistillation" tests/invariants.yaml`
returns nothing; `grep -n "invariant(" tests/unit/test_session_distillation.py tests/unit/test_session_redistillation.py`
returns nothing; 2026-08-24, pinned tree). By the corpus rule, an unbound correctness
requirement is itself a finding: RISK 08-R10.

Also unbound: the memory projection fanout's status vocabulary, retry budgets and queued
delivery (tested in `tests/unit/test_memory_projection_adapters.py`,
`test_memory_projection_queue.py`, `test_memory_projection_retry.py`, no invariant marker
found by the same bounded search).

## 11. RISKS

RISK 08-R01: the bundle's semantic lane collects "multiple active values for slot"
warnings into a LOCAL list and returns only `(facts, provenance)`, so the warning is
discarded and the caller's `warnings` array never contains it; decision 0029 states these
are "reported as warnings, not silently dropped".
[`boltrig/memory/bundle.py:171`](../../../boltrig/memory/bundle.py) `"warnings.append(f\"multiple active values for slot {slot}\")"`
versus `:184` `"return facts[: cfg.budget.semantic_items], provenance"`.

RISK 08-R02: `PgVectorMemoryEngine`'s docstring claims "recall is backed by an ANN index at
scale", but no ANN index exists anywhere in the tree and `recall` unconditionally SELECTs
every in-scope row before scoring.
[`boltrig/memory/pgvector.py:5`](../../../boltrig/memory/pgvector.py) `"backed by an ANN index at scale"`
versus `:137` `"rows = await conn.fetch("` (no LIMIT) and the index list at `:55`.

RISK 08-R03: production Knowledge search ALWAYS uses the deterministic `HashingEmbedder`.
`embedder` is a constructor-only seam with no manifest or environment path, so the
"pgvector embeddings" in the README are lexical feature hashes, not semantic vectors.
[`boltrig/knowledge/service.py:57`](../../../boltrig/knowledge/service.py) `"self.embedder = embedder or HashingEmbedder()"`
and [`boltrig/knowledge/bootstrap.py:99`](../../../boltrig/knowledge/bootstrap.py) `"service = KnowledgeService(repository, _vault(cfg), projections)"`
(no embedder argument; bounded: `rg -n "KnowledgeService\(" boltrig/`, one hit).

RISK 08-R04: `_project_reviewed_fact` does NOT compensate when the engine write fails,
unlike the propose path. An approved candidate is already `active` in the ledger and the
previous version already `superseded`, so a failed engine write leaves the ledger
activated and the engine without the node.
[`boltrig/memory/typed_verbs.py:317`](../../../boltrig/memory/typed_verbs.py) `"f\"memory engine write failed: {type(exc).__name__}\","`
with no call to `_compensate` (defined at `:328` and used only by `_commit_accepted`).

RISK 08-R05: supersession is two unbatched awaits with no transaction. A crash or a
partial-unique-index violation between them leaves the slot with ZERO active rows; the
UPDATE has landed and the INSERT has not, and `add_memory_fact`'s `ON CONFLICT` targets the
primary key, not the slot index, so a cross-process race raises rather than merges.
[`boltrig/memory/write_gate_outcomes.py:33`](../../../boltrig/memory/write_gate_outcomes.py) `"await store.update_memory_fact(current)"`
then `:51` `"await store.add_memory_fact(fact)"`; conflict target at
[`boltrig/store/postgres.py:1119`](../../../boltrig/store/postgres.py) `"ON CONFLICT (tenant_id, id) DO UPDATE SET"`.

RISK 08-R06: `MemoryErasure.engine_confirmed` is set to the literal `True` and reported to
the caller as `"engine_confirmed": True` regardless of what the engine actually removed,
including when `removed` is empty. SEC-44's claim is "engine-confirmed".
[`boltrig/memory/adapter.py:269`](../../../boltrig/memory/adapter.py) `"engine_confirmed=True,"`.

RISK 08-R07: the Worker's review flow answers the HITL approval it just raised, as the same
principal, inside one click, then replays. The high-consequence gate on
`memory.candidates.review` therefore functions as a confirmation dialog rather than a
second-party approval, and no self-approval prohibition was found (bounded:
`rg -n "self.approv|requested_by|four.eyes|cannot approve" boltrig/kernel/hitl.py boltrig/kernel/hitl_access.py`,
2026-08-24).
[`apps/worker/src/components/MemorySurface.tsx:191`](../../../apps/worker/src/components/MemorySurface.tsx) `"await client.respondHitl(approvalId, \"approve\");"`.

RISK 08-R08: a non-`CogneeModelUnavailable` exception from the model-binding resolver
escapes `compile` and turns an already-committed canonical ingest into an INTERNAL adapter
error for the caller.
[`boltrig/knowledge/projections.py:186`](../../../boltrig/knowledge/projections.py) `"try:"` with only
`"except CogneeModelUnavailable as error:"` at `:188`, and the call site outside the lock at
[`boltrig/knowledge/service.py:136`](../../../boltrig/knowledge/service.py) `"projections = await self.projections.compile("`.

RISK 08-R09: the README still describes Mem0 and Supermemory as "disabled governed
catalogue add-ons" that can be enabled, which decision 0015's 2026-08-15 amendment retired
and which the code makes impossible.
[`README.md:55`](../../../README.md) `"Supermemory and Mem0 are disabled governed"`
versus [`boltrig/knowledge/projections.py:19`](../../../boltrig/knowledge/projections.py) `"SUPPORTED_PROVIDER_IDS = frozenset({\"cognee\"})"`.

RISK 08-R10: session distillation writes into 365-day memory under a system seat and is
bound by no invariant id, so its nineteen tests are not part of the K-29/K-30 binding gate
and can be deleted without the gate noticing. Bounded search stated in section 10.
[`boltrig/memory/session_distillation.py:22`](../../../boltrig/memory/session_distillation.py) `"OFF unless the manifest says otherwise."`

RISK 08-R11: `manifest.example.yaml` still says `ingest.incremental` is "NOT READ
(2026-07-30)" while `policy_from_manifest` has read it since 2026-07-31. An operator
reading the manifest will believe the knob is inert.
[`manifest.example.yaml:521`](../../../manifest.example.yaml) `"# NOT READ (2026-07-30). A thread is distilled ONCE and never revisited"`
versus [`boltrig/memory/session_distillation.py:72`](../../../boltrig/memory/session_distillation.py) `"incremental=ingest.get(\"incremental\") is not False,"`.

RISK 08-R12: seven `memory:` manifest keys are advertised and read by nothing
(`store`, `authority`, `default_owner_scope`, `retrieval.default_mode`, `fanout.mode`,
`ingest.schedule`, `retention_days`), and `ingest.screen_content` is read only by the
doctor as a warning while screening is unconditional. This is the exact defect class the
`session_distillation` docstring was written to record.
[`manifest.example.yaml:517`](../../../manifest.example.yaml) `"default_owner_scope: user"`;
bounded searches stated in section 7.1.

RISK 08-R13: the shipped nightly workflow specifies `adapter_kind: craft`, but the craft
gate is fail-closed and always returns `UNAVAILABLE`. The night therefore builds the
corpus, ships it, and runs a full LoRA training pass before the gate refuses, so following
the runbook step 5 as written burns a training run every night for nothing.
[`libraries/workflows/sleep-distillation-craft.yaml:42`](../../../libraries/workflows/sleep-distillation-craft.yaml) `"adapter_kind: craft"`
versus [`boltrig/distill/adapter_gates.py:58`](../../../boltrig/distill/adapter_gates.py) `"return AdapterError("` and
[`boltrig/distill/adapter_night.py:61`](../../../boltrig/distill/adapter_night.py) `"gated = cast("` (which runs after `_train`).

RISK 08-R14: `_gate_receipt` scans only the newest 500 audit rows for the whole tenant. On
a busy tenant a legitimate gate receipt ages out between the night and the manual
promotion, and `distill.promote` then refuses a candidate that did pass.
[`boltrig/distill/adapter.py:35`](../../../boltrig/distill/adapter.py) `"_GATE_AUDIT_SCAN = 500"`
and `:343` `"events = await self._store.audit_query(tenant_id, limit=_GATE_AUDIT_SCAN)"`.

RISK 08-R15: the write gate's per-slot lock dictionary is never pruned, so one
`asyncio.Lock` accumulates per distinct (tenant, memory_key) for the life of the process.
[`boltrig/memory/write_gate.py:144`](../../../boltrig/memory/write_gate.py) `"return self._locks.setdefault((tenant, memory_key), asyncio.Lock())"`.

RISK 08-R16: only the PRIMARY text of a proposal is screened. For a procedural proposal,
`body_markdown`, `invariants` and `prohibited_actions` never pass `screen_content` or
`contains_secret`, and `invariants` is rendered verbatim into `<active_procedures>`, the
ONLY authority-bearing section of the bundle. Human review stands between proposal and
activation, which is the mitigation, but the screen does not run.
[`boltrig/memory/typed_verbs.py:37`](../../../boltrig/memory/typed_verbs.py) `"if plane == PROCEDURAL:"`
(text is title plus summary only) versus
[`boltrig/memory/bundle.py:290`](../../../boltrig/memory/bundle.py) `"+ \"\\n\".join(f\"  * {inv}\" for inv in (payload.get(\"invariants\") or []))"`.
The semantic plane has the same shape: `statement` is screened, `value` is not, and
`value` is what `<current_facts>` renders ([`boltrig/memory/bundle.py:300`](../../../boltrig/memory/bundle.py) `"- {f.memory_key}: {(f.payload or {}).get('value')}"`).

RISK 08-R17: any authenticated principal may write to the `org` memory scope, because
`memory_owner_scopes` returns `["user:<id>", "org", ...]` for every caller and the adapter
fails closed to the same pair. A low-privileged user can therefore park an org-scope
procedural candidate; activation still needs review.
[`boltrig/identity/rbac.py:272`](../../../boltrig/identity/rbac.py) `"scopes = [f\"user:{user_id}\", \"org\"]"`
and [`boltrig/memory/adapter_writes.py:56`](../../../boltrig/memory/adapter_writes.py) `"return [f\"user:{owner}\", \"org\"]"`.

RISK 08-R18: the distill sidecar has NO authentication of any kind. Loopback binding is the
only control, and `BOLTRIG_DISTILL_BIND` widens it. Anyone who can reach the port can ship
a corpus, start a training run, or read scores.
[`services/distill_sidecar/app.py:57`](../../../services/distill_sidecar/app.py) `"# Loopback by default: an unauthenticated trainer must not face the LAN."`

RISK 08-R19: the non-Cognee branches of `KnowledgeProjectionCoordinator.compile` and
`_erase_one` are unreachable, because the loop above them already `continue`s on
`provider.id not in SUPPORTED_PROVIDER_IDS` and that set is exactly `{"cognee"}`. They read
as a live add-on path and are not one. DEAD.
[`boltrig/knowledge/projections.py:157`](../../../boltrig/knowledge/projections.py) `"if provider.id not in SUPPORTED_PROVIDER_IDS or not provider.enabled:"`
then `:161` `"else:"` with "needs its credential-backed projection adapter configured"; same
shape at `:279` `"if provider.id != \"cognee\":"`.

RISK 08-R20: `knowledge_projection_outbox` is created by migration 0034, listed in the RLS
overlay, and read or written by no application code. DEAD (bounded:
`rg -n "knowledge_projection_outbox" --glob '!migrations/**' .` returns only rls.sql,
schema.sql, and two test cleanup DELETEs, 2026-08-24).
[`migrations/versions/0034_knowledge_fabric.py:129`](../../../migrations/versions/0034_knowledge_fabric.py) `"CREATE TABLE IF NOT EXISTS knowledge_projection_outbox ("`.

RISK 08-R21: `knowledge_assets.deleted_at` exists and every read filters on it, but the
erase path issues a hard DELETE and nothing ever sets the column. A reader would reasonably
believe assets are soft-deleted and recoverable.
[`migrations/versions/0034_knowledge_fabric.py:37`](../../../migrations/versions/0034_knowledge_fabric.py) `"source_kind TEXT NOT NULL, source_ref TEXT, deleted_at TIMESTAMPTZ,"`
versus [`boltrig/knowledge/postgres_repository.py:277`](../../../boltrig/knowledge/postgres_repository.py) `"\"DELETE FROM knowledge_assets WHERE tenant_id=$1 AND id=$2\","`.

RISK 08-R22: Knowledge search uses an INNER `JOIN LATERAL` for the embedding, so a segment
with no embedding row is invisible to search entirely rather than merely scoring zero on
the vector term.
[`boltrig/knowledge/postgres_repository.py:235`](../../../boltrig/knowledge/postgres_repository.py) `"JOIN LATERAL ("` with `"ON true"` at `:239`.

RISK 08-R23: the bundle's episodic and source lanes share ONE similarity pass capped at
`memory.retrieval.max_results` (20). Twenty document chunks ranking above every episode
starve the episodic lane completely, and no warning says so.
[`boltrig/memory/bundle.py:217`](../../../boltrig/memory/bundle.py) `"hits = await recall(query, scopes)"`
with the limit set at [`boltrig/memory/typed_verbs.py:157`](../../../boltrig/memory/typed_verbs.py) `"limit = self._max_results"`.

RISK 08-R24: KNO-02's binding test asserts the projection status is `in {"written", "failed"}`,
which is the complete set of terminal statuses `_compile_cognee` can return, so that half
of the assertion cannot fail. The load-bearing half (commit succeeded, search still works)
does hold.
[`tests/knowledge/test_knowledge_service.py:201`](../../../tests/knowledge/test_knowledge_service.py) `"assert committed[\"projections\"][0][\"status\"] in {\"written\", \"failed\"}"`.

RISK 08-R25: `CogneeEngine`'s id-to-fact index and improve weights are PER PROCESS
(`self._index`, `self._weight`, `self._scopes`), so after a kernel restart a Cognee recall
returns nothing until facts are re-remembered, and a scope with a live cognee dataset is
invisible to `recall` because `self._scopes` is empty. The docstring admits the index is a
session cache but the recall path treats it as the authority on what exists.
[`boltrig/memory/cognee.py:28`](../../../boltrig/memory/cognee.py) `"per-process. The durable governance ledger is the kernel store's"`
and the hard gate at `:203` `"if not in_scope:"` returning `[]`.

## 12. OPEN QUESTIONS

1. **Does `memory.bundle` reach any model?** No caller exists in the pinned tree beyond the
   HTTP route and the adapter (bounded: `rg -n "memory\.bundle" .` excluding `apps/` and
   `docs/`, plus `rg -n "memory.bundle|memoryBundle" apps/ sdks/ libraries/ ios/` which
   returns nothing). Decision 0029 declares this a seam
   ([`docs/decisions/0029-typed-memory-planes.md:109`](../../../docs/decisions/0029-typed-memory-planes.md) `"the Codex runtime does not yet CONSUME"`).
   Settled by finding a prompt-assembly call site, or by confirming the seam is still open.

2. **Is MEM-ENG-03's erasure half ever executed in CI?** The three live Cognee tests are
   declared service-gated. Settled by a CI configuration that sets `BOLTRIG_COGNEE_LIVE=1`,
   or by an offline double for `cognee.forget`.

3. **What happens to a semantic slot after a cross-process unique-index violation?**
   Reasoned from the code (RISK 08-R05), not observed. Settled by a two-writer test against
   the disposable Postgres container.

4. **Is `_compensate` reachable in practice?** It is only called from `_commit_accepted`.
   No test node was found asserting the compensated state (bounded:
   `grep -n "def test_" tests/security/test_typed_memory.py`, seven tests, none named for
   compensation). Settled by reading the Round Five remember tests or adding one.

5. **Does anything consume `projection_delivery_posture()`?** Not searched beyond
   `boltrig/memory/`. Settled by an `rg` across `boltrig/kernel/` and `apps/`.

6. **What is the intended lifetime of `knowledge_projection_outbox`?** Migration 0034
   created it with a pending index, which implies a durable projection worker that was
   never built. Settled by the author of 0034 or by a decision record.

7. **Should `memory.forget` be high-consequence?** It is `consequence="low"` with the
   comment that erasure is a compliance right and therefore not HITL-gated
   ([`boltrig/memory/adapter_specs.py:109`](../../../boltrig/memory/adapter_specs.py) `"# Erasure is a compliance right, so it is not HITL-gated but is always"`),
   while `knowledge.asset.erase` IS high. The asymmetry is deliberate on one side and
   unexplained on the other. Settled by a ruling.

8. **Does the `distill` sidecar's `_model_args` fallback allow an arbitrary HF repo
   download?** A gate `incumbent_model` containing a `/` that is not an adapter directory is
   passed straight to mlx as `--model`
   ([`services/distill_sidecar/app.py:288`](../../../services/distill_sidecar/app.py) `"return [\"--model\", model if \"/\" in model else base_repo]"`).
   The charset is constrained and the caller is a governed verb, so this is not obviously a
   hole, but the network behaviour of `mlx_lm.load` was not read. Settled by reading mlx-lm.

## 13. Requirements

100 requirements, BT-REQ-0800 to BT-REQ-0899. Status counts: 87 IMPLEMENTED,
9 IMPLEMENTED-UNTESTED, 1 SCAFFOLDED, 1 SEAM, 2 DEAD, 0 UNCERTAIN.

Where I looked before tagging IMPLEMENTED-UNTESTED (all bounded to the pinned tree,
2026-08-24):

- BT-REQ-0835 (no ANN index): `rg -ni "hnsw|ivfflat|vector_cosine_ops|vector_l2_ops" .`
  excluding node_modules and lockfiles. One hit, a comment.
- BT-REQ-0843 (Cognee erasure is real): the binding test exists but the invariant file
  itself declares it service-gated ([`tests/invariants.yaml:1091`](../../../tests/invariants.yaml) `"offline they are gated-not-verified."`; the erasure binding listed at [`tests/invariants.yaml:1095`](../../../tests/invariants.yaml) `"test_live_forget_erasure_is_real"`), so it does not run
  offline.
- BT-REQ-0854 (Knowledge always uses HashingEmbedder): `rg -n "embedder=" boltrig/` and
  `rg -n "KnowledgeService\(" boltrig/ tests/`. No test asserts the production wiring.
- BT-REQ-0881, 0882, 0883 (sidecar bind, held-out exclusion, replay weights): the only
  sidecar test file is `tests/security/test_distill_sidecar_argv.py`, whose four tests
  cover argv shape and the absent resume flag, not `_chat_rows`, `_replay_weight` or the
  bind address (`rg -n "held_out|_chat_rows|_replay_weight" tests/` returns two hits, both
  in `test_distill_corpus.py`).
- BT-REQ-0895 (RLS coverage): `tests/integration/test_rls.py` runs only under
  `make live-check`.
- BT-REQ-0896 (unread manifest keys): a negative claim; the bounded searches are stated
  in section 7.1.
- BT-REQ-0897 (all three subsystems default OFF): `rg -n "register_knowledge" tests/`
  returns one caller, which passes `enabled: True`; no test asserts the OFF default.

| id | statement | status | evidence | invariant |
| --- | --- | --- | --- | --- |
| BT-REQ-0800 | Five memory planes are named and exactly three (semantic, episodic, procedural) are writable through the typed write gate. | IMPLEMENTED | `boltrig/memory/typology.py:28 "WRITABLE_PLANES = frozenset({SEMANTIC, EPISODIC, PROCEDURAL})"` | MEM-TYP-01 |
| BT-REQ-0801 | memory.propose refuses any plane outside the writable three, naming source knowledge and working state as not writable memory. | IMPLEMENTED | `boltrig/memory/typed_verbs.py:61 "if plane not in WRITABLE_PLANES:"` | MEM-TYP-05 |
| BT-REQ-0802 | A semantic fact occupies the slot subject_type::subject_id::predicate::owner_scope, independent of its natural-language wording. | IMPLEMENTED | `boltrig/memory/typology.py:54 "def semantic_memory_key"` | MEM-TYP-01 |
| BT-REQ-0803 | A procedure occupies the slot procedure::procedure_key::owner_scope and its key must be ::-separated with at least three non-empty parts. | IMPLEMENTED | `boltrig/memory/typology.py:151 "def valid_procedure_key"` | MEM-TYP-03 |
| BT-REQ-0804 | A semantic proposal naming a predicate outside the closed per-subject registry is rejected REJECT_INVALID_PREDICATE before any lock is taken. | IMPLEMENTED | `boltrig/memory/write_gate.py:118 "if not predicate_allowed(subject_type, predicate):"` | MEM-TYP-01 |
| BT-REQ-0805 | Present-state wording is rejected REJECT_TRANSIENT unless the caller explicitly asserts is_durable true. | IMPLEMENTED | `boltrig/memory/write_gate.py:122 "if is_durable is False or (is_durable is None and looks_transient(statement)):"` | MEM-TYP-02 |
| BT-REQ-0806 | A proposal below the 0.50 review floor is rejected REJECT_UNSUPPORTED and never becomes a candidate. | IMPLEMENTED | `boltrig/memory/write_gate.py:128 "if confidence < CONFIDENCE_REVIEW:"` | MEM-TYP-01 |
| BT-REQ-0807 | A source of strictly lower authority than the slot's current value is rejected REJECT_LOWER_AUTHORITY with both ranks recorded in the event detail. | IMPLEMENTED | `boltrig/memory/write_gate.py:102 "if incoming < holding:"` | MEM-TYP-01 |
| BT-REQ-0808 | An equal-authority conflict with a different current value is parked as a candidate for review, never applied. | IMPLEMENTED | `boltrig/memory/write_gate.py:206 "if verdict == \"conflict\":"` | MEM-TYP-01 |
| BT-REQ-0809 | Accepting a changed semantic value closes the previous row as superseded with valid_to set and opens a new row at version+1 carrying supersedes_id. | IMPLEMENTED | `boltrig/memory/write_gate_outcomes.py:31 "current.status = \"superseded\""` | MEM-TYP-01 |
| BT-REQ-0810 | Re-observing the current value normalises to CONFIRM_EXISTING and writes no new fact row. | IMPLEMENTED | `boltrig/memory/write_gate.py:331 "if current is None or _norm(current.payload.get(\"value\")) != _norm(value):"` | MEM-TYP-01 |
| BT-REQ-0811 | Episodes are append-only: they are written with memory_key unset and have no supersession path. | IMPLEMENTED | `boltrig/memory/write_gate_planes.py:56 "Append-only experience: `memory_key` unset, no supersession path."` | MEM-TYP-04 |
| BT-REQ-0812 | An episode is written only from a terminal run with a non-empty retrieval_text and an outcome from the four-value vocabulary. | IMPLEMENTED | `boltrig/memory/write_gate_planes.py:36 "return REJECT_NOT_TERMINAL, [\"run has not reached a terminal/reviewable state\"]"` | MEM-TYP-04 |
| BT-REQ-0813 | A procedural proposal is always born a candidate; no confidence value activates it. | IMPLEMENTED | `boltrig/memory/write_gate_planes.py:108 "No amount of confidence activates a procedure: always a candidate."` | MEM-TYP-03 |
| BT-REQ-0814 | Explicit review through the high-consequence memory.candidates.review verb is the only path that activates a candidate. | IMPLEMENTED | `boltrig/memory/adapter_specs.py:261 "consequence=\"high\","` | MEM-TYP-06 |
| BT-REQ-0815 | A candidate whose status is not exactly candidate cannot be reviewed, so a rejected candidate can never be re-activated. | IMPLEMENTED | `boltrig/memory/write_gate_review.py:21 "if candidate is None or candidate.status != \"candidate\":"` | MEM-TYP-06 |
| BT-REQ-0816 | Every write-gate decision appends a policy-versioned memory_events row recording the decision code and never the memory content. | IMPLEMENTED | `boltrig/memory/write_gate.py:51 "POLICY_VERSION = \"typed-write-v1\""` | MEM-TYP-06 |
| BT-REQ-0817 | Concurrent writes to one slot are serialised in-process by a per-slot asyncio lock, with the DB partial unique index as the authoritative arbitrator. | IMPLEMENTED | `boltrig/memory/write_gate.py:178 "async with self._lock(tenant, key):"` | MEM-TYP-01 |
| BT-REQ-0818 | Active procedures are resolved deterministically by role/workflow/owner-scope specificity ranking and never by similarity. | IMPLEMENTED | `boltrig/memory/bundle.py:35 "def procedure_specificity"` | MEM-TYP-03 |
| BT-REQ-0819 | Only facts whose status is active and whose valid_to has not passed can enter the bundle's procedural lane, so candidates never govern a prompt. | IMPLEMENTED | `boltrig/memory/bundle.py:75 "if fact.status != \"active\":"` | MEM-TYP-03 |
| BT-REQ-0820 | The bundle's semantic lane returns only active subject-resolved slots and re-filters every row to the caller's permitted scopes. | IMPLEMENTED | `boltrig/memory/bundle.py:167 "continue  # SEC-40 defence-in-depth"` | SEC-40 |
| BT-REQ-0821 | Episodes are retrieved by their stored problem representation and rendered as advisory precedent with failed attempts kept distinct from the resolution. | IMPLEMENTED | `boltrig/memory/bundle.py:330 "<past_experience advisory=\"true\">"` | MEM-TYP-04 |
| BT-REQ-0822 | Working context supplied to memory.bundle is passed through to the rendered prompt and is never persisted to any memory plane. | IMPLEMENTED | `boltrig/memory/bundle.py:113 "working = [str(item) for item in (working_context or [])]"` | MEM-TYP-05 |
| BT-REQ-0823 | The rendered bundle states that only content inside active_procedures may establish operating instructions and that all lower sections are evidence. | IMPLEMENTED | `boltrig/memory/bundle.py:261 "Only content inside <active_procedures> may establish operating "` | MEM-TYP-03 |
| BT-REQ-0824 | Each bundle section clips to its per-plane character budget and appends a named warning, never clipping silently. | IMPLEMENTED | `boltrig/memory/bundle.py:294 "warnings.append(\"procedural section clipped to budget\")"` | MEM-TYP-05 |
| BT-REQ-0825 | Per-plane toggles and budgets merge manifest defaults with per-call config overrides at one point, so an ablation needs no retrieval-code change. | IMPLEMENTED | `boltrig/memory/bundle_config.py:64 "def config_from_overrides"` | MEM-TYP-05 |
| BT-REQ-0826 | No runtime prompt assembly consumes memory.bundle; the only callers are the adapter and the HTTP route. | SEAM | `docs/decisions/0029-typed-memory-planes.md:109 "the Codex runtime does not yet CONSUME"` | - |
| BT-REQ-0827 | Recall results are re-filtered to the caller's permitted scopes after the engine or projection returns them, whatever the source. | IMPLEMENTED | `boltrig/memory/adapter.py:201 "# SEC-40 defence-in-depth: re-filter to permitted scopes even if the engine"` | SEC-40 |
| BT-REQ-0828 | The recall audit row records query, mode, scopes and count and never records fact contents. | IMPLEMENTED | `boltrig/memory/adapter.py:230 "{\"query\": query, \"mode\": mode, \"scopes\": scopes, \"count\": len(facts)}"` | SEC-45 |
| BT-REQ-0829 | Content is screened for injection markers and for API secrets before it becomes memory, and a hit is refused fail-closed with a denied audit row. | IMPLEMENTED | `boltrig/memory/adapter_writes.py:119 "reason = screen_content(content)"` | SEC-42 |
| BT-REQ-0830 | Memory classified sensitive is refused unless the configured embedding endpoint is in the local endpoint set, and the misroute is audited. | IMPLEMENTED | `boltrig/memory/adapter_writes.py:73 "if data_class == \"sensitive\" and self._sensitive_endpoint not in self._local_endpoints:"` | SEC-43 |
| BT-REQ-0831 | memory.forget requires a target or a source_ref so an empty erasure can never be a silent no-op. | IMPLEMENTED | `boltrig/memory/adapter.py:96 "if not params.get(\"target\") and not params.get(\"source_ref\"):"` | SEC-44 |
| BT-REQ-0832 | Erasure writes a MemoryErasure ledger row carrying the requester, target, scope, facts_removed and completion time, and audits the act. | IMPLEMENTED | `boltrig/memory/adapter.py:263 "erasure = MemoryErasure("` | SEC-44 |
| BT-REQ-0833 | The memory engine is a manifest choice among local, vector, pgvector and cognee behind one Protocol, and the kernel core imports none of them. | IMPLEMENTED | `boltrig/memory/bootstrap.py:25 "engine_kind = memory_cfg.get(\"engine\", \"local\")"` | MEM-VEC-01 |
| BT-REQ-0834 | The pgvector engine scope-filters every read in SQL and loads only edges whose both endpoints are in scope, so a cross-scope edge is structurally unfollowable. | IMPLEMENTED | `boltrig/memory/pgvector.py:171 "WHERE tenant_id=$1 AND src = ANY($2::text[]) AND dst = ANY($2::text[])"` | SEC-40 |
| BT-REQ-0835 | No approximate-nearest-neighbour index exists for any vector column in the tree, so vector recall is a sequential scan. | IMPLEMENTED-UNTESTED | `boltrig/memory/pgvector.py:55 "CREATE INDEX IF NOT EXISTS memory_vectors_scope_idx"` | - |
| BT-REQ-0836 | Absent an embedding.base_url and embedding.model, memory embeddings are deterministic feature hashes from HashingEmbedder rather than a semantic model. | IMPLEMENTED | `boltrig/memory/embeddings.py:172 "def build_embedder"` | MEM-VEC-01 |
| BT-REQ-0837 | Each projection operation records a status row from a closed vocabulary and an out-of-vocabulary backend answer is recorded failed and never retried. | IMPLEMENTED | `boltrig/memory/projections.py:189 "# A backend that RETURNS an out-of-vocabulary status is a"` | - |
| BT-REQ-0838 | Inline projection retry is exactly one bounded reattempt when fanout.retry_failed is true, and the applied budget is recorded on the status row. | IMPLEMENTED | `boltrig/memory/projection_retry.py:70 "budget = 2 if self._retry_failed else 1"` | - |
| BT-REQ-0839 | A queued projection task refuses to run when its payload tenant differs from its context envelope tenant. | IMPLEMENTED | `boltrig/memory/projection_queue.py:205 "def _fence(payload: dict[str, Any]) -> None:"` | - |
| BT-REQ-0840 | Projection recall re-hydrates every hit from the kernel ledger, labels the projection source, and returns None on any exception so the engine answers instead. | IMPLEMENTED | `boltrig/memory/projections.py:301 "fact = await self._get_fact(tenant_id, raw.fact_id)"` | - |
| BT-REQ-0841 | Cognee maps one dataset per (tenant, owner_scope) with a sha256 suffix that keeps the mapping injective after slugging. | IMPLEMENTED | `boltrig/memory/cognee.py:79 "def dataset_for(tenant_id: str, owner_scope: str) -> str:"` | MEM-ENG-03 |
| BT-REQ-0842 | CogneeEngine.remember refuses secret-bearing content before the cognee package is imported, so nothing secret can reach its stores. | IMPLEMENTED | `boltrig/memory/cognee.py:161 "refusing to persist into cognee (SEC-42)"` | SEC-42 |
| BT-REQ-0843 | Cognee erasure drops each affected dataset and rebuilds it from the surviving facts only, so a recall after forget cannot return the erased fact from any layer. | IMPLEMENTED-UNTESTED | `boltrig/memory/cognee.py:328 "await cognee.forget(dataset=ds)"` | MEM-ENG-03 |
| BT-REQ-0844 | Cognee request configs are built with model_construct so pydantic-settings never absorbs unrelated process environment variables, and undeclared fields are refused. | IMPLEMENTED | `boltrig/memory/cognee_runtime.py:42 "raise RuntimeError(\"Cognee request config retained undeclared fields\")"` | KNO-05 |
| BT-REQ-0845 | Cognee reuses the caller's ordinary tenant/workspace/user chat connection through one Bifrost virtual key and exact model route; provider plaintext stays in the kernel. | IMPLEMENTED | `boltrig/memory/cognee_model_binding.py:165 "endpoint, api_key, headers = transport.openai_compatible_route(binding.virtual_key)"` | KNO-05 |
| BT-REQ-0846 | Cognee health reports down when the package is unimportable and degraded with a reason when it is importable but has no usable model, never claiming an outage. | IMPLEMENTED | `boltrig/memory/cognee.py:349 "async def health(self, runtime_model: CogneeRuntimeModel \| None = None) -> str:"` | KNO-04 |
| BT-REQ-0847 | A Knowledge upload proceeds begun then staged then committed, and only a staged upload may commit. | IMPLEMENTED | `boltrig/knowledge/postgres_repository.py:91 "raise ValueError(\"upload is not ready to commit\")"` | KNO-01 |
| BT-REQ-0848 | Commit re-verifies the staged bytes against the recorded sha256 digest and byte length before extracting or promoting them. | IMPLEMENTED | `boltrig/knowledge/service.py:121 "if hashlib.sha256(data).hexdigest() != upload.digest or len(data) != upload.byte_size:"` | KNO-01 |
| BT-REQ-0849 | Committing an already-committed upload returns the same asset id with replayed true rather than creating a second asset. | IMPLEMENTED | `boltrig/knowledge/service.py:117 "return {\"asset_id\": upload.asset_id, \"status\": \"committed\", \"replayed\": True}"` | KNO-01 |
| BT-REQ-0850 | Every search hit carries a citation object with asset_id, revision_id, segment_id, locator, source_kind, source_ref and content_hash. | IMPLEMENTED | `boltrig/knowledge/models.py:165 "\"citation\": {"` | KNO-01 |
| BT-REQ-0851 | Knowledge permitted scopes are derived server-side from the authenticated principal and never from caller-supplied context extras. | IMPLEMENTED | `boltrig/knowledge/service.py:40 "keys; missing principal fields fail closed."` | SEC-KNO-01 |
| BT-REQ-0852 | The asset-access scope predicate is inside the search WHERE clause, so an out-of-scope candidate is never scored or ranked. | IMPLEMENTED | `boltrig/knowledge/postgres_repository.py:242 "AND EXISTS (SELECT 1 FROM knowledge_asset_access x"` | SEC-KNO-01 |
| BT-REQ-0853 | Knowledge search scores title exactness, ts_rank_cd over a generated tsvector, and 0.35 times clamped pgvector cosine in one query. | IMPLEMENTED | `boltrig/knowledge/postgres_repository.py:232 "GREATEST(0,1-(e.vector <=> $5::vector))*0.35 END) AS score"` | KNO-01 |
| BT-REQ-0854 | Production Knowledge always embeds with HashingEmbedder because register_knowledge passes no embedder and no manifest or environment key selects one. | IMPLEMENTED-UNTESTED | `boltrig/knowledge/bootstrap.py:99 "service = KnowledgeService(repository, _vault(cfg), projections)"` | - |
| BT-REQ-0855 | Asset erasure removes derived segments immediately and removes the original object only when no surviving revision references its digest. | IMPLEMENTED | `boltrig/knowledge/postgres_repository.py:283 "AND NOT EXISTS (SELECT 1 FROM knowledge_revisions r"` | KNO-03 |
| BT-REQ-0856 | Both ObjectVault implementations refuse an object key that escapes their root or prefix and validate the digest before promoting a staged object. | IMPLEMENTED | `boltrig/knowledge/filesystem_vault.py:22 "raise ValueError(\"object key escapes vault root\")"` | KNO-01 |
| BT-REQ-0857 | Extraction supports only text, Markdown and PDF and refuses a document with no extractable text, over 5000 segments, or over 5000000 characters. | IMPLEMENTED | `boltrig/knowledge/extraction.py:60 "raise ValueError(\"first-slice Knowledge supports text, Markdown, and PDF files\")"` | KNO-01 |
| BT-REQ-0858 | knowledge.context.build returns a bounded envelope labelling every item untrusted_source_content with authority original_revision plus an omissions count and a context hash. | IMPLEMENTED | `boltrig/knowledge/service.py:319 "\"trust\": \"untrusted_source_content\","` | KNO-01 |
| BT-REQ-0859 | A degraded or failing Cognee compiler cannot roll back the canonical Knowledge commit, because compile runs after the ingestion transaction and returns statuses rather than raising. | IMPLEMENTED | `boltrig/knowledge/service.py:136 "projections = await self.projections.compile("` | KNO-02 |
| BT-REQ-0860 | Cognee is the only provider id the Knowledge service will construct, list publicly, or enable; Mem0 and Supermemory are retired, not disabled add-ons. | IMPLEMENTED | `boltrig/knowledge/projections.py:19 "SUPPORTED_PROVIDER_IDS = frozenset({\"cognee\"})"` | KNO-04 |
| BT-REQ-0861 | Persisted Mem0 and Supermemory provider rows are rewritten to disabled and retired on every Knowledge registration and are hidden from public reads. | IMPLEMENTED | `boltrig/knowledge/projections.py:60 "async def retire_legacy_providers(repository, tenant_id: str) -> None:"` | KNO-04 |
| BT-REQ-0862 | The non-Cognee compile and erase branches in the projection coordinator are unreachable because the enclosing loop already skips any id outside SUPPORTED_PROVIDER_IDS. | DEAD | `boltrig/knowledge/projections.py:157 "if provider.id not in SUPPORTED_PROVIDER_IDS or not provider.enabled:"` | - |
| BT-REQ-0863 | A distillation corpus refuses a target endpoint or a record outside the corpus tenant rather than silently thinning itself. | IMPLEMENTED | `boltrig/distill/corpus.py:214 "if target_tenant_id != tenant_id:"` | DIS-1 |
| BT-REQ-0864 | A distillation corpus may only target a sensitive-classed endpoint, because run-level sensitivity is not durably recorded per run. | IMPLEMENTED | `boltrig/distill/corpus.py:219 "if target_data_class != \"sensitive\":"` | DIS-2 |
| BT-REQ-0865 | A conversation covered by any MemoryErasure is excluded from every corpus built afterwards and the erasure watermark is folded into the corpus digest. | IMPLEMENTED | `boltrig/distill/corpus.py:246 "erased = _erased_conversations(conversations, messages_by_conv, erasure_targets)"` | DIS-3 |
| BT-REQ-0866 | The corpus digest hashes record CONTENT rather than record ids, so a change to the scrubber changes the digest. | IMPLEMENTED | `boltrig/distill/corpus_identity.py:25 "def record_fingerprint(r: Any) -> str:"` | DIS-3 |
| BT-REQ-0867 | Exact duplicate records are collapsed at build keeping the best-signal copy at its original position, and the count is reported on the receipt. | IMPLEMENTED | `boltrig/distill/corpus_identity.py:57 "elif _SIGNAL_RANK.get(r.signal, 9) < _SIGNAL_RANK.get(best[key][1].signal, 9):"` | - |
| BT-REQ-0868 | The held-out split is a deterministic ten percent by record-id hash and is guaranteed non-empty whenever any sft record exists. | IMPLEMENTED | `boltrig/distill/corpus.py:123 "def _held_out_split(records: list[SftRecord \| PrefRecord]) -> tuple[str, ...]:"` | - |
| BT-REQ-0869 | Corpus text is PII-redacted first and then refused entirely if secret material survives, and one secret in the prompt poisons the whole record. | IMPLEMENTED | `boltrig/distill/corpus.py:141 "def _scrub(text: str) -> str \| None:"` | DIS-1 |
| BT-REQ-0870 | The distill.train schema has no field naming any starting point other than the composed base pin, so adapter-on-adapter training is unrepresentable. | IMPLEMENTED | `boltrig/distill/adapter_specs.py:36 "# Deliberately NO base/adapter/resume field (DIS-4)."` | DIS-4 |
| BT-REQ-0871 | The sidecar refuses a corpus whose header base_pin differs from the request, and the adapter refuses a train response reporting any other base. | IMPLEMENTED | `services/distill_sidecar/app.py:208 "return 409, {\"error\": \"corpus base_pin does not match the requested base_pin\"}"` | DIS-4 |
| BT-REQ-0872 | The register gate promotes only when the candidate assigns strictly higher held-out mean log-likelihood than the incumbent; a tie keeps the incumbent. | IMPLEMENTED | `boltrig/distill/gate.py:63 "if candidate_loglik > incumbent_loglik + _REGISTER_EPSILON:"` | DIS-9 |
| BT-REQ-0873 | A candidate whose seeded distinct-2 diversity is below 0.8 times the incumbent's is held with reason entropy_collapse regardless of likelihood. | IMPLEMENTED | `boltrig/distill/gate.py:56 "and candidate_diversity < _DIVERSITY_FLOOR * incumbent_diversity"` | DIS-9 |
| BT-REQ-0874 | Every gate run writes one hash-chained audit receipt carrying the digest, base pin, both scores, both diversities and the reason, on promote and on hold alike. | IMPLEMENTED | `boltrig/distill/adapter.py:251 "status=\"distill_gate_promote\" if verdict.promote else \"distill_gate_hold\","` | DIS-7 |
| BT-REQ-0875 | distill.promote activates an endpoint only when a passing gate receipt matching the exact corpus digest and model is found in the newest 500 audit rows. | IMPLEMENTED | `boltrig/distill/adapter.py:339 "async def _gate_receipt(self, tenant_id: str, digest: str, model: str) -> AuditEvent \| None:"` | DIS-5 |
| BT-REQ-0876 | Promotion installs the per-model price into the cost accountant in the same act, closing the unpriced-local-model cost-tier trap. | IMPLEMENTED | `boltrig/distill/adapter.py:309 "self._cost.set_price(endpoint.model, price)"` | DIS-8 |
| BT-REQ-0877 | One night is one governed verb running build then ship then train then gate inside the adapter, because step outputs cannot thread between workflow steps. | IMPLEMENTED | `boltrig/distill/adapter_night.py:24 "async def run_night("` | DIS-10 |
| BT-REQ-0878 | distill.night refuses before any corpus construction or sidecar request unless the organisation setting behaviour.overnight.enabled is exactly true. | IMPLEMENTED | `boltrig/distill/adapter.py:89 "if not await overnight_enabled(self._store, context.tenant_id):"` | DIS-10 |
| BT-REQ-0879 | A night whose corpus has zero records returns success with reason empty_corpus and never trains. | IMPLEMENTED | `boltrig/distill/adapter_night.py:47 "\"reason\": \"empty_corpus\","` | - |
| BT-REQ-0880 | The craft gate always returns UNAVAILABLE until inactive candidates can be evaluated through governed Codex/Bifrost model admission. | SCAFFOLDED | `boltrig/distill/adapter_gates.py:57 "async def craft_gate() -> GateVerdict \| AdapterError:"` | DIS-6 |
| BT-REQ-0881 | The distill sidecar binds loopback by default and performs no authentication of any request. | IMPLEMENTED-UNTESTED | `services/distill_sidecar/app.py:60 "BIND = os.environ.get(\"BOLTRIG_DISTILL_BIND\") or \"127.0.0.1\""` | - |
| BT-REQ-0882 | Held-out records are excluded from the training stream for both adapter kinds, so a candidate cannot pass by memorising its own exam. | IMPLEMENTED-UNTESTED | `services/distill_sidecar/app.py:170 "if r[\"record_id\"] in held_out:"` | - |
| BT-REQ-0883 | The trainer replays human-anchored signals harder than clean runs and doubles records from the last seven days, applying weights to the train split only. | IMPLEMENTED-UNTESTED | `services/distill_sidecar/app.py:137 "_SIGNAL_WEIGHT = {\"hitl_approved\": 3, \"superseded\": 2, \"eval_pass\": 2, \"clean_run\": 1}"` | - |
| BT-REQ-0884 | Conversation compaction appends a new conversation_summaries row and never edits a frozen message record. | IMPLEMENTED | `boltrig/fleet/chat_compaction.py:38 "await service._store.add_conversation_summary(  # noqa: SLF001"` | SEC-90 |
| BT-REQ-0885 | Between compactions the composed task stays a byte-prefix of the next turn's, because the summary block is byte-stable and the tail only appends. | IMPLEMENTED | `boltrig/fleet/continuity.py:351 "return render_summary_block(summary.summary) + render_transcript(tail, config)"` | SEC-91 |
| BT-REQ-0886 | Superseded turns are excluded from both the summarised older set and the verbatim tail, because both are drawn from the superseded-filtered live set. | IMPLEMENTED | `boltrig/fleet/continuity.py:334 "live = [m for m in messages if getattr(m, \"superseded_by\", None) is None]"` | SEC-92 |
| BT-REQ-0887 | The shipped summariser is deterministic and offline; an optional model summariser seam falls back to it on failure or empty output. | IMPLEMENTED | `boltrig/fleet/chat_compaction.py:20 "return summarize_messages(older)"` | SEC-91 |
| BT-REQ-0888 | Compaction thresholds are tighten-only: a manifest may lower the threshold or keep fewer recent turns but never grow the verbatim window past the code ceiling. | IMPLEMENTED | `boltrig/config/manifest.py:788 "compaction_threshold=_tighten_cap("` | SEC-93 |
| BT-REQ-0889 | Session distillation is off unless memory.ingest.on_session_end is exactly true, and a malformed idle window reverts to sixty minutes rather than guessing. | IMPLEMENTED | `boltrig/memory/session_distillation.py:65 "if not isinstance(ingest, dict) or ingest.get(\"on_session_end\") is not True:"` | - |
| BT-REQ-0890 | A re-distilled thread has its prior summary retired before the new one is written, so a crash leaves it summary-less rather than double-summarised. | IMPLEMENTED | `boltrig/memory/session_distillation.py:165 "\"memory\", \"memory.forget\", {\"source_ref\": conv.id}, context"` | - |
| BT-REQ-0891 | Each distillation acts under a seat built for that thread with on_behalf_of set to the thread owner and only memory.remember and memory.forget granted. | IMPLEMENTED | `boltrig/memory/session_distillation.py:116 "grants=GrantSet.of([\"memory.remember\", \"memory.forget\"])"` | - |
| BT-REQ-0892 | Session distillation writes through kernel.invoke rather than the store, so the anti-poisoning screen and the grant check both run. | IMPLEMENTED | `boltrig/memory/session_distillation.py:167 "result = await kernel.invoke("` | SEC-42 |
| BT-REQ-0893 | Migration 0076 adds eight nullable typed columns plus two partial unique indexes enforcing one active row per semantic and per procedural slot. | IMPLEMENTED | `migrations/versions/0076_typed_memory_ledger.py:43 "CREATE UNIQUE INDEX IF NOT EXISTS one_active_semantic_fact_per_slot"` | MEM-TYP-01 |
| BT-REQ-0894 | Migration 0034 creates the thirteen knowledge tables with a generated tsvector column, a GIN index, a fixed vector(256) column and a RESTRICT reference from revisions to blobs. | IMPLEMENTED | `migrations/versions/0034_knowledge_fabric.py:73 "search_vector TSVECTOR GENERATED ALWAYS AS"` | KNO-01 |
| BT-REQ-0895 | Every memory and knowledge table is in the opt-in RLS overlay with a FORCE tenant-isolation policy that yields zero rows on a null GUC. | IMPLEMENTED-UNTESTED | `boltrig/store/rls.sql:107 "'memory_vectors','memory_vector_edges','memory_events',"` | - |
| BT-REQ-0896 | Seven memory manifest keys are advertised in the example manifest and read by no code, and ingest.screen_content is read only as a readiness warning. | IMPLEMENTED-UNTESTED | `manifest.example.yaml:517 "default_owner_scope: user"` | - |
| BT-REQ-0897 | Memory, Knowledge and distillation are each default OFF and register nothing unless their manifest section explicitly enables them. | IMPLEMENTED-UNTESTED | `boltrig/knowledge/bootstrap.py:31 "value = config.get(\"enabled\", False)"` | - |
| BT-REQ-0898 | Distillation refuses to register at all when base_pin is missing, because an unpinned base would make promotion state underivable. | IMPLEMENTED | `boltrig/distill/bootstrap.py:46 "log.warning(\"distill enabled but base_pin missing; not registering\")"` | DIS-4 |
| BT-REQ-0899 | The knowledge_projection_outbox table is created and RLS-fenced but is read and written by no application code. | DEAD | `migrations/versions/0034_knowledge_fabric.py:129 "CREATE TABLE IF NOT EXISTS knowledge_projection_outbox ("` | - |
