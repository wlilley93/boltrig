"""Bounded readiness summaries for fleet-owned background maintenance."""

from __future__ import annotations

import asyncio
from typing import Any

from boltrig.models import BACKGROUND_JOB_NAMES
from boltrig.observability.background_jobs import (
    BACKGROUND_JOB_EVIDENCE_KIND,
    background_job_readiness_checks,
)


def _unavailable_checks() -> dict[str, dict[str, Any]]:
    return {
        f"{job_name}_janitor": {
            "status": "unknown",
            "required": False,
            "reason": "attempt_evidence_unavailable",
            "evidence_kind": BACKGROUND_JOB_EVIDENCE_KIND,
            "proves_liveness": False,
            "process_coverage": "bounded_receipts_not_replica_inventory",
            "observed_process_receipts": 0,
        }
        for job_name in BACKGROUND_JOB_NAMES
    }


async def read_background_job_readiness(
    store: Any,
    tenant_id: str,
    *,
    timeout_s: float,
) -> dict[str, dict[str, Any]]:
    """Read optional attempt evidence without making traffic depend on it."""
    try:
        receipts = await asyncio.wait_for(
            store.list_background_job_receipts(tenant_id),
            timeout=timeout_s,
        )
    except Exception:
        return _unavailable_checks()
    return background_job_readiness_checks(receipts)


__all__ = ["read_background_job_readiness"]
