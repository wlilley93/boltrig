"""Memory-planes store domain (arc-1 structural partial): scope-filtered memory
items, structured memory governance (facts, ingestions, erasures, projection
statuses) and typed memory planes (decision 0029), extracted verbatim from
``store/postgres.py`` + ``store/memory.py``. PG host: ``self._pool``; Mem host:
``self._memory``/``_mem_facts``/``_mem_ingest``/``_mem_erase``/``_mem_projection``/
``_mem_events``. Public surface unchanged.
"""

from __future__ import annotations

from dataclasses import replace

from boltrig.models import (
    MemoryErasure, MemoryFact, MemoryIngestion, MemoryItem, MemoryProjectionStatus, utcnow,
)

from .rows import (
    _mem_erasure, _mem_event, _mem_fact, _mem_ingestion, _mem_projection, _memory,
)


class MemoryPlanesStorePG:
    async def add_memory_item(self, m: MemoryItem):
        await self._pool.execute(
            """INSERT INTO memory_items (id, tenant_id, owner_scope, kind, content, embedding, source_ref, data_class)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT (tenant_id, id) DO NOTHING""",
            m.id, m.tenant_id, m.owner_scope, m.kind, m.content, m.embedding, m.source_ref,
            m.data_class,
        )

    async def query_memory(self, tenant_id, owner_scopes, kind=None, limit=20):
        if kind is None:
            rows = await self._pool.fetch(
                """SELECT * FROM memory_items WHERE tenant_id=$1 AND owner_scope = ANY($2::text[])
                   ORDER BY created_at DESC LIMIT $3""",
                tenant_id, list(owner_scopes), limit,
            )
        else:
            rows = await self._pool.fetch(
                """SELECT * FROM memory_items WHERE tenant_id=$1 AND owner_scope = ANY($2::text[])
                   AND kind=$3 ORDER BY created_at DESC LIMIT $4""",
                tenant_id, list(owner_scopes), kind, limit,
            )
        return [_memory(r) for r in rows]

    async def add_memory_fact(self, f: MemoryFact):
        await self._pool.execute(
            """INSERT INTO memory_facts (id, tenant_id, owner_scope, engine_ref, kind,
                                         source_kind, source_ref, data_class, content, redacted,
                                         memory_key, status, version, confidence,
                                         valid_from, valid_to, payload, supersedes_id)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 owner_scope=EXCLUDED.owner_scope, engine_ref=EXCLUDED.engine_ref,
                 kind=EXCLUDED.kind, source_kind=EXCLUDED.source_kind,
                 source_ref=EXCLUDED.source_ref, data_class=EXCLUDED.data_class,
                 content=EXCLUDED.content, redacted=EXCLUDED.redacted,
                 memory_key=EXCLUDED.memory_key, status=EXCLUDED.status,
                 version=EXCLUDED.version, confidence=EXCLUDED.confidence,
                 valid_from=EXCLUDED.valid_from, valid_to=EXCLUDED.valid_to,
                 payload=EXCLUDED.payload, supersedes_id=EXCLUDED.supersedes_id""",
            f.id, f.tenant_id, f.owner_scope, f.engine_ref, f.kind, f.source_kind,
            f.source_ref, f.data_class, f.content, f.redacted,
            f.memory_key, f.status, f.version, f.confidence,
            f.valid_from, f.valid_to, f.payload, f.supersedes_id,
        )

    async def get_memory_fact(self, tenant_id, fact_id):
        row = await self._pool.fetchrow(
            "SELECT * FROM memory_facts WHERE tenant_id=$1 AND id=$2", tenant_id, fact_id
        )
        return _mem_fact(row)

    async def list_memory_facts(self, tenant_id, owner_scopes, kind=None, limit=50):
        if kind is None:
            rows = await self._pool.fetch(
                """SELECT * FROM memory_facts WHERE tenant_id=$1
                   AND owner_scope = ANY($2::text[]) ORDER BY created_at DESC LIMIT $3""",
                tenant_id, list(owner_scopes), limit,
            )
        else:
            rows = await self._pool.fetch(
                """SELECT * FROM memory_facts WHERE tenant_id=$1
                   AND owner_scope = ANY($2::text[]) AND kind=$3
                   ORDER BY created_at DESC LIMIT $4""",
                tenant_id, list(owner_scopes), kind, limit,
            )
        return [_mem_fact(r) for r in rows]

    async def delete_memory_fact(self, tenant_id, fact_id):
        await self._pool.execute(
            "DELETE FROM memory_facts WHERE tenant_id=$1 AND id=$2", tenant_id, fact_id
        )

    async def add_memory_ingestion(self, i: MemoryIngestion):
        await self._pool.execute(
            """INSERT INTO memory_ingestions (id, tenant_id, source_kind, source_ref,
                                              owner_scope, status, hatchet_run_id,
                                              facts_added, screened, detail, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 status=EXCLUDED.status, hatchet_run_id=EXCLUDED.hatchet_run_id,
                 facts_added=EXCLUDED.facts_added, screened=EXCLUDED.screened,
                 detail=EXCLUDED.detail""",
            i.id, i.tenant_id, i.source_kind, i.source_ref, i.owner_scope, i.status,
            i.hatchet_run_id, i.facts_added, i.screened, i.detail, i.created_at,
        )

    async def update_memory_ingestion(self, i: MemoryIngestion):
        await self.add_memory_ingestion(i)

    async def list_memory_ingestions(self, tenant_id, limit=50):
        rows = await self._pool.fetch(
            "SELECT * FROM memory_ingestions WHERE tenant_id=$1 ORDER BY created_at DESC LIMIT $2",
            tenant_id, limit,
        )
        return [_mem_ingestion(r) for r in rows]

    async def add_memory_erasure(self, e: MemoryErasure):
        await self._pool.execute(
            """INSERT INTO memory_erasures (id, tenant_id, requested_by, target, scope,
                                            engine_confirmed, transcript_handled,
                                            facts_removed, created_at, completed_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
               ON CONFLICT (tenant_id, id) DO NOTHING""",
            e.id, e.tenant_id, e.requested_by, e.target, e.scope, e.engine_confirmed,
            e.transcript_handled, e.facts_removed, e.created_at, e.completed_at,
        )

    async def list_memory_erasures(self, tenant_id, limit=50):
        rows = await self._pool.fetch(
            "SELECT * FROM memory_erasures WHERE tenant_id=$1 ORDER BY created_at DESC LIMIT $2",
            tenant_id, limit,
        )
        return [_mem_erasure(r) for r in rows]

    async def upsert_memory_projection_status(self, s: MemoryProjectionStatus):
        await self._pool.execute(
            """INSERT INTO memory_projection_statuses
               (id, tenant_id, projection_id, operation, status, fact_id, target,
                projection_ref, error, enqueue_attempts, operation_attempts,
                max_operation_attempts, first_attempt_at, last_attempt_at,
                last_failure_at, failure_code, created_at, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,
                       $16,$17,$18)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 status=EXCLUDED.status, projection_ref=EXCLUDED.projection_ref,
                 error=EXCLUDED.error,
                 enqueue_attempts=EXCLUDED.enqueue_attempts,
                 operation_attempts=EXCLUDED.operation_attempts,
                 max_operation_attempts=EXCLUDED.max_operation_attempts,
                 first_attempt_at=EXCLUDED.first_attempt_at,
                 last_attempt_at=EXCLUDED.last_attempt_at,
                 last_failure_at=EXCLUDED.last_failure_at,
                 failure_code=EXCLUDED.failure_code,
                 updated_at=EXCLUDED.updated_at""",
            s.id, s.tenant_id, s.projection_id, s.operation, s.status, s.fact_id,
            s.target, s.projection_ref, s.error, s.enqueue_attempts,
            s.operation_attempts, s.max_operation_attempts, s.first_attempt_at,
            s.last_attempt_at, s.last_failure_at, s.failure_code, s.created_at,
            s.updated_at,
        )

    async def list_memory_projection_statuses(self, tenant_id, fact_id=None, limit=50):
        if fact_id is None:
            rows = await self._pool.fetch(
                """SELECT * FROM memory_projection_statuses WHERE tenant_id=$1
                   ORDER BY updated_at DESC LIMIT $2""",
                tenant_id, limit,
            )
        else:
            rows = await self._pool.fetch(
                """SELECT * FROM memory_projection_statuses
                   WHERE tenant_id=$1 AND fact_id=$2
                   ORDER BY updated_at DESC LIMIT $3""",
                tenant_id, fact_id, limit,
            )
        return [_mem_projection(r) for r in rows]

    async def get_active_memory_fact(self, tenant_id, memory_key):
        row = await self._pool.fetchrow(
            """SELECT * FROM memory_facts
               WHERE tenant_id=$1 AND memory_key=$2 AND status='active'
                 AND (valid_to IS NULL OR valid_to > now())
               ORDER BY version DESC LIMIT 1""",
            tenant_id, memory_key,
        )
        return _mem_fact(row)

    async def list_active_subject_facts(
        self, tenant_id, owner_scopes, subject_type, subject_id, limit=64
    ):
        prefix = f"{subject_type}::{subject_id}::%"
        rows = await self._pool.fetch(
            """SELECT * FROM memory_facts
               WHERE tenant_id=$1 AND owner_scope = ANY($2::text[])
                 AND memory_key LIKE $3 AND status='active'
                 AND (valid_to IS NULL OR valid_to > now())
               ORDER BY created_at DESC LIMIT $4""",
            tenant_id, list(owner_scopes), prefix, limit,
        )
        return [_mem_fact(r) for r in rows]

    async def list_memory_slot_history(self, tenant_id, memory_key, limit=50):
        rows = await self._pool.fetch(
            """SELECT * FROM memory_facts
               WHERE tenant_id=$1 AND memory_key=$2
               ORDER BY version DESC LIMIT $3""",
            tenant_id, memory_key, limit,
        )
        return [_mem_fact(r) for r in rows]

    async def list_memory_candidates(self, tenant_id, owner_scopes, limit=50):
        rows = await self._pool.fetch(
            """SELECT * FROM memory_facts
               WHERE tenant_id=$1 AND owner_scope = ANY($2::text[])
                 AND status='candidate'
               ORDER BY created_at DESC LIMIT $3""",
            tenant_id, list(owner_scopes), limit,
        )
        return [_mem_fact(r) for r in rows]

    async def update_memory_fact(self, fact):
        await self._pool.execute(
            """UPDATE memory_facts SET
                 owner_scope=$3, kind=$4, source_kind=$5, source_ref=$6,
                 data_class=$7, content=$8, redacted=$9,
                 memory_key=$10, status=$11, version=$12, confidence=$13,
                 valid_from=$14, valid_to=$15, payload=$16, supersedes_id=$17
               WHERE tenant_id=$1 AND id=$2""",
            fact.tenant_id, fact.id, fact.owner_scope, fact.kind, fact.source_kind,
            fact.source_ref, fact.data_class, fact.content, fact.redacted,
            fact.memory_key, fact.status, fact.version, fact.confidence,
            fact.valid_from, fact.valid_to, fact.payload, fact.supersedes_id,
        )

    async def add_memory_event(self, e):
        await self._pool.execute(
            """INSERT INTO memory_events (id, tenant_id, memory_id, memory_key,
                                          event, decision, policy_version, detail, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
               ON CONFLICT (tenant_id, id) DO NOTHING""",
            e.id, e.tenant_id, e.memory_id, e.memory_key, e.event, e.decision,
            e.policy_version, e.detail, e.created_at,
        )

    async def list_memory_events(self, tenant_id, *, memory_id=None, memory_key=None, limit=100):
        if memory_id is not None:
            rows = await self._pool.fetch(
                """SELECT * FROM memory_events WHERE tenant_id=$1 AND memory_id=$2
                   ORDER BY created_at DESC LIMIT $3""",
                tenant_id, memory_id, limit,
            )
        elif memory_key is not None:
            rows = await self._pool.fetch(
                """SELECT * FROM memory_events WHERE tenant_id=$1 AND memory_key=$2
                   ORDER BY created_at DESC LIMIT $3""",
                tenant_id, memory_key, limit,
            )
        else:
            rows = await self._pool.fetch(
                """SELECT * FROM memory_events WHERE tenant_id=$1
                   ORDER BY created_at DESC LIMIT $2""",
                tenant_id, limit,
            )
        return [_mem_event(r) for r in rows]


