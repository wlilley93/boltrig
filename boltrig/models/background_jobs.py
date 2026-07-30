"""Bounded, secret-free evidence from periodic background maintenance loops.

These receipts record completed attempts.  They are deliberately not heartbeats:
an old receipt can show that one opaque process instance ran a job at a point in
time, but cannot prove that process is still alive or that every replica is
represented.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re

from .base import TenantId

BACKGROUND_JOB_NAMES = ("hitl_expiry", "retention")
BACKGROUND_JOB_OUTCOMES = ("succeeded", "failed")
BACKGROUND_JOB_RECEIPTS_PER_JOB = 4
BACKGROUND_JOB_MAX_RETURNED_RECEIPTS = (
    len(BACKGROUND_JOB_NAMES) * BACKGROUND_JOB_RECEIPTS_PER_JOB
)
BACKGROUND_JOB_MAX_INTERVAL_SECONDS = 7 * 24 * 60 * 60
BACKGROUND_JOB_MAX_ITEM_COUNT = 1_000_000

_PROCESS_IDENTITY = re.compile(r"^bjp_[a-f0-9]{24}$")


@dataclass(frozen=True)
class BackgroundJobReceipt:
    """The latest attempt history for one job in one opaque process instance."""

    tenant_id: TenantId
    job_name: str
    process_instance_identity: str
    interval_seconds: int
    last_attempt_at: datetime
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_outcome: str
    failure_code: str | None
    last_item_count: int
    receipt_kind: str = "attempt_history_not_liveness"

    def __post_init__(self) -> None:
        if not str(self.tenant_id).strip():
            raise ValueError("tenant_id is required")
        if self.job_name not in BACKGROUND_JOB_NAMES:
            raise ValueError("background job name is invalid")
        if not _PROCESS_IDENTITY.fullmatch(self.process_instance_identity):
            raise ValueError("background process identity is invalid")
        if not 1 <= self.interval_seconds <= BACKGROUND_JOB_MAX_INTERVAL_SECONDS:
            raise ValueError("background job interval is outside the bounded range")
        timestamps = (
            self.last_attempt_at,
            self.last_success_at,
            self.last_failure_at,
        )
        if any(value is not None and value.tzinfo is None for value in timestamps):
            raise ValueError("background job timestamps must be timezone-aware")
        if self.last_success_at is not None and self.last_success_at > self.last_attempt_at:
            raise ValueError("background job success cannot follow its latest attempt")
        if self.last_failure_at is not None and self.last_failure_at > self.last_attempt_at:
            raise ValueError("background job failure cannot follow its latest attempt")
        if self.last_outcome not in BACKGROUND_JOB_OUTCOMES:
            raise ValueError("background job outcome is invalid")
        if self.last_outcome == "succeeded":
            if self.last_success_at != self.last_attempt_at or self.failure_code is not None:
                raise ValueError("successful background job receipt has invalid shape")
        elif (
            self.last_failure_at != self.last_attempt_at
            or self.failure_code != "sweep_failed"
        ):
            raise ValueError("failed background job receipt has invalid shape")
        if not 0 <= self.last_item_count <= BACKGROUND_JOB_MAX_ITEM_COUNT:
            raise ValueError("background job item count is outside the bounded range")
        if self.receipt_kind != "attempt_history_not_liveness":
            raise ValueError("background job receipt kind is invalid")


__all__ = [
    "BACKGROUND_JOB_MAX_INTERVAL_SECONDS",
    "BACKGROUND_JOB_MAX_ITEM_COUNT",
    "BACKGROUND_JOB_MAX_RETURNED_RECEIPTS",
    "BACKGROUND_JOB_NAMES",
    "BACKGROUND_JOB_OUTCOMES",
    "BACKGROUND_JOB_RECEIPTS_PER_JOB",
    "BackgroundJobReceipt",
]
