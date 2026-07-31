"""Store parity for bounded background-maintenance attempt receipts."""

from __future__ import annotations

from .tenant_scope import bind_conn_to_tenant

from dataclasses import replace
from datetime import datetime
import logging
import math
from typing import Any, Protocol

from boltrig.models import (
    BACKGROUND_JOB_MAX_INTERVAL_SECONDS,
    BACKGROUND_JOB_MAX_ITEM_COUNT,
    BACKGROUND_JOB_MAX_RETURNED_RECEIPTS,
    BACKGROUND_JOB_NAMES,
    BACKGROUND_JOB_RECEIPTS_PER_JOB,
    BackgroundJobReceipt,
)


def _normalise_attempt(
    *,
    tenant_id: str,
    job_name: str,
    process_instance_identity: str,
    interval_seconds: float,
    attempted_at: datetime,
    succeeded: bool,
    item_count: int,
) -> tuple[int, int]:
    if not tenant_id.strip() or job_name not in BACKGROUND_JOB_NAMES:
        raise ValueError("invalid background job attempt identity")
    if attempted_at.tzinfo is None:
        raise ValueError("background job attempt timestamp must be timezone-aware")
    if not math.isfinite(interval_seconds):
        raise ValueError("background job interval must be finite")
    interval = max(1, min(round(interval_seconds), BACKGROUND_JOB_MAX_INTERVAL_SECONDS))
    count = max(0, min(int(item_count), BACKGROUND_JOB_MAX_ITEM_COUNT))
    # Reuse the model's opaque-identity and lifecycle validation.
    BackgroundJobReceipt(
        tenant_id=tenant_id,
        job_name=job_name,
        process_instance_identity=process_instance_identity,
        interval_seconds=interval,
        last_attempt_at=attempted_at,
        last_success_at=attempted_at if succeeded else None,
        last_failure_at=None if succeeded else attempted_at,
        last_outcome="succeeded" if succeeded else "failed",
        failure_code=None if succeeded else "sweep_failed",
        last_item_count=count,
    )
    return interval, count


def _merged_receipt(
    existing: BackgroundJobReceipt | None,
    *,
    tenant_id: str,
    job_name: str,
    process_instance_identity: str,
    interval_seconds: int,
    attempted_at: datetime,
    succeeded: bool,
    item_count: int,
) -> BackgroundJobReceipt:
    return BackgroundJobReceipt(
        tenant_id=tenant_id,
        job_name=job_name,
        process_instance_identity=process_instance_identity,
        interval_seconds=interval_seconds,
        last_attempt_at=attempted_at,
        last_success_at=(
            attempted_at
            if succeeded
            else existing.last_success_at if existing is not None else None
        ),
        last_failure_at=(
            existing.last_failure_at
            if succeeded and existing is not None
            else None if succeeded else attempted_at
        ),
        last_outcome="succeeded" if succeeded else "failed",
        failure_code=None if succeeded else "sweep_failed",
        last_item_count=item_count,
    )


_log = logging.getLogger("boltrig.store.background_jobs")


def _receipts_skipping_unknown(rows: Any) -> list[BackgroundJobReceipt]:
    """Map rows to receipts, DROPPING any whose job_name this build does not know.

    BackgroundJobReceipt validates job_name against BACKGROUND_JOB_NAMES, so a row
    written by a NEWER process raised ValueError here and took the ENTIRE read down
    - readiness then reported `attempt_evidence_unavailable` for every job,
    including ones that were perfectly healthy.

    Measured on the beelink 2026-07-30: registering `distillation` and rolling only
    the fleet image left the kernel unable to read ANY receipt. Adding a job name
    was therefore not a backward-compatible change, and during any rolling deploy
    with mixed versions the whole readiness surface went dark.

    Dropping the row costs visibility of ONE job on an old build, which is the
    correct trade against losing all of them. It is logged, not silent - an
    unrecognised name is either a rollout in progress or a downgrade, and both are
    worth saying out loud.
    """
    out: list[BackgroundJobReceipt] = []
    for row in rows:
        try:
            receipt = _receipt(row)
        except ValueError:
            _log.warning(
                "background job receipt for unknown job=%r skipped; this build "
                "knows %s (older process reading a newer row?)",
                row["job_name"],
                list(BACKGROUND_JOB_NAMES),
            )
            continue
        if receipt is not None:
            out.append(receipt)
    return out


