"""Durable asyncpg adapter for digest-only, phase-scoped model-proxy grants."""

from __future__ import annotations

from datetime import datetime, timedelta

import asyncpg

from boltrig.fleet.domain.model_proxy_grant import (
    ActiveModelProxyGenerationConflict,
    ModelProxyGrantConflict,
    ModelProxyGrantDraft,
    StaleModelProxyGeneration,
    StoredModelProxyGrant,
    validate_model_proxy_revocation_reason,
)
from boltrig.fleet.domain.model_proxy_scope import (
    ModelProxyAssignmentScope,
    ModelProxyCellScope,
    ModelProxyGrantBinding,
    ModelProxyPhaseScope,
    ModelProxyRootScope,
    TrustedModelProxyRequestObservation,
)
from boltrig.fleet.infrastructure.postgres_model_proxy_grant_support import (
    GRANT_COLS,
    active_generation_exists,
    aware,
    collides,
    expire_due,
    highest_generation_for_cell,
    insert_grant,
    is_cancelled,
    is_digest_candidate,
    lock_root,
    revoke_active_for_assignment,
    revoke_active_for_cell,
    revoke_active_for_phase,
    revoke_active_for_root,
    row_to_grant,
)


class PostgresModelProxyGrantStore:
    """Durable model-proxy grant store backed by PostgreSQL.

    Mirrors ``MemoryModelProxyGrantStore``'s atomic semantics: every write (and
    every expiry-materialising lookup) runs inside one transaction holding a
    per-root transactional advisory lock, so competing insert/find/cancel
    operations for one root serialize exactly as the single in-process
    ``asyncio.Lock`` does for the memory adapter (that lock is store-global
    rather than per-root only because dict operations are always this cheap
    in-process; per-root locking here is an equivalent, strictly less
    contended, serialization boundary for a real connection pool).

    Highest-generation-ever-seen for a cell is derived with
    ``MAX(generation)`` over every historical row for that exact cell (active,
    revoked, or expired) rather than tracked in a separate table: Postgres
    keeps every row forever, so the derived query is exact and needs no
    additional bookkeeping structure the way the bounded in-memory adapter's
    ``_highest_generation`` dict does (that dict is pruned on cancellation
    purely to keep memory bounded; this store is unbounded, so nothing is ever
    pruned).

    Design decision -- clock: the ``ModelProxyGrantStore`` protocol mints no
    ``now`` parameter at all (unlike ``GrantLeaseStore``, whose protocol
    requires one on every time-sensitive method). Since a stateless
    connection-pool adapter cannot safely hold the in-memory adapter's
    per-process ``_clock_high_water`` rollback flag (that flag is meaningful
    only because one process's memory IS the store), this adapter instead
    accepts an optional ``now: datetime | None`` keyword on every
    time-sensitive method: passing it (as the contract does, for
    determinism) pins the authoritative instant explicitly, matching
    ``PostgresGrantLeaseStore``'s style; omitting it (the production default)
    mints from Postgres's own ``now()`` inside the same locked transaction.
    Every pool connection shares one server-side wall clock, so there is no
    per-process rollback to fail closed against here -- a backwards step of
    the database server's own clock is an infrastructure concern, same as the
    caller-supplied ``now`` is for the sibling grant-lease adapter.

    Capacity limits (``max_records``/``max_fences``,
    ``ModelProxyGrantStoreCapacityExceeded``) are a bounded in-memory-only
    property; this durable store is unbounded and never raises them.
    """

    __slots__ = ("_pool",)

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    def __repr__(self) -> str:
        return "PostgresModelProxyGrantStore(bounded=False)"

    async def _now(self, conn: asyncpg.Connection, now: datetime | None) -> datetime:
        if now is not None:
            return aware("now", now)
        return aware("now", await conn.fetchval("SELECT now()"))

    async def insert_active(
        self, draft: ModelProxyGrantDraft, *, now: datetime | None = None
    ) -> StoredModelProxyGrant:
        if type(draft) is not ModelProxyGrantDraft:
            raise TypeError("draft must be an exact ModelProxyGrantDraft")
        cell = draft.binding.cell
        root = cell.assignment.phase.root
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await lock_root(conn, root)
                current = await self._now(conn, now)
                await expire_due(conn, root, current)
                if await is_cancelled(conn, cell):
                    raise StaleModelProxyGeneration("model-proxy scope is terminally cancelled")
                if await collides(conn, draft):
                    raise ModelProxyGrantConflict("model-proxy credential was already inserted")
                if await active_generation_exists(conn, cell, draft.generation, current):
                    raise ActiveModelProxyGenerationConflict(
                        "model-proxy generation is already active"
                    )
                highest = await highest_generation_for_cell(conn, cell)
                if highest is not None and draft.generation <= highest:
                    raise StaleModelProxyGeneration("model-proxy generation is stale")
                grant = StoredModelProxyGrant(
                    grant_id=draft.grant_id,
                    binding=draft.binding,
                    bearer_digest=draft.bearer_digest,
                    startup_request_digest=draft.startup_request_digest,
                    issued_at=current,
                    expires_at=current + timedelta(seconds=draft.ttl_seconds),
                    generation=draft.generation,
                )
                await revoke_active_for_cell(conn, cell, current, "superseded_generation")
                await insert_grant(conn, grant)
                return grant

    async def find_active_for_trusted_observation(
        self,
        bearer_digest: str,
        observation: TrustedModelProxyRequestObservation,
        *,
        generation: int,
        now: datetime | None = None,
    ) -> StoredModelProxyGrant | None:
        if type(observation) is not TrustedModelProxyRequestObservation:
            raise TypeError("observation must be an exact TrustedModelProxyRequestObservation")
        if not is_digest_candidate(bearer_digest):
            return None
        root = observation.binding.cell.assignment.phase.root
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await lock_root(conn, root)
                current = await self._now(conn, now)
                await expire_due(conn, root, current)
                row = await conn.fetchrow(
                    f"SELECT {GRANT_COLS} FROM model_proxy_grants WHERE bearer_digest=$1",
                    bearer_digest,
                )
                matched = None if row is None else row_to_grant(row)
                if (
                    matched is not None
                    and matched.binding == observation.binding
                    and matched.active_at(current, generation=generation)
                ):
                    return matched
                return None

    async def find_active_by_id(
        self,
        grant_id: str,
        binding: ModelProxyGrantBinding,
        *,
        generation: int,
        now: datetime | None = None,
    ) -> StoredModelProxyGrant | None:
        if type(binding) is not ModelProxyGrantBinding:
            raise TypeError("binding must be an exact ModelProxyGrantBinding")
        if type(grant_id) is not str:
            return None
        root = binding.cell.assignment.phase.root
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await lock_root(conn, root)
                current = await self._now(conn, now)
                await expire_due(conn, root, current)
                row = await conn.fetchrow(
                    f"SELECT {GRANT_COLS} FROM model_proxy_grants WHERE grant_id=$1", grant_id
                )
                record = None if row is None else row_to_grant(row)
                if (
                    record is not None
                    and record.binding == binding
                    and record.active_at(current, generation=generation)
                ):
                    return record
                return None

    async def get_by_id(
        self, grant_id: str, binding: ModelProxyGrantBinding
    ) -> StoredModelProxyGrant | None:
        if type(binding) is not ModelProxyGrantBinding:
            raise TypeError("binding must be an exact ModelProxyGrantBinding")
        if type(grant_id) is not str:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {GRANT_COLS} FROM model_proxy_grants WHERE grant_id=$1", grant_id
            )
            if row is None:
                return None
            record = row_to_grant(row)
            return record if record.binding == binding else None

    async def revoke_root(
        self, scope: ModelProxyRootScope, *, reason: str, now: datetime | None = None
    ) -> int:
        if type(scope) is not ModelProxyRootScope:
            raise TypeError("scope must be an exact ModelProxyRootScope")
        safe_reason = validate_model_proxy_revocation_reason(reason)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await lock_root(conn, scope)
                current = await self._now(conn, now)
                await expire_due(conn, scope, current)
                count = await revoke_active_for_root(conn, scope, current, safe_reason)
                await conn.execute(
                    "INSERT INTO model_proxy_grant_cancelled_roots "
                    "(tenant_id, workspace_id, root_run_id, reason) VALUES ($1,$2,$3,$4) "
                    "ON CONFLICT DO NOTHING",
                    scope.tenant_id,
                    scope.workspace_id,
                    scope.root_run_id,
                    safe_reason,
                )
                return count

    async def revoke_phase(
        self, scope: ModelProxyPhaseScope, *, reason: str, now: datetime | None = None
    ) -> int:
        if type(scope) is not ModelProxyPhaseScope:
            raise TypeError("scope must be an exact ModelProxyPhaseScope")
        safe_reason = validate_model_proxy_revocation_reason(reason)
        root = scope.root
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await lock_root(conn, root)
                current = await self._now(conn, now)
                await expire_due(conn, root, current)
                count = await revoke_active_for_phase(conn, scope, current, safe_reason)
                await conn.execute(
                    "INSERT INTO model_proxy_grant_cancelled_phases "
                    "(tenant_id, workspace_id, root_run_id, phase_id, reason) "
                    "VALUES ($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING",
                    root.tenant_id,
                    root.workspace_id,
                    root.root_run_id,
                    scope.phase_id,
                    safe_reason,
                )
                return count

    async def revoke_assignment(
        self, scope: ModelProxyAssignmentScope, *, reason: str, now: datetime | None = None
    ) -> int:
        if type(scope) is not ModelProxyAssignmentScope:
            raise TypeError("scope must be an exact ModelProxyAssignmentScope")
        safe_reason = validate_model_proxy_revocation_reason(reason)
        phase = scope.phase
        root = phase.root
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await lock_root(conn, root)
                current = await self._now(conn, now)
                await expire_due(conn, root, current)
                count = await revoke_active_for_assignment(conn, scope, current, safe_reason)
                await conn.execute(
                    "INSERT INTO model_proxy_grant_cancelled_assignments "
                    "(tenant_id, workspace_id, root_run_id, phase_id, assignment_id, reason) "
                    "VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT DO NOTHING",
                    root.tenant_id,
                    root.workspace_id,
                    root.root_run_id,
                    phase.phase_id,
                    scope.assignment_id,
                    safe_reason,
                )
                return count

    async def revoke_cell(
        self, scope: ModelProxyCellScope, *, reason: str, now: datetime | None = None
    ) -> int:
        if type(scope) is not ModelProxyCellScope:
            raise TypeError("scope must be an exact ModelProxyCellScope")
        safe_reason = validate_model_proxy_revocation_reason(reason)
        assignment = scope.assignment
        phase = assignment.phase
        root = phase.root
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await lock_root(conn, root)
                current = await self._now(conn, now)
                await expire_due(conn, root, current)
                count = await revoke_active_for_cell(conn, scope, current, safe_reason)
                await conn.execute(
                    "INSERT INTO model_proxy_grant_cancelled_cells "
                    "(tenant_id, workspace_id, root_run_id, phase_id, assignment_id, cell_id, "
                    "pid, pid_start_ticks, boot_id, pid_namespace_inode, "
                    "cgroup_identity_digest, reason) "
                    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12) ON CONFLICT DO NOTHING",
                    root.tenant_id,
                    root.workspace_id,
                    root.root_run_id,
                    phase.phase_id,
                    assignment.assignment_id,
                    scope.cell_id,
                    scope.pid,
                    scope.pid_start_ticks,
                    scope.boot_id,
                    scope.pid_namespace_inode,
                    scope.cgroup_identity_digest,
                    safe_reason,
                )
                return count


__all__ = ["PostgresModelProxyGrantStore"]
