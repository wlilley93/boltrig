"""Persist bounded, authority-inheriting follow-on work from a fleet result."""

from __future__ import annotations

import logging
from typing import Any

from boltrig.kernel.work_authority import inherit_work_authority
from boltrig.models import WorkItem
from boltrig.work import normalise

log = logging.getLogger("boltrig.fleet.work_follow_ons")


async def persist_new_work_items(
    store: Any, parent: WorkItem, new_items: list[Any] | None, *, source: str
) -> list[WorkItem]:
    """Persist a step's discovered follow-on work as pending children.

    The existing-intent check narrows the common duplicate-child window but is
    not a concurrency fence: closing the two-reader race needs a database
    uniqueness constraint on ``(parent_id, intent)``. Every accepted child
    inherits the parent's server-stamped authority ceilings; model/source fields
    can never replace those reserved values.
    """
    created: list[WorkItem] = []
    existing: set[str] = set()
    if new_items:
        try:
            siblings = await store.list_work_items(parent.tenant_id, parent_id=parent.id)
            existing = {sibling.intent for sibling in siblings}
        except Exception:  # best effort: a sibling read never blocks the follow-on
            log.warning("could not read existing children of %s", parent.id, exc_info=True)
    for raw in new_items or []:
        payload = dict(raw) if isinstance(raw, dict) else {"intent": str(raw)}
        child = normalise(payload, source, parent.tenant_id)
        if child.intent in existing:
            log.info(
                "skipping follow-on %r for %s: a child with that intent already exists",
                child.intent,
                parent.id,
            )
            continue
        child.parent_id = parent.id
        child.depth = parent.depth + 1
        child.on_behalf_of, child.workspace_id = parent.on_behalf_of, parent.workspace_id
        inherit_work_authority(parent, child)
        await store.create_work_item(child)
        existing.add(child.intent)
        created.append(child)
    return created


__all__ = ["persist_new_work_items"]
