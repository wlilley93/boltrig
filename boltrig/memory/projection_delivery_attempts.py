"""Bounded attempt execution for one queued memory projection task."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Awaitable, Callable

from boltrig.models import InvocationContext, MemoryProjectionStatus, utcnow

from .engine import EngineFact
from .projections import _check_status, _public, _row


class _ProjectionReportedFailure(Exception):
    pass


async def run_remember_delivery(
    fanout: Any,
    payload: dict[str, Any],
    fact: EngineFact,
    context: InvocationContext,
) -> dict[str, Any]:
    async def call() -> tuple[str, str | None]:
        projection = fanout._projection(str(payload["projection_id"]))
        result = await projection.remember(
            str(payload["tenant_id"]),
            fact,
            context,
        )
        status = _check_status("remember", result.status, final=True)
        if status == "failed":
            raise _ProjectionReportedFailure
        return status, result.projection_ref

    return await _run_attempts(
        fanout,
        payload,
        fact_id=fact.id,
        call=call,
    )


async def run_forget_delivery(
    fanout: Any,
    payload: dict[str, Any],
    context: InvocationContext,
) -> dict[str, Any]:
    fact_id = str(payload["fact_id"])
    projection_ref = payload.get("projection_ref")

    async def call() -> tuple[str, str | None]:
        projection = fanout._projection(str(payload["projection_id"]))
        result = await projection.forget(
            str(payload["tenant_id"]),
            fact_id=fact_id,
            projection_ref=projection_ref,
            context=context,
        )
        status = _check_status("forget", result.status, final=True)
        if status == "delete_failed":
            raise _ProjectionReportedFailure
        return status, result.projection_ref or projection_ref

    return await _run_attempts(
        fanout,
        payload,
        fact_id=fact_id,
        call=call,
    )


async def _run_attempts(
    fanout: Any,
    payload: dict[str, Any],
    *,
    fact_id: str,
    call: Callable[[], Awaitable[tuple[str, str | None]]],
) -> dict[str, Any]:
    previous = await _current_row(
        fanout,
        tenant_id=str(payload["tenant_id"]),
        fact_id=fact_id,
        row_id=str(payload["row_id"]),
    )
    if (
        previous is not None
        and previous.status in {"written", "failed", "deleted", "delete_failed"}
        and previous.failure_code != "enqueue_failed"
    ):
        return _public(previous)

    completed_attempts = getattr(previous, "operation_attempts", 0)
    max_attempts = getattr(
        previous, "max_operation_attempts", fanout._max_operation_attempts
    )
    first_attempt_at = previous.first_attempt_at if previous is not None else None
    last_failure_at = previous.last_failure_at if previous is not None else None
    failure_code = previous.failure_code if previous is not None else None
    final = None
    for attempt in range(completed_attempts + 1, max_attempts + 1):
        attempted_at = utcnow()
        first_attempt_at = first_attempt_at or attempted_at
        try:
            status, result_ref = await call()
            final = _delivery_row(
                fanout,
                payload,
                status=status,
                fact_id=fact_id,
                projection_ref=result_ref,
                attempt=attempt,
                max_operation_attempts=max_attempts,
                first_attempt_at=first_attempt_at,
                last_attempt_at=attempted_at,
                last_failure_at=last_failure_at,
                failure_code=failure_code,
            )
            break
        except Exception as exc:
            last_failure_at = attempted_at
            failure_code = _failure_code(exc)
            final = failure_row(
                payload,
                failure_code,
                enqueue_attempts=_enqueue_attempts(fanout),
                operation_attempts=attempt,
                max_operation_attempts=max_attempts,
                first_attempt_at=first_attempt_at,
                last_attempt_at=attempted_at,
                last_failure_at=last_failure_at,
            )
            if attempt < max_attempts:
                final.status = "pending"
                await fanout._upsert(final)
                continue
    if final is None:
        final = failure_row(
            payload,
            failure_code or "projection_operation_failed",
            enqueue_attempts=_enqueue_attempts(fanout),
            operation_attempts=max_attempts,
            max_operation_attempts=max_attempts,
            first_attempt_at=first_attempt_at,
            last_attempt_at=previous.last_attempt_at if previous is not None else None,
            last_failure_at=last_failure_at,
        )
    assert final is not None
    await fanout._upsert(final)
    return _public(final)


async def _current_row(
    fanout: Any,
    *,
    tenant_id: str,
    fact_id: str,
    row_id: str,
) -> MemoryProjectionStatus | None:
    rows = await fanout._list(tenant_id, fact_id=fact_id, limit=100)
    return next((row for row in rows if row.id == row_id), None)


def _delivery_row(
    fanout: Any,
    payload: dict[str, Any],
    *,
    status: str,
    fact_id: str,
    projection_ref: str | None,
    attempt: int,
    max_operation_attempts: int,
    first_attempt_at: datetime,
    last_attempt_at: datetime,
    last_failure_at: datetime | None,
    failure_code: str | None,
) -> MemoryProjectionStatus:
    operation = str(payload["operation"])
    return _row(
        tenant_id=str(payload["tenant_id"]),
        projection_id=str(payload["projection_id"]),
        operation=operation,
        status=status,
        fact_id=fact_id,
        target=fact_id if operation == "forget" else None,
        projection_ref=projection_ref,
        enqueue_attempts=_enqueue_attempts(fanout),
        operation_attempts=attempt,
        max_operation_attempts=max_operation_attempts,
        first_attempt_at=first_attempt_at,
        last_attempt_at=last_attempt_at,
        last_failure_at=last_failure_at,
        failure_code=failure_code,
        row_id=str(payload["row_id"]),
    )


def failure_row(
    payload: dict[str, Any],
    failure_code: str,
    *,
    enqueue_attempts: int = 0,
    operation_attempts: int = 0,
    max_operation_attempts: int = 1,
    first_attempt_at: datetime | None = None,
    last_attempt_at: datetime | None = None,
    last_failure_at: datetime | None = None,
) -> MemoryProjectionStatus:
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
        enqueue_attempts=enqueue_attempts,
        operation_attempts=operation_attempts,
        max_operation_attempts=max_operation_attempts,
        first_attempt_at=first_attempt_at,
        last_attempt_at=last_attempt_at,
        last_failure_at=last_failure_at,
        failure_code=failure_code,
        row_id=str(payload.get("row_id") or ""),
    )


def _enqueue_attempts(fanout: Any) -> int:
    return 1 if fanout._executor is not None else 0


def _failure_code(exc: Exception) -> str:
    if isinstance(exc, LookupError):
        return "projection_not_configured"
    if isinstance(exc, ValueError) and "projection status" in str(exc):
        return "invalid_projection_result"
    return "projection_operation_failed"
