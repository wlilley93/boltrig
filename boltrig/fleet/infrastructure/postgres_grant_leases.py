"""Durable asyncpg adapter for run-scoped MCP grant leases."""

from __future__ import annotations

from datetime import datetime

import asyncpg

from boltrig.fleet.domain.grant_lease import (
    GrantAuthoritySnapshot,
    GrantLeaseBinding,
    GrantLeaseCandidate,
    GrantLeaseConflict,
    GrantLeaseStatus,
    GrantRootBinding,
    LeaseGenerationExhausted,
    StaleGrantGeneration,
    StoredGrantLease,
    validate_revocation_reason,
)
from boltrig.fleet.infrastructure.postgres_grant_lease_support import (
    LEASE_COLS,
    MAX_SIGNED_BIGINT,
    aware,
    current_authority,
    expire_binding,
    insert_lease,
    is_cancelled,
    is_digest_candidate,
    lock_root,
    matches,
    revoke_active,
    root_of,
    row_to_lease,
)


class PostgresGrantLeaseStore:
    """Durable grant-lease store backed by PostgreSQL.

    Mirrors the in-memory adapter's atomic semantics: every write (and every
    expiry-materialising lookup) runs inside one transaction holding a per-root
    transactional advisory lock, so competing issue/reissue/revoke operations for
    one root serialize exactly as the single-process lock does. Authority compare,
    generation compare-and-swap, cancellation tombstones, and supersession are all
    evaluated over the rows loaded in that transaction. Bounded-record backpressure
    is a property of the in-memory adapter only; this durable store is unbounded.
    """

    __slots__ = ("_pool",)

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    def __repr__(self) -> str:
        return "PostgresGrantLeaseStore(bounded=False)"

    async def install_authority_snapshot(
        self, snapshot: GrantAuthoritySnapshot, *, now: datetime
    ) -> None:
        if type(snapshot) is not GrantAuthoritySnapshot:
            raise TypeError("snapshot must be an exact GrantAuthoritySnapshot")
        current = aware("now", now)
        binding = snapshot.binding
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await lock_root(conn, root_of(binding))
                await expire_binding(conn, binding, current)
                if await is_cancelled(conn, binding):
                    raise StaleGrantGeneration("grant binding is terminally cancelled")
                previous = await current_authority(conn, binding)
                if previous == snapshot:
                    return
                highest = previous.authority_policy_generation if previous else None
                if highest is not None and snapshot.authority_policy_generation <= highest:
                    raise GrantLeaseConflict(
                        "authority replacement must advance the policy generation"
                    )
                await revoke_active(conn, binding, current, "authority_replaced")
                await conn.execute(
                    """
                    INSERT INTO grant_authority_snapshots (
                        tenant_id, workspace_id, root_run_id, phase_id, assignment_id,
                        authority_evaluation_id, authority_evaluation_digest,
                        authority_policy_generation, permitted_verbs
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    ON CONFLICT (tenant_id, workspace_id, root_run_id, phase_id, assignment_id)
                    DO UPDATE SET authority_evaluation_id = EXCLUDED.authority_evaluation_id,
                        authority_evaluation_digest = EXCLUDED.authority_evaluation_digest,
                        authority_policy_generation = EXCLUDED.authority_policy_generation,
                        permitted_verbs = EXCLUDED.permitted_verbs
                    """,
                    binding.tenant_id,
                    binding.workspace_id,
                    binding.root_run_id,
                    binding.phase_id,
                    binding.assignment_id,
                    snapshot.authority_evaluation_id,
                    snapshot.authority_evaluation_digest,
                    snapshot.authority_policy_generation,
                    list(snapshot.permitted_verbs),
                )

    async def insert_active(
        self, candidate: GrantLeaseCandidate, *, expected_authority: GrantAuthoritySnapshot,
        now: datetime,
    ) -> StoredGrantLease:
        if type(candidate) is not GrantLeaseCandidate:
            raise TypeError("candidate must be an exact GrantLeaseCandidate")
        if type(expected_authority) is not GrantAuthoritySnapshot:
            raise TypeError("expected_authority must be an exact GrantAuthoritySnapshot")
        current = aware("now", now)
        binding = candidate.binding
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await lock_root(conn, root_of(binding))
                await expire_binding(conn, binding, current)
                receipt = await self._issue_receipt(conn, candidate)
                if receipt is not None:
                    if receipt.is_projection_of(candidate):
                        return receipt
                    raise GrantLeaseConflict("issue operation conflicts with durable receipt")
                if candidate.issued_at > current or candidate.expires_at <= current:
                    raise GrantLeaseConflict("lease is not active at insertion time")
                if await is_cancelled(conn, binding):
                    raise StaleGrantGeneration("grant binding is terminally cancelled")
                authority = await current_authority(conn, binding)
                if (
                    binding != expected_authority.binding
                    or not candidate.matches_authority_snapshot(expected_authority)
                    or authority != expected_authority
                ):
                    raise GrantLeaseConflict(
                        "grant authority differs from the current durable snapshot"
                    )
                if await self._credential_collision(conn, candidate):
                    raise GrantLeaseConflict("lease identifier or digest was already inserted")
                highest = await conn.fetchval(
                    "SELECT max(lease_generation) FROM grant_leases WHERE tenant_id=$1 "
                    "AND workspace_id=$2 AND root_run_id=$3 AND phase_id=$4 AND assignment_id=$5",
                    binding.tenant_id,
                    binding.workspace_id,
                    binding.root_run_id,
                    binding.phase_id,
                    binding.assignment_id,
                )
                if candidate.expected_current_lease_generation != highest:
                    raise StaleGrantGeneration("lease generation compare-and-swap failed")
                if highest == MAX_SIGNED_BIGINT:
                    raise LeaseGenerationExhausted("lease generation fence is exhausted")
                lease_generation = 1 if highest is None else highest + 1
                stored = StoredGrantLease.from_candidate(
                    candidate, lease_generation=lease_generation
                )
                await revoke_active(conn, binding, current, "superseded_generation")
                await insert_lease(conn, stored)
                return stored

    async def get_by_issue_operation_id(
        self, issue_operation_id: str, binding: GrantLeaseBinding
    ) -> StoredGrantLease | None:
        if type(binding) is not GrantLeaseBinding:
            raise TypeError("binding must be an exact GrantLeaseBinding")
        if type(issue_operation_id) is not str or not issue_operation_id:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {LEASE_COLS} FROM grant_leases WHERE tenant_id=$1 "
                "AND workspace_id=$2 AND issue_operation_id=$3",
                binding.tenant_id,
                binding.workspace_id,
                issue_operation_id,
            )
            if row is None:
                return None
            record = row_to_lease(row)
            return record if record.binding == binding else None

    async def find_active_by_digest(
        self, token_digest: str, binding: GrantLeaseBinding, *, now: datetime,
        expected_authority: GrantAuthoritySnapshot,
    ) -> StoredGrantLease | None:
        current = aware("now", now)
        if type(binding) is not GrantLeaseBinding:
            raise TypeError("binding must be an exact GrantLeaseBinding")
        if type(expected_authority) is not GrantAuthoritySnapshot:
            raise TypeError("expected_authority must be an exact GrantAuthoritySnapshot")
        if expected_authority.binding != binding or not is_digest_candidate(token_digest):
            return None
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await lock_root(conn, root_of(binding))
                await expire_binding(conn, binding, current)
                row = await conn.fetchrow(
                    f"SELECT {LEASE_COLS} FROM grant_leases WHERE token_digest=$1", token_digest
                )
                matched = None if row is None else row_to_lease(row)
                if await current_authority(conn, binding) != expected_authority:
                    return None
                return matched if matches(matched, binding, current, expected_authority) else None

    async def find_active_by_id(
        self, lease_id: str, binding: GrantLeaseBinding, *, now: datetime,
        expected_authority: GrantAuthoritySnapshot,
    ) -> StoredGrantLease | None:
        current = aware("now", now)
        if type(binding) is not GrantLeaseBinding:
            raise TypeError("binding must be an exact GrantLeaseBinding")
        if type(expected_authority) is not GrantAuthoritySnapshot:
            raise TypeError("expected_authority must be an exact GrantAuthoritySnapshot")
        if expected_authority.binding != binding or not isinstance(lease_id, str):
            return None
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await lock_root(conn, root_of(binding))
                await expire_binding(conn, binding, current)
                row = await conn.fetchrow(
                    f"SELECT {LEASE_COLS} FROM grant_leases WHERE lease_id=$1", lease_id
                )
                record = None if row is None else row_to_lease(row)
                if await current_authority(conn, binding) != expected_authority:
                    return None
                return record if matches(record, binding, current, expected_authority) else None

    async def get_by_id(
        self, lease_id: str, binding: GrantLeaseBinding
    ) -> StoredGrantLease | None:
        if type(binding) is not GrantLeaseBinding:
            raise TypeError("binding must be an exact GrantLeaseBinding")
        if not isinstance(lease_id, str):
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {LEASE_COLS} FROM grant_leases WHERE lease_id=$1", lease_id
            )
            if row is None:
                return None
            record = row_to_lease(row)
            return record if record.binding == binding else None

    async def revoke_exact(
        self, lease_id: str, binding: GrantLeaseBinding, *, now: datetime, reason: str
    ) -> bool:
        current = aware("now", now)
        if type(binding) is not GrantLeaseBinding:
            raise TypeError("binding must be an exact GrantLeaseBinding")
        safe_reason = validate_revocation_reason(reason)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await lock_root(conn, root_of(binding))
                await expire_binding(conn, binding, current)
                row = await conn.fetchrow(
                    f"SELECT {LEASE_COLS} FROM grant_leases WHERE lease_id=$1", lease_id
                )
                if row is None:
                    return False
                record = row_to_lease(row)
                if record.binding != binding or record.status is not GrantLeaseStatus.ACTIVE:
                    return False
                await conn.execute(
                    "UPDATE grant_leases SET status='revoked', revoked_at=GREATEST($1, issued_at), "
                    "revocation_reason=$2 WHERE lease_id=$3 AND status='active'",
                    current,
                    safe_reason,
                    lease_id,
                )
                return True

    async def revoke_assignment(
        self, binding: GrantLeaseBinding, *, now: datetime, reason: str
    ) -> int:
        current = aware("now", now)
        if type(binding) is not GrantLeaseBinding:
            raise TypeError("binding must be an exact GrantLeaseBinding")
        safe_reason = validate_revocation_reason(reason)
        root = root_of(binding)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await lock_root(conn, root)
                await expire_binding(conn, binding, current)
                root_already = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM grant_lease_cancelled_roots "
                    "WHERE tenant_id=$1 AND workspace_id=$2 AND root_run_id=$3)",
                    root.tenant_id,
                    root.workspace_id,
                    root.root_run_id,
                )
                count = await revoke_active(conn, binding, current, safe_reason)
                if not root_already:
                    await conn.execute(
                        "DELETE FROM grant_authority_snapshots WHERE tenant_id=$1 "
                        "AND workspace_id=$2 AND root_run_id=$3 AND phase_id=$4 AND assignment_id=$5",
                        binding.tenant_id,
                        binding.workspace_id,
                        binding.root_run_id,
                        binding.phase_id,
                        binding.assignment_id,
                    )
                    await conn.execute(
                        "INSERT INTO grant_lease_cancelled_assignments "
                        "(tenant_id, workspace_id, root_run_id, phase_id, assignment_id, reason) "
                        "VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT DO NOTHING",
                        binding.tenant_id,
                        binding.workspace_id,
                        binding.root_run_id,
                        binding.phase_id,
                        binding.assignment_id,
                        safe_reason,
                    )
                return count

    async def revoke_root(
        self, binding: GrantRootBinding, *, now: datetime, reason: str
    ) -> int:
        current = aware("now", now)
        if type(binding) is not GrantRootBinding:
            raise TypeError("binding must be an exact GrantRootBinding")
        safe_reason = validate_revocation_reason(reason)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await lock_root(conn, binding)
                await conn.execute(
                    "UPDATE grant_leases SET status='expired' WHERE tenant_id=$1 "
                    "AND workspace_id=$2 AND root_run_id=$3 AND status='active' AND expires_at <= $4",
                    binding.tenant_id,
                    binding.workspace_id,
                    binding.root_run_id,
                    current,
                )
                count = await conn.fetchval(
                    "WITH revoked AS (UPDATE grant_leases SET status='revoked', "
                    "revoked_at=GREATEST($1, issued_at), revocation_reason=$2 "
                    "WHERE tenant_id=$3 AND workspace_id=$4 AND root_run_id=$5 "
                    "AND status='active' RETURNING 1) SELECT count(*) FROM revoked",
                    current,
                    safe_reason,
                    binding.tenant_id,
                    binding.workspace_id,
                    binding.root_run_id,
                )
                await conn.execute(
                    "DELETE FROM grant_authority_snapshots WHERE tenant_id=$1 "
                    "AND workspace_id=$2 AND root_run_id=$3",
                    binding.tenant_id,
                    binding.workspace_id,
                    binding.root_run_id,
                )
                await conn.execute(
                    "INSERT INTO grant_lease_cancelled_roots "
                    "(tenant_id, workspace_id, root_run_id, reason) "
                    "VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
                    binding.tenant_id,
                    binding.workspace_id,
                    binding.root_run_id,
                    safe_reason,
                )
                return count or 0

    async def _issue_receipt(
        self, conn: asyncpg.Connection, candidate: GrantLeaseCandidate
    ) -> StoredGrantLease | None:
        row = await conn.fetchrow(
            f"SELECT {LEASE_COLS} FROM grant_leases WHERE tenant_id=$1 "
            "AND workspace_id=$2 AND issue_operation_id=$3",
            candidate.binding.tenant_id,
            candidate.binding.workspace_id,
            candidate.issue_operation_id,
        )
        return None if row is None else row_to_lease(row)

    async def _credential_collision(
        self, conn: asyncpg.Connection, candidate: GrantLeaseCandidate
    ) -> bool:
        return await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM grant_leases WHERE token_digest=$1 OR lease_id=$2)",
            candidate.token_digest,
            candidate.lease_id,
        )


__all__ = ["PostgresGrantLeaseStore"]
