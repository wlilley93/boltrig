"""Queued memory projection fanout.

The canonical memory write/delete stays in the kernel ledger. This module only
turns projection catch-up into named task payloads so Mem0/Cognee writes can run
on the existing executor seam instead of blocking the request path.
"""

from __future__ import annotations

from typing import Any

from boltrig.models import GrantSet, InvocationContext, TenantIsolation

from .engine import EngineFact
from .projections import (
    MemoryProjection,
    MemoryProjectionFanout,
    _check_status,
    _public,
    _row,
    _short_error,
)

_DEFAULT_TASK_NAME = "boltrig-memory-projection"
_QUEUED_MODES = {"async", "queue", "queued", "worker", "workers"}


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
    ) -> None:
        super().__init__(
            store, projections, primary_projection_id=primary_projection_id
        )
        self._executor = executor
        self._task_name = task_name

    def register_executor(self, executor: Any, *, task_name: str | None = None) -> None:
        """Attach an executor; fleet owns task registration for this task name."""
        if task_name:
            self._task_name = task_name
        self._executor = executor

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
            return await self._process_remember(payload)
        if operation == "forget":
            return await self._process_forget(payload)
        raise ValueError(f"unknown memory projection operation {operation!r}")

    async def _submit_or_run(self, payload: dict[str, Any], pending) -> dict[str, Any]:
        if self._executor is None:
            return await self.process(payload)
        try:
            await self._executor.enqueue(self._task_name, payload)
        except Exception as exc:
            final = _failure_row(payload, _short_error(exc))
            await self._upsert(final)
            return _public(final)
        return _public(pending)

    async def _process_remember(self, payload: dict[str, Any]) -> dict[str, Any]:
        fact = _fact_from_payload(payload["fact"])
        try:
            projection = self._projection(str(payload["projection_id"]))
            result = await projection.remember(
                str(payload["tenant_id"]), fact, _context_from_payload(payload["ctx_envelope"])
            )
            status = _check_status("remember", result.status, final=True)
            final = _row(
                tenant_id=str(payload["tenant_id"]),
                projection_id=projection.id,
                operation="remember",
                status=status,
                fact_id=fact.id,
                target=None,
                projection_ref=result.projection_ref,
                error=result.error,
                row_id=str(payload["row_id"]),
            )
        except Exception as exc:
            final = _failure_row(payload, _short_error(exc))
        await self._upsert(final)
        return _public(final)

    async def _process_forget(self, payload: dict[str, Any]) -> dict[str, Any]:
        fact_id = str(payload["fact_id"])
        projection_ref = payload.get("projection_ref")
        try:
            projection = self._projection(str(payload["projection_id"]))
            result = await projection.forget(
                str(payload["tenant_id"]),
                fact_id=fact_id,
                projection_ref=projection_ref,
                context=_context_from_payload(payload["ctx_envelope"]),
            )
            status = _check_status("forget", result.status, final=True)
            final = _row(
                tenant_id=str(payload["tenant_id"]),
                projection_id=projection.id,
                operation="forget",
                status=status,
                fact_id=fact_id,
                target=fact_id,
                projection_ref=result.projection_ref or projection_ref,
                error=result.error,
                row_id=str(payload["row_id"]),
            )
        except Exception as exc:
            final = _failure_row(payload, _short_error(exc))
        await self._upsert(final)
        return _public(final)

    def _projection(self, projection_id: str) -> MemoryProjection:
        for projection in self._projections:
            if projection.id == projection_id:
                return projection
        raise LookupError(f"unknown memory projection {projection_id!r}")


def _failure_row(payload: dict[str, Any], error: str):
    operation = str(payload.get("operation") or "")
    fact_id = payload.get("fact_id") or (payload.get("fact") or {}).get("id")
    return _row(
        tenant_id=str(payload.get("tenant_id") or ""),
        projection_id=str(payload.get("projection_id") or ""),
        operation=operation,
        status="failed" if operation == "remember" else "delete_failed",
        fact_id=str(fact_id) if fact_id is not None else None,
        target=str(fact_id) if operation == "forget" and fact_id is not None else None,
        projection_ref=payload.get("projection_ref"),
        error=error,
        row_id=str(payload.get("row_id") or ""),
    )


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
