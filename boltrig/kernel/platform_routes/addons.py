"""Authenticated runtime add-on inventory."""

from __future__ import annotations

from fastapi import Request

from boltrig.kernel.addon_inventory import addon_inventory

from ._shared import platform_state


def register(app, P, K) -> None:
    @app.get("/v1/addons")
    async def addons(request: Request, k=K, p=P) -> dict[str, object]:
        return await addon_inventory(
            k,
            tenant_id=p.tenant_id,
            workspace_id=p.active_workspace_id,
            status_provider=platform_state(request).get("status"),
        )
