"""Fail-safe workflow lifecycle projections for the run event relay."""

from __future__ import annotations

from typing import Any


def emit_terminal(
    relay: Any,
    tenant_id: str,
    run_id: str | None,
    workflow_id: str,
    status: str,
) -> None:
    """Publish the terminal workflow marker without affecting execution."""
    if relay is None or not run_id:
        return
    try:
        relay.publish(
            tenant_id,
            run_id,
            {
                "type": "workflow_run",
                "run_id": run_id,
                "workflow_id": workflow_id,
                "status": status,
            },
        )
    except Exception:
        pass
