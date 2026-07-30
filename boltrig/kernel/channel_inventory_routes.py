"""Author-scoped channel inventory and delivery evidence."""

from __future__ import annotations

from fastapi import Depends
from fastapi.responses import JSONResponse

from boltrig.config.control_channel_ops import channel_delivery_view
from boltrig.config.channel_addressing import (
    channel_addressing_catalogue,
    project_channel_addressing,
)
from boltrig.identity.rbac import can_author, departments_for
from boltrig.models import utcnow
from boltrig.models.channel_providers import (
    credential_presence,
    provider_public_descriptor,
)

from .channel_gateway_specs import channel_desired_revision


async def list_channels(kernel, principal) -> JSONResponse:
    if not can_author(principal.role):
        return _admin_denied()
    observations = {
        row.channel_id: row
        for row in await kernel.store.list_channel_gateway_statuses(
            principal.tenant_id
        )
    }
    leases = {
        row.channel_id: row
        for row in await kernel.store.list_channel_gateway_leases(
            principal.tenant_id
        )
    }
    catalogue = await channel_addressing_catalogue(
        kernel.store,
        principal.tenant_id,
        principal.active_workspace_id,
        allowed_departments=departments_for(principal.role, principal.scope),
    )
    rows = []
    for channel in await kernel.store.list_channels(principal.tenant_id):
        credentials = (
            await kernel.store.get_credential_ref(
                principal.tenant_id, channel.credential_ref
            )
            if channel.credential_ref
            else None
        )
        rows.append(
            _channel_view(
                channel,
                credentials,
                observations.get(channel.id),
                leases.get(channel.id),
                catalogue,
            )
        )
    return JSONResponse(
        {"channels": rows, "addressing_catalogue": catalogue}
    )


def _channel_view(channel, credentials, observed, lease, catalogue) -> dict:
    configured = credential_presence(channel.platform, credentials)
    desired = (
        channel_desired_revision(channel, credentials)
        if channel.transport == "socket"
        else None
    )
    converged = bool(
        observed and desired and observed.observed_revision == desired
    )
    return {
        "id": channel.id,
        "platform": channel.platform,
        "name": channel.name,
        "transport": channel.transport,
        "enabled": channel.enabled,
        "unpaired_behavior": channel.unpaired_behavior,
        "config": channel.config,
        "addressing": project_channel_addressing(channel.config, catalogue),
        "credential_configured": all(configured.values()),
        "credentials_configured": configured,
        "provider": provider_public_descriptor(channel.platform),
        "gateway": _gateway_view(
            channel, observed, lease, desired, converged
        ),
    }


def _gateway_view(channel, observed, lease, desired, converged: bool) -> dict:
    ownership = _ownership_view(channel, lease)
    if observed is None:
        applies = channel.enabled and channel.transport == "socket"
        return {
            "status": "awaiting_gateway" if applies else "not_applicable",
            "reason_code": (
                "gateway_token_scope_or_heartbeat_required"
                if applies
                else None
            ),
            "ownership": ownership,
        }
    return {
        "status": observed.status if converged else "awaiting_gateway",
        "gateway_id": observed.gateway_id,
        "desired_revision": desired,
        "observed_revision": observed.observed_revision,
        "reason_code": (
            observed.reason_code if converged else "desired_state_changed"
        ),
        "observed_at": (
            observed.observed_at.isoformat()
            if observed.observed_at
            else None
        ),
        "ownership": ownership,
    }


def _ownership_view(channel, lease) -> dict:
    if lease is not None and channel.transport == "socket":
        return {
            "status": (
                "active_lease"
                if lease.lease_expires_at > utcnow()
                else "expired_lease"
            ),
            "gateway_id": lease.gateway_id,
            "lease_expires_at": lease.lease_expires_at.isoformat(),
            "single_owner_enforced": True,
            "owner_lease_id_disclosed": False,
            "proves_process_liveness": False,
        }
    applies = channel.transport == "socket"
    return {
        "status": "unclaimed" if applies and channel.enabled else "not_applicable",
        "gateway_id": None,
        "lease_expires_at": None,
        "single_owner_enforced": applies,
        "owner_lease_id_disclosed": False,
        "proves_process_liveness": False,
    }


async def list_channel_deliveries(
    channel_id: str, limit: int, kernel, principal
) -> JSONResponse:
    if not can_author(principal.role):
        return _admin_denied()
    channel = await kernel.store.get_channel(
        principal.tenant_id, channel_id
    )
    if channel is None:
        return JSONResponse(
            {"status": "error", "reason": "not_found"}, status_code=404
        )
    receipts = await kernel.store.list_channel_delivery_receipts(
        principal.tenant_id, channel_id, limit
    )
    return JSONResponse(
        {"deliveries": [channel_delivery_view(row) for row in receipts]}
    )


def _admin_denied() -> JSONResponse:
    return JSONResponse(
        {"status": "denied", "reason": "admin only"}, status_code=403
    )


def register_channel_inventory_routes(
    app, *, principal_dep, get_kernel
) -> None:
    principal = Depends(principal_dep)
    kernel = Depends(get_kernel)

    async def list_endpoint(k=kernel, p=principal):
        return await list_channels(k, p)

    async def deliveries_endpoint(
        channel_id: str, limit: int = 50, k=kernel, p=principal
    ):
        return await list_channel_deliveries(channel_id, limit, k, p)

    app.add_api_route(
        "/v1/channels",
        list_endpoint,
        methods=["GET"],
        name="list_channels",
    )
    app.add_api_route(
        "/v1/channels/{channel_id}/deliveries",
        deliveries_endpoint,
        methods=["GET"],
        name="list_channel_deliveries",
    )


__all__ = ["register_channel_inventory_routes"]
