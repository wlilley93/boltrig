"""Shared workspace-scope predicates for durable and in-memory stores.

Two consumers, one predicate. A workspace-scoped row is visible to a caller
operating inside a workspace when it is org-wide (``workspace_id IS NULL``) or
belongs to that workspace; ``enforce_workspace=False`` is the trusted unfiltered
read an internal caller uses. The helpers were named ``work_item_*`` while
WorkItem was the only consumer; agent capability profiles now share them, and a
second copy of this rule is how the two scopes drift apart.

Deactivation and other EXACT-scope operations must NOT call
`workspace_scope_visible` or `append_workspace_scope_clause`: the union
predicate would let an org-scoped reconcile reach into a workspace's rows. Match
the scope exactly (``IS NOT DISTINCT FROM``) for those.
"""

from __future__ import annotations

from typing import Any


def workspace_scope_visible(
    item: Any, workspace_id: str | None, enforce_workspace: bool
) -> bool:
    """Distinguish trusted unfiltered reads from external org-wide-only reads."""
    if not enforce_workspace:
        return True
    return item.workspace_id is None or item.workspace_id == workspace_id


def append_workspace_scope_clause(
    clauses: list[str],
    args: list[Any],
    workspace_id: str | None,
    enforce_workspace: bool,
) -> None:
    """Append the SQL equivalent of :func:`workspace_scope_visible`."""
    if not enforce_workspace:
        return
    if workspace_id is None:
        clauses.append("workspace_id IS NULL")
        return
    args.append(workspace_id)
    clauses.append(f"(workspace_id IS NULL OR workspace_id=${len(args)})")
