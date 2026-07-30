"""The two reads session distillation needs, which no existing method provides.

``list_conversations`` requires a ``user_id``, so there is no tenant-wide sweep for
"which threads have gone quiet". And ``list_memory_ingestions`` takes a bare
``limit`` and returns newest-first, so asking "have we already distilled this
thread?" through it is a scan that is correct only while the answer happens to sit
inside the window - a check that passes until the data grows.

Both live here rather than in ``postgres.py``, which sits at its size ratchet.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from boltrig.models.memory import MemoryIngestion

from .rows import _conversation, _mem_ingestion


class DistillationReadsPG:
    """Tenant-wide idle-thread and ingestion-by-source reads for a Postgres store."""

    _pool: Any

    async def get_memory_ingestion_by_source(
        self, tenant_id: str, source_kind: str, source_ref: str
    ) -> MemoryIngestion | None:
        row = await self._pool.fetchrow(
            """SELECT * FROM memory_ingestions
               WHERE tenant_id=$1 AND source_kind=$2 AND source_ref=$3
               ORDER BY created_at DESC LIMIT 1""",
            tenant_id,
            source_kind,
            source_ref,
        )
        return _mem_ingestion(row) if row else None

    async def list_idle_conversations(
        self, tenant_id: str, idle_before: datetime, *, limit: int = 50
    ) -> list[Any]:
        """Threads last touched before ``idle_before``, still open, NOT yet distilled.

        ``status='active'`` is deliberate: retention.py soft-closes a deleted
        thread to CLOSED, and a thread the user asked to delete must not then be
        distilled into 365-day memory. Oldest first, so a backlog drains in the
        order it accumulated rather than starving the oldest thread forever.

        THE NOT EXISTS IS WHAT MAKES THE LIMIT MEAN ANYTHING. Filtering distilled
        threads in Python AFTER a SQL LIMIT wedges the sweep permanently: the same
        oldest N come back every time, all are discarded, and the rest are never
        fetched. Measured on the beelink 2026-07-30 - 20 of 89 written, then
        nothing, with no error and a healthy worker. The LIMIT has to apply to rows
        that are genuinely eligible, which means the exclusion belongs here.
        """
        rows = await self._pool.fetch(
            """SELECT c.* FROM conversations c
               WHERE c.tenant_id=$1 AND c.status='active' AND c.updated_at < $2
                 AND NOT EXISTS (
                   SELECT 1 FROM memory_ingestions i
                    WHERE i.tenant_id = c.tenant_id
                      AND i.source_kind = 'conversation'
                      AND i.source_ref = c.id)
               ORDER BY c.updated_at ASC LIMIT $3""",
            tenant_id,
            idle_before,
            max(1, min(limit, 500)),
        )
        return [_conversation(r) for r in rows]
