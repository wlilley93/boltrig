"""Queued memory projection fanout.

The canonical memory write/delete stays in the kernel ledger. This module only
turns projection catch-up into named task payloads so Mem0/Cognee writes can run
on the existing executor seam instead of blocking the request path.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from boltrig.models import GrantSet, InvocationContext, TenantIsolation, utcnow

from .engine import EngineFact
from .projection_delivery_attempts import (
    failure_row,
    run_forget_delivery,
    run_remember_delivery,
)
from .projections import (
    MemoryProjection,
    MemoryProjectionFanout,
    _public,
    _row,
)

_DEFAULT_TASK_NAME = "boltrig-memory-projection"
_QUEUED_MODES = {"async", "queue", "queued", "worker", "workers"}
_DEFAULT_MAX_OPERATION_ATTEMPTS = 3
_MAX_OPERATION_ATTEMPTS = 5


def is_queued_projection_mode(value: Any) -> bool:
    return str(value or "").strip().lower() in _QUEUED_MODES


class QueuedMemoryProjectionFanout(MemoryProjectionFanout):
    """Projection fanout that submits one backend operation per executor task."""

    def __init__(
        self,
        store: Any,
        projections: list[MemoryProjection] | None = None,
        *,
        primary_projection_id: str = "mem0",
        executor: Any = None,
        task_name: str = _DEFAULT_TASK_NAME,
        max_operation_attempts: int = _DEFAULT_MAX_OPERATION_ATTEMPTS,
    ) -> None:
        super().__init__(
            store, projections, primary_projection_id=primary_projection_id
        )
        self._executor = executor
        self._task_name = task_name
        attempts = int(max_operation_attempts)
        if attempts < 1 or attempts > _MAX_OPERATION_ATTEMPTS:
            raise ValueError(
                f"max_operation_attempts must be between 1 and {_MAX_OPERATION_ATTEMPTS}"
            )
        self._max_operation_attempts = attempts

    def register_executor(self, executor: Any, *, task_name: str | None = None) -> None:
        """Attach an executor; fleet owns task registration for this task name."""
        if task_name:
            self._task_name = task_name
        self._executor = executor

    def projection_delivery_posture(self) -> dict[str, Any]:
        """Return safe facts about this live queue seam, never its task payloads."""
        durable = getattr(self._executor, "durable", None)
        if self._executor is None:
            execution_mode = "inline_no_queue"
        elif durable is True:
            execution_mode = "durable_executor"
        elif durable is False:
            execution_mode = "local_inline_fallback"
        else:
            execution_mode = "external_executor_durability_unknown"
        return {
            "status": "configured" if self._projections else "no_projections",
            "execution_mode": execution_mode,
            "configured_projection_count": len(self._projections),
            "max_operation_attempts": self._max_operation_attempts,
            "retry_scope": "single_task_invocation",
            "enqueue_retry": "disabled_ambiguous_acceptance",
            "payload_retention": "executor_owned_not_in_status_receipt",
            "manual_retry": "unavailable_original_payload_not_retained",
            "proves_worker_liveness": False,
        }

    async def remember(
        self, tenant_id: str, fact: EngineFact, context: InvocationContext
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for projection in self._projections:
            row_id = f"{projection.id}:remember:{fact.id}"
            pending = _row(
                tenant_id=tenant_id,
                projection_id=projection.id,
                operation="remember",
                status="pending",
                fact_id=fact.id,
                target=None,
                max_operation_attempts=self._max_operation_attempts,
                row_id=row_id,
            )
            await self._upsert(pending)
            payload = {
                "tenant_id": tenant_id,
                "projection_id": projection.id,
                "operation": "remember",
                "row_id": row_id,
                "fact": _fact_payload(fact),
                "ctx_envelope": _context_payload(context),
            }
            rows.append(await self._submit_or_run(payload, pending))
        return rows

    async def forget(
        self, tenant_id: str, fact_ids: list[str], context: InvocationContext
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for fact_id in fact_ids:
            previous = {
                row.projection_id: row
                for row in await self._list(tenant_id, fact_id=fact_id, limit=100)
                if row.operation == "remember"
            }
            for projection in self._projections:
                row_id = f"{projection.id}:forget:{fact_id}"
                prior = previous.get(projection.id)
                projection_ref = getattr(prior, "projection_ref", None)
                pending = _row(
                    tenant_id=tenant_id,
                    projection_id=projection.id,
                    operation="forget",
                    status="pending",
                    fact_id=fact_id,
                    target=fact_id,
                    projection_ref=projection_ref,
                    max_operation_attempts=self._max_operation_attempts,
                    row_id=row_id,
                )
                await self._upsert(pending)
                payload = {
                    "tenant_id": tenant_id,
                    "projection_id": projection.id,
                    "operation": "forget",
                    "row_id": row_id,
                    "fact_id": fact_id,
                    "projection_ref": projection_ref,
                    "ctx_envelope": _context_payload(context),
                }
                rows.append(await self._submit_or_run(payload, pending))
        return rows

    async def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run one queued projection operation and finalise its status row."""
        _fence(payload)
        operation = str(payload.get("operation") or "")
        if operation == "remember":
            return await run_remember_delivery(
                self,
                payload,
                _fact_from_payload(payload["fact"]),
                _context_from_payload(payload["ctx_envelope"]),
            )
        if operation == "forget":
            return await run_forget_delivery(
                self,
                payload,
                _context_from_payload(payload["ctx_envelope"]),
            )
        raise ValueError(f"unknown memory projection operation {operation!r}")

    async def _submit_or_run(self, payload: dict[str, Any], pending) -> dict[str, Any]:
        if self._executor is None:
            return await self.process(payload)
        enqueued = replace(
            pending,
            enqueue_attempts=1,
            updated_at=utcnow(),
        )
        await self._upsert(enqueued)
        try:
            await self._executor.enqueue(self._task_name, payload)
        except Exception:
            final = failure_row(
                payload,
                "enqueue_failed",
                enqueue_attempts=1,
                max_operation_attempts=self._max_operation_attempts,
            )
            await self._upsert(final)
            return _public(final)
        return _public(enqueued)

    def _projection(self, projection_id: str) -> MemoryProjection:
        for projection in self._projections:
            if projection.id == projection_id:
                return projection
        raise LookupError(f"unknown memory projection {projection_id!r}")

