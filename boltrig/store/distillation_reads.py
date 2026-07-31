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

    async def count_pending_distillation(self, tenant_id: str, idle_before: datetime) -> int:
        """How many idle threads still await distillation, measured INDEPENDENTLY
        of the selection query.

        ``list_idle_conversations`` answers "what should this batch do". This
        answers "is there work at all", and it must not share the selection
        query's logic: the 2026-07-30 wedge was a bug INSIDE selection that made
        it return nothing, and any pending count derived from the same NOT EXISTS
        would inherit the same blind spot and report idle. Two plain counts -
        idle threads, and conversation receipts - share no logic with selection,
        so a selection bug leaves this number visibly non-zero while acted stays
        zero, which is precisely the stalled signal SweepProgress escalates.
        """
        # #43 changed this exactly as the prior note here demanded: a thread is
        # settled when a receipt is NEWER than its last message, not when any
        # receipt exists - so a CONTINUED thread counts as pending again. The
        # predicate is TIME-based on purpose while selection's is COUNT-based:
        # two different measures of the same fact, so a bug in either leaves the
        # other visibly disagreeing (pending>0 with acted=0), which is the
        # stalled signal SweepProgress escalates.
        #
        # fetchrow, not fetchval: _RlsPool exposes only fetch/fetchrow/execute,
        # and it is the pool every store call goes through (the beelink deploy
        # caught this - the in-memory tests never touch the pool).
        row = await self._pool.fetchrow(
            """SELECT count(*) AS n FROM conversations c
               WHERE c.tenant_id=$1 AND c.status='active' AND c.updated_at < $2
                 AND NOT EXISTS (
                   SELECT 1 FROM memory_ingestions i
                    WHERE i.tenant_id = c.tenant_id
                      AND i.source_kind = 'conversation'
                      AND i.source_ref = c.id
                      AND i.created_at >= c.updated_at)""",
            tenant_id,
            idle_before,
        )
        return int(row["n"])

    async def list_idle_conversations(
        self,
        tenant_id: str,
        idle_before: datetime,
        *,
        limit: int = 50,
        include_grown: bool = False,
    ) -> list[Any]:
        """Threads last touched before ``idle_before``, still open, NOT yet distilled.

        ``include_grown`` (task #43, ingest.incremental): a distilled thread whose
        live message count EXCEEDS the count its receipt recorded is eligible
        again. The predicate lives HERE, inside the SQL, for the same reason the
        NOT EXISTS does - filtered in Python after the LIMIT, a page full of
        distilled-and-unchanged threads wedges the sweep while a grown thread
        waits beyond it. A receipt with no recorded count is treated as settled
        (see backfill_distillation_baselines).

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
        settled = (
            """(i.detail->>'message_count') IS NOT NULL
                      AND (i.detail->>'message_count')::int >= (
                        SELECT count(*) FROM conversation_messages m
                         WHERE m.tenant_id = c.tenant_id
                           AND m.conversation_id = c.id)"""
            if include_grown
            else "TRUE"
        )
        rows = await self._pool.fetch(
            f"""SELECT c.* FROM conversations c
               WHERE c.tenant_id=$1 AND c.status='active' AND c.updated_at < $2
                 AND NOT EXISTS (
                   SELECT 1 FROM memory_ingestions i
                    WHERE i.tenant_id = c.tenant_id
                      AND i.source_kind = 'conversation'
                      AND i.source_ref = c.id
                      AND {settled})
               ORDER BY c.updated_at ASC LIMIT $3""",
            tenant_id,
            idle_before,
            max(1, min(limit, 500)),
        )
        return [_conversation(r) for r in rows]

    async def backfill_distillation_baselines(
        self, tenant_id: str, *, limit: int = 50
    ) -> int:
        """Stamp pre-#43 receipts with the live message count (bounded batch).

        A receipt from before #43 has no ``message_count``, so growth is
        undetectable against it. Re-distilling all of those in one sweep would
        re-write 365-day memory wholesale (89 threads on the beelink), so the
        CURRENT count becomes the baseline instead, and ``created_at`` refreshes
        to record that the thread was re-examined now - which also settles the
        time-based pending count for it. Growth is detectable from this moment
        on, which is the honest floor for a feature that shipped after the
        threads did. Returns how many receipts were stamped.
        """
        result = await self._pool.execute(
            """UPDATE memory_ingestions i
                  SET detail = coalesce(i.detail, '{}'::jsonb) || jsonb_build_object(
                        'message_count',
                        (SELECT count(*) FROM conversation_messages m
                          WHERE m.tenant_id = i.tenant_id
                            AND m.conversation_id = i.source_ref)),
                      created_at = now()
                WHERE (i.tenant_id, i.id) IN (
                  SELECT tenant_id, id FROM memory_ingestions
                   WHERE tenant_id=$1 AND source_kind='conversation'
                     AND (detail->>'message_count') IS NULL
                   LIMIT $2)""",
            tenant_id,
            max(1, min(limit, 500)),
        )
        try:
            return int(str(result).rsplit(" ", 1)[-1])
        except (ValueError, IndexError):
            return 0