def _receipt(row: Any) -> BackgroundJobReceipt | None:
    if row is None:
        return None
    return BackgroundJobReceipt(
        tenant_id=row["tenant_id"],
        job_name=row["job_name"],
        process_instance_identity=row["process_instance_identity"],
        interval_seconds=row["interval_seconds"],
        last_attempt_at=row["last_attempt_at"],
        last_success_at=row["last_success_at"],
        last_failure_at=row["last_failure_at"],
        last_outcome=row["last_outcome"],
        failure_code=row["failure_code"],
        last_item_count=row["last_item_count"],
        receipt_kind=row["receipt_kind"],
    )


_UPSERT_ATTEMPT_SQL = """INSERT INTO background_job_receipts
  (tenant_id,job_name,process_instance_identity,interval_seconds,last_attempt_at,
   last_success_at,last_failure_at,last_outcome,failure_code,last_item_count)
VALUES (
  $1,$2,$3,$4,$5,CASE WHEN $6::boolean THEN $5::timestamptz ELSE NULL END,
  CASE WHEN $6::boolean THEN NULL ELSE $5::timestamptz END,$7,$8,$9
)
ON CONFLICT (tenant_id,job_name,process_instance_identity) DO UPDATE SET
  interval_seconds=EXCLUDED.interval_seconds,
  last_attempt_at=EXCLUDED.last_attempt_at,
  last_success_at=CASE WHEN EXCLUDED.last_outcome='succeeded'
    THEN EXCLUDED.last_attempt_at ELSE background_job_receipts.last_success_at END,
  last_failure_at=CASE WHEN EXCLUDED.last_outcome='failed'
    THEN EXCLUDED.last_attempt_at ELSE background_job_receipts.last_failure_at END,
  last_outcome=EXCLUDED.last_outcome,
  failure_code=EXCLUDED.failure_code,
  last_item_count=EXCLUDED.last_item_count
WHERE background_job_receipts.last_attempt_at <= EXCLUDED.last_attempt_at
RETURNING *"""

_PRUNE_ATTEMPT_SQL = """DELETE FROM background_job_receipts
WHERE tenant_id=$1 AND job_name=$2 AND process_instance_identity IN (
  SELECT process_instance_identity FROM background_job_receipts
  WHERE tenant_id=$1 AND job_name=$2
  ORDER BY last_attempt_at DESC,process_instance_identity DESC OFFSET $3
)"""


class BackgroundJobStoreContract(Protocol):
    async def record_background_job_attempt(
        self,
        *,
        tenant_id: str,
        job_name: str,
        process_instance_identity: str,
        interval_seconds: float,
        attempted_at: datetime,
        succeeded: bool,
        item_count: int,
    ) -> BackgroundJobReceipt: ...

    async def list_background_job_receipts(
        self, tenant_id: str
    ) -> list[BackgroundJobReceipt]: ...