def _fence(payload: dict[str, Any]) -> None:
    env = payload.get("ctx_envelope") or {}
    if payload.get("tenant_id") != env.get("tenant_id"):
        raise TenantIsolation(
            f"projection payload tenant '{payload.get('tenant_id')}' != "
            f"envelope tenant '{env.get('tenant_id')}'"
        )


def _fact_payload(fact: EngineFact) -> dict[str, Any]:
    return {
        "id": fact.id,
        "owner_scope": fact.owner_scope,
        "kind": fact.kind,
        "content": fact.content,
        "data_class": fact.data_class,
        "source_kind": fact.source_kind,
        "source_ref": fact.source_ref,
        "relates_to": list(fact.relates_to),
    }


def _fact_from_payload(data: dict[str, Any]) -> EngineFact:
    return EngineFact(
        id=str(data["id"]),
        owner_scope=str(data["owner_scope"]),
        kind=str(data["kind"]),
        content=str(data["content"]),
        data_class=str(data.get("data_class") or "standard"),
        source_kind=str(data.get("source_kind") or "verb_result"),
        source_ref=data.get("source_ref"),
        relates_to=list(data.get("relates_to") or []),
    )


def _context_payload(ctx: InvocationContext) -> dict[str, Any]:
    return {
        "tenant_id": ctx.tenant_id,
        "run_id": ctx.run_id,
        "parent_run_id": ctx.parent_run_id,
        "depth": ctx.depth,
        "on_behalf_of": ctx.on_behalf_of,
        "workspace_id": ctx.workspace_id,
        "ip_address": ctx.ip_address,
        "user_agent": ctx.user_agent,
        "grants": {"allow": list(ctx.grants.allow), "deny": list(ctx.grants.deny)},
        "actor": ctx.actor,
        "actor_tier": ctx.actor_tier,
        "skills_loaded": list(ctx.skills_loaded),
        "extra": dict(ctx.extra),
    }


def _context_from_payload(data: dict[str, Any]) -> InvocationContext:
    grants = data.get("grants") or {}
    return InvocationContext(
        tenant_id=data["tenant_id"],
        run_id=data.get("run_id"),
        parent_run_id=data.get("parent_run_id"),
        depth=int(data.get("depth") or 0),
        on_behalf_of=data.get("on_behalf_of"),
        workspace_id=data.get("workspace_id"),
        ip_address=data.get("ip_address"),
        user_agent=data.get("user_agent"),
        grants=GrantSet.of(list(grants.get("allow") or []), list(grants.get("deny") or [])),
        actor=data.get("actor", "unknown"),
        actor_tier=data.get("actor_tier", "ephemeral"),
        skills_loaded=tuple(data.get("skills_loaded") or ()),
        extra=dict(data.get("extra") or {}),
    )
