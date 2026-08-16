"""The trajectory's Postgres store, fenced by row-level security.

DECORATED, AND THAT IS NOT OPTIONAL. ``bind_tenant_on_store_methods`` sets
``app.tenant_id`` per call from each method's own ``tenant_id`` argument, which
is what RLS policies read. Passing the tenant in a WHERE clause is NOT the same
thing: the fence is the GUC, and a class that holds an ``_RlsPool`` without
binding it writes rows RLS cannot police.

This class is exactly the case tests/unit/test_rls_pool.py was written to catch
-- "a THIRD such class, added later" that holds its own pool outside the
PostgresStore MRO. It failed there first, which is the point of the invariant.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from boltrig.models import TrajectoryEvent, TrajectoryKind, utcnow
from boltrig.store.tenant_scope import bind_tenant_on_store_methods


@bind_tenant_on_store_methods
class PostgresTrajectoryStore:
    """Production. Takes the pool directly rather than reaching into a Store."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def append_trajectory(
        self,
        tenant_id: str,
        run_id: str,
        kind: TrajectoryKind,
        payload: dict[str, Any],
        *,
        actor: str = "unknown",
        parent_run_id: str | None = None,
        depth: int = 0,
        ttl_days: int = 14,
    ) -> TrajectoryEvent:
        # The SEQUENCE IS ASSIGNED BY THE DATABASE, in the same statement as the
        # insert. Reading max(seq) and adding one in Python is the classic
        # read-modify-write race, and two tool calls finishing together in one
        # run would produce duplicate rows and an order that is a coin toss.
        row = await self._pool.fetchrow(
            """INSERT INTO trajectory_events (
                 tenant_id, run_id, seq, kind, payload, actor,
                 parent_run_id, depth, expires_at
               )
               VALUES (
                 $1, $2,
                 (SELECT COALESCE(MAX(seq), 0) + 1
                    FROM trajectory_events
                   WHERE tenant_id = $1 AND run_id = $2),
                 $3, $4, $5, $6, $7, now() + ($8 || ' days')::interval
               )
               RETURNING seq, at, expires_at""",
            tenant_id, run_id, kind.value, payload, actor,
            parent_run_id, depth, str(ttl_days),
        )
        return TrajectoryEvent(
            tenant_id=tenant_id,
            run_id=run_id,
            seq=row["seq"],
            kind=kind,
            payload=payload,
            at=row["at"],
            actor=actor,
            parent_run_id=parent_run_id,
            depth=depth,
            expires_at=row["expires_at"],
        )

    async def read_trajectory(
        self, tenant_id: str, run_id: str, *, after_seq: int = 0, limit: int = 1000
    ) -> list[TrajectoryEvent]:
        rows = await self._pool.fetch(
            """SELECT seq, kind, payload, at, actor, parent_run_id, depth, expires_at
                 FROM trajectory_events
                WHERE tenant_id = $1 AND run_id = $2 AND seq > $3
                ORDER BY seq ASC
                LIMIT $4""",
            tenant_id, run_id, after_seq, limit,
        )
        return [
            TrajectoryEvent(
                tenant_id=tenant_id,
                run_id=run_id,
                seq=row["seq"],
                kind=TrajectoryKind(row["kind"]),
                payload=row["payload"] or {},
                at=row["at"],
                actor=row["actor"],
                parent_run_id=row["parent_run_id"],
                depth=row["depth"],
                expires_at=row["expires_at"],
            )
            for row in rows
        ]

    async def list_trajectory_runs(self, tenant_id: str, *, limit: int = 50) -> list[str]:
        rows = await self._pool.fetch(
            """SELECT run_id
                 FROM trajectory_events
                WHERE tenant_id = $1
                GROUP BY run_id
                ORDER BY MAX(at) DESC
                LIMIT $2""",
            tenant_id, limit,
        )
        return [row["run_id"] for row in rows]

    async def purge_trajectory(self, tenant_id: str, run_id: str) -> int:
        result = await self._pool.execute(
            "DELETE FROM trajectory_events WHERE tenant_id = $1 AND run_id = $2",
            tenant_id, run_id,
        )
        return int(str(result).rsplit(" ", 1)[-1] or 0)

    async def expire_trajectories(self, *, now: datetime | None = None) -> int:
        result = await self._pool.execute(
            "DELETE FROM trajectory_events WHERE expires_at IS NOT NULL AND expires_at <= $1",
            now or utcnow(),
        )
        return int(str(result).rsplit(" ", 1)[-1] or 0)
