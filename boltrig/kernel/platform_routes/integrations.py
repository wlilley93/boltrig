"""Reviewed integration catalogue and tenant connection projections."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from boltrig.models.base import utcnow

from boltrig.kernel.control_routes import dispatch_control_route

from ._shared import require_author
from .integration_setup import public_secret_contract, register_integration_setup


async def _enabled_tools(kernel, tenant_id: str, adapter_id: str) -> list[str]:
    enabled: list[str] = []
    for verb in await kernel.store.list_verbs(tenant_id):
        binding = await kernel.store.get_binding(tenant_id, verb.id)
        if binding is not None and binding.target_ref == adapter_id:
            enabled.append(verb.id)
    return sorted(enabled)


async def _enabled_capabilities(kernel, tenant_id: str, adapter_id: str) -> list[str]:
    """The canonical capabilities this connection actually serves.

    ``enabled_tools`` above counts raw verb ids bound to the adapter - the
    SOURCE OPERATIONS. Once a capability layer exists that stops being the
    honest answer to "what can this connection do": two connections can serve
    one capability, and a provider-prefixed verb id is not what the model ever
    sees (SPEC §11.1 site 6). Only APPROVED bindings count, so a proposed
    mapping is invisible here exactly as it is invisible to routing.
    """
    connection_ids = {
        connection.id
        for connection in await kernel.store.list_provider_connections(tenant_id)
        if connection.adapter_id == adapter_id
    }
    if not connection_ids:
        return []
    return sorted(
        {
            binding.ref
            for binding in await kernel.store.list_capability_bindings(tenant_id)
            if binding.connection_id in connection_ids and binding.status == "approved"
        }
    )


async def _catalogue_view(kernel, tenant_id: str, item) -> dict:
    adapter = (
        await kernel.store.get_adapter(tenant_id, item.adapter_id)
        if item.adapter_id
        else None
    )
    health = (
        kernel.loader.health_of(tenant_id, item.adapter_id)
        if item.adapter_id
        else "unknown"
    )
    available = bool(
        item.certification == "certified"
        and adapter is not None
        and adapter.activated
        and health in {"ok", "degraded"}
    )
    if item.certification != "certified":
        reason = "not_certified"
    elif adapter is None:
        reason = "adapter_not_registered"
    elif not adapter.activated:
        reason = "adapter_not_activated"
    elif health not in {"ok", "degraded"}:
        reason = "adapter_health_unverified" if health == "unknown" else "adapter_down"
    else:
        reason = None
    return {
        "id": item.id,
        "label": item.label,
        "category": item.category,
        "transport": item.transport,
        "auth": list(item.auth),
        "description": item.description,
        "certification": item.certification,
        "setup_copy": item.setup_copy,
        "access_copy": item.access_copy,
        "available": available,
        "availability_reason": reason,
        "setup_supported": bool(available and item.secret_contract is not None),
        "setup_contract": (
            public_secret_contract(item.secret_contract)
            if available
            else None
        ),
        "enabled_tools": (
            await _enabled_tools(kernel, tenant_id, item.adapter_id)
            if item.adapter_id
            else []
        ),
    }


async def _connection_view(kernel, tenant_id: str, connection) -> dict:
    revoked = connection.health == "revoked"
    enabled = (
        [] if revoked else await _enabled_tools(kernel, tenant_id, connection.adapter_id)
    )
    capabilities = (
        []
        if revoked
        else await _enabled_capabilities(kernel, tenant_id, connection.adapter_id)
    )
    accounts = [
        {
            "id": str(account.get("id") or "")[:200],
            "label": str(account.get("label") or "")[:200],
            "selected": bool(account.get("selected")),
        }
        for account in connection.accounts[:100]
        if isinstance(account, dict)
    ]
    return {
        "id": connection.id,
        "integration_id": connection.integration_id,
        "label": connection.label,
        "health": connection.health,
        "credential_ref_present": bool(connection.credential_ref),
        "accounts": accounts,
        "enabled_tools": enabled,
        "enabled_capabilities": capabilities,
        "last_checked_at": (
            connection.last_checked_at.isoformat()
            if connection.last_checked_at
            else None
        ),
        "created_at": connection.created_at.isoformat(),
    }


def _register_reads(app, P, K) -> None:
    @app.get("/v1/integrations/catalogue")
    async def catalogue(k=K, p=P) -> dict:
        k.loader.health_snapshot()
        items = await k.store.list_integration_catalogue(p.tenant_id)
        return {
            "integrations": [
                await _catalogue_view(k, p.tenant_id, item) for item in items
            ]
        }

    @app.get("/v1/integrations/connections")
    async def connections(k=K, p=P) -> dict:
        rows = await k.store.list_integration_connections(p.tenant_id)
        return {
            "connections": [
                await _connection_view(k, p.tenant_id, row) for row in rows
            ]
        }


def _register_connection_lifecycle(app, P, K) -> None:
    @app.get("/v1/integrations/connections/{connection_id}/health")
    async def connection_health(connection_id: str, k=K, p=P) -> JSONResponse:
        connection = await k.store.get_integration_connection(
            p.tenant_id, connection_id
        )
        if connection is None:
            return JSONResponse({"status": "error", "reason": "not_found"}, status_code=404)
        if connection.health != "revoked":
            await k.loader.refresh_health()
            record = await k.store.get_adapter(p.tenant_id, connection.adapter_id)
            health = (
                k.loader.health_of(p.tenant_id, connection.adapter_id)
                if record is not None and record.activated
                else "down"
            )
            checked_at = utcnow()
            connection = await k.store.update_integration_connection_health_if_active(
                p.tenant_id,
                connection_id,
                health if health in {"ok", "degraded", "down"} else "pending",
                checked_at,
            )
            if connection is None:
                connection = await k.store.get_integration_connection(
                    p.tenant_id, connection_id
                )
                if connection is None:
                    return JSONResponse(
                        {"status": "error", "reason": "not_found"}, status_code=404
                    )
        return JSONResponse({
            "connection": await _connection_view(k, p.tenant_id, connection)
        })

    @app.delete("/v1/integrations/connections/{connection_id}")
    async def revoke_connection(
        connection_id: str, request: Request, k=K, p=P
    ) -> JSONResponse:
        require_author(p)
        output, pending = await dispatch_control_route(
            k,
            p,
            "control.integration.revoke",
            {"connection_id": connection_id},
            request=request,
        )
        if pending is not None:
            return pending
        return JSONResponse({"status": "revoked", **(output or {})})


def register(app, P, K) -> None:
    _register_reads(app, P, K)
    register_integration_setup(app, P, K, connection_view=_connection_view)
    _register_connection_lifecycle(app, P, K)
