"""PostgreSQL row mapping for durable memory-projection receipts."""

from __future__ import annotations

from boltrig.models import MemoryProjectionStatus


def _mem_projection(row):
    if row is None:
        return None
    return MemoryProjectionStatus(
        id=row["id"],
        tenant_id=row["tenant_id"],
        projection_id=row["projection_id"],
        operation=row["operation"],
        status=row["status"],
        fact_id=row["fact_id"],
        target=row["target"],
        projection_ref=row["projection_ref"],
        error=row["error"],
        enqueue_attempts=row["enqueue_attempts"],
        operation_attempts=row["operation_attempts"],
        max_operation_attempts=row["max_operation_attempts"],
        first_attempt_at=row["first_attempt_at"],
        last_attempt_at=row["last_attempt_at"],
        last_failure_at=row["last_failure_at"],
        failure_code=row["failure_code"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


__all__ = ["_mem_projection"]
