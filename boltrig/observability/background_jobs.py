"""Safe recording and projection of background-maintenance attempt evidence."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import secrets
from typing import Any, Iterable

from boltrig.models import (
    BACKGROUND_JOB_MAX_RETURNED_RECEIPTS,
    BACKGROUND_JOB_NAMES,
    BACKGROUND_JOB_RECEIPTS_PER_JOB,
    BackgroundJobReceipt,
)

log = logging.getLogger("boltrig.observability.background_jobs")

BACKGROUND_JOB_EVIDENCE_KIND = "bounded_attempt_receipt_not_liveness"
MAX_LAG_SECONDS = 365 * 24 * 60 * 60


def new_background_process_identity() -> str:
    """Return a random process identity carrying no host or deployment metadata."""
    return f"bjp_{secrets.token_hex(12)}"


async def record_background_attempt(
    store: Any,
    *,
    tenant_id: str,
    job_name: str,
    process_instance_identity: str,
    interval_seconds: float,
    attempted_at: datetime,
    succeeded: bool,
    item_count: int,
) -> None:
    """Best-effort evidence write that can never change the janitor outcome."""
    try:
        await store.record_background_job_attempt(
            tenant_id=tenant_id,
            job_name=job_name,
            process_instance_identity=process_instance_identity,
            interval_seconds=interval_seconds,
            attempted_at=attempted_at,
            succeeded=succeeded,
            item_count=item_count,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        log.warning(
            "background attempt receipt could not be recorded job=%s tenant=%s",
            job_name,
            tenant_id,
            exc_info=True,
        )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def project_background_job_receipt(
    receipt: BackgroundJobReceipt,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Project one receipt with bounded lag and explicit non-liveness semantics."""
    at = now or datetime.now(timezone.utc)
    raw_lag = (at - receipt.last_attempt_at).total_seconds()
    lag_seconds = max(0, min(round(raw_lag), MAX_LAG_SECONDS))
    stale_after_seconds = min(
        MAX_LAG_SECONDS,
        max(120, receipt.interval_seconds * 2 + 30),
    )
    if raw_lag < -60:
        state = "future_evidence"
    elif lag_seconds > stale_after_seconds:
        state = f"stale_{receipt.last_outcome}_evidence"
    else:
        state = f"recent_{receipt.last_outcome}_evidence"
    return {
        "job_name": receipt.job_name,
        "process_instance_identity": receipt.process_instance_identity,
        "state": state,
        "last_outcome": receipt.last_outcome,
        "last_attempt_at": _iso(receipt.last_attempt_at),
        "last_success_at": _iso(receipt.last_success_at),
        "last_failure_at": _iso(receipt.last_failure_at),
        "failure_code": receipt.failure_code,
        "last_item_count": receipt.last_item_count,
        "interval_seconds": receipt.interval_seconds,
        "lag_seconds": lag_seconds,
        "stale_after_seconds": stale_after_seconds,
        "evidence_kind": BACKGROUND_JOB_EVIDENCE_KIND,
        "proves_liveness": False,
        "process_coverage": "bounded_receipts_not_replica_inventory",
    }


def project_background_job_receipts(
    receipts: Iterable[BackgroundJobReceipt],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    return [
        project_background_job_receipt(receipt, now=now)
        for receipt in receipts
    ]


def background_job_readiness_checks(
    receipts: Iterable[BackgroundJobReceipt],
    *,
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """Summarize only the newest retained receipt for each job.

    The summary is optional readiness context.  It never gates traffic and never
    upgrades a bounded historical attempt into cross-process liveness.
    """
    at = now or datetime.now(timezone.utc)
    rows = tuple(receipts)
    checks: dict[str, dict[str, Any]] = {}
    for job_name in BACKGROUND_JOB_NAMES:
        job_rows = [row for row in rows if row.job_name == job_name]
        if not job_rows:
            checks[f"{job_name}_janitor"] = {
                "status": "unknown",
                "required": False,
                "reason": "attempt_evidence_not_observed",
                "evidence_kind": BACKGROUND_JOB_EVIDENCE_KIND,
                "proves_liveness": False,
                "process_coverage": "bounded_receipts_not_replica_inventory",
                "observed_process_receipts": 0,
            }
            continue
        latest = max(
            job_rows,
            key=lambda row: (row.last_attempt_at, row.process_instance_identity),
        )
        projected = project_background_job_receipt(latest, now=at)
        state = projected["state"]
        status = "ok" if state == "recent_succeeded_evidence" else "degraded"
        checks[f"{job_name}_janitor"] = {
            "status": status,
            "required": False,
            "reason": state,
            "evidence_kind": BACKGROUND_JOB_EVIDENCE_KIND,
            "proves_liveness": False,
            "process_coverage": "bounded_receipts_not_replica_inventory",
            "observed_process_receipts": len(job_rows),
            "last_attempt_at": projected["last_attempt_at"],
            "last_success_at": projected["last_success_at"],
            "last_failure_at": projected["last_failure_at"],
            "lag_seconds": projected["lag_seconds"],
            "interval_seconds": projected["interval_seconds"],
            "last_item_count": projected["last_item_count"],
        }
    return checks


async def background_job_platform_fields(
    store: Any,
    tenant_id: str,
) -> dict[str, Any]:
    """Return the complete safe authenticated platform-status fragment."""
    try:
        receipts = await store.list_background_job_receipts(tenant_id)
        background_jobs = project_background_job_receipts(receipts)
        evidence_status = "available"
    except Exception:
        background_jobs = []
        evidence_status = "unavailable"
    return {
        "background_jobs": background_jobs,
        "background_job_evidence": {
            "status": evidence_status,
            "evidence_kind": BACKGROUND_JOB_EVIDENCE_KIND,
            "proves_liveness": False,
            "process_coverage": "bounded_receipts_not_replica_inventory",
            "max_retained_process_receipts_per_job": (
                BACKGROUND_JOB_RECEIPTS_PER_JOB
            ),
            "max_returned_receipts": BACKGROUND_JOB_MAX_RETURNED_RECEIPTS,
        },
    }


__all__ = [
    "BACKGROUND_JOB_EVIDENCE_KIND",
    "background_job_platform_fields",
    "background_job_readiness_checks",
    "new_background_process_identity",
    "project_background_job_receipt",
    "project_background_job_receipts",
    "record_background_attempt",
]
