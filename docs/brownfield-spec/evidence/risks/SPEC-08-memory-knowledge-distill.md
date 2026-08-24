# Risks harvested from SPEC-08-memory-knowledge-distill.md

RISK 08-R01: the bundle's semantic lane collects "multiple active values for slot"
warnings into a LOCAL list and returns only `(facts, provenance)`, so the warning is
discarded and the caller's `warnings` array never contains it; decision 0029 states these
are "reported as warnings, not silently dropped".
[`boltrig/memory/bundle.py:171`](../../../boltrig/memory/bundle.py) `"warnings.append(f\"multiple active values for slot {slot}\")"`
versus `:184` `"return facts[: cfg.budget.semantic_items], provenance"`.

---

RISK 08-R02: `PgVectorMemoryEngine`'s docstring claims "recall is backed by an ANN index at
scale", but no ANN index exists anywhere in the tree and `recall` unconditionally SELECTs
every in-scope row before scoring.
[`boltrig/memory/pgvector.py:5`](../../../boltrig/memory/pgvector.py) `"backed by an ANN index at scale"`
versus `:137` `"rows = await conn.fetch("` (no LIMIT) and the index list at `:55`.

---

RISK 08-R03: production Knowledge search ALWAYS uses the deterministic `HashingEmbedder`.
`embedder` is a constructor-only seam with no manifest or environment path, so the
"pgvector embeddings" in the README are lexical feature hashes, not semantic vectors.
[`boltrig/knowledge/service.py:57`](../../../boltrig/knowledge/service.py) `"self.embedder = embedder or HashingEmbedder()"`
and [`boltrig/knowledge/bootstrap.py:99`](../../../boltrig/knowledge/bootstrap.py) `"service = KnowledgeService(repository, _vault(cfg), projections)"`
(no embedder argument; bounded: `rg -n "KnowledgeService\(" boltrig/`, one hit).

---

RISK 08-R04: `_project_reviewed_fact` does NOT compensate when the engine write fails,
unlike the propose path. An approved candidate is already `active` in the ledger and the
previous version already `superseded`, so a failed engine write leaves the ledger
activated and the engine without the node.
[`boltrig/memory/typed_verbs.py:317`](../../../boltrig/memory/typed_verbs.py) `"f\"memory engine write failed: {type(exc).__name__}\","`
with no call to `_compensate` (defined at `:328` and used only by `_commit_accepted`).

---

RISK 08-R05: supersession is two unbatched awaits with no transaction. A crash or a
partial-unique-index violation between them leaves the slot with ZERO active rows; the
UPDATE has landed and the INSERT has not, and `add_memory_fact`'s `ON CONFLICT` targets the
primary key, not the slot index, so a cross-process race raises rather than merges.
[`boltrig/memory/write_gate_outcomes.py:33`](../../../boltrig/memory/write_gate_outcomes.py) `"await store.update_memory_fact(current)"`
then `:51` `"await store.add_memory_fact(fact)"`; conflict target at
[`boltrig/store/postgres.py:1119`](../../../boltrig/store/postgres.py) `"ON CONFLICT (tenant_id, id) DO UPDATE SET"`.

---

RISK 08-R06: `MemoryErasure.engine_confirmed` is set to the literal `True` and reported to
the caller as `"engine_confirmed": True` regardless of what the engine actually removed,
including when `removed` is empty. SEC-44's claim is "engine-confirmed".
[`boltrig/memory/adapter.py:269`](../../../boltrig/memory/adapter.py) `"engine_confirmed=True,"`.

---

RISK 08-R07: the Worker's review flow answers the HITL approval it just raised, as the same
principal, inside one click, then replays. The high-consequence gate on
`memory.candidates.review` therefore functions as a confirmation dialog rather than a
second-party approval, and no self-approval prohibition was found (bounded:
`rg -n "self.approv|requested_by|four.eyes|cannot approve" boltrig/kernel/hitl.py boltrig/kernel/hitl_access.py`,
2026-08-24).
[`apps/worker/src/components/MemorySurface.tsx:191`](../../../apps/worker/src/components/MemorySurface.tsx) `"await client.respondHitl(approvalId, \"approve\");"`.

---

RISK 08-R08: a non-`CogneeModelUnavailable` exception from the model-binding resolver
escapes `compile` and turns an already-committed canonical ingest into an INTERNAL adapter
error for the caller.
[`boltrig/knowledge/projections.py:186`](../../../boltrig/knowledge/projections.py) `"try:"` with only
`"except CogneeModelUnavailable as error:"` at `:188`, and the call site outside the lock at
[`boltrig/knowledge/service.py:136`](../../../boltrig/knowledge/service.py) `"projections = await self.projections.compile("`.

