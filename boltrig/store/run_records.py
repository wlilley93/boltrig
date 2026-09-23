"""Run-record store domain (arc-1 structural partial).

The execution-record write path - workflow run records, work-item writes and
leases, fanout counters, run checkpoints and run-cancellation markers -
extracted verbatim from ``store/postgres.py`` + ``store/memory.py``.
``PostgresStore`` mixes in :class:`RunRecordsStorePG`; ``InMemoryStore`` mixes
in :class:`RunRecordsStoreMem`. Public surface unchanged; work-item READS
already live in ``store/work_items.py``.

Host contract: PG uses ``self._pool``; Mem uses ``self._workflow_runs`` /
``self._work`` / ``self._fanout`` / ``self._checkpoints`` / ``self._cancels``.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from boltrig.models import WorkItem, utcnow
from boltrig.models.work import RunCheckpoint, WorkStatus

from .rows import _checkpoint
from .work_items import work_item_from_row


class RunRecordsStorePG:
    """Run-record methods for ``PostgresStore`` (uses ``self._pool``)."""

    async def record_workflow_run(self, tenant_id, workflow_id, run_id, status):
        # Insert/replace on the (tenant_id, run_id) PK. ON CONFLICT DO NOTHING
        # preserves the original started_at for a re-recorded run_id (idempotent
        # re-recording of the same run never bumps its start time forward).
        await self._pool.execute(
            """INSERT INTO workflow_run_records (tenant_id, workflow_id, run_id, status)
               VALUES ($1,$2,$3,$4)
               ON CONFLICT (tenant_id, run_id) DO NOTHING""",
            tenant_id, workflow_id, run_id, status,
        )

    async def list_workflow_run_ids(self, tenant_id, workflow_id, limit=100):
        rows = await self._pool.fetch(
            """SELECT run_id FROM workflow_run_records
               WHERE tenant_id=$1 AND workflow_id=$2
               ORDER BY started_at DESC LIMIT $3""",
            tenant_id,
            workflow_id,
            max(0, min(limit, 1000)),
        )
        return [row["run_id"] for row in rows]

    async def workflow_run_stats(self, tenant_id):
        rows = await self._pool.fetch(
            """SELECT workflow_id,
                      COUNT(*) AS run_count,
                      COUNT(*) FILTER (WHERE status='completed') AS success_count,
                      MAX(started_at) AS last_run_at
               FROM workflow_run_records
               WHERE tenant_id=$1
               GROUP BY workflow_id
               ORDER BY workflow_id""",
            tenant_id,
        )
        return [
            {"workflow_id": r["workflow_id"], "run_count": int(r["run_count"]),
             "success_count": int(r["success_count"]),
             "last_run_at": r["last_run_at"]}
            for r in rows
        ]

    async def create_work_item(self, w: WorkItem):
        await self._pool.execute(
            """INSERT INTO work_items (id, tenant_id, workspace_id, source, source_id, intent, confidence,
                                       convergent, status, owner_member, parent_id, hatchet_run_id,
                                       depth, on_behalf_of, constraints, raw, attempts, degraded,
                                       result, lease_owner, lease_expires_at, target, reply_route)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23)
               ON CONFLICT (tenant_id, id) DO UPDATE SET
                 workspace_id=EXCLUDED.workspace_id, source=EXCLUDED.source, source_id=EXCLUDED.source_id, intent=EXCLUDED.intent,
                 confidence=EXCLUDED.confidence, convergent=EXCLUDED.convergent,
                 status=EXCLUDED.status, owner_member=EXCLUDED.owner_member,
                 parent_id=EXCLUDED.parent_id, hatchet_run_id=EXCLUDED.hatchet_run_id,
                 depth=EXCLUDED.depth, on_behalf_of=EXCLUDED.on_behalf_of,
                 constraints=EXCLUDED.constraints, raw=EXCLUDED.raw,
                 attempts=EXCLUDED.attempts, degraded=EXCLUDED.degraded,
                 result=EXCLUDED.result, lease_owner=EXCLUDED.lease_owner,
                 lease_expires_at=EXCLUDED.lease_expires_at,
                 target=EXCLUDED.target, reply_route=EXCLUDED.reply_route, updated_at=now()""",
            w.id, w.tenant_id, w.workspace_id, w.source, w.source_id, w.intent, w.confidence, w.convergent,
            w.status.value, w.owner_member, w.parent_id, w.hatchet_run_id, w.depth,
            w.on_behalf_of, w.constraints, w.raw, w.attempts, w.degraded, w.result,
            w.lease_owner, w.lease_expires_at, w.target, w.reply_route,
        )

    async def update_work_item(self, item: WorkItem):
        await self.create_work_item(item)  # upsert

    async def update_work_item_if_leased(
        self, item: WorkItem, *, lease_owner: str | None, lease_expires_at: datetime | None
    ) -> bool:
        """Write the row ONLY if it still carries the lease the caller was given.

        Returns True if it wrote, False if the lease moved. The predicate is
        evaluated HERE, by the party that serialises the write, in the same
        statement ([2026] VJS-CC-BOLTRIG-WORK-ITEM-LEASE-FENCE-001 D1). That is the
        whole point: a read-then-write check in the caller cannot decide a
        read-then-write race, which is why the earlier `_still_leased` helper was
        defeated by a reviewer who applied it and reproduced the original defect.

        The expected tuple must be the one MINTED AT CLAIM and carried to this
        body, never one the body re-read. A CAS whose expectation is re-derived at
        body start inherits the identical defect.

        Deliberately a distinct method rather than a keyword on update_work_item,
        so a call site that must be fenced is greppable and an unfenced write to a
        claimed row is visible in review.
        """
        row = await self._pool.fetchrow(
            """UPDATE work_items SET
                 workspace_id=$3, source=$4, source_id=$5, intent=$6, confidence=$7,
                 convergent=$8, status=$9, owner_member=$10, parent_id=$11,
                 hatchet_run_id=$12, depth=$13, on_behalf_of=$14, constraints=$15,
                 raw=$16, attempts=$17, degraded=$18, result=$19, lease_owner=$20,
                 lease_expires_at=$21, target=$22, reply_route=$23, updated_at=now()
               WHERE tenant_id=$1 AND id=$2
                 AND lease_owner IS NOT DISTINCT FROM $24
                 AND lease_expires_at IS NOT DISTINCT FROM $25
               RETURNING id""",
            item.tenant_id, item.id, item.workspace_id, item.source, item.source_id,
            item.intent, item.confidence, item.convergent, item.status.value,
            item.owner_member, item.parent_id, item.hatchet_run_id, item.depth,
            item.on_behalf_of, item.constraints, item.raw, item.attempts,
            item.degraded, item.result, item.lease_owner, item.lease_expires_at,
            item.target, item.reply_route, lease_owner, lease_expires_at,
        )
        return row is not None

    async def transition_work_item_status(self, tenant_id, item_id, *, expected, new_status):
        # Conditional status write (CAS on the guarded status): a concurrent
        # transition that already moved the row matches 0 rows, so the loser
        # fails instead of silently overwriting the winner.
        row = await self._pool.fetchrow(
            """UPDATE work_items SET status=$4, updated_at=now()
               WHERE tenant_id=$1 AND id=$2 AND status=$3 RETURNING id""",
            tenant_id, item_id, expected.value, new_status.value,
        )
        return row is not None

    async def transition_work_item_settled(
        self, tenant_id, item_id, *, expected, new_status, result
    ):
        # The payload-carrying twin: status CAS + lease clear + result stamp in
        # ONE conditional UPDATE, so a sweeper's settle carries its reason
        # without a read-then-write window a concurrent re-queue can slip into.
        row = await self._pool.fetchrow(
            """UPDATE work_items
                  SET status=$4, lease_owner=NULL, lease_expires_at=NULL,
                      result=$5, updated_at=now()
               WHERE tenant_id=$1 AND id=$2 AND status=$3 RETURNING id""",
            tenant_id, item_id, expected.value, new_status.value, result,
        )
        return row is not None

    async def claim_work_item(self, tenant_id, worker_id, lease_seconds):
        # atomic pending -> in_flight claim with a lease (US-FLT-05): one
        # statement, FOR UPDATE SKIP LOCKED so concurrent claimers never block
        # or double-claim; an expired lease is reclaimable. RETURNING tells us
        # if we won (mirrors consume_hitl).
        row = await self._pool.fetchrow(
            """UPDATE work_items
               SET status='in_flight', lease_owner=$2,
                   lease_expires_at=now() + make_interval(secs => $3),
                   attempts=attempts+1, updated_at=now()
               WHERE tenant_id=$1 AND id IN (
                 SELECT id FROM work_items
                 WHERE tenant_id=$1 AND (status='pending'
                        OR (status='in_flight' AND lease_expires_at < now()))
                 ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED
               )
               RETURNING *""",
            tenant_id, worker_id, float(lease_seconds),
        )
        return work_item_from_row(row)

    async def try_increment_fanout(self, tenant_id, tree_id, counter, n, cap):
        # atomic capped increment (US-EXE-07): the conditional upsert applies
        # the whole increment or none; no row returned means refused. The INSERT
        # arm has no WHERE, so an over-cap first increment is refused up front.
        if n > cap:
            return False
        row = await self._pool.fetchrow(
            """INSERT INTO fanout_counters (tenant_id, tree_id, counter, value)
               VALUES ($1,$2,$3,$4)
               ON CONFLICT (tenant_id, tree_id, counter) DO UPDATE
                 SET value = fanout_counters.value + EXCLUDED.value
                 WHERE fanout_counters.value + EXCLUDED.value <= $5
               RETURNING value""",
            tenant_id, tree_id, counter, n, cap,
        )
        return row is not None

    async def upsert_checkpoint(
        self, tenant_id, run_id, step, status, output=None, hitl_request_id=None
    ):
        await self._pool.execute(
            """INSERT INTO run_checkpoints (tenant_id, run_id, step, status, output,
                                            hitl_request_id, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,now())
               ON CONFLICT (tenant_id, run_id, step) DO UPDATE SET
                 status=EXCLUDED.status, output=EXCLUDED.output,
                 hitl_request_id=EXCLUDED.hitl_request_id, updated_at=now()""",
            tenant_id, run_id, step, status, output, hitl_request_id,
        )

    async def list_checkpoints(self, tenant_id, run_id):
        rows = await self._pool.fetch(
            """SELECT * FROM run_checkpoints WHERE tenant_id=$1 AND run_id=$2
               ORDER BY updated_at, step""",
            tenant_id, run_id,
        )
        return [_checkpoint(r) for r in rows]

    async def request_run_cancel(self, tenant_id, run_id, requested_by):
        # Idempotent marker (D2): INSERT .. ON CONFLICT DO NOTHING, so a
        # re-request never overwrites the original requester. Durable across
        # restarts - the row is the backstop that stops a cancelled run being
        # resurrected (the pump re-detects it and re-writes CANCELLED).
        await self._pool.execute(
            """INSERT INTO run_cancel_requests (tenant_id, run_id, requested_by)
               VALUES ($1,$2,$3)
               ON CONFLICT (tenant_id, run_id) DO NOTHING""",
            tenant_id, run_id, requested_by,
        )

    async def is_run_cancel_requested(self, tenant_id, run_id):
        row = await self._pool.fetchrow(
            "SELECT 1 FROM run_cancel_requests WHERE tenant_id=$1 AND run_id=$2",
            tenant_id, run_id,
        )
        return row is not None


class RunRecordsStoreMem:
    """Run-record methods for ``InMemoryStore``."""

    async def record_workflow_run(self, tenant_id, workflow_id, run_id, status):
        # Insert-only on the run_id PK, matching the postgres ON CONFLICT DO
        # NOTHING: a re-record keeps the first status and started_at.
        key = (tenant_id, run_id)
        if key not in self._workflow_runs:
            self._workflow_runs[key] = (workflow_id, status, utcnow())

    async def list_workflow_run_ids(self, tenant_id, workflow_id, limit=100):
        rows = [
            (started, run_id)
            for (tenant, run_id), (wf_id, _status, started) in self._workflow_runs.items()
            if tenant == tenant_id and wf_id == workflow_id
        ]
        rows.sort(reverse=True)
        return [run_id for _started, run_id in rows[: max(0, min(limit, 1000))]]

    async def workflow_run_stats(self, tenant_id):
        # Aggregate per workflow_id: run_count, success_count (status == completed),
        # last_run_at (max started_at). Ordered by workflow_id, matching postgres.
        buckets: dict[str, dict] = {}
        for (t, _run_id), (wf_id, status, started) in self._workflow_runs.items():
            if t != tenant_id:
                continue
            b = buckets.setdefault(wf_id, {"run_count": 0, "success_count": 0, "last_run_at": None})
            b["run_count"] += 1
            if status == "completed":
                b["success_count"] += 1
            if b["last_run_at"] is None or started > b["last_run_at"]:
                b["last_run_at"] = started
        return [
            {
                "workflow_id": wf_id,
                "run_count": b["run_count"],
                "success_count": b["success_count"],
                "last_run_at": b["last_run_at"],
            }
            for wf_id, b in sorted(buckets.items())
        ]

    # Store a COPY, and hand back copies on read (see work_items._detached). The
    # store used to alias the caller's object in both directions, so a caller
    # mutating a row after writing it changed the store with no write call, and a
    # conditional write would compare a stored object against itself and always
    # agree. Postgres has never aliased; this is the parity repair
    # ([2026] VJS-CC-BOLTRIG-WORK-ITEM-LEASE-FENCE-001 D6).
    async def create_work_item(self, item):
        self._work[(item.tenant_id, item.id)] = replace(item)

    async def update_work_item(self, item):
        self._work[(item.tenant_id, item.id)] = replace(item)

    async def update_work_item_if_leased(self, item, *, lease_owner, lease_expires_at):
        """Write ONLY if the stored row still carries the lease the caller was
        given; return whether it wrote (D1).

        Mirrors the Postgres UPDATE ... WHERE lease_owner=$ AND lease_expires_at=$.
        No await between the compare and the write, so it is atomic on the
        single-threaded loop, the same argument transition_work_item_status and
        claim_work_item already rely on.

        The comparison is against the STORED row, which is only meaningful because
        the store no longer hands callers that row: before the copy-on-read repair
        the caller's `item` could BE the stored object and every comparison would
        trivially pass.
        """
        stored = self._work.get((item.tenant_id, item.id))
        if stored is None:
            return False
        if stored.lease_owner != lease_owner or stored.lease_expires_at != lease_expires_at:
            return False
        self._work[(item.tenant_id, item.id)] = replace(item)
        return True

    async def transition_work_item_status(self, tenant_id, item_id, *, expected, new_status):
        # Conditional status write (mirrors the PG UPDATE ... WHERE status=$):
        # no await between the check and the write, so it is atomic on the
        # single-threaded event loop; a moved row fails the CAS.
        item = self._work.get((tenant_id, item_id))
        if item is None or item.status != expected:
            return False
        item.status = new_status
        return True

    async def transition_work_item_settled(
        self, tenant_id, item_id, *, expected, new_status, result
    ):
        # The payload-carrying twin: status CAS + lease clear + result stamp in
        # one conditional write (same event-loop-atomicity argument as above).
        item = self._work.get((tenant_id, item_id))
        if item is None or item.status != expected:
            return False
        item.status = new_status
        item.lease_owner = None
        item.lease_expires_at = None
        item.result = result
        return True

    async def claim_work_item(self, tenant_id, worker_id, lease_seconds):
        # atomic pending -> in_flight claim with a lease (US-FLT-05): no await between
        # scan and write (mirrors consume_hitl); insertion order stands in for the
        # Postgres ORDER BY created_at (oldest first).
        now = utcnow()
        for (t, _), item in self._work.items():
            if t != tenant_id:
                continue
            claimable = item.status == WorkStatus.PENDING or (
                item.status == WorkStatus.IN_FLIGHT
                and item.lease_expires_at is not None
                and item.lease_expires_at < now
            )
            if not claimable:
                continue
            item.status = WorkStatus.IN_FLIGHT
            item.lease_owner = worker_id
            item.lease_expires_at = now + timedelta(seconds=lease_seconds)
            item.attempts += 1
            # A copy: the claimer must not hold the stored object, or its own
            # later mutations would land in the store unwritten.
            return replace(item)
        return None

    async def try_increment_fanout(self, tenant_id, tree_id, counter, n, cap):
        # atomic capped increment (US-EXE-07): all-or-nothing, no await between read/write.
        key = (tenant_id, tree_id, counter)
        new_value = self._fanout.get(key, 0) + n
        if new_value > cap:
            return False
        self._fanout[key] = new_value
        return True

    async def upsert_checkpoint(
        self, tenant_id, run_id, step, status, output=None, hitl_request_id=None
    ):
        self._checkpoints[(tenant_id, run_id, step)] = RunCheckpoint(
            tenant_id=tenant_id,
            run_id=run_id,
            step=step,
            status=status,
            output=output,
            hitl_request_id=hitl_request_id,
            updated_at=utcnow(),
        )

    async def list_checkpoints(self, tenant_id, run_id):
        out = [c for (t, r, _), c in self._checkpoints.items() if t == tenant_id and r == run_id]
        # oldest-first with a step tiebreak, matching the Postgres ORDER BY.
        return sorted(out, key=lambda c: (c.updated_at, c.step))

    async def request_run_cancel(self, tenant_id, run_id, requested_by):
        # Idempotent marker (D2): the first request wins, a re-request is a no-op
        # so the original requester is never overwritten. Durable for the process
        # lifetime (the Postgres row is durable across restarts).
        self._cancels.setdefault((tenant_id, run_id), requested_by)

    async def is_run_cancel_requested(self, tenant_id, run_id):
        return (tenant_id, run_id) in self._cancels