class MemoryPlanesStoreMem:
    async def add_memory_item(self, item):
        self._memory.append(item)

    async def query_memory(self, tenant_id, owner_scopes, kind=None, limit=20):
        scopes = set(owner_scopes)
        out = [
            m
            for m in self._memory
            if m.tenant_id == tenant_id
            and m.owner_scope in scopes
            and (kind is None or m.kind == kind)
        ]
        # newest-first, matching the Postgres ORDER BY created_at DESC contract.
        return sorted(out, key=lambda m: m.created_at, reverse=True)[:limit]

    async def add_memory_fact(self, fact):
        self._mem_facts[(fact.tenant_id, fact.id)] = fact

    async def get_memory_fact(self, tenant_id, fact_id):
        return self._mem_facts.get((tenant_id, fact_id))

    async def list_memory_facts(self, tenant_id, owner_scopes, kind=None, limit=50):
        scopes = set(owner_scopes)
        out = [
            f
            for (t, _), f in self._mem_facts.items()
            if t == tenant_id and f.owner_scope in scopes and (kind is None or f.kind == kind)
        ]
        return sorted(out, key=lambda f: f.created_at, reverse=True)[:limit]

    async def delete_memory_fact(self, tenant_id, fact_id):
        self._mem_facts.pop((tenant_id, fact_id), None)

    async def add_memory_ingestion(self, ing):
        self._mem_ingest[(ing.tenant_id, ing.id)] = ing

    async def update_memory_ingestion(self, ing):
        self._mem_ingest[(ing.tenant_id, ing.id)] = ing

    async def list_memory_ingestions(self, tenant_id, limit=50):
        out = [i for (t, _), i in self._mem_ingest.items() if t == tenant_id]
        return sorted(out, key=lambda i: i.created_at, reverse=True)[:limit]

    async def add_memory_erasure(self, er):
        self._mem_erase.append(er)

    async def list_memory_erasures(self, tenant_id, limit=50):
        out = [e for e in self._mem_erase if e.tenant_id == tenant_id]
        return sorted(out, key=lambda e: e.created_at, reverse=True)[:limit]

    async def upsert_memory_projection_status(self, status):
        key = (status.tenant_id, status.id)
        previous = self._mem_projection.get(key)
        self._mem_projection[key] = (
            replace(status, created_at=previous.created_at) if previous is not None else status
        )

    async def list_memory_projection_statuses(self, tenant_id, fact_id=None, limit=50):
        out = [
            s
            for (t, _), s in self._mem_projection.items()
            if t == tenant_id and (fact_id is None or s.fact_id == fact_id)
        ]
        return sorted(out, key=lambda s: s.updated_at, reverse=True)[:limit]

    async def get_active_memory_fact(self, tenant_id, memory_key):
        # Newest non-expired active wins in the twin, mirroring the DB's
        # one-active index plus the expiry filter (MEM-TYP-01: an expired
        # value is history, not the current truth).
        now = utcnow()
        hits = [
            f
            for (t, _), f in self._mem_facts.items()
            if t == tenant_id
            and f.memory_key == memory_key
            and f.status == "active"
            and (f.valid_to is None or f.valid_to > now)
        ]
        return max(hits, key=lambda f: (f.version, f.created_at)) if hits else None

    async def list_active_subject_facts(
        self, tenant_id, owner_scopes, subject_type, subject_id, limit=64
    ):
        scopes = set(owner_scopes)
        prefix = f"{subject_type}::{subject_id}::"
        out = [
            f
            for (t, _), f in self._mem_facts.items()
            if t == tenant_id
            and f.owner_scope in scopes
            and f.memory_key is not None
            and f.memory_key.startswith(prefix)
            and f.status == "active"
            and (f.valid_to is None or f.valid_to > utcnow())
        ]
        return sorted(out, key=lambda f: f.created_at, reverse=True)[:limit]

    async def list_memory_slot_history(self, tenant_id, memory_key, limit=50):
        out = [
            f
            for (t, _), f in self._mem_facts.items()
            if t == tenant_id and f.memory_key == memory_key
        ]
        return sorted(out, key=lambda f: f.version, reverse=True)[:limit]

    async def list_memory_candidates(self, tenant_id, owner_scopes, limit=50):
        scopes = set(owner_scopes)
        out = [
            f
            for (t, _), f in self._mem_facts.items()
            if t == tenant_id and f.owner_scope in scopes and f.status == "candidate"
        ]
        return sorted(out, key=lambda f: f.created_at, reverse=True)[:limit]

    async def update_memory_fact(self, fact):
        self._mem_facts[(fact.tenant_id, fact.id)] = fact

    async def add_memory_event(self, event):
        self._mem_events[(event.tenant_id, event.id)] = event

    async def list_memory_events(self, tenant_id, *, memory_id=None, memory_key=None, limit=100):
        out = [
            e
            for (t, _), e in self._mem_events.items()
            if t == tenant_id
            and (memory_id is None or e.memory_id == memory_id)
            and (memory_key is None or e.memory_key == memory_key)
        ]
        return sorted(out, key=lambda e: e.created_at, reverse=True)[:limit]
