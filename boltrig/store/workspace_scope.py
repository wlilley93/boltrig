"""Shared WorkItem workspace predicates for durable and in-memory stores."""

from __future__ import annotations

from typing import Any


def work_item_workspace_visible(
    item: Any, workspace_id: str | None, enforce_workspace: bool
) -> bool:
    """Distinguish trusted unfiltered reads from external org-wide-only reads."""
    if not enforce_workspace:
        return True
    return item.workspace_id is None or item.workspace_id == workspace_id


def append_work_workspace_clause(
    clauses: list[str],
    args: list[Any],
    workspace_id: str | None,
    enforce_workspace: bool,
) -> None:
    """Append the SQL equivalent of :func:`work_item_workspace_visible`."""
    if not enforce_workspace:
        return
    if workspace_id is None:
        clauses.append("workspace_id IS NULL")
        return
    args.append(workspace_id)
    clauses.append(f"(workspace_id IS NULL OR workspace_id=${len(args)})")
