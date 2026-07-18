"""Fail-closed reconciliation for ambiguous run-grant issue outcomes."""

from __future__ import annotations

import asyncio
from datetime import datetime

from boltrig.fleet.domain.grant_lease import (
    GrantLeaseCandidate,
    GrantLeaseConflict,
    StoredGrantLease,
)
from boltrig.fleet.ports.grant_leases import GrantLeaseStore


async def reconcile_issue_receipt(
    store: GrantLeaseStore,
    candidate: GrantLeaseCandidate,
) -> StoredGrantLease | None:
    """Resolve only an exact durable operation receipt for this candidate."""

    receipt = await store.get_by_issue_operation_id(
        candidate.issue_operation_id,
        candidate.binding,
    )
    if receipt is None or not receipt.is_projection_of(candidate):
        return None
    return receipt


async def cleanup_committed_issue(
    store: GrantLeaseStore,
    store_task: asyncio.Task[StoredGrantLease],
    candidate: GrantLeaseCandidate,
    *,
    now: datetime,
    reason: str,
) -> None:
    """Revoke an exact commit after cancellation or failed bearer handoff."""

    stored: StoredGrantLease | None
    try:
        stored = await asyncio.shield(store_task)
    except (Exception, asyncio.CancelledError):
        stored = await reconcile_issue_receipt(store, candidate)
    if stored is None or not stored.is_projection_of(candidate):
        return
    await store.revoke_exact(
        stored.lease_id,
        stored.binding,
        now=now,
        reason=reason,
    )


async def finish_issue_cleanup(cleanup: asyncio.Task[None]) -> None:
    """Retain and observe exact cleanup despite repeated caller cancellation."""

    while True:
        try:
            await asyncio.shield(cleanup)
            return
        except asyncio.CancelledError:
            if cleanup.cancelled():
                raise GrantLeaseConflict("grant issue cleanup was cancelled") from None


__all__ = [
    "cleanup_committed_issue",
    "finish_issue_cleanup",
    "reconcile_issue_receipt",
]
