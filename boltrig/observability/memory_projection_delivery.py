"""Safe bounded evidence for memory projection delivery."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any, Iterable

from boltrig.models import MemoryProjectionStatus

MAX_MEMORY_PROJECTION_RECEIPTS = 50
_READ_LIMIT = MAX_MEMORY_PROJECTION_RECEIPTS + 1
_MAX_AGE_SECONDS = 365 * 24 * 60 * 60
MEMORY_PROJECTION_EVIDENCE_KIND = "bounded_status_receipts_not_queue_or_worker_liveness"


def _opaque(prefix: str, tenant_id: str, value: str) -> str:
    digest = hashlib.sha256(f"{tenant_id}:{value}".encode()).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _age_seconds(later: datetime, earlier: datetime | None) -> int | None:
    if earlier is None:
        return None
    return max(0, min(round((later - earlier).total_seconds()), _MAX_AGE_SECONDS))


def _state(row: MemoryProjectionStatus) -> str:
    if row.status == "pending":
        return (
            "retry_attempt_observed"
            if row.operation_attempts
            else "queued_not_yet_attempted"
        )
    if row.status in {"written", "deleted"}:
        return (
            "delivered_after_retry"
            if row.operation_attempts > 1
            else "delivered"
        )
    if row.failure_code == "enqueue_failed":
        return "enqueue_failed_retry_unsafe"
    if row.operation_attempts >= row.max_operation_attempts:
        return "terminal_after_retry_cap"
    return "terminal_failure_attempt_count_unknown"


def project_memory_projection_receipt(
    row: MemoryProjectionStatus,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    at = now or datetime.now(timezone.utc)
    terminal = row.status in {"written", "failed", "deleted", "delete_failed"}
    return {
        "receipt_identity": _opaque("mpr", row.tenant_id, row.id),
        "projection_identity": _opaque(
            "mp",
            row.tenant_id,
            row.projection_id,
        ),
        "operation": row.operation,
        "state": _state(row),
        "status": row.status,
        "enqueue_attempts": row.enqueue_attempts,
        "operation_attempts": row.operation_attempts,
        "max_operation_attempts": row.max_operation_attempts,
        "queued_at": _iso(row.created_at),
        "first_attempt_at": _iso(row.first_attempt_at),
        "last_attempt_at": _iso(row.last_attempt_at),
        "last_failure_at": _iso(row.last_failure_at),
        "last_failure_code": row.failure_code,
        "queue_wait_seconds": (
            _age_seconds(row.first_attempt_at, row.created_at)
            if row.first_attempt_at is not None
            else None
        ),
        "pending_age_seconds": (
            _age_seconds(at, row.created_at)
            if row.status == "pending"
            else None
        ),
        "terminal_at": _iso(row.updated_at) if terminal else None,
        "content_retained_in_receipt": False,
        "manual_retry": (
            "unavailable_original_payload_not_retained"
            if row.status in {"failed", "delete_failed"}
            else "not_applicable"
        ),
    }


def project_memory_projection_receipts(
    rows: Iterable[MemoryProjectionStatus],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    return [
        project_memory_projection_receipt(row, now=now)
        for row in rows
    ]


def _queue_posture(kernel: Any, tenant_id: str) -> dict[str, Any]:
    try:
        adapter = kernel.loader.peek(tenant_id, "memory")
        fanout = getattr(adapter, "_projections", None)
        posture = getattr(fanout, "projection_delivery_posture", None)
        value = posture() if callable(posture) else None
    except Exception:
        value = None
    return value if isinstance(value, dict) else {
        "status": "unavailable",
        "execution_mode": "unknown",
        "configured_projection_count": 0,
        "max_operation_attempts": 0,
        "retry_scope": "unknown",
        "enqueue_retry": "unknown",
        "payload_retention": "not_observed",
        "manual_retry": "unavailable_original_payload_not_retained",
        "proves_worker_liveness": False,
    }


async def memory_projection_delivery_fields(
    kernel: Any,
    tenant_id: str,
) -> dict[str, Any]:
    try:
        rows = await kernel.store.list_memory_projection_statuses(
            tenant_id,
            limit=_READ_LIMIT,
        )
        status = "available"
    except Exception:
        rows = []
        status = "unavailable"
    return {
        "memory_projection_delivery": {
            "status": status,
            "evidence_kind": MEMORY_PROJECTION_EVIDENCE_KIND,
            "proves_queue_depth": False,
            "proves_worker_liveness": False,
            "queue_posture": _queue_posture(kernel, tenant_id),
            "receipts": project_memory_projection_receipts(
                rows[:MAX_MEMORY_PROJECTION_RECEIPTS]
            ),
            "max_returned_receipts": MAX_MEMORY_PROJECTION_RECEIPTS,
            "truncated": len(rows) > MAX_MEMORY_PROJECTION_RECEIPTS,
            "manual_retry": "unavailable_original_payload_not_retained",
        }
    }


__all__ = [
    "MAX_MEMORY_PROJECTION_RECEIPTS",
    "MEMORY_PROJECTION_EVIDENCE_KIND",
    "memory_projection_delivery_fields",
    "project_memory_projection_receipt",
    "project_memory_projection_receipts",
]
