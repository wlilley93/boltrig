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
        """Threads last touched before ``idle_before`` and still open.

        ``status='active'`` is deliberate: retention.py soft-closes a deleted
        thread to CLOSED, and a thread the user asked to delete must not then be
        distilled into 365-day memory. Oldest first, so a backlog drains in the
        order it accumulated rather than starving the oldest thread forever.
        """
        rows = await self._pool.fetch(
            """SELECT * FROM conversations
               WHERE tenant_id=$1 AND status='active' AND updated_at < $2
               ORDER BY updated_at ASC LIMIT $3""",
            tenant_id,
            idle_before,
            max(1, min(limit, 500)),
        )
        return [_conversation(r) for r in rows]