---

RISK 08-R09: the README still describes Mem0 and Supermemory as "disabled governed
catalogue add-ons" that can be enabled, which decision 0015's 2026-08-15 amendment retired
and which the code makes impossible.
[`README.md:55`](../../../README.md) `"Supermemory and Mem0 are disabled governed"`
versus [`boltrig/knowledge/projections.py:19`](../../../boltrig/knowledge/projections.py) `"SUPPORTED_PROVIDER_IDS = frozenset({\"cognee\"})"`.

---

RISK 08-R10: session distillation writes into 365-day memory under a system seat and is
bound by no invariant id, so its nineteen tests are not part of the K-29/K-30 binding gate
and can be deleted without the gate noticing. Bounded search stated in section 10.
[`boltrig/memory/session_distillation.py:22`](../../../boltrig/memory/session_distillation.py) `"OFF unless the manifest says otherwise."`

---

RISK 08-R11: `manifest.example.yaml` still says `ingest.incremental` is "NOT READ
(2026-07-30)" while `policy_from_manifest` has read it since 2026-07-31. An operator
reading the manifest will believe the knob is inert.
[`manifest.example.yaml:521`](../../../manifest.example.yaml) `"# NOT READ (2026-07-30). A thread is distilled ONCE and never revisited"`
versus [`boltrig/memory/session_distillation.py:72`](../../../boltrig/memory/session_distillation.py) `"incremental=ingest.get(\"incremental\") is not False,"`.

---

RISK 08-R12: seven `memory:` manifest keys are advertised and read by nothing
(`store`, `authority`, `default_owner_scope`, `retrieval.default_mode`, `fanout.mode`,
`ingest.schedule`, `retention_days`), and `ingest.screen_content` is read only by the
doctor as a warning while screening is unconditional. This is the exact defect class the
`session_distillation` docstring was written to record.
[`manifest.example.yaml:517`](../../../manifest.example.yaml) `"default_owner_scope: user"`;
bounded searches stated in section 7.1.

---

RISK 08-R13: the shipped nightly workflow specifies `adapter_kind: craft`, but the craft
gate is fail-closed and always returns `UNAVAILABLE`. The night therefore builds the
corpus, ships it, and runs a full LoRA training pass before the gate refuses, so following
the runbook step 5 as written burns a training run every night for nothing.
[`libraries/workflows/sleep-distillation-craft.yaml:42`](../../../libraries/workflows/sleep-distillation-craft.yaml) `"adapter_kind: craft"`
versus [`boltrig/distill/adapter_gates.py:58`](../../../boltrig/distill/adapter_gates.py) `"return AdapterError("` and
[`boltrig/distill/adapter_night.py:61`](../../../boltrig/distill/adapter_night.py) `"gated = cast("` (which runs after `_train`).

---

RISK 08-R14: `_gate_receipt` scans only the newest 500 audit rows for the whole tenant. On
a busy tenant a legitimate gate receipt ages out between the night and the manual
promotion, and `distill.promote` then refuses a candidate that did pass.
[`boltrig/distill/adapter.py:35`](../../../boltrig/distill/adapter.py) `"_GATE_AUDIT_SCAN = 500"`
and `:343` `"events = await self._store.audit_query(tenant_id, limit=_GATE_AUDIT_SCAN)"`.

---

RISK 08-R15: the write gate's per-slot lock dictionary is never pruned, so one
`asyncio.Lock` accumulates per distinct (tenant, memory_key) for the life of the process.
[`boltrig/memory/write_gate.py:144`](../../../boltrig/memory/write_gate.py) `"return self._locks.setdefault((tenant, memory_key), asyncio.Lock())"`.

---

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

---

RISK 08-R17: any authenticated principal may write to the `org` memory scope, because
`memory_owner_scopes` returns `["user:<id>", "org", ...]` for every caller and the adapter
fails closed to the same pair. A low-privileged user can therefore park an org-scope
procedural candidate; activation still needs review.
[`boltrig/identity/rbac.py:272`](../../../boltrig/identity/rbac.py) `"scopes = [f\"user:{user_id}\", \"org\"]"`
and [`boltrig/memory/adapter_writes.py:56`](../../../boltrig/memory/adapter_writes.py) `"return [f\"user:{owner}\", \"org\"]"`.

