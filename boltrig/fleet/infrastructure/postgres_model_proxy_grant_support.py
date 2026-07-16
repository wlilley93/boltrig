"""Pure and connection helpers for the durable model-proxy grant adapter."""

from __future__ import annotations

from datetime import datetime

import asyncpg

from boltrig.fleet.domain.model_proxy_grant import (
    ModelProxyGrantDraft,
    ModelProxyGrantStatus,
    StoredModelProxyGrant,
)
from boltrig.fleet.domain.model_proxy_scope import (
    ModelProxyAssignmentScope,
    ModelProxyBudgetBinding,
    ModelProxyCellScope,
    ModelProxyGrantBinding,
    ModelProxyModelBinding,
    ModelProxyPhaseScope,
    ModelProxyRootScope,
)

GRANT_COLS = (
    "grant_id, tenant_id, workspace_id, root_run_id, phase_id, assignment_id, "
    "cell_id, pid, pid_start_ticks, boot_id, pid_namespace_inode, cgroup_identity_digest, "
    "model_id, model_policy_digest, budget_id, max_input_tokens, max_output_tokens, "
    "max_total_tokens, max_cost_micros, budget_policy_digest, bearer_digest, "
    "startup_request_digest, issued_at, expires_at, generation, status, revoked_at, "
    "revocation_reason"
)

# The exact-cell identity predicate: every column ModelProxyCellScope equality
# depends on (assignment chain plus all seven of its own fields). Reused by every
# helper that must match one process's grants exactly, in the same $1.. order
# ``cell_params`` produces.
CELL_WHERE = (
    "tenant_id=$1 AND workspace_id=$2 AND root_run_id=$3 AND phase_id=$4 "
    "AND assignment_id=$5 AND cell_id=$6 AND pid=$7 AND pid_start_ticks=$8 "
    "AND boot_id=$9 AND pid_namespace_inode=$10 AND cgroup_identity_digest=$11"
)


def cell_params(cell: ModelProxyCellScope) -> tuple[object, ...]:
    assignment = cell.assignment
    phase = assignment.phase
    root = phase.root
    return (
        root.tenant_id,
        root.workspace_id,
        root.root_run_id,
        phase.phase_id,
        assignment.assignment_id,
        cell.cell_id,
        cell.pid,
        cell.pid_start_ticks,
        cell.boot_id,
        cell.pid_namespace_inode,
        cell.cgroup_identity_digest,
    )


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


def row_to_grant(row: asyncpg.Record) -> StoredModelProxyGrant:
    root = ModelProxyRootScope(row["tenant_id"], row["workspace_id"], row["root_run_id"])
    phase = ModelProxyPhaseScope(root, row["phase_id"])
    assignment = ModelProxyAssignmentScope(phase, row["assignment_id"])
    cell = ModelProxyCellScope(
        assignment,
        row["cell_id"],
        row["pid"],
        row["pid_start_ticks"],
        row["boot_id"],
        row["pid_namespace_inode"],
        row["cgroup_identity_digest"],
    )
    model = ModelProxyModelBinding(row["model_id"], row["model_policy_digest"])
    budget = ModelProxyBudgetBinding(
        row["budget_id"],
        row["max_input_tokens"],
        row["max_output_tokens"],
        row["max_total_tokens"],
        row["max_cost_micros"],
        row["budget_policy_digest"],
    )
    binding = ModelProxyGrantBinding(cell, model, budget)
    return StoredModelProxyGrant(
        grant_id=row["grant_id"],
        binding=binding,
        bearer_digest=row["bearer_digest"],
        startup_request_digest=row["startup_request_digest"],
        issued_at=row["issued_at"],
        expires_at=row["expires_at"],
        generation=row["generation"],
        status=ModelProxyGrantStatus(row["status"]),
        revoked_at=row["revoked_at"],
        revocation_reason=row["revocation_reason"],
    )


async def lock_root(conn: asyncpg.Connection, root: ModelProxyRootScope) -> None:
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtext($1))",
        f"{root.tenant_id}:{root.workspace_id}:{root.root_run_id}",
    )


async def expire_due(conn: asyncpg.Connection, root: ModelProxyRootScope, now: datetime) -> None:
    await conn.execute(
        "UPDATE model_proxy_grants SET status='expired' WHERE tenant_id=$1 AND workspace_id=$2 "
        "AND root_run_id=$3 AND status='active' AND expires_at <= $4",
        root.tenant_id,
        root.workspace_id,
        root.root_run_id,
        now,
    )


async def is_cancelled(conn: asyncpg.Connection, cell: ModelProxyCellScope) -> bool:
    assignment = cell.assignment
    phase = assignment.phase
    root = phase.root
    if await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM model_proxy_grant_cancelled_roots "
        "WHERE tenant_id=$1 AND workspace_id=$2 AND root_run_id=$3)",
        root.tenant_id,
        root.workspace_id,
        root.root_run_id,
    ):
        return True
    if await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM model_proxy_grant_cancelled_phases "
        "WHERE tenant_id=$1 AND workspace_id=$2 AND root_run_id=$3 AND phase_id=$4)",
        root.tenant_id,
        root.workspace_id,
        root.root_run_id,
        phase.phase_id,
    ):
        return True
    if await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM model_proxy_grant_cancelled_assignments "
        "WHERE tenant_id=$1 AND workspace_id=$2 AND root_run_id=$3 AND phase_id=$4 "
        "AND assignment_id=$5)",
        root.tenant_id,
        root.workspace_id,
        root.root_run_id,
        phase.phase_id,
        assignment.assignment_id,
    ):
        return True
    return bool(
        await conn.fetchval(
            f"SELECT EXISTS(SELECT 1 FROM model_proxy_grant_cancelled_cells WHERE {CELL_WHERE})",
            *cell_params(cell),
        )
    )


