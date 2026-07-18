"""Pure and connection helpers for the durable grant-lease adapter."""

from __future__ import annotations

from datetime import datetime

import asyncpg

from boltrig.fleet.domain.grant_lease import (
    GrantAuthoritySnapshot,
    GrantLeaseBinding,
    GrantLeaseStatus,
    GrantRootBinding,
    StoredGrantLease,
)

MAX_SIGNED_BIGINT = 2**63 - 1

LEASE_COLS = (
    "lease_id, tenant_id, workspace_id, root_run_id, phase_id, assignment_id, "
    "issue_operation_id, token_digest, authority_evaluation_id, "
    "authority_evaluation_digest, authority_policy_generation, permitted_verbs, "
    "issued_at, expires_at, max_ttl_seconds, expected_current_lease_generation, "
    "lease_generation, status, revoked_at, revocation_reason"
)


def root_of(binding: GrantLeaseBinding) -> GrantRootBinding:
    return GrantRootBinding(binding.tenant_id, binding.workspace_id, binding.root_run_id)


def aware(label: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value


def is_digest_candidate(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64 or value != value.lower():
        return False
    try:
        bytes.fromhex(value)
    except ValueError:
        return False
    return True


def matches(
    record: StoredGrantLease | None,
    binding: GrantLeaseBinding,
    now: datetime,
    expected_authority: GrantAuthoritySnapshot,
) -> bool:
    return bool(
        record is not None
        and record.binding == binding
        and record.issued_at <= now
        and record.authority_snapshot == expected_authority
        and record.is_active_at(
            now, authority_policy_generation=expected_authority.authority_policy_generation
        )
    )


def row_to_lease(row: asyncpg.Record) -> StoredGrantLease:
    binding = GrantLeaseBinding(
        row["tenant_id"],
        row["workspace_id"],
        row["root_run_id"],
        row["phase_id"],
        row["assignment_id"],
    )
    return StoredGrantLease(
        lease_id=row["lease_id"],
        issue_operation_id=row["issue_operation_id"],
        binding=binding,
        token_digest=row["token_digest"],
        authority_snapshot=row_to_authority(row),
        issued_at=row["issued_at"],
        expires_at=row["expires_at"],
        max_ttl_seconds=row["max_ttl_seconds"],
        expected_current_lease_generation=row["expected_current_lease_generation"],
        lease_generation=row["lease_generation"],
        status=GrantLeaseStatus(row["status"]),
        revoked_at=row["revoked_at"],
        revocation_reason=row["revocation_reason"],
    )


def row_to_authority(row: asyncpg.Record) -> GrantAuthoritySnapshot:
    binding = GrantLeaseBinding(
        row["tenant_id"],
        row["workspace_id"],
        row["root_run_id"],
        row["phase_id"],
        row["assignment_id"],
    )
    return GrantAuthoritySnapshot.from_stored_values(
        binding=binding,
        authority_evaluation_id=row["authority_evaluation_id"],
        authority_evaluation_digest=row["authority_evaluation_digest"],
        authority_policy_generation=row["authority_policy_generation"],
        permitted_verbs=tuple(row["permitted_verbs"]),
    )


async def lock_root(conn: asyncpg.Connection, root: GrantRootBinding) -> None:
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtext($1))",
        f"{root.tenant_id}:{root.workspace_id}:{root.root_run_id}",
    )


async def expire_binding(
    conn: asyncpg.Connection, binding: GrantLeaseBinding, now: datetime
) -> None:
    await conn.execute(
        "UPDATE grant_leases SET status='expired' WHERE tenant_id=$1 AND workspace_id=$2 "
        "AND root_run_id=$3 AND status='active' AND expires_at <= $4",
        binding.tenant_id,
        binding.workspace_id,
        binding.root_run_id,
        now,
    )


async def is_cancelled(conn: asyncpg.Connection, binding: GrantLeaseBinding) -> bool:
    if await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM grant_lease_cancelled_roots "
        "WHERE tenant_id=$1 AND workspace_id=$2 AND root_run_id=$3)",
        binding.tenant_id,
        binding.workspace_id,
        binding.root_run_id,
    ):
        return True
    return await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM grant_lease_cancelled_assignments "
        "WHERE tenant_id=$1 AND workspace_id=$2 AND root_run_id=$3 "
        "AND phase_id=$4 AND assignment_id=$5)",
        binding.tenant_id,
        binding.workspace_id,
        binding.root_run_id,
        binding.phase_id,
        binding.assignment_id,
    )


async def current_authority(
    conn: asyncpg.Connection, binding: GrantLeaseBinding
) -> GrantAuthoritySnapshot | None:
    row = await conn.fetchrow(
        "SELECT tenant_id, workspace_id, root_run_id, phase_id, assignment_id, "
        "authority_evaluation_id, authority_evaluation_digest, "
        "authority_policy_generation, permitted_verbs "
        "FROM grant_authority_snapshots WHERE tenant_id=$1 AND workspace_id=$2 "
        "AND root_run_id=$3 AND phase_id=$4 AND assignment_id=$5",
        binding.tenant_id,
        binding.workspace_id,
        binding.root_run_id,
        binding.phase_id,
        binding.assignment_id,
    )
    return None if row is None else row_to_authority(row)


async def revoke_active(
    conn: asyncpg.Connection, binding: GrantLeaseBinding, now: datetime, reason: str
) -> int:
    count = await conn.fetchval(
        "WITH revoked AS (UPDATE grant_leases SET status='revoked', "
        "revoked_at=GREATEST($1, issued_at), revocation_reason=$2 "
        "WHERE tenant_id=$3 AND workspace_id=$4 AND root_run_id=$5 AND phase_id=$6 "
        "AND assignment_id=$7 AND status='active' RETURNING 1) SELECT count(*) FROM revoked",
        now,
        reason,
        binding.tenant_id,
        binding.workspace_id,
        binding.root_run_id,
        binding.phase_id,
        binding.assignment_id,
    )
    return count or 0


async def insert_lease(conn: asyncpg.Connection, stored: StoredGrantLease) -> None:
    binding = stored.binding
    authority = stored.authority_snapshot
    await conn.execute(
        f"INSERT INTO grant_leases ({LEASE_COLS}) VALUES "
        "($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)",
        stored.lease_id,
        binding.tenant_id,
        binding.workspace_id,
        binding.root_run_id,
        binding.phase_id,
        binding.assignment_id,
        stored.issue_operation_id,
        stored.token_digest,
        authority.authority_evaluation_id,
        authority.authority_evaluation_digest,
        authority.authority_policy_generation,
        list(authority.permitted_verbs),
        stored.issued_at,
        stored.expires_at,
        stored.max_ttl_seconds,
        stored.expected_current_lease_generation,
        stored.lease_generation,
        stored.status.value,
        stored.revoked_at,
        stored.revocation_reason,
    )


__all__ = [
    "LEASE_COLS",
    "MAX_SIGNED_BIGINT",
    "aware",
    "current_authority",
    "expire_binding",
    "insert_lease",
    "is_cancelled",
    "is_digest_candidate",
    "lock_root",
    "matches",
    "revoke_active",
    "root_of",
    "row_to_authority",
    "row_to_lease",
]
