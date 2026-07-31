"""In-memory distillation reads - the twin of ``distillation_reads.py`` (PG).

One mixin per concern, like the other *_memory.py files. Split out with #43,
when the growth-aware selection and the time-based pending count made this a
real surface rather than two small methods: the two twins carry the SAME two
predicates on purpose - selection COUNT-based, pending TIME-based - so a bug in
either leaves the other visibly disagreeing (pending>0 with acted=0), which is
the stalled signal SweepProgress escalates.
"""

from __future__ import annotations


class DistillationReadsMem:
    """Requires ``self._convs``, ``self._mem_ingest`` and ``self._messages``."""

    async def count_pending_distillation(self, tenant_id, idle_before):
        # #43: a thread is settled when a receipt is NEWER than its last message,
        # so a CONTINUED thread counts as pending again. TIME-based on purpose
        # while selection's predicate is COUNT-based - two measures of the same
        # fact, so a bug in either leaves the other visibly disagreeing.
        settled = {
            i.source_ref: i.created_at
            for (t, _), i in sorted(
                self._mem_ingest.items(), key=lambda kv: kv[1].created_at
            )
            if t == tenant_id and i.source_kind == "conversation"
        }
        return len(
            [
                c
                for (t, _), c in self._convs.items()
                if t == tenant_id
                and getattr(c, "status", "active") == "active"
                and c.updated_at < idle_before
                and not (c.id in settled and settled[c.id] >= c.updated_at)
            ]
        )

    def _distillation_settled(self, tenant_id, conv_id, *, include_grown):
        """Whether a receipt settles this thread (the Postgres twin's predicate)."""
        receipts = [
            i
            for (t, _), i in self._mem_ingest.items()
            if t == tenant_id and i.source_kind == "conversation" and i.source_ref == conv_id
        ]
        if not receipts:
            return False
        if not include_grown:
            return True
        receipt = max(receipts, key=lambda i: i.created_at)
        recorded = receipt.detail.get("message_count")
        if not isinstance(recorded, int):
            return True  # no baseline: settled; backfill stamps it (task #43)
        live = len(self._messages.get(conv_id, []))
        return recorded >= live

    async def list_idle_conversations(
        self, tenant_id, idle_before, *, limit=50, include_grown=False
    ):
        # Excludes settled threads HERE, before the limit, exactly as the
        # Postgres twin does - filtering after the limit wedges the sweep.
        # include_grown (#43): a distilled thread that GREW past its receipt's
        # recorded message_count is eligible again.
        out = [
            c
            for (t, _), c in self._convs.items()
            if t == tenant_id
            and getattr(c, "status", "active") == "active"
            and c.updated_at < idle_before
            and not self._distillation_settled(
                tenant_id, c.id, include_grown=include_grown
            )
        ]
        return sorted(out, key=lambda c: c.updated_at)[: max(1, min(limit, 500))]

    async def backfill_distillation_baselines(self, tenant_id, *, limit=50):
        """Stamp pre-#43 receipts with the live message count (bounded batch).

        Mirrors the Postgres twin: the current count becomes the baseline rather
        than re-writing 365-day memory wholesale, and created_at refreshes to
        record the re-examination (settling the time-based pending count too).
        """
        from boltrig.models import utcnow

        stamped = 0
        for (t, _), i in list(self._mem_ingest.items()):
            if stamped >= max(1, min(limit, 500)):
                break
            if (
                t == tenant_id
                and i.source_kind == "conversation"
                and not isinstance(i.detail.get("message_count"), int)
            ):
                i.detail["message_count"] = len(self._messages.get(i.source_ref, []))
                i.created_at = utcnow()
                stamped += 1
        return stamped