async def collides(conn: asyncpg.Connection, draft: ModelProxyGrantDraft) -> bool:
    return bool(
        await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM model_proxy_grants "
            "WHERE grant_id=$1 OR bearer_digest=$2 OR startup_request_digest=$3)",
            draft.grant_id,
            draft.bearer_digest,
            draft.startup_request_digest,
        )
    )


async def highest_generation_for_cell(
    conn: asyncpg.Connection, cell: ModelProxyCellScope
) -> int | None:
    return await conn.fetchval(
        f"SELECT max(generation) FROM model_proxy_grants WHERE {CELL_WHERE}",
        *cell_params(cell),
    )


async def active_generation_exists(
    conn: asyncpg.Connection, cell: ModelProxyCellScope, generation: int, now: datetime
) -> bool:
    return bool(
        await conn.fetchval(
            f"SELECT EXISTS(SELECT 1 FROM model_proxy_grants WHERE {CELL_WHERE} "
            "AND status='active' AND expires_at > $12 AND generation=$13)",
            *cell_params(cell),
            now,
            generation,
        )
    )


async def insert_grant(conn: asyncpg.Connection, grant: StoredModelProxyGrant) -> None:
    cell = grant.binding.cell
    model = grant.binding.model
    budget = grant.binding.budget
    assignment = cell.assignment
    phase = assignment.phase
    root = phase.root
    await conn.execute(
        f"INSERT INTO model_proxy_grants ({GRANT_COLS}) VALUES "
        "($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,"
        "$21,$22,$23,$24,$25,$26,$27,$28)",
        grant.grant_id,
        root.tenant_id,
        root.workspace_id,
        root.root_run_id,
        phase.phase_id,
        assignment.assignment_id,
        cell.cell_id,
        cell.pid,
        cell.pid_start_ticks,
        cell.boot_id,
        cell.pid_namespace_inode,
        cell.cgroup_identity_digest,
        model.model_id,
        model.policy_digest,
        budget.budget_id,
        budget.max_input_tokens,
        budget.max_output_tokens,
        budget.max_total_tokens,
        budget.max_cost_micros,
        budget.policy_digest,
        grant.bearer_digest,
        grant.startup_request_digest,
        grant.issued_at,
        grant.expires_at,
        grant.generation,
        grant.status.value,
        grant.revoked_at,
        grant.revocation_reason,
    )


async def revoke_active_for_cell(
    conn: asyncpg.Connection, cell: ModelProxyCellScope, now: datetime, reason: str
) -> int:
    count = await conn.fetchval(
        f"WITH revoked AS (UPDATE model_proxy_grants SET status='revoked', "
        f"revoked_at=GREATEST($12, issued_at), revocation_reason=$13 "
        f"WHERE {CELL_WHERE} AND status='active' RETURNING 1) SELECT count(*) FROM revoked",
        *cell_params(cell),
        now,
        reason,
    )
    return count or 0


async def revoke_active_for_root(
    conn: asyncpg.Connection, root: ModelProxyRootScope, now: datetime, reason: str
) -> int:
    count = await conn.fetchval(
        "WITH revoked AS (UPDATE model_proxy_grants SET status='revoked', "
        "revoked_at=GREATEST($1, issued_at), revocation_reason=$2 "
        "WHERE tenant_id=$3 AND workspace_id=$4 AND root_run_id=$5 AND status='active' "
        "RETURNING 1) SELECT count(*) FROM revoked",
        now,
        reason,
        root.tenant_id,
        root.workspace_id,
        root.root_run_id,
    )
    return count or 0


async def revoke_active_for_phase(
    conn: asyncpg.Connection, phase: ModelProxyPhaseScope, now: datetime, reason: str
) -> int:
    root = phase.root
    count = await conn.fetchval(
        "WITH revoked AS (UPDATE model_proxy_grants SET status='revoked', "
        "revoked_at=GREATEST($1, issued_at), revocation_reason=$2 "
        "WHERE tenant_id=$3 AND workspace_id=$4 AND root_run_id=$5 AND phase_id=$6 "
        "AND status='active' RETURNING 1) SELECT count(*) FROM revoked",
        now,
        reason,
        root.tenant_id,
        root.workspace_id,
        root.root_run_id,
        phase.phase_id,
    )
    return count or 0


async def revoke_active_for_assignment(
    conn: asyncpg.Connection, assignment: ModelProxyAssignmentScope, now: datetime, reason: str
) -> int:
    phase = assignment.phase
    root = phase.root
    count = await conn.fetchval(
        "WITH revoked AS (UPDATE model_proxy_grants SET status='revoked', "
        "revoked_at=GREATEST($1, issued_at), revocation_reason=$2 "
        "WHERE tenant_id=$3 AND workspace_id=$4 AND root_run_id=$5 AND phase_id=$6 "
        "AND assignment_id=$7 AND status='active' RETURNING 1) SELECT count(*) FROM revoked",
        now,
        reason,
        root.tenant_id,
        root.workspace_id,
        root.root_run_id,
        phase.phase_id,
        assignment.assignment_id,
    )
    return count or 0


__all__ = [
    "CELL_WHERE",
    "GRANT_COLS",
    "active_generation_exists",
    "aware",
    "cell_params",
    "collides",
    "expire_due",
    "highest_generation_for_cell",
    "insert_grant",
    "is_cancelled",
    "is_digest_candidate",
    "lock_root",
    "revoke_active_for_assignment",
    "revoke_active_for_cell",
    "revoke_active_for_phase",
    "revoke_active_for_root",
    "row_to_grant",
]
