"""Durable asyncpg adapter for immutable root-engine decisions."""

from __future__ import annotations

import asyncpg

from boltrig.fleet.domain.codex_rollout import (
    CodexCompatibility,
    EngineRoute,
    ExecutionResultSource,
    RootEngineDecision,
    RootRouteScope,
    RootWorkload,
    RoutingReason,
)
from boltrig.fleet.ports.root_engine_decisions import (
    RootEngineDecisionConflict,
    RootEngineDecisionInsertResult,
    RootEngineDecisionInsertStatus,
)

_INSERT_SQL = """
    INSERT INTO root_engine_decisions (
        tenant_id, workspace_id, root_run_id,
        workload, compatibility, policy_generation, policy_digest,
        route, execution_result_source, reason_code, canary_bucket,
        decision_digest
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
    ON CONFLICT (tenant_id, workspace_id, root_run_id) DO NOTHING
    RETURNING decision_digest
"""

_SELECT_SQL = """
    SELECT workload, compatibility, policy_generation, policy_digest,
           route, execution_result_source, reason_code, canary_bucket,
           decision_digest
    FROM root_engine_decisions
    WHERE tenant_id = $1 AND workspace_id = $2 AND root_run_id = $3
"""


class PostgresRootEngineDecisionStore:
    """Durable insert-once root decision store backed by PostgreSQL.

    Every statement is scoped by the exact (tenant, workspace, root) primary key,
    matching the in-memory adapter's semantics. An insert that lands returns the
    caller's own decision by identity; a primary-key conflict is resolved inside
    one transaction by comparing the retained canonical digest, so an exact replay
    returns the stored value while a divergent decision fails closed.
    """

    __slots__ = ("_pool",)

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    def __repr__(self) -> str:
        return "PostgresRootEngineDecisionStore(bounded=False)"

    async def insert_once(
        self, decision: RootEngineDecision
    ) -> RootEngineDecisionInsertResult:
        if type(decision) is not RootEngineDecision:
            raise TypeError("decision must be an exact RootEngineDecision")
        scope = decision.scope
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                inserted = await conn.fetchrow(
                    _INSERT_SQL,
                    scope.tenant_id,
                    scope.workspace_id,
                    scope.root_run_id,
                    decision.workload.value,
                    decision.compatibility.value,
                    decision.policy_generation,
                    decision.policy_digest,
                    decision.route.value,
                    decision.execution_result_source.value,
                    decision.reason_code.value,
                    decision.canary_bucket,
                    decision.digest,
                )
                if inserted is not None:
                    return RootEngineDecisionInsertResult(
                        RootEngineDecisionInsertStatus.INSERTED, decision
                    )
                retained = await conn.fetchrow(
                    _SELECT_SQL,
                    scope.tenant_id,
                    scope.workspace_id,
                    scope.root_run_id,
                )
                # ON CONFLICT fired so a row must exist; fail closed if it does not.
                if retained is None or retained["decision_digest"] != decision.digest:
                    raise RootEngineDecisionConflict(
                        "root engine decision conflicts with immutable history"
                    )
                return RootEngineDecisionInsertResult(
                    RootEngineDecisionInsertStatus.REPLAYED,
                    _row_to_decision(retained, scope),
                )

    async def get(self, scope: RootRouteScope) -> RootEngineDecision | None:
        if type(scope) is not RootRouteScope:
            raise TypeError("scope must be an exact RootRouteScope")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                _SELECT_SQL, scope.tenant_id, scope.workspace_id, scope.root_run_id
            )
            return None if row is None else _row_to_decision(row, scope)


def _row_to_decision(
    row: asyncpg.Record, scope: RootRouteScope
) -> RootEngineDecision:
    return RootEngineDecision(
        scope=scope,
        workload=RootWorkload(row["workload"]),
        compatibility=CodexCompatibility(row["compatibility"]),
        policy_generation=row["policy_generation"],
        policy_digest=row["policy_digest"],
        route=EngineRoute(row["route"]),
        execution_result_source=ExecutionResultSource(row["execution_result_source"]),
        reason_code=RoutingReason(row["reason_code"]),
        canary_bucket=row["canary_bucket"],
    )


__all__ = ["PostgresRootEngineDecisionStore"]
