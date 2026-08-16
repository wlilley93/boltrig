"""Durable, narrowing-only authority ceilings carried by Work items."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from boltrig.models import GrantSet, WorkItem

CHANNEL_THREAD_CEILING_KEY = "_channel_thread_ceiling"
CREATOR_GRANT_CEILING_KEY = "_creator_grant_ceiling"
_PROPAGATED_KEYS = (CHANNEL_THREAD_CEILING_KEY, CREATOR_GRANT_CEILING_KEY)


def _grant_document(grants: GrantSet) -> dict[str, list[str]]:
    if type(grants) is not GrantSet:
        raise TypeError("a work authority ceiling must be an exact GrantSet")
    return {"allow": list(grants.allow), "deny": list(grants.deny)}


def _grant_list(value: Any) -> list[str] | None:
    if type(value) is not list or any(type(item) is not str for item in value):
        return None
    return list(value)


def _read_grants(value: Any) -> GrantSet:
    if type(value) is not dict:
        return GrantSet.of([])
    allow = _grant_list(value.get("allow"))
    deny = _grant_list(value.get("deny"))
    if allow is None or deny is None:
        return GrantSet.of([])
    try:
        return GrantSet.of(allow, deny)
    except (TypeError, ValueError):
        return GrantSet.of([])


def stamp_creator_ceiling(item: WorkItem, grants: GrantSet) -> None:
    """Bind new queued work to no more than its creator held at creation time."""

    item.constraints[CREATOR_GRANT_CEILING_KEY] = _grant_document(grants)


def creator_ceiling_from_item(item: WorkItem) -> GrantSet | None:
    raw = (item.constraints or {}).get(CREATOR_GRANT_CEILING_KEY)
    return None if raw is None else _read_grants(raw)


def inherit_work_authority(parent: WorkItem, child: WorkItem) -> None:
    """Replace model/source-provided reserved values with the parent's ceilings."""

    for key in _PROPAGATED_KEYS:
        child.constraints.pop(key, None)
        if key in (parent.constraints or {}):
            child.constraints[key] = deepcopy(parent.constraints[key])


__all__ = [
    "CHANNEL_THREAD_CEILING_KEY",
    "CREATOR_GRANT_CEILING_KEY",
    "creator_ceiling_from_item",
    "inherit_work_authority",
    "stamp_creator_ceiling",
]