class BackgroundJobStoreMem:
    def _init_background_job_state(self) -> None:
        self._background_job_receipts: dict[
            tuple[str, str, str], BackgroundJobReceipt
        ] = {}

    async def record_background_job_attempt(
        self,
        *,
        tenant_id,
        job_name,
        process_instance_identity,
        interval_seconds,
        attempted_at,
        succeeded,
        item_count,
    ):
        interval, count = _normalise_attempt(
            tenant_id=tenant_id,
            job_name=job_name,
            process_instance_identity=process_instance_identity,
            interval_seconds=interval_seconds,
            attempted_at=attempted_at,
            succeeded=succeeded,
            item_count=item_count,
        )
        key = (tenant_id, job_name, process_instance_identity)
        existing = self._background_job_receipts.get(key)
        if existing is not None and existing.last_attempt_at > attempted_at:
            return replace(existing)
        receipt = _merged_receipt(
            existing,
            tenant_id=tenant_id,
            job_name=job_name,
            process_instance_identity=process_instance_identity,
            interval_seconds=interval,
            attempted_at=attempted_at,
            succeeded=succeeded,
            item_count=count,
        )
        self._background_job_receipts[key] = receipt
        retained = sorted(
            (
                row
                for row in self._background_job_receipts.values()
                if row.tenant_id == tenant_id and row.job_name == job_name
            ),
            key=lambda row: (row.last_attempt_at, row.process_instance_identity),
            reverse=True,
        )
        for expired in retained[BACKGROUND_JOB_RECEIPTS_PER_JOB:]:
            del self._background_job_receipts[
                (
                    expired.tenant_id,
                    expired.job_name,
                    expired.process_instance_identity,
                )
            ]
        return replace(receipt)

    async def list_background_job_receipts(self, tenant_id):
        rows = [
            replace(receipt)
            for (row_tenant, _, _), receipt in self._background_job_receipts.items()
            if row_tenant == tenant_id
        ]
        rows.sort(
            key=lambda row: (
                row.job_name,
                -row.last_attempt_at.timestamp(),
                row.process_instance_identity,
            )
        )
        return rows[:BACKGROUND_JOB_MAX_RETURNED_RECEIPTS]


class BackgroundJobStorePG:
    async def record_background_job_attempt(
        self,
        *,
        tenant_id,
        job_name,
        process_instance_identity,
        interval_seconds,
        attempted_at,
        succeeded,
        item_count,
    ):
        interval, count = _normalise_attempt(
            tenant_id=tenant_id,
            job_name=job_name,
            process_instance_identity=process_instance_identity,
            interval_seconds=interval_seconds,
            attempted_at=attempted_at,
            succeeded=succeeded,
            item_count=item_count,
        )
        outcome = "succeeded" if succeeded else "failed"
        failure_code = None if succeeded else "sweep_failed"
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await bind_conn_to_tenant(conn, tenant_id, pool=self._pool)
                await conn.execute(
                    """SELECT pg_advisory_xact_lock(
                         hashtext($1), hashtext($2)
                       )""",
                    tenant_id,
                    job_name,
                )
                row = await conn.fetchrow(
                    _UPSERT_ATTEMPT_SQL,
                    tenant_id,
                    job_name,
                    process_instance_identity,
                    interval,
                    attempted_at,
                    succeeded,
                    outcome,
                    failure_code,
                    count,
                )
                if row is None:
                    row = await conn.fetchrow(
                        """SELECT * FROM background_job_receipts
                           WHERE tenant_id=$1 AND job_name=$2
                             AND process_instance_identity=$3""",
                        tenant_id,
                        job_name,
                        process_instance_identity,
                    )
                await conn.execute(
                    _PRUNE_ATTEMPT_SQL,
                    tenant_id,
                    job_name,
                    BACKGROUND_JOB_RECEIPTS_PER_JOB,
                )
                receipt = _receipt(row)
                assert receipt is not None
                return receipt

    async def list_background_job_receipts(self, tenant_id):
        # /readyz has no caller principal by design, so there is no request
        # contextvar for _RlsPool to bind. The configured readiness tenant is
        # trusted composition input and is bound explicitly here.
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await bind_conn_to_tenant(conn, tenant_id, pool=self._pool)
                rows = await conn.fetch(
                    """SELECT * FROM background_job_receipts
                       WHERE tenant_id=$1
                       ORDER BY job_name,last_attempt_at DESC,
                                process_instance_identity DESC
                       LIMIT $2""",
                    tenant_id,
                    BACKGROUND_JOB_MAX_RETURNED_RECEIPTS,
                )
        return _receipts_skipping_unknown(rows)


__all__ = [
    "BackgroundJobStoreContract",
    "BackgroundJobStoreMem",
    "BackgroundJobStorePG",
]
