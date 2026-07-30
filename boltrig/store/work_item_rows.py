"""Shared WorkItem detachment and PostgreSQL row decoding."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from boltrig.models import WorkItem, WorkStatus


def detached_work_item(item):
    """Return a caller-owned shallow copy of a stored in-memory work item."""
    return replace(item) if item is not None else None


def work_item_from_row(row: Any) -> WorkItem | None:
    if row is None:
        return None
    return WorkItem(
        id=row["id"],
        tenant_id=row["tenant_id"],
        workspace_id=row["workspace_id"],
        source=row["source"],
        intent=row["intent"],
        confidence=row["confidence"],
        convergent=row["convergent"],
        status=WorkStatus(row["status"]),
        source_id=row["source_id"],
        owner_member=row["owner_member"],
        parent_id=row["parent_id"],
        hatchet_run_id=row["hatchet_run_id"],
        depth=row["depth"],
        on_behalf_of=row["on_behalf_of"],
        constraints=row["constraints"] or {},
        raw=row["raw"] or {},
        attempts=row["attempts"],
        degraded=row["degraded"],
        result=row["result"],
        lease_owner=row["lease_owner"],
        lease_expires_at=row["lease_expires_at"],
        target=row["target"],
        reply_route=row["reply_route"],
    )