---

RISK 08-R18: the distill sidecar has NO authentication of any kind. Loopback binding is the
only control, and `BOLTRIG_DISTILL_BIND` widens it. Anyone who can reach the port can ship
a corpus, start a training run, or read scores.
[`services/distill_sidecar/app.py:57`](../../../services/distill_sidecar/app.py) `"# Loopback by default: an unauthenticated trainer must not face the LAN."`

---

RISK 08-R19: the non-Cognee branches of `KnowledgeProjectionCoordinator.compile` and
`_erase_one` are unreachable, because the loop above them already `continue`s on
`provider.id not in SUPPORTED_PROVIDER_IDS` and that set is exactly `{"cognee"}`. They read
as a live add-on path and are not one. DEAD.
[`boltrig/knowledge/projections.py:157`](../../../boltrig/knowledge/projections.py) `"if provider.id not in SUPPORTED_PROVIDER_IDS or not provider.enabled:"`
then `:161` `"else:"` with "needs its credential-backed projection adapter configured"; same
shape at `:279` `"if provider.id != \"cognee\":"`.

---

RISK 08-R20: `knowledge_projection_outbox` is created by migration 0034, listed in the RLS
overlay, and read or written by no application code. DEAD (bounded:
`rg -n "knowledge_projection_outbox" --glob '!migrations/**' .` returns only rls.sql,
schema.sql, and two test cleanup DELETEs, 2026-08-24).
[`migrations/versions/0034_knowledge_fabric.py:129`](../../../migrations/versions/0034_knowledge_fabric.py) `"CREATE TABLE IF NOT EXISTS knowledge_projection_outbox ("`.

---

RISK 08-R21: `knowledge_assets.deleted_at` exists and every read filters on it, but the
erase path issues a hard DELETE and nothing ever sets the column. A reader would reasonably
believe assets are soft-deleted and recoverable.
[`migrations/versions/0034_knowledge_fabric.py:37`](../../../migrations/versions/0034_knowledge_fabric.py) `"source_kind TEXT NOT NULL, source_ref TEXT, deleted_at TIMESTAMPTZ,"`
versus [`boltrig/knowledge/postgres_repository.py:277`](../../../boltrig/knowledge/postgres_repository.py) `"\"DELETE FROM knowledge_assets WHERE tenant_id=$1 AND id=$2\","`.

---

RISK 08-R22: Knowledge search uses an INNER `JOIN LATERAL` for the embedding, so a segment
with no embedding row is invisible to search entirely rather than merely scoring zero on
the vector term.
[`boltrig/knowledge/postgres_repository.py:235`](../../../boltrig/knowledge/postgres_repository.py) `"JOIN LATERAL ("` with `"ON true"` at `:239`.

---

RISK 08-R23: the bundle's episodic and source lanes share ONE similarity pass capped at
`memory.retrieval.max_results` (20). Twenty document chunks ranking above every episode
starve the episodic lane completely, and no warning says so.
[`boltrig/memory/bundle.py:217`](../../../boltrig/memory/bundle.py) `"hits = await recall(query, scopes)"`
with the limit set at [`boltrig/memory/typed_verbs.py:157`](../../../boltrig/memory/typed_verbs.py) `"limit = self._max_results"`.

---

RISK 08-R24: KNO-02's binding test asserts the projection status is `in {"written", "failed"}`,
which is the complete set of terminal statuses `_compile_cognee` can return, so that half
of the assertion cannot fail. The load-bearing half (commit succeeded, search still works)
does hold.
[`tests/knowledge/test_knowledge_service.py:201`](../../../tests/knowledge/test_knowledge_service.py) `"assert committed[\"projections\"][0][\"status\"] in {\"written\", \"failed\"}"`.

---

RISK 08-R25: `CogneeEngine`'s id-to-fact index and improve weights are PER PROCESS
(`self._index`, `self._weight`, `self._scopes`), so after a kernel restart a Cognee recall
returns nothing until facts are re-remembered, and a scope with a live cognee dataset is
invisible to `recall` because `self._scopes` is empty. The docstring admits the index is a
session cache but the recall path treats it as the authority on what exists.
[`boltrig/memory/cognee.py:28`](../../../boltrig/memory/cognee.py) `"per-process. The durable governance ledger is the kernel store's"`
and the hard gate at `:203` `"if not in_scope:"` returning `[]`.
