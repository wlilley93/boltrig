"""Trajectory persistence: append-only rows, per-run sequence, bounded life.

SPLIT MEMORY FROM POSTGRES, as the store layer already does elsewhere
(ai_key_proposals_memory.py / _postgres.py). Not cosmetic: the RLS invariant in
tests/unit/test_rls_pool.py scans each module's SOURCE for pool statements, then
requires every class defined in that file to bind the tenant GUC. Keeping the
in-memory store and the Protocol beside the Postgres one made all three
offenders, and decorating an in-memory dict with an RLS binding would be a lie
told to satisfy a scanner.

(That scan is a regex over source text, so even spelling the pattern out in a
comment here would put this file back on its list -- which is why it is
described rather than quoted. Worth knowing before anyone "clarifies" this.)

A STANDALONE STORE, NOT A MIXIN ON ``Store``. Every other stream here composes
into ``InMemoryStore`` / ``PostgresStore``, and this one deliberately does not.
The whole argument for the trajectory is that it is a different stream with a
different posture -- verbatim where audit is scrubbed, expiring where audit is
permanent, opt-in where audit is always on. Bolting it onto the object that
carries the compliance record would blur exactly the line the design depends
on, and would mean every holder of a ``Store`` incidentally holds a handle to
the unscrubbed prompts.

TWO IMPLEMENTATIONS, ONE CONTRACT. The in-memory one is what the kernel runs on
in dev and tests; Postgres is production. Both must assign ``seq`` themselves --
see the model's note on why a caller-supplied sequence is a race.

TENANT SCOPING IS A CONTRACT OF EVERY METHOD (SEC-08), as in base.py: a run id
is never enough on its own.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from threading import Lock
from typing import Any, Protocol, runtime_checkable

from boltrig.models import TrajectoryEvent, TrajectoryKind, utcnow


@runtime_checkable
class TrajectoryStore(Protocol):
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
    ) -> TrajectoryEvent: ...

    async def read_trajectory(
        self, tenant_id: str, run_id: str, *, after_seq: int = 0, limit: int = 1000
    ) -> list[TrajectoryEvent]: ...

    async def list_trajectory_runs(self, tenant_id: str, *, limit: int = 50) -> list[str]: ...

    async def purge_trajectory(self, tenant_id: str, run_id: str) -> int: ...

    async def expire_trajectories(self, *, now: datetime | None = None) -> int: ...


class InMemoryTrajectoryStore:
    """Dev and tests. Holds rows for the life of the process and no longer."""

    def __init__(self) -> None:
        self._trajectory: dict[tuple[str, str], list[TrajectoryEvent]] = {}
        self._trajectory_lock = Lock()

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
        now = utcnow()
        with self._trajectory_lock:
            rows = self._trajectory.setdefault((tenant_id, run_id), [])
            event = TrajectoryEvent(
                tenant_id=tenant_id,
                run_id=run_id,
                seq=len(rows) + 1,
                kind=kind,
                payload=payload,
                at=now,
                actor=actor,
                parent_run_id=parent_run_id,
                depth=depth,
                expires_at=now + timedelta(days=ttl_days),
            )
            rows.append(event)
            return event

    async def read_trajectory(
        self, tenant_id: str, run_id: str, *, after_seq: int = 0, limit: int = 1000
    ) -> list[TrajectoryEvent]:
        with self._trajectory_lock:
            rows = self._trajectory.get((tenant_id, run_id), [])
            return [row for row in rows if row.seq > after_seq][:limit]

    async def list_trajectory_runs(self, tenant_id: str, *, limit: int = 50) -> list[str]:
        with self._trajectory_lock:
            runs = [
                (rows[-1].at, run)
                for (tenant, run), rows in self._trajectory.items()
                if tenant == tenant_id and rows
            ]
        return [run for _, run in sorted(runs, reverse=True)][:limit]

    async def purge_trajectory(self, tenant_id: str, run_id: str) -> int:
        with self._trajectory_lock:
            return len(self._trajectory.pop((tenant_id, run_id), []))

    async def expire_trajectories(self, *, now: datetime | None = None) -> int:
        moment = now or utcnow()
        removed = 0
        with self._trajectory_lock:
            for key, rows in list(self._trajectory.items()):
                keep = [r for r in rows if r.expires_at is None or r.expires_at > moment]
                removed += len(rows) - len(keep)
                if keep:
                    self._trajectory[key] = keep
                else:
                    self._trajectory.pop(key, None)
        return removed
