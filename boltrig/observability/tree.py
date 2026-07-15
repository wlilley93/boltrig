"""Execution-tree reconstruction (US-OBS-02).

Given a root ``run_id``, follow parent links in the audit log to render the tree
of agents, children, and workflows with per-node status and aggregated cost.
The audit log is the single source (every action wrote one row), so the tree is
reconstructable after the fact even for crashed runs.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from boltrig.models import AuditEvent
from boltrig.store import Store


def tree_from_events(
    events: Iterable[AuditEvent], root_run_id: str
) -> dict[str, Any]:
    """Build a tree exclusively from the caller-authorized event slice."""
    # group events by run, and record each run's parent
    runs: dict[str, dict[str, Any]] = {}
    children: dict[str, list[str]] = {}
    for e in events:
        if e.run_id is None:
            continue
        node = runs.setdefault(
            e.run_id,
            {
                "run_id": e.run_id,
                "parent_run_id": e.parent_run_id,
                "actor": e.actor,
                "tier": e.actor_tier,
                "depth": e.depth,
                "actions": 0,
                "cost_micros": 0,
                "tokens": 0,
                "statuses": {},
            },
        )
        node["actions"] += 1
        node["cost_micros"] += e.cost_micros or 0
        node["tokens"] += e.tokens_used or 0
        node["statuses"][e.status] = node["statuses"].get(e.status, 0) + 1
        if e.parent_run_id:
            children.setdefault(e.parent_run_id, [])
            if e.run_id not in children[e.parent_run_id]:
                children[e.parent_run_id].append(e.run_id)

    def assemble(run_id: str, path: frozenset[str] = frozenset()) -> dict[str, Any]:
        if run_id in path:
            return {
                "run_id": run_id,
                "actions": 0,
                "children": [],
                "total_cost_micros": 0,
                "degraded": "cycle",
            }
        if len(path) >= 256:
            return {
                "run_id": run_id,
                "actions": 0,
                "children": [],
                "total_cost_micros": 0,
                "degraded": "depth_limit",
            }
        node = dict(runs.get(run_id, {"run_id": run_id, "actions": 0}))
        branch = path | {run_id}
        node["children"] = [assemble(c, branch) for c in children.get(run_id, [])]
        node["total_cost_micros"] = node.get("cost_micros", 0) + sum(
            c["total_cost_micros"] for c in node["children"]
        )
        return node

    return {"root": assemble(root_run_id)}


async def build_tree(
    store: Store, tenant_id: str, root_run_id: str
) -> dict[str, Any]:
    """Backward-compatible unscoped builder for trusted in-process callers."""
    events = await store.audit_query(tenant_id, limit=10_000)
    return tree_from_events(events, root_run_id)
